"""
Unit tests for safe regex operations with ReDoS protection.

Tests verify process-based timeout enforcement, input validation,
and proper handling of catastrophic backtracking patterns.
"""

import pytest
import re
import time
from app.workflow_services.review_workflow import safe_regex_search, safe_regex_finditer


class TestSafeRegexTimeout:
    """Test timeout protection for regex operations."""

    def test_safe_regex_search_normal_operation(self):
        """Verify normal regex search works."""
        result = safe_regex_search(r"\d+", "test 123 data")
        assert result is not None
        assert result.group() == "123"
        assert result.start() == 5
        assert result.end() == 8
        assert result.span() == (5, 8)

    def test_safe_regex_search_no_match(self):
        """Verify returns None when no match."""
        result = safe_regex_search(r"\d+", "no numbers here")
        assert result is None

    def test_safe_regex_search_redos_protection(self):
        """Verify timeout prevents ReDoS attacks with true process termination."""
        # Classic ReDoS pattern: catastrophic backtracking on failure
        # This pattern causes exponential backtracking when it FAILS to match
        redos_pattern = r"(a+)+b"
        # Vulnerable input: repeated 'a's WITHOUT the 'b' at the end
        # This forces the regex engine to try all combinations
        redos_input = "a" * 28 + "c"  # 28 a's followed by 'c' (not 'b')

        start_time = time.time()
        result = safe_regex_search(redos_pattern, redos_input, timeout=0.5)
        elapsed = time.time() - start_time

        # Should timeout quickly instead of hanging
        assert result is None
        assert elapsed < 1.5, f"Timeout protection failed, took {elapsed}s"

    def test_safe_regex_search_complex_redos_pattern(self):
        """Test another ReDoS pattern to verify process isolation."""
        # Another catastrophic backtracking case - fails to match
        redos_pattern = r"(a*)*b"
        redos_input = "a" * 28 + "c"  # No 'b', forces backtracking

        start_time = time.time()
        result = safe_regex_search(redos_pattern, redos_input, timeout=0.5)
        elapsed = time.time() - start_time

        assert result is None
        assert elapsed < 1.5, f"Process isolation failed, took {elapsed}s"

    def test_safe_regex_search_pattern_truncation(self):
        """Verify overly long patterns are truncated."""
        long_pattern = "a" * 1000  # Exceeds 500 char limit
        result = safe_regex_search(long_pattern, "test data")
        # Should not raise exception, just truncate and warn
        assert result is None  # Won't match since pattern was truncated

    def test_safe_regex_search_text_truncation(self):
        """Verify overly long text is truncated."""
        long_text = "a" * 100000  # Exceeds 50000 char limit
        result = safe_regex_search(r"b", long_text)
        # Should not raise exception, just truncate and warn
        assert result is None  # 'b' not in truncated text

    def test_safe_regex_search_text_found_after_truncation(self):
        """Verify matches work within truncated text."""
        long_text = "a" * 1000 + "test123" + "a" * 100000
        result = safe_regex_search(r"\d+", long_text)
        # Pattern should match within the first 50000 chars
        assert result is not None
        assert result.group() == "123"

    def test_safe_regex_finditer_multiple_matches(self):
        """Verify finditer returns all matches."""
        results = safe_regex_finditer(r"\d+", "123 test 456 data 789")
        assert len(results) == 3
        assert [m.group() for m in results] == ["123", "456", "789"]
        assert results[0].start() == 0
        assert results[0].end() == 3
        assert results[1].start() == 9
        assert results[1].end() == 12

    def test_safe_regex_finditer_no_matches(self):
        """Verify finditer returns empty list when no matches."""
        results = safe_regex_finditer(r"\d+", "no numbers here")
        assert results == []

    def test_safe_regex_finditer_timeout(self):
        """Verify finditer respects timeout with process termination."""
        redos_pattern = r"(a+)+b"
        redos_input = "a" * 28 + "c"  # Forces catastrophic backtracking

        start_time = time.time()
        results = safe_regex_finditer(redos_pattern, redos_input, timeout=0.5)
        elapsed = time.time() - start_time

        assert results == []
        assert elapsed < 1.5, f"Timeout protection failed, took {elapsed}s"

    def test_safe_regex_search_invalid_pattern(self):
        """Verify invalid regex patterns are handled gracefully."""
        # Invalid regex: unmatched parenthesis
        result = safe_regex_search(r"(invalid", "test data")
        assert result is None  # Should return None, not raise

    def test_safe_regex_search_with_flags(self):
        """Verify regex flags work correctly."""
        result = safe_regex_search(r"TEST", "test data", flags=re.IGNORECASE)
        assert result is not None
        assert result.group() == "test"

    def test_safe_regex_finditer_with_flags(self):
        """Verify flags work with finditer."""
        results = safe_regex_finditer(r"TEST", "test TEST Test", flags=re.IGNORECASE)
        assert len(results) == 3
        assert [m.group() for m in results] == ["test", "TEST", "Test"]


