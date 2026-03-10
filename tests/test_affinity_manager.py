"""AffinityManager のテスト

親密度マネージャーの交流記録・ランク計算・プロンプト取得の動作を確認する。
"""


import pytest

from bot.core.config import AppConfig
from bot.core.database import Database
from bot.managers.affinity_manager import AffinityManager


def make_affinity_config(
    enabled: bool = True,
    rank2_threshold: int = 5,
    rank3_threshold: int = 20,
) -> AppConfig:
    """テスト用 AppConfig を生成する。"""
    return AppConfig(
        affinity=dict(
            enabled=enabled,
            rank2_threshold=rank2_threshold,
            rank3_threshold=rank3_threshold,
        )
    )


# ========== record_interaction のテスト ==========


@pytest.mark.asyncio
async def test_record_interaction_new_user(db: Database) -> None:
    """新規ユーザーの場合、interaction_count=1 で登録されること。"""
    config = make_affinity_config()
    manager = AffinityManager(config, db)

    await manager.record_interaction("user_001")

    row = await db.fetchone(
        "SELECT interaction_count, rank FROM affinities WHERE user_id = ?",
        ("user_001",),
    )
    assert row is not None
    assert row["interaction_count"] == 1
    assert row["rank"] == 1


@pytest.mark.asyncio
async def test_record_interaction_increment(db: Database) -> None:
    """既存ユーザーの場合、interaction_count がインクリメントされること。"""
    config = make_affinity_config()
    manager = AffinityManager(config, db)

    await manager.record_interaction("user_002")
    await manager.record_interaction("user_002")
    await manager.record_interaction("user_002")

    row = await db.fetchone(
        "SELECT interaction_count FROM affinities WHERE user_id = ?",
        ("user_002",),
    )
    assert row is not None
    assert row["interaction_count"] == 3


# ========== _calculate_rank のテスト ==========


@pytest.mark.asyncio
async def test_rank_calculation_rank1(db: Database) -> None:
    """閾値未満のユーザーはランク1のままであること。"""
    config = make_affinity_config(rank2_threshold=5, rank3_threshold=20)
    manager = AffinityManager(config, db)

    for _ in range(4):
        await manager.record_interaction("user_r1")

    rank = await manager.get_rank("user_r1")
    assert rank == 1


@pytest.mark.asyncio
async def test_rank_calculation_rank2(db: Database) -> None:
    """rank2_threshold 以上の交流でランク2に昇格すること。"""
    config = make_affinity_config(rank2_threshold=5, rank3_threshold=20)
    manager = AffinityManager(config, db)

    for _ in range(5):
        await manager.record_interaction("user_r2")

    rank = await manager.get_rank("user_r2")
    assert rank == 2


@pytest.mark.asyncio
async def test_rank_calculation_rank3(db: Database) -> None:
    """rank3_threshold 以上の交流でランク3に昇格すること。"""
    config = make_affinity_config(rank2_threshold=5, rank3_threshold=20)
    manager = AffinityManager(config, db)

    for _ in range(20):
        await manager.record_interaction("user_r3")

    rank = await manager.get_rank("user_r3")
    assert rank == 3


# ========== get_affinity_prompt のテスト ==========


@pytest.mark.asyncio
async def test_get_affinity_prompt_rank1(db: Database) -> None:
    """ランク1のプロンプトは空文字であること。"""
    config = make_affinity_config()
    manager = AffinityManager(config, db)

    # DB にレコードなし = ランク1
    prompt = await manager.get_affinity_prompt("unknown_user")
    assert prompt == ""


@pytest.mark.asyncio
async def test_get_affinity_prompt_rank2(db: Database) -> None:
    """ランク2のプロンプトは「心を開いている」系のテキストであること。"""
    config = make_affinity_config(rank2_threshold=2, rank3_threshold=20)
    manager = AffinityManager(config, db)

    for _ in range(2):
        await manager.record_interaction("user_p2")

    prompt = await manager.get_affinity_prompt("user_p2")
    assert "心を開いている" in prompt


@pytest.mark.asyncio
async def test_get_affinity_prompt_rank3(db: Database) -> None:
    """ランク3のプロンプトは「親しく信頼」系のテキストであること。"""
    config = make_affinity_config(rank2_threshold=2, rank3_threshold=5)
    manager = AffinityManager(config, db)

    for _ in range(5):
        await manager.record_interaction("user_p3")

    prompt = await manager.get_affinity_prompt("user_p3")
    assert "親しく" in prompt
    assert "信頼" in prompt


# ========== disabled 時のテスト ==========


@pytest.mark.asyncio
async def test_disabled_returns_rank1(db: Database) -> None:
    """disabled の場合、get_rank は常にランク1を返すこと。"""
    config = make_affinity_config(enabled=False)
    manager = AffinityManager(config, db)

    rank = await manager.get_rank("user_dis")
    assert rank == 1


@pytest.mark.asyncio
async def test_disabled_skips_record(db: Database) -> None:
    """disabled の場合、record_interaction は DB に書き込まないこと。"""
    config = make_affinity_config(enabled=False)
    manager = AffinityManager(config, db)

    await manager.record_interaction("user_nodis")

    row = await db.fetchone(
        "SELECT * FROM affinities WHERE user_id = ?",
        ("user_nodis",),
    )
    assert row is None


@pytest.mark.asyncio
async def test_disabled_prompt_is_empty(db: Database) -> None:
    """disabled の場合、get_affinity_prompt は空文字を返すこと。"""
    config = make_affinity_config(enabled=False)
    manager = AffinityManager(config, db)

    prompt = await manager.get_affinity_prompt("any_user")
    assert prompt == ""


# ========== enabled プロパティのテスト ==========


def test_enabled_property_true() -> None:
    """enabled=True の場合、enabled プロパティが True であること。"""
    config = make_affinity_config(enabled=True)
    manager = AffinityManager(config, None)  # type: ignore
    assert manager.enabled is True


def test_enabled_property_false() -> None:
    """enabled=False の場合、enabled プロパティが False であること。"""
    config = make_affinity_config(enabled=False)
    manager = AffinityManager(config, None)  # type: ignore
    assert manager.enabled is False
