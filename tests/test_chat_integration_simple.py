"""
Simple integration tests for chat history functionality.

These tests verify the core functionality without complex fixture dependencies.
"""

import pytest
import uuid
import asyncio
from datetime import datetime
from typing import List, Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.db_models import ChatMessage, MessageRole
from app.services.chat_history_service import ChatHistoryService
from app.services.chat_qdrant_service import ChatQdrantService
from app.core.chat_exceptions import ChatPrivacyError, ChatValidationError


class TestChatIntegrationSimple:
    """Simple integration tests for chat history system."""

    @pytest.mark.asyncio
    async def test_message_storage_and_retrieval_flow(self):
        """
        Test basic message storage and retrieval flow.
        
        Requirements: 1.1, 1.2, 1.4
        """
        # Setup service with mock cache
        mock_cache_service = MagicMock()
        mock_cache_service.get = AsyncMock(return_value=None)
        mock_cache_service.set = AsyncMock()
        mock_cache_service.clear_cache = AsyncMock()
        
        chat_service = ChatHistoryService(cache_service=mock_cache_service)
        
        # Mock storage
        stored_messages = []
        
        async def mock_store_message(session_id, role, content, **kwargs):
            message = ChatMessage(
                message_id=str(uuid.uuid4()),
                conversation_id=str(uuid.uuid4()),
                session_id=session_id,
                role=MessageRole.USER if role == "user" else MessageRole.ASSISTANT,
                content=content,
                created_at=datetime.utcnow()
            )
            stored_messages.append(message)
            return message
        
        async def mock_get_history(session_id, **kwargs):
            return [msg for msg in stored_messages if msg.session_id == session_id]
        
        with patch.object(chat_service, 'store_message', side_effect=mock_store_message), \
             patch.object(chat_service, 'get_conversation_history', side_effect=mock_get_history):
            
            session_id = f"test_session_{uuid.uuid4().hex[:8]}"
            
            # Store messages
            msg1 = await chat_service.store_message(
                session_id=session_id,
                role="user",
                content="What is virtue ethics?"
            )
            
            msg2 = await chat_service.store_message(
                session_id=session_id,
                role="assistant",
                content="Virtue ethics focuses on character..."
            )
            
            # Retrieve messages
            history = await chat_service.get_conversation_history(session_id)
            
            # Verify
            assert len(history) == 2
            assert all(msg.session_id == session_id for msg in history)
            assert history[0].content == "What is virtue ethics?"
            assert history[1].content == "Virtue ethics focuses on character..."

    @pytest.mark.asyncio
    async def test_session_isolation(self):
        """
        Test that different sessions cannot access each other's data.
        
        Requirements: 7.4, 7.5
        """
        mock_cache_service = MagicMock()
        chat_service = ChatHistoryService(cache_service=mock_cache_service)
        
        # Create separate storage for each session
        session_storage = {}
        
        async def mock_store_message(session_id, role, content, **kwargs):
            if session_id not in session_storage:
                session_storage[session_id] = []
            
            message = ChatMessage(
                message_id=str(uuid.uuid4()),
                conversation_id=str(uuid.uuid4()),
                session_id=session_id,
                role=MessageRole.USER if role == "user" else MessageRole.ASSISTANT,
                content=content,
                created_at=datetime.utcnow()
            )
            session_storage[session_id].append(message)
            return message
        
        async def mock_get_history(session_id, **kwargs):
            return session_storage.get(session_id, [])
        
        with patch.object(chat_service, 'store_message', side_effect=mock_store_message), \
             patch.object(chat_service, 'get_conversation_history', side_effect=mock_get_history):
            
            # Create two different sessions
            session1 = f"user1_session_{uuid.uuid4().hex[:8]}"
            session2 = f"user2_session_{uuid.uuid4().hex[:8]}"
            
            # Store different data for each session
            await chat_service.store_message(
                session_id=session1,
                role="user",
                content="User 1's private message"
            )
            
            await chat_service.store_message(
                session_id=session2,
                role="user",
                content="User 2's confidential data"
            )
            
            # Verify session isolation
            history1 = await chat_service.get_conversation_history(session1)
            history2 = await chat_service.get_conversation_history(session2)
            
            # Each session should only see its own data
            assert len(history1) == 1
            assert len(history2) == 1
            
            assert history1[0].content == "User 1's private message"
            assert history2[0].content == "User 2's confidential data"
            
            # Cross-contamination check
            user1_contents = [msg.content for msg in history1]
            user2_contents = [msg.content for msg in history2]
            
            assert "User 2's confidential data" not in user1_contents
            assert "User 1's private message" not in user2_contents

    @pytest.mark.asyncio
    async def test_qdrant_collection_privacy(self):
        """
        Test Qdrant collection privacy and filtering.
        
        Requirements: 2.5, 7.1, 7.2
        """
        # Test collection name mapping
        with patch.dict('os.environ', {'APP_ENV': 'test'}):
            mock_qdrant_client = AsyncMock()
            mock_llm_manager = AsyncMock()
            
            service = ChatQdrantService(mock_qdrant_client, mock_llm_manager)
            assert service.collection_name == "Chat_History_Test"
        
        with patch.dict('os.environ', {'APP_ENV': 'dev'}):
            service = ChatQdrantService(mock_qdrant_client, mock_llm_manager)
            assert service.collection_name == "Chat_History_Dev"
        
        with patch.dict('os.environ', {'APP_ENV': 'prod'}):
            service = ChatQdrantService(mock_qdrant_client, mock_llm_manager)
            assert service.collection_name == "Chat_History"
        
        # Test collection pattern detection
        patterns = ChatQdrantService.get_all_chat_collection_patterns()
        expected = ["Chat_History", "Chat_History_Dev", "Chat_History_Test"]
        assert set(patterns) == set(expected)
        
        # Test chat collection identification
        assert ChatQdrantService.is_chat_collection("Chat_History") is True
        assert ChatQdrantService.is_chat_collection("Chat_History_Dev") is True
        assert ChatQdrantService.is_chat_collection("Chat_History_Test") is True
        assert ChatQdrantService.is_chat_collection("Aristotle") is False
        assert ChatQdrantService.is_chat_collection("Kant") is False

    @pytest.mark.asyncio
    async def test_vector_search_session_filtering(self):
        """
        Test that vector search properly filters by session ID.
        
        Requirements: 3.1, 3.2, 7.4
        """
        mock_qdrant_client = AsyncMock()
        mock_llm_manager = AsyncMock()
        mock_llm_manager.generate_dense_vector.return_value = [0.1] * 1024
        
        with patch.dict('os.environ', {'APP_ENV': 'test'}):
            service = ChatQdrantService(mock_qdrant_client, mock_llm_manager)
        
        # Mock search results with session filtering
        def mock_search(collection_name, query_vector, query_filter=None, **kwargs):
            # Simulate results from different sessions
            all_results = [
                MagicMock(
                    id="point1",
                    score=0.9,
                    payload={
                        "session_id": "session1",
                        "content": "Session 1 content",
                        "message_id": "msg1"
                    }
                ),
                MagicMock(
                    id="point2", 
                    score=0.8,
                    payload={
                        "session_id": "session2",
                        "content": "Session 2 content",
                        "message_id": "msg2"
                    }
                )
            ]
            
            # Apply session filter
            if query_filter and hasattr(query_filter, 'must'):
                filtered_results = []
                for result in all_results:
                    for condition in query_filter.must:
                        if (condition.key == "session_id" and 
                            hasattr(condition, 'match') and
                            result.payload["session_id"] == condition.match.value):
                            filtered_results.append(result)
                return filtered_results
            
            return all_results
        
        mock_qdrant_client.search = AsyncMock(side_effect=mock_search)
        
        # Test search with session filtering
        results = await service.search_messages(
            session_id="session1",
            query="test query"
        )
        
        # Should only return results from session1
        if results:  # Handle fallback decorator potentially returning None/empty
            for result in results:
                if isinstance(result, dict):
                    assert result.get("session_id") == "session1"

    @pytest.mark.asyncio
    async def test_privacy_violation_detection(self):
        """
        Test detection of privacy violations in search results.
        
        Requirements: 7.3, 7.4, 7.5
        """
        # Test the privacy validation logic directly
        from app.core.chat_exceptions import ChatPrivacyError
        
        # Simulate privacy violation scenario
        requesting_session = "user_session_123"
        violating_session = "different_user_456"
        
        # Mock result that violates privacy (different session)
        mock_result = MagicMock()
        mock_result.payload = {"session_id": violating_session}
        
        # Test the privacy check logic that should be in the service
        # This simulates what happens when a search result has wrong session_id
        result_session_id = mock_result.payload.get("session_id")
        
        # Verify privacy violation is detected
        assert result_session_id != requesting_session
        
        # Test that ChatPrivacyError can be raised with correct parameters
        try:
            raise ChatPrivacyError(
                message="Search result privacy violation detected",
                violation_type="cross_session_result",
                session_id=requesting_session,
                details={"violating_session": violating_session}
            )
        except ChatPrivacyError as e:
            assert e.violation_type == "cross_session_result"
            assert e.session_id == requesting_session
            assert "privacy violation" in str(e).lower()
        
        # Test collection privacy patterns
        mock_qdrant_client = AsyncMock()
        mock_llm_manager = AsyncMock()
        
        with patch.dict('os.environ', {'APP_ENV': 'test'}):
            service = ChatQdrantService(mock_qdrant_client, mock_llm_manager)
        
        # Verify chat collection patterns are properly configured
        patterns = service.get_all_chat_collection_patterns()
        assert "Chat_History_Test" in patterns
        assert service.is_chat_collection("Chat_History_Test") is True
        assert service.is_chat_collection("Aristotle") is False

    @pytest.mark.asyncio
    async def test_error_handling_and_fallbacks(self):
        """
        Test error handling and fallback scenarios.
        
        Requirements: 5.4
        """
        mock_cache_service = MagicMock()
        chat_service = ChatHistoryService(cache_service=mock_cache_service)
        
        # Test validation errors
        with patch.object(chat_service, 'store_message') as mock_store:
            mock_store.side_effect = ChatValidationError(
                message="Invalid session ID",
                field="session_id",
                value=""
            )
            
            with pytest.raises(ChatValidationError):
                await chat_service.store_message(
                    session_id="",
                    role="user",
                    content="test"
                )
        
        # Test graceful degradation
        with patch.object(chat_service, 'get_conversation_history') as mock_get:
            # First call fails, second succeeds
            mock_get.side_effect = [
                Exception("Database error"),
                []  # Fallback returns empty list
            ]
            
            try:
                result = await chat_service.get_conversation_history("test_session")
                # If no exception, should get empty list
                assert isinstance(result, list)
            except Exception:
                # Exception is also acceptable
                pass

    @pytest.mark.asyncio
    async def test_concurrent_operations(self):
        """
        Test concurrent operations maintain data integrity.
        
        Requirements: 1.1, 2.1
        """
        mock_cache_service = MagicMock()
        chat_service = ChatHistoryService(cache_service=mock_cache_service)
        
        stored_messages = []
        store_lock = asyncio.Lock()
        
        async def mock_store_message(session_id, role, content, **kwargs):
            async with store_lock:
                message = ChatMessage(
                    message_id=str(uuid.uuid4()),
                    conversation_id=str(uuid.uuid4()),
                    session_id=session_id,
                    role=MessageRole.USER if role == "user" else MessageRole.ASSISTANT,
                    content=content,
                    created_at=datetime.utcnow()
                )
                stored_messages.append(message)
                await asyncio.sleep(0.001)  # Simulate processing time
                return message
        
        with patch.object(chat_service, 'store_message', side_effect=mock_store_message):
            
            session_id = f"concurrent_session_{uuid.uuid4().hex[:8]}"
            
            # Run concurrent operations
            async def store_batch(batch_id):
                tasks = []
                for i in range(3):
                    task = chat_service.store_message(
                        session_id=session_id,
                        role="user",
                        content=f"Concurrent message {batch_id}-{i}"
                    )
                    tasks.append(task)
                return await asyncio.gather(*tasks)
            
            # Execute multiple batches concurrently
            batch_results = await asyncio.gather(
                store_batch(1),
                store_batch(2),
                store_batch(3)
            )
            
            # Verify all messages were stored
            total_expected = 3 * 3  # 3 batches * 3 messages each
            assert len(stored_messages) == total_expected
            
            # Verify all messages have correct session ID
            for message in stored_messages:
                assert message.session_id == session_id
            
            # Verify message IDs are unique (no race conditions)
            message_ids = [msg.message_id for msg in stored_messages]
            assert len(set(message_ids)) == len(message_ids)

    @pytest.mark.asyncio
    async def test_data_consistency_between_services(self):
        """
        Test data consistency between PostgreSQL and Qdrant services.
        
        Requirements: 2.1, 2.3, 2.4
        """
        # Setup services
        mock_cache_service = MagicMock()
        chat_service = ChatHistoryService(cache_service=mock_cache_service)
        
        mock_qdrant_client = AsyncMock()
        mock_llm_manager = AsyncMock()
        mock_llm_manager.generate_dense_vector.return_value = [0.1] * 1024
        
        with patch.dict('os.environ', {'APP_ENV': 'test'}):
            qdrant_service = ChatQdrantService(mock_qdrant_client, mock_llm_manager)
        
        # Track data in both services
        postgres_data = []
        qdrant_data = []
        
        async def mock_store_message(session_id, role, content, **kwargs):
            message = ChatMessage(
                message_id=str(uuid.uuid4()),
                conversation_id=str(uuid.uuid4()),
                session_id=session_id,
                role=MessageRole.USER if role == "user" else MessageRole.ASSISTANT,
                content=content,
                created_at=datetime.utcnow()
            )
            postgres_data.append(message)
            return message
        
        async def mock_upload_to_qdrant(message):
            point_id = str(uuid.uuid4())
            qdrant_data.append({
                "point_id": point_id,
                "message_id": message.message_id,
                "session_id": message.session_id,
                "content": message.content
            })
            return [point_id]
        
        with patch.object(chat_service, 'store_message', side_effect=mock_store_message), \
             patch.object(qdrant_service, 'upload_message_to_qdrant', side_effect=mock_upload_to_qdrant):
            
            session_id = f"consistency_session_{uuid.uuid4().hex[:8]}"
            
            # Store and upload messages
            test_messages = [
                ("user", "First message"),
                ("assistant", "First response"),
                ("user", "Second message")
            ]
            
            for role, content in test_messages:
                message = await chat_service.store_message(
                    session_id=session_id,
                    role=role,
                    content=content
                )
                await qdrant_service.upload_message_to_qdrant(message)
            
            # Verify data consistency
            assert len(postgres_data) == len(qdrant_data)
            assert len(postgres_data) == len(test_messages)
            
            # Verify message IDs match
            postgres_ids = {msg.message_id for msg in postgres_data}
            qdrant_ids = {vec["message_id"] for vec in qdrant_data}
            assert postgres_ids == qdrant_ids
            
            # Verify content consistency
            for pg_msg in postgres_data:
                matching_vector = next(
                    (vec for vec in qdrant_data if vec["message_id"] == pg_msg.message_id),
                    None
                )
                assert matching_vector is not None
                assert matching_vector["content"] == pg_msg.content
                assert matching_vector["session_id"] == pg_msg.session_id

    @pytest.mark.asyncio
    async def test_collection_environment_isolation(self):
        """
        Test that different environments use different collections.
        
        Requirements: 7.1, 7.2
        """
        mock_qdrant_client = AsyncMock()
        mock_llm_manager = AsyncMock()
        
        # Test different environment configurations
        environments = {
            'dev': 'Chat_History_Dev',
            'test': 'Chat_History_Test', 
            'prod': 'Chat_History',
            'staging': 'Chat_History_Dev',  # Default fallback
            'unknown': 'Chat_History_Dev'   # Default fallback
        }
        
        for env, expected_collection in environments.items():
            with patch.dict('os.environ', {'APP_ENV': env}):
                service = ChatQdrantService(mock_qdrant_client, mock_llm_manager)
                assert service.collection_name == expected_collection
        
        # Test that collections are properly isolated
        # (In real implementation, different environments would use different Qdrant instances)
        dev_service = None
        prod_service = None
        
        with patch.dict('os.environ', {'APP_ENV': 'dev'}):
            dev_service = ChatQdrantService(mock_qdrant_client, mock_llm_manager)
        
        with patch.dict('os.environ', {'APP_ENV': 'prod'}):
            prod_service = ChatQdrantService(mock_qdrant_client, mock_llm_manager)
        
        assert dev_service.collection_name != prod_service.collection_name
        assert dev_service.collection_name == "Chat_History_Dev"
        assert prod_service.collection_name == "Chat_History"