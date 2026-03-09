"""共通再試行ユーティリティ

Misskey API / AI API の呼び出し失敗時の再試行ルールを統一する。
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ========== 例外クラス ==========


class MisskeyAPIError(Exception):
    """Misskey API のエラーレスポンス"""

    def __init__(self, status: int, code: str | None, message: str) -> None:
        self.status = status
        self.code = code
        super().__init__(f"Misskey API {status}: {code} - {message}")


class RetryableError(MisskeyAPIError):
    """再試行対象のエラー（429 / 5xx）"""

    pass


class NonRetryableError(MisskeyAPIError):
    """再試行しないエラー（400 / 401 / 403）"""

    pass


# ========== 再試行ユーティリティ ==========


async def retry_async(
    func: Callable[..., Awaitable[T]],
    retries: int = 1,
    base_delay: float = 5.0,
    max_delay: float = 60.0,
    retry_on: tuple[type[Exception], ...] = (RetryableError,),
) -> T:
    """指数バックオフ付き再試行。

    Args:
        func: 再試行対象の非同期関数（引数なしの呼び出し可能オブジェクト）
        retries: 最大再試行回数
        base_delay: 初回再試行までの待機時間（秒）
        max_delay: 最大待機時間（秒）
        retry_on: 再試行対象の例外タプル

    Returns:
        func の戻り値

    Raises:
        最後の試行で発生した例外
    """
    last_exception: Exception | None = None

    for attempt in range(retries + 1):
        try:
            return await func()
        except retry_on as e:
            last_exception = e
            if attempt < retries:
                delay = min(base_delay * (2**attempt), max_delay)
                logger.warning(
                    "再試行 %d/%d（%s, %.1f秒後にリトライ）",
                    attempt + 1,
                    retries,
                    str(e),
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "再試行回数の上限に達しました（%d回）: %s",
                    retries,
                    str(e),
                )
        except Exception:
            # retry_on に含まれない例外はそのまま発生させる
            raise

    assert last_exception is not None
    raise last_exception


def classify_http_error(status: int, code: str | None, message: str) -> MisskeyAPIError:
    """HTTP ステータスコードからエラーを分類する。

    Args:
        status: HTTP ステータスコード
        code: Misskey エラーコード（あれば）
        message: エラーメッセージ

    Returns:
        RetryableError または NonRetryableError
    """
    if status in (429, 500, 502, 503):
        return RetryableError(status, code, message)
    elif status in (400, 401, 403):
        return NonRetryableError(status, code, message)
    else:
        return MisskeyAPIError(status, code, message)
