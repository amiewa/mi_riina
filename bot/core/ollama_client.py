"""Ollama AI クライアント

aiohttp で Ollama API を直接叩く実装。
外部URL / 別マシンからの呼び出しを前提とする。
"""

import asyncio
import logging

import aiohttp

from bot.core.ai_client import AIClientBase

logger = logging.getLogger(__name__)


class OllamaClient(AIClientBase):
    """Ollama API クライアント"""

    def __init__(
        self,
        base_url: str,
        model: str = "llama3",
        temperature: float = 0.8,
        num_predict: int = 300,
        timeout_seconds: int = 30,
        input_max_chars: int = 800,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._default_temperature = temperature
        self._default_num_predict = num_predict
        self._timeout = timeout_seconds
        self._input_max_chars = input_max_chars
        self._session = session

        logger.info(
            "Ollama クライアントを初期化しました（モデル: %s, URL: %s）",
            model, self._base_url,
        )

    async def generate(
        self,
        user_prompt: str,
        system_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 1.0,
    ) -> str:
        """Ollama API でテキストを生成する（non-streaming）。"""
        if self._session is None:
            raise RuntimeError("aiohttp セッションが設定されていません")

        # 入力テキストの切り捨て
        if len(user_prompt) > self._input_max_chars:
            user_prompt = user_prompt[: self._input_max_chars]
            logger.debug(
                "入力テキストを %d 文字に切り捨てました", self._input_max_chars
            )

        payload = {
            "model": self._model,
            "prompt": user_prompt,
            "system": system_prompt,
            "stream": False,
            "options": {
                "temperature": temperature or self._default_temperature,
                "num_predict": max_tokens or self._default_num_predict,
            },
        }

        url = f"{self._base_url}/api/generate"

        try:
            async with asyncio.timeout(self._timeout):
                async with self._session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(
                            "Ollama API エラー: status=%d, body=%s",
                            resp.status, error_text[:200],
                        )
                        raise RuntimeError(
                            f"Ollama API エラー: {resp.status}"
                        )

                    data = await resp.json()
                    response_text = data.get("response", "")

                    if not response_text:
                        logger.warning("Ollama から空の応答が返されました")
                        raise ValueError("Ollama から空の応答が返されました")

                    logger.debug(
                        "Ollama 応答を取得しました（%d 文字）",
                        len(response_text),
                    )
                    return response_text

        except asyncio.TimeoutError:
            logger.error(
                "Ollama API がタイムアウトしました（%d秒）", self._timeout
            )
            raise
        except Exception as e:
            logger.error("Ollama API エラー: %s", str(e))
            raise

    async def close(self) -> None:
        """リソースを解放する（セッションの管理は外部で行う）。"""
        logger.info("Ollama クライアントを終了しました")
