import pytest
from bot.utils.tokenizer import _VISIBLE_PATTERN

def test_visible_pattern():
    # 正常な例（可視文字を含む）
    assert _VISIBLE_PATTERN.search("あ")
    assert _VISIBLE_PATTERN.search("アイウ")
    assert _VISIBLE_PATTERN.search("漢字")
    assert _VISIBLE_PATTERN.search("Word")
    assert _VISIBLE_PATTERN.search("123")
    assert _VISIBLE_PATTERN.search("全角スペースの後　")

    # 不可視文字のみの例
    assert not _VISIBLE_PATTERN.search("　")  # 全角スペース
    assert not _VISIBLE_PATTERN.search(" ")   # 半角スペース
    assert not _VISIBLE_PATTERN.search("\n")
    assert not _VISIBLE_PATTERN.search("\t")
    assert not _VISIBLE_PATTERN.search("　　\n  ")
    assert not _VISIBLE_PATTERN.search("🍔") # Emoji 等 (指定外)
