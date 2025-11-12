# app/services/feature_flags.py
"""
Feature flag service for managing optional functionality.
Provides centralized feature flag checking and graceful degradation.
"""
import logging
from typing import Optional
from functools import wraps
from app.config.settings import Settings

logger = logging.getLogger(__name__)

class FeatureFlagService:
    """Service for managing feature flags and graceful degradation."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self._log_feature_states()
    
    def _log_feature_states(self) -> None:
        """Log the current state of all feature flags."""
        logger.info("Feature flag states:")
        logger.info(f"  chat_history: {self.settings.chat_history}")
        logger.info(f"  use_llama_index_workflows: {self.settings.use_llama_index_workflows}")
        logger.info(f"  enable_compilation: {self.settings.enable_compilation}")
    
    def is_chat_history_enabled(self) -> bool:
        """Check if chat history feature is enabled."""
        return self.settings.chat_history
    
    def require_chat_history(self, operation_name: str = "operation") -> bool:
        """
        Check if chat history is enabled and log if disabled.
        
        Args:
            operation_name: Name of the operation being checked for logging
            
        Returns:
            True if enabled, False if disabled
        """
        if not self.is_chat_history_enabled():
            logger.warning(f"Chat history feature is disabled, skipping {operation_name}")
            return False
        return True
    
    def get_chat_history_status(self) -> dict:
        """Get detailed status of chat history feature."""
        return {
            "enabled": self.is_chat_history_enabled(),
            "feature_name": "chat_history",
            "description": "Persistent chat history storage with vector search"
        }

def require_chat_history_feature(settings: Settings):
    """
    Decorator to check if chat history feature is enabled before executing function.
    Returns None if feature is disabled, allowing graceful degradation.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not settings.chat_history:
                logger.warning(f"Chat history feature disabled, skipping {func.__name__}")
                return None
            return await func(*args, **kwargs)
        return wrapper
    return decorator

def check_chat_history_feature(settings: Settings, operation_name: str = "operation") -> bool:
    """
    Utility function to check chat history feature flag with logging.
    
    Args:
        settings: Application settings
        operation_name: Name of operation for logging
        
    Returns:
        True if enabled, False if disabled
    """
    if not settings.chat_history:
        logger.warning(f"Chat history feature is disabled, skipping {operation_name}")
        return False
    return True