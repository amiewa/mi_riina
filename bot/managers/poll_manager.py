"""アンケート機能マネージャー

tl_word / static / ai の3モードでアンケートを投稿する。
"""

import asyncio
import json
import logging
import random
import sqlite3
from datetime import datetime, timedelta

from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from bot.core.ai_client import AIClientBase
from bot.core.config import AppConfig
from bot.core.database import Database
from bot.core.misskey_client import MisskeyClient, filter_notes
from bot.core.models import NoteEvent
from bot.utils.ng_word_manager import NGWordManager
from bot.utils.night_mode import is_night_mode
from bot.utils.serif_loader import SerifLoader
from bot.utils.text_cleaner import clean_note_text
from bot.utils.tokenizer import TokenizerBase

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")


class PollAIResponse(BaseModel):
    """AI モードのレスポンスバリデーション"""

    question: str = Field(min_length=1)
    choices: list[str]

    @field_validator("choices")
    @classmethod
    def validate_choices(cls, v: list[str]) -> list[str]:
        if len(v) != 4:
            raise ValueError("choices must be exactly 4")
        if any(not c.strip() for c in v):
            raise ValueError("empty choice found")
        if len(set(v)) != len(v):
            raise ValueError("duplicate choices found")
        if any(len(c) > 50 for c in v):
            raise ValueError("choice too long (max 50 chars)")
        return v


