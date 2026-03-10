"""OpenRouter AI クライアント

OpenAI 互換 API を介した OpenRouter の実装。
aiohttp を用いて API に直接リクエストを送信する。
"""

import asyncio
import logging

import aiohttp

from bot.core.ai_client import AIClientBase

logger = logging.getLogger(__name__)


class OpenRouterClient(AIClientBase):
    """OpenRouter クライアント"""

    def __init__(
        self,
        api_key: str,
        session: aiohttp.ClientSession,
        model: str = "google/gemma-3-27b-it",
        max_tokens: int = 1024,
        temperature: float = 1.0,
        timeout_seconds: int = 30,
        input_max_chars: int = 2500,
    ) -> None:
        self._api_key = api_key
        self._session = session
        self._model = model
        self._default_max_tokens = max_tokens
        self._default_temperature = temperature
        self._timeout = timeout_seconds
        self._input_max_chars = input_max_chars
        self._url = "https://openrouter.ai/api/v1/chat/completions"

        logger.info("OpenRouter クライアントを初期化しました（モデル: %s）", model)

    async def generate(
        self,
        user_prompt: str,
        system_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 1.0,
    ) -> str:
        """OpenRouter API でテキストを生成する。"""
        if not self._api_key:
            raise ValueError("OpenRouter API キーが設定されていません")

        # 入力テキストの切り捨て
        if len(user_prompt) > self._input_max_chars:
            user_prompt = user_prompt[: self._input_max_chars]
            logger.debug(
                "入力テキストを %d 文字に切り捨てました", self._input_max_chars
            )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/amiewa/mi_riina",
            "X-Title": "mi_riina",
        }

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens or self._default_max_tokens,
            "temperature": temperature or self._default_temperature,
            "stream": False,
        }

        try:
            async with self._session.post(
                self._url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    choices = data.get("choices", [])
                    if choices and "message" in choices[0]:
                        content = choices[0]["message"].get("content") or ""
                        logger.debug(
                            "OpenRouter 応答を取得しました（%d 文字）", len(content)
                        )
                        return content
                    else:
                        logger.warning(
                            "OpenRouter から空の応答または不正なフォーマットが返されました"
                        )
                        raise ValueError("OpenRouter からの応答が不正です")
                elif response.status == 429:
                    logger.warning(
                        "OpenRouter API のレートリミットに達しました (HTTP 429)"
                    )
                    # aiohttp 経由で発生する HTTP エラーの形式として扱う
                    response.raise_for_status()
                else:
                    text = await response.text()
                    logger.error(
                        "OpenRouter API エラー (ステータス %d): %s",
                        response.status,
                        text,
                    )
                    response.raise_for_status()

        except asyncio.TimeoutError:
            logger.error("OpenRouter API がタイムアウトしました（%d秒）", self._timeout)
            raise
        except Exception as e:
            logger.error("OpenRouter リクエストでエラーが発生しました: %s", str(e))
            raise

    async def close(self) -> None:
        """リソースを解放する。

        ClientSession は main.py で管理・クローズされるため、ここでは何もしない。
        """
        logger.info("OpenRouter クライアントを終了しました")
