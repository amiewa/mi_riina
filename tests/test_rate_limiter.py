"""レート制限のテスト"""

import pytest
import pytest_asyncio
from pathlib import Path

from bot.core.database import Database
from bot.utils.rate_limiter import RateLimiter


@pytest_asyncio.fixture
async def db_and_limiter(tmp_path: Path):
    """テスト用のDB + RateLimiter を返す。"""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    limiter = RateLimiter(db, max_per_user_per_hour=3)
    yield db, limiter
    await db.close()


class TestRateLimiter:
    """RateLimiter のテスト"""

    @pytest.mark.asyncio
    async def test_not_limited_initially(self, db_and_limiter) -> None:
        """初期状態では制限されていない"""
        _, limiter = db_and_limiter
        assert await limiter.is_limited("user1") is False

    @pytest.mark.asyncio
    async def test_limited_after_max(self, db_and_limiter) -> None:
        """最大回数に達するとレート制限される"""
        _, limiter = db_and_limiter
        for _ in range(3):
            await limiter.record("user1")
        assert await limiter.is_limited("user1") is True

    @pytest.mark.asyncio
    async def test_different_users_independent(self, db_and_limiter) -> None:
        """異なるユーザーのレート制限は独立"""
        _, limiter = db_and_limiter
        for _ in range(3):
            await limiter.record("user1")
        assert await limiter.is_limited("user1") is True
        assert await limiter.is_limited("user2") is False

    @pytest.mark.asyncio
    async def test_under_limit(self, db_and_limiter) -> None:
        """制限未達ではFalse"""
        _, limiter = db_and_limiter
        await limiter.record("user1")
        await limiter.record("user1")
        assert await limiter.is_limited("user1") is False
