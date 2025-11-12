# app/services/chat_config.py
"""
Chat history configuration service with environment support.
Handles retention policies, collection naming, and performance settings.
"""
import logging
import os
from typing import Optional, Dict, Any
from datetime import timedelta
from app.config.settings import Settings

logger = logging.getLogger(__name__)

class ChatHistoryConfig:
    """Configuration manager for chat history functionality."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.env = settings.env
        self._validate_config()
    
    def _validate_config(self) -> None:
        """Validate chat history configuration."""
        if self.settings.chat_history:
            logger.info(f"Chat history enabled for environment: {self.env}")
            logger.info(f"Collection name: {self.get_chat_collection_name()}")
            logger.info(f"Retention policy: {self.get_retention_days()} days")
        else:
            logger.info("Chat history disabled")
    
    def get_chat_collection_name(self) -> str:
        """
        Get environment-aware chat collection name.
        
        Returns:
            Collection name based on environment (Chat_History, Chat_History_Dev, Chat_History_Test)
        """
        base_name = "Chat_History"
        
        if self.env == "prod":
            return base_name
        elif self.env == "dev":
            return f"{base_name}_Dev"
        elif self.env == "test":
            return f"{base_name}_Test"
        else:
            # Default to dev for unknown environments
            logger.warning(f"Unknown environment '{self.env}', using dev collection name")
            return f"{base_name}_Dev"
    
    def get_retention_days(self) -> int:
        """
        Get chat history retention period in days.
        
        Returns:
            Number of days to retain chat history (default: 90)
        """
        # Check environment variable first
        retention_str = os.environ.get("CHAT_HISTORY_RETENTION_DAYS")
        if retention_str:
            try:
                return int(retention_str)
            except ValueError:
                logger.warning(f"Invalid CHAT_HISTORY_RETENTION_DAYS value: {retention_str}, using default")
        
        # Environment-specific defaults
        if self.env == "prod":
            return 90  # 3 months for production
        elif self.env == "test":
            return 1   # 1 day for tests
        else:
            return 30  # 1 month for development
    
    def get_cleanup_batch_size(self) -> int:
        """
        Get batch size for cleanup operations.
        
        Returns:
            Batch size for processing cleanup operations
        """
        batch_size_str = os.environ.get("CHAT_CLEANUP_BATCH_SIZE")
        if batch_size_str:
            try:
                return int(batch_size_str)
            except ValueError:
                logger.warning(f"Invalid CHAT_CLEANUP_BATCH_SIZE value: {batch_size_str}, using default")
        
        # Environment-specific defaults
        if self.env == "prod":
            return 1000  # Larger batches for production
        else:
            return 100   # Smaller batches for dev/test
    
    def get_vector_upload_batch_size(self) -> int:
        """
        Get batch size for vector upload operations.
        
        Returns:
            Batch size for Qdrant vector uploads
        """
        batch_size_str = os.environ.get("CHAT_VECTOR_BATCH_SIZE")
        if batch_size_str:
            try:
                return int(batch_size_str)
            except ValueError:
                logger.warning(f"Invalid CHAT_VECTOR_BATCH_SIZE value: {batch_size_str}, using default")
        
        # Environment-specific defaults
        if self.env == "prod":
            return 50   # Moderate batches for production stability
        elif self.env == "test":
            return 10   # Small batches for tests
        else:
            return 25   # Medium batches for development
    
    def get_qdrant_timeout(self) -> int:
        """
        Get Qdrant operation timeout in seconds.
        
        Returns:
            Timeout for Qdrant operations
        """
        timeout_str = os.environ.get("CHAT_QDRANT_TIMEOUT")
        if timeout_str:
            try:
                return int(timeout_str)
            except ValueError:
                logger.warning(f"Invalid CHAT_QDRANT_TIMEOUT value: {timeout_str}, using default")
        
        # Use existing qdrant timeout from settings or default
        return getattr(self.settings, 'qdrant_timeout', 30)
    
    def get_max_message_length(self) -> int:
        """
        Get maximum message length for storage.
        
        Returns:
            Maximum length of chat messages in characters
        """
        max_length_str = os.environ.get("CHAT_MAX_MESSAGE_LENGTH")
        if max_length_str:
            try:
                return int(max_length_str)
            except ValueError:
                logger.warning(f"Invalid CHAT_MAX_MESSAGE_LENGTH value: {max_length_str}, using default")
        
        return 10000  # 10KB default limit
    
    def get_pagination_default_limit(self) -> int:
        """
        Get default pagination limit for chat history queries.
        
        Returns:
            Default number of messages per page
        """
        return 50
    
    def get_pagination_max_limit(self) -> int:
        """
        Get maximum pagination limit for chat history queries.
        
        Returns:
            Maximum number of messages per page
        """
        return 200
    
    def should_enable_vector_search(self) -> bool:
        """
        Check if vector search should be enabled for chat history.
        
        Returns:
            True if vector search should be enabled
        """
        # Check environment variable
        enable_str = os.environ.get("CHAT_ENABLE_VECTOR_SEARCH", "true").lower()
        return enable_str in ("true", "1", "yes", "on")
    
    def get_local_qdrant_config(self) -> Dict[str, Any]:
        """
        Get configuration for local Qdrant instance (development).
        
        Returns:
            Dictionary with local Qdrant configuration
        """
        return {
            "url": os.environ.get("LOCAL_QDRANT_URL", "http://localhost:6333"),
            "api_key": os.environ.get("LOCAL_QDRANT_API_KEY"),  # Usually None for local
            "timeout": self.get_qdrant_timeout(),
            "collection_name": self.get_chat_collection_name()
        }
    
    def get_production_qdrant_config(self) -> Dict[str, Any]:
        """
        Get configuration for production Qdrant instance (for backups).
        
        Returns:
            Dictionary with production Qdrant configuration
        """
        return {
            "url": self.settings.qdrant_url,
            "api_key": self.settings.qdrant_api_key.get_secret_value() if self.settings.qdrant_api_key else None,
            "timeout": self.get_qdrant_timeout(),
            "collection_name": "Chat_History"  # Always use production collection name
        }
    
    def get_config_summary(self) -> Dict[str, Any]:
        """
        Get a summary of current chat history configuration.
        
        Returns:
            Dictionary with configuration summary
        """
        return {
            "enabled": self.settings.chat_history,
            "environment": self.env,
            "collection_name": self.get_chat_collection_name(),
            "retention_days": self.get_retention_days(),
            "cleanup_batch_size": self.get_cleanup_batch_size(),
            "vector_upload_batch_size": self.get_vector_upload_batch_size(),
            "qdrant_timeout": self.get_qdrant_timeout(),
            "max_message_length": self.get_max_message_length(),
            "vector_search_enabled": self.should_enable_vector_search(),
            "pagination_default_limit": self.get_pagination_default_limit(),
            "pagination_max_limit": self.get_pagination_max_limit()
        }