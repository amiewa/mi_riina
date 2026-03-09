"""bot 自身ノート除外テスト

reply / reaction の各経路で bot 自身のノートを弾けることを検証する。
（wordcloud は StreamingManager 経由でのフィルタリングを filter_notes で対応済み）
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.core.models import MentionEvent, NoteEvent


def _make_note_event(
    note_id: str = "note1",
    user_id: str = "user1",
    text: str = "テスト",
    visibility: str = "public",
    renote_id: str | None = None,
) -> NoteEvent:
    """テスト用 NoteEvent を生成する。"""
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


def _make_mention_event(
    note_id: str = "note1",
    user_id: str = "user1",
    text: str = "@riina こんにちは",
    visibility: str = "public",
) -> MentionEvent:
    """テスト用 MentionEvent を生成する。"""
    return MentionEvent(
        note_id=note_id,
        user_id=user_id,
        username="testuser",
        text=text,
        cw=None,
        visibility=visibility,
    )


BOT_USER_ID = "bot_user_id"


class TestReactionManagerBotSelfExclusion:
    """ReactionManager における bot 自身除外テスト"""

    @pytest.fixture
    def mock_misskey(self) -> MagicMock:
        """MisskeyClient のモック"""
        mock = MagicMock()
        mock.bot_user_id = BOT_USER_ID
        mock.create_reaction = AsyncMock()
        return mock

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Database のモック"""
        mock = MagicMock()
        mock.is_mutual = AsyncMock(return_value=True)
        mock.has_reacted = AsyncMock(return_value=False)
        mock.record_reaction = AsyncMock()
        return mock

    @pytest.fixture
    def mock_config(self) -> MagicMock:
        """AppConfig のモック"""
        config = MagicMock()
        config.reaction.enabled = True
        config.reaction.mutual_only = False  # 簡略化のためFalse
        config.reaction.rules = []
        config.posting.night_mode.enabled = False
        config.posting.night_mode.start_hour = 23
        config.posting.night_mode.end_hour = 5
        config.bot.timezone = "Asia/Tokyo"
        return config

    @pytest.mark.asyncio
    async def test_bot_self_note_skipped(
        self, mock_config: MagicMock, mock_db: MagicMock, mock_misskey: MagicMock
    ) -> None:
        """bot 自身のノートはリアクションを送信しない"""
        from bot.managers.reaction_manager import ReactionManager

        manager = ReactionManager(mock_config, mock_db, mock_misskey)

        # bot 自身のノートイベント
        event = _make_note_event(user_id=BOT_USER_ID, text="おはよう")

        await manager.on_note(event)

        # リアクションが送信されていないこと
        mock_misskey.create_reaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_other_user_note_processed(
        self, mock_config: MagicMock, mock_db: MagicMock, mock_misskey: MagicMock
    ) -> None:
        """他ユーザーのノートはリアクション処理される（ルールがなければ何もしないだけ）"""
        from bot.managers.reaction_manager import ReactionManager

        manager = ReactionManager(mock_config, mock_db, mock_misskey)

        # 別ユーザーのノートイベント（ルールなし → リアクションなし）
        event = _make_note_event(user_id="other_user", text="おはよう")

        # 例外なく処理されること
        await manager.on_note(event)


