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


class TestNGWordManagerCacheFallback:
    """NGWordManager のキャッシュフォールバックテスト"""

    @pytest.mark.asyncio
    async def test_cache_fallback_when_external_fails(self, tmp_path) -> None:
        """外部取得失敗時にキャッシュファイルを使用する"""
        from unittest.mock import MagicMock

        # キャッシュファイルを作成
        cache_file = tmp_path / "ng_cache.txt"
        cache_file.write_text("キャッシュNG\nキャッシュワード\n", encoding="utf-8")

        # セッションがエラーを発生させるようにモック
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("接続エラー")

        mgr = NGWordManager(
            local_words=["ローカルNG"],
            external_urls=["https://example.com/ng.txt"],
            cache_file=str(cache_file),
            session=mock_session,
        )
        await mgr.initialize()

        # キャッシュのワードが含まれていること（lower()済みなので小文字に変換される）
        assert mgr.contains_ng_word("キャッシュNGです") is True
        # ローカルリストも含まれていること
        assert mgr.contains_ng_word("ローカルNGです") is True

    @pytest.mark.asyncio
    async def test_local_only_when_no_cache(self, tmp_path) -> None:
        """外部取得失敗かつキャッシュなし → ローカルリストのみで運用"""
        from unittest.mock import MagicMock

        cache_file = tmp_path / "nonexistent_cache.txt"
        # キャッシュファイルは作らない

        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("接続エラー")

        mgr = NGWordManager(
            local_words=["ローカルのみ"],
            external_urls=["https://example.com/ng.txt"],
            cache_file=str(cache_file),
            session=mock_session,
        )
        await mgr.initialize()

        # ローカルリストは有効
        assert mgr.contains_ng_word("ローカルのみのワード") is True
        # キャッシュがないので外部ワードは含まれない
        assert mgr.contains_ng_word("外部だけのワード") is False

    @pytest.mark.asyncio
    async def test_cache_saved_on_success(self, tmp_path) -> None:
        """外部取得成功時にキャッシュが保存される"""
        from unittest.mock import AsyncMock, MagicMock

        cache_file = tmp_path / "ng_cache.txt"

        # 成功するモックレスポンス
        mock_response = AsyncMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value="外部NG\n外部ワード\n")

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response

        mgr = NGWordManager(
            local_words=["ローカル"],
            external_urls=["https://example.com/ng.txt"],
            cache_file=str(cache_file),
            session=mock_session,
        )
        await mgr.initialize()

        # キャッシュファイルが作成されていること
        assert cache_file.exists()
        cache_content = cache_file.read_text(encoding="utf-8")
        # lower()済みで保存されている
        assert "外部ng" in cache_content

    @pytest.mark.asyncio
    async def test_no_session_falls_back_to_cache(self, tmp_path) -> None:
        """セッションなしの場合はキャッシュを使用する"""
        cache_file = tmp_path / "ng_cache.txt"
        cache_file.write_text("キャッシュのみ\n", encoding="utf-8")

        mgr = NGWordManager(
            local_words=["ローカル"],
            external_urls=["https://example.com/ng.txt"],
            cache_file=str(cache_file),
            session=None,  # セッションなし
        )
        await mgr.initialize()

        # キャッシュのワードが含まれていること
        assert mgr.contains_ng_word("キャッシュのみワード") is True
        # ローカルリストも有効
        assert mgr.contains_ng_word("ローカルお話") is True
