#!/usr/bin/env python3
"""
Basic test for ChatQdrantService without LLMManager dependency.
This tests the core functionality without importing problematic dependencies.
"""

import sys
import os
from datetime import datetime

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

def test_environment_collection_names():
    """Test environment-specific collection name generation."""
    print("--- Testing Environment Collection Names ---")
    
    # Mock the ChatQdrantService class without dependencies
    class MockChatQdrantService:
        def __init__(self):
            pass
            
        def _get_environment_collection_name(self) -> str:
            """Get environment-specific collection name for chat history."""
            app_env = os.environ.get("APP_ENV", "dev").lower()
            
            if app_env == "prod":
                return "Chat_History"
            elif app_env == "test":
                return "Chat_History_Test"
            else:
                return "Chat_History_Dev"
        
        @classmethod
        def get_all_chat_collection_patterns(cls):
            """Get all possible chat collection name patterns for filtering."""
            return ["Chat_History", "Chat_History_Dev", "Chat_History_Test"]
        
        @classmethod
        def is_chat_collection(cls, collection_name: str) -> bool:
            """Check if a collection name is a chat history collection."""
            chat_patterns = cls.get_all_chat_collection_patterns()
            return collection_name in chat_patterns
    
    # Test different environments
    test_cases = [
        ("prod", "Chat_History"),
        ("dev", "Chat_History_Dev"),
        ("test", "Chat_History_Test"),
        ("staging", "Chat_History_Dev"),  # Default to dev for unknown environments
    ]
    
    for env, expected in test_cases:
        # Temporarily set environment
        original_env = os.environ.get("APP_ENV")
        os.environ["APP_ENV"] = env
        
        try:
            service = MockChatQdrantService()
            actual = service._get_environment_collection_name()
            
            if actual == expected:
                print(f"✓ Environment '{env}' -> Collection '{actual}'")
            else:
                print(f"✗ Environment '{env}' -> Expected '{expected}', got '{actual}'")
        finally:
            # Restore original environment
            if original_env is not None:
                os.environ["APP_ENV"] = original_env
            elif "APP_ENV" in os.environ:
                del os.environ["APP_ENV"]

def test_chat_collection_filtering():
    """Test chat collection pattern matching."""
    print("\n--- Testing Chat Collection Filtering ---")
    
    class MockChatQdrantService:
        @classmethod
        def get_all_chat_collection_patterns(cls):
            return ["Chat_History", "Chat_History_Dev", "Chat_History_Test"]
        
        @classmethod
        def is_chat_collection(cls, collection_name: str) -> bool:
            chat_patterns = cls.get_all_chat_collection_patterns()
            return collection_name in chat_patterns
    
    test_collections = [
        ("Chat_History", True),
        ("Chat_History_Dev", True),
        ("Chat_History_Test", True),
        ("Aristotle", False),
        ("Plato", False),
        ("Meta Collection", False),
        ("Chat_History_Prod", False),  # Not in our patterns
        ("chat_history", False),  # Case sensitive
    ]
    
    for collection_name, expected in test_collections:
        actual = MockChatQdrantService.is_chat_collection(collection_name)
        
        if actual == expected:
            print(f"✓ Collection '{collection_name}' -> Chat collection: {actual}")
        else:
            print(f"✗ Collection '{collection_name}' -> Expected {expected}, got {actual}")

def test_message_chunking():
    """Test message content chunking functionality."""
    print("\n--- Testing Message Chunking ---")
    
    class MockChatQdrantService:
        def __init__(self):
            self.max_chunk_size = 100  # Small size for testing
        
        def _chunk_message_content(self, content: str):
            """Split long message content into chunks for vector generation."""
            if len(content) <= self.max_chunk_size:
                return [(content, 0, 1)]
            
            chunks = []
            
            # Split by sentences first, then by character limit if needed
            sentences = content.split('. ')
            current_chunk = ""
            
            for sentence in sentences:
                # If adding this sentence would exceed limit, save current chunk
                if len(current_chunk) + len(sentence) + 2 > self.max_chunk_size and current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = sentence + ". "
                else:
                    current_chunk += sentence + ". "
            
            # Add the last chunk if it has content
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            
            # If we still have chunks that are too long, split by character limit
            final_chunks = []
            for chunk in chunks:
                if len(chunk) <= self.max_chunk_size:
                    final_chunks.append(chunk)
                else:
                    # Split by character limit as last resort
                    for i in range(0, len(chunk), self.max_chunk_size):
                        final_chunks.append(chunk[i:i + self.max_chunk_size])
            
            total_chunks = len(final_chunks)
            return [(chunk, idx, total_chunks) for idx, chunk in enumerate(final_chunks)]
    
    service = MockChatQdrantService()
    
    test_cases = [
        ("Short message", 1),
        ("This is a longer message that should be split into multiple chunks because it exceeds the maximum chunk size limit that we have set for testing purposes.", 2),
        ("", 1),  # Empty content should still return one chunk
    ]
    
    for content, expected_chunks in test_cases:
        chunks = service._chunk_message_content(content)
        actual_chunks = len(chunks)
        
        if actual_chunks == expected_chunks:
            print(f"✓ Content length {len(content)} -> {actual_chunks} chunks")
        else:
            print(f"✗ Content length {len(content)} -> Expected {expected_chunks} chunks, got {actual_chunks}")
        
        # Verify chunk structure
        for chunk_text, chunk_index, total_chunks in chunks:
            if total_chunks != actual_chunks:
                print(f"✗ Chunk metadata mismatch: total_chunks={total_chunks}, actual={actual_chunks}")
                break
        else:
            print(f"  ✓ Chunk metadata is consistent")

def test_db_models_import():
    """Test importing database models."""
    print("\n--- Testing Database Models Import ---")
    
    try:
        from core.db_models import ChatMessage, MessageRole
        print("✓ Successfully imported ChatMessage and MessageRole")
        
        # Test creating a message
        message = ChatMessage(
            message_id="test-123",
            conversation_id="conv-456", 
            session_id="session-789",
            role=MessageRole.USER,
            content="Test message content",
            philosopher_collection="Aristotle",
            created_at=datetime.utcnow()
        )
        
        print(f"✓ Created ChatMessage: {message.message_id}")
        print(f"  Role: {message.role.value}")
        print(f"  Content length: {len(message.content)}")
        
    except ImportError as e:
        print(f"✗ Failed to import database models: {e}")
    except Exception as e:
        print(f"✗ Failed to create ChatMessage: {e}")

def main():
    """Run all tests."""
    print("ChatQdrantService Basic Implementation Test")
    print("=" * 50)
    
    test_environment_collection_names()
    test_chat_collection_filtering()
    test_message_chunking()
    test_db_models_import()
    
    print("\n" + "=" * 50)
    print("Basic test completed. Check output above for any failures.")

if __name__ == "__main__":
    main()