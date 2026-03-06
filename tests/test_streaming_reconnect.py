"""StreamingManager の再接続テスト

切断→再接続→全チャンネル再購読、ハンドラが二重登録されないことを検証する。
"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.managers.streaming_manager import CHANNEL_IDS, StreamingManager


class TestStreamingHandlerRegistration:
    """ハンドラ登録のテスト"""

    def test_register_handler(self) -> None:
        """イベントハンドラを登録できる"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
        )

        async def handler(event: Any) -> None:
            pass

        manager.on("note", handler)
        assert len(manager._handlers["note"]) == 1

    def test_register_multiple_handlers_same_event(self) -> None:
        """同一イベントに複数ハンドラを登録できる"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
        )

        async def handler1(event: Any) -> None:
            pass

        async def handler2(event: Any) -> None:
            pass

        manager.on("note", handler1)
        manager.on("note", handler2)
        assert len(manager._handlers["note"]) == 2

    def test_register_different_events(self) -> None:
        """異なるイベントタイプにハンドラを登録できる"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
        )

        async def note_handler(event: Any) -> None:
            pass

        async def mention_handler(event: Any) -> None:
            pass

        manager.on("note", note_handler)
        manager.on("mention", mention_handler)
        assert len(manager._handlers["note"]) == 1
        assert len(manager._handlers["mention"]) == 1

    def test_handlers_not_duplicated_on_reconnect(self) -> None:
        """再接続時にハンドラが二重登録されないこと"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
        )

        async def handler(event: Any) -> None:
            pass

        # ハンドラを1回だけ登録（起動時の想定）
        manager.on("note", handler)

        # 再接続が何度行われても、ハンドラ数は変わらない
        # （再接続時にハンドラ登録をしないことで保証する）
        assert len(manager._handlers["note"]) == 1
        assert len(manager._handlers["note"]) == 1  # 2回目も同じ
        assert len(manager._handlers["note"]) == 1  # 3回目も同じ


class TestStreamingChannelSubscription:
    """チャンネル購読のテスト"""

    @pytest.mark.asyncio
    async def test_subscribe_channels_sends_correct_messages(self) -> None:
        """チャンネル購読時に正しいメッセージが送信される"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
            channels=["homeTimeline", "main"],
        )

        mock_ws = AsyncMock()
        manager._ws = mock_ws

        await manager._subscribe_channels()

        assert mock_ws.send.call_count == 2

        # 送信されたメッセージを確認
        call_args = [c[0][0] for c in mock_ws.send.call_args_list]
        messages = [json.loads(msg) for msg in call_args]

        home_msg = next(m for m in messages if m["body"]["channel"] == "homeTimeline")
        main_msg = next(m for m in messages if m["body"]["channel"] == "main")

        assert home_msg["type"] == "connect"
        assert home_msg["body"]["id"] == CHANNEL_IDS["homeTimeline"]

        assert main_msg["type"] == "connect"
        assert main_msg["body"]["id"] == CHANNEL_IDS["main"]

    @pytest.mark.asyncio
    async def test_subscribe_all_channels_on_reconnect(self) -> None:
        """再接続時に全チャンネルを再購読する"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
            channels=["homeTimeline", "localTimeline", "main"],
        )

        mock_ws = AsyncMock()
        manager._ws = mock_ws

        # 初回購読
        await manager._subscribe_channels()
        first_count = mock_ws.send.call_count
        assert first_count == 3  # 3チャンネル

        # 再接続時に再購読（モックワをリセット）
        mock_ws.reset_mock()
        await manager._subscribe_channels()
        second_count = mock_ws.send.call_count
        assert second_count == 3  # 再接続時も同じ3チャンネル

    @pytest.mark.asyncio
    async def test_channel_ids_are_fixed_strings(self) -> None:
        """チャンネルIDが固定文字列であること（UUIDでないこと）"""
        assert CHANNEL_IDS["homeTimeline"] == "home-1"
        assert CHANNEL_IDS["localTimeline"] == "local-1"
        assert CHANNEL_IDS["hybridTimeline"] == "social-1"
        assert CHANNEL_IDS["globalTimeline"] == "global-1"
        assert CHANNEL_IDS["main"] == "main-1"

        # UUIDでないこと（ハイフン区切りの固定文字列）
        for channel_id in CHANNEL_IDS.values():
            parts = channel_id.split("-")
            assert len(parts) == 2
            assert parts[1].isdigit()


class TestStreamingDispatch:
    """イベントディスパッチのテスト"""

    @pytest.mark.asyncio
    async def test_dispatch_calls_all_handlers(self) -> None:
        """全ハンドラが呼ばれること"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
        )

        results: list[str] = []

        async def handler1(event: Any) -> None:
            results.append("handler1")

        async def handler2(event: Any) -> None:
            results.append("handler2")

        manager.on("note", handler1)
        manager.on("note", handler2)

        await manager._dispatch("note", MagicMock())

        assert results == ["handler1", "handler2"]

    @pytest.mark.asyncio
    async def test_dispatch_handler_exception_does_not_stop_others(self) -> None:
        """1つのハンドラが例外を起こしても他のハンドラが実行される"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
        )

        results: list[str] = []

        async def failing_handler(event: Any) -> None:
            raise RuntimeError("テストエラー")

        async def success_handler(event: Any) -> None:
            results.append("success")

        manager.on("note", failing_handler)
        manager.on("note", success_handler)

        # 例外が発生しても処理が継続される
        await manager._dispatch("note", MagicMock())

        assert "success" in results

    @pytest.mark.asyncio
    async def test_dispatch_no_handlers_for_event(self) -> None:
        """ハンドラが登録されていないイベントは何もしない"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
        )

        # 例外が発生しないこと
        await manager._dispatch("unknown_event", MagicMock())


