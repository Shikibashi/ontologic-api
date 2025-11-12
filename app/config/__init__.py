"""Configuration interface using Pydantic Settings."""

from typing import Dict, Any
from app.config.settings import get_settings

def get_workflow_config() -> Dict[str, Any]:
    """Get workflow-specific configuration."""
    settings = get_settings()
    return {
        "max_retries": settings.max_retries,
        "timeout": settings.timeout,
        "batch_size": settings.batch_size
    }

def get_oauth_enabled() -> bool:
    """Check if OAuth authentication is enabled."""
    settings = get_settings()
    return settings.oauth_enabled

def get_chat_history_enabled() -> bool:
    """Check if chat history feature is enabled."""
    settings = get_settings()
    return settings.chat_history

def get_enabled_providers() -> list:
    """Get list of enabled OAuth providers."""
    settings = get_settings()
    return [p.strip() for p in settings.oauth_providers.split(",") if p.strip()]

def get_uploads_enabled() -> bool:
    """Check if document uploads are enabled."""
    settings = get_settings()
    return settings.document_uploads_enabled

def get_security_config() -> Dict[str, Any]:
    """Get security configuration."""
    settings = get_settings()
    return {
        "session_secret": settings.session_secret.get_secret_value() if settings.session_secret else None
    }

def get_trusted_hosts():
    """Get trusted hosts for middleware."""
    import os
    import sys
    hosts = ["api.ontologicai.com", "localhost", "www.ontologicai.com"]
    
    # Add testserver for test environments
    if (os.getenv("APP_ENV") == "test" or "pytest" in sys.modules):
        hosts.append("testserver")
    
    return hosts

def get_cors_config():
    """Get CORS configuration."""
    return {
        "origins": ["http://localhost:5173", "http://localhost:5174", 
                   "https://www.ontologicai.com", "https://ontologicai.com"],
        "credentials": True,
        "methods": ["GET", "POST"],
        "headers": ["*"]
    }

# Legacy compatibility layer has been removed.
# Use get_settings() directly or the helper functions above for configuration access.