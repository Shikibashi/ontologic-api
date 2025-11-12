"""
Test suite for PDF context integration in /ask_philosophy endpoint.

Tests cover:
- PDF context retrieval when enabled
- Graceful handling when user has no documents
- Configuration flag behavior
- Context merging with conversation history
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_qdrant_manager_with_user_docs():
    """Mock QdrantManager with user documents."""
    manager = MagicMock()
    manager.qclient = AsyncMock()

    # Mock search results for user documents
    mock_point = MagicMock()
    mock_point.payload = {
        'text': 'Important information from user document',
        'filename': 'user_doc.pdf',
        'file_id': 'doc-123'
    }

    manager.qclient.search = AsyncMock(return_value=[mock_point])
    manager.qclient.get_collection = AsyncMock(return_value=MagicMock())

    # Mock gather_points_and_sort for philosophy nodes
    async def mock_gather(body, refeed=True):
        node = MagicMock()
        node.payload = {'text': 'Philosophy content', 'summary': ''}
        return [node]

    manager.gather_points_and_sort = mock_gather

    return manager


@pytest.fixture
def mock_llm_manager():
    """Mock LLMManager for embeddings and chat."""
    manager = MagicMock()
    manager.aembed = AsyncMock(return_value=[0.1] * 384)  # Mock embedding vector

    # Mock chat response
    mock_response = MagicMock()
    mock_response.raw = MagicMock()
    manager.achat = AsyncMock(return_value=mock_response)
    manager.set_llm_context_window = MagicMock()

    return manager


@pytest.fixture
def mock_chat_services():
    """Mock chat history and Qdrant services."""
    history_service = MagicMock()
    qdrant_service = MagicMock()

    history_service.store_message = AsyncMock(return_value=MagicMock(message_id='msg-1'))
    history_service.get_conversation_history = AsyncMock(return_value=[])
    history_service.update_message_qdrant_id = AsyncMock()

    qdrant_service.upload_message_to_qdrant = AsyncMock(return_value=['point-1'])
    qdrant_service.get_all_chat_collection_patterns = MagicMock(return_value=[])

    return history_service, qdrant_service


class TestPDFContextIntegration:
    """Tests for PDF context in /ask_philosophy endpoint."""

    @patch('app.config.settings.get_settings')
    @patch('app.router.ontologic.LLMResponseProcessor.extract_content_with_think_tag_removal')
    def test_pdf_context_when_enabled(
        self,
        mock_processor,
        mock_settings,
        test_client: TestClient,
        mock_qdrant_manager_with_user_docs,
        mock_llm_manager,
        mock_chat_services
    ):
        """Test that PDF context is retrieved when enabled."""
        # Configure settings
        settings = MagicMock()
        settings.chat_history = False  # Disable to simplify test
        settings.chat_use_pdf_context = True
        settings.pdf_context_limit = 5
        settings.default_context_window = 8192
        settings.max_context_window = 32000
        mock_settings.return_value = settings

        mock_processor.return_value = "AI response with document context"

        history_service, qdrant_service = mock_chat_services

        with patch('app.core.dependencies.get_llm_manager', return_value=mock_llm_manager):
            with patch('app.core.dependencies.get_qdrant_manager', return_value=mock_qdrant_manager_with_user_docs):
                with patch('app.core.dependencies.get_chat_history_service', return_value=history_service):
                    with patch('app.core.dependencies.get_chat_qdrant_service', return_value=qdrant_service):
                        response = test_client.post(
                            '/ask_philosophy',
                            json={
                                'query_str': 'What is the meaning of life?',
                                'collection': 'aristotle',
                                'top_k': 5
                            },
                            params={
                                'username': 'testuser',
                                'include_pdf_context': True
                            }
                        )

                        assert response.status_code == 200
                        # Verify document search was called
                        mock_qdrant_manager_with_user_docs.qclient.search.assert_called_once()

    @patch('app.config.settings.get_settings')
    @patch('app.router.ontologic.LLMResponseProcessor.extract_content_with_think_tag_removal')
    def test_pdf_context_disabled_by_config(
        self,
        mock_processor,
        mock_settings,
        test_client: TestClient,
        mock_qdrant_manager_with_user_docs,
        mock_llm_manager,
        mock_chat_services
    ):
        """Test that PDF context is NOT retrieved when config disabled."""
        settings = MagicMock()
        settings.chat_history = False
        settings.chat_use_pdf_context = False  # Disabled
        settings.default_context_window = 8192
        settings.max_context_window = 32000
        mock_settings.return_value = settings

        mock_processor.return_value = "AI response without document context"

        history_service, qdrant_service = mock_chat_services

        with patch('app.core.dependencies.get_llm_manager', return_value=mock_llm_manager):
            with patch('app.core.dependencies.get_qdrant_manager', return_value=mock_qdrant_manager_with_user_docs):
                with patch('app.core.dependencies.get_chat_history_service', return_value=history_service):
                    with patch('app.core.dependencies.get_chat_qdrant_service', return_value=qdrant_service):
                        response = test_client.post(
                            '/ask_philosophy',
                            json={
                                'query_str': 'What is the meaning of life?',
                                'collection': 'aristotle',
                                'top_k': 5
                            },
                            params={
                                'username': 'testuser',
                                'include_pdf_context': True
                            }
                        )

                        assert response.status_code == 200
                        # Document search should NOT be called
                        mock_qdrant_manager_with_user_docs.qclient.search.assert_not_called()

    @patch('app.config.settings.get_settings')
    @patch('app.router.ontologic.LLMResponseProcessor.extract_content_with_think_tag_removal')
    def test_pdf_context_no_username(
        self,
        mock_processor,
        mock_settings,
        test_client: TestClient,
        mock_qdrant_manager_with_user_docs,
        mock_llm_manager,
        mock_chat_services
    ):
        """Test that PDF context is skipped when no username provided."""
        settings = MagicMock()
        settings.chat_history = False
        settings.chat_use_pdf_context = True
        settings.default_context_window = 8192
        settings.max_context_window = 32000
        mock_settings.return_value = settings

        mock_processor.return_value = "AI response"

        history_service, qdrant_service = mock_chat_services

        with patch('app.core.dependencies.get_llm_manager', return_value=mock_llm_manager):
            with patch('app.core.dependencies.get_qdrant_manager', return_value=mock_qdrant_manager_with_user_docs):
                with patch('app.core.dependencies.get_chat_history_service', return_value=history_service):
                    with patch('app.core.dependencies.get_chat_qdrant_service', return_value=qdrant_service):
                        response = test_client.post(
                            '/ask_philosophy',
                            json={
                                'query_str': 'What is the meaning of life?',
                                'collection': 'aristotle',
                                'top_k': 5
                            },
                            params={
                                'include_pdf_context': True
                                # No username provided
                            }
                        )

                        assert response.status_code == 200
                        # Document search should NOT be called without username
                        mock_qdrant_manager_with_user_docs.qclient.search.assert_not_called()

    @patch('app.config.settings.get_settings')
    @patch('app.router.ontologic.LLMResponseProcessor.extract_content_with_think_tag_removal')
    def test_pdf_context_user_has_no_documents(
        self,
        mock_processor,
        mock_settings,
        test_client: TestClient,
        mock_llm_manager,
        mock_chat_services
    ):
        """Test graceful handling when user has no documents."""
        settings = MagicMock()
        settings.chat_history = False
        settings.chat_use_pdf_context = True
        settings.pdf_context_limit = 5
        settings.default_context_window = 8192
        settings.max_context_window = 32000
        mock_settings.return_value = settings

        mock_processor.return_value = "AI response"

        # Mock Qdrant manager where user has no collection
        mock_qdrant = MagicMock()
        mock_qdrant.qclient = AsyncMock()
        mock_qdrant.qclient.get_collection = AsyncMock(side_effect=Exception("Collection not found"))

        # Mock gather_points_and_sort
        async def mock_gather(body, refeed=True):
            node = MagicMock()
            node.payload = {'text': 'Philosophy content'}
            return [node]

        mock_qdrant.gather_points_and_sort = mock_gather

        history_service, qdrant_service = mock_chat_services

        with patch('app.core.dependencies.get_llm_manager', return_value=mock_llm_manager):
            with patch('app.core.dependencies.get_qdrant_manager', return_value=mock_qdrant):
                with patch('app.core.dependencies.get_chat_history_service', return_value=history_service):
                    with patch('app.core.dependencies.get_chat_qdrant_service', return_value=qdrant_service):
                        response = test_client.post(
                            '/ask_philosophy',
                            json={
                                'query_str': 'What is the meaning of life?',
                                'collection': 'aristotle',
                                'top_k': 5
                            },
                            params={
                                'username': 'newuser',
                                'include_pdf_context': True
                            }
                        )

                        # Should succeed even though user has no documents
                        assert response.status_code == 200

    @patch('app.config.settings.get_settings')
    @patch('app.router.ontologic.LLMResponseProcessor.extract_content_with_think_tag_removal')
    def test_pdf_context_respects_limit(
        self,
        mock_processor,
        mock_settings,
        test_client: TestClient,
        mock_llm_manager,
        mock_chat_services
    ):
        """Test that PDF context respects the configured limit."""
        settings = MagicMock()
        settings.chat_history = False
        settings.chat_use_pdf_context = True
        settings.pdf_context_limit = 3  # Limit to 3 chunks
        settings.default_context_window = 8192
        settings.max_context_window = 32000
        mock_settings.return_value = settings

        mock_processor.return_value = "AI response"

        # Mock Qdrant with multiple documents
        mock_qdrant = MagicMock()
        mock_qdrant.qclient = AsyncMock()
        mock_qdrant.qclient.get_collection = AsyncMock(return_value=MagicMock())

        # Mock search to return more results than limit
        mock_points = [
            MagicMock(payload={'text': f'Doc {i}', 'filename': f'file{i}.pdf'})
            for i in range(10)
        ]
        mock_qdrant.qclient.search = AsyncMock(return_value=mock_points)

        async def mock_gather(body, refeed=True):
            return [MagicMock(payload={'text': 'Philosophy'})]

        mock_qdrant.gather_points_and_sort = mock_gather

        history_service, qdrant_service = mock_chat_services

        with patch('app.core.dependencies.get_llm_manager', return_value=mock_llm_manager):
            with patch('app.core.dependencies.get_qdrant_manager', return_value=mock_qdrant):
                with patch('app.core.dependencies.get_chat_history_service', return_value=history_service):
                    with patch('app.core.dependencies.get_chat_qdrant_service', return_value=qdrant_service):
                        response = test_client.post(
                            '/ask_philosophy',
                            json={
                                'query_str': 'What is the meaning of life?',
                                'collection': 'aristotle',
                                'top_k': 5
                            },
                            params={
                                'username': 'testuser',
                                'include_pdf_context': True
                            }
                        )

                        assert response.status_code == 200
                        # Verify limit was passed to search
                        call_kwargs = mock_qdrant.qclient.search.call_args[1]
                        assert call_kwargs['limit'] == 3


class TestUsernameTracking:
    """Tests for username tracking in chat history."""

    @patch('app.config.settings.get_settings')
    @patch('app.router.ontologic.LLMResponseProcessor.extract_content_with_think_tag_removal')
    def test_username_stored_with_message(
        self,
        mock_processor,
        mock_settings,
        test_client: TestClient,
        mock_llm_manager,
        mock_chat_services
    ):
        """Test that username is stored with chat messages."""
        settings = MagicMock()
        settings.chat_history = True  # Enable chat history
        settings.chat_use_pdf_context = False
        settings.default_context_window = 8192
        settings.max_context_window = 32000
        mock_settings.return_value = settings

        mock_processor.return_value = "AI response"

        mock_qdrant = MagicMock()
        async def mock_gather(body, refeed=True):
            return [MagicMock(payload={'text': 'Philosophy'})]
        mock_qdrant.gather_points_and_sort = mock_gather

        history_service, qdrant_service = mock_chat_services

        with patch('app.core.dependencies.get_llm_manager', return_value=mock_llm_manager):
            with patch('app.core.dependencies.get_qdrant_manager', return_value=mock_qdrant):
                with patch('app.core.dependencies.get_chat_history_service', return_value=history_service):
                    with patch('app.core.dependencies.get_chat_qdrant_service', return_value=qdrant_service):
                        response = test_client.post(
                            '/ask_philosophy',
                            json={
                                'query_str': 'What is the meaning of life?',
                                'collection': 'aristotle',
                                'top_k': 5
                            },
                            params={
                                'session_id': 'session-123',
                                'username': 'testuser'
                            }
                        )

                        assert response.status_code == 200

                        # Verify username was passed to store_message
                        calls = history_service.store_message.call_args_list
                        assert len(calls) == 2  # User message + AI response

                        # Check username in both calls
                        for call in calls:
                            kwargs = call[1]
                            assert kwargs.get('username') == 'testuser'
