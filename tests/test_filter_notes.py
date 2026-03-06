"""visibility フィルタのテスト"""

from bot.core.misskey_client import filter_notes
from bot.core.models import NoteEvent


def _make_note(
    note_id: str = "note1",
    user_id: str = "user1",
    text: str | None = "テスト",
    visibility: str = "public",
    renote_id: str | None = None,
) -> NoteEvent:
    """テスト用の NoteEvent を作成する。"""
    return NoteEvent(
        note_id=note_id,
        user_id=user_id,
        username="testuser",
        text=text,
        cw=None,
        visibility=visibility,
        reply_id=None,
        renote_id=renote_id,
        has_poll=False,
    )


BOT_USER_ID = "bot_user"


class TestFilterNotes:
    """filter_notes のテスト"""

    def test_public_passes(self) -> None:
        """public visibility は通過する"""
        notes = [_make_note(visibility="public")]
        result = filter_notes(notes, BOT_USER_ID)
        assert len(result) == 1

    def test_home_passes(self) -> None:
        """home visibility は通過する"""
        notes = [_make_note(visibility="home")]
        result = filter_notes(notes, BOT_USER_ID)
        assert len(result) == 1

    def test_followers_excluded(self) -> None:
        """followers visibility は除外される"""
        notes = [_make_note(visibility="followers")]
        result = filter_notes(notes, BOT_USER_ID)
        assert len(result) == 0

    def test_specified_excluded(self) -> None:
        """specified visibility は除外される"""
        notes = [_make_note(visibility="specified")]
        result = filter_notes(notes, BOT_USER_ID)
        assert len(result) == 0

    def test_bot_self_excluded(self) -> None:
        """bot 自身のノートは除外される"""
        notes = [_make_note(user_id=BOT_USER_ID)]
        result = filter_notes(notes, BOT_USER_ID)
        assert len(result) == 0

    def test_renote_without_text_excluded(self) -> None:
        """テキストなし Renote は除外される"""
        notes = [_make_note(text=None, renote_id="renoted_note")]
        result = filter_notes(notes, BOT_USER_ID)
        assert len(result) == 0

    def test_quote_renote_passes(self) -> None:
        """引用 Renote（テキストあり）は通過する"""
        notes = [_make_note(text="引用テキスト", renote_id="renoted_note")]
        result = filter_notes(notes, BOT_USER_ID)
        assert len(result) == 1

    def test_empty_text_excluded(self) -> None:
        """テキストが空文字のノートは除外される"""
        notes = [_make_note(text="")]
        result = filter_notes(notes, BOT_USER_ID)
        assert len(result) == 0

    def test_none_text_excluded(self) -> None:
        """テキストが None のノートは除外される"""
        notes = [_make_note(text=None)]
        result = filter_notes(notes, BOT_USER_ID)
        assert len(result) == 0

    def test_mixed_notes(self) -> None:
        """複数のノートに対するフィルタリング"""
        notes = [
            _make_note(note_id="1", visibility="public", text="OK"),
            _make_note(note_id="2", visibility="followers", text="NG"),
            _make_note(note_id="3", user_id=BOT_USER_ID, text="bot"),
            _make_note(note_id="4", text=None, renote_id="renote"),
            _make_note(note_id="5", text="引用", renote_id="renote"),
        ]
        result = filter_notes(notes, BOT_USER_ID)
        assert len(result) == 2
        assert result[0].note_id == "1"
        assert result[1].note_id == "5"

    def test_cw_note_passes(self) -> None:
        """CW 付きノートでもテキストがあれば通過する"""
        note = NoteEvent(
            note_id="cw1",
            user_id="user1",
            username="test",
            text="テキスト本文",
            cw="閲覧注意",
            visibility="public",
            reply_id=None,
            renote_id=None,
            has_poll=False,
        )
        result = filter_notes([note], BOT_USER_ID)
        assert len(result) == 1
