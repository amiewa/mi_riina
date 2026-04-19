"""イベント投稿スケジュール登録のテスト

_schedule_event_post の境界条件を確認する。
"""

import logging
import random
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from main import _schedule_event_post

JST = ZoneInfo("Asia/Tokyo")


def _make_manager(event_key: str | None) -> MagicMock:
    manager = MagicMock()
    manager.get_today_event_key.return_value = event_key
    return manager


def test_schedules_when_event_exists_and_enabled() -> None:
    """イベントキーあり・enabled=True・10時起動時に add_job が 1 回呼ばれること。"""
    scheduler = MagicMock()
    now = datetime(2026, 4, 19, 10, 0, tzinfo=JST)

    _schedule_event_post(
        scheduler, _make_manager("04/19"), True, now, random.Random(42)
    )

    scheduler.add_job.assert_called_once()
    kwargs = scheduler.add_job.call_args.kwargs
    assert kwargs["misfire_grace_time"] == 60
    run_date: datetime = kwargs["run_date"]
    assert 11 <= run_date.hour <= 21


def test_skips_when_event_key_is_none() -> None:
    """イベントキーが None のとき add_job を呼ばないこと。"""
    scheduler = MagicMock()
    now = datetime(2026, 4, 19, 10, 0, tzinfo=JST)

    _schedule_event_post(scheduler, _make_manager(None), True, now, random.Random(42))

    scheduler.add_job.assert_not_called()


def test_skips_when_event_disabled() -> None:
    """enabled=False のとき add_job を呼ばないこと。"""
    scheduler = MagicMock()
    now = datetime(2026, 4, 19, 10, 0, tzinfo=JST)

    _schedule_event_post(
        scheduler, _make_manager("04/19"), False, now, random.Random(42)
    )

    scheduler.add_job.assert_not_called()


def test_skips_when_hour_is_21(caplog: pytest.LogCaptureFixture) -> None:
    """21時ちょうど起動時はスキップログのみ出力し、add_job を呼ばないこと。"""
    scheduler = MagicMock()
    now = datetime(2026, 4, 19, 21, 0, tzinfo=JST)

    with caplog.at_level(logging.INFO, logger="bot"):
        _schedule_event_post(
            scheduler, _make_manager("04/19"), True, now, random.Random(42)
        )

    scheduler.add_job.assert_not_called()
    assert any("スキップ" in rec.message for rec in caplog.records)


def test_skips_when_hour_is_23(caplog: pytest.LogCaptureFixture) -> None:
    """23時起動時もスキップログのみ出力し、add_job を呼ばないこと。"""
    scheduler = MagicMock()
    now = datetime(2026, 4, 19, 23, 0, tzinfo=JST)

    with caplog.at_level(logging.INFO, logger="bot"):
        _schedule_event_post(
            scheduler, _make_manager("04/19"), True, now, random.Random(42)
        )

    scheduler.add_job.assert_not_called()
    assert any("スキップ" in rec.message for rec in caplog.records)


def test_schedules_at_20_forces_21_oclock() -> None:
    """20時起動時は max(7, 21) = randint(21, 21) により run_date.hour が 21 になること。"""
    scheduler = MagicMock()
    now = datetime(2026, 4, 19, 20, 30, tzinfo=JST)

    _schedule_event_post(
        scheduler, _make_manager("04/19"), True, now, random.Random(42)
    )

    scheduler.add_job.assert_called_once()
    run_date: datetime = scheduler.add_job.call_args.kwargs["run_date"]
    assert run_date.hour == 21


def test_early_morning_uses_hour_7_floor() -> None:
    """3時起動時は max(7, 4) = 7 が下限になり、run_date.hour が 7〜21 になること。"""
    scheduler = MagicMock()
    now = datetime(2026, 4, 19, 3, 0, tzinfo=JST)

    _schedule_event_post(
        scheduler, _make_manager("04/19"), True, now, random.Random(42)
    )

    scheduler.add_job.assert_called_once()
    run_date: datetime = scheduler.add_job.call_args.kwargs["run_date"]
    assert 7 <= run_date.hour <= 21


def test_run_date_has_zero_second_and_microsecond() -> None:
    """run_date の second と microsecond が 0 になること。"""
    scheduler = MagicMock()
    now = datetime(2026, 4, 19, 10, 15, 30, 999999, tzinfo=JST)

    _schedule_event_post(
        scheduler, _make_manager("04/19"), True, now, random.Random(42)
    )

    run_date: datetime = scheduler.add_job.call_args.kwargs["run_date"]
    assert run_date.second == 0
    assert run_date.microsecond == 0
