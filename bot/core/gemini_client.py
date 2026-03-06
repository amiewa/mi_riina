"""Gemini AI クライアント

google-genai ライブラリを使用した Gemini API の実装。
"""

import asyncio
import logging

from google import genai
from google.genai import types

from bot.core.ai_client import AIClientBase

logger = logging.getLogger(__name__)


class GeminiClient(AIClientBase):
    """Gemini API クライアント"""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        max_output_tokens: int = 1024,
        temperature: float = 1.0,
        timeout_seconds: int = 30,
        input_max_chars: int = 800,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._default_max_tokens = max_output_tokens
        self._default_temperature = temperature
        self._timeout = timeout_seconds
        self._input_max_chars = input_max_chars

        logger.info("Gemini クライアントを初期化しました（モデル: %s）", model)

    async def generate(
        self,
        user_prompt: str,
        system_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 1.0,
    ) -> str:
        """Gemini API でテキストを生成する。"""
        # 入力テキストの切り捨て
        if len(user_prompt) > self._input_max_chars:
            user_prompt = user_prompt[: self._input_max_chars]
            logger.debug(
                "入力テキストを %d 文字に切り捨てました", self._input_max_chars
            )

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens or self._default_max_tokens,
            temperature=temperature or self._default_temperature,
        )

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.models.generate_content,
                    model=self._model,
                    contents=user_prompt,
                    config=config,
                ),
                timeout=self._timeout,
            )

            if response.text:
                logger.debug(
                    "Gemini 応答を取得しました（%d 文字）",
                    len(response.text),
                )
                return response.text
            else:
                logger.warning("Gemini から空の応答が返されました")
                raise ValueError("Gemini から空の応答が返されました")

        except asyncio.TimeoutError:
            logger.error(
                "Gemini API がタイムアウトしました（%d秒）", self._timeout
            )
            raise
        except Exception as e:
            logger.error("Gemini API エラー: %s", str(e))
            raise

    async def close(self) -> None:
        """リソースを解放する（Gemini は特にクリーンアップ不要）。"""
        logger.info("Gemini クライアントを終了しました")
