"""定期投稿系 create_note の retry_async 適用テスト

scheduled / random / weekday / timeline / horoscope / poll の各投稿は
RetryableError（429/5xx）が一発失敗にならず、retry_async でリトライされて
成功することを検証する（timeline / horoscope は既存テストファイルで
create_note 呼び出し自体を別途検証済みのため、ここでは残る3マネージャーを対象とする）。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.utils.retry import RetryableError


@pytest.fixture(autouse=True)
def _no_real_retry_delay():
    """retry_async の base_delay=5.0 による実待機を避ける。"""
    with patch("bot.utils.retry.asyncio.sleep", new=AsyncMock()):
        yield


def _flaky_create_note(success_note_id: str) -> AsyncMock:
    """1回目は RetryableError、2回目は成功する create_note モックを返す。"""
    return AsyncMock(
        side_effect=[
            RetryableError(503, "SERVICE_UNAVAILABLE", "一時的なエラー"),
            success_note_id,
        ]
    )


@pytest.mark.asyncio
async def test_random_post_retries_on_retryable_error() -> None:
    """PostManager: create_note が RetryableError → 成功でリトライされる"""
    from bot.managers.post_manager import PostManager

    config = MagicMock()
    config.posting.auto_delete.random_post.enabled = False
    config.posting.default_visibility = "home"

    db = AsyncMock()
    db.insert_post.return_value = "post_id"

    misskey = AsyncMock()
    misskey.create_note = _flaky_create_note("note_id_1")

    serif_loader = MagicMock()
    serif_loader.random = {"posts": ["こんにちは"]}

    manager = PostManager(config, db, misskey, serif_loader)
    await manager._do_random_post()

    assert misskey.create_note.call_count == 2
    db.update_post_note_id.assert_called_once_with("post_id", "note_id_1")


@pytest.mark.asyncio
async def test_scheduled_post_retries_on_retryable_error() -> None:
    """ScheduledPostManager: create_note が RetryableError → 成功でリトライされる"""
    from bot.managers.scheduled_post_manager import ScheduledPostManager

    config = MagicMock()
    config.posting.default_visibility = "home"
    config.posting.auto_delete.scheduled_posts.enabled = False

    db = AsyncMock()
    db.insert_post.return_value = "post_id"

    misskey = AsyncMock()
    misskey.create_note = _flaky_create_note("note_id_2")

    serif_loader = MagicMock()
    serif_loader.scheduled = {"08:00": ["おはよう"]}

    manager = ScheduledPostManager(config, db, misskey, serif_loader)
    await manager._do_scheduled_post("08:00", force=True)

    assert misskey.create_note.call_count == 2
    db.update_post_note_id.assert_called_once_with("post_id", "note_id_2")


@pytest.mark.asyncio
async def test_weekday_post_retries_on_retryable_error() -> None:
    """WeekdayPostManager: create_note が RetryableError → 成功でリトライされる"""
    from bot.managers.weekday_post_manager import WeekdayPostManager

    config = MagicMock()
    config.posting.default_visibility = "home"
    config.posting.weekday_posts.probability = 1.0

    db = AsyncMock()
    db.insert_post.return_value = "post_id"

    misskey = AsyncMock()
    misskey.create_note = _flaky_create_note("note_id_3")

    serif_loader = MagicMock()

    manager = WeekdayPostManager(config, db, misskey, serif_loader)

    # 現在の曜日・時刻に必ずヒットするデータを組み立てる
    import bot.managers.weekday_post_manager as wpm_module
    from datetime import datetime

    now = datetime.now(wpm_module.JST)
    weekday = wpm_module.WEEKDAY_NAMES[now.weekday()]
    time_key = now.strftime("%H:%M")
    serif_loader.weekday_posts = {weekday: {time_key: {"posts": ["やっほー"]}}}

    await manager._do_weekday_post(force=True)

    assert misskey.create_note.call_count == 2
    db.update_post_note_id.assert_called_once_with("post_id", "note_id_3")
