"""Tests for RedisCacheService cache key generation and consistency."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.services.cache_service import RedisCacheService
from pydantic import BaseModel


class MockPydanticV2Model(BaseModel):
    """Mock Pydantic v2 model for testing."""
    author: str
    tags: list[str]


class MockPydanticV1Model:
    """Mock Pydantic v1-style model for testing."""

    def __init__(self, author: str, tags: list[str]):
        self.author = author
        self.tags = tags

    def dict(self):
        """Pydantic v1 dict() method."""
        return {"author": self.author, "tags": self.tags}


@pytest.fixture
def cache_service():
    """Create a RedisCacheService instance with mocked Redis."""
    with patch('app.services.cache_service.redis.Redis'):
        service = RedisCacheService()
        # Mock Redis availability for key generation tests
        service._redis_available = True
        service._key_prefix = 'test'
        return service


class TestCacheKeyConsistency:
    """Test cache key generation consistency for various input types."""

    def test_cache_key_consistency_with_dict_order(self, cache_service):
        """Verify cache keys are deterministic regardless of dict key order."""
        # Same dictionary content, different key order - values are identical
        filter1 = {"author": "Aristotle", "tags": ["ethics", "virtue"]}
        filter2 = {"tags": ["ethics", "virtue"], "author": "Aristotle"}  # Same list order

        key1 = cache_service._make_cache_key('query', 'text', filter1)
        key2 = cache_service._make_cache_key('query', 'text', filter2)

        # Keys should be identical because dicts are sorted by key
        assert key1 == key2, "Cache keys should be identical regardless of dict key order"

    def test_cache_key_respects_list_order_in_dict_values(self, cache_service):
        """Verify list order within dict values is preserved (order matters for lists)."""
        filter1 = {"author": "Aristotle", "tags": ["ethics", "virtue"]}
        filter2 = {"author": "Aristotle", "tags": ["virtue", "ethics"]}  # Different list order

        key1 = cache_service._make_cache_key('query', 'text', filter1)
        key2 = cache_service._make_cache_key('query', 'text', filter2)

        # Keys should be DIFFERENT because list order is preserved
        assert key1 != key2, "Cache keys should differ when list values have different order"

    def test_cache_key_consistency_with_nested_dicts(self, cache_service):
        """Verify cache keys handle nested dictionaries consistently."""
        filter1 = {"must": {"author": "Kant"}, "should": {"topic": "ethics"}}
        filter2 = {"should": {"topic": "ethics"}, "must": {"author": "Kant"}}

        key1 = cache_service._make_cache_key('query', 'text', filter1)
        key2 = cache_service._make_cache_key('query', 'text', filter2)

        assert key1 == key2, "Cache keys should be identical for nested dicts"

    def test_cache_key_with_none_values(self, cache_service):
        """Verify None values are handled explicitly."""
        key1 = cache_service._make_cache_key('query', 'text', None, None)
        key2 = cache_service._make_cache_key('query', 'text', None, None)

        assert key1 == key2, "Cache keys should handle None values consistently"
        assert 'None' not in key1 or 'null' in key1, "None should be serialized explicitly"

    def test_cache_key_with_list_arguments(self, cache_service):
        """Verify list arguments maintain order."""
        vector_types1 = ["sparse_original", "dense_original"]
        vector_types2 = ["dense_original", "sparse_original"]

        key1 = cache_service._make_cache_key('query', 'text', vector_types1)
        key2 = cache_service._make_cache_key('query', 'text', vector_types2)

        # List order matters - different orders should produce different keys
        assert key1 != key2, "Cache keys should respect list ordering"

    def test_cache_key_with_identical_lists(self, cache_service):
        """Verify identical lists produce identical keys."""
        vector_types1 = ["sparse_original", "dense_original"]
        vector_types2 = ["sparse_original", "dense_original"]

        key1 = cache_service._make_cache_key('query', 'text', vector_types1)
        key2 = cache_service._make_cache_key('query', 'text', vector_types2)

        assert key1 == key2, "Identical lists should produce identical keys"

    def test_cache_key_with_pydantic_v2_model(self, cache_service):
        """Verify Pydantic v2 models serialize consistently via model_dump."""
        model1 = MockPydanticV2Model(author="Aristotle", tags=["ethics", "virtue"])
        model2 = MockPydanticV2Model(author="Aristotle", tags=["ethics", "virtue"])

        key1 = cache_service._make_cache_key('query', 'text', model1)
        key2 = cache_service._make_cache_key('query', 'text', model2)

        assert key1 == key2, "Pydantic v2 models with same data should produce identical keys"

    def test_cache_key_with_pydantic_v1_model(self, cache_service):
        """Verify Pydantic v1-style models serialize consistently via dict()."""
        model1 = MockPydanticV1Model(author="Kant", tags=["ethics"])
        model2 = MockPydanticV1Model(author="Kant", tags=["ethics"])

        key1 = cache_service._make_cache_key('query', 'text', model1)
        key2 = cache_service._make_cache_key('query', 'text', model2)

        assert key1 == key2, "Pydantic v1 models with same data should produce identical keys"

    def test_cache_key_with_mixed_types(self, cache_service):
        """Verify cache keys handle mixed argument types correctly."""
        # Simulate real query_hybrid call signature
        query_text = "What is virtue?"
        collection = "Aristotle"
        limit = 10
        vector_types = ["sparse_original", "dense_original"]
        filter_dict = {"author": "Aristotle"}
        payload = ["text", "summary"]

        key1 = cache_service._make_cache_key(
            'query', query_text, collection, limit, vector_types, filter_dict, payload
        )
        key2 = cache_service._make_cache_key(
            'query', query_text, collection, limit, vector_types, filter_dict, payload
        )

        assert key1 == key2, "Complex mixed-type arguments should produce consistent keys"

    def test_cache_key_with_boolean_payload(self, cache_service):
        """Verify boolean values in payload are handled correctly."""
        # payload can be True (all fields) or a list of field names
        key1 = cache_service._make_cache_key('query', 'text', 'collection', True)
        key2 = cache_service._make_cache_key('query', 'text', 'collection', True)

        assert key1 == key2, "Boolean payload should produce consistent keys"

    def test_serialize_key_args_primitives(self, cache_service):
        """Test _serialize_key_args with primitive types."""
        assert cache_service._serialize_key_args("text") == "text"
        assert cache_service._serialize_key_args(42) == 42
        assert cache_service._serialize_key_args(3.14) == 3.14
        assert cache_service._serialize_key_args(True) is True
        assert cache_service._serialize_key_args(False) is False
        assert cache_service._serialize_key_args(None) is None

    def test_serialize_key_args_collections(self, cache_service):
        """Test _serialize_key_args with collections."""
        # Lists should maintain order
        assert cache_service._serialize_key_args([1, 2, 3]) == [1, 2, 3]

        # Tuples should be converted to lists
        assert cache_service._serialize_key_args((1, 2, 3)) == [1, 2, 3]

        # Dicts should be sorted by key
        result = cache_service._serialize_key_args({"z": 1, "a": 2})
        assert list(result.keys()) == ["a", "z"]

    def test_serialize_key_args_nested_structures(self, cache_service):
        """Test _serialize_key_args with nested structures."""
        nested = {
            "outer": {
                "inner": ["a", "b"],
                "values": [1, 2, 3]
            }
        }
        result = cache_service._serialize_key_args(nested)

        assert isinstance(result, dict)
        assert isinstance(result["outer"], dict)
        assert isinstance(result["outer"]["inner"], list)

    def test_serialize_key_args_pydantic_model(self, cache_service):
        """Test _serialize_key_args with Pydantic model."""
        model = MockPydanticV2Model(author="Plato", tags=["forms", "idealism"])
        result = cache_service._serialize_key_args(model)

        # Should convert to dict
        assert isinstance(result, dict)
        assert result["author"] == "Plato"
        assert "forms" in result["tags"]

    def test_cache_key_format(self, cache_service):
        """Verify cache key format structure."""
        key = cache_service._make_cache_key('embedding', 'test text')

        # Format: {prefix}:{category}:{hash}
        parts = key.split(':')
        assert len(parts) == 3, "Cache key should have 3 parts: prefix:category:hash"
        assert parts[0] == 'test', "First part should be key prefix"
        assert parts[1] == 'embedding', "Second part should be category"
        assert len(parts[2]) == 64, "Third part should be 64-char SHA-256 hash"

    def test_cache_key_different_for_different_inputs(self, cache_service):
        """Verify different inputs produce different cache keys."""
        key1 = cache_service._make_cache_key('query', 'What is virtue?')
        key2 = cache_service._make_cache_key('query', 'What is justice?')

        assert key1 != key2, "Different query texts should produce different keys"

    def test_cache_key_collision_resistance(self, cache_service):
        """Verify cache keys are collision-resistant."""
        # Test that similar but different inputs produce different keys
        key1 = cache_service._make_cache_key('query', 'text', {'a': 1, 'b': 2})
        key2 = cache_service._make_cache_key('query', 'text', {'a': 1, 'b': 3})
        key3 = cache_service._make_cache_key('query', 'text', {'a': 1})

        assert key1 != key2, "Different values should produce different keys"
        assert key1 != key3, "Different structures should produce different keys"
        assert key2 != key3, "Different structures should produce different keys"


class TestCacheKeyRealWorldScenarios:
    """Test cache key generation with real-world Qdrant query scenarios."""

    def test_query_hybrid_signature(self, cache_service):
        """Test cache key generation matching query_hybrid method signature."""
        # From qdrant_manager.py:263-274
        query_text = "What is virtue ethics?"
        collection = "Aristotle"
        limit = 10
        vector_types = ["sparse_original", "dense_original"]
        filter_obj = {"philosopher": "Aristotle"}
        payload = ["text", "summary"]

        key = cache_service._make_cache_key(
            'query',
            query_text,
            collection,
            limit,
            vector_types,
            filter_obj,
            payload
        )

        # Verify key is generated successfully
        assert key.startswith('test:query:')
        assert len(key.split(':')[2]) == 64  # SHA-256 hash

    def test_embedding_signature(self, cache_service):
        """Test cache key generation matching embedding method signature."""
        # From llm_manager.py:721-727
        text = "Virtue is the mean between extremes"

        key = cache_service._make_cache_key('embedding', text)

        assert key.startswith('test:embedding:')
        assert len(key.split(':')[2]) == 64

    def test_splade_vector_signature(self, cache_service):
        """Test cache key generation matching SPLADE vector method signature."""
        # From llm_manager.py:786-792
        text = "What is the categorical imperative?"

        key = cache_service._make_cache_key('splade', text)

        assert key.startswith('test:splade:')
        assert len(key.split(':')[2]) == 64

    def test_cache_key_with_empty_filter(self, cache_service):
        """Test cache key when filter is None or empty dict."""
        key1 = cache_service._make_cache_key('query', 'text', 'collection', None)
        key2 = cache_service._make_cache_key('query', 'text', 'collection', {})

        # None and empty dict should produce different keys
        assert key1 != key2, "None and empty dict should produce different keys"

    def test_cache_key_stability_across_calls(self, cache_service):
        """Verify cache keys remain stable across multiple calls."""
        args = ('query', 'What is virtue?', 'Aristotle', 10, ['sparse'], {'a': 1}, True)

        keys = [cache_service._make_cache_key(*args) for _ in range(10)]

        # All keys should be identical
        assert len(set(keys)) == 1, "Cache keys should be stable across multiple calls"
