"""MisskeyClient の ClientSession 注入テスト

main.py が生成する共有 aiohttp.ClientSession をコンストラクタで受け取り、
initialize()/close() では独自セッションを生成・クローズしないことを検証する。
"""

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from bot.core.misskey_client import MisskeyClient


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.closed = False
    return session


@pytest.mark.asyncio
async def test_constructor_stores_injected_session(mock_session: MagicMock) -> None:
    """コンストラクタに渡した session がそのまま使われる"""
    client = MisskeyClient("https://example.com", "token", mock_session)
    assert client._session is mock_session


@pytest.mark.asyncio
async def test_initialize_does_not_create_new_session(mock_session: MagicMock) -> None:
    """initialize() は独自セッションを生成しない（注入されたものを使い続ける）"""
    client = MisskeyClient("https://example.com", "token", mock_session)

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"id": "bot_id", "username": "riina"})
    mock_session.post.return_value.__aenter__.return_value = mock_resp

    await client.initialize()

    assert client._session is mock_session
    assert client.bot_user_id == "bot_id"


@pytest.mark.asyncio
async def test_close_does_not_close_injected_session(mock_session: MagicMock) -> None:
    """close() は所有権が main.py にあるセッションをクローズしない"""
    client = MisskeyClient("https://example.com", "token", mock_session)

    await client.close()

    mock_session.close.assert_not_called()
