"""WebSocket ストリーミング管理

Misskey WebSocket に接続し、イベントを正規化してディスパッチする。
無限再接続ループ、自前 keepalive、チャンネル固定ID管理を実装。
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from bot.core.models import FollowedEvent, MentionEvent, NoteEvent

logger = logging.getLogger(__name__)

# チャンネル ID の命名規則: "{チャンネル名}-{連番}"
CHANNEL_IDS = {
    "homeTimeline": "home-1",
    "localTimeline": "local-1",
    "hybridTimeline": "social-1",
    "globalTimeline": "global-1",
    "main": "main-1",  # フォロー通知・メンション等
}

# チャンネル名 → ソース名の対応
CHANNEL_TO_SOURCE = {
    "home-1": "home",
    "local-1": "local",
    "social-1": "social",
    "global-1": "global",
    "main-1": "main",
}


class StreamingManager:
    """WebSocket ストリーミング管理

    Misskey の WebSocket に接続し、受信メッセージを
    内部イベント DTO に正規化してコールバック方式でディスパッチする。
    """

    def __init__(
        self,
        instance_url: str,
        token: str,
        channels: list[str] | None = None,
    ) -> None:
        self._instance_url = (
            instance_url.rstrip("/")
            .replace("https://", "wss://")
            .replace("http://", "ws://")
        )
        self._token = token
        self._channels = channels or ["homeTimeline", "main"]
        self._handlers: dict[str, list[Callable]] = {}
        self._ws: Any = None
        self._running = False
        self._retry_count = 0

    def on(self, event_type: str, handler: Callable) -> None:
        """イベントハンドラを登録する。同一イベントに複数ハンドラ登録可能。

        Args:
            event_type: "note", "mention", "followed"
            handler: async def handler(event: NoteEvent | MentionEvent | FollowedEvent)
        """
        self._handlers.setdefault(event_type, []).append(handler)
        logger.debug(
            "ハンドラを登録しました: %s -> %s",
            event_type,
            handler.__qualname__,
        )

    async def start(self) -> None:
        """ストリーミングを開始する（無限再接続ループ）。"""
        self._running = True
        await self._connect_loop()

    async def stop(self) -> None:
        """ストリーミングを停止する。"""
        self._running = False
        if self._ws:
            await self._ws.close()
            logger.info("WebSocket 接続を閉じました")

    async def _connect_loop(self) -> None:
        """無限再接続ループ（上限なし）。"""
        while self._running:
            try:
                ws_url = f"{self._instance_url}/streaming?i={self._token}"
                logger.info("WebSocket に接続中...")

                async with websockets.connect(
                    ws_url,
                    ping_interval=None,  # 自前管理
                ) as ws:
                    self._ws = ws
                    self._retry_count = 0
                    logger.info("WebSocket に接続しました")

                    # チャンネル購読
                    await self._subscribe_channels()

                    # Keepalive と メッセージ受信を並行実行
                    await asyncio.gather(
                        self._keepalive_loop(),
                        self._message_handler(),
                    )

            except ConnectionClosed as e:
                logger.warning("WebSocket 接続が切断されました: %s", str(e))
            except Exception as e:
                logger.error("WebSocket エラー: %s", str(e))
            finally:
                self._ws = None

            if self._running:
                wait = min(5 * (2**self._retry_count), 300)
                self._retry_count += 1
                logger.info(
                    "%.1f 秒後に再接続します（リトライ #%d）", wait, self._retry_count
                )
                await asyncio.sleep(wait)

    async def _subscribe_channels(self) -> None:
        """チャンネルを購読する。接続・再接続のたびに実行。"""
        if not self._ws:
            return

        for channel in self._channels:
            channel_id = CHANNEL_IDS.get(channel, f"{channel}-1")
            msg = {
                "type": "connect",
                "body": {
                    "channel": channel,
                    "id": channel_id,
                },
            }
            await self._ws.send(json.dumps(msg))
            logger.info("チャンネルを購読しました: %s (id=%s)", channel, channel_id)

    async def _keepalive_loop(self) -> None:
        """30秒ごとに ping を送信する。"""
        try:
            while self._running and self._ws:
                await asyncio.sleep(30)
                if self._ws:
                    pong = await self._ws.ping()
                    try:
                        await asyncio.wait_for(pong, timeout=10)
                    except asyncio.TimeoutError:
                        logger.warning(
                            "Pong がタイムアウトしました。接続を強制切断します"
                        )
                        await self._ws.close()
                        return
        except Exception as e:
            logger.debug("Keepalive ループが終了しました: %s", str(e))

    async def _message_handler(self) -> None:
        """WebSocket メッセージを受信し、正規化してディスパッチする。"""
        if not self._ws:
            return

        async for raw_message in self._ws:
            try:
                data = json.loads(raw_message)
                await self._process_message(data)
            except json.JSONDecodeError:
                logger.warning("不正なJSONメッセージを受信しました")
            except Exception as e:
                logger.error(
                    "メッセージ処理でエラーが発生しました: %s", str(e), exc_info=True
                )

    async def _process_message(self, data: dict) -> None:
        """受信メッセージを解析してディスパッチする。"""
        msg_type = data.get("type")

        if msg_type == "channel":
            body = data.get("body", {})
            channel_id = body.get("id", "")
            channel_type = body.get("type", "")
            channel_body = body.get("body", {})

            source = CHANNEL_TO_SOURCE.get(channel_id, "home")

            if channel_type == "note":
                event = self._normalize_note(channel_body, source)
                await self._dispatch("note", event)

            elif channel_type == "mention":
                event = self._normalize_mention(channel_body)
                await self._dispatch("mention", event)

            elif channel_type == "followed":
                event = self._normalize_followed(channel_body)
                await self._dispatch("followed", event)

    async def _dispatch(self, event_type: str, event: Any) -> None:
        """登録済みハンドラを順に呼び出す。

        1つのハンドラの例外が他に影響しないようにする。
        """
        for handler in self._handlers.get(event_type, []):
            try:
                await handler(event)
            except Exception as e:
                logger.error(
                    "ハンドラ %s でエラーが発生しました: %s",
                    handler.__qualname__,
                    str(e),
                    exc_info=True,
                )

    def _normalize_note(self, body: dict, channel: str) -> NoteEvent:
        """生の Misskey JSON を NoteEvent に変換する。"""
        return NoteEvent(
            note_id=body["id"],
            user_id=body["userId"],
            username=body.get("user", {}).get("username"),
            text=body.get("text"),
            cw=body.get("cw"),
            visibility=body.get("visibility", "public"),
            reply_id=body.get("replyId"),
            renote_id=body.get("renoteId"),
            has_poll=body.get("poll") is not None,
            file_ids=[f["id"] for f in body.get("files", [])],
            channel=channel,
            raw=body,
        )

    def _normalize_mention(self, body: dict) -> MentionEvent:
        """生の Misskey JSON を MentionEvent に変換する。"""
        return MentionEvent(
            note_id=body["id"],
            user_id=body["userId"],
            username=body.get("user", {}).get("username"),
            text=body.get("text"),
            cw=body.get("cw"),
            visibility=body.get("visibility", "public"),
            raw=body,
        )

    def _normalize_followed(self, body: dict) -> FollowedEvent:
        """生の Misskey JSON を FollowedEvent に変換する。"""
        return FollowedEvent(
            user_id=body["id"],
            username=body.get("username"),
            raw=body,
        )
