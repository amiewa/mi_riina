"""WordcloudManager における bot 自身ノート除外テスト

WordcloudManager.on_note が bot 自身のノートをワードストックに含めないことを検証する。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.core.models import NoteEvent


BOT_USER_ID = "bot_user_id_123"
OTHER_USER_ID = "other_user_456"


def _make_note_event(
    user_id: str = OTHER_USER_ID,
    text: str = "テストメッセージ",
    visibility: str = "public",
    renote_id: str | None = None,
    channel: str = "home",
) -> NoteEvent:
    """テスト用 NoteEvent を生成する。"""
    return NoteEvent(
        note_id="note_test_1",
        user_id=user_id,
        username="testuser",
        text=text,
        cw=None,
        visibility=visibility,
        reply_id=None,
        renote_id=renote_id,
        has_poll=False,
        channel=channel,
    )


def _make_wordcloud_manager(bot_user_id: str = BOT_USER_ID) -> "WordcloudManager":
    """テスト用 WordcloudManager を生成する。"""
    from bot.managers.wordcloud_manager import WordcloudManager

    mock_config = MagicMock()
    mock_config.posting.wordcloud.enabled = True
    mock_config.posting.wordcloud.timeline_source = "home"
    mock_config.posting.wordcloud.max_note_length = 500
    mock_config.posting.wordcloud.max_keywords_per_note = 10
    mock_config.posting.wordcloud.min_keyword_length = 2
    mock_config.posting.wordcloud.exclude_keywords = []
    mock_config.posting.wordcloud.analysis_concurrency = 1

    mock_db = MagicMock()
    mock_db.stock_words = AsyncMock()
    mock_db.get_stock_count = AsyncMock(return_value=0)

    mock_misskey = MagicMock()
    mock_misskey.bot_user_id = bot_user_id

    mock_tokenizer = MagicMock()
    mock_tokenizer.extract_keywords = MagicMock(return_value=["テスト", "メッセージ"])

    mock_ng_word = MagicMock()
    mock_ng_word.contains_ng_word = MagicMock(return_value=False)

    manager = WordcloudManager(
        config=mock_config,
        db=mock_db,
        misskey=mock_misskey,
        tokenizer=mock_tokenizer,
        ng_word_manager=mock_ng_word,
        session=None,
    )
    manager._font_path = None
    return manager


class TestWordcloudManagerBotSelfExclusion:
    """WordcloudManager.on_note での bot 自身ノート除外テスト"""

    @pytest.mark.asyncio
    async def test_bot_own_note_not_stocked(self) -> None:
        """bot 自身のノートはワードストックに追加されない"""
        manager = _make_wordcloud_manager(bot_user_id=BOT_USER_ID)

        # bot 自身のノート
        event = _make_note_event(user_id=BOT_USER_ID, text="ワードクラウドのテスト投稿")
        await manager.on_note(event)

        # stock_words が呼ばれていないこと
        manager._db.stock_words.assert_not_called()

    @pytest.mark.asyncio
    async def test_other_user_note_is_stocked(self) -> None:
        """他ユーザーのノートはワードストックに追加される"""
        manager = _make_wordcloud_manager(bot_user_id=BOT_USER_ID)

        # 他ユーザーのノート
        event = _make_note_event(user_id=OTHER_USER_ID, text="テストメッセージ")
        await manager.on_note(event)

        # stock_words が呼ばれること
        manager._db.stock_words.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_bot_user_id_skips_all_notes(self) -> None:
        """bot_user_id が未設定（空文字）の場合はすべてのノートをスキップする"""
        manager = _make_wordcloud_manager(bot_user_id="")

        # 他ユーザーのノートでも、bot_user_id 未設定時はスキップ
        event = _make_note_event(user_id=OTHER_USER_ID, text="テストメッセージ")
        await manager.on_note(event)

        # stock_words が呼ばれないこと（安全側に倒す）
        manager._db.stock_words.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_reply_not_stocked(self) -> None:
        """bot が送信したリプライもワードストックに追加されない"""
        manager = _make_wordcloud_manager(bot_user_id=BOT_USER_ID)

        # bot 自身のリプライノート（reply_id あり）
        event = NoteEvent(
            note_id="reply_note_1",
            user_id=BOT_USER_ID,
            username="riina",
            text="こんにちは！お返事です。",
            cw=None,
            visibility="public",
            reply_id="original_note_id",
            renote_id=None,
            has_poll=False,
            channel="home",
        )
        await manager.on_note(event)

        manager._db.stock_words.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_timeline_post_not_stocked(self) -> None:
        """bot が投稿したタイムライン投稿もワードストックに追加されない"""
        manager = _make_wordcloud_manager(bot_user_id=BOT_USER_ID)

        # bot のタイムライン投稿（ランダム投稿など）
        event = _make_note_event(
            user_id=BOT_USER_ID,
            text="今日もよろしくね！",
        )
        await manager.on_note(event)

        manager._db.stock_words.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_bots_own_notes_all_excluded(self) -> None:
        """複数の bot 自身ノートがすべて除外される"""
        manager = _make_wordcloud_manager(bot_user_id=BOT_USER_ID)

        bot_notes = [
            _make_note_event(user_id=BOT_USER_ID, text=f"bot投稿 {i}")
            for i in range(3)
        ]
        for note in bot_notes:
            await manager.on_note(note)

        manager._db.stock_words.assert_not_called()


class TestWordcloudManagerOtherBotExclusion:
    """WordcloudManager.on_note での他 bot ユーザーノート除外テスト（isBot フラグ）"""

    @pytest.mark.asyncio
    async def test_other_bot_note_not_stocked(self) -> None:
        """isBot=True のユーザーのノートはワードストックに追加されない"""
        manager = _make_wordcloud_manager(bot_user_id=BOT_USER_ID)

        # isBot=True の他 bot ユーザーのノート
        event = NoteEvent(
            note_id="bot_note_1",
            user_id="other_bot_user",
            username="otherbot",
            text="他の bot の投稿テスト",
            cw=None,
            visibility="public",
            reply_id=None,
            renote_id=None,
            has_poll=False,
            channel="home",
            is_bot=True,
        )
        await manager.on_note(event)

        manager._db.stock_words.assert_not_called()

    @pytest.mark.asyncio
    async def test_normal_user_note_is_stocked(self) -> None:
        """isBot=False の通常ユーザーのノートはワードストックに追加される"""
        manager = _make_wordcloud_manager(bot_user_id=BOT_USER_ID)

        # isBot=False の通常ユーザーのノート
        event = NoteEvent(
            note_id="user_note_1",
            user_id=OTHER_USER_ID,
            username="normaluser",
            text="通常ユーザーの投稿テスト",
            cw=None,
            visibility="public",
            reply_id=None,
            renote_id=None,
            has_poll=False,
            channel="home",
            is_bot=False,
        )
        await manager.on_note(event)

        manager._db.stock_words.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_other_bots_all_excluded(self) -> None:
        """複数の他 bot ユーザーのノートがすべて除外される"""
        manager = _make_wordcloud_manager(bot_user_id=BOT_USER_ID)

        other_bot_notes = [
            NoteEvent(
                note_id=f"bot_note_{i}",
                user_id=f"other_bot_{i}",
                username=f"bot{i}",
                text=f"他bot投稿 {i}",
                cw=None,
                visibility="public",
                reply_id=None,
                renote_id=None,
                has_poll=False,
                channel="home",
                is_bot=True,
            )
            for i in range(3)
        ]
        for note in other_bot_notes:
            await manager.on_note(note)

        manager._db.stock_words.assert_not_called()

    @pytest.mark.asyncio
    async def test_is_bot_flag_default_false(self) -> None:
        """is_bot フラグのデフォルト値が False であることを確認する"""
        from bot.core.models import NoteEvent

        event = NoteEvent(
            note_id="note1",
            user_id="user1",
            username="user",
            text="テスト",
            cw=None,
            visibility="public",
            reply_id=None,
            renote_id=None,
            has_poll=False,
        )
        assert event.is_bot is False
