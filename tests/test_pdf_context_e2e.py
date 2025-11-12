"""
End-to-end integration test for PDF context workflow.

This test verifies that:
1. Documents can be uploaded
2. Chat requests with include_pdf_context=true actually use document content
3. Document nodes are merged with philosopher nodes in LLM prompts
"""

import pytest
import io
from unittest.mock import AsyncMock, MagicMock, patch
from app.core import dependencies as deps
from app.config.settings import get_settings
from app.core.models import Raw, Usage


def test_pdf_context_e2e_workflow_documents_merged_with_philosopher_nodes(test_client):
    """
    Verify that uploaded documents are actually merged with philosopher nodes
    and passed to the LLM, not just logged.

    This is a critical test to ensure the PDF context feature actually works.
    """
    # Step 1: Upload a PDF with known content
    pdf_content = b'%PDF-1.4\nTest document about quantum mechanics and philosophy'

    # Mock Qdrant manager for document upload
    mock_qdrant_upload = MagicMock()
    mock_qdrant_upload.qclient = AsyncMock()

    with patch('app.router.documents.QdrantUploadService') as mock_upload_service:
        mock_upload_service.return_value.upload_file = AsyncMock(return_value={
            'status': 'success',
            'file_id': 'test-pdf-123',
            'filename': 'quantum_philosophy.pdf',
            'collection': 'testuser',
            'chunks_uploaded': 3,
            'point_ids': ['point-1', 'point-2', 'point-3']
        })

        # Override Qdrant dependency for upload
        test_client.app.dependency_overrides[deps.get_qdrant_manager] = lambda: mock_qdrant_upload

        try:
            upload_response = test_client.post(
                '/documents/upload',
                files={'file': ('quantum_philosophy.pdf', io.BytesIO(pdf_content), 'application/pdf')},
                params={'username': 'testuser'}
            )

            assert upload_response.status_code == 200
            assert upload_response.json()['file_id'] == 'test-pdf-123'
        finally:
            test_client.app.dependency_overrides.clear()

    # Step 2: Ask a philosophy question with PDF context enabled
    # Configure settings
    settings = MagicMock()
    settings.chat_history = False
    settings.chat_use_pdf_context = True  # Enable PDF context
    settings.pdf_context_limit = 5
    settings.default_context_window = 8192
    settings.max_context_window = 32000

    # Mock Qdrant manager for chat
    mock_qdrant = MagicMock()
    mock_qdrant.qclient = AsyncMock()

    # Mock gather_points_and_sort to return philosopher nodes
    philosopher_node = MagicMock()
    philosopher_node.payload = {
        'text': 'Aristotle discusses the nature of reality',
        'summary': 'Philosophy of reality'
    }

    async def mock_gather(body, refeed=True):
        return [philosopher_node]

    mock_qdrant.gather_points_and_sort = mock_gather

    # Mock user document collection exists
    mock_qdrant.qclient.get_collection = AsyncMock(return_value=MagicMock())

    # Mock document search results
    doc_result = MagicMock()
    doc_result.payload = {
        'text': 'Quantum mechanics relates to philosophical questions about determinism and free will',
        'filename': 'quantum_philosophy.pdf',
        'document_type': 'pdf'
    }
    doc_result.score = 0.95
    mock_qdrant.qclient.search = AsyncMock(return_value=[doc_result])

    # Mock LLM manager
    mock_llm = MagicMock()
    mock_llm.aembed = AsyncMock(return_value=[0.1] * 384)

    # This is the CRITICAL check: verify achat receives merged nodes
    captured_nodes = None

    async def capture_achat(query, nodes, **kwargs):
        nonlocal captured_nodes
        captured_nodes = nodes
        response = MagicMock()
        response.raw = Raw(
            model="test-model",
            created_at="2025-01-01T00:00:00Z",
            done=True,
            done_reason="stop",
            total_duration=1000000,
            load_duration=100000,
            prompt_eval_count=10,
            prompt_eval_duration=500000,
            eval_count=20,
            eval_duration=400000,
            usage=Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        )
        return response

    mock_llm.achat = capture_achat
    mock_llm.set_llm_context_window = MagicMock()

    # Mock chat services
    mock_chat_history = MagicMock()
    mock_chat_history.store_message = AsyncMock(return_value=MagicMock())
    mock_chat_history.get_conversation_history = AsyncMock(return_value=[])
    mock_chat_history.update_message_qdrant_id = AsyncMock()

    mock_chat_qdrant = MagicMock()
    mock_chat_qdrant.upload_message_to_qdrant = AsyncMock(return_value=['point-1'])
    mock_chat_qdrant.get_all_chat_collection_patterns = MagicMock(return_value=[])

    # Override dependencies
    test_client.app.dependency_overrides[deps.get_qdrant_manager] = lambda: mock_qdrant
    test_client.app.dependency_overrides[deps.get_llm_manager] = lambda: mock_llm
    test_client.app.dependency_overrides[deps.get_chat_history_service] = lambda: mock_chat_history
    test_client.app.dependency_overrides[deps.get_chat_qdrant_service] = lambda: mock_chat_qdrant

    try:
        with patch('app.router.ontologic.LLMResponseProcessor.extract_content_with_think_tag_removal') as mock_processor, \
             patch('app.router.ontologic.get_settings', return_value=settings):
            mock_processor.return_value = "Response about quantum philosophy using document context"

            # Make the request
            response = test_client.post(
                '/ask_philosophy',
                json={
                    'query_str': 'How does quantum mechanics relate to free will?',
                    'collection': 'aristotle',
                    'top_k': 5
                },
                params={
                    'username': 'testuser',
                    'include_pdf_context': True  # Request PDF context
                }
            )

            assert response.status_code == 200

            # CRITICAL ASSERTION: Verify nodes were actually merged
            assert captured_nodes is not None, "achat was not called with nodes"
            assert len(captured_nodes) == 2, f"Expected 2 nodes (1 doc + 1 philosopher), got {len(captured_nodes)}"

            # Verify first node is the document (prioritized)
            doc_node = captured_nodes[0]
            assert hasattr(doc_node, 'payload'), "Document node missing payload"
            assert 'Quantum mechanics' in doc_node.payload['text'], "Document text not in first node"
            assert doc_node.payload.get('source') == 'user_document', "Source not marked as user_document"
            assert doc_node.payload.get('filename') == 'quantum_philosophy.pdf'

            # Verify second node is the philosopher node
            phil_node = captured_nodes[1]
            assert 'Aristotle' in phil_node.payload['text'], "Philosopher content not in second node"
    finally:
        test_client.app.dependency_overrides.clear()


