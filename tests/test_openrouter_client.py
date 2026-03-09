import pytest
import aiohttp
from unittest.mock import AsyncMock, MagicMock
from bot.core.openrouter_client import OpenRouterClient


@pytest.fixture
def session_mock():
    session = MagicMock(spec=aiohttp.ClientSession)
    return session


@pytest.mark.asyncio
async def test_openrouter_generate_success(session_mock):
    # モックのレスポンスを設定
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(
        return_value={"choices": [{"message": {"content": "Generated text"}}]}
    )

    # post メソッドがモックレスポンスを返すように設定
    session_mock.post.return_value.__aenter__.return_value = mock_response

    client = OpenRouterClient(api_key="test_key", session=session_mock)
    result = await client.generate(user_prompt="Hello", system_prompt="System")

    assert result == "Generated text"
    session_mock.post.assert_called_once()

    # ヘッダーに API キーが含まれているか確認
    kwargs = session_mock.post.call_args[1]
    assert kwargs["headers"]["Authorization"] == "Bearer test_key"
    assert kwargs["json"]["messages"][1]["content"] == "Hello"


@pytest.mark.asyncio
async def test_openrouter_generate_no_api_key(session_mock):
    client = OpenRouterClient(api_key="", session=session_mock)
    with pytest.raises(ValueError, match="OpenRouter API キーが設定されていません"):
        await client.generate(user_prompt="Hello", system_prompt="System")
