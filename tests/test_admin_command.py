import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.managers.admin_manager import AdminManager
from bot.core.models import MentionEvent
from bot.core.config import AppConfig


@pytest.fixture
def mock_config():
    config = MagicMock(spec=AppConfig)
    config.admin = MagicMock()
    config.admin.usernames = ["admin_user"]
    return config


@pytest.fixture
def mock_misskey():
    client = AsyncMock()
    # adminの解決用モック
    client.get_user_by_username.return_value = {"id": "admin_user_id"}
    return client


@pytest.fixture
def admin_manager(mock_config, mock_misskey):
    am = AdminManager(
        config=mock_config,
        db=AsyncMock(),
        misskey=mock_misskey,
        serif_loader=MagicMock(),
        post_manager=AsyncMock(),
        scheduled_post_manager=AsyncMock(),
        weekday_post_manager=AsyncMock(),
        timeline_post_manager=AsyncMock(),
        horoscope_manager=AsyncMock(),
        wordcloud_manager=AsyncMock(),
        poll_manager=AsyncMock(),
    )
    return am


@pytest.mark.asyncio
async def test_try_handle_not_admin_command(admin_manager):
    """/admin で始まらない場合は False を返す"""
    await admin_manager.initialize()
    event = MentionEvent(
        note_id="n1",
        user_id="admin_user_id",
        text="こんにちは",
        username="u",
        cw=None,
        visibility="public",
    )
    handled = await admin_manager.try_handle(event)
    assert not handled


@pytest.mark.asyncio
async def test_try_handle_unauthorized_user(admin_manager):
    """非管理者の /admin は無視（後続に渡さないため True）"""
    await admin_manager.initialize()
    event = MentionEvent(
        note_id="n1",
        user_id="other_user_id",
        text="/admin status",
        username="u",
        cw=None,
        visibility="public",
    )
    handled = await admin_manager.try_handle(event)
    assert handled
    # 何も応答しない
    admin_manager._misskey.create_note.assert_not_called()


@pytest.mark.asyncio
async def test_try_handle_status_command(admin_manager):
    """管理者の /admin status は該当処理を呼ぶ"""
    await admin_manager.initialize()
    admin_manager._handle_status = AsyncMock()
    event = MentionEvent(
        note_id="n1",
        user_id="admin_user_id",
        text="@bot /admin status",
        username="u",
        cw=None,
        visibility="public",
    )
    handled = await admin_manager.try_handle(event)
    assert handled
    admin_manager._handle_status.assert_called_once_with("n1")


@pytest.mark.asyncio
async def test_try_handle_post_command(admin_manager):
    """管理者の /admin post は該当処理を呼ぶ"""
    await admin_manager.initialize()
    admin_manager._handle_post = AsyncMock()
    event = MentionEvent(
        note_id="n1",
        user_id="admin_user_id",
        text="/admin post random",
        username="u",
        cw=None,
        visibility="public",
    )
    handled = await admin_manager.try_handle(event)
    assert handled
    admin_manager._handle_post.assert_called_once_with("n1", "random")


@pytest.mark.asyncio
async def test_try_handle_invalid_command(admin_manager):
    """不明なサブコマンドはエラー応答"""
    await admin_manager.initialize()
    admin_manager._reply_error = AsyncMock()
    event = MentionEvent(
        note_id="n1",
        user_id="admin_user_id",
        text="/admin unknown",
        username="u",
        cw=None,
        visibility="public",
    )
    handled = await admin_manager.try_handle(event)
    assert handled
    admin_manager._reply_error.assert_called_once_with("n1")


@pytest.mark.asyncio
async def test_try_handle_no_admin_config(mock_config, mock_misskey):
    """admin.usernames が空の場合は全機能を無効化"""
    mock_config.admin.usernames = []
    am = AdminManager(
        config=mock_config,
        db=AsyncMock(),
        misskey=mock_misskey,
        serif_loader=MagicMock(),
        post_manager=AsyncMock(),
        scheduled_post_manager=AsyncMock(),
        weekday_post_manager=AsyncMock(),
        timeline_post_manager=AsyncMock(),
        horoscope_manager=AsyncMock(),
        wordcloud_manager=AsyncMock(),
        poll_manager=AsyncMock(),
    )
    await am.initialize()

    event = MentionEvent(
        note_id="n1",
        user_id="admin_user_id",
        text="/admin status",
        username="u",
        cw=None,
        visibility="public",
    )
    handled = await am.try_handle(event)
    assert not handled
