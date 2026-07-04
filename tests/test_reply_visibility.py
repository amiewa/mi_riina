"""ReplyManager の specified visibility 返信テスト

visibility="specified"（DMメンション）の場合、create_note に
visibleUserIds を付与しないと相手に届かない不具合の回帰防止。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.models import MentionEvent
from bot.managers.reply_manager import ReplyManager


def _make_mention_event(
    note_id: str = "note1",
    user_id: str = "user1",
    text: str = "@riina こんにちは",
    visibility: str = "public",
) -> MentionEvent:
    return MentionEvent(
        note_id=note_id,
        user_id=user_id,
        username="testuser",
        text=text,
        cw=None,
        visibility=visibility,
    )


@pytest.fixture
def mock_misskey() -> MagicMock:
    mock = MagicMock()
    mock.bot_user_id = "bot_id"
    mock.create_note = AsyncMock(return_value="note_id_1")
    return mock


@pytest.fixture
def mock_db() -> MagicMock:
    mock = MagicMock()
    mock.is_mutual = AsyncMock(return_value=True)
    mock.insert_post = AsyncMock(return_value=1)
    mock.update_post_note_id = AsyncMock()
    mock.delete_post_by_id = AsyncMock()
    mock.get_nickname = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def mock_ai() -> MagicMock:
    mock = MagicMock()
    mock.generate = AsyncMock(return_value="こんにちは！")
    return mock


@pytest.fixture
def mock_ng_word() -> MagicMock:
    mock = MagicMock()
    mock.contains_ng_word = MagicMock(return_value=False)
    return mock


@pytest.fixture
def mock_rate_limiter() -> MagicMock:
    mock = MagicMock()
    mock.is_limited = AsyncMock(return_value=False)
    mock.record = AsyncMock()
    return mock


@pytest.fixture
def mock_serif_loader() -> MagicMock:
    mock = MagicMock()
    mock.fallback = {
        "api_error": ["エラー台詞"],
        "ng_word": ["NG台詞"],
        "empty_input": ["空台詞"],
        "rate_limited": ["制限台詞"],
    }
    return mock


@pytest.fixture
def mock_config() -> MagicMock:
    config = MagicMock()
    config.reply.enabled = True
    config.reply.mutual_only = False
    config.reply.ai_concurrency = 1
    config.reply.nickname.enabled = False
    config.reply.conversation.enabled = False
    config.bot.character_prompt_file = "config/character_prompt.md"
    config.ai.input_max_chars = 800
    return config


@pytest.fixture
def manager(
    mock_config,
    mock_db,
    mock_misskey,
    mock_ai,
    mock_ng_word,
    mock_rate_limiter,
    mock_serif_loader,
) -> ReplyManager:
    return ReplyManager(
        mock_config,
        mock_db,
        mock_misskey,
        mock_ai,
        mock_ng_word,
        mock_rate_limiter,
        mock_serif_loader,
    )


@pytest.mark.asyncio
async def test_specified_visibility_reply_includes_visible_user_ids(
    manager: ReplyManager, mock_misskey: MagicMock
) -> None:
    """DM（visibility=specified）へのAI返信は visibleUserIds 付きで送られる"""
    event = _make_mention_event(user_id="user1", visibility="specified")

    await manager.on_mention(event)

    mock_misskey.create_note.assert_called_once()
    call_kwargs = mock_misskey.create_note.call_args.kwargs
    assert call_kwargs["visibility"] == "specified"
    assert call_kwargs["visible_user_ids"] == ["user1"]


@pytest.mark.asyncio
async def test_public_visibility_reply_has_no_visible_user_ids(
    manager: ReplyManager, mock_misskey: MagicMock
) -> None:
    """public 等の通常返信では visibleUserIds を付与しない"""
    event = _make_mention_event(user_id="user1", visibility="public")

    await manager.on_mention(event)

    mock_misskey.create_note.assert_called_once()
    call_kwargs = mock_misskey.create_note.call_args.kwargs
    assert call_kwargs["visibility"] == "public"
    assert call_kwargs["visible_user_ids"] is None


@pytest.mark.asyncio
async def test_specified_visibility_fallback_includes_visible_user_ids(
    manager: ReplyManager, mock_misskey: MagicMock, mock_ng_word: MagicMock
) -> None:
    """NGワード等のフォールバック応答も specified の場合 visibleUserIds を付与する"""
    mock_ng_word.contains_ng_word = MagicMock(return_value=True)
    event = _make_mention_event(user_id="user1", visibility="specified")

    await manager.on_mention(event)

    mock_misskey.create_note.assert_called_once()
    call_kwargs = mock_misskey.create_note.call_args.kwargs
    assert call_kwargs["visibility"] == "specified"
    assert call_kwargs["visible_user_ids"] == ["user1"]
