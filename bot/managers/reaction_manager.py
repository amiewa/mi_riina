"""リアクションマネージャー

TL上のノートに対し、指定ワードが含まれていればリアクションを送信する。
"""

import logging
import random

from bot.core.config import AppConfig
from bot.core.database import Database
from bot.core.misskey_client import MisskeyClient
from bot.core.models import NoteEvent
from bot.utils.night_mode import is_night_mode

logger = logging.getLogger(__name__)


class ReactionManager:
    """リアクションマネージャー"""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        misskey: MisskeyClient,
    ) -> None:
        self._config = config
        self._db = db
        self._misskey = misskey

    async def on_note(self, event: NoteEvent) -> None:
        """ノートイベントを処理し、マッチするキーワードを含んでいればリアクションを送信する。"""
        if not self._config.reaction.enabled:
            return

        # bot 自身のノートはスキップ
        if event.user_id == self._misskey.bot_user_id:
            return

        # 夜間モード判定
        night = self._config.posting.night_mode
        if is_night_mode(night.start_hour, night.end_hour, night.enabled, self._config.bot.timezone):
            return

        # 相互フォローチェック
        if self._config.reaction.mutual_only:
            if not await self._db.is_mutual(event.user_id):
                return

        # テキストがない場合はスキップ
        if not event.text:
            return

        # 重複チェック
        if await self._db.has_reacted(event.note_id):
            return

        # ルールとマッチング
        for rule in self._config.reaction.rules:
            for keyword in rule.keywords:
                if keyword in event.text:
                    # マッチした → リアクション送信
                    reaction = random.choice(rule.reactions)
                    try:
                        await self._misskey.create_reaction(
                            event.note_id, reaction
                        )
                        await self._db.record_reaction(event.note_id)
                        logger.debug(
                            "リアクションを送信しました（note_id=%s, reaction=%s）",
                            event.note_id, reaction,
                        )
                    except Exception as e:
                        logger.error(
                            "リアクション送信に失敗しました: %s", str(e)
                        )
                    return  # 最初にマッチしたルールのみ
