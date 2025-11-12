"""Timeout calculation helpers for retry operations."""


def calculate_per_attempt_timeout(
    total_timeout: int,
    max_retries: int,
    min_per_attempt: int = 1
) -> tuple[int, int]:
    """
    Calculate per-attempt timeout from total timeout and retry count.

    This function divides a total timeout budget across multiple retry attempts,
    ensuring each attempt gets an equal share. The per-attempt timeout should be
    passed to asyncio.wait_for() or similar timeout mechanisms.

    Args:
        total_timeout: Total timeout in seconds across all attempts (e.g., 120s)
        max_retries: Maximum number of retry attempts AFTER initial attempt
                     (e.g., max_retries=2 means 3 total attempts)
        min_per_attempt: Minimum timeout per attempt in seconds (default: 1)

    Returns:
        Tuple of (max_attempts, per_attempt_timeout):
        - max_attempts: Total number of attempts including initial (max_retries + 1)
        - per_attempt_timeout: Timeout in seconds for EACH individual attempt,
                               calculated as total_timeout // max_attempts

    Example:
        >>> calculate_per_attempt_timeout(120, max_retries=2)
        (3, 40)  # 120s / 3 attempts = 40s per attempt
        >>> calculate_per_attempt_timeout(2, max_retries=5)
        (2, 1)  # 2s / 6 would be 0s -> clamped to min and attempts reduced

    Note:
        Uses floor division, so some timeout budget may be lost due to rounding.
        Example: 100s ÷ 3 attempts = 33s each = 99s total (1s lost)

    Raises:
        ValueError: If max_retries is negative or total_timeout < min_per_attempt
    """
    if max_retries < 0:
        raise ValueError(f"max_retries must be non-negative, got {max_retries}")

    if total_timeout < min_per_attempt:
        raise ValueError(
            f"total_timeout ({total_timeout}s) must be at least {min_per_attempt}s "
            f"(minimum per-attempt timeout)"
        )

    max_attempts = max_retries + 1  # Total attempts = initial + retries
    per_attempt_timeout = total_timeout // max_attempts

    # Ensure each attempt gets at least min_per_attempt seconds
    if per_attempt_timeout < min_per_attempt:
        # Reduce max_attempts to ensure minimum timeout per attempt
        max_attempts = total_timeout // min_per_attempt
        per_attempt_timeout = min_per_attempt
        if max_attempts == 0:
            max_attempts = 1  # At least one attempt

    return max_attempts, per_attempt_timeout
