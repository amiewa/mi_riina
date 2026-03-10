"""親密度マネージャー

ユーザーとの交流回数を記録し、ランクに応じてAIプロンプトを変化させる。
みあbot（Webhook.gs）と同等の仕組みを実装する。
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.core.config import AppConfig
from bot.core.database import Database

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")

# ランクに応じて追加するプロンプト文
AFFINITY_PROMPTS = {
    1: "",
    2: "相手とは何度か話したことがあり、少しだけ心を開いている。",
    3: "相手とは親しく、信頼している。いつもより少しだけ素直に話す。",
}


class AffinityManager:
    """親密度マネージャー

    交流カウントを DB に記録し、ランクに応じた追加プロンプトを提供する。
    enabled=False の場合は DB 操作を一切行わない。
    """

    def __init__(self, config: AppConfig, db: Database) -> None:
        self._config = config
        self._db = db

    @property
    def enabled(self) -> bool:
        """親密度機能が有効かどうか。"""
        return self._config.affinity.enabled

    async def record_interaction(self, user_id: str) -> None:
        """交流を記録し、ランクを更新する。

        AI が正常に応答を生成し、投稿が成功した場合のみ呼び出す。

        Args:
            user_id: 交流相手のユーザーID
        """
        if not self.enabled:
            return

        now = datetime.now(JST).isoformat()

        existing = await self._db.fetchone(
            "SELECT interaction_count FROM affinities WHERE user_id = ?",
            (user_id,),
        )

        if existing:
            new_count = existing["interaction_count"] + 1
            new_rank = self._calculate_rank(new_count)
            await self._db.execute(
                """UPDATE affinities
                   SET interaction_count = ?, last_interaction = ?, rank = ?
                   WHERE user_id = ?""",
                (new_count, now, new_rank, user_id),
            )
        else:
            new_count = 1
            new_rank = self._calculate_rank(new_count)
            await self._db.execute(
                """INSERT INTO affinities
                   (user_id, interaction_count, last_interaction, rank)
                   VALUES (?, ?, ?, ?)""",
                (user_id, new_count, now, new_rank),
            )

        logger.debug(
            "親密度を更新しました（user_id=%s, count=%d, rank=%d）",
            user_id,
            new_count,
            new_rank,
        )

    async def get_rank(self, user_id: str) -> int:
        """ユーザーのランクを取得する。

        Args:
            user_id: ユーザーID

        Returns:
            ランク（1/2/3）。DBに記録がない場合は 1。
        """
        if not self.enabled:
            return 1
        row = await self._db.fetchone(
            "SELECT rank FROM affinities WHERE user_id = ?",
            (user_id,),
        )
        return row["rank"] if row else 1

    async def get_affinity_prompt(self, user_id: str) -> str:
        """ランクに応じた追加プロンプトを返す。

        Args:
            user_id: ユーザーID

        Returns:
            追加プロンプト文。Rank1 の場合は空文字。
        """
        rank = await self.get_rank(user_id)
        return AFFINITY_PROMPTS.get(rank, "")

    def _calculate_rank(self, interaction_count: int) -> int:
        """交流回数からランクを計算する。

        Args:
            interaction_count: 交流回数

        Returns:
            ランク（1/2/3）
        """
        if interaction_count >= self._config.affinity.rank3_threshold:
            return 3
        elif interaction_count >= self._config.affinity.rank2_threshold:
            return 2
        return 1
