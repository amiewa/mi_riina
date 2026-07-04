"""AI クライアント max_tokens / temperature デフォルト反映テスト

各クライアントで generate() を引数なしで呼んだ場合に、コンストラクタで
渡した config 由来のデフォルト値（max_output_tokens / num_predict / temperature）が
実際の API リクエストに使われることを検証する。

`x or self._default_x` パターンは 1024 / 1.0 のような truthy な signature
デフォルトに退行しやすいため、`is None` 判定への回帰を防ぐのが目的。
"""

import aiohttp
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.gemini_client import GeminiClient
from bot.core.ollama_client import OllamaClient
from bot.core.openrouter_client import OpenRouterClient


# ========== GeminiClient ==========


@pytest.mark.asyncio
async def test_gemini_generate_uses_constructor_defaults() -> None:
    """引数なし呼び出しでコンストラクタの max_output_tokens/temperature が使われる"""
    mock_response = MagicMock()
    mock_response.text = "応答"

    with patch(
        "bot.core.gemini_client.asyncio.to_thread", new_callable=AsyncMock
    ) as mock_thread:
        mock_thread.return_value = mock_response

        client = GeminiClient(
            api_key="test_key", max_output_tokens=2048, temperature=0.4
        )
        await client.generate(user_prompt="質問", system_prompt="システム")

    _, kwargs = mock_thread.call_args
    config = kwargs["config"]
    assert config.max_output_tokens == 2048
    assert config.temperature == 0.4


@pytest.mark.asyncio
async def test_gemini_generate_explicit_zero_temperature() -> None:
    """temperature=0.0 明示指定時は 0.0 がそのまま使われる（or 退行防止）"""
    mock_response = MagicMock()
    mock_response.text = "応答"

    with patch(
        "bot.core.gemini_client.asyncio.to_thread", new_callable=AsyncMock
    ) as mock_thread:
        mock_thread.return_value = mock_response

        client = GeminiClient(api_key="test_key", temperature=0.9)
        await client.generate(
            user_prompt="質問", system_prompt="システム", temperature=0.0
        )

    _, kwargs = mock_thread.call_args
    assert kwargs["config"].temperature == 0.0


# ========== OllamaClient ==========


@pytest.fixture
def ollama_session() -> MagicMock:
    return MagicMock(spec=aiohttp.ClientSession)


@pytest.mark.asyncio
async def test_ollama_generate_uses_constructor_defaults(
    ollama_session: MagicMock,
) -> None:
    """引数なし呼び出しでコンストラクタの num_predict/temperature が使われる"""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"message": {"content": "応答"}})
    ollama_session.post.return_value.__aenter__.return_value = mock_resp

    client = OllamaClient(
        base_url="http://localhost:11434",
        session=ollama_session,
        temperature=0.3,
        num_predict=512,
    )
    await client.generate(user_prompt="質問", system_prompt="システム")

    options = ollama_session.post.call_args[1]["json"]["options"]
    assert options["num_predict"] == 512
    assert options["temperature"] == 0.3


@pytest.mark.asyncio
async def test_ollama_generate_explicit_zero_temperature(
    ollama_session: MagicMock,
) -> None:
    """temperature=0.0 明示指定時は 0.0 がそのまま使われる（or 退行防止）"""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"message": {"content": "応答"}})
    ollama_session.post.return_value.__aenter__.return_value = mock_resp

    client = OllamaClient(
        base_url="http://localhost:11434", session=ollama_session, temperature=0.8
    )
    await client.generate(user_prompt="質問", system_prompt="システム", temperature=0.0)

    options = ollama_session.post.call_args[1]["json"]["options"]
    assert options["temperature"] == 0.0


# ========== OpenRouterClient ==========


@pytest.fixture
def openrouter_session() -> MagicMock:
    return MagicMock(spec=aiohttp.ClientSession)


@pytest.mark.asyncio
async def test_openrouter_generate_uses_constructor_defaults(
    openrouter_session: MagicMock,
) -> None:
    """引数なし呼び出しでコンストラクタの max_tokens/temperature が使われる"""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={"choices": [{"message": {"content": "応答"}}]}
    )
    openrouter_session.post.return_value.__aenter__.return_value = mock_resp

    client = OpenRouterClient(
        api_key="test_key",
        session=openrouter_session,
        max_tokens=777,
        temperature=0.6,
    )
    await client.generate(user_prompt="質問", system_prompt="システム")

    payload = openrouter_session.post.call_args[1]["json"]
    assert payload["max_tokens"] == 777
    assert payload["temperature"] == 0.6


@pytest.mark.asyncio
async def test_openrouter_generate_explicit_zero_temperature(
    openrouter_session: MagicMock,
) -> None:
    """temperature=0.0 明示指定時は 0.0 がそのまま使われる（or 退行防止）"""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={"choices": [{"message": {"content": "応答"}}]}
    )
    openrouter_session.post.return_value.__aenter__.return_value = mock_resp

    client = OpenRouterClient(
        api_key="test_key", session=openrouter_session, temperature=1.0
    )
    await client.generate(user_prompt="質問", system_prompt="システム", temperature=0.0)

    payload = openrouter_session.post.call_args[1]["json"]
    assert payload["temperature"] == 0.0
