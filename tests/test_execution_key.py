"""execution_key 二重投稿防止のテスト"""

import pytest
import pytest_asyncio
from pathlib import Path

from bot.core.database import Database


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """テスト用のDB を返す。"""
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


class TestExecutionKey:
    """execution_key による二重投稿防止のテスト"""

    @pytest.mark.asyncio
    async def test_unique_execution_key(self, db: Database) -> None:
        """同じ execution_key で2回 INSERT するとエラー"""
        await db.insert_post(
            post_type="scheduled",
            execution_key="scheduled:2026-03-06T07:30",
            content="テスト1",
        )

        with pytest.raises(Exception):  # IntegrityError
            await db.insert_post(
                post_type="scheduled",
                execution_key="scheduled:2026-03-06T07:30",
                content="テスト2",
            )

    @pytest.mark.asyncio
    async def test_null_execution_key_allows_duplicates(self, db: Database) -> None:
        """execution_key が NULL の場合は重複を許可する"""
        id1 = await db.insert_post(
            post_type="random",
            execution_key=None,
            content="ランダム1",
        )
        id2 = await db.insert_post(
            post_type="random",
            execution_key=None,
            content="ランダム2",
        )
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_different_execution_keys(self, db: Database) -> None:
        """異なる execution_key は問題なく INSERT できる"""
        await db.insert_post(
            post_type="scheduled",
            execution_key="scheduled:2026-03-06T07:30",
            content="テスト1",
        )
        await db.insert_post(
            post_type="scheduled",
            execution_key="scheduled:2026-03-06T12:30",
            content="テスト2",
        )

    @pytest.mark.asyncio
    async def test_delete_allows_reinsert(self, db: Database) -> None:
        """投稿レコードを削除すれば同じ execution_key で再投稿できる"""
        post_id = await db.insert_post(
            post_type="scheduled",
            execution_key="scheduled:2026-03-06T07:30",
            content="テスト",
        )
        await db.delete_post_by_id(post_id)

        # 再投稿が可能
        await db.insert_post(
            post_type="scheduled",
            execution_key="scheduled:2026-03-06T07:30",
            content="リトライ",
        )