class TestTimeoutValidation:
    """Test timeout parameter validation."""

    def test_timeout_too_small(self):
        """Verify timeout below minimum is rejected."""
        with pytest.raises(ValueError, match="Timeout must be between"):
            safe_regex_search(r"test", "data", timeout=0.05)

    def test_timeout_zero(self):
        """Verify zero timeout is rejected."""
        with pytest.raises(ValueError, match="Timeout must be between"):
            safe_regex_search(r"test", "data", timeout=0.0)

    def test_timeout_negative(self):
        """Verify negative timeout is rejected."""
        with pytest.raises(ValueError, match="Timeout must be between"):
            safe_regex_search(r"test", "data", timeout=-1.0)

    def test_timeout_too_large(self):
        """Verify timeout above maximum is rejected."""
        with pytest.raises(ValueError, match="Timeout must be between"):
            safe_regex_search(r"test", "data", timeout=99999.0)

    def test_timeout_at_minimum(self):
        """Verify minimum timeout (0.1) is accepted."""
        result = safe_regex_search(r"\d+", "test 123", timeout=0.1)
        assert result is not None
        assert result.group() == "123"

    def test_timeout_at_maximum(self):
        """Verify maximum timeout (10.0) is accepted."""
        result = safe_regex_search(r"\d+", "test 123", timeout=10.0)
        assert result is not None
        assert result.group() == "123"

    def test_finditer_timeout_validation(self):
        """Verify finditer also validates timeout."""
        with pytest.raises(ValueError, match="Timeout must be between"):
            safe_regex_finditer(r"test", "data", timeout=-1.0)


class TestProcessIsolation:
    """Test that process isolation works correctly."""

    def test_process_pool_reuse(self):
        """Verify process pool is reused across multiple operations."""
        # Multiple operations should use the same pool
        for _ in range(5):
            result = safe_regex_search(r"\d+", "test 123", timeout=1.0)
            assert result is not None

    def test_timeout_does_not_block_subsequent_operations(self):
        """Verify that a timed-out operation doesn't block future operations."""
        # Trigger a timeout
        redos_pattern = r"(a+)+b"
        redos_input = "a" * 28 + "c"
        result1 = safe_regex_search(redos_pattern, redos_input, timeout=0.3)
        assert result1 is None

        # Subsequent operations should work normally
        result2 = safe_regex_search(r"\d+", "test 123", timeout=1.0)
        assert result2 is not None
        assert result2.group() == "123"

    def test_concurrent_timeout_handling(self):
        """Test multiple concurrent timeouts don't cause issues."""
        import concurrent.futures

        redos_pattern = r"(a+)+b"
        redos_input = "a" * 28 + "c"

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(safe_regex_search, redos_pattern, redos_input, 0.3)
                for _ in range(3)
            ]

            results = [f.result() for f in futures]

        # All should timeout and return None
        assert all(r is None for r in results)


