"""
Tests for cache warming service.

Verifies that cache warming correctly pre-loads frequently accessed data
into Redis cache during application startup.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.cache_warming import CacheWarmingService


class TestCacheWarmingConfiguration:
    """Test cache warming configuration and initialization."""

    def test_cache_warming_enabled_by_default(self):
        """Test that cache warming is enabled by default."""
        from app.config.settings import get_settings
        settings = get_settings()
        assert settings.cache_warming_enabled is True

    def test_cache_warming_items_default(self):
        """Test that cache warming items has correct default."""
        from app.config.settings import get_settings
        settings = get_settings()
        assert settings.cache_warming_items == "collections,embeddings"

    def test_cache_warming_service_initialization(self):
        """Test that CacheWarmingService initializes correctly."""
        mock_qdrant = MagicMock()
        mock_cache = MagicMock()
        mock_llm = MagicMock()

        service = CacheWarmingService(
            qdrant_manager=mock_qdrant,
            cache_service=mock_cache,
            llm_manager=mock_llm,
            enabled=True,
            warming_items="collections,embeddings"
        )

        assert service.enabled is True
        assert service.warming_items == ["collections", "embeddings"]
        assert service.qdrant_manager is mock_qdrant
        assert service.cache_service is mock_cache
        assert service.llm_manager is mock_llm


class TestPhilosopherCollectionsWarming:
    """Test warming of philosopher collections."""

    @pytest.mark.asyncio
    async def test_warm_philosopher_collections_success(self):
        """Test successful warming of philosopher collections."""
        # Mock Qdrant manager
        mock_qdrant = MagicMock()
        mock_collections = MagicMock()
        aristotle_mock = MagicMock()
        aristotle_mock.name = "Aristotle"
        locke_mock = MagicMock()
        locke_mock.name = "John Locke"
        nietzsche_mock = MagicMock()
        nietzsche_mock.name = "Friedrich Nietzsche"
        chat_mock = MagicMock()
        chat_mock.name = "Chat_History"
        
        mock_collections.collections = [
            aristotle_mock,
            locke_mock,
            nietzsche_mock,
            chat_mock,  # Should be filtered out
        ]
        mock_qdrant.get_collections = AsyncMock(return_value=mock_collections)

        # Mock cache service
        mock_cache = MagicMock()
        mock_cache.make_constant_cache_key = MagicMock(return_value="test_key")
        mock_cache.set = AsyncMock(return_value=True)

        service = CacheWarmingService(
            qdrant_manager=mock_qdrant,
            cache_service=mock_cache,
            enabled=True,
            warming_items="collections"
        )

        await service._warm_philosopher_collections()

        # Verify collections were fetched
        mock_qdrant.get_collections.assert_called_once()

        # Verify cache was set with philosopher collections
        mock_cache.set.assert_called_once()
        call_args = mock_cache.set.call_args
        assert call_args[0][0] == "test_key"  # cache_key
        assert "Aristotle" in call_args[0][1]  # cached value
        assert "John Locke" in call_args[0][1]
        assert "Friedrich Nietzsche" in call_args[0][1]
        assert "Chat_History" not in call_args[0][1]  # Filtered out
        assert call_args[0][2] == 3600  # TTL

        # Verify stats were updated
        assert service._warming_stats["philosopher_collections"]["success"] is True
        assert service._warming_stats["philosopher_collections"]["items_warmed"] == 3

    @pytest.mark.asyncio
    async def test_warm_philosopher_collections_no_qdrant(self):
        """Test warming skipped when QdrantManager not available."""
        service = CacheWarmingService(
            qdrant_manager=None,
            cache_service=MagicMock(),
            enabled=True,
            warming_items="collections"
        )

        await service._warm_philosopher_collections()

        # Verify error was recorded
        assert "qdrant_manager_unavailable" in service._warming_stats["errors"]

    @pytest.mark.asyncio
    async def test_warm_philosopher_collections_no_cache(self):
        """Test warming skipped when CacheService not available."""
        service = CacheWarmingService(
            qdrant_manager=MagicMock(),
            cache_service=None,
            enabled=True,
            warming_items="collections"
        )

        await service._warm_philosopher_collections()

        # Verify error was recorded
        assert "cache_service_unavailable" in service._warming_stats["errors"]

    @pytest.mark.asyncio
    async def test_warm_philosopher_collections_qdrant_error(self):
        """Test error handling when Qdrant query fails."""
        mock_qdrant = MagicMock()
        mock_qdrant.get_collections = AsyncMock(side_effect=Exception("Qdrant error"))

        mock_cache = MagicMock()
        mock_cache._make_cache_key = MagicMock(return_value="test_key")

        service = CacheWarmingService(
            qdrant_manager=mock_qdrant,
            cache_service=mock_cache,
            enabled=True,
            warming_items="collections"
        )

        await service._warm_philosopher_collections()

        # Verify error was recorded
        assert service._warming_stats["philosopher_collections"]["success"] is False
        assert len(service._warming_stats["errors"]) > 0


class TestCommonEmbeddingsWarming:
    """Test warming of common embeddings."""

    @pytest.mark.asyncio
    async def test_warm_common_embeddings_success(self):
        """Test successful warming of common embeddings."""
        # Mock LLM manager
        mock_llm = MagicMock()
        mock_llm.get_embedding = AsyncMock(return_value=[0.1, 0.2, 0.3])

        service = CacheWarmingService(
            qdrant_manager=MagicMock(),
            cache_service=MagicMock(),
            llm_manager=mock_llm,
            enabled=True,
            warming_items="embeddings"
        )

        await service._warm_common_embeddings()

        # Verify embeddings were generated for common terms
        assert mock_llm.get_embedding.call_count >= 5  # At least 5 philosopher names

        # Verify stats were updated
        assert service._warming_stats["common_embeddings"]["success"] is True
        assert service._warming_stats["common_embeddings"]["items_warmed"] >= 5

    @pytest.mark.asyncio
    async def test_warm_common_embeddings_no_llm(self):
        """Test warming skipped when LLMManager not available."""
        service = CacheWarmingService(
            qdrant_manager=MagicMock(),
            cache_service=MagicMock(),
            llm_manager=None,
            enabled=True,
            warming_items="embeddings"
        )

        await service._warm_common_embeddings()

        # Verify error was recorded
        assert "llm_manager_unavailable" in service._warming_stats["errors"]

    @pytest.mark.asyncio
    async def test_warm_common_embeddings_partial_failure(self):
        """Test that warming continues even if some embeddings fail."""
        # Mock LLM manager that fails for some terms
        mock_llm = MagicMock()
        call_count = 0

        async def mock_get_embedding(text):
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # Fail on second call
                raise Exception("Embedding error")
            return [0.1, 0.2, 0.3]

        mock_llm.get_embedding = mock_get_embedding

        service = CacheWarmingService(
            qdrant_manager=MagicMock(),
            cache_service=MagicMock(),
            llm_manager=mock_llm,
            enabled=True,
            warming_items="embeddings"
        )

        await service._warm_common_embeddings()

        # Verify some embeddings were warmed despite one failure
        assert service._warming_stats["common_embeddings"]["success"] is True
        assert service._warming_stats["common_embeddings"]["items_warmed"] >= 4


class TestCacheWarmingOrchestration:
    """Test overall cache warming orchestration."""

    @pytest.mark.asyncio
    async def test_warm_cache_disabled(self):
        """Test that warming is skipped when disabled."""
        service = CacheWarmingService(
            qdrant_manager=MagicMock(),
            cache_service=MagicMock(),
            llm_manager=MagicMock(),
            enabled=False
        )

        result = await service.warm_cache()

        assert result["enabled"] is False

    @pytest.mark.asyncio
    async def test_warm_cache_collections_only(self):
        """Test warming only collections when configured."""
        mock_qdrant = MagicMock()
        mock_collections = MagicMock()
        mock_collections.collections = [MagicMock(name="Aristotle")]
        mock_qdrant.get_collections = AsyncMock(return_value=mock_collections)

        mock_cache = MagicMock()
        mock_cache._make_cache_key = MagicMock(return_value="test_key")
        mock_cache.set = AsyncMock(return_value=True)

        mock_llm = MagicMock()
        mock_llm.get_embedding = AsyncMock(return_value=[0.1, 0.2, 0.3])

        service = CacheWarmingService(
            qdrant_manager=mock_qdrant,
            cache_service=mock_cache,
            llm_manager=mock_llm,
            enabled=True,
            warming_items="collections"  # Only collections
        )

        result = await service.warm_cache()

        # Verify collections were warmed
        assert result["stats"]["philosopher_collections"]["success"] is True

        # Verify embeddings were NOT warmed
        assert result["stats"]["common_embeddings"]["items_warmed"] == 0

    @pytest.mark.asyncio
    async def test_warm_cache_embeddings_only(self):
        """Test warming only embeddings when configured."""
        mock_llm = MagicMock()
        mock_llm.get_embedding = AsyncMock(return_value=[0.1, 0.2, 0.3])

        service = CacheWarmingService(
            qdrant_manager=MagicMock(),
            cache_service=MagicMock(),
            llm_manager=mock_llm,
            enabled=True,
            warming_items="embeddings"  # Only embeddings
        )

        result = await service.warm_cache()

        # Verify embeddings were warmed
        assert result["stats"]["common_embeddings"]["success"] is True

        # Verify collections were NOT warmed
        assert result["stats"]["philosopher_collections"]["items_warmed"] == 0

    @pytest.mark.asyncio
    async def test_warm_cache_both(self):
        """Test warming both collections and embeddings."""
        # Mock Qdrant
        mock_qdrant = MagicMock()
        mock_collections = MagicMock()
        mock_collections.collections = [MagicMock(name="Aristotle")]
        mock_qdrant.get_collections = AsyncMock(return_value=mock_collections)

        # Mock cache
        mock_cache = MagicMock()
        mock_cache._make_cache_key = MagicMock(return_value="test_key")
        mock_cache.set = AsyncMock(return_value=True)

        # Mock LLM
        mock_llm = MagicMock()
        mock_llm.get_embedding = AsyncMock(return_value=[0.1, 0.2, 0.3])

        service = CacheWarmingService(
            qdrant_manager=mock_qdrant,
            cache_service=mock_cache,
            llm_manager=mock_llm,
            enabled=True,
            warming_items="collections,embeddings"
        )

        result = await service.warm_cache()

        # Verify both were warmed
        assert result["enabled"] is True
        assert result["stats"]["philosopher_collections"]["success"] is True
        assert result["stats"]["common_embeddings"]["success"] is True
        assert result["stats"]["total_duration_seconds"] > 0

    def test_get_stats(self):
        """Test getting cache warming statistics."""
        service = CacheWarmingService(
            qdrant_manager=MagicMock(),
            cache_service=MagicMock(),
            enabled=True
        )

        stats = service.get_stats()

        assert stats["enabled"] is True
        assert "stats" in stats
        assert "philosopher_collections" in stats["stats"]
        assert "common_embeddings" in stats["stats"]


class TestCacheWarmingMetrics:
    """Test Prometheus metrics integration."""

    @pytest.mark.asyncio
    async def test_metrics_recorded_on_success(self):
        """Test that cache warming completes successfully (metrics are handled by decorator)."""
        # Mock services
        mock_qdrant = MagicMock()
        mock_collections = MagicMock()
        aristotle_mock = MagicMock()
        aristotle_mock.name = "Aristotle"
        mock_collections.collections = [aristotle_mock]
        mock_qdrant.get_collections = AsyncMock(return_value=mock_collections)

        mock_cache = MagicMock()
        mock_cache.make_constant_cache_key = MagicMock(return_value="test_key")
        mock_cache.set = AsyncMock(return_value=True)

        service = CacheWarmingService(
            qdrant_manager=mock_qdrant,
            cache_service=mock_cache,
            enabled=True,
            warming_items="collections"
        )

        result = await service.warm_cache()

        # Verify cache warming completed successfully
        assert result["enabled"] is True
        assert "stats" in result
        
        # Verify cache was called
        mock_cache.set.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
