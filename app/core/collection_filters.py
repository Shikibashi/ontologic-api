"""
Shared collection filtering utilities.

Ensures consistent philosopher collection identification across
cache warming and API endpoints.

This module provides the single source of truth for determining which
collections are philosopher collections vs. excluded collections.
"""

from typing import List


def get_excluded_collection_names() -> List[str]:
    """
    Get list of collection names to exclude from philosopher collections.

    This is the single source of truth for filtering. Used by:
    - /get_philosophers endpoint (ontologic.py)
    - Cache warming service (cache_warming.py)

    Returns:
        List of collection names to exclude (meta collections + chat collections)

    Note:
        This function imports ChatQdrantService locally to avoid circular dependencies.
        ChatQdrantService is the authoritative source for chat collection patterns.
    """
    # Import here to avoid circular dependency
    from app.services.chat_qdrant_service import ChatQdrantService

    chat_collection_patterns = ChatQdrantService.get_all_chat_collection_patterns()

    return [
        "Meta Collection",
        "Combined Collection",
    ] + chat_collection_patterns


def filter_philosopher_collections(collection_names: List[str]) -> List[str]:
    """
    Filter collection names to only philosopher collections.

    Excludes:
    - Meta Collection
    - Combined Collection
    - All chat history collections (from ChatQdrantService)

    Args:
        collection_names: List of all collection names

    Returns:
        Filtered list containing only philosopher collections

    Example:
        >>> all_collections = ["Aristotle", "John Locke", "Chat_History", "Meta Collection"]
        >>> filter_philosopher_collections(all_collections)
        ["Aristotle", "John Locke"]
    """
    excluded = get_excluded_collection_names()
    return [name for name in collection_names if name not in excluded]
