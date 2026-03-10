"""曜日別投稿マネージャー

指定した曜日・時刻に台詞を投稿する。
"""

import logging
import random
import sqlite3
from datetime import datetime

from zoneinfo import ZoneInfo

from bot.core.config import AppConfig
from bot.core.database import Database
from bot.core.misskey_client import MisskeyClient
from bot.utils.night_mode import is_night_mode
from bot.utils.serif_loader import SerifLoader

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")

# 曜日名の対応
WEEKDAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


class WeekdayPostManager:
    """曜日別投稿マネージャー"""

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

    async def check_and_post(self) -> None:
        """現在の曜日・時刻に一致する台詞があれば投稿する。"""
        if not self._config.posting.weekday_posts.enabled:
            return

        # 夜間モード判定
        night = self._config.posting.night_mode
        if is_night_mode(
            night.start_hour, night.end_hour, night.enabled, self._config.bot.timezone
        ):
            return

        try:
            await self._do_weekday_post(check_probability=True)
        except ValueError:
            pass
        except Exception as e:
            logger.error("曜日別投稿に失敗しました: %s", str(e))

    async def _do_weekday_post(
        self, check_probability: bool = False, force: bool = False
    ) -> None:
        """実際の曜日別投稿処理。AdminManagerからも呼ばれる。"""
        now = datetime.now(JST)
        weekday = WEEKDAY_NAMES[now.weekday()]
        time_key = now.strftime("%H:%M")

        serif_data = self._serif_loader.weekday_posts
        if not serif_data or weekday not in serif_data:
            raise ValueError("現在の曜日の台詞データがありません")

        day_data = serif_data[weekday]
        if time_key not in day_data:
            raise ValueError("現在時刻の台詞データがありません")

        entry = day_data[time_key]

        # 確率判定（スケジューラからの呼び出し時のみ）
        if check_probability:
            probability = entry.get(
                "probability", self._config.posting.weekday_posts.probability
            )
            if random.random() > probability:
                logger.debug("確率判定により曜日別投稿をスキップします")
                return

        # execution_key
        today = now.strftime("%Y-%m-%d")
        execution_key = f"weekday:{weekday}:{time_key}:{today}"

        if force:
            execution_key = None

        # 台詞選択
        posts = entry.get("posts", [])
        if not posts:
            return

        text = random.choice(posts)

        # 投稿
        try:
            post_id = await self._db.insert_post(
                post_type="weekday",
                execution_key=execution_key,
                content=text,
            )
        except sqlite3.IntegrityError:
            if not force:
                logger.info(
                    "曜日別投稿は既に実行済みです（execution_key=%s）",
                    execution_key,
                )
                return
            raise

        try:
            note_id = await self._misskey.create_note(
                text=text,
                visibility=self._config.posting.default_visibility,
            )
            await self._db.update_post_note_id(post_id, note_id)
            logger.info(
                "曜日別投稿を実行しました（%s %s, note_id=%s）",
                weekday,
                time_key,
                note_id,
            )
        except Exception:
            await self._db.delete_post_by_id(post_id)
            raise

    def get_weekday_schedule(self) -> list[dict]:
        """曜日別投稿のスケジュール一覧を返す。

        Returns:
            [{"weekday": "MON", "time": "08:00"}, ...]
        """
        serif_data = self._serif_loader.weekday_posts
        if not serif_data:
            return []

        schedule = []
        for weekday in WEEKDAY_NAMES:
            if weekday in serif_data:
                for time_key in serif_data[weekday]:
                    schedule.append({"weekday": weekday, "time": time_key})
        return schedule
