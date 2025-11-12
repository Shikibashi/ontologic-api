"""Central error handling decorator for HTTP endpoints."""

import asyncio
import random
from functools import wraps
from typing import Callable, Any, TypeVar, ParamSpec, Awaitable
from fastapi import HTTPException
from app.core.logger import log
from app.core.exceptions import (
    LLMError, LLMTimeoutError, LLMResponseError, LLMUnavailableError,
    ValidationError, DatabaseError
)

P = ParamSpec("P")
R = TypeVar("R")

def http_error_guard(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """
    Centralized error handling decorator for HTTP endpoints.

    Converts application exceptions to appropriate HTTP responses.
    """
    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await func(*args, **kwargs)
        except ValidationError as e:
            log.warning(f"Validation error in {func.__name__}: {e}")
            raise HTTPException(status_code=422, detail=str(e))
        except LLMTimeoutError as e:
            log.error(f"LLM timeout in {func.__name__}: {e}")
            raise HTTPException(status_code=504, detail="Request timeout")
        except LLMUnavailableError as e:
            log.error(f"LLM unavailable in {func.__name__}: {e}")
            raise HTTPException(status_code=503, detail="Service temporarily unavailable")
        except (LLMError, LLMResponseError) as e:
            log.error(f"LLM error in {func.__name__}: {e}")
            raise HTTPException(status_code=500, detail="Internal processing error")
        except DatabaseError as e:
            log.error(f"Database error in {func.__name__}: {e}")
            raise HTTPException(status_code=500, detail="Database error")
        except HTTPException:
            # Re-raise HTTP exceptions as-is
            raise
        except Exception as e:
            log.error(f"Unexpected error in {func.__name__}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")
    
    return wrapper


def with_timeout(
    timeout_seconds: int,
    operation_name: str = "operation"
):
    """Decorator to add timeout to async operations with standardized error."""
    if timeout_seconds <= 0:
        raise ValueError(f"timeout_seconds must be positive, got {timeout_seconds}")

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                log.warning(
                    f"{operation_name} timed out after {timeout_seconds}s: {func.__name__}"
                )
                raise LLMTimeoutError(
                    f"{operation_name} exceeded {timeout_seconds}s timeout"
                )
        return wrapper
    return decorator


def with_retry(
    max_retries: int = 3,
    backoff_base: float = 1.0,
    jitter: bool = True,
    retryable_exceptions: tuple = (ConnectionError, TimeoutError)
):
    """Decorator to add retry logic with exponential backoff."""
    if not isinstance(max_retries, int) or max_retries <= 0:
        raise ValueError(f"max_retries must be > 0, got {max_retries}")
    if not isinstance(backoff_base, (int, float)) or backoff_base <= 0:
        raise ValueError(f"backoff_base must be > 0, got {backoff_base}")

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = backoff_base * (2 ** attempt)
                        if jitter:
                            delay *= (0.5 + random.random())
                        log.warning(
                            f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                            f"after {delay:.2f}s: {e}"
                        )
                        await asyncio.sleep(delay)
                    else:
                        log.error(
                            f"All {max_retries} retries exhausted for {func.__name__}: {e}"
                        )
            raise last_exception
        return wrapper
    return decorator