class TestMatchProxyInterface:
    """Test that _MatchProxy behaves like re.Match."""

    def test_match_group_method(self):
        """Verify group() method works."""
        result = safe_regex_search(r"\d+", "test 123")
        assert result.group() == "123"
        assert result.group(0) == "123"

    def test_match_group_invalid_index(self):
        """Verify group() raises for invalid group index."""
        result = safe_regex_search(r"\d+", "test 123")
        with pytest.raises(IndexError, match="no such group"):
            result.group(1)

    def test_match_start_method(self):
        """Verify start() method works."""
        result = safe_regex_search(r"\d+", "test 123")
        assert result.start() == 5

    def test_match_end_method(self):
        """Verify end() method works."""
        result = safe_regex_search(r"\d+", "test 123")
        assert result.end() == 8

    def test_match_span_method(self):
        """Verify span() method works."""
        result = safe_regex_search(r"\d+", "test 123")
        assert result.span() == (5, 8)


class TestEdgeCases:
    """Test edge cases and corner scenarios."""

    def test_empty_pattern(self):
        """Test empty pattern."""
        result = safe_regex_search(r"", "test")
        # Empty pattern matches at start
        assert result is not None

    def test_empty_text(self):
        """Test empty text."""
        result = safe_regex_search(r"\d+", "")
        assert result is None

    def test_empty_pattern_and_text(self):
        """Test both empty."""
        result = safe_regex_search(r"", "")
        assert result is not None

    def test_special_characters_in_pattern(self):
        """Test special regex characters."""
        result = safe_regex_search(r"\d+\.\d+", "version 3.14 beta")
        assert result is not None
        assert result.group() == "3.14"

    def test_multiline_text(self):
        """Test multiline text with flags."""
        text = "line1\nline2 123\nline3"
        result = safe_regex_search(r"^line2", text, flags=re.MULTILINE)
        assert result is not None
        assert result.group() == "line2"

    def test_dotall_flag(self):
        """Test DOTALL flag."""
        text = "start\nmiddle\nend"
        result = safe_regex_search(r"start.*end", text, flags=re.DOTALL)
        assert result is not None

    def test_unicode_text(self):
        """Test Unicode text."""
        result = safe_regex_search(r"你好", "测试 你好 世界")
        assert result is not None
        assert result.group() == "你好"

    def test_very_long_match(self):
        """Test matching very long strings."""
        long_match = "a" * 10000
        result = safe_regex_search(r"a+", long_match)
        assert result is not None
        # Should match up to truncation limit
        assert len(result.group()) > 0


class TestRealWorldPatterns:
    """Test patterns commonly used in review_workflow.py."""

    def test_suggestion_section_pattern(self):
        """Test pattern from _generate_suggestions."""
        text = """
        ### 4. Specific Suggestions
        - Suggestion 1: Fix this
        - Suggestion 2: Improve that
        ### 5. Next Section
        """
        pattern = r"### 4\. Specific Suggestions(.*?)(?=###|$)"
        result = safe_regex_search(pattern, text, timeout=1.0, flags=re.DOTALL | re.IGNORECASE)
        assert result is not None
        assert "Suggestion 1" in result.group(0)

    def test_criterion_text_pattern(self):
        """Test pattern from _extract_criterion_text."""
        text = "### accuracy: The paper shows high accuracy in citations."
        pattern = r"### accuracy(.*?)(?=###|$)"
        result = safe_regex_search(pattern, text, timeout=1.0, flags=re.DOTALL | re.IGNORECASE)
        assert result is not None
        assert "citations" in result.group(0)

    def test_score_extraction_pattern(self):
        """Test pattern from _extract_criterion_score."""
        text = "**Accuracy**: 8/10"
        pattern = r"\*\*accuracy\*\*[:\s]*(\d+)(?:/(\d+))?"
        result = safe_regex_search(pattern, text.lower(), timeout=1.0, flags=re.IGNORECASE)
        assert result is not None

    def test_claim_verification_pattern(self):
        """Test pattern from _extract_verification_assessment."""
        text = "Claim 1 verified by source X. Evidence supports this."
        pattern = r"(Claim.*?(?:verified|supported|contradicted).*?)(?=\n\n|$)"
        results = safe_regex_finditer(pattern, text, timeout=1.0, flags=re.DOTALL | re.IGNORECASE)
        assert len(results) > 0
        assert "verified" in results[0].group(0)
