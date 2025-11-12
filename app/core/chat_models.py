"""
Pydantic models for chat history API endpoints.

This module defines request and response models for chat history operations
including conversation retrieval, search, and management.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from app.core.db_models import MessageRole


class ChatMessageResponse(BaseModel):
    """Response model for individual chat messages."""

    message_id: str = Field(description="Unique message identifier")
    conversation_id: str = Field(description="Conversation identifier")
    session_id: str = Field(description="Session identifier")
    username: Optional[str] = Field(default=None, description="User identifier for multi-user support")
    role: str = Field(description="Message role (user or assistant)")
    content: str = Field(description="Message content")
    philosopher_collection: Optional[str] = Field(default=None, description="Associated philosopher collection")
    created_at: datetime = Field(description="Message creation timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "message_id": "550e8400-e29b-41d4-a716-446655440000",
                "conversation_id": "550e8400-e29b-41d4-a716-446655440001",
                "session_id": "user_session_123",
                "username": "alice@example.com",
                "role": "user",
                "content": "What is virtue ethics according to Aristotle?",
                "philosopher_collection": "Aristotle",
                "created_at": "2024-01-15T10:30:00Z"
            }
        }


class ChatHistoryResponse(BaseModel):
    """Response model for paginated chat history."""
    
    messages: List[ChatMessageResponse] = Field(description="List of chat messages")
    total_count: int = Field(description="Total number of messages in the session")
    has_more: bool = Field(description="Whether there are more messages available")
    offset: int = Field(description="Current offset in pagination")
    limit: int = Field(description="Current limit per page")
    
    class Config:
        json_schema_extra = {
            "example": {
                "messages": [
                    {
                        "message_id": "550e8400-e29b-41d4-a716-446655440000",
                        "conversation_id": "550e8400-e29b-41d4-a716-446655440001",
                        "session_id": "user_session_123",
                        "role": "user",
                        "content": "What is virtue ethics?",
                        "philosopher_collection": "Aristotle",
                        "created_at": "2024-01-15T10:30:00Z"
                    }
                ],
                "total_count": 25,
                "has_more": True,
                "offset": 0,
                "limit": 20
            }
        }


class ChatSearchRequest(BaseModel):
    """Request model for searching chat history."""

    session_id: str = Field(description="Session ID to search within")
    query: str = Field(description="Search query text", min_length=1)
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of results to return")
    philosopher_filter: Optional[str] = Field(default=None, description="Optional philosopher collection filter")
    username: Optional[str] = Field(default=None, description="Optional username for user-specific filtering")
    include_pdf_context: bool = Field(default=False, description="If true and username provided, include relevant document context")

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "user_session_123",
                "query": "virtue ethics",
                "limit": 10,
                "philosopher_filter": "Aristotle",
                "username": "alice@example.com",
                "include_pdf_context": True
            }
        }


class ChatSearchResultItem(BaseModel):
    """Individual search result item with relevance scoring."""

    message_id: str = Field(description="Message identifier")
    conversation_id: str = Field(description="Conversation identifier")
    session_id: str = Field(description="Session identifier")
    username: Optional[str] = Field(default=None, description="User identifier")
    role: str = Field(description="Message role")
    content: str = Field(description="Message content")
    philosopher_collection: Optional[str] = Field(default=None, description="Philosopher collection")
    created_at: datetime = Field(description="Message creation timestamp")
    relevance_score: float = Field(description="Relevance score (0.0 to 1.0)")
    source_type: str = Field(default="chat", description="Source type (chat or document)")

    class Config:
        json_schema_extra = {
            "example": {
                "message_id": "550e8400-e29b-41d4-a716-446655440000",
                "conversation_id": "550e8400-e29b-41d4-a716-446655440001",
                "session_id": "user_session_123",
                "username": "alice@example.com",
                "role": "assistant",
                "content": "Virtue ethics, according to Aristotle, is a moral philosophy that emphasizes character...",
                "philosopher_collection": "Aristotle",
                "created_at": "2024-01-15T10:31:00Z",
                "relevance_score": 0.85,
                "source_type": "chat"
            }
        }


class ChatSearchResponse(BaseModel):
    """Response model for chat history search results."""
    
    results: List[ChatSearchResultItem] = Field(description="Search results with relevance scores")
    total_found: int = Field(description="Total number of matching messages")
    query: str = Field(description="Original search query")
    session_id: str = Field(description="Session ID that was searched")
    
    class Config:
        json_schema_extra = {
            "example": {
                "results": [
                    {
                        "message_id": "550e8400-e29b-41d4-a716-446655440000",
                        "conversation_id": "550e8400-e29b-41d4-a716-446655440001",
                        "session_id": "user_session_123",
                        "role": "assistant",
                        "content": "Virtue ethics focuses on character rather than actions...",
                        "philosopher_collection": "Aristotle",
                        "created_at": "2024-01-15T10:31:00Z",
                        "relevance_score": 0.85
                    }
                ],
                "total_found": 3,
                "query": "virtue ethics",
                "session_id": "user_session_123"
            }
        }


class ChatConversationResponse(BaseModel):
    """Response model for individual conversations."""

    conversation_id: str = Field(description="Unique conversation identifier")
    session_id: str = Field(description="Session identifier")
    username: Optional[str] = Field(default=None, description="User identifier")
    title: Optional[str] = Field(default=None, description="Conversation title")
    philosopher_collection: Optional[str] = Field(default=None, description="Associated philosopher collection")
    message_count: int = Field(description="Number of messages in conversation")
    created_at: datetime = Field(description="Conversation creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "conversation_id": "550e8400-e29b-41d4-a716-446655440001",
                "session_id": "user_session_123",
                "username": "alice@example.com",
                "title": "Discussion about Aristotelian Ethics",
                "philosopher_collection": "Aristotle",
                "message_count": 8,
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T11:45:00Z"
            }
        }


class ChatConversationsResponse(BaseModel):
    """Response model for paginated conversation list."""
    
    conversations: List[ChatConversationResponse] = Field(description="List of conversations")
    total_count: int = Field(description="Total number of conversations")
    has_more: bool = Field(description="Whether there are more conversations available")
    offset: int = Field(description="Current offset in pagination")
    limit: int = Field(description="Current limit per page")
    
    class Config:
        json_schema_extra = {
            "example": {
                "conversations": [
                    {
                        "conversation_id": "550e8400-e29b-41d4-a716-446655440001",
                        "session_id": "user_session_123",
                        "title": "Aristotelian Ethics Discussion",
                        "philosopher_collection": "Aristotle",
                        "message_count": 8,
                        "created_at": "2024-01-15T10:30:00Z",
                        "updated_at": "2024-01-15T11:45:00Z"
                    }
                ],
                "total_count": 5,
                "has_more": False,
                "offset": 0,
                "limit": 20
            }
        }


class ChatDeletionResponse(BaseModel):
    """Response model for chat history deletion operations."""

    success: bool = Field(description="Whether the deletion was successful")
    message: str = Field(description="Status message")
    deleted_conversations: int = Field(default=0, description="Number of conversations deleted")
    deleted_messages: int = Field(default=0, description="Number of messages deleted")
    session_id: str = Field(description="Session ID that was processed")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Chat history successfully deleted",
                "deleted_conversations": 3,
                "deleted_messages": 24,
                "session_id": "user_session_123"
            }
        }


class ChatMessageRequest(BaseModel):
    """Request model for storing a chat message."""

    session_id: str = Field(description="Session identifier for privacy isolation")
    role: str = Field(description="Message role (user or assistant)")
    content: str = Field(description="Message content", min_length=1)
    philosopher_collection: Optional[str] = Field(default=None, description="Optional philosopher collection context")
    conversation_id: Optional[str] = Field(default=None, description="Optional existing conversation ID")
    username: Optional[str] = Field(default=None, description="Optional username for user tracking")

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "user_session_123",
                "role": "user",
                "content": "What is virtue ethics according to Aristotle?",
                "philosopher_collection": "Aristotle",
                "conversation_id": None,
                "username": "alice@example.com"
            }
        }