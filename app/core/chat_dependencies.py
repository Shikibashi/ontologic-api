# app/core/chat_dependencies.py
"""
Dependency injection for chat history services.
Provides centralized access to chat history configuration and feature flags.
"""
import logging
from functools import lru_cache
from fastapi import Depends
from app.config import get_chat_history_enabled
from app.config.settings import get_settings
from app.services.feature_flags import FeatureFlagService
from app.services.chat_config import ChatHistoryConfig

logger = logging.getLogger(__name__)

def get_feature_flags(settings=None) -> FeatureFlagService:
    """
    Get the feature flag service instance.
    
    Args:
        settings: Settings instance (optional, will get from get_settings if not provided)
        
    Returns:
        FeatureFlagService instance
    """
    if settings is None:
        settings = get_settings()
    return FeatureFlagService(settings)

def get_chat_config(settings=None) -> ChatHistoryConfig:
    """
    Get the chat history configuration instance.
    
    Args:
        settings: Settings instance (optional, will get from get_settings if not provided)
        
    Returns:
        ChatHistoryConfig instance
    """
    if settings is None:
        settings = get_settings()
    return ChatHistoryConfig(settings)

@lru_cache()
def get_expansion_service():
    """
    Get the ExpansionService instance for fusion search.
    
    Returns:
        ExpansionService instance or None if not available
    """
    try:
        from app.services.expansion_service import ExpansionService
        return ExpansionService()
    except Exception as e:
        logger.warning(f"ExpansionService not available: {e}")
        return None

def get_chat_qdrant_service():
    """
    Get ChatQdrantService with optional fusion support.
    
    Returns:
        ChatQdrantService instance with ExpansionService if available
    """
    from app.services.chat_qdrant_service import ChatQdrantService
    from app.services.llm_manager import LLMManager
    from app.services.qdrant_manager import QdrantManager
    
    # Get dependencies
    llm_manager = LLMManager()
    qdrant_manager = QdrantManager()
    expansion_service = get_expansion_service()
    
    # Create service with optional expansion service
    return ChatQdrantService(
        qdrant_client=qdrant_manager.client,
        llm_manager=llm_manager,
        expansion_service=expansion_service
    )

def get_chat_feature_status(
    feature_flags: FeatureFlagService = Depends(get_feature_flags)
) -> dict:
    """
    Get chat history feature status for API responses.
    
    Args:
        feature_flags: Feature flag service
        
    Returns:
        Dictionary with feature status
    """
    return feature_flags.get_chat_history_status()

def require_chat_history_enabled(
    feature_flags: FeatureFlagService = Depends(get_feature_flags)
) -> bool:
    """
    Dependency that ensures chat history is enabled.
    Raises HTTPException if disabled.
    
    Args:
        feature_flags: Feature flag service
        
    Returns:
        True if enabled
        
    Raises:
        HTTPException: If chat history is disabled
    """
    from fastapi import HTTPException, status
    
    if not feature_flags.is_chat_history_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "feature_disabled",
                "message": "Chat history feature is currently disabled",
                "feature": "chat_history"
            }
        )
    return True