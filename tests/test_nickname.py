"""ニックネーム機能のテスト

DB操作（upsert/get/delete）、パターンマッチ、NGワード拒否、リセットの動作を確認する。
"""

import pytest

from bot.core.database import Database
from bot.managers.reply_manager import (
    _NICKNAME_REGISTER_RE,
    _NICKNAME_RESET_KEYWORD,
)


# ========== DB操作のテスト ==========


@pytest.mark.asyncio
async def test_upsert_and_get_nickname(db: Database) -> None:
    """ニックネームの登録と取得ができること。"""
    await db.upsert_nickname("user_001", "たろう")
    result = await db.get_nickname("user_001")
    assert result == "たろう"


@pytest.mark.asyncio
async def test_upsert_nickname_update(db: Database) -> None:
    """既存のニックネームが上書き更新されること。"""
    await db.upsert_nickname("user_002", "はなこ")
    await db.upsert_nickname("user_002", "じろう")
    result = await db.get_nickname("user_002")
    assert result == "じろう"


@pytest.mark.asyncio
async def test_get_nickname_not_found(db: Database) -> None:
    """未登録ユーザーは None を返すこと。"""
    result = await db.get_nickname("nonexistent_user")
    assert result is None


@pytest.mark.asyncio
async def test_delete_nickname(db: Database) -> None:
    """ニックネームが削除されること。"""
    await db.upsert_nickname("user_003", "さぶろう")
    await db.delete_nickname("user_003")
    result = await db.get_nickname("user_003")
    assert result is None


@pytest.mark.asyncio
async def test_delete_nickname_nonexistent(db: Database) -> None:
    """存在しないユーザーの削除でもエラーにならないこと。"""
    await db.delete_nickname("nonexistent_user")


# ========== パターンマッチのテスト ==========


def test_register_pattern_basic() -> None:
    """基本的な「〜って呼んで」パターンにマッチすること。"""
    match = _NICKNAME_REGISTER_RE.search("たろうって呼んで")
    assert match is not None
    assert match.group(1) == "たろう"


def test_register_pattern_with_prefix() -> None:
    """前方にテキストがあっても正しくマッチすること。"""
    match = _NICKNAME_REGISTER_RE.search("ねえ、たろうって呼んで")
    assert match is not None
    assert match.group(1) == "ねえ、たろう"


def test_register_pattern_no_match() -> None:
    """パターンに合わないテキストにはマッチしないこと。"""
    match = _NICKNAME_REGISTER_RE.search("こんにちは")
    assert match is None


def test_reset_pattern_match() -> None:
    """「呼び名リセット」パターンにマッチすること。"""
    assert _NICKNAME_RESET_KEYWORD in "呼び名リセットして"


def test_reset_pattern_exact() -> None:
    """「呼び名リセット」そのものにマッチすること。"""
    assert _NICKNAME_RESET_KEYWORD in "呼び名リセット"


def test_reset_pattern_no_match() -> None:
    """無関係なテキストにはマッチしないこと。"""
    assert _NICKNAME_RESET_KEYWORD not in "こんにちは"