def test_pdf_context_disabled_when_flag_false(test_client):
    """Verify PDF context is NOT retrieved when chat_use_pdf_context=False."""
    # Configure settings with PDF context DISABLED
    settings = MagicMock()
    settings.chat_history = False
    settings.chat_use_pdf_context = False  # Disabled
    settings.default_context_window = 8192
    settings.max_context_window = 32000

    # Mock Qdrant manager
    mock_qdrant = MagicMock()
    mock_qdrant.qclient = AsyncMock()

    # Mock philosopher nodes
    async def mock_gather(body, refeed=True):
        return [MagicMock(payload={'text': 'Philosophy text'})]
    mock_qdrant.gather_points_and_sort = mock_gather

    # Mock LLM
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.raw = Raw(
        model="test-model",
        created_at="2025-01-01T00:00:00Z",
        done=True,
        done_reason="stop",
        total_duration=1000000,
        load_duration=100000,
        prompt_eval_count=10,
        prompt_eval_duration=500000,
        eval_count=20,
        eval_duration=400000,
        usage=Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    )
    mock_llm.achat = AsyncMock(return_value=mock_response)
    mock_llm.set_llm_context_window = MagicMock()

    # Mock chat services
    mock_chat_history = MagicMock()
    mock_chat_history.store_message = AsyncMock(return_value=MagicMock())
    mock_chat_history.get_conversation_history = AsyncMock(return_value=[])
    mock_chat_history.update_message_qdrant_id = AsyncMock()

    mock_chat_qdrant = MagicMock()
    mock_chat_qdrant.upload_message_to_qdrant = AsyncMock(return_value=[])
    mock_chat_qdrant.get_all_chat_collection_patterns = MagicMock(return_value=[])

    # Override dependencies
    test_client.app.dependency_overrides[deps.get_qdrant_manager] = lambda: mock_qdrant
    test_client.app.dependency_overrides[deps.get_llm_manager] = lambda: mock_llm
    test_client.app.dependency_overrides[deps.get_chat_history_service] = lambda: mock_chat_history
    test_client.app.dependency_overrides[deps.get_chat_qdrant_service] = lambda: mock_chat_qdrant

    try:
        with patch('app.router.ontologic.LLMResponseProcessor.extract_content_with_think_tag_removal') as mock_processor, \
             patch('app.router.ontologic.get_settings', return_value=settings):
            mock_processor.return_value = "Response"

            response = test_client.post(
                '/ask_philosophy',
                json={
                    'query_str': 'Test question',
                    'collection': 'aristotle',
                    'top_k': 5
                },
                params={
                    'username': 'testuser',
                    'include_pdf_context': True  # User requests it, but feature is disabled
                }
            )

            assert response.status_code == 200

            # Verify document collection was NOT queried
            mock_qdrant.qclient.get_collection.assert_not_called()
            mock_qdrant.qclient.search.assert_not_called()
    finally:
        test_client.app.dependency_overrides.clear()