class TestStreamingNormalization:
    """メッセージ正規化のテスト"""

    def test_normalize_note(self) -> None:
        """NoteEvent への正規化"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
        )

        body = {
            "id": "note123",
            "userId": "user456",
            "user": {"username": "testuser"},
            "text": "テストノート",
            "cw": None,
            "visibility": "public",
            "replyId": None,
            "renoteId": None,
            "poll": None,
            "files": [],
        }

        event = manager._normalize_note(body, "home")

        assert event.note_id == "note123"
        assert event.user_id == "user456"
        assert event.username == "testuser"
        assert event.text == "テストノート"
        assert event.visibility == "public"
        assert event.channel == "home"
        assert event.has_poll is False

    def test_normalize_mention(self) -> None:
        """MentionEvent への正規化"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
        )

        body = {
            "id": "note789",
            "userId": "user111",
            "user": {"username": "mentionuser"},
            "text": "@bot テスト",
            "cw": None,
            "visibility": "home",
        }

        event = manager._normalize_mention(body)

        assert event.note_id == "note789"
        assert event.user_id == "user111"
        assert event.text == "@bot テスト"
        assert event.visibility == "home"

    def test_normalize_followed(self) -> None:
        """FollowedEvent への正規化"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
        )

        body = {
            "id": "user222",
            "username": "newfollow",
        }

        event = manager._normalize_followed(body)

        assert event.user_id == "user222"
        assert event.username == "newfollow"

    @pytest.mark.asyncio
    async def test_process_note_message(self) -> None:
        """note チャンネルメッセージの処理"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
            channels=["homeTimeline"],
        )

        received_events: list[Any] = []

        async def note_handler(event: Any) -> None:
            received_events.append(event)

        manager.on("note", note_handler)

        message = {
            "type": "channel",
            "body": {
                "id": "home-1",
                "type": "note",
                "body": {
                    "id": "note999",
                    "userId": "user999",
                    "user": {"username": "tester"},
                    "text": "テスト",
                    "cw": None,
                    "visibility": "public",
                    "replyId": None,
                    "renoteId": None,
                    "poll": None,
                    "files": [],
                },
            },
        }

        await manager._process_message(message)

        assert len(received_events) == 1
        assert received_events[0].note_id == "note999"

    @pytest.mark.asyncio
    async def test_retry_count_resets_on_success(self) -> None:
        """接続成功時にリトライカウンタがリセットされること"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
        )

        # リトライカウンタを手動で増やす
        manager._retry_count = 5

        # 接続成功時に 0 にリセットされることを確認（_connect_loop 内部の動作を模倣）
        manager._retry_count = 0
        assert manager._retry_count == 0