class TestReplyManagerBotSelfExclusion:
    """ReplyManager における bot 自身除外テスト"""

    @pytest.fixture
    def mock_misskey(self) -> MagicMock:
        """MisskeyClient のモック"""
        mock = MagicMock()
        mock.bot_user_id = BOT_USER_ID
        mock.create_note = AsyncMock()
        return mock

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Database のモック"""
        mock = MagicMock()
        mock.is_mutual = AsyncMock(return_value=True)
        mock.insert_post = AsyncMock(return_value=1)
        mock.update_post_note_id = AsyncMock()
        mock.delete_post_by_id = AsyncMock()
        return mock

    @pytest.fixture
    def mock_ai(self) -> MagicMock:
        """AIClientBase のモック"""
        mock = MagicMock()
        mock.generate = AsyncMock(return_value="こんにちは！")
        return mock

    @pytest.fixture
    def mock_ng_word(self) -> MagicMock:
        """NGWordManager のモック"""
        mock = MagicMock()
        mock.contains_ng_word = MagicMock(return_value=False)
        return mock

    @pytest.fixture
    def mock_rate_limiter(self) -> MagicMock:
        """RateLimiter のモック"""
        mock = MagicMock()
        mock.is_limited = AsyncMock(return_value=False)
        mock.record = AsyncMock()
        return mock

    @pytest.fixture
    def mock_serif_loader(self) -> MagicMock:
        """SerifLoader のモック"""
        mock = MagicMock()
        mock.fallback = {
            "api_error": ["エラー台詞"],
            "ng_word": ["NG台詞"],
            "empty_input": ["空台詞"],
            "rate_limited": ["制限台詞"],
        }
        return mock

    @pytest.fixture
    def mock_config(self) -> MagicMock:
        """AppConfig のモック"""
        config = MagicMock()
        config.reply.enabled = True
        config.reply.mutual_only = False  # 簡略化
        config.reply.ai_concurrency = 1
        config.posting.night_mode.enabled = False
        config.posting.night_mode.start_hour = 23
        config.posting.night_mode.end_hour = 5
        config.bot.timezone = "Asia/Tokyo"
        config.bot.character_prompt_file = "config/character_prompt.md"
        config.ai.input_max_chars = 800
        return config

    @pytest.mark.asyncio
    async def test_bot_self_mention_skipped(
        self,
        mock_config: MagicMock,
        mock_db: MagicMock,
        mock_misskey: MagicMock,
        mock_ai: MagicMock,
        mock_ng_word: MagicMock,
        mock_rate_limiter: MagicMock,
        mock_serif_loader: MagicMock,
    ) -> None:
        """bot 自身のメンションはスキップされる"""
        from bot.managers.reply_manager import ReplyManager

        manager = ReplyManager(
            mock_config,
            mock_db,
            mock_misskey,
            mock_ai,
            mock_ng_word,
            mock_rate_limiter,
            mock_serif_loader,
        )

        # bot 自身からのメンション
        event = _make_mention_event(
            user_id=BOT_USER_ID, text="@riina 自分へのメンション"
        )

        await manager.on_mention(event)

        # ノートが投稿されていないこと
        mock_misskey.create_note.assert_not_called()
        # AI が呼ばれていないこと
        mock_ai.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_other_user_mention_processed(
        self,
        mock_config: MagicMock,
        mock_db: MagicMock,
        mock_misskey: MagicMock,
        mock_ai: MagicMock,
        mock_ng_word: MagicMock,
        mock_rate_limiter: MagicMock,
        mock_serif_loader: MagicMock,
    ) -> None:
        """他ユーザーからのメンションは処理される"""
        from bot.managers.reply_manager import ReplyManager
        from pathlib import Path

        # character_prompt.md が存在しない場合の対応
        with patch.object(Path, "exists", return_value=False):
            manager = ReplyManager(
                mock_config,
                mock_db,
                mock_misskey,
                mock_ai,
                mock_ng_word,
                mock_rate_limiter,
                mock_serif_loader,
            )

        # 別ユーザーからのメンション
        event = _make_mention_event(user_id="other_user", text="@riina こんにちは！")

        await manager.on_mention(event)

        # AI が呼ばれること
        mock_ai.generate.assert_called_once()


class TestFilterNotesWithBotSelf:
    """filter_notes での bot 自身の除外テスト（wordcloud 経路）"""

    def test_bot_self_note_excluded_in_filter(self) -> None:
        """filter_notes が bot 自身のノートを除外する"""
        from bot.core.misskey_client import filter_notes

        notes = [
            _make_note_event(note_id="1", user_id="other_user", text="テスト"),
            _make_note_event(note_id="2", user_id=BOT_USER_ID, text="bot自身"),
            _make_note_event(note_id="3", user_id="another_user", text="別ユーザー"),
        ]

        result = filter_notes(notes, BOT_USER_ID)

        assert len(result) == 2
        assert all(n.user_id != BOT_USER_ID for n in result)
        assert result[0].note_id == "1"
        assert result[1].note_id == "3"

    def test_only_bot_self_notes_all_excluded(self) -> None:
        """bot 自身のノートのみの場合は全て除外される"""
        from bot.core.misskey_client import filter_notes

        notes = [
            _make_note_event(note_id="1", user_id=BOT_USER_ID, text="bot投稿1"),
            _make_note_event(note_id="2", user_id=BOT_USER_ID, text="bot投稿2"),
        ]

        result = filter_notes(notes, BOT_USER_ID)

        assert len(result) == 0

    def test_mixed_notes_bot_self_excluded(self) -> None:
        """混在する場合は bot 自身のみ除外される"""
        from bot.core.misskey_client import filter_notes

        notes = [
            _make_note_event(note_id="1", user_id="user_a", text="ユーザーA"),
            _make_note_event(note_id="2", user_id=BOT_USER_ID, text="bot"),
            _make_note_event(note_id="3", user_id="user_b", text="ユーザーB"),
        ]

        result = filter_notes(notes, BOT_USER_ID)

        assert len(result) == 2
        note_ids = [n.note_id for n in result]
        assert "1" in note_ids
        assert "2" not in note_ids
        assert "3" in note_ids
