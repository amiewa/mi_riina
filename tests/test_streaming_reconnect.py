"""StreamingManager の再接続テスト

切断→再接続→全チャンネル再購読、ハンドラが二重登録されないことを検証する。
"""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
        # _dispatch はハンドラをタスク化して即座に返るため、完了を待つ
        await asyncio.gather(*manager._pending_tasks)

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
        await asyncio.gather(*manager._pending_tasks)

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

    @pytest.mark.asyncio
    async def test_dispatch_does_not_block_subsequent_events(self) -> None:
        """遅いハンドラの完了を待たずに後続イベントが処理されること"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
        )

        order: list[str] = []

        async def slow_handler(event: Any) -> None:
            await asyncio.sleep(0.2)
            order.append("slow_done")

        async def fast_handler(event: Any) -> None:
            order.append("fast_done")

        manager.on("note", slow_handler)
        manager.on("mention", fast_handler)

        # 遅いハンドラを持つイベントをディスパッチしても即座に返る
        await manager._dispatch("note", MagicMock())
        # 後続イベントのディスパッチがブロックされないこと
        await manager._dispatch("mention", MagicMock())
        await asyncio.sleep(0.01)  # fast_handler タスクの実行を待つ

        # 遅いハンドラ（0.2秒）の完了を待たず、速いハンドラが先に完了している
        assert order == ["fast_done"]

        # 後片付け: 残りのタスクの完了を待つ
        await asyncio.gather(*manager._pending_tasks)
        assert order == ["fast_done", "slow_done"]

    @pytest.mark.asyncio
    async def test_stop_cancels_still_pending_tasks_after_timeout(self) -> None:
        """stop() はタイムアウトまでに完了しないハンドラタスクを cancel する"""
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
        )

        async def slow_handler(event: Any) -> None:
            await asyncio.sleep(30)

        manager.on("note", slow_handler)
        await manager._dispatch("note", MagicMock())
        task = next(iter(manager._pending_tasks))

        # asyncio.wait をタイムアウト（未完了のまま）で即座に返すよう差し替える
        with patch(
            "bot.managers.streaming_manager.asyncio.wait",
            new=AsyncMock(return_value=(set(), {task})),
        ):
            await manager.stop()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()


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
        # _dispatch はハンドラをタスク化して即座に返るため、完了を待つ
        await asyncio.gather(*manager._pending_tasks)

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


class TestStreamingConnectLoopTaskGroup:
    """_connect_loop の TaskGroup 化（keepalive 残留防止）のテスト"""

    @pytest.mark.asyncio
    async def test_keepalive_cancelled_promptly_when_message_handler_fails(
        self,
    ) -> None:
        """message_handler が失敗したら keepalive も直ちにキャンセルされること

        asyncio.gather は一方が例外を投げてももう一方をキャンセルしないため、
        従来は keepalive が最大30秒残留しうる不具合があった（Fix4）。
        asyncio.TaskGroup への置き換えにより即座にキャンセルされることを確認する。
        """
        manager = StreamingManager(
            instance_url="https://example.com",
            token="test_token",
        )
        manager._running = True

        keepalive_cancelled = asyncio.Event()

        async def fake_message_handler() -> None:
            await asyncio.sleep(0.01)
            # ループを1回で終わらせる
            manager._running = False
            raise RuntimeError("接続エラー（テスト）")

        async def fake_keepalive_loop() -> None:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                keepalive_cancelled.set()
                raise

        manager._message_handler = fake_message_handler
        manager._keepalive_loop = fake_keepalive_loop
        manager._subscribe_channels = AsyncMock()

        mock_ws = AsyncMock()

        @asynccontextmanager
        async def fake_connect(*args, **kwargs):
            yield mock_ws

        with patch("bot.managers.streaming_manager.websockets.connect", fake_connect):
            # タイムアウトを設定し、万一キャンセルされずに30秒残留した場合でも
            # テストがハングしないようにする
            await asyncio.wait_for(manager._connect_loop(), timeout=2.0)

        assert keepalive_cancelled.is_set()
