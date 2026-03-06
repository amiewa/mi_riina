"""Misskey REST API クライアント

mipac ラッパーとして実装し、各 Manager は公開メソッドのみを使用する。
mipac が Misskey 2025.12.2 で正常動作しない場合は aiohttp 直接実装に切り替える。
"""

import logging
from typing import Any

from mipac.client import Client as MipacClient

from bot.core.models import NoteEvent

logger = logging.getLogger(__name__)

# visibility フィルタ: followers / specified は常に除外
EXCLUDED_VISIBILITIES = {"followers", "specified"}


def filter_notes(notes: list[NoteEvent], bot_user_id: str) -> list[NoteEvent]:
    """共通フィルタ: TL系機能で取得したノートをフィルタリングする。

    除外対象:
    - followers / specified visibility
    - bot 自身のノート
    - テキストなし Renote（renote_id あり かつ text が null）
    - テキストが null または空文字
    """
    return [
        n
        for n in notes
        if n.visibility not in EXCLUDED_VISIBILITIES
        and n.user_id != bot_user_id
        and not (n.renote_id is not None and n.text is None)
        and n.text  # None または空文字を除外
    ]


class MisskeyClient:
    """Misskey REST API クライアント

    各 Manager はこのクラスの公開メソッドのみを使用する。
    内部実装が mipac であれ aiohttp 直接実装であれ、
    このインターフェースは変わらない。
    """

    def __init__(self, instance_url: str, api_token: str) -> None:
        self._instance_url = instance_url.rstrip("/")
        self._token = api_token
        self._client: MipacClient | None = None
        self._bot_user_id: str = ""

    async def initialize(self) -> None:
        """クライアントを初期化し、bot 自身の user_id を取得する。"""
        self._client = MipacClient(self._instance_url, self._token)
        await self._client.http.login()

        # bot 自身のユーザー情報を取得
        me = await self.get_me()
        self._bot_user_id = me["id"]
        logger.info(
            "Misskey クライアントを初期化しました（user_id: %s）",
            self._bot_user_id,
        )

    @property
    def bot_user_id(self) -> str:
        """起動時に取得した bot 自身の user_id。"""
        return self._bot_user_id

    @property
    def token(self) -> str:
        """API トークン（WebSocket 接続用）。"""
        return self._token

    @property
    def instance_url(self) -> str:
        """インスタンス URL。"""
        return self._instance_url

    async def create_note(
        self,
        text: str,
        visibility: str = "home",
        reply_id: str | None = None,
        file_ids: list[str] | None = None,
        poll: dict | None = None,
    ) -> str:
        """ノートを投稿し、note_id を返す。"""
        assert self._client is not None

        params: dict[str, Any] = {
            "text": text,
            "visibility": visibility,
        }
        if reply_id:
            params["replyId"] = reply_id
        if file_ids:
            params["fileIds"] = file_ids
        if poll:
            params["poll"] = poll

        result = await self._client.http.request(
            route="/api/notes/create",
            json=params,
            auth=True,
            lower=True,
        )
        note_id = result["created_note"]["id"]
        logger.info("ノートを投稿しました（note_id=%s）", note_id)
        return note_id

    async def delete_note(self, note_id: str) -> None:
        """ノートを削除する。404 は成功扱い。"""
        assert self._client is not None

        try:
            await self._client.http.request(
                route="/api/notes/delete",
                json={"noteId": note_id},
                auth=True,
                lower=True,
            )
            logger.info("ノートを削除しました（note_id=%s）", note_id)
        except Exception as e:
            if "404" in str(e) or "NO_SUCH_NOTE" in str(e):
                logger.info(
                    "ノートは既に削除されています（note_id=%s）", note_id
                )
            else:
                raise

    async def create_reaction(self, note_id: str, reaction: str) -> None:
        """リアクションを送信する。"""
        assert self._client is not None

        await self._client.http.request(
            route="/api/notes/reactions/create",
            json={"noteId": note_id, "reaction": reaction},
            auth=True,
            lower=True,
        )
        logger.debug(
            "リアクションを送信しました（note_id=%s, reaction=%s）",
            note_id, reaction,
        )

    async def upload_file(self, file_path: str) -> str:
        """ファイルをドライブにアップロードし、file_id を返す。"""
        assert self._client is not None

        # mipac のアップロード API を試行
        # 未対応の場合は aiohttp で直接実装に切り替え
        import aiohttp

        url = f"{self._instance_url}/api/drive/files/create"
        with open(file_path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field("i", self._token)
            data.add_field(
                "file",
                f,
                filename=file_path.split("/")[-1],
            )

            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise RuntimeError(
                            f"ファイルアップロードに失敗しました: {resp.status} {error_text[:200]}"
                        )
                    result = await resp.json()
                    file_id = result["id"]
                    logger.info(
                        "ファイルをアップロードしました（file_id=%s）", file_id
                    )
                    return file_id

    async def delete_file(self, file_id: str) -> None:
        """ドライブファイルを削除する。404 は成功扱い。"""
        assert self._client is not None

        try:
            await self._client.http.request(
                route="/api/drive/files/delete",
                json={"fileId": file_id},
                auth=True,
                lower=True,
            )
            logger.info("ドライブファイルを削除しました（file_id=%s）", file_id)
        except Exception as e:
            if "404" in str(e) or "NO_SUCH_FILE" in str(e):
                logger.info(
                    "ファイルは既に削除されています（file_id=%s）", file_id
                )
            else:
                raise

    async def get_me(self) -> dict:
        """bot 自身のユーザー情報を取得する。"""
        assert self._client is not None

        result = await self._client.http.request(
            route="/api/i",
            json={},
            auth=True,
            lower=True,
        )
        return result

    async def get_timeline(
        self, source: str, limit: int = 20
    ) -> list[dict]:
        """指定ソースの TL からノートを取得する。ページネーション対応。"""
        assert self._client is not None

        # ソースと API エンドポイントの対応
        endpoints = {
            "home": "/api/notes/timeline",
            "local": "/api/notes/local-timeline",
            "social": "/api/notes/hybrid-timeline",
            "global": "/api/notes/global-timeline",
        }
        endpoint = endpoints.get(source, "/api/notes/timeline")

        all_notes: list[dict] = []
        until_id: str | None = None
        remaining = limit

        while remaining > 0:
            params: dict[str, Any] = {
                "limit": min(remaining, 100),
            }
            if until_id:
                params["untilId"] = until_id

            notes = await self._client.http.request(
                route=endpoint,
                json=params,
                auth=True,
                lower=True,
            )

            if not notes:
                break

            all_notes.extend(notes)
            remaining -= len(notes)
            until_id = notes[-1]["id"]

        return all_notes[:limit]

    async def follow_user(self, user_id: str) -> None:
        """ユーザーをフォローする。"""
        assert self._client is not None

        await self._client.http.request(
            route="/api/following/create",
            json={"userId": user_id},
            auth=True,
            lower=True,
        )
        logger.info("ユーザーをフォローしました（user_id=%s）", user_id)

    async def unfollow_user(self, user_id: str) -> None:
        """ユーザーのフォローを解除する。"""
        assert self._client is not None

        await self._client.http.request(
            route="/api/following/delete",
            json={"userId": user_id},
            auth=True,
            lower=True,
        )
        logger.info("ユーザーのフォローを解除しました（user_id=%s）", user_id)

    async def get_followers(self, limit: int = 100) -> list[dict]:
        """フォロワー一覧を取得する。ページネーション対応。"""
        assert self._client is not None

        all_followers: list[dict] = []
        until_id: str | None = None
        remaining = limit

        while remaining > 0:
            params: dict[str, Any] = {
                "userId": self._bot_user_id,
                "limit": min(remaining, 100),
            }
            if until_id:
                params["untilId"] = until_id

            followers = await self._client.http.request(
                route="/api/users/followers",
                json=params,
                auth=True,
                lower=True,
            )

            if not followers:
                break

            all_followers.extend(followers)
            remaining -= len(followers)
            until_id = followers[-1].get("id", "")

        return all_followers[:limit]

    async def get_following(self, limit: int = 100) -> list[dict]:
        """フォロー一覧を取得する。ページネーション対応。"""
        assert self._client is not None

        all_following: list[dict] = []
        until_id: str | None = None
        remaining = limit

        while remaining > 0:
            params: dict[str, Any] = {
                "userId": self._bot_user_id,
                "limit": min(remaining, 100),
            }
            if until_id:
                params["untilId"] = until_id

            following = await self._client.http.request(
                route="/api/users/following",
                json=params,
                auth=True,
                lower=True,
            )

            if not following:
                break

            all_following.extend(following)
            remaining -= len(following)
            until_id = following[-1].get("id", "")

        return all_following[:limit]

    async def close(self) -> None:
        """クライアントを終了する。"""
        if self._client:
            await self._client.http.close_session()
            logger.info("Misskey クライアントを終了しました")