class PollManager:
    """アンケートマネージャー"""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        misskey: MisskeyClient,
        ai_client: AIClientBase,
        tokenizer: TokenizerBase,
        ng_word_manager: NGWordManager,
        serif_loader: SerifLoader,
    ) -> None:
        self._config = config
        self._db = db
        self._misskey = misskey
        self._ai = ai_client
        self._tokenizer = tokenizer
        self._ng_word = ng_word_manager
        self._serif_loader = serif_loader

    async def execute_poll(self) -> None:
        """アンケートを投稿する。"""
        poll_config = self._config.posting.poll

        if not poll_config.enabled:
            return

        # 夜間モード判定
        night = self._config.posting.night_mode
        if is_night_mode(night.start_hour, night.end_hour, night.enabled, self._config.bot.timezone):
            return

        # 確率判定
        if random.random() > poll_config.probability:
            return

        # クールダウン
        cooldown = self._config.posting.cooldown_minutes
        if cooldown > 0:
            last_time = await self._db.get_last_auto_post_time()
            if last_time:
                last_dt = datetime.fromisoformat(last_time)
                if datetime.now(JST) - last_dt < timedelta(minutes=cooldown):
                    return

        # execution_key
        now = datetime.now(JST)
        execution_key = f"poll:{now.strftime('%Y-%m-%dT%H:00')}"

        # 自動削除
        auto_delete = self._config.posting.auto_delete.poll
        scheduled_delete_at = None
        if auto_delete.enabled:
            delete_time = now + timedelta(hours=auto_delete.after_hours)
            scheduled_delete_at = delete_time.isoformat()

        # モード別処理
        mode = poll_config.mode
        if mode == "tl_word":
            result = await self._generate_tl_word_poll()
        elif mode == "static":
            result = self._generate_static_poll()
        elif mode == "ai":
            result = await self._generate_ai_poll()
        else:
            logger.error("不明なアンケートモード: %s", mode)
            return

        if not result:
            return

        question, choices = result

        # 投稿
        try:
            post_id = await self._db.insert_post(
                post_type="poll",
                execution_key=execution_key,
                content=question,
                scheduled_delete_at=scheduled_delete_at,
            )
        except sqlite3.IntegrityError:
            logger.info("アンケートは既に実行済みです（execution_key=%s）", execution_key)
            return

        # expiresAt 計算（UNIXミリ秒）
        expires_at = int((now + timedelta(hours=poll_config.expire_hours)).timestamp() * 1000)

        try:
            note_id = await self._misskey.create_note(
                text=question,
                visibility=self._config.posting.default_visibility,
                poll={
                    "choices": choices,
                    "multiple": poll_config.multiple_choice,
                    "expiresAt": expires_at,
                },
            )
            await self._db.update_post_note_id(post_id, note_id)
            logger.info("アンケートを投稿しました（mode=%s, note_id=%s）", mode, note_id)
        except Exception as e:
            logger.error("アンケート投稿に失敗しました: %s", str(e))
            await self._db.delete_post_by_id(post_id)

    async def _generate_tl_word_poll(self) -> tuple[str, list[str]] | None:
        """tl_word モードの選択肢を生成する。"""
        poll_serif = self._serif_loader.poll
        if not poll_serif:
            return None

        poll_config = self._config.posting.poll

        # TLからノート取得
        raw_notes = await self._misskey.get_timeline(
            source=poll_config.timeline_source,
            limit=poll_config.max_notes_fetch,
        )

        note_events = [
            NoteEvent(
                note_id=n.get("id", ""),
                user_id=n.get("userId", ""),
                username=n.get("user", {}).get("username"),
                text=n.get("text"),
                cw=n.get("cw"),
                visibility=n.get("visibility", "public"),
                reply_id=n.get("replyId"),
                renote_id=n.get("renoteId"),
                has_poll=n.get("poll") is not None,
                file_ids=[f["id"] for f in n.get("files", [])],
            )
            for n in raw_notes
        ]

        filtered = filter_notes(note_events, self._misskey.bot_user_id)

        # キーワード抽出
        keywords: list[str] = []
        for note in filtered:
            cleaned = clean_note_text(note.text)
            if not cleaned:
                continue
            kws = await asyncio.to_thread(
                self._tokenizer.extract_keywords, cleaned
            )
            for kw in kws:
                if not self._ng_word.contains_ng_word(kw):
                    keywords.append(kw)

        # 不足分は items で補完
        choice_count = poll_config.choice_count
        unique_keywords = list(set(keywords))

        if len(unique_keywords) < choice_count:
            items = poll_serif.get("items", [])
            while len(unique_keywords) < choice_count and items:
                item = random.choice(items)
                if item not in unique_keywords:
                    unique_keywords.append(item)

        if len(unique_keywords) < choice_count:
            logger.warning("選択肢が不足しています")
            return None

        selected = random.sample(unique_keywords, choice_count)

        # 接頭辞を付与
        prefixes = poll_serif.get("prefixes", [])
        choices = []
        for kw in selected:
            if prefixes:
                prefix = random.choice(prefixes)
                choices.append(f"{prefix}{kw}")
            else:
                choices.append(kw)

        # 質問文
        questions = poll_serif.get("questions", ["どれ？"])
        question = random.choice(questions)

        return question, choices

    def _generate_static_poll(self) -> tuple[str, list[str]] | None:
        """static モードの選択肢を生成する。"""
        poll_serif = self._serif_loader.poll
        if not poll_serif:
            return None

        items = poll_serif.get("items", [])
        if len(items) < self._config.posting.poll.choice_count:
            return None

        selected = random.sample(items, self._config.posting.poll.choice_count)

        prefixes = poll_serif.get("prefixes", [])
        choices = []
        for item in selected:
            if prefixes:
                prefix = random.choice(prefixes)
                choices.append(f"{prefix}{item}")
            else:
                choices.append(item)

        questions = poll_serif.get("questions", ["どれ？"])
        question = random.choice(questions)

        return question, choices

    async def _generate_ai_poll(self) -> tuple[str, list[str]] | None:
        """ai モードの選択肢を生成する。"""
        prompt = (
            "投票の質問文を1つと、カジュアルで面白い選択肢を4つ生成してください。\n"
            "JSONで {\"question\": \"質問文\", \"choices\": [\"選択肢1\", \"選択肢2\", \"選択肢3\", \"選択肢4\"]} "
            "の形式で返してください。JSON以外の文字は含めないでください。"
        )

        try:
            response = await self._ai.generate(
                user_prompt=prompt,
                system_prompt="あなたはカジュアルで面白いアンケートを作るアシスタントです。",
            )

            # JSONをパース
            data = json.loads(response)
            validated = PollAIResponse(**data)

            # NGワードチェック
            all_text = validated.question + " ".join(validated.choices)
            if self._ng_word.contains_ng_word(all_text):
                logger.warning("AIアンケートにNGワードが含まれていました。staticモードにフォールバックします")
                return self._generate_static_poll()

            return validated.question, validated.choices

        except (json.JSONDecodeError, Exception) as e:
            logger.warning("AIアンケート生成に失敗しました: %s。staticモードにフォールバックします", str(e))
            return self._generate_static_poll()
