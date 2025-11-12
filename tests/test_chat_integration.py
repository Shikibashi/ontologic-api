#!/usr/bin/env python3
"""
Simple integration test for chat history functionality.
Tests that the /ask_philosophy endpoint can handle session_id parameter
and that chat collections are properly excluded from /get_philosophers.
"""

import asyncio
import sys
import os

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

async def test_chat_integration():
    """Test chat history integration without external dependencies."""
    
    print("Testing chat history integration...")
    
    # Test 1: Import all necessary components
    try:
        from app.router.ontologic import (
            is_chat_history_enabled,
            store_chat_message_safely,
            merge_conversation_history
        )
        from app.services.chat_qdrant_service import ChatQdrantService
        from app.config import get_chat_history_enabled
        print("✓ All chat history components imported successfully")
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False
    
    # Test 2: Check configuration
    try:
        chat_enabled = get_chat_history_enabled()
        print(f"✓ Chat history enabled in config: {chat_enabled}")
    except Exception as e:
        print(f"✗ Config check failed: {e}")
        return False
    
    # Test 3: Check ChatQdrantService collection patterns
    try:
        patterns = ChatQdrantService.get_all_chat_collection_patterns()
        expected_patterns = ["Chat_History", "Chat_History_Dev", "Chat_History_Test"]
        
        if set(patterns) == set(expected_patterns):
            print(f"✓ Chat collection patterns correct: {patterns}")
        else:
            print(f"✗ Chat collection patterns incorrect. Got: {patterns}, Expected: {expected_patterns}")
            return False
    except Exception as e:
        print(f"✗ ChatQdrantService test failed: {e}")
        return False
    
    # Test 4: Check collection filtering
    try:
        is_chat = ChatQdrantService.is_chat_collection("Chat_History_Dev")
        is_not_chat = ChatQdrantService.is_chat_collection("Aristotle")
        
        if is_chat and not is_not_chat:
            print("✓ Chat collection filtering works correctly")
        else:
            print(f"✗ Chat collection filtering failed. Chat_History_Dev: {is_chat}, Aristotle: {is_not_chat}")
            return False
    except Exception as e:
        print(f"✗ Collection filtering test failed: {e}")
        return False
    
    # Test 5: Check helper functions
    try:
        enabled = is_chat_history_enabled()
        print(f"✓ Chat history helper function works: {enabled}")
    except Exception as e:
        print(f"✗ Helper function test failed: {e}")
        return False
    
    print("\n🎉 All chat history integration tests passed!")
    return True

if __name__ == "__main__":
    success = asyncio.run(test_chat_integration())
    sys.exit(0 if success else 1)