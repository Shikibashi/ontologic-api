"""Tests for timeout calculation helpers."""

import pytest
from app.core.timeout_helpers import calculate_per_attempt_timeout


class TestCalculatePerAttemptTimeout:
    """Test timeout calculation logic used across LLM operations."""

    def test_basic_calculation(self):
        """Verify correct division of timeout across attempts."""
        max_attempts, per_attempt = calculate_per_attempt_timeout(120, max_retries=2)
        assert max_attempts == 3  # 1 initial + 2 retries
        assert per_attempt == 40  # 120 // 3

    def test_zero_retries(self):
        """Single attempt gets full timeout."""
        max_attempts, per_attempt = calculate_per_attempt_timeout(60, max_retries=0)
        assert max_attempts == 1
        assert per_attempt == 60

    def test_integer_division_rounding(self):
        """Verify floor division behavior."""
        max_attempts, per_attempt = calculate_per_attempt_timeout(100, max_retries=2)
        assert per_attempt == 33  # 100 // 3 = 33 (not 33.33)
        assert max_attempts == 3

    def test_negative_retries_raises_error(self):
        """Negative retry count is invalid."""
        with pytest.raises(ValueError, match="max_retries must be non-negative"):
            calculate_per_attempt_timeout(120, max_retries=-1)

    def test_large_retry_count(self):
        """Many retries result in short per-attempt timeout."""
        max_attempts, per_attempt = calculate_per_attempt_timeout(100, max_retries=9)
        assert max_attempts == 10
        assert per_attempt == 10  # 100 // 10

    def test_timeout_less_than_retries_edge_case(self):
        """Edge case: timeout too small for retry count - clamps to minimum."""
        max_attempts, per_attempt = calculate_per_attempt_timeout(2, max_retries=5)
        assert per_attempt >= 1  # Never returns 0
        assert max_attempts == 2  # Reduced from 6 to fit minimum timeout
        assert per_attempt == 1  # Minimum timeout enforced

    def test_minimum_timeout_enforcement(self):
        """Timeout too small for retry count reduces attempts."""
        max_attempts, per_attempt = calculate_per_attempt_timeout(5, max_retries=10)
        assert per_attempt >= 1  # Never 0
        assert max_attempts == 5  # Reduced from 11 to fit minimum
        assert per_attempt == 1

    def test_exact_division(self):
        """Timeout divides evenly across attempts."""
        max_attempts, per_attempt = calculate_per_attempt_timeout(90, max_retries=2)
        assert max_attempts == 3
        assert per_attempt == 30
        assert max_attempts * per_attempt == 90  # No remainder

    def test_very_large_timeout(self):
        """Handle large timeout values."""
        max_attempts, per_attempt = calculate_per_attempt_timeout(3600, max_retries=3)
        assert max_attempts == 4
        assert per_attempt == 900  # 15 minutes per attempt

    def test_minimum_total_timeout(self):
        """Total timeout must be at least minimum per-attempt."""
        with pytest.raises(ValueError, match="total_timeout .* must be at least"):
            calculate_per_attempt_timeout(0, max_retries=2)

    def test_custom_minimum_per_attempt(self):
        """Can specify custom minimum timeout per attempt."""
        max_attempts, per_attempt = calculate_per_attempt_timeout(
            100, max_retries=30, min_per_attempt=5
        )
        assert per_attempt >= 5  # Respects custom minimum
        assert max_attempts == 20  # 100 // 5 = 20 attempts max

    def test_production_llm_query_scenario(self):
        """Test real-world LLM query scenario (120s, 2 retries)."""
        max_attempts, per_attempt = calculate_per_attempt_timeout(120, max_retries=2)
        assert max_attempts == 3
        assert per_attempt == 40
        # Verify total time: 3 attempts × 40s = 120s

    def test_production_vector_scenario(self):
        """Test real-world vector generation scenario (300s, 3 retries)."""
        max_attempts, per_attempt = calculate_per_attempt_timeout(300, max_retries=3)
        assert max_attempts == 4
        assert per_attempt == 75
        # Verify total time: 4 attempts × 75s = 300s
