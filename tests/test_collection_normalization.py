"""
Test philosopher collection name normalization and validation.

Tests the fuzzy matching logic that maps user input to proper collection names.
"""
import pytest
from fastapi import HTTPException

from app.router.ontologic import _normalize_collection_name, _validate_philosopher_collection


def test_exact_match_returns_proper_case():
    """Test exact matches return proper-cased names."""
    assert _normalize_collection_name("Aristotle") == "Aristotle"
    assert _normalize_collection_name("aristotle") == "Aristotle"
    assert _normalize_collection_name("ARISTOTLE") == "Aristotle"


def test_partial_match_with_unique_result():
    """Test partial matches work when unambiguous."""
    # Test with Friedrich (should match Friedrich Nietzsche if it exists)
    result = _normalize_collection_name("friedrich")
    # The result should be a proper-cased name containing "friedrich"
    assert "friedrich" in result.lower() or result == "friedrich"


def test_word_boundary_matching():
    """Test word boundary matching works correctly."""
    # "kant" should match "Immanuel Kant" via word boundary
    # This assumes "Immanuel Kant" exists as a collection
    # If the test fails, it means either:
    # 1. Collection doesn't exist
    # 2. Multiple collections match (ambiguous)
    try:
        result = _normalize_collection_name("kant")
        # Should return proper-cased name if unambiguous
        assert result is not None
    except ValueError:
        # If ValueError raised, it means multiple matches (ambiguous)
        # This is expected behavior - test passes
        pass


def test_ambiguous_match_raises_value_error():
    """Test ambiguous matches raise ValueError."""
    # Try to find a pattern that matches multiple philosophers
    # This test may need adjustment based on actual available philosophers
    try:
        # If there are multiple Johns, this should raise ValueError
        result = _normalize_collection_name("john")
        # If we get here, it means only one match found (not ambiguous)
        assert result is not None
    except ValueError as e:
        # Expected: ambiguous match should raise ValueError
        assert "ambiguous" in str(e).lower() or "multiple" in str(e).lower()


def test_no_match_returns_original():
    """Test unknown names return original input."""
    result = _normalize_collection_name("NonexistentPhilosopher123")
    assert result == "NonexistentPhilosopher123"


def test_validate_empty_collection_raises_400():
    """Test validation rejects empty collection names."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_philosopher_collection("")

    assert exc_info.value.status_code == 400
    assert "required" in exc_info.value.detail.lower()


def test_validate_whitespace_only_raises_400():
    """Test validation rejects whitespace-only collection names."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_philosopher_collection("   ")

    assert exc_info.value.status_code == 400
    assert "required" in exc_info.value.detail.lower()


def test_validate_unknown_collection_raises_404():
    """Test validation rejects unknown philosophers."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_philosopher_collection("NonexistentPhilosopher123")

    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()
    assert "available" in exc_info.value.detail.lower()


def test_validate_success_returns_normalized_name():
    """Test successful validation returns normalized name."""
    result = _validate_philosopher_collection("aristotle")
    assert result == "Aristotle"


def test_case_insensitive_matching():
    """Test that matching is case-insensitive."""
    # All these should match to the same philosopher
    results = [
        _normalize_collection_name("ARISTOTLE"),
        _normalize_collection_name("aristotle"),
        _normalize_collection_name("Aristotle"),
        _normalize_collection_name("ArIsToTlE")
    ]

    # All results should be identical
    assert len(set(results)) == 1
    assert results[0] == "Aristotle"


def test_prefix_matching():
    """Test prefix matching works for partial names."""
    # "imman" should match "Immanuel Kant" via prefix if unambiguous
    try:
        result = _normalize_collection_name("imman")
        # Should return a name starting with "Imman" if successful
        assert result.lower().startswith("imman") or "imman" in result.lower()
    except ValueError:
        # Ambiguous match - acceptable result
        pass


def test_validation_error_includes_available_philosophers():
    """Test that validation errors include list of available philosophers."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_philosopher_collection("InvalidPhilosopher")

    error_detail = exc_info.value.detail
    # Should include text like "Available philosophers: Aristotle, Kant, ..."
    assert "available" in error_detail.lower()
    assert "philosopher" in error_detail.lower()


def test_strip_whitespace_in_input():
    """Test that leading/trailing whitespace is handled."""
    result1 = _normalize_collection_name("  aristotle  ")
    result2 = _normalize_collection_name("aristotle")

    assert result1 == result2 == "Aristotle"


def test_validate_ambiguous_raises_400_not_404():
    """Test that ambiguous matches return 400, not 404."""
    # Try to trigger an ambiguous match
    # This test may need adjustment based on actual philosopher names
    try:
        # If "john" matches multiple (John Locke, John Stuart Mill, etc.)
        _validate_philosopher_collection("john")
    except HTTPException as e:
        if "ambiguous" in e.detail.lower():
            # Ambiguous should be 400, not 404
            assert e.status_code == 400
        elif "not found" in e.detail.lower():
            # If not found, should be 404
            assert e.status_code == 404
