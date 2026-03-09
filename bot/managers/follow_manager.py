"""フォロー管理マネージャー

フォロワーの定期同期、キーワードフォローバック、
猶予付き自動リムーブバックを管理する。
"""

import logging

from bot.core.config import AppConfig
from bot.core.database import Database
from bot.core.misskey_client import MisskeyClient
from bot.core.models import FollowedEvent, MentionEvent
from bot.utils.text_cleaner import clean_note_text

logger = logging.getLogger(__name__)


class FollowManager:
    """フォロー管理マネージャー"""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        misskey: MisskeyClient,
    ) -> None:
        self._config = config
        self._db = db
        self._misskey = misskey

    async def on_followed(self, event: FollowedEvent) -> None:
        """新規フォロー通知を処理する。"""
        logger.info(
            "新規フォロワーを検出しました（user_id=%s, username=%s）",
            event.user_id,
            event.username,
        )

        # フォロワーテーブルに追加
        await self._db.upsert_follower(
            user_id=event.user_id,
            username=event.username or "",
        )

        # 自動フォローバック
        if self._config.follow.auto_follow_back:
            try:
                await self._misskey.follow_user(event.user_id)
                await self._db.update_following_status(event.user_id, True)
                logger.info(
                    "自動フォローバックを実行しました（user_id=%s）",
                    event.user_id,
                )
            except Exception as e:
                logger.error("フォローバックに失敗しました: %s", str(e))

    async def on_mention(self, event: MentionEvent) -> None:
        """メンションからキーワードフォローバックを処理する。"""
        kfb = self._config.follow.keyword_follow_back
        if not kfb.enabled:
            return

        # bot 自身のメンションはスキップ
        if event.user_id == self._misskey.bot_user_id:
            return

        # テキストチェック
        if not event.text:
            return

        cleaned = clean_note_text(event.text)

        # キーワードマッチ
        for keyword in kfb.keywords:
            if keyword in cleaned:
                # 既にフォローしているか確認
                is_following = await self._db.is_mutual(event.user_id)
                if not is_following:
                    try:
                        await self._misskey.follow_user(event.user_id)
                        await self._db.upsert_follower(
                            user_id=event.user_id,
                            username=event.username or "",
                            i_am_following=True,
                        )
                        logger.info(
                            "キーワードフォローバックを実行しました（user_id=%s, keyword=%s）",
                            event.user_id,
                            keyword,
                        )
                    except Exception as e:
                        logger.error(
                            "キーワードフォローバックに失敗しました: %s",
                            str(e),
                        )
                return

    async def sync_followers(self) -> None:
        """フォロワー・フォロー一覧を定期同期する。"""
        try:
            # 現在のフォロワー一覧を取得
            raw_followers = await self._misskey.get_followers(limit=1000)
            follower_ids = set()

            for f in raw_followers:
                follower = f.get("follower", f)
                user_id = follower.get("id", "")
                username = follower.get("username", "")
                if user_id:
                    follower_ids.add(user_id)
                    await self._db.upsert_follower(
                        user_id=user_id,
                        username=username,
                    )

            # 現在のフォロー一覧を取得
            raw_following = await self._misskey.get_following(limit=1000)
            following_ids = set()

            for f in raw_following:
                followee = f.get("followee", f)
                user_id = followee.get("id", "")
                if user_id:
                    following_ids.add(user_id)

            # フォロー状態を更新
            db_followers = await self._db.get_all_followers()
            for follower in db_followers:
                user_id = follower["user_id"]
                is_following = user_id in following_ids
                await self._db.update_following_status(user_id, is_following)

                # フォロワーから外れたユーザーの処理
                if user_id not in follower_ids:
                    count = await self._db.increment_missing_count(user_id)
                    grace = self._config.follow.unfollow_grace_cycles

                    if count >= grace:
                        logger.info(
                            "フォロワーから外れたユーザーを検出しました（user_id=%s, missing_count=%d/%d）",
                            user_id,
                            count,
                            grace,
                        )
                        await self._db.delete_follower(user_id)

                        # 自動アンフォローバック
                        if self._config.follow.auto_unfollow_back and is_following:
                            try:
                                await self._misskey.unfollow_user(user_id)
                                logger.info(
                                    "自動アンフォローバックを実行しました（user_id=%s）",
                                    user_id,
                                )
                            except Exception as e:
                                logger.error(
                                    "アンフォローバックに失敗しました: %s",
                                    str(e),
                                )
                else:
                    # フォロワーに存在する場合は missing_count をリセット
                    await self._db.reset_missing_count(user_id)

            logger.info(
                "フォロワー同期を完了しました（フォロワー: %d, フォロー: %d）",
                len(follower_ids),
                len(following_ids),
            )

        except Exception as e:
            logger.error("フォロワー同期に失敗しました: %s", str(e))
