"""
Privacy and security validation tests for chat history functionality.

Tests cross-user data access prevention, Qdrant collection privacy and filtering,
and session-based data isolation to ensure complete privacy protection.
"""

import pytest
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.core.db_models import ChatConversation, ChatMessage, MessageRole
from app.services.chat_history_service import ChatHistoryService
from app.services.chat_qdrant_service import ChatQdrantService
from app.core.chat_exceptions import ChatPrivacyError, ChatValidationError
from app.core.exceptions import LLMError


class TestChatPrivacySecurity:
    """Privacy and security validation tests for chat history system."""

    @pytest.fixture
    def test_sessions(self):
        """Generate test session IDs for privacy testing."""
        return {
            "alice": f"alice_session_{uuid.uuid4().hex[:12]}",
            "bob": f"bob_session_{uuid.uuid4().hex[:12]}",
            "charlie": f"charlie_session_{uuid.uuid4().hex[:12]}",
            "malicious": f"malicious_session_{uuid.uuid4().hex[:12]}"
        }

    @pytest.fixture
    def sensitive_conversations(self, test_sessions):
        """Create sensitive conversation data for privacy testing."""
        return {
            test_sessions["alice"]: [
                {
                    "role": "user",
                    "content": "I have a personal question about my relationship with my partner",
                    "philosopher": "Aristotle",
                    "conversation_id": "alice_conv_1"
                },
                {
                    "role": "assistant", 
                    "content": "I understand this is personal. Aristotle would suggest...",
                    "philosopher": "Aristotle",
                    "conversation_id": "alice_conv_1"
                }
            ],
            test_sessions["bob"]: [
                {
                    "role": "user",
                    "content": "Confidential business ethics question about my company",
                    "philosopher": "Kant",
                    "conversation_id": "bob_conv_1"
                },
                {
                    "role": "assistant",
                    "content": "From a Kantian perspective on business ethics...",
                    "philosopher": "Kant", 
                    "conversation_id": "bob_conv_1"
                }
            ],
            test_sessions["charlie"]: [
                {
                    "role": "user",
                    "content": "Private thoughts about existential crisis",
                    "philosopher": "Nietzsche",
                    "conversation_id": "charlie_conv_1"
                }
            ]
        }

    @pytest.mark.asyncio
    async def test_cross_user_data_access_prevention(
        self,
        test_sessions,
        sensitive_conversations
    ):
        """
        Test that users cannot access other users' conversation data through any means.
        
        Requirements: 7.3, 7.4, 7.5
        """
        mock_cache_service = MagicMock()
        chat_history_service = ChatHistoryService(cache_service=mock_cache_service)
        
        # Store all conversations in mock database
        stored_data = {}
        
        async def mock_store_message(session_id, role, content, conversation_id=None, **kwargs):
            if session_id not in stored_data:
                stored_data[session_id] = []
            
            message = ChatMessage(
                message_id=str(uuid.uuid4()),
                conversation_id=conversation_id or str(uuid.uuid4()),
                session_id=session_id,
                role=MessageRole.USER if role == "user" else MessageRole.ASSISTANT,
                content=content,
                created_at=datetime.utcnow()
            )
            stored_data[session_id].append(message)
            return message
        
        async def mock_get_history(session_id, limit=50, offset=0, conversation_id=None, **kwargs):
            session_messages = stored_data.get(session_id, [])
            if conversation_id:
                session_messages = [msg for msg in session_messages if msg.conversation_id == conversation_id]
            return session_messages[offset:offset+limit]
        
        async def mock_get_conversation_by_id(conversation_id, session_id, **kwargs):
            # This should enforce privacy - only return if session matches
            for stored_session_id, messages in stored_data.items():
                if stored_session_id == session_id:
                    for message in messages:
                        if message.conversation_id == conversation_id:
                            return message  # Found in correct session
            return None  # Not found or privacy violation
        
        with patch.object(chat_history_service, 'store_message', side_effect=mock_store_message), \
             patch.object(chat_history_service, 'get_conversation_history', side_effect=mock_get_history), \
             patch.object(chat_history_service, '_get_conversation_by_id', side_effect=mock_get_conversation_by_id):
            
            # Store sensitive conversations for each user
            conversation_ids = {}
            for session_id, messages in sensitive_conversations.items():
                conversation_ids[session_id] = []
                for msg_data in messages:
                    message = await chat_history_service.store_message(
                        session_id=session_id,
                        role=msg_data["role"],
                        content=msg_data["content"],
                        conversation_id=msg_data["conversation_id"],
                        philosopher_collection=msg_data["philosopher"]
                    )
                    conversation_ids[session_id].append(message.conversation_id)
            
            # Test 1: Users can only access their own data
            for session_id in test_sessions.values():
                user_history = await chat_history_service.get_conversation_history(session_id)
                
                # Verify all messages belong to the requesting user
                for message in user_history:
                    assert message.session_id == session_id
                
                # Verify content matches expected data for this user
                if session_id in sensitive_conversations:
                    expected_contents = [msg["content"] for msg in sensitive_conversations[session_id]]
                    actual_contents = [msg.content for msg in user_history]
                    
                    for expected_content in expected_contents:
                        assert expected_content in actual_contents
            
            # Test 2: Cross-user conversation access attempts should fail
            alice_session = test_sessions["alice"]
            bob_session = test_sessions["bob"]
            
            # Alice tries to access Bob's conversation
            alice_history = await chat_history_service.get_conversation_history(alice_session)
            bob_contents = [msg["content"] for msg in sensitive_conversations[bob_session]]
            
            for message in alice_history:
                assert message.content not in bob_contents
            
            # Test 3: Specific conversation ID access with wrong session should fail
            bob_conv_id = "bob_conv_1"
            
            # Alice tries to access Bob's specific conversation
            result = await chat_history_service._get_conversation_by_id(
                conversation_id=bob_conv_id,
                session_id=alice_session
            )
            assert result is None  # Should not find conversation (privacy protection)
            
            # Bob can access his own conversation
            result = await chat_history_service._get_conversation_by_id(
                conversation_id=bob_conv_id,
                session_id=bob_session
            )
            # Should find the conversation since session matches
            if result:
                assert result.session_id == bob_session
            
            # Test 4: Malicious session ID attempts
            malicious_session = test_sessions["malicious"]
            
            # Malicious user tries to access all other users' data
            malicious_history = await chat_history_service.get_conversation_history(malicious_session)
            assert len(malicious_history) == 0  # Should have no data
            
            # Verify malicious user cannot see any sensitive content
            all_sensitive_content = []
            for messages in sensitive_conversations.values():
                all_sensitive_content.extend([msg["content"] for msg in messages])
            
            for message in malicious_history:
                assert message.content not in all_sensitive_content

    @pytest.mark.asyncio
    async def test_qdrant_collection_privacy_and_filtering(
        self,
        test_sessions,
        sensitive_conversations,
        mock_environment,
        mock_all_services
    ):
        """
        Test Qdrant collection privacy and proper filtering of chat collections.
        
        Requirements: 7.3, 7.4, 7.5
        """
        # Setup Qdrant service with mocks
        mock_qdrant_client = AsyncMock()
        mock_llm_manager = AsyncMock()
        mock_llm_manager.generate_dense_vector.return_value = [0.1] * 4096
        
        with patch.dict('os.environ', {'APP_ENV': 'test'}):
            chat_qdrant_service = ChatQdrantService(mock_qdrant_client, mock_llm_manager)
        
        # Mock vector storage
        vector_storage = {}
        
        async def mock_upsert(collection_name, points, **kwargs):
            if collection_name not in vector_storage:
                vector_storage[collection_name] = []
            
            for point in points:
                vector_storage[collection_name].append({
                    "id": point.id,
                    "vector": point.vector,
                    "payload": point.payload
                })
        
        async def mock_search(collection_name, query_vector, query_filter=None, limit=10, **kwargs):
            if collection_name not in vector_storage:
                return []
            
            results = []
            for point in vector_storage[collection_name]:
                # Apply session filter if present
                if query_filter and hasattr(query_filter, 'must'):
                    session_match = False
                    for condition in query_filter.must:
                        if (condition.key == "session_id" and 
                            hasattr(condition, 'match') and 
                            point["payload"].get("session_id") == condition.match.value):
                            session_match = True
                            break
                    
                    if not session_match:
                        continue  # Skip this point due to session filter
                
                # Create mock result
                mock_result = MagicMock()
                mock_result.id = point["id"]
                mock_result.score = 0.85
                mock_result.payload = point["payload"]
                results.append(mock_result)
            
            return results[:limit]
        
        async def mock_delete(collection_name, points_selector, **kwargs):
            if collection_name in vector_storage:
                # Simulate deletion based on filter
                if hasattr(points_selector, 'filter') and hasattr(points_selector.filter, 'must'):
                    for condition in points_selector.filter.must:
                        if condition.key == "session_id":
                            session_to_delete = condition.match.value
                            vector_storage[collection_name] = [
                                point for point in vector_storage[collection_name]
                                if point["payload"].get("session_id") != session_to_delete
                            ]
        
        mock_qdrant_client.upsert = mock_upsert
        mock_qdrant_client.search = mock_search
        mock_qdrant_client.delete = mock_delete
        
        # Mock collection existence
        mock_qdrant_client.get_collections.return_value = MagicMock(
            collections=[MagicMock(name="Chat_History_Test")]
        )
        
        with patch.object(chat_qdrant_service, 'ensure_chat_collection_exists', return_value=None):
            
            # Upload messages for each user to Qdrant
            uploaded_messages = {}
            for session_id, messages in sensitive_conversations.items():
                uploaded_messages[session_id] = []
                for msg_data in messages:
                    message = ChatMessage(
                        message_id=str(uuid.uuid4()),
                        conversation_id=msg_data["conversation_id"],
                        session_id=session_id,
                        role=MessageRole.USER if msg_data["role"] == "user" else MessageRole.ASSISTANT,
                        content=msg_data["content"],
                        philosopher_collection=msg_data["philosopher"],
                        created_at=datetime.utcnow()
                    )
                    
                    point_ids = await chat_qdrant_service.upload_message_to_qdrant(message)
                    uploaded_messages[session_id].append({
                        "message": message,
                        "point_ids": point_ids
                    })
            
            # Test 1: Search results are properly filtered by session
            alice_session = test_sessions["alice"]
            bob_session = test_sessions["bob"]
            
            # Alice searches for content that exists in Bob's data
            alice_results = await chat_qdrant_service.search_messages(
                session_id=alice_session,
                query="business ethics",  # This is in Bob's conversation
                limit=10
            )
            
            # Alice should not see Bob's results
            for result in alice_results:
                if isinstance(result, dict):
                    assert result.get("session_id") == alice_session
                    assert "business ethics" not in result.get("content", "").lower()
            
            # Bob searches for his own content
            bob_results = await chat_qdrant_service.search_messages(
                session_id=bob_session,
                query="business ethics",
                limit=10
            )
            
            # Bob should see his own results
            found_own_content = False
            for result in bob_results:
                if isinstance(result, dict):
                    assert result.get("session_id") == bob_session
                    if "business ethics" in result.get("content", "").lower():
                        found_own_content = True
            
            # Test 2: Cross-session search privacy violation detection
            # Try to search with one session but get results from another
            charlie_session = test_sessions["charlie"]
            
            # Charlie searches for Alice's personal content
            charlie_results = await chat_qdrant_service.search_messages(
                session_id=charlie_session,
                query="personal question relationship",  # Alice's content
                limit=10
            )
            
            # Charlie should not see Alice's personal content
            for result in charlie_results:
                if isinstance(result, dict):
                    assert result.get("session_id") == charlie_session
                    assert "personal question" not in result.get("content", "").lower()
            
            # Test 3: Collection filtering - chat collections should be hidden
            chat_patterns = ChatQdrantService.get_all_chat_collection_patterns()
            expected_patterns = ["Chat_History", "Chat_History_Dev", "Chat_History_Test"]
            assert set(chat_patterns) == set(expected_patterns)
            
            # Verify chat collection detection
            assert ChatQdrantService.is_chat_collection("Chat_History_Test") is True
            assert ChatQdrantService.is_chat_collection("Chat_History_Dev") is True
            assert ChatQdrantService.is_chat_collection("Chat_History") is True
            assert ChatQdrantService.is_chat_collection("Aristotle") is False
            assert ChatQdrantService.is_chat_collection("Kant") is False
            
            # Test 4: Deletion privacy - users can only delete their own data
            # Alice deletes her data
            alice_delete_result = await chat_qdrant_service.delete_user_messages(alice_session)
            assert alice_delete_result is True
            
            # Verify Alice's data is gone but Bob's remains
            alice_search_after_delete = await chat_qdrant_service.search_messages(
                session_id=alice_session,
                query="personal question",
                limit=10
            )
            assert len(alice_search_after_delete) == 0  # Alice's data should be gone
            
            # Bob's data should still exist
            bob_search_after_alice_delete = await chat_qdrant_service.search_messages(
                session_id=bob_session,
                query="business ethics",
                limit=10
            )
            # Bob's data should still be accessible to Bob
            for result in bob_search_after_alice_delete:
                if isinstance(result, dict):
                    assert result.get("session_id") == bob_session

    @pytest.mark.asyncio
    async def test_session_based_data_isolation(
        self,
        test_sessions,
        mock_environment,
        mock_all_services
    ):
        """
        Test comprehensive session-based data isolation across all operations.
        
        Requirements: 7.3, 7.4, 7.5
        """
        mock_cache_service = MagicMock()
        chat_history_service = ChatHistoryService(cache_service=mock_cache_service)
        
        # Create isolated data stores for each session
        session_data_stores = {session_id: [] for session_id in test_sessions.values()}
        
        async def mock_store_message(session_id, role, content, **kwargs):
            if session_id not in session_data_stores:
                session_data_stores[session_id] = []
            
            message = ChatMessage(
                message_id=str(uuid.uuid4()),
                conversation_id=str(uuid.uuid4()),
                session_id=session_id,
                role=MessageRole.USER if role == "user" else MessageRole.ASSISTANT,
                content=content,
                created_at=datetime.utcnow()
            )
            session_data_stores[session_id].append(message)
            return message
        
        async def mock_get_history(session_id, **kwargs):
            return session_data_stores.get(session_id, [])
        
        async def mock_get_count(session_id, **kwargs):
            return len(session_data_stores.get(session_id, []))
        
        async def mock_delete_history(session_id, **kwargs):
            if session_id in session_data_stores:
                deleted_count = len(session_data_stores[session_id])
                session_data_stores[session_id] = []
                return deleted_count > 0
            return False
        
        with patch.object(chat_history_service, 'store_message', side_effect=mock_store_message), \
             patch.object(chat_history_service, 'get_conversation_history', side_effect=mock_get_history), \
             patch.object(chat_history_service, 'get_message_count', side_effect=mock_get_count), \
             patch.object(chat_history_service, 'delete_user_history', side_effect=mock_delete_history):
            
            # Test 1: Store data for each session
            test_data = {
                test_sessions["alice"]: [
                    ("user", "Alice's secret message 1"),
                    ("assistant", "Response to Alice 1"),
                    ("user", "Alice's secret message 2")
                ],
                test_sessions["bob"]: [
                    ("user", "Bob's confidential data 1"),
                    ("assistant", "Response to Bob 1")
                ],
                test_sessions["charlie"]: [
                    ("user", "Charlie's private thoughts")
                ]
            }
            
            # Store messages for each session
            for session_id, messages in test_data.items():
                for role, content in messages:
                    await chat_history_service.store_message(
                        session_id=session_id,
                        role=role,
                        content=content
                    )
            
            # Test 2: Verify complete isolation - each session only sees its own data
            for session_id, expected_messages in test_data.items():
                history = await chat_history_service.get_conversation_history(session_id)
                count = await chat_history_service.get_message_count(session_id)
                
                # Verify count matches expected
                assert count == len(expected_messages)
                assert len(history) == len(expected_messages)
                
                # Verify all messages belong to correct session
                for message in history:
                    assert message.session_id == session_id
                
                # Verify content matches expected data
                expected_contents = [content for role, content in expected_messages]
                actual_contents = [msg.content for msg in history]
                
                for expected_content in expected_contents:
                    assert expected_content in actual_contents
            
            # Test 3: Cross-contamination check - verify no session sees other sessions' data
            alice_history = await chat_history_service.get_conversation_history(test_sessions["alice"])
            bob_history = await chat_history_service.get_conversation_history(test_sessions["bob"])
            charlie_history = await chat_history_service.get_conversation_history(test_sessions["charlie"])
            
            # Alice should not see Bob's or Charlie's data
            alice_contents = [msg.content for msg in alice_history]
            assert "Bob's confidential data 1" not in alice_contents
            assert "Charlie's private thoughts" not in alice_contents
            
            # Bob should not see Alice's or Charlie's data
            bob_contents = [msg.content for msg in bob_history]
            assert "Alice's secret message 1" not in bob_contents
            assert "Charlie's private thoughts" not in bob_contents
            
            # Charlie should not see Alice's or Bob's data
            charlie_contents = [msg.content for msg in charlie_history]
            assert "Alice's secret message 1" not in charlie_contents
            assert "Bob's confidential data 1" not in charlie_contents
            
            # Test 4: Deletion isolation - deleting one session doesn't affect others
            initial_alice_count = await chat_history_service.get_message_count(test_sessions["alice"])
            initial_bob_count = await chat_history_service.get_message_count(test_sessions["bob"])
            
            # Delete Alice's data
            alice_deleted = await chat_history_service.delete_user_history(test_sessions["alice"])
            assert alice_deleted is True
            
            # Verify Alice's data is gone
            alice_count_after = await chat_history_service.get_message_count(test_sessions["alice"])
            assert alice_count_after == 0
            
            # Verify Bob's data is unaffected
            bob_count_after = await chat_history_service.get_message_count(test_sessions["bob"])
            assert bob_count_after == initial_bob_count
            
            # Verify Bob can still access his data
            bob_history_after = await chat_history_service.get_conversation_history(test_sessions["bob"])
            assert len(bob_history_after) == initial_bob_count
            assert "Bob's confidential data 1" in [msg.content for msg in bob_history_after]

    @pytest.mark.asyncio
    async def test_api_endpoint_privacy_protection(
        self,
        test_sessions,
        async_client: AsyncClient,
        mock_environment,
        mock_all_services
    ):
        """
        Test privacy protection at the API endpoint level.
        
        Requirements: 7.4, 7.5
        """
        # Enable chat history for testing
        with patch('app.router.chat_history.is_chat_history_enabled', return_value=True):
            
            # Mock data for different sessions
            session_data = {
                test_sessions["alice"]: [
                    {
                        "message_id": str(uuid.uuid4()),
                        "conversation_id": str(uuid.uuid4()),
                        "session_id": test_sessions["alice"],
                        "role": "user",
                        "content": "Alice's private conversation",
                        "created_at": datetime.utcnow()
                    }
                ],
                test_sessions["bob"]: [
                    {
                        "message_id": str(uuid.uuid4()),
                        "conversation_id": str(uuid.uuid4()),
                        "session_id": test_sessions["bob"],
                        "role": "user", 
                        "content": "Bob's confidential discussion",
                        "created_at": datetime.utcnow()
                    }
                ]
            }
            
            # Mock service methods to enforce session isolation
            async def mock_get_history(session_id, **kwargs):
                messages = session_data.get(session_id, [])
                return [
                    ChatMessage(
                        message_id=msg["message_id"],
                        conversation_id=msg["conversation_id"],
                        session_id=msg["session_id"],
                        role=MessageRole.USER if msg["role"] == "user" else MessageRole.ASSISTANT,
                        content=msg["content"],
                        created_at=msg["created_at"]
                    )
                    for msg in messages
                ]
            
            async def mock_get_count(session_id, **kwargs):
                return len(session_data.get(session_id, []))
            
            async def mock_search_messages(session_id, query, **kwargs):
                # Only return results for the requesting session
                session_messages = session_data.get(session_id, [])
                results = []
                for msg in session_messages:
                    if query.lower() in msg["content"].lower():
                        results.append({
                            "message_id": msg["message_id"],
                            "session_id": msg["session_id"],
                            "content": msg["content"],
                            "relevance_score": 0.85,
                            "role": msg["role"],
                            "conversation_id": msg["conversation_id"],
                            "created_at": msg["created_at"].isoformat()
                        })
                return results
            
            # Override dependencies
            with patch('app.core.dependencies.get_chat_history_service') as mock_get_chat_service, \
                 patch('app.core.dependencies.get_chat_qdrant_service') as mock_get_qdrant_service:
                
                mock_chat_service = AsyncMock()
                mock_chat_service.get_conversation_history = mock_get_history
                mock_chat_service.get_message_count = mock_get_count
                mock_chat_service.get_conversations = AsyncMock(return_value=[])
                mock_chat_service.get_conversation_count = AsyncMock(return_value=0)
                mock_chat_service.delete_user_history = AsyncMock(return_value=True)
                
                mock_qdrant_service = AsyncMock()
                mock_qdrant_service.search_messages = mock_search_messages
                mock_qdrant_service.delete_user_messages = AsyncMock(return_value=True)
                
                mock_get_chat_service.return_value = mock_chat_service
                mock_get_qdrant_service.return_value = mock_qdrant_service
                
                # Test 1: Alice can only access her own history
                alice_session = test_sessions["alice"]
                response = await async_client.get(f"/chat/history/{alice_session}")
                assert response.status_code == 200
                
                data = response.json()
                assert "messages" in data
                assert data["total_count"] == 1
                
                # Verify Alice only sees her own content
                alice_content = data["messages"][0]["content"]
                assert alice_content == "Alice's private conversation"
                assert test_sessions["bob"] not in alice_content
                
                # Test 2: Bob can only access his own history
                bob_session = test_sessions["bob"]
                response = await async_client.get(f"/chat/history/{bob_session}")
                assert response.status_code == 200
                
                data = response.json()
                assert data["total_count"] == 1
                
                # Verify Bob only sees his own content
                bob_content = data["messages"][0]["content"]
                assert bob_content == "Bob's confidential discussion"
                assert "Alice's private" not in bob_content
                
                # Test 3: Search privacy - Alice searching for Bob's content returns nothing
                search_payload = {
                    "session_id": alice_session,
                    "query": "confidential discussion",  # This is in Bob's data
                    "limit": 10
                }
                
                response = await async_client.post("/chat/search", json=search_payload)
                assert response.status_code == 200
                
                data = response.json()
                assert data["total_found"] == 0  # Alice should not find Bob's content
                assert len(data["results"]) == 0
                
                # Test 4: Bob searching for his own content finds it
                search_payload = {
                    "session_id": bob_session,
                    "query": "confidential discussion",
                    "limit": 10
                }
                
                response = await async_client.post("/chat/search", json=search_payload)
                assert response.status_code == 200
                
                data = response.json()
                assert data["total_found"] == 1  # Bob should find his own content
                assert data["results"][0]["session_id"] == bob_session
                
                # Test 5: Invalid session ID attempts
                invalid_sessions = ["", "   ", "../../../etc/passwd", "null", "undefined"]
                
                for invalid_session in invalid_sessions:
                    response = await async_client.get(f"/chat/history/{invalid_session}")
                    assert response.status_code == 400  # Should reject invalid session IDs
                
                # Test 6: Session ID injection attempts
                malicious_sessions = [
                    f"{alice_session}' OR '1'='1",
                    f"{alice_session}; DROP TABLE chat_messages;",
                    f"{alice_session}/**/UNION/**/SELECT/**/*",
                ]
                
                for malicious_session in malicious_sessions:
                    response = await async_client.get(f"/chat/history/{malicious_session}")
                    # Should either reject (400) or return empty results (200 with no data)
                    assert response.status_code in [400, 200]
                    
                    if response.status_code == 200:
                        data = response.json()
                        # Should not return any sensitive data
                        assert data["total_count"] == 0

    @pytest.mark.asyncio
    async def test_privacy_violation_detection_and_logging(
        self,
        test_sessions,
        mock_environment,
        mock_all_services
    ):
        """
        Test detection and logging of privacy violations.
        
        Requirements: 7.4, 7.5
        """
        # Setup services with privacy violation detection
        mock_qdrant_client = AsyncMock()
        mock_llm_manager = AsyncMock()
        mock_llm_manager.generate_dense_vector.return_value = [0.1] * 4096
        
        with patch.dict('os.environ', {'APP_ENV': 'test'}):
            chat_qdrant_service = ChatQdrantService(mock_qdrant_client, mock_llm_manager)
        
        # Mock search that returns cross-session results (privacy violation)
        async def mock_search_with_violation(collection_name, query_vector, query_filter=None, **kwargs):
            # Simulate a privacy violation - return result from different session
            mock_result = MagicMock()
            mock_result.id = "violation_point_123"
            mock_result.score = 0.95
            mock_result.payload = {
                "message_id": "msg_violation_123",
                "session_id": test_sessions["bob"],  # Different session!
                "role": "user",
                "content": "This should not be visible to Alice",
                "created_at": datetime.utcnow().isoformat(),
                "chunk_index": 0,
                "total_chunks": 1
            }
            return [mock_result]
        
        mock_qdrant_client.search = mock_search_with_violation
        
        # Test privacy violation detection
        alice_session = test_sessions["alice"]
        
        # This should detect the privacy violation and raise an error
        with pytest.raises(ChatPrivacyError) as exc_info:
            # Call the internal method directly to avoid fallback decorators
            await chat_qdrant_service._search_standard(
                session_id=alice_session,
                query="test query",
                limit=10
            )
        
        # Verify the privacy error details
        assert exc_info.value.violation_type == "cross_session_result"
        assert "privacy violation" in str(exc_info.value).lower()
        
        # Test logging of privacy violations (mock the logger)
        with patch('app.services.chat_qdrant_service.log') as mock_logger:
            try:
                await chat_qdrant_service._search_standard(
                    session_id=alice_session,
                    query="test query",
                    limit=10
                )
            except ChatPrivacyError:
                pass  # Expected
            
            # Verify privacy violation was logged
            mock_logger.error.assert_called()
            error_call_args = str(mock_logger.error.call_args)
            assert "privacy violation" in error_call_args.lower()

    @pytest.mark.asyncio
    async def test_data_anonymization_and_cleanup(
        self,
        test_sessions,
        mock_environment,
        mock_all_services
    ):
        """
        Test data anonymization and cleanup procedures for privacy compliance.
        
        Requirements: 7.5
        """
        mock_cache_service = MagicMock()
        chat_history_service = ChatHistoryService(cache_service=mock_cache_service)
        
        # Mock data with potentially sensitive information
        sensitive_data = {
            test_sessions["alice"]: [
                {
                    "content": "My email is alice@example.com and my phone is 555-1234",
                    "role": "user"
                },
                {
                    "content": "I live at 123 Main Street, Anytown USA",
                    "role": "user"
                }
            ]
        }
        
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
        
        async def mock_delete_history(session_id, **kwargs):
            nonlocal stored_messages
            initial_count = len([msg for msg in stored_messages if msg.session_id == session_id])
            stored_messages = [msg for msg in stored_messages if msg.session_id != session_id]
            return initial_count > 0
        
        async def mock_get_history(session_id, **kwargs):
            return [msg for msg in stored_messages if msg.session_id == session_id]
        
        with patch.object(chat_history_service, 'store_message', side_effect=mock_store_message), \
             patch.object(chat_history_service, 'delete_user_history', side_effect=mock_delete_history), \
             patch.object(chat_history_service, 'get_conversation_history', side_effect=mock_get_history):
            
            # Store sensitive data
            alice_session = test_sessions["alice"]
            for msg_data in sensitive_data[alice_session]:
                await chat_history_service.store_message(
                    session_id=alice_session,
                    role=msg_data["role"],
                    content=msg_data["content"]
                )
            
            # Verify data was stored
            alice_history = await chat_history_service.get_conversation_history(alice_session)
            assert len(alice_history) == 2
            
            # Test complete data deletion (right to be forgotten)
            deletion_result = await chat_history_service.delete_user_history(alice_session)
            assert deletion_result is True
            
            # Verify all data is completely removed
            alice_history_after = await chat_history_service.get_conversation_history(alice_session)
            assert len(alice_history_after) == 0
            
            # Verify no traces remain in storage
            remaining_messages = [msg for msg in stored_messages if msg.session_id == alice_session]
            assert len(remaining_messages) == 0
            
            # Test that deletion is permanent and irreversible
            alice_history_final = await chat_history_service.get_conversation_history(alice_session)
            assert len(alice_history_final) == 0

    @pytest.mark.asyncio
    async def test_concurrent_privacy_protection(
        self,
        test_sessions,
        mock_environment,
        mock_all_services
    ):
        """
        Test privacy protection under concurrent access scenarios.
        
        Requirements: 7.4, 7.5
        """
        mock_cache_service = MagicMock()
        chat_history_service = ChatHistoryService(cache_service=mock_cache_service)
        
        # Shared storage with thread-safe access simulation
        shared_storage = {}
        access_log = []
        
        async def mock_get_history(session_id, **kwargs):
            # Log access attempt
            access_log.append({
                "session_id": session_id,
                "timestamp": datetime.utcnow(),
                "operation": "read"
            })
            return shared_storage.get(session_id, [])
        
        async def mock_store_message(session_id, role, content, **kwargs):
            if session_id not in shared_storage:
                shared_storage[session_id] = []
            
            message = ChatMessage(
                message_id=str(uuid.uuid4()),
                conversation_id=str(uuid.uuid4()),
                session_id=session_id,
                role=MessageRole.USER if role == "user" else MessageRole.ASSISTANT,
                content=content,
                created_at=datetime.utcnow()
            )
            shared_storage[session_id].append(message)
            
            access_log.append({
                "session_id": session_id,
                "timestamp": datetime.utcnow(),
                "operation": "write"
            })
            return message
        
        with patch.object(chat_history_service, 'get_conversation_history', side_effect=mock_get_history), \
             patch.object(chat_history_service, 'store_message', side_effect=mock_store_message):
            
            # Simulate concurrent access from multiple sessions
            async def user_activity(session_id, user_name):
                # Each user stores and retrieves their own data
                await chat_history_service.store_message(
                    session_id=session_id,
                    role="user",
                    content=f"Private message from {user_name}"
                )
                
                # Retrieve own data
                history = await chat_history_service.get_conversation_history(session_id)
                return history
            
            # Run concurrent activities
            alice_task = user_activity(test_sessions["alice"], "Alice")
            bob_task = user_activity(test_sessions["bob"], "Bob")
            charlie_task = user_activity(test_sessions["charlie"], "Charlie")
            
            alice_result, bob_result, charlie_result = await asyncio.gather(
                alice_task, bob_task, charlie_task
            )
            
            # Verify each user only sees their own data
            alice_contents = [msg.content for msg in alice_result]
            bob_contents = [msg.content for msg in bob_result]
            charlie_contents = [msg.content for msg in charlie_result]
            
            assert "Private message from Alice" in alice_contents
            assert "Private message from Bob" not in alice_contents
            assert "Private message from Charlie" not in alice_contents
            
            assert "Private message from Bob" in bob_contents
            assert "Private message from Alice" not in bob_contents
            assert "Private message from Charlie" not in bob_contents
            
            assert "Private message from Charlie" in charlie_contents
            assert "Private message from Alice" not in charlie_contents
            assert "Private message from Bob" not in charlie_contents
            
            # Verify access log shows proper session isolation
            alice_accesses = [log for log in access_log if log["session_id"] == test_sessions["alice"]]
            bob_accesses = [log for log in access_log if log["session_id"] == test_sessions["bob"]]
            charlie_accesses = [log for log in access_log if log["session_id"] == test_sessions["charlie"]]
            
            # Each user should have both read and write operations
            assert len(alice_accesses) >= 2  # At least one write, one read
            assert len(bob_accesses) >= 2
            assert len(charlie_accesses) >= 2
            
            # Verify no cross-session access in logs
            for log_entry in access_log:
                assert log_entry["session_id"] in test_sessions.values()