"""NGワード管理

ローカル + 外部URL + キャッシュの3層構造で NGワードを管理する。
"""

import logging
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)


class NGWordManager:
    """NGワード管理クラス

    起動時にローカルリスト + 外部リストを結合してメモリに保持する。
    外部リスト取得失敗時はキャッシュファイルにフォールバックする。
    """

    def __init__(
        self,
        local_words: list[str],
        external_urls: list[str],
        cache_file: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._local_words = local_words
        self._external_urls = external_urls
        self._cache_file = Path(cache_file)
        self._session = session
        self._ng_words: set[str] = set()

    async def initialize(self) -> None:
        """NGワードリストを初期化する。"""
        # ローカルリストの読み込み（前処理: lower + strip + 空文字除外）
        local = {w.lower().strip() for w in self._local_words if w.strip()}

        # 外部リストの取得
        external = await self._fetch_external_words()

        # 結合して重複排除
        self._ng_words = local | external
        logger.info(
            "NGワードリストを初期化しました（ローカル: %d 件, 外部: %d 件, 合計: %d 件）",
            len(local),
            len(external),
            len(self._ng_words),
        )

    async def refresh(self) -> None:
        """外部リストを再取得してNGワードセットを再構築する。"""
        external = await self._fetch_external_words()
        local = {w.lower().strip() for w in self._local_words if w.strip()}
        self._ng_words = local | external
        logger.info("NGワードリストを更新しました（合計: %d 件）", len(self._ng_words))

    def contains_ng_word(self, text: str) -> bool:
        """テキストにNGワードが含まれているかを判定する。

        Phase 1: 単純部分一致（substring モード）
        前処理: 対象テキストに lower() を適用
        """
        if not text:
            return False

        text_lower = text.lower()
        return any(ng in text_lower for ng in self._ng_words if ng)

    @property
    def word_count(self) -> int:
        """現在のNGワード数を返す。"""
        return len(self._ng_words)

    async def _fetch_external_words(self) -> set[str]:
        """外部URLからNGワードリストを取得する。

        成功時: キャッシュファイルに保存
        失敗時: キャッシュファイルがあればそれを使用
        キャッシュもなし: 空セットを返す（警告ログ）
        """
        external_words: set[str] = set()

        if not self._external_urls:
            return external_words

        if self._session is None:
            logger.warning(
                "HTTP セッションが未設定のため、外部NGワードリストを取得できません"
            )
            return self._load_cache()

        for url in self._external_urls:
            try:
                async with self._session.get(
                    url, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        words = {
                            w.lower().strip() for w in text.splitlines() if w.strip()
                        }
                        external_words |= words
                        logger.info(
                            "外部NGワードリストを取得しました: %s（%d 件）",
                            url[:100],
                            len(words),
                        )
                    else:
                        logger.warning(
                            "外部NGワードリストの取得に失敗しました: %s (status=%d)",
                            url[:100],
                            resp.status,
                        )
            except Exception as e:
                logger.warning(
                    "外部NGワードリストの取得に失敗しました: %s (%s)",
                    url[:100],
                    str(e),
                )

        if external_words:
            # キャッシュに保存
            self._save_cache(external_words)
            return external_words
        else:
            # 外部取得失敗 → キャッシュファイルにフォールバック
            return self._load_cache()

    def _save_cache(self, words: set[str]) -> None:
        """NGワードをキャッシュファイルに保存する。"""
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._cache_file.write_text("\n".join(sorted(words)), encoding="utf-8")
            logger.debug("NGワードキャッシュを保存しました: %s", self._cache_file)
        except Exception as e:
            logger.warning("NGワードキャッシュの保存に失敗しました: %s", str(e))

    def _load_cache(self) -> set[str]:
        """キャッシュファイルからNGワードを読み込む。"""
        if self._cache_file.exists():
            try:
                text = self._cache_file.read_text(encoding="utf-8")
                words = {w.lower().strip() for w in text.splitlines() if w.strip()}
                logger.info("NGワードキャッシュからロードしました（%d 件）", len(words))
                return words
            except Exception as e:
                logger.warning("NGワードキャッシュの読み込みに失敗しました: %s", str(e))

        logger.warning(
            "外部NGワードリストを取得できず、キャッシュもありません。ローカルリストのみで運用します"
        )
        return set()
