"""Misskey REST API クライアント

mipac が Misskey 2025.12.2 で正常動作しないため、
aiohttp で Misskey REST API を直接実装する。
各 Manager は公開メソッドのみを使用する。
"""

import logging
from typing import Any

import aiohttp

from bot.core.models import NoteEvent

logger = logging.getLogger(__name__)

# visibility フィルタ: followers / specified は常に除外
EXCLUDED_VISIBILITIES = {"followers", "specified"}


def dict_to_note_event(n: dict) -> NoteEvent:
    """Misskey API の dict レスポンスを NoteEvent に変換する。

    get_timeline() の結果を NoteEvent に変換するヘルパー。
    timeline_post_manager / poll_manager などで共通利用する。
    """
    return NoteEvent(
        note_id=n.get("id", ""),
        user_id=n.get("userId", ""),
        username=n.get("user", {}).get("username"),
        text=n.get("text"),
        cw=n.get("cw"),
        visibility=n.get("visibility", "public"),
        reply_id=n.get("replyId"),
        renote_id=n.get("renoteId"),
        has_poll=n.get("poll") is not None,
        file_ids=[f["id"] for f in n.get("files", [])],
    )


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
    """Misskey REST API クライアント（aiohttp 直接実装）

    各 Manager はこのクラスの公開メソッドのみを使用する。
    """

    def __init__(self, instance_url: str, api_token: str) -> None:
        self._instance_url = instance_url.rstrip("/")
        self._token = api_token
        self._session: aiohttp.ClientSession | None = None
        self._bot_user_id: str = ""

    async def initialize(self) -> None:
        """クライアントを初期化し、bot 自身の user_id を取得する。"""
        self._session = aiohttp.ClientSession()

        # bot 自身のユーザー情報を取得して接続確認
        me = await self.get_me()
        self._bot_user_id = me["id"]
        logger.info(
            "Misskey クライアントを初期化しました（user_id: %s, username: %s）",
            self._bot_user_id,
            me.get("username", ""),
        )

    @property
    def bot_user_id(self) -> str:
        """起動時に取得した bot 自身の user_id。"""
        return self._bot_user_id

    async def get_user_by_username(self, username: str) -> dict | None:
        """ユーザー名からユーザー情報を取得する。見つからない場合は None。"""
        try:
            # username に @host が含まれる場合は host パラメータも処理する（必要に応じて適宜修正可能だが暫定対応）
            if "@" in username:
                name, host = username.split("@", 1)
                return await self._request(
                    "/api/users/show", {"username": name, "host": host}
                )
            else:
                return await self._request("/api/users/show", {"username": username})
        except RuntimeError as e:
            if "NOT_FOUND" in str(e) or "404" in str(e) or "400" in str(e):
                return None
            raise

    @property
    def token(self) -> str:
        """API トークン（WebSocket 接続用）。"""
        return self._token

    @property
    def instance_url(self) -> str:
        """インスタンス URL。"""
        return self._instance_url

    async def _request(self, endpoint: str, params: dict | None = None) -> Any:
        """Misskey API にリクエストを送信する。

        Args:
            endpoint: /api/ から始まる API エンドポイントパス
            params: リクエストボディ（認証トークンは自動付与）

        Returns:
            API レスポンス（dict / list / None）

        Raises:
            RuntimeError: API エラー時
        """
        assert self._session is not None, "クライアントが初期化されていません"

        body = {"i": self._token}
        if params:
            body.update(params)

        url = f"{self._instance_url}{endpoint}"
        logger.debug("API リクエスト: %s", endpoint)

        async with self._session.post(url, json=body) as resp:
            if resp.status == 204:
                # コンテンツなし（削除系など）
                return None

            response_body = await resp.json(content_type=None)

            if resp.status != 200:
                error_info = response_body if isinstance(response_body, dict) else {}
                error_code = error_info.get("error", {}).get("code", "UNKNOWN")
                error_msg = error_info.get("error", {}).get(
                    "message", str(response_body)
                )
                raise RuntimeError(
                    f"Misskey API エラー [{resp.status}] {error_code}: {error_msg}"
                )

            logger.debug("API レスポンス: %s -> status=%s", endpoint, resp.status)
            return response_body

    async def create_note(
        self,
        text: str,
        visibility: str = "home",
        reply_id: str | None = None,
        file_ids: list[str] | None = None,
        poll: dict | None = None,
    ) -> str:
        """ノートを投稿し、note_id を返す。"""
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

        result = await self._request("/api/notes/create", params)
        note_id = result["createdNote"]["id"]
        logger.info("ノートを投稿しました（note_id=%s）", note_id)
        return note_id

    async def delete_note(self, note_id: str) -> None:
        """ノートを削除する。404 は成功扱い。"""
        try:
            await self._request("/api/notes/delete", {"noteId": note_id})
            logger.info("ノートを削除しました（note_id=%s）", note_id)
        except RuntimeError as e:
            if "NO_SUCH_NOTE" in str(e) or "404" in str(e):
                logger.info("ノートは既に削除されています（note_id=%s）", note_id)
            else:
                raise

    async def create_reaction(self, note_id: str, reaction: str) -> None:
        """リアクションを送信する。"""
        await self._request(
            "/api/notes/reactions/create",
            {"noteId": note_id, "reaction": reaction},
        )
        logger.debug(
            "リアクションを送信しました（note_id=%s, reaction=%s）",
            note_id,
            reaction,
        )

    async def upload_file(self, file_path: str) -> str:
        """ファイルをドライブにアップロードし、file_id を返す。"""
        assert self._session is not None

        url = f"{self._instance_url}/api/drive/files/create"
        with open(file_path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field("i", self._token)
            data.add_field(
                "file",
                f,
                filename=file_path.split("/")[-1],
            )

            async with self._session.post(url, data=data) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise RuntimeError(
                        f"ファイルアップロードに失敗しました: {resp.status} {error_text[:200]}"
                    )
                result = await resp.json()
                file_id = result["id"]
                logger.info("ファイルをアップロードしました（file_id=%s）", file_id)
                return file_id

    async def delete_file(self, file_id: str) -> None:
        """ドライブファイルを削除する。404 は成功扱い。"""
        try:
            await self._request("/api/drive/files/delete", {"fileId": file_id})
            logger.info("ドライブファイルを削除しました（file_id=%s）", file_id)
        except RuntimeError as e:
            if "NO_SUCH_FILE" in str(e) or "404" in str(e):
                logger.info("ファイルは既に削除されています（file_id=%s）", file_id)
            else:
                raise

    async def get_me(self) -> dict:
        """bot 自身のユーザー情報を取得する。"""
        result = await self._request("/api/i")
        return result

    async def get_timeline(self, source: str, limit: int = 20) -> list[dict]:
        """指定ソースの TL からノートを取得する。ページネーション対応。"""
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

            notes = await self._request(endpoint, params)

            if not notes:
                break

            all_notes.extend(notes)
            remaining -= len(notes)
            until_id = notes[-1]["id"]

        return all_notes[:limit]

    async def follow_user(self, user_id: str) -> None:
        """ユーザーをフォローする。"""
        await self._request("/api/following/create", {"userId": user_id})
        logger.info("ユーザーをフォローしました（user_id=%s）", user_id)

    async def unfollow_user(self, user_id: str) -> None:
        """ユーザーのフォローを解除する。"""
        await self._request("/api/following/delete", {"userId": user_id})
        logger.info("ユーザーのフォローを解除しました（user_id=%s）", user_id)

    async def get_followers(self, limit: int = 100) -> list[dict]:
        """フォロワー一覧を取得する。ページネーション対応。"""
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

            followers = await self._request("/api/users/followers", params)

            if not followers:
                break

            all_followers.extend(followers)
            remaining -= len(followers)
            until_id = followers[-1].get("id", "")

        return all_followers[:limit]

    async def get_following(self, limit: int = 100) -> list[dict]:
        """フォロー一覧を取得する。ページネーション対応。"""
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

            following = await self._request("/api/users/following", params)

            if not following:
                break

            all_following.extend(following)
            remaining -= len(following)
            until_id = following[-1].get("id", "")

        return all_following[:limit]

    async def close(self) -> None:
        """クライアントを終了する。"""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("Misskey クライアントを終了しました")
