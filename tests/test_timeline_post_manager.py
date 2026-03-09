import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from bot.managers.timeline_post_manager import TimelinePostManager
from bot.core.config import AppConfig

@pytest.fixture
def mock_config():
    config = MagicMock()
    config.posting.timeline_post.enabled = True
    config.posting.timeline_post.mode = "ai"
    config.posting.timeline_post.source = "home"
    config.posting.timeline_post.interval_minutes = 120
    config.posting.timeline_post.max_notes_fetch = 20
    config.posting.timeline_post.min_keyword_length = 2
    config.posting.timeline_post.probability = 1.0 # 確率100%
    config.posting.timeline_post.ai_keyword_count = 3
    config.posting.timeline_post.ai_max_chars = 100
    config.posting.night_mode.enabled = False
    config.posting.cooldown_minutes = 0
    config.posting.auto_delete.timeline_post.enabled = False
    config.posting.default_visibility = "home"
    config.bot.timezone = "Asia/Tokyo"
    config.bot.character_prompt_file = "config/character_prompt.md"
    return config

@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.get_last_auto_post_time.return_value = None
    db.insert_post.return_value = "post_id"
    return db

@pytest.fixture
def mock_misskey():
    misskey = AsyncMock()
    misskey.bot_user_id = "bot_id"
    misskey.get_timeline.return_value = [
        {"id": "note1", "userId": "user1", "user": {"username": "user1"}, "text": "こんにちは世界"}
    ]
    misskey.create_note.return_value = "note_id"
    return misskey

@pytest.fixture
def mock_tokenizer():
    tokenizer = MagicMock()
    tokenizer.extract_keywords.return_value = ["世界"]
    return tokenizer

@pytest.fixture
def mock_ng_word_manager():
    ng = MagicMock()
    ng.contains_ng_word.return_value = False
    return ng

@pytest.fixture
def mock_ai_client():
    ai = AsyncMock()
    ai.generate.return_value = "AI生成された投稿です"
    return ai

@pytest.mark.asyncio
async def test_timeline_post_ai_mode(mock_config, mock_db, mock_misskey, mock_tokenizer, mock_ng_word_manager, mock_ai_client):
    manager = TimelinePostManager(
        config=mock_config,
        db=mock_db,
        misskey=mock_misskey,
        tokenizer=mock_tokenizer,
        ng_word_manager=mock_ng_word_manager,
        ai_client=mock_ai_client
    )

    with patch("bot.managers.timeline_post_manager.open", mock_open(read_data="System Prompt")):
        await manager.execute_timeline_post()

    mock_ai_client.generate.assert_called_once()
    assert mock_misskey.create_note.called
    args, kwargs = mock_misskey.create_note.call_args
    assert kwargs["text"] == "AI生成された投稿です"

@pytest.mark.asyncio
async def test_timeline_post_template_mode_if_ai_client_missing(mock_config, mock_db, mock_misskey, mock_tokenizer, mock_ng_word_manager):
    # AIモードだがai_clientがNoneの場合
    manager = TimelinePostManager(
        config=mock_config,
        db=mock_db,
        misskey=mock_misskey,
        tokenizer=mock_tokenizer,
        ng_word_manager=mock_ng_word_manager,
        ai_client=None
    )
    mock_config.posting.timeline_post.template = "Template: {keyword}"

    await manager.execute_timeline_post()

    assert mock_misskey.create_note.called
    args, kwargs = mock_misskey.create_note.call_args
    assert "Template: " in kwargs["text"]
