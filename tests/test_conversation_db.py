"""conversation_history テーブルのテスト

save_conversation_turn / get_conversation_history /
cleanup_conversation_history の CRUD を検証する。
"""

import pytest

from bot.core.database import Database


@pytest.mark.asyncio
async def test_save_and_get_conversation_turn(db: Database) -> None:
    """会話ターンを保存して取得できること"""
    await db.save_conversation_turn(
        user_id="user_001",
        user_message="こんにちは",
        bot_response="やあ！",
        note_id="note_abc",
    )
    rows = await db.get_conversation_history("user_001", max_turns=5)
    assert len(rows) == 1
    assert rows[0]["user_message"] == "こんにちは"
    assert rows[0]["bot_response"] == "やあ！"


@pytest.mark.asyncio
async def test_get_conversation_history_order(db: Database) -> None:
    """取得結果が古い順（昇順）に並ぶこと"""
    for i in range(3):
        await db.save_conversation_turn(
            user_id="user_002",
            user_message=f"質問{i}",
            bot_response=f"回答{i}",
        )

    rows = await db.get_conversation_history("user_002", max_turns=5)
    assert len(rows) == 3
    assert rows[0]["user_message"] == "質問0"
    assert rows[1]["user_message"] == "質問1"
    assert rows[2]["user_message"] == "質問2"


@pytest.mark.asyncio
async def test_get_conversation_history_max_turns(db: Database) -> None:
    """max_turns を超える件数は返さない（直近N件を古い順で返す）"""
    for i in range(5):
        await db.save_conversation_turn(
            user_id="user_003",
            user_message=f"q{i}",
            bot_response=f"a{i}",
        )

    rows = await db.get_conversation_history("user_003", max_turns=3)
    assert len(rows) == 3
    # 直近3件なので質問2, 3, 4（古い順）
    assert rows[0]["user_message"] == "q2"
    assert rows[2]["user_message"] == "q4"


@pytest.mark.asyncio
async def test_get_conversation_history_empty(db: Database) -> None:
    """履歴がない場合は空リストを返す"""
    rows = await db.get_conversation_history("nonexistent_user", max_turns=5)
    assert rows == []


@pytest.mark.asyncio
async def test_get_conversation_history_different_users(db: Database) -> None:
    """異なるユーザーの履歴が混在しないこと"""
    await db.save_conversation_turn("user_a", "aの質問", "aの回答")
    await db.save_conversation_turn("user_b", "bの質問", "bの回答")

    rows_a = await db.get_conversation_history("user_a", max_turns=5)
    rows_b = await db.get_conversation_history("user_b", max_turns=5)

    assert len(rows_a) == 1
    assert rows_a[0]["user_message"] == "aの質問"
    assert len(rows_b) == 1
    assert rows_b[0]["user_message"] == "bの質問"


@pytest.mark.asyncio
async def test_save_truncates_long_messages(db: Database) -> None:
    """500文字を超えるメッセージは先頭500文字で保存される"""
    long_msg = "あ" * 600
    long_resp = "い" * 700

    await db.save_conversation_turn(
        user_id="user_trunc",
        user_message=long_msg,
        bot_response=long_resp,
    )

    rows = await db.get_conversation_history("user_trunc", max_turns=1)
    assert len(rows[0]["user_message"]) == 500
    assert len(rows[0]["bot_response"]) == 500


@pytest.mark.asyncio
async def test_cleanup_conversation_history(db: Database) -> None:
    """指定日数より古いデータが削除される（通常の cleanup 経由）"""
    await db.save_conversation_turn("user_x", "古い質問", "古い回答")

    # cleanup_days=0 にすると全データが削除対象になる
    deleted = await db.cleanup_conversation_history(days=0)
    assert deleted >= 1

    rows = await db.get_conversation_history("user_x", max_turns=5)
    assert rows == []


@pytest.mark.asyncio
async def test_cleanup_via_main_cleanup(db: Database) -> None:
    """Database.cleanup() が conversation_history を削除すること"""
    await db.save_conversation_turn("user_y", "質問", "回答")

    await db.cleanup(cleanup_days=0)

    rows = await db.get_conversation_history("user_y", max_turns=5)
    assert rows == []
