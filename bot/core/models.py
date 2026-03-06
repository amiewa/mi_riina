"""内部イベント DTO（Data Transfer Object）

StreamingManager が WebSocket メッセージを正規化し、
各 Manager にディスパッチするためのデータクラス。
各 Manager は生の Misskey JSON を直接読まない。
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class NoteEvent:
    """TL上に流れてきたノートのイベント"""

    note_id: str
    user_id: str
    username: str | None
    text: str | None
    cw: str | None  # CW（Content Warning）テキスト
    visibility: str  # public / home / followers / specified
    reply_id: str | None
    renote_id: str | None
    has_poll: bool  # 投票付きノートか
    file_ids: list[str] = field(default_factory=list)
    channel: Literal["home", "local", "social", "global", "main"] = "home"
    raw: dict = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class MentionEvent:
    """bot宛メンションのイベント"""

    note_id: str
    user_id: str
    username: str | None
    text: str | None
    cw: str | None
    visibility: str
    raw: dict = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class FollowedEvent:
    """新規フォロー通知のイベント"""

    user_id: str
    username: str | None
    raw: dict = field(default_factory=dict, repr=False)
