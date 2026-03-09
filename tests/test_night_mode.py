"""夜間モード判定のテスト"""

from unittest.mock import patch
from datetime import datetime

from bot.utils.night_mode import is_night_mode


class TestNightMode:
    """is_night_mode のテスト"""

    def test_disabled(self) -> None:
        """enabled=False の場合は常に False"""
        assert is_night_mode(23, 5, enabled=False) is False

    def test_same_start_end(self) -> None:
        """start_hour == end_hour の場合は「無効」扱い"""
        assert is_night_mode(5, 5, enabled=True) is False

    @patch("bot.utils.night_mode.datetime")
    def test_night_time_23(self, mock_dt) -> None:
        """23:00 は夜間"""
        from zoneinfo import ZoneInfo

        mock_dt.now.return_value = datetime(
            2026, 3, 6, 23, 0, tzinfo=ZoneInfo("Asia/Tokyo")
        )
        assert is_night_mode(23, 5) is True

    @patch("bot.utils.night_mode.datetime")
    def test_night_time_0(self, mock_dt) -> None:
        """0:00 は夜間（日跨ぎ）"""
        from zoneinfo import ZoneInfo

        mock_dt.now.return_value = datetime(
            2026, 3, 6, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo")
        )
        assert is_night_mode(23, 5) is True

    @patch("bot.utils.night_mode.datetime")
    def test_night_time_459(self, mock_dt) -> None:
        """4:59 は夜間"""
        from zoneinfo import ZoneInfo

        mock_dt.now.return_value = datetime(
            2026, 3, 6, 4, 59, tzinfo=ZoneInfo("Asia/Tokyo")
        )
        assert is_night_mode(23, 5) is True

    @patch("bot.utils.night_mode.datetime")
    def test_day_time_5(self, mock_dt) -> None:
        """5:00 は昼間（夜間終了）"""
        from zoneinfo import ZoneInfo

        mock_dt.now.return_value = datetime(
            2026, 3, 6, 5, 0, tzinfo=ZoneInfo("Asia/Tokyo")
        )
        assert is_night_mode(23, 5) is False

    @patch("bot.utils.night_mode.datetime")
    def test_day_time_12(self, mock_dt) -> None:
        """12:00 は昼間"""
        from zoneinfo import ZoneInfo

        mock_dt.now.return_value = datetime(
            2026, 3, 6, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo")
        )
        assert is_night_mode(23, 5) is False

    @patch("bot.utils.night_mode.datetime")
    def test_no_wrap(self, mock_dt) -> None:
        """日跨ぎなし: start=1, end=5 → 1:00〜4:59 が夜間"""
        from zoneinfo import ZoneInfo

        mock_dt.now.return_value = datetime(
            2026, 3, 6, 3, 0, tzinfo=ZoneInfo("Asia/Tokyo")
        )
        assert is_night_mode(1, 5) is True

    @patch("bot.utils.night_mode.datetime")
    def test_no_wrap_outside(self, mock_dt) -> None:
        """日跨ぎなし: start=1, end=5 → 0:00 は昼間"""
        from zoneinfo import ZoneInfo

        mock_dt.now.return_value = datetime(
            2026, 3, 6, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo")
        )
        assert is_night_mode(1, 5) is False
