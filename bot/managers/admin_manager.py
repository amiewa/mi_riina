"""管理コマンドマネージャー

bot管理者がメンションでコマンドを送信することで、
ステータス確認や強制投稿を行う。
"""

import logging
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from bot import __version__
from bot.core.config import AppConfig
from bot.core.database import Database
from bot.core.misskey_client import MisskeyClient
from bot.core.models import MentionEvent
from bot.managers.horoscope_manager import HoroscopeManager
from bot.managers.poll_manager import PollManager
from bot.managers.post_manager import PostManager
from bot.managers.scheduled_post_manager import ScheduledPostManager
from bot.managers.timeline_post_manager import TimelinePostManager
from bot.managers.weekday_post_manager import WeekdayPostManager
from bot.managers.wordcloud_manager import WordcloudManager
from bot.utils.serif_loader import SerifLoader
from bot.utils.text_cleaner import clean_note_text

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")


class AdminManager:
    """管理コマンドマネージャー"""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        misskey: MisskeyClient,
        serif_loader: SerifLoader,
        post_manager: PostManager,
        scheduled_post_manager: ScheduledPostManager,
        weekday_post_manager: WeekdayPostManager,
        timeline_post_manager: TimelinePostManager,
        horoscope_manager: HoroscopeManager,
        wordcloud_manager: WordcloudManager,
        poll_manager: PollManager,
    ) -> None:
        self._config = config
        self._db = db
        self._misskey = misskey
        self._serif_loader = serif_loader

        self._post_manager = post_manager
        self._scheduled_post_manager = scheduled_post_manager
        self._weekday_post_manager = weekday_post_manager
        self._timeline_post_manager = timeline_post_manager
        self._horoscope_manager = horoscope_manager
        self._wordcloud_manager = wordcloud_manager
        self._poll_manager = poll_manager

        self._admin_user_ids: list[str] = []

    async def initialize(self) -> None:
        """初期化処理（管理者IDの解決）。"""
        usernames = self._config.admin.usernames
        if not usernames:
            logger.info("管理コマンドは無効です（admin.usernames が空）")
            return

        for username in usernames:
            user = await self._misskey.get_user_by_username(username)
            if user:
                user_id = user["id"]
                self._admin_user_ids.append(user_id)
                logger.info("管理者IDを解決しました: %s -> %s", username, user_id)
            else:
                logger.warning("管理者ユーザーが見つかりません: %s", username)

    async def try_handle(self, event: MentionEvent) -> bool:
        """管理コマンドとしての処理を試みる。
        管理コマンドとして処理した場合は True を返す。
        """
        if not self._admin_user_ids:
            return False

        text = clean_note_text(event.text or "")

        if not text.startswith("/admin"):
            return False

        if event.user_id not in self._admin_user_ids:
            logger.warning("非管理者からのコマンドを無視しました: %s", event.user_id)
            return True

        parts = text.split()
        if len(parts) < 2:
            await self._reply_error(event.note_id)
            return True

        subcommand = parts[1]

        try:
            if subcommand == "status":
                await self._handle_status(event.note_id)
            elif subcommand == "post":
                if len(parts) < 3:
                    await self._reply_error(event.note_id)
                else:
                    await self._handle_post(event.note_id, parts[2])
            else:
                await self._reply_error(event.note_id)
        except Exception as e:
            logger.error("管理コマンド実行中にエラー: %s", e)
            await self._reply_error(event.note_id)

        return True

    async def _reply_error(self, reply_id: str) -> None:
        """不正なコマンド時のエラー応答"""
        fallback_data = self._serif_loader.fallback or {}
        serifs = fallback_data.get("command_error", [])
        text = random.choice(serifs) if serifs else "コマンドエラー"
        await self._misskey.create_note(
            text=text,
            visibility="specified",
            reply_id=reply_id,
        )

    async def _handle_status(self, reply_id: str) -> None:
        """/admin status の処理"""
        c = self._config
        today_start = datetime.now(JST).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        row = await self._db.fetchone(
            """
            SELECT COUNT(*) as count FROM posts
            WHERE post_type IN ('reply', 'horoscope', 'timeline', 'poll')
              AND posted_at >= ?
            """,
            (today_start.isoformat(),),
        )
        today_posts_count = row["count"] if row else 0

        stock_count = await self._db.get_stock_count()

        lines = [
            f"りいなbot v{__version__}",
            "─────────────",
            f"ai: {c.ai.provider} / 本日の投稿数: {today_posts_count}件",
            f"posting: {c.posting.default_visibility} / cooldown: {c.posting.cooldown_minutes}分",  # noqa: E501
            f"night_mode: {c.posting.night_mode.enabled} / {c.posting.night_mode.start_hour}:00〜{c.posting.night_mode.end_hour}:00",  # noqa: E501
            f"random_post: {c.posting.random_post.enabled} / {c.posting.random_post.interval_minutes}分 / prob: {c.posting.random_post.probability}",  # noqa: E501
            f"scheduled: {c.posting.scheduled_posts.enabled} / prob: {c.posting.scheduled_posts.probability}",  # noqa: E501
            f"weekday: {c.posting.weekday_posts.enabled} / prob: {c.posting.weekday_posts.probability}",  # noqa: E501
            f"timeline: {c.posting.timeline_post.enabled} / {c.posting.timeline_post.source} / {c.posting.timeline_post.interval_minutes}分 / max: {c.posting.timeline_post.max_notes_fetch} / min_kw: {c.posting.timeline_post.min_keyword_length} / prob: {c.posting.timeline_post.probability}",  # noqa: E501
            f"horoscope: {c.posting.horoscope.enabled} / {c.posting.horoscope.mode} / {c.posting.horoscope.post_hour}:00",  # noqa: E501
            f"wordcloud: {c.posting.wordcloud.enabled} / {c.posting.wordcloud.interval_hours}h / {c.posting.wordcloud.timeline_source} / stock: {stock_count}語",  # noqa: E501
            f"poll: {c.posting.poll.enabled} / {c.posting.poll.mode} / {c.posting.poll.interval_hours}h / expire: {c.posting.poll.expire_hours}h / {c.posting.poll.timeline_source} / max: {c.posting.poll.max_notes_fetch} / prob: {c.posting.poll.probability}",  # noqa: E501
            f"event: {c.posting.event.enabled}",
        ]

        text = "\n".join(lines)
        await self._misskey.create_note(
            text=text,
            visibility="specified",
            reply_id=reply_id,
        )
        logger.info("statusを応答しました")

    async def _handle_post(self, reply_id: str, post_type: str) -> None:
        """/admin post の処理"""

        try:
            if post_type == "random":
                await self._post_manager._do_random_post(force=True)
            elif post_type == "scheduled":
                now = datetime.now(JST)
                time_key = f"{now.hour:02d}:{now.minute:02d}"
                await self._scheduled_post_manager._do_scheduled_post(time_key, force=True)
            elif post_type == "weekday":
                await self._weekday_post_manager._do_weekday_post(force=True)
            elif post_type == "timeline":
                await self._timeline_post_manager._do_timeline_post(force=True)
            elif post_type == "horoscope":
                await self._horoscope_manager._do_horoscope_post(force=True)
            elif post_type == "wordcloud":
                await self._wordcloud_manager._do_wordcloud_post(force=True)
            elif post_type == "poll":
                await self._poll_manager._do_poll_post(force=True)
            elif post_type == "event":
                await self._scheduled_post_manager._do_event_post(force=True)
            else:
                await self._reply_error(reply_id)
                return

            await self._misskey.create_note(
                text=f"✅ {post_type} 投稿を実行しました",
                visibility="specified",
                reply_id=reply_id,
            )
        except Exception as e:
            logger.error("強制投稿エラー: %s", e)
            await self._misskey.create_note(
                text=f"❌ {post_type} 投稿エラー: {e}",
                visibility="specified",
                reply_id=reply_id,
            )
