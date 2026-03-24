"""AI クライアント マルチターン対応テスト

各 AI クライアントの messages パラメータ対応と後方互換性を検証する。
"""

import pytest
import aiohttp
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from bot.core.gemini_client import GeminiClient
from bot.core.ollama_client import OllamaClient
from bot.core.openrouter_client import OpenRouterClient


# ========== GeminiClient テスト ==========


@pytest.mark.asyncio
async def test_gemini_messages_format() -> None:
    """role: assistant → role: model に変換される"""
    messages = [
        {"role": "user", "content": "こんにちは"},
        {"role": "assistant", "content": "やあ！"},
        {"role": "user", "content": "続きの質問"},
    ]

    mock_response = MagicMock()
    mock_response.text = "Gemini からの応答"

    with patch("bot.core.gemini_client.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = mock_response

        client = GeminiClient(api_key="test_key")
        result = await client.generate(
            user_prompt="",
            system_prompt="システム",
            messages=messages,
        )

    assert result == "Gemini からの応答"
    # to_thread に渡された contents 引数を確認
    call_args = mock_thread.call_args
    contents = call_args[1].get("contents") if call_args[1] else call_args[0][2] if len(call_args[0]) > 2 else None
    # contents が渡されているかは kwargs で確認
    _, kwargs = mock_thread.call_args
    assert "contents" in kwargs
    contents = kwargs["contents"]
    assert isinstance(contents, list)
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"   # assistant → model に変換
    assert contents[2]["role"] == "user"


@pytest.mark.asyncio
async def test_gemini_generate_without_messages() -> None:
    """messages=None で user_prompt が使われる（後方互換）"""
    mock_response = MagicMock()
    mock_response.text = "単発応答"

    with patch("bot.core.gemini_client.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
        mock_thread.return_value = mock_response

        client = GeminiClient(api_key="test_key")
        result = await client.generate(
            user_prompt="質問です",
            system_prompt="システム",
            messages=None,
        )

    assert result == "単発応答"
    _, kwargs = mock_thread.call_args
    # contents が str（user_prompt）で渡されること
    assert kwargs["contents"] == "質問です"


# ========== OllamaClient テスト ==========


@pytest.fixture
def ollama_session() -> MagicMock:
    session = MagicMock(spec=aiohttp.ClientSession)
    return session


@pytest.mark.asyncio
async def test_ollama_messages_passthrough(ollama_session: MagicMock) -> None:
    """system + messages が正しく結合される"""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"message": {"content": "Ollama応答"}})
    ollama_session.post.return_value.__aenter__.return_value = mock_resp

    messages = [
        {"role": "user", "content": "前の質問"},
        {"role": "assistant", "content": "前の回答"},
        {"role": "user", "content": "今の質問"},
    ]

    client = OllamaClient(base_url="http://localhost:11434", session=ollama_session)
    result = await client.generate(
        user_prompt="",
        system_prompt="システム",
        messages=messages,
    )

    assert result == "Ollama応答"
    call_kwargs = ollama_session.post.call_args[1]
    sent_messages = call_kwargs["json"]["messages"]
    assert sent_messages[0] == {"role": "system", "content": "システム"}
    assert sent_messages[1] == {"role": "user", "content": "前の質問"}
    assert sent_messages[2] == {"role": "assistant", "content": "前の回答"}
    assert sent_messages[3] == {"role": "user", "content": "今の質問"}


@pytest.mark.asyncio
async def test_ollama_generate_without_messages(ollama_session: MagicMock) -> None:
    """messages=None で user_prompt が使われる（後方互換）"""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"message": {"content": "単発応答"}})
    ollama_session.post.return_value.__aenter__.return_value = mock_resp

    client = OllamaClient(base_url="http://localhost:11434", session=ollama_session)
    result = await client.generate(
        user_prompt="単発の質問",
        system_prompt="システム",
        messages=None,
    )

    assert result == "単発応答"
    call_kwargs = ollama_session.post.call_args[1]
    sent_messages = call_kwargs["json"]["messages"]
    assert len(sent_messages) == 2
    assert sent_messages[0] == {"role": "system", "content": "システム"}
    assert sent_messages[1] == {"role": "user", "content": "単発の質問"}


# ========== OpenRouterClient テスト ==========


@pytest.fixture
def openrouter_session() -> MagicMock:
    session = MagicMock(spec=aiohttp.ClientSession)
    return session


@pytest.mark.asyncio
async def test_openrouter_messages_passthrough(openrouter_session: MagicMock) -> None:
    """system + messages が正しく結合される"""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={"choices": [{"message": {"content": "OR応答"}}]}
    )
    openrouter_session.post.return_value.__aenter__.return_value = mock_resp

    messages = [
        {"role": "user", "content": "前の質問"},
        {"role": "assistant", "content": "前の回答"},
        {"role": "user", "content": "今の質問"},
    ]

    client = OpenRouterClient(api_key="test_key", session=openrouter_session)
    result = await client.generate(
        user_prompt="",
        system_prompt="システム",
        messages=messages,
    )

    assert result == "OR応答"
    call_kwargs = openrouter_session.post.call_args[1]
    sent_messages = call_kwargs["json"]["messages"]
    assert sent_messages[0] == {"role": "system", "content": "システム"}
    assert sent_messages[1] == {"role": "user", "content": "前の質問"}
    assert sent_messages[2] == {"role": "assistant", "content": "前の回答"}
    assert sent_messages[3] == {"role": "user", "content": "今の質問"}


@pytest.mark.asyncio
async def test_openrouter_generate_without_messages(openrouter_session: MagicMock) -> None:
    """messages=None で user_prompt が使われる（後方互換）"""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={"choices": [{"message": {"content": "単発OR応答"}}]}
    )
    openrouter_session.post.return_value.__aenter__.return_value = mock_resp

    client = OpenRouterClient(api_key="test_key", session=openrouter_session)
    result = await client.generate(
        user_prompt="単発の質問",
        system_prompt="システム",
        messages=None,
    )

    assert result == "単発OR応答"
    call_kwargs = openrouter_session.post.call_args[1]
    sent_messages = call_kwargs["json"]["messages"]
    assert len(sent_messages) == 2
    assert sent_messages[0] == {"role": "system", "content": "システム"}
    assert sent_messages[1] == {"role": "user", "content": "単発の質問"}
