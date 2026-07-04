"""レート制限ユーティリティ

リプライのレート制限を管理する。
DB ベースで直近N時間のリプライ数をチェックする。
"""

import logging

from bot.core.database import Database

logger = logging.getLogger(__name__)


class RateLimiter:
    """リプライレート制限

    指定ユーザーの直近1時間のリプライ数をチェックし、
    制限を超えている場合はスキップする。
    """

    def __init__(self, db: Database, max_per_user_per_hour: int = 3) -> None:
        self._db = db
        self._max_per_user_per_hour = max_per_user_per_hour

    async def is_limited(self, user_id: str) -> bool:
        """指定ユーザーがレート制限に達しているかを判定する。"""
        count = await self.get_count(user_id)
        if count >= self._max_per_user_per_hour:
            logger.info(
                "レート制限に達しています（user_id=%s, count=%d/%d）",
                user_id,
                count,
                self._max_per_user_per_hour,
            )
            return True
        return False

    async def get_count(self, user_id: str) -> int:
        """指定ユーザーの直近1時間のリプライ数を取得する。"""
        return await self._db.count_recent_replies(user_id, hours=1)

    @property
    def max_per_user_per_hour(self) -> int:
        """1時間あたりの上限リプライ数。"""
        return self._max_per_user_per_hour

    async def record(self, user_id: str) -> None:
        """リプライを記録する。"""
        await self._db.record_reply(user_id)
