"""リプライマネージャー

bot宛メンションに対して AI で応答するリプライ機能。
Phase 1: 単発リプライ（メンション1件のみ、会話文脈なし）。
Phase 2: マルチターン会話文脈対応（reply.conversation.enabled: true の場合）。
"""

import asyncio
import logging
import random
import re
import sqlite3
from pathlib import Path

from bot.core.ai_client import AIClientBase
from bot.core.config import AppConfig
from bot.core.database import Database
from bot.core.misskey_client import MisskeyClient
from bot.core.models import MentionEvent
from bot.utils.ng_word_manager import NGWordManager
from bot.utils.rate_limiter import RateLimiter
from bot.utils.serif_loader import SerifLoader
from bot.utils.text_cleaner import clean_note_text

logger = logging.getLogger(__name__)

# ニックネーム登録パターン
_NICKNAME_REGISTER_RE = re.compile(r"(.+?)って呼んで")
# ニックネーム削除パターン
_NICKNAME_RESET_KEYWORD = "呼び名リセット"


class ReplyManager:
    """リプライマネージャー"""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        misskey: MisskeyClient,
        ai_client: AIClientBase,
        ng_word_manager: NGWordManager,
        rate_limiter: RateLimiter,
        serif_loader: SerifLoader,
        affinity_manager=None,
    ) -> None:
        self._config = config
        self._db = db
        self._misskey = misskey
        self._ai = ai_client
        self._ng_word = ng_word_manager
        self._rate_limiter = rate_limiter
        self._serif_loader = serif_loader
        self._affinity = affinity_manager
        self._semaphore = asyncio.Semaphore(config.reply.ai_concurrency)
        self._character_prompt = self._load_character_prompt()

    def _load_character_prompt(self) -> str:
        """キャラクタープロンプトを読み込む。"""
        prompt_path = Path(self._config.bot.character_prompt_file)
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        logger.warning("キャラクタープロンプトが見つかりません: %s", prompt_path)
        return ""

    async def on_mention(self, event: MentionEvent) -> None:
        """メンションイベントを処理する。"""
        # bot 自身のメンションはスキップ
        if event.user_id == self._misskey.bot_user_id:
            return

        if not self._config.reply.enabled:
            return

        # execution_key チェック（二重返信防止）
        execution_key = f"reply:{event.note_id}"

        # 相互フォローチェック
        if self._config.reply.mutual_only:
            if not await self._db.is_mutual(event.user_id):
                logger.debug(
                    "相互フォローでないためリプライをスキップします（user_id=%s）",
                    event.user_id,
                )
                return

        # レート制限チェック
        if await self._rate_limiter.is_limited(event.user_id):
            await self._send_fallback(event, "rate_limited")
            return

        # テキストクリーニング
        cleaned_text = clean_note_text(event.text)

        # ニックネームパターンチェック
        if self._config.reply.nickname.enabled:
            if _NICKNAME_RESET_KEYWORD in cleaned_text:
                await self._handle_nickname_reset(event, execution_key)
                return
            match = _NICKNAME_REGISTER_RE.search(cleaned_text)
            if match:
                await self._handle_nickname_registration(
                    event, match.group(1), execution_key
                )
                return

        # 空文チェック
        if not cleaned_text:
            await self._send_fallback(event, "empty_input")
            return

        # NGワードチェック
        if self._ng_word.contains_ng_word(cleaned_text):
            await self._send_fallback(event, "ng_word")
            return

        # 入力テキストの切り捨て
        max_chars = self._config.ai.input_max_chars
        if len(cleaned_text) > max_chars:
            cleaned_text = cleaned_text[:max_chars]

        # AI応答生成
        async with self._semaphore:
            try:
                # 親密度ランクに応じた追加プロンプトを構築
                system_prompt = self._character_prompt
                if self._affinity:
                    affinity_prompt = await self._affinity.get_affinity_prompt(
                        event.user_id
                    )
                    if affinity_prompt:
                        system_prompt = f"{system_prompt}\n\n{affinity_prompt}"

                # ニックネーム/表示名をプロンプトに反映
                display_name = await self._resolve_display_name(event)
                if display_name:
                    system_prompt = (
                        f"{system_prompt}\n\n相手の呼び名は{display_name}"
                    )

                # 会話文脈の構築
                conv_messages: list[dict] | None = None
                if self._config.reply.conversation.enabled:
                    conv_messages = await self._build_conversation_messages(
                        event, cleaned_text
                    )

                response = await self._ai.generate(
                    user_prompt=cleaned_text,
                    system_prompt=system_prompt,
                    messages=conv_messages,
                )
            except Exception as e:
                logger.error("AI応答の生成に失敗しました: %s", str(e))
                await self._send_fallback(event, "api_error")
                return

        # NGワードチェック（AI応答）
        if self._ng_word.contains_ng_word(response):
            logger.warning("AI応答にNGワードが含まれていました")
            await self._send_fallback(event, "ng_word")
            return

        # 投稿
        try:
            post_id = await self._db.insert_post(
                post_type="reply",
                execution_key=execution_key,
                content=response[:200],  # 保存は先頭200文字
            )
        except sqlite3.IntegrityError:
            logger.info(
                "リプライは既に送信済みです（execution_key=%s）",
                execution_key,
            )
            return

        try:
            note_id = await self._misskey.create_note(
                text=response,
                visibility=event.visibility,
                reply_id=event.note_id,
            )
            await self._db.update_post_note_id(post_id, note_id)
            await self._rate_limiter.record(event.user_id)
            # 投稿成功後に親密度を記録
            if self._affinity:
                await self._affinity.record_interaction(event.user_id)
            # 投稿成功後に会話履歴を保存
            if self._config.reply.conversation.enabled:
                await self._db.save_conversation_turn(
                    user_id=event.user_id,
                    user_message=cleaned_text,
                    bot_response=response,
                    note_id=note_id,
                )
            logger.info(
                "リプライを送信しました（note_id=%s, user_id=%s）",
                note_id,
                event.user_id,
            )
        except Exception as e:
            logger.error("リプライの投稿に失敗しました: %s", str(e))
            await self._db.delete_post_by_id(post_id)

    async def _build_conversation_messages(
        self, event: MentionEvent, cleaned_text: str
    ) -> list[dict]:
        """会話文脈の messages 配列を構築する。

        リプライツリー遡りを優先し、失敗した場合は DB 履歴にフォールバックする。
        最後に現在のユーザー発言を末尾に追加して返す。
        """
        conv_config = self._config.reply.conversation
        turns: list[dict] = []

        if event.reply_id:
            turns = await self._build_context_from_tree(
                event.reply_id,
                event.user_id,
                conv_config.max_turns,
            )

        if not turns:
            turns = await self._build_context_from_db(
                event.user_id, conv_config.max_turns
            )

        # 文字数制限の適用
        turns = self._trim_context_by_chars(turns, conv_config.history_max_chars)

        # 現在の発言を末尾に追加
        turns.append({"role": "user", "content": cleaned_text})
        return turns

    async def _build_context_from_tree(
        self,
        start_reply_id: str,
        user_id: str,
        max_turns: int,
    ) -> list[dict]:
        """リプライツリーを遡って会話文脈を構築する。

        bot とユーザーのやり取りのみを対象とし、第三者が介入した場合は遡りを中止する。
        1ターン = user + bot の2ノート分。最大 max_turns * 2 ノートを取得する。
        """
        bot_user_id = self._misskey.bot_user_id
        turns: list[dict] = []
        current_note_id: str | None = start_reply_id
        max_nodes = max_turns * 2  # 1ターン = 2ノード

        try:
            for _ in range(max_nodes):
                if not current_note_id:
                    break

                note = await self._misskey.get_note(current_note_id)
                if note is None:
                    break

                note_user_id = note.get("userId", "")
                note_text = clean_note_text(note.get("text") or "")

                if note_user_id == bot_user_id:
                    # bot の発言 → assistant ロール（テキストなしはスキップ）
                    if note_text:
                        turns.append({"role": "assistant", "content": note_text})
                elif note_user_id == user_id:
                    # 同一ユーザーの発言 → user ロール（テキストなしはスキップ）
                    if note_text:
                        turns.append({"role": "user", "content": note_text})
                else:
                    # 第三者の発言 → 遡り中止
                    break

                current_note_id = note.get("replyId")

        except Exception as e:
            logger.debug("リプライツリー遡り中にエラーが発生しました: %s", str(e))
            return []

        turns.reverse()  # 古い順に並べ直す

        # 先頭が assistant の場合は不完全なペアのため削る
        while turns and turns[0]["role"] == "assistant":
            turns.pop(0)

        return turns

    async def _build_context_from_db(
        self,
        user_id: str,
        max_turns: int,
    ) -> list[dict]:
        """DB の会話履歴から文脈を構築する。"""
        history = await self._db.get_conversation_history(user_id, max_turns)
        turns: list[dict] = []
        for h in history:
            turns.append({"role": "user", "content": h["user_message"]})
            turns.append({"role": "assistant", "content": h["bot_response"]})
        return turns

    def _trim_context_by_chars(
        self, turns: list[dict], max_chars: int
    ) -> list[dict]:
        """文字数制限を超えた場合、古いターンからペア単位で削除する。"""
        turns = list(turns)  # コピーして元を変更しない

        while sum(len(t["content"]) for t in turns) > max_chars and turns:
            removed = turns.pop(0)
            # ペアとなる次のターン（role が異なる）も除去する
            if turns and turns[0]["role"] != removed["role"]:
                turns.pop(0)

        return turns

    async def _send_fallback(self, event: MentionEvent, category: str) -> None:
        """フォールバック台詞を送信する。"""
        fallback = self._serif_loader.fallback
        if not fallback or category not in fallback:
            logger.warning("フォールバック台詞が見つかりません: %s", category)
            return

        text = random.choice(fallback[category])

        try:
            await self._misskey.create_note(
                text=text,
                visibility=event.visibility,
                reply_id=event.note_id,
            )
            logger.info(
                "フォールバック台詞を送信しました（category=%s, note_id=%s）",
                category,
                event.note_id,
            )
        except Exception as e:
            logger.error("フォールバック台詞の送信に失敗しました: %s", str(e))

    async def _resolve_display_name(self, event: MentionEvent) -> str | None:
        """ニックネームまたは表示名を解決する。"""
        nickname = await self._db.get_nickname(event.user_id)
        if nickname:
            return nickname
        name = event.raw.get("user", {}).get("name")
        if name and name.strip():
            return name.strip()
        return None

    async def _handle_nickname_registration(
        self, event: MentionEvent, nickname: str, execution_key: str
    ) -> None:
        """ニックネーム登録を処理する。"""
        nickname = nickname.strip()
        nick_config = self._config.reply.nickname

        # 空文字チェック
        if not nickname:
            return

        # 長さチェック
        if len(nickname) > nick_config.max_length:
            nickname = nickname[: nick_config.max_length]

        # NGワードチェック
        if self._ng_word.contains_ng_word(nickname):
            try:
                await self._misskey.create_note(
                    text=nick_config.ng_word_response,
                    visibility=event.visibility,
                    reply_id=event.note_id,
                )
            except Exception as e:
                logger.error("ニックネームNG応答の送信に失敗しました: %s", str(e))
            return

        # DB に登録
        await self._db.upsert_nickname(event.user_id, nickname)
        text = nick_config.success_template.format(nickname=nickname)

        # 二重送信防止チェック
        try:
            post_id = await self._db.insert_post(
                post_type="reply",
                execution_key=execution_key,
                content=text[:200],
            )
        except sqlite3.IntegrityError:
            logger.info(
                "ニックネーム登録応答は既に送信済みです（execution_key=%s）",
                execution_key,
            )
            return

        try:
            note_id = await self._misskey.create_note(
                text=text,
                visibility=event.visibility,
                reply_id=event.note_id,
            )
            await self._db.update_post_note_id(post_id, note_id)
            logger.info(
                "ニックネームを登録しました（user_id=%s, nickname=%s）",
                event.user_id,
                nickname,
            )
        except Exception as e:
            logger.error("ニックネーム登録応答の送信に失敗しました: %s", str(e))
            await self._db.delete_post_by_id(post_id)

    async def _handle_nickname_reset(self, event: MentionEvent, execution_key: str) -> None:
        """ニックネーム削除を処理する。"""
        await self._db.delete_nickname(event.user_id)
        text = self._config.reply.nickname.reset_response

        # 二重送信防止チェック
        try:
            post_id = await self._db.insert_post(
                post_type="reply",
                execution_key=execution_key,
                content=text[:200],
            )
        except sqlite3.IntegrityError:
            logger.info(
                "ニックネームリセット応答は既に送信済みです（execution_key=%s）",
                execution_key,
            )
            return

        try:
            note_id = await self._misskey.create_note(
                text=text,
                visibility=event.visibility,
                reply_id=event.note_id,
            )
            await self._db.update_post_note_id(post_id, note_id)
            logger.info(
                "ニックネームをリセットしました（user_id=%s）",
                event.user_id,
            )
        except Exception as e:
            logger.error("ニックネームリセット応答の送信に失敗しました: %s", str(e))
            await self._db.delete_post_by_id(post_id)
