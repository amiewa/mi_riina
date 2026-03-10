"""ワードクラウドマネージャー

WebSocket で受信したノートを常時ストックし、
interval_hours ごとにストックを消費してワードクラウド画像を生成・投稿する。
"""

import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp

from bot.core.config import AppConfig
from bot.core.database import Database
from bot.core.misskey_client import MisskeyClient
from bot.core.models import NoteEvent
from bot.utils.ng_word_manager import NGWordManager
from bot.utils.text_cleaner import clean_note_text
from bot.utils.tokenizer import TokenizerBase

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")

# チャンネル → ソース名の対応（timeline_source との照合用）
SOURCE_MAP = {
    "home": "home",
    "local": "local",
    "social": "social",
    "global": "global",
}

# フォントダウンロード URL（M PLUS Rounded 1c Regular 400）
FONT_URL = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/"
    "roundedmplus1c/RoundedMplus1c-Regular.ttf"
)
FONT_FILENAME = "MPLUSRounded1c-Regular.ttf"
DEFAULT_FONT_DIR = "data/fonts"


class WordcloudManager:
    """ワードクラウドマネージャー"""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        misskey: MisskeyClient,
        tokenizer: TokenizerBase,
        ng_word_manager: NGWordManager,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._config = config
        self._db = db
        self._misskey = misskey
        self._tokenizer = tokenizer
        self._ng_word_manager = ng_word_manager
        self._session = session
        self._wc_config = config.posting.wordcloud

        # 形態素解析の同時実行制限
        self._analysis_semaphore = asyncio.Semaphore(
            self._wc_config.analysis_concurrency
        )

        # フォントパス（初期化時に解決）
        self._font_path: str | None = None

    async def initialize(self) -> None:
        """初期化処理: フォントの確保。"""
        if not self._wc_config.enabled:
            return

        self._font_path = await self._ensure_font()
        if self._font_path:
            logger.info("ワードクラウド用フォントを確認しました: %s", self._font_path)
        else:
            logger.warning(
                "ワードクラウド用フォントが見つかりません。"
                "デフォルトフォントで生成します（日本語表示は崩れる可能性があります）"
            )

    async def on_note(self, event: NoteEvent) -> None:
        """StreamingManager から呼ばれるノートイベントハンドラ。

        ノートからキーワードを抽出し、ワードクラウド用ストックに保存する。
        """
        if not self._wc_config.enabled:
            return

        # bot 自身のノートはスキップ
        if event.user_id == self._misskey.bot_user_id:
            return

        # visibility フィルタ: followers / specified は除外
        if event.visibility in ("followers", "specified"):
            return

        # Renote（renote_id あり かつ text が null）はスキップ
        if event.renote_id is not None and event.text is None:
            return

        # テキストがないノートはスキップ
        if not event.text:
            return

        # timeline_source に対応するチャンネルのみ対象
        target_source = self._wc_config.timeline_source
        if event.channel != target_source:
            return

        # テキスト長チェック
        if len(event.text) > self._wc_config.max_note_length:
            return

        # テキストクリーニング
        cleaned = clean_note_text(event.text)
        if not cleaned:
            return

        # 形態素解析（Semaphore + to_thread でブロッキングを回避）
        try:
            async with self._analysis_semaphore:
                keywords = await asyncio.to_thread(
                    self._tokenizer.extract_keywords, cleaned
                )
        except Exception as e:
            logger.debug("形態素解析に失敗しました: %s", str(e))
            return

        if not keywords:
            return

        # max_keywords_per_note で制限
        keywords = keywords[: self._wc_config.max_keywords_per_note]

        # NGワードフィルタリングと長さ制限（min_keyword_length以上の単語を抽出）
        valid_keywords = []
        for kw in keywords:
            if len(
                kw
            ) >= self._wc_config.min_keyword_length and not self._ng_word_manager.contains_ng_word(
                kw
            ):
                valid_keywords.append(kw)

        if not valid_keywords:
            return

        # DB に保存
        try:
            await self._db.stock_words(valid_keywords)
        except Exception as e:
            logger.error("ワードストックの保存に失敗しました: %s", str(e))
            return

        # ストック数チェック（max_stock_size + 100 超過時にトリム）
        try:
            count = await self._db.get_stock_count()
            threshold = self._wc_config.max_stock_size + 100
            if count > threshold:
                await self._db.trim_word_stock(self._wc_config.max_stock_size)
                logger.debug(
                    "ワードストックをトリムしました（%d → %d）",
                    count,
                    self._wc_config.max_stock_size,
                )
        except Exception as e:
            logger.error("ワードストックのトリムに失敗しました: %s", str(e))

    async def execute_wordcloud(self) -> None:
        """ワードクラウドを生成・投稿する。"""
        if not self._wc_config.enabled:
            return

        await self._do_wordcloud_post()

    async def _do_wordcloud_post(self, force: bool = False) -> None:
        """実際のワードクラウド投稿処理。AdminManagerからも呼ばれる。"""

        now = datetime.now(JST)
        # execution_key: 時間枠ベース
        execution_key = f"wordcloud:{now.strftime('%Y-%m-%dT%H:00')}"

        if force:
            execution_key = None

        # execution_key 二重投稿チェック
        try:
            post_id = await self._db.insert_post(
                post_type="wordcloud",
                execution_key=execution_key,
                content=None,
            )
        except Exception:
            if not force:
                logger.info(
                    "ワードクラウドは既に投稿済みです（execution_key=%s）",
                    execution_key,
                )
                return
            raise

        try:
            # ストック数チェック
            stock_count = await self._db.get_stock_count()
            if stock_count < self._wc_config.min_stock_words:
                logger.info(
                    "ワードストックが不足しています（%d / %d）。スキップします",
                    stock_count,
                    self._wc_config.min_stock_words,
                )
                await self._db.delete_post_by_id(post_id)
                return

            # ストック取得 + 頻度集計
            words = await self._db.get_word_stock()
            word_counts = Counter(words)

            # 画像生成
            image_path = await self._generate_image(word_counts)

            # 投稿テキスト
            interval = self._wc_config.interval_hours
            text = f"直近 {interval}時間のワードクラウド"

            # 上位頻出語をcontent用に保存
            top_words = [w for w, _ in word_counts.most_common(10)]
            content_summary = ", ".join(top_words)

            # 投稿（最大3回リトライ）
            note_id = None
            drive_file_id = None

            for attempt in range(3):
                try:
                    # ドライブにアップロード
                    drive_file_id = await self._misskey.upload_file(str(image_path))

                    # ノート投稿
                    note_id = await self._misskey.create_note(
                        text=text,
                        visibility=self._config.posting.default_visibility,
                        file_ids=[drive_file_id],
                    )
                    break
                except Exception as e:
                    logger.error(
                        "ワードクラウドの投稿に失敗しました（試行 %d/3）: %s",
                        attempt + 1,
                        str(e),
                    )
                    if attempt < 2:
                        await asyncio.sleep(10)

            # 自動削除スケジュール計算
            auto_delete = self._config.posting.auto_delete.wordcloud
            scheduled_delete_at = None
            if auto_delete.enabled:
                delete_time = now + timedelta(hours=auto_delete.after_hours)
                scheduled_delete_at = delete_time.isoformat()

            if note_id:
                # 投稿成功
                await self._db.execute(
                    "UPDATE posts SET content = ?, note_id = ?, drive_file_id = ?, "
                    "scheduled_delete_at = ? WHERE id = ?",
                    (
                        content_summary,
                        note_id,
                        drive_file_id,
                        scheduled_delete_at,
                        post_id,
                    ),
                )
                # ストッククリア
                await self._db.clear_word_stock()
                # 一時ファイル削除
                try:
                    image_path.unlink()
                except Exception:
                    pass
                logger.info(
                    "ワードクラウドを投稿しました（note_id=%s, words=%d, execution_key=%s）",
                    note_id,
                    stock_count,
                    execution_key,
                )
            else:
                # 3回失敗: ストッククリア + ログ
                await self._db.clear_word_stock()
                await self._db.delete_post_by_id(post_id)
                logger.error(
                    "ワードクラウドの投稿が3回失敗しました。"
                    "ストックをクリアし、画像はローカルに残します: %s",
                    image_path,
                )

        except Exception as e:
            logger.error("ワードクラウドの生成・投稿でエラーが発生しました: %s", str(e))
            try:
                await self._db.delete_post_by_id(post_id)
            except Exception:
                pass

    async def _generate_image(self, word_counts: Counter) -> Path:
        """ワードクラウド画像を生成する。

        Args:
            word_counts: 単語と頻度の Counter

        Returns:
            生成された画像ファイルのパス
        """
        from wordcloud import WordCloud

        # 出力ディレクトリ
        output_dir = Path(self._config.storage.wordcloud_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(JST)
        filename = f"wordcloud_{now.strftime('%Y%m%d_%H%M%S')}.png"
        output_path = output_dir / filename

        # WordCloud 生成（CPU バウンドなので to_thread）
        def _generate() -> None:
            wc = WordCloud(
                font_path=self._font_path,
                width=self._wc_config.width,
                height=self._wc_config.height,
                background_color=self._wc_config.background_color,
                colormap=self._wc_config.colormap,
            )
            wc.generate_from_frequencies(dict(word_counts))
            wc.to_file(str(output_path))

        await asyncio.to_thread(_generate)
        logger.debug("ワードクラウド画像を生成しました: %s", output_path)

        return output_path

    async def _ensure_font(self) -> str | None:
        """フォントファイルを確認し、なければダウンロードする。

        Returns:
            フォントファイルのパス。ダウンロード失敗時は None。
        """
        # config で明示指定されている場合はそちらを優先
        if self._wc_config.font_path:
            font = Path(self._wc_config.font_path)
            if font.exists():
                return str(font)
            logger.warning(
                "指定されたフォントパスが見つかりません: %s", self._wc_config.font_path
            )

        # デフォルトパスを確認
        font_dir = Path(DEFAULT_FONT_DIR)
        font_path = font_dir / FONT_FILENAME

        if font_path.exists():
            return str(font_path)

        # ダウンロード
        logger.info("ワードクラウド用フォントをダウンロード中...")
        try:
            font_dir.mkdir(parents=True, exist_ok=True)

            if self._session:
                async with self._session.get(
                    FONT_URL, timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        font_path.write_bytes(data)
                        logger.info("フォントをダウンロードしました: %s", font_path)
                        return str(font_path)
                    else:
                        logger.warning(
                            "フォントのダウンロードに失敗しました（status=%d）",
                            resp.status,
                        )
            else:
                logger.warning(
                    "HTTP セッションが未設定のため、フォントをダウンロードできません"
                )

        except Exception as e:
            logger.warning("フォントのダウンロードに失敗しました: %s", str(e))

        return None
