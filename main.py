"""りいなbot v2 エントリポイント

起動・終了シーケンスを管理する。
"""

import asyncio
import logging
import logging.handlers
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.core.config import AppConfig, load_config
from bot.core.database import Database
from bot.core.gemini_client import GeminiClient
from bot.core.misskey_client import MisskeyClient
from bot.core.ollama_client import OllamaClient
from bot.managers.follow_manager import FollowManager
from bot.managers.horoscope_manager import HoroscopeManager
from bot.managers.poll_manager import PollManager
from bot.managers.post_manager import PostManager
from bot.managers.reaction_manager import ReactionManager
from bot.managers.reply_manager import ReplyManager
from bot.managers.scheduled_post_manager import ScheduledPostManager
from bot.managers.streaming_manager import StreamingManager
from bot.managers.timeline_post_manager import TimelinePostManager
from bot.managers.weekday_post_manager import WeekdayPostManager
from bot.managers.wordcloud_manager import WordcloudManager
from bot.utils.ng_word_manager import NGWordManager
from bot.utils.rate_limiter import RateLimiter
from bot.utils.serif_loader import SerifLoader
from bot.utils.tokenizer import SudachiTokenizer

logger = logging.getLogger("bot")

JST = ZoneInfo("Asia/Tokyo")


def setup_logging(config: AppConfig) -> None:
    """ログを設定する。"""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_dir = Path(config.storage.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # ルートロガーの設定
    root_logger = logging.getLogger("bot")
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))

    # フォーマッタ
    formatter = logging.Formatter(
        fmt=config.logging.format,
        datefmt=config.logging.date_format,
    )

    # コンソール出力
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # ファイル出力（日付ローテーション）
    today = datetime.now(JST).strftime("%Y-%m-%d")
    log_filename = config.logging.file_name_pattern.replace("{date}", today)
    log_filepath = log_dir / log_filename

    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_filepath),
        when=config.logging.file_rotation,
        encoding="utf-8",
        backupCount=config.logging.file_retention_days,
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    logger.info("ログを設定しました（レベル: %s）", log_level)


