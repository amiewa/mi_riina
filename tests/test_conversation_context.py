"""マルチターン会話文脈テスト

ReplyManager の会話文脈構築ロジック（ツリー遡り・DBフォールバック・
文字数制限・履歴保存）を検証する。
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.core.models import MentionEvent


# ========== ヘルパー ==========

BOT_USER_ID = "bot_user_id"
USER_ID = "user_001"


def _make_mention(
    note_id: str = "note_current",
    user_id: str = USER_ID,
    text: str = "@riina こんにちは",
    reply_id: str | None = None,
) -> MentionEvent:
    return MentionEvent(
        note_id=note_id,
        user_id=user_id,
        username="testuser",
        text=text,
        cw=None,
        visibility="home",
        reply_id=reply_id,
    )


def _make_reply_manager(
    mock_config: MagicMock,
    mock_db: MagicMock,
    mock_misskey: MagicMock,
    mock_ai: MagicMock,
) -> "ReplyManager":  # noqa: F821
    from bot.managers.reply_manager import ReplyManager

    ng_word = MagicMock()
    ng_word.contains_ng_word = MagicMock(return_value=False)
    rate_limiter = MagicMock()
    rate_limiter.is_limited = AsyncMock(return_value=False)
    rate_limiter.get_count = AsyncMock(return_value=0)
    rate_limiter.max_per_user_per_hour = 3
    rate_limiter.record = AsyncMock()
    serif_loader = MagicMock()
    serif_loader.fallback = {
        "api_error": ["エラー台詞"],
        "ng_word": ["NG台詞"],
        "empty_input": ["空台詞"],
        "rate_limited": ["制限台詞"],
    }

    with patch.object(Path, "exists", return_value=False):
        return ReplyManager(
            mock_config,
            mock_db,
            mock_misskey,
            mock_ai,
            ng_word,
            rate_limiter,
            serif_loader,
        )


def _base_config(conversation_enabled: bool = True) -> MagicMock:
    config = MagicMock()
    config.reply.enabled = True
    config.reply.mutual_only = False
    config.reply.ai_concurrency = 1
    config.reply.nickname.enabled = False
    config.reply.conversation.enabled = conversation_enabled
    config.reply.conversation.max_turns = 3
    config.reply.conversation.history_max_chars = 2000
    config.bot.character_prompt_file = "config/character_prompt.md"
    config.ai.input_max_chars = 2500
    return config


def _base_misskey() -> MagicMock:
    mock = MagicMock()
    mock.bot_user_id = BOT_USER_ID
    mock.create_note = AsyncMock(return_value="reply_note_id")
    mock.get_note = AsyncMock(return_value=None)
    return mock


def _base_db() -> MagicMock:
    mock = MagicMock()
    mock.is_mutual = AsyncMock(return_value=True)
    mock.insert_post = AsyncMock(return_value=1)
    mock.update_post_note_id = AsyncMock()
    mock.delete_post_by_id = AsyncMock()
    mock.get_nickname = AsyncMock(return_value=None)
    mock.record_reply = AsyncMock()
    mock.get_conversation_history = AsyncMock(return_value=[])
    mock.save_conversation_turn = AsyncMock()
    return mock


def _base_ai(response: str = "AI応答テスト") -> MagicMock:
    mock = MagicMock()
    mock.generate = AsyncMock(return_value=response)
    return mock


# ========== ツリー遡りテスト ==========


@pytest.mark.asyncio
async def test_tree_traversal_simple() -> None:
    """bot↔user 2ターンのツリーを正しく復元する"""
    config = _base_config()
    db = _base_db()
    misskey = _base_misskey()
    ai = _base_ai()

    # ツリー構造: current_note → note_bot → note_user（古い順: user → bot）
    note_bot = {
        "id": "note_bot",
        "userId": BOT_USER_ID,
        "text": "@user 前回の返答",
        "replyId": "note_user",
    }
    note_user = {
        "id": "note_user",
        "userId": USER_ID,
        "text": "@riina 最初の質問",
        "replyId": None,
    }

    async def get_note_side_effect(note_id: str) -> dict | None:
        if note_id == "note_bot":
            return note_bot
        if note_id == "note_user":
            return note_user
        return None

    misskey.get_note.side_effect = get_note_side_effect

    manager = _make_reply_manager(config, db, misskey, ai)
    event = _make_mention(
        note_id="note_current",
        text="@riina 続きの質問",
        reply_id="note_bot",
    )

    await manager.on_mention(event)

    # AI が呼ばれ、messages に会話文脈が含まれること
    ai.generate.assert_called_once()
    call_kwargs = ai.generate.call_args[1]
    messages = call_kwargs.get("messages")
    assert messages is not None
    assert len(messages) >= 3  # user, assistant, user（現在）
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[-1]["content"] == "続きの質問"


@pytest.mark.asyncio
async def test_tree_traversal_max_turns() -> None:
    """max_turns で遡りが打ち切られる"""
    config = _base_config()
    config.reply.conversation.max_turns = 1  # 最大1ターン（= 2ノード）
    db = _base_db()
    misskey = _base_misskey()
    ai = _base_ai()

    # ツリーを4ノード連ねる（通常なら2ターン分）
    notes = {
        "n4": {"id": "n4", "userId": BOT_USER_ID, "text": "bot3", "replyId": "n3"},
        "n3": {"id": "n3", "userId": USER_ID, "text": "user2", "replyId": "n2"},
        "n2": {"id": "n2", "userId": BOT_USER_ID, "text": "bot1", "replyId": "n1"},
        "n1": {"id": "n1", "userId": USER_ID, "text": "user1", "replyId": None},
    }
    misskey.get_note.side_effect = lambda nid: notes.get(nid)

    manager = _make_reply_manager(config, db, misskey, ai)
    event = _make_mention(text="@riina 質問", reply_id="n4")

    await manager.on_mention(event)

    ai.generate.assert_called_once()
    call_kwargs = ai.generate.call_args[1]
    messages = call_kwargs.get("messages")
    assert messages is not None
    # max_turns=1 → 最大2ノード取得 → assistant(n4) + user(n3) reversed → user(n3) + assistant(n4) + current
    # ただし先頭が assistant の場合は削られる場合もある
    assert messages[-1]["content"] == "質問"


@pytest.mark.asyncio
async def test_tree_traversal_third_party() -> None:
    """第三者ノートで遡りが中止し、取得済みターンが使われる"""
    config = _base_config()
    db = _base_db()
    misskey = _base_misskey()
    ai = _base_ai()

    # bot → 第三者（遡り中止）
    note_bot = {
        "id": "note_bot",
        "userId": BOT_USER_ID,
        "text": "bot応答",
        "replyId": "note_third",
    }
    note_third = {
        "id": "note_third",
        "userId": "third_party",
        "text": "第三者の投稿",
        "replyId": None,
    }

    async def get_note_side_effect(note_id: str) -> dict | None:
        if note_id == "note_bot":
            return note_bot
        if note_id == "note_third":
            return note_third
        return None

    misskey.get_note.side_effect = get_note_side_effect

    manager = _make_reply_manager(config, db, misskey, ai)
    event = _make_mention(text="@riina 質問", reply_id="note_bot")

    await manager.on_mention(event)

    # turns に bot ノートのみ → 先頭 assistant が削られ → DB フォールバックへ
    ai.generate.assert_called_once()
    # DB からの取得が呼ばれること（第三者で中止後フォールバック）
    db.get_conversation_history.assert_called_once()


@pytest.mark.asyncio
async def test_tree_traversal_deleted_note() -> None:
    """get_note が None を返す場合は DB フォールバックへ"""
    config = _base_config()
    db = _base_db()
    misskey = _base_misskey()
    ai = _base_ai()

    misskey.get_note.return_value = None  # 削除済み

    manager = _make_reply_manager(config, db, misskey, ai)
    event = _make_mention(text="@riina 質問", reply_id="deleted_note")

    await manager.on_mention(event)

    db.get_conversation_history.assert_called_once()
    ai.generate.assert_called_once()


@pytest.mark.asyncio
async def test_tree_traversal_no_text() -> None:
    """テキストなしノートはスキップされる"""
    config = _base_config()
    db = _base_db()
    misskey = _base_misskey()
    ai = _base_ai()

    note_no_text = {
        "id": "note_img",
        "userId": BOT_USER_ID,
        "text": None,  # 画像のみ
        "replyId": None,
    }
    misskey.get_note.return_value = note_no_text

    manager = _make_reply_manager(config, db, misskey, ai)
    event = _make_mention(text="@riina 画像みた", reply_id="note_img")

    await manager.on_mention(event)

    # テキストなしノートはスキップ → turns が空 → DB フォールバック
    db.get_conversation_history.assert_called_once()
    ai.generate.assert_called_once()


# ========== DB フォールバックテスト ==========


@pytest.mark.asyncio
async def test_db_fallback_no_reply_id() -> None:
    """reply_id なし → DB 履歴を使用する"""
    config = _base_config()
    db = _base_db()
    db.get_conversation_history = AsyncMock(
        return_value=[
            {
                "user_message": "前回の質問",
                "bot_response": "前回の回答",
                "created_at": "2026-01-01",
            },
        ]
    )
    misskey = _base_misskey()
    ai = _base_ai()

    manager = _make_reply_manager(config, db, misskey, ai)
    event = _make_mention(text="@riina 新しい質問", reply_id=None)

    await manager.on_mention(event)

    db.get_conversation_history.assert_called_once_with(USER_ID, 3)
    call_kwargs = ai.generate.call_args[1]
    messages = call_kwargs.get("messages")
    assert messages is not None
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "前回の質問"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "前回の回答"
    assert messages[-1]["content"] == "新しい質問"


@pytest.mark.asyncio
async def test_db_fallback_empty_history() -> None:
    """DB 履歴も空 → messages は現在の発言のみ"""
    config = _base_config()
    db = _base_db()
    db.get_conversation_history = AsyncMock(return_value=[])
    misskey = _base_misskey()
    ai = _base_ai()

    manager = _make_reply_manager(config, db, misskey, ai)
    event = _make_mention(text="@riina はじめまして", reply_id=None)

    await manager.on_mention(event)

    call_kwargs = ai.generate.call_args[1]
    messages = call_kwargs.get("messages")
    assert messages is not None
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "はじめまして"


# ========== 文字数制限テスト ==========


def test_trim_context_by_chars_over_limit() -> None:
    """文字数超過時に古いターンが削除される"""
    from bot.managers.reply_manager import ReplyManager

    manager = MagicMock(spec=ReplyManager)
    manager._trim_context_by_chars = ReplyManager._trim_context_by_chars.__get__(
        manager, ReplyManager
    )

    turns = [
        {"role": "user", "content": "a" * 600},
        {"role": "assistant", "content": "b" * 600},
        {"role": "user", "content": "c" * 600},
        {"role": "assistant", "content": "d" * 600},
    ]

    result = manager._trim_context_by_chars(turns, max_chars=1500)
    total = sum(len(t["content"]) for t in result)
    assert total <= 1500


def test_trim_context_by_chars_within_limit() -> None:
    """文字数が上限内の場合は削除しない"""
    from bot.managers.reply_manager import ReplyManager

    manager = MagicMock(spec=ReplyManager)
    manager._trim_context_by_chars = ReplyManager._trim_context_by_chars.__get__(
        manager, ReplyManager
    )

    turns = [
        {"role": "user", "content": "短い"},
        {"role": "assistant", "content": "返答"},
    ]

    result = manager._trim_context_by_chars(turns, max_chars=2000)
    assert len(result) == 2


# ========== 会話無効テスト ==========


@pytest.mark.asyncio
async def test_conversation_disabled() -> None:
    """conversation.enabled=false で単発リプライ動作（messages=None）"""
    config = _base_config(conversation_enabled=False)
    db = _base_db()
    misskey = _base_misskey()
    ai = _base_ai()

    manager = _make_reply_manager(config, db, misskey, ai)
    event = _make_mention(text="@riina こんにちは", reply_id="some_note_id")

    await manager.on_mention(event)

    call_kwargs = ai.generate.call_args[1]
    # messages=None（単発リプライ）で呼ばれること
    assert call_kwargs.get("messages") is None
    # 履歴保存も行われないこと
    db.save_conversation_turn.assert_not_called()


# ========== 会話履歴保存テスト ==========


@pytest.mark.asyncio
async def test_save_conversation_turn() -> None:
    """応答成功後に conversation_history に保存される"""
    config = _base_config(conversation_enabled=True)
    db = _base_db()
    misskey = _base_misskey()
    ai = _base_ai(response="テスト応答")

    manager = _make_reply_manager(config, db, misskey, ai)
    event = _make_mention(text="@riina 質問文", reply_id=None)

    await manager.on_mention(event)

    db.save_conversation_turn.assert_called_once_with(
        user_id=USER_ID,
        user_message="質問文",
        bot_response="テスト応答",
        note_id="reply_note_id",
    )
