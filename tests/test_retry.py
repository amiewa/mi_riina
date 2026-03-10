"""retry.py のテスト

retry_async / classify_http_error の動作を確認する。
"""


import pytest

from bot.utils.retry import (
    MisskeyAPIError,
    NonRetryableError,
    RetryableError,
    classify_http_error,
    retry_async,
)


# ========== retry_async のテスト ==========


@pytest.mark.asyncio
async def test_retry_success_first_attempt() -> None:
    """初回で成功した場合、1回で完了すること。"""
    call_count = 0

    async def func() -> str:
        nonlocal call_count
        call_count += 1
        return "ok"

    result = await retry_async(func)
    assert result == "ok"
    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_success_after_retries() -> None:
    """1回失敗後に成功する場合、再試行で成功すること。"""
    call_count = 0

    async def func() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise RetryableError(503, "SERVICE_UNAVAILABLE", "一時的なエラー")
        return "ok"

    result = await retry_async(func, retries=2, base_delay=0.01)
    assert result == "ok"
    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_non_retryable_not_retried() -> None:
    """NonRetryableError は再試行されないこと。"""
    call_count = 0

    async def func() -> None:
        nonlocal call_count
        call_count += 1
        raise NonRetryableError(400, "INVALID_PARAM", "不正なパラメータ")

    with pytest.raises(NonRetryableError):
        await retry_async(func, retries=3, retry_on=(RetryableError,))

    assert call_count == 1  # 再試行なしで即時中断


@pytest.mark.asyncio
async def test_retry_max_retries_exceeded() -> None:
    """最大再試行回数を超えた場合、最後の例外が発生すること。"""
    call_count = 0

    async def func() -> None:
        nonlocal call_count
        call_count += 1
        raise RetryableError(503, "SERVICE_UNAVAILABLE", "サービス停止中")

    with pytest.raises(RetryableError):
        await retry_async(func, retries=2, base_delay=0.01)

    assert call_count == 3  # 初回1回 + 再試行2回


# ========== classify_http_error のテスト ==========


def test_classify_429_is_retryable() -> None:
    """429 はリトライ可能エラーに分類されること。"""
    error = classify_http_error(429, "TOO_MANY_REQUESTS", "レート制限")
    assert isinstance(error, RetryableError)
    assert error.status == 429


def test_classify_400_is_non_retryable() -> None:
    """400 はリトライ不可エラーに分類されること。"""
    error = classify_http_error(400, "INVALID_PARAM", "不正なパラメータ")
    assert isinstance(error, NonRetryableError)
    assert error.status == 400


def test_classify_500_is_retryable() -> None:
    """500 はリトライ可能エラーに分類されること。"""
    error = classify_http_error(500, "INTERNAL_ERROR", "内部エラー")
    assert isinstance(error, RetryableError)
    assert error.status == 500


def test_classify_401_is_non_retryable() -> None:
    """401 はリトライ不可エラーに分類されること。"""
    error = classify_http_error(401, "CREDENTIALS_REQUIRED", "認証エラー")
    assert isinstance(error, NonRetryableError)
    assert error.status == 401


def test_classify_403_is_non_retryable() -> None:
    """403 はリトライ不可エラーに分類されること。"""
    error = classify_http_error(403, "FORBIDDEN", "権限エラー")
    assert isinstance(error, NonRetryableError)
    assert error.status == 403


def test_classify_502_is_retryable() -> None:
    """502 はリトライ可能エラーに分類されること。"""
    error = classify_http_error(502, "BAD_GATEWAY", "ゲートウェイエラー")
    assert isinstance(error, RetryableError)
    assert error.status == 502


def test_classify_503_is_retryable() -> None:
    """503 はリトライ可能エラーに分類されること。"""
    error = classify_http_error(503, "SERVICE_UNAVAILABLE", "サービス停止")
    assert isinstance(error, RetryableError)
    assert error.status == 503


def test_classify_404_is_base_error() -> None:
    """404 は基底 MisskeyAPIError に分類されること。"""
    error = classify_http_error(404, "NOT_FOUND", "見つかりません")
    assert type(error) is MisskeyAPIError
    assert error.status == 404


def test_misskey_api_error_attributes() -> None:
    """MisskeyAPIError の属性が正しく設定されること。"""
    error = MisskeyAPIError(418, "IM_A_TEAPOT", "ティーポット")
    assert error.status == 418
    assert error.code == "IM_A_TEAPOT"
    assert "418" in str(error)
