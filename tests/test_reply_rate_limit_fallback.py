"""レート制限フォールバックの迂回防止テスト

制限到達時のフォールバックそのものが制限にカウントされず、
連投すると1通ごとに応答してしまう不具合の回帰防止。
「ちょうど到達した最初の1回のみ」フォールバックを送信し、
以降は無応答でスキップすることを検証する。
"""

import asyncio
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
    mock.max_per_user_per_hour = 3
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
async def test_fallback_sent_when_count_just_reaches_max(
    manager: ReplyManager, mock_misskey: MagicMock, mock_rate_limiter: MagicMock
) -> None:
    """count がちょうど上限に達した回はフォールバックを送信する"""
    mock_rate_limiter.get_count = AsyncMock(return_value=3)  # == max
    event = _make_mention_event(user_id="user1")

    await manager.on_mention(event)

    mock_misskey.create_note.assert_called_once()
    mock_rate_limiter.record.assert_called_once_with("user1")


@pytest.mark.asyncio
async def test_fallback_not_sent_when_count_exceeds_max(
    manager: ReplyManager, mock_misskey: MagicMock, mock_rate_limiter: MagicMock
) -> None:
    """count が上限を超えている場合は無応答でスキップする（フォールバック連打防止）"""
    mock_rate_limiter.get_count = AsyncMock(return_value=4)  # > max
    event = _make_mention_event(user_id="user1")

    await manager.on_mention(event)

    mock_misskey.create_note.assert_not_called()
    mock_rate_limiter.record.assert_not_called()


@pytest.mark.asyncio
async def test_normal_reply_when_under_limit(
    manager: ReplyManager, mock_misskey: MagicMock, mock_rate_limiter: MagicMock
) -> None:
    """制限未達では通常どおりAI応答する"""
    mock_rate_limiter.get_count = AsyncMock(return_value=1)  # < max
    event = _make_mention_event(user_id="user1")

    await manager.on_mention(event)

    mock_misskey.create_note.assert_called_once()
    call_kwargs = mock_misskey.create_note.call_args.kwargs
    assert call_kwargs["text"] == "こんにちは！"
    mock_rate_limiter.record.assert_called_once_with("user1")


@pytest.mark.asyncio
async def test_other_fallback_categories_also_recorded(
    manager: ReplyManager,
    mock_misskey: MagicMock,
    mock_rate_limiter: MagicMock,
    mock_ng_word: MagicMock,
) -> None:
    """NGワード等の他カテゴリのフォールバックも record される（連打対策）"""
    mock_rate_limiter.get_count = AsyncMock(return_value=0)
    mock_ng_word.contains_ng_word = MagicMock(return_value=True)
    event = _make_mention_event(user_id="user1", text="@riina NGワード入り")

    await manager.on_mention(event)

    mock_misskey.create_note.assert_called_once()
    mock_rate_limiter.record.assert_called_once_with("user1")


@pytest.mark.asyncio
async def test_concurrent_mentions_same_user_are_serialized(
    manager: ReplyManager, mock_rate_limiter: MagicMock
) -> None:
    """同一ユーザーからの並行メンションはロックにより直列化される

    StreamingManager._dispatch がハンドラをタスク化するようになったため、
    同一ユーザーの複数メンションが on_mention を並行実行し得る。
    レート制限の get_count → record が非アトミックな check-then-act の
    ままだと、並行実行によりレート制限を迂回できてしまう（回帰防止）。
    """
    in_critical_section = False
    race_detected = False

    async def fake_get_count(user_id: str) -> int:
        nonlocal in_critical_section, race_detected
        if in_critical_section:
            race_detected = True
        in_critical_section = True
        await asyncio.sleep(0.05)  # 他のタスクに実行機会を与える
        return 0

    async def fake_record(user_id: str) -> None:
        nonlocal in_critical_section
        in_critical_section = False

    mock_rate_limiter.get_count = fake_get_count
    mock_rate_limiter.record = fake_record

    event1 = _make_mention_event(note_id="note1", user_id="user1")
    event2 = _make_mention_event(note_id="note2", user_id="user1")

    await asyncio.gather(manager.on_mention(event1), manager.on_mention(event2))

    assert not race_detected
