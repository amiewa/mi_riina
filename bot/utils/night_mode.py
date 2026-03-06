"""夜間モード判定ユーティリティ

指定時間帯に自動投稿を停止するための判定ロジック。
"""

import logging
from datetime import datetime

from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def is_night_mode(
    start_hour: int,
    end_hour: int,
    enabled: bool = True,
    timezone: str = "Asia/Tokyo",
) -> bool:
    """現在が夜間モードかどうかを判定する。

    Args:
        start_hour: 夜間開始時刻（0-23）
        end_hour: 夜間終了時刻（0-23）
        enabled: 夜間モードが有効かどうか
        timezone: タイムゾーン文字列

    Returns:
        True: 夜間モード中（投稿を停止すべき）
        False: 通常時間帯

    仕様:
    - enabled=False の場合は常に False
    - start_hour == end_hour の場合は「夜間モード無効」扱い（False）
    - 日跨ぎ対応: start_hour=23, end_hour=5 は 23:00〜翌4:59 が夜間
    """
    if not enabled:
        return False

    if start_hour == end_hour:
        return False

    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    current_hour = now.hour

    if start_hour < end_hour:
        # 日跨ぎなし: 例 start=1, end=5 → 1:00〜4:59
        return start_hour <= current_hour < end_hour
    else:
        # 日跨ぎあり: 例 start=23, end=5 → 23:00〜翌4:59
        return current_hour >= start_hour or current_hour < end_hour
