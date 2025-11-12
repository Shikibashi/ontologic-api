"""Factory helpers for philosophy API tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from unittest.mock import MagicMock
from uuid import uuid4

from app.core.models import ConversationMessage, HybridQueryRequest


def create_mock_llm_response(
    content: str,
    *,
    model: str = "qwen3:8b",
    prompt_tokens: int = 450,
    completion_tokens: int = 320,
    **kwargs: Any,
) -> MagicMock:
    """Create a mock CompletionResponse-like object."""

    mock_response = MagicMock()
    mock_response.message = MagicMock()
    mock_response.message.content = content

    raw: Dict[str, Any] = {
        "model": model,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "done": True,
        "done_reason": "stop",
        "total_duration": 0,
        "load_duration": 0,
        "prompt_eval_duration": 0,
        "eval_duration": 0,
        "prompt_eval_count": prompt_tokens,
        "eval_count": completion_tokens,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
    raw.update(kwargs)

    mock_response.raw = raw
    return mock_response


def create_mock_node(
    node_id: str,
    text: str,
    *,
    score: float = 0.9,
    collection: str = "Aristotle",
    author: Optional[str] = None,
    **extra_payload: Any,
) -> MagicMock:
    """Create a mock Qdrant node."""

    payload = {
        "text": text,
        "collection_name": collection,
        "author": author or collection,
    }
    payload.update(extra_payload)

    node = MagicMock()
    node.id = node_id
    node.score = score
    node.payload = payload
    return node


def create_mock_collection(
    name: str,
    *,
    vectors_count: int = 1000,
    points_count: int = 1000,
    **extra: Any,
) -> MagicMock:
    """Create a mock Qdrant collection description."""

    collection = MagicMock()
    collection.name = name
    collection.vectors_count = vectors_count
    collection.points_count = points_count
    for key, value in extra.items():
        setattr(collection, key, value)
    return collection


def create_hybrid_query_request(
    query_str: str,
    *,
    collection: str = "Aristotle",
    vector_types: Optional[Iterable[str]] = None,
    filter: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> HybridQueryRequest:
    """Instantiate a HybridQueryRequest for testing."""

    payload: Dict[str, Any] = {
        "query_str": query_str,
        "collection": collection,
    }
    if vector_types is not None:
        payload["vector_types"] = list(vector_types)
    if filter is not None:
        payload["filter"] = filter
    payload.update(kwargs)
    return HybridQueryRequest(**payload)


def create_conversation_history(
    messages: Iterable[tuple[str, str]]
) -> List[ConversationMessage]:
    """Create conversation history objects."""

    history: List[ConversationMessage] = []
    for role, text in messages:
        history.append(
            ConversationMessage(id=str(uuid4()), role=role, content=text)
        )
    return history


def create_mock_nodes_dict(
    collection: str,
    *,
    num_nodes: int = 5,
    vector_types: Optional[Iterable[str]] = None,
    base_text: str = "Philosophical passage",
) -> Dict[str, List[MagicMock]]:
    """Create a mapping of vector type to mock nodes."""

    types = list(
        vector_types
        if vector_types is not None
        else [
            "sparse_original",
            "dense_original",
            "sparse_summary",
            "dense_summary",
        ]
    )

    nodes: Dict[str, List[MagicMock]] = {}
    for vector_type in types:
        nodes[vector_type] = [
            create_mock_node(
                node_id=f"{collection}-{vector_type}-{i}",
                text=f"{base_text} #{i} ({vector_type})",
                collection=collection,
                score=0.9 - i * 0.01,
            )
            for i in range(1, num_nodes + 1)
        ]
    return nodes


__all__ = [
    "create_mock_llm_response",
    "create_mock_node",
    "create_mock_collection",
    "create_hybrid_query_request",
    "create_conversation_history",
    "create_mock_nodes_dict",
]
