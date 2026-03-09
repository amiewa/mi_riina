"""タイムライン連動投稿マネージャー

TLからノートを取得し、キーワードを抽出して投稿する。
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta

from zoneinfo import ZoneInfo

from bot.core.config import AppConfig
from bot.core.database import Database
from bot.core.misskey_client import MisskeyClient, filter_notes
from bot.core.models import NoteEvent
from bot.utils.night_mode import is_night_mode
from bot.utils.ng_word_manager import NGWordManager
from bot.utils.text_cleaner import clean_note_text
from bot.utils.tokenizer import TokenizerBase

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")


class TimelinePostManager:
    """タイムライン連動投稿マネージャー"""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        misskey: MisskeyClient,
        tokenizer: TokenizerBase,
        ng_word_manager: NGWordManager,
    ) -> None:
        self._config = config
        self._db = db
        self._misskey = misskey
        self._tokenizer = tokenizer
        self._ng_word = ng_word_manager

    async def execute_timeline_post(self) -> None:
        """タイムライン連動投稿を実行する。"""
        tl_config = self._config.posting.timeline_post

        if not tl_config.enabled:
            return

        # 夜間モード判定
        night = self._config.posting.night_mode
        if is_night_mode(
            night.start_hour, night.end_hour, night.enabled, self._config.bot.timezone
        ):
            logger.debug("夜間モード中のためTL連動投稿をスキップします")
            return

        # 確率判定
        if random.random() > tl_config.probability:
            logger.debug("確率判定によりTL連動投稿をスキップします")
            return

        # クールダウン判定
        cooldown = self._config.posting.cooldown_minutes
        if cooldown > 0:
            last_time = await self._db.get_last_auto_post_time()
            if last_time:
                last_dt = datetime.fromisoformat(last_time)
                if datetime.now(JST) - last_dt < timedelta(minutes=cooldown):
                    logger.debug("クールダウン中のためTL連動投稿をスキップします")
                    return

        # TLからノート取得
        raw_notes = await self._misskey.get_timeline(
            source=tl_config.source,
            limit=tl_config.max_notes_fetch,
        )

        # NoteEvent に変換してフィルタリング
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

        if not filtered:
            logger.debug("TLからフィルタリング後のノートがありません")
            return

        # キーワード抽出
        all_keywords: list[str] = []
        for note in filtered:
            cleaned = clean_note_text(note.text)
            if not cleaned:
                continue

            keywords = await asyncio.to_thread(
                self._tokenizer.extract_keywords, cleaned
            )

            for kw in keywords:
                if (
                    len(kw) >= tl_config.min_keyword_length
                    and not self._ng_word.contains_ng_word(kw)
                ):
                    all_keywords.append(kw)

        if not all_keywords:
            logger.debug("TLからキーワードを抽出できませんでした")
            return

        # キーワードを選択して投稿文を生成
        keyword = random.choice(all_keywords)
        text = f"{keyword}… りいなも気になるじゃん"

        # 自動削除スケジュール計算
        auto_delete = self._config.posting.auto_delete.timeline_post
        scheduled_delete_at = None
        if auto_delete.enabled:
            delete_time = datetime.now(JST) + timedelta(hours=auto_delete.after_hours)
            scheduled_delete_at = delete_time.isoformat()

        # 投稿
        try:
            post_id = await self._db.insert_post(
                post_type="timeline",
                execution_key=None,
                content=text,
                scheduled_delete_at=scheduled_delete_at,
            )

            note_id = await self._misskey.create_note(
                text=text,
                visibility=self._config.posting.default_visibility,
            )

            await self._db.update_post_note_id(post_id, note_id)
            logger.info(
                "TL連動投稿を実行しました（keyword=%s, note_id=%s）",
                keyword,
                note_id,
            )
        except Exception as e:
            logger.error("TL連動投稿に失敗しました: %s", str(e))
            try:
                await self._db.delete_post_by_id(post_id)
            except Exception:
                pass
