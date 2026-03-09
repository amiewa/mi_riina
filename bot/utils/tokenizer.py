"""形態素解析ユーティリティ

SudachiPy を使用した形態素解析。
抽象クラス経由で差し替え可能な構造（将来 MeCab 等）。
"""

import logging
import re
import threading
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# 日本語の可視文字（漢字・カタカナ・ひらがな・英数字）を1文字以上含むことを要求するパターン
_VISIBLE_PATTERN = re.compile(
    r"[\u4E00-\u9FFF\u3400-\u4DBF\u30A0-\u30FF\u3040-\u309F\uFF66-\uFF9Fa-zA-Zａ-ｚＡ-Ｚ0-9０-９]"
)


class TokenizerBase(ABC):
    """形態素解析の抽象基底クラス"""

    @abstractmethod
    def extract_keywords(self, text: str) -> list[str]:
        """テキストからキーワード（名詞・固有名詞）を抽出する。

        Args:
            text: 入力テキスト（クリーニング済みを前提）

        Returns:
            抽出されたキーワードのリスト
        """
        ...


class SudachiTokenizer(TokenizerBase):
    """SudachiPy による形態素解析

    config の sudachi_dict (small/core/full) で辞書を選択する。
    スレッドセーフのために threading.Lock を使用する。
    """

    def __init__(self, dict_type: str = "core") -> None:
        """初期化する。

        Args:
            dict_type: 辞書タイプ（small / core / full）
        """
        from sudachipy import Dictionary, SplitMode

        self._lock = threading.Lock()
        self._split_mode = SplitMode.C  # 最長分割

        # 辞書タイプに応じて初期化
        try:
            self._tokenizer = Dictionary(dict_type=dict_type).create()
            logger.info("SudachiPy を初期化しました（辞書: %s）", dict_type)
        except Exception as e:
            logger.error("SudachiPy の初期化に失敗しました: %s", str(e))
            raise

    def extract_keywords(self, text: str) -> list[str]:
        """テキストからキーワード（名詞・固有名詞）を抽出する。"""
        if not text:
            return []

        with self._lock:
            try:
                morphemes = self._tokenizer.tokenize(text, self._split_mode)
                keywords = []
                for m in morphemes:
                    pos = m.part_of_speech()
                    # 名詞（一般名詞・固有名詞）を抽出
                    if pos[0] == "名詞" and pos[1] in ("普通名詞", "固有名詞"):
                        surface = m.surface().strip()
                        # 1文字の名詞はスキップ（助詞等のノイズを減らす）
                        if len(surface) < 2:
                            continue
                        # 可視文字が含まれていない場合はスキップ（全角スペースのみなどを除外）
                        if not _VISIBLE_PATTERN.search(surface):
                            continue
                            
                        keywords.append(surface)
                return keywords
            except Exception as e:
                logger.error("形態素解析に失敗しました: %s", str(e))
                return []
