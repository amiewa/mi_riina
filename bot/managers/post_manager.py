"""ランダム投稿マネージャー

一定間隔でランダムな台詞を投稿する。
夜間停止・確率判定・クールダウン・自己削除スケジュール登録に対応。
"""

import logging
import random
from datetime import datetime, timedelta

from zoneinfo import ZoneInfo

from bot.core.config import AppConfig
from bot.core.database import Database
from bot.core.misskey_client import MisskeyClient
from bot.utils.night_mode import is_night_mode
from bot.utils.serif_loader import SerifLoader

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")


class PostManager:
    """ランダム投稿マネージャー"""

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

    async def execute_random_post(self) -> None:
        """ランダム投稿を実行する。"""
        post_config = self._config.posting.random_post

        if not post_config.enabled:
            return

        # 夜間モード判定
        night = self._config.posting.night_mode
        if is_night_mode(
            night.start_hour, night.end_hour, night.enabled, self._config.bot.timezone
        ):
            logger.debug("夜間モード中のためランダム投稿をスキップします")
            return

        # 確率判定
        if random.random() > post_config.probability:
            logger.debug("確率判定によりランダム投稿をスキップします")
            return

        # クールダウン判定
        if not await self._check_cooldown():
            return

        await self._do_random_post()

    async def _do_random_post(self) -> None:
        """実際の投稿処理（チェックなし）。AdminManagerからも呼ばれる。"""
        # 台詞取得
        serif_data = self._serif_loader.random
        if not serif_data or "posts" not in serif_data:
            logger.warning("ランダム投稿の台詞が設定されていません")
            return

        text = random.choice(serif_data["posts"])

        # 自動削除スケジュール計算
        auto_delete = self._config.posting.auto_delete.random_post
        scheduled_delete_at = None
        if auto_delete.enabled:
            delete_time = datetime.now(JST) + timedelta(hours=auto_delete.after_hours)
            scheduled_delete_at = delete_time.isoformat()

        # 投稿
        try:
            post_id = await self._db.insert_post(
                post_type="random",
                execution_key=None,  # ランダム投稿は execution_key なし
                content=text,
                scheduled_delete_at=scheduled_delete_at,
            )

            note_id = await self._misskey.create_note(
                text=text,
                visibility=self._config.posting.default_visibility,
            )

            await self._db.update_post_note_id(post_id, note_id)
            logger.info(
                "ランダム投稿を実行しました（note_id=%s, post_type=random）",
                note_id,
            )
        except Exception as e:
            logger.error("ランダム投稿に失敗しました: %s", str(e))
            # 投稿レコードの削除（リトライ許可）
            try:
                await self._db.delete_post_by_id(post_id)
            except Exception:
                pass

    async def _check_cooldown(self) -> bool:
        """クールダウンを確認する。制限内なら True、制限超過なら False。"""
        cooldown = self._config.posting.cooldown_minutes
        if cooldown <= 0:
            return True

        last_time = await self._db.get_last_auto_post_time()
        if last_time:
            last_dt = datetime.fromisoformat(last_time)
            if datetime.now(JST) - last_dt < timedelta(minutes=cooldown):
                logger.debug(
                    "クールダウン中のためスキップします（%d分間隔）",
                    cooldown,
                )
                return False
        return True
