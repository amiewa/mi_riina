"""定時投稿 + 記念日イベント投稿マネージャー

scheduled.yaml の時刻に基づいて定時投稿を実行する。
event.yaml の記念日イベント投稿もこのマネージャーが処理する。
"""

import logging
import random
import sqlite3
from datetime import datetime, timedelta

from zoneinfo import ZoneInfo

from bot.core.config import AppConfig
from bot.core.database import Database
from bot.core.misskey_client import MisskeyClient
from bot.utils.night_mode import is_night_mode
from bot.utils.serif_loader import SerifLoader

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")


class ScheduledPostManager:
    """定時投稿 + 記念日イベント投稿マネージャー"""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        misskey: MisskeyClient,
        serif_loader: SerifLoader,
    ) -> None:
        self._config = config
        self._db = db
        self._misskey = misskey
        self._serif_loader = serif_loader

    async def execute_scheduled_post(self, time_key: str) -> None:
        """指定時刻の定時投稿を実行する。

        Args:
            time_key: "HH:MM" 形式の時刻キー
        """
        if not self._config.posting.scheduled_posts.enabled:
            return

        # 夜間モード判定
        night = self._config.posting.night_mode
        if is_night_mode(night.start_hour, night.end_hour, night.enabled, self._config.bot.timezone):
            logger.debug("夜間モード中のため定時投稿をスキップします")
            return

        # 確率判定
        if random.random() > self._config.posting.scheduled_posts.probability:
            logger.debug("確率判定により定時投稿をスキップします")
            return

        # execution_key で二重投稿チェック
        today = datetime.now(JST).strftime("%Y-%m-%dT")
        execution_key = f"scheduled:{today}{time_key}"

        # 台詞取得
        serif_data = self._serif_loader.scheduled
        if not serif_data or time_key not in serif_data:
            logger.warning("定時投稿の台詞が見つかりません: %s", time_key)
            return

        text = random.choice(serif_data[time_key])

        # 自動削除スケジュール計算
        auto_delete = self._config.posting.auto_delete.scheduled_posts
        scheduled_delete_at = None
        if auto_delete.enabled:
            delete_time = datetime.now(JST) + timedelta(hours=auto_delete.after_hours)
            scheduled_delete_at = delete_time.isoformat()

        # 投稿
        try:
            post_id = await self._db.insert_post(
                post_type="scheduled",
                execution_key=execution_key,
                content=text,
                scheduled_delete_at=scheduled_delete_at,
            )
        except sqlite3.IntegrityError:
            logger.info(
                "定時投稿は既に実行済みです（execution_key=%s）",
                execution_key,
            )
            return

        try:
            note_id = await self._misskey.create_note(
                text=text,
                visibility=self._config.posting.default_visibility,
            )
            await self._db.update_post_note_id(post_id, note_id)
            logger.info(
                "定時投稿を実行しました（note_id=%s, execution_key=%s）",
                note_id, execution_key,
            )
        except Exception as e:
            logger.error("定時投稿に失敗しました: %s", str(e))
            await self._db.delete_post_by_id(post_id)

    async def execute_event_post(self, date_key: str) -> None:
        """記念日イベント投稿を実行する。

        Args:
            date_key: "MM/DD" 形式の日付キー
        """
        if not self._config.posting.event.enabled:
            return

        # execution_key で二重投稿チェック
        today = datetime.now(JST).strftime("%Y-%m-%d")
        execution_key = f"event:{date_key}:{today}"

        # 台詞取得
        serif_data = self._serif_loader.event
        if not serif_data or "events" not in serif_data:
            return

        events = serif_data["events"]
        if date_key not in events:
            return

        event_info = events[date_key]
        text = random.choice(event_info["posts"])

        # 投稿
        try:
            post_id = await self._db.insert_post(
                post_type="event",
                execution_key=execution_key,
                content=text,
            )
        except sqlite3.IntegrityError:
            logger.info(
                "イベント投稿は既に実行済みです（execution_key=%s）",
                execution_key,
            )
            return

        try:
            note_id = await self._misskey.create_note(
                text=text,
                visibility=self._config.posting.default_visibility,
            )
            await self._db.update_post_note_id(post_id, note_id)
            logger.info(
                "イベント投稿を実行しました（%s: %s, note_id=%s）",
                event_info.get("name", date_key), execution_key, note_id,
            )
        except Exception as e:
            logger.error("イベント投稿に失敗しました: %s", str(e))
            await self._db.delete_post_by_id(post_id)

    def get_today_event_key(self) -> str | None:
        """今日のイベントキー ("MM/DD") を返す。なければ None。"""
        serif_data = self._serif_loader.event
        if not serif_data or "events" not in serif_data:
            return None

        today_key = datetime.now(JST).strftime("%m/%d")
        if today_key in serif_data["events"]:
            return today_key
        return None

    def get_scheduled_times(self) -> list[str]:
        """定時投稿の全時刻キーを返す。"""
        serif_data = self._serif_loader.scheduled
        if not serif_data:
            return []
        return list(serif_data.keys())
