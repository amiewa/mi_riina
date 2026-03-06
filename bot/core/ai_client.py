"""AI クライアント基底クラス

各 Manager は AIClientBase のみを受け取り、
Gemini か Ollama かを意識しない。
"""

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class AIClientBase(ABC):
    """AI クライアントの抽象基底クラス"""

    @abstractmethod
    async def generate(
        self,
        user_prompt: str,
        system_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 1.0,
    ) -> str:
        """テキストを生成する。

        Args:
            user_prompt: ユーザーからの入力テキスト
            system_prompt: システムプロンプト（キャラクター設定等）
            max_tokens: 最大出力トークン数
            temperature: 生成の温度パラメータ

        Returns:
            生成されたテキスト

        Raises:
            asyncio.TimeoutError: タイムアウト時
            Exception: API エラー時
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """リソースを解放する。"""
        ...
