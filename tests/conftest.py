"""テスト用共通フィクスチャ"""

from pathlib import Path

import pytest
import pytest_asyncio

from bot.core.config import AppConfig, load_config
from bot.core.database import Database


@pytest.fixture
def config() -> AppConfig:
    """テスト用の設定を返す。"""
    return load_config("config/config.yaml")


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    """テスト用のインメモリ DB を返す。"""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()