async def main() -> None:
    """メインの起動シーケンス"""
    # 1. config.yaml + .env ロード
    try:
        config = load_config("config/config.yaml")
    except Exception as e:
        print(f"設定ファイルの読み込みに失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. ログ設定
    setup_logging(config)
    logger.info("りいなbot v2 を起動中...")

    # 3. 停止シグナル用イベント
    stop_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("停止シグナルを受信しました")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    # 4. Database 初期化
    db = Database(config.storage.database_path)
    try:
        Path(config.storage.database_path).parent.mkdir(parents=True, exist_ok=True)
        await db.connect()
    except Exception as e:
        logger.error("データベースの初期化に失敗しました: %s", str(e))
        sys.exit(1)

    # 5. aiohttp.ClientSession 生成
    session = aiohttp.ClientSession()

    try:
        # 6. NGWordManager 初期化
        ng_word_manager = NGWordManager(
            local_words=config.ng_words.local,
            external_urls=config.ng_words.external_urls,
            cache_file=config.ng_words.cache_file,
            session=session,
        )
        await ng_word_manager.initialize()

        # 7. Tokenizer 初期化
        tokenizer = SudachiTokenizer(dict_type=config.bot.tokenizer.sudachi_dict)

        # 8. AIClient 初期化
        if config.ai.provider == "gemini":
            gemini_key = os.getenv("GEMINI_API_KEY", "")
            if not gemini_key:
                logger.error("GEMINI_API_KEY が設定されていません")
                sys.exit(1)
            ai_client = GeminiClient(
                api_key=gemini_key,
                model=config.ai.gemini.model,
                max_output_tokens=config.ai.gemini.max_output_tokens,
                temperature=config.ai.gemini.temperature,
                timeout_seconds=config.ai.timeout_seconds,
                input_max_chars=config.ai.input_max_chars,
            )
        else:
            ollama_url = os.getenv("OLLAMA_BASE_URL", "")
            if not ollama_url:
                logger.error("OLLAMA_BASE_URL が設定されていません")
                sys.exit(1)
            ai_client = OllamaClient(
                base_url=ollama_url,
                model=config.ai.ollama.model,
                temperature=config.ai.ollama.temperature,
                num_predict=config.ai.ollama.num_predict,
                timeout_seconds=config.ai.timeout_seconds,
                input_max_chars=config.ai.input_max_chars,
                session=session,
            )

        # 9. MisskeyClient 初期化
        misskey_url = os.getenv("MISSKEY_INSTANCE_URL", "")
        misskey_token = os.getenv("MISSKEY_API_TOKEN", "")
        if not misskey_url or not misskey_token:
            logger.error(
                "MISSKEY_INSTANCE_URL / MISSKEY_API_TOKEN が設定されていません"
            )
            sys.exit(1)

        misskey = MisskeyClient(misskey_url, misskey_token)
        try:
            await misskey.initialize()
        except Exception as e:
            logger.error("Misskey クライアントの初期化に失敗しました: %s", str(e))
            sys.exit(1)

        # 台詞ファイル読み込み
        serif_loader = SerifLoader()
        serif_loader.load_all()
        serif_loader.start_watching()

        # レート制限
        rate_limiter = RateLimiter(
            db=db,
            max_per_user_per_hour=config.reply.rate_limit.max_per_user_per_hour,
        )

        # 10. 各 Manager 初期化
        post_manager = PostManager(config, db, misskey, serif_loader)
        scheduled_post_manager = ScheduledPostManager(config, db, misskey, serif_loader)
        weekday_post_manager = WeekdayPostManager(config, db, misskey, serif_loader)
        timeline_post_manager = TimelinePostManager(
            config, db, misskey, tokenizer, ng_word_manager
        )
        reply_manager = ReplyManager(
            config, db, misskey, ai_client, ng_word_manager, rate_limiter, serif_loader
        )
        reaction_manager = ReactionManager(config, db, misskey)
        follow_manager = FollowManager(config, db, misskey)
        poll_manager = PollManager(
            config, db, misskey, ai_client, tokenizer, ng_word_manager, serif_loader
        )
        horoscope_manager = HoroscopeManager(
            config, db, misskey, ai_client, ng_word_manager
        )
        wordcloud_manager = WordcloudManager(
            config, db, misskey, tokenizer, ng_word_manager, session
        )
        await wordcloud_manager.initialize()

        # 11. StreamingManager にイベントハンドラ登録
        streaming = StreamingManager(
            instance_url=misskey_url,
            token=misskey_token,
            channels=["homeTimeline", "main"],
        )

        # NoteEvent ハンドラ
        streaming.on("note", reaction_manager.on_note)
        streaming.on("note", wordcloud_manager.on_note)  # ストック収集

        # MentionEvent ハンドラ
        streaming.on("mention", reply_manager.on_mention)
        streaming.on("mention", follow_manager.on_mention)

        # FollowedEvent ハンドラ
        streaming.on("followed", follow_manager.on_followed)

        # 12. APScheduler 起動
        scheduler = AsyncIOScheduler(timezone=JST)

        # ランダム投稿
        if config.posting.random_post.enabled:
            scheduler.add_job(
                post_manager.execute_random_post,
                "interval",
                minutes=config.posting.random_post.interval_minutes,
                misfire_grace_time=60,
            )

        # 定時投稿
        if config.posting.scheduled_posts.enabled:
            for time_key in scheduled_post_manager.get_scheduled_times():
                hour, minute = map(int, time_key.split(":"))
                scheduler.add_job(
                    scheduled_post_manager.execute_scheduled_post,
                    "cron",
                    hour=hour,
                    minute=minute,
                    args=[time_key],
                    misfire_grace_time=60,
                )

        # 曜日別投稿（毎分チェック）
        if config.posting.weekday_posts.enabled:
            scheduler.add_job(
                weekday_post_manager.check_and_post,
                "cron",
                minute="*",
                misfire_grace_time=60,
            )

        # TL連動投稿
        if config.posting.timeline_post.enabled:
            scheduler.add_job(
                timeline_post_manager.execute_timeline_post,
                "interval",
                minutes=config.posting.timeline_post.interval_minutes,
                misfire_grace_time=60,
            )

        # アンケート
        if config.posting.poll.enabled:
            scheduler.add_job(
                poll_manager.execute_poll,
                "cron",
                hour=f"*/{config.posting.poll.interval_hours}",
                minute=0,
                misfire_grace_time=60,
            )

        # 星座占い
        if config.posting.horoscope.enabled:
            scheduler.add_job(
                horoscope_manager.execute_horoscope,
                "cron",
                hour=config.posting.horoscope.post_hour,
                minute=0,
                misfire_grace_time=60,
            )

        # ワードクラウド
        if config.posting.wordcloud.enabled:
            scheduler.add_job(
                wordcloud_manager.execute_wordcloud,
                "cron",
                hour=f"*/{config.posting.wordcloud.interval_hours}",
                minute=0,
                misfire_grace_time=60,
            )

        # フォロー同期
        scheduler.add_job(
            follow_manager.sync_followers,
            "interval",
            minutes=config.follow.check_interval_minutes,
            misfire_grace_time=60,
        )

        # 記念日イベント投稿のスケジュール登録
        event_key = scheduled_post_manager.get_today_event_key()
        if event_key and config.posting.event.enabled:
            import random

            now = datetime.now(JST)
            # 7〜22時のランダムな時刻
            if now.hour < 22:
                event_hour = random.randint(max(7, now.hour + 1), 21)
                event_minute = random.randint(0, 59)
                scheduler.add_job(
                    scheduled_post_manager.execute_event_post,
                    "date",
                    run_date=now.replace(
                        hour=event_hour, minute=event_minute, second=0
                    ),
                    args=[event_key],
                    misfire_grace_time=60,
                )
                logger.info(
                    "イベント投稿をスケジュールしました: %s (%02d:%02d)",
                    event_key,
                    event_hour,
                    event_minute,
                )

        # メンテナンスジョブ
        if config.maintenance.enabled:
            # DBクリーンアップ
            cleanup_h, cleanup_m = map(int, config.maintenance.cleanup_time.split(":"))
            scheduler.add_job(
                db.cleanup,
                "cron",
                hour=cleanup_h,
                minute=cleanup_m,
                args=[config.maintenance.cleanup_days],
                misfire_grace_time=300,
            )

            # NGワードリフレッシュ
            ng_h, ng_m = map(int, config.maintenance.ng_word_refresh_time.split(":"))
            scheduler.add_job(
                ng_word_manager.refresh,
                "cron",
                hour=ng_h,
                minute=ng_m,
                misfire_grace_time=300,
            )

            # 自己削除
            del_h, del_m = map(int, config.maintenance.auto_delete_time.split(":"))
            scheduler.add_job(
                _execute_auto_delete,
                "cron",
                hour=del_h,
                minute=del_m,
                args=[db, misskey],
                misfire_grace_time=300,
            )

        scheduler.start()
        logger.info("スケジューラを起動しました")

        # 13. StreamingManager 起動
        streaming_task = asyncio.create_task(streaming.start())
        logger.info("Bot の起動が完了しました")

        # 停止シグナルを待機
        await stop_event.wait()

        # ========== 終了シーケンス ==========
        logger.info("Bot を停止中...")

        # StreamingManager 停止
        await streaming.stop()
        streaming_task.cancel()
        try:
            await streaming_task
        except asyncio.CancelledError:
            pass

        # スケジューラ停止
        scheduler.shutdown(wait=True)

        # 台詞ファイル監視停止
        serif_loader.stop_watching()

    finally:
        # AIClient 終了
        try:
            await ai_client.close()
        except Exception:
            pass

        # aiohttp セッション終了
        await session.close()

        # Misskey クライアント終了
        try:
            await misskey.close()
        except Exception:
            pass

        # DB 終了
        await db.close()

    logger.info("Bot を停止しました")


async def _execute_auto_delete(db: Database, misskey: MisskeyClient) -> None:
    """自己削除を実行する。"""
    posts = await db.get_posts_to_delete()
    for post in posts:
        try:
            if post["note_id"]:
                await misskey.delete_note(post["note_id"])

            # ワードクラウドのドライブファイル削除
            if post.get("drive_file_id"):
                await misskey.delete_file(post["drive_file_id"])

            await db.mark_post_deleted(post["id"])
            logger.info(
                "投稿を自動削除しました（note_id=%s, post_type=%s）",
                post["note_id"],
                post["post_type"],
            )
        except Exception as e:
            logger.error(
                "投稿の自動削除に失敗しました（note_id=%s）: %s",
                post["note_id"],
                str(e),
            )


if __name__ == "__main__":
    asyncio.run(main())