def test_pdf_context_graceful_failure_no_documents(test_client):
    """Verify graceful handling when user has no documents."""
    settings = MagicMock()
    settings.chat_history = False
    settings.chat_use_pdf_context = True
    settings.pdf_context_limit = 5
    settings.default_context_window = 8192
    settings.max_context_window = 32000

    mock_qdrant = MagicMock()
    mock_qdrant.qclient = AsyncMock()

    async def mock_gather(body, refeed=True):
        return [MagicMock(payload={'text': 'Philosophy'})]
    mock_qdrant.gather_points_and_sort = mock_gather

    # User has no documents collection
    mock_qdrant.qclient.get_collection = AsyncMock(side_effect=Exception("Collection not found"))

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.raw = Raw(
        model="test-model",
        created_at="2025-01-01T00:00:00Z",
        done=True,
        done_reason="stop",
        total_duration=1000000,
        load_duration=100000,
        prompt_eval_count=10,
        prompt_eval_duration=500000,
        eval_count=20,
        eval_duration=400000,
        usage=Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    )
    mock_llm.achat = AsyncMock(return_value=mock_response)
    mock_llm.set_llm_context_window = MagicMock()

    mock_chat_history = MagicMock()
    mock_chat_history.store_message = AsyncMock(return_value=MagicMock())
    mock_chat_history.get_conversation_history = AsyncMock(return_value=[])
    mock_chat_history.update_message_qdrant_id = AsyncMock()

    mock_chat_qdrant = MagicMock()
    mock_chat_qdrant.upload_message_to_qdrant = AsyncMock(return_value=[])
    mock_chat_qdrant.get_all_chat_collection_patterns = MagicMock(return_value=[])

    # Override dependencies
    test_client.app.dependency_overrides[deps.get_qdrant_manager] = lambda: mock_qdrant
    test_client.app.dependency_overrides[deps.get_llm_manager] = lambda: mock_llm
    test_client.app.dependency_overrides[deps.get_chat_history_service] = lambda: mock_chat_history
    test_client.app.dependency_overrides[deps.get_chat_qdrant_service] = lambda: mock_chat_qdrant

    try:
        with patch('app.router.ontologic.LLMResponseProcessor.extract_content_with_think_tag_removal') as mock_processor, \
             patch('app.router.ontologic.get_settings', return_value=settings):
            mock_processor.return_value = "Response"

            # Should succeed even though user has no documents
            response = test_client.post(
                '/ask_philosophy',
                json={
                    'query_str': 'Test question',
                    'collection': 'aristotle',
                    'top_k': 5
                },
                params={
                    'username': 'newuser',
                    'include_pdf_context': True
                }
            )

            assert response.status_code == 200
    finally:
        test_client.app.dependency_overrides.clear()
