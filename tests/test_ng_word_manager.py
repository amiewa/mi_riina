"""NGワード管理のテスト"""

import pytest

from bot.utils.ng_word_manager import NGWordManager


class TestNGWordManager:
    """NGWordManager のテスト"""

    @pytest.fixture
    def ng_manager(self) -> NGWordManager:
        """テスト用のNGWordManagerを返す。"""
        return NGWordManager(
            local_words=["死ね", "バカ", ""],
            external_urls=[],
            cache_file="/tmp/test_ng_cache.txt",
        )

    @pytest.mark.asyncio
    async def test_initialize(self, ng_manager: NGWordManager) -> None:
        """初期化でローカルリストが読み込まれる"""
        await ng_manager.initialize()
        assert ng_manager.word_count >= 2  # "死ね", "バカ"

    @pytest.mark.asyncio
    async def test_contains_ng_word_exact(self, ng_manager: NGWordManager) -> None:
        """NGワードの完全一致検出"""
        await ng_manager.initialize()
        assert ng_manager.contains_ng_word("死ね") is True
        assert ng_manager.contains_ng_word("バカ") is True

    @pytest.mark.asyncio
    async def test_contains_ng_word_substring(self, ng_manager: NGWordManager) -> None:
        """NGワードの部分一致検出"""
        await ng_manager.initialize()
        assert ng_manager.contains_ng_word("お前死ねよ") is True
        assert ng_manager.contains_ng_word("このバカ野郎") is True

    @pytest.mark.asyncio
    async def test_case_insensitive(self, ng_manager: NGWordManager) -> None:
        """大文字小文字を区別しない"""
        mgr = NGWordManager(
            local_words=["hello"],
            external_urls=[],
            cache_file="/tmp/test_ng_cache.txt",
        )
        await mgr.initialize()
        assert mgr.contains_ng_word("HELLO world") is True
        assert mgr.contains_ng_word("Hello World") is True

    @pytest.mark.asyncio
    async def test_empty_string_excluded(self, ng_manager: NGWordManager) -> None:
        """空文字のNGワードは除外される"""
        await ng_manager.initialize()
        # 空文字が含まれていても、すべてにマッチしてはいけない
        assert ng_manager.contains_ng_word("普通のテキスト") is False

    @pytest.mark.asyncio
    async def test_safe_text(self, ng_manager: NGWordManager) -> None:
        """NGワードを含まないテキスト"""
        await ng_manager.initialize()
        assert ng_manager.contains_ng_word("こんにちは") is False
        assert ng_manager.contains_ng_word("今日はいい天気") is False

    @pytest.mark.asyncio
    async def test_empty_input(self, ng_manager: NGWordManager) -> None:
        """空入力はFalse"""
        await ng_manager.initialize()
        assert ng_manager.contains_ng_word("") is False
        assert ng_manager.contains_ng_word(None) is False  # type: ignore

    @pytest.mark.asyncio
    async def test_whitespace_stripped(self) -> None:
        """NGワードの前後の空白が除去される"""
        mgr = NGWordManager(
            local_words=["  テスト  ", " NG "],
            external_urls=[],
            cache_file="/tmp/test_ng_cache.txt",
        )
        await mgr.initialize()
        assert mgr.contains_ng_word("テストです") is True
        assert mgr.contains_ng_word("これはNGです") is True  # NGはlower()で「ng」になりマッチする
        assert mgr.contains_ng_word("これはngです") is True
