from typing import Optional, Dict, Any, TYPE_CHECKING
from datetime import datetime, timezone
import uuid

from app.config import (
    get_oauth_enabled,
    get_enabled_providers,
    get_chat_history_enabled,
    get_uploads_enabled,
    get_security_config,
)
from app.core.logger import log

if TYPE_CHECKING:
    from app.services.cache_service import RedisCacheService

class AuthService:
    """
    Optional authentication service that enhances but doesn't gate functionality.

    All endpoints remain publicly accessible. Auth provides:
    - Persistent user session tracking for chat history (Redis-backed)
    - User-specific data association
    - Optional enhanced features for authenticated users

    Sessions are stored in Redis for persistence and horizontal scalability.

    LIFECYCLE: This service should be initialized during application startup
    and stored in app.state for request-time access via dependency injection.
    """

    def __init__(self, cache_service: Optional['RedisCacheService'] = None):
        """
        Initialize AuthService with optional cache service.

        Args:
            cache_service: Optional RedisCacheService for session storage.
                          If None, sessions will not persist across restarts.
        """
        self.cache_service = cache_service
        self.oauth_enabled = get_oauth_enabled()
        provider_list = get_enabled_providers()
        # Convert list to dictionary for easier access
        self.enabled_providers = {provider: {"enabled": True} for provider in provider_list}
        self.session_ttl_hours = get_security_config().get("session_timeout_hours", 24)

        if cache_service is None:
            log.warning("AuthService initialized without cache_service - sessions will not persist across restarts")

    @classmethod
    async def start(cls, cache_service: Optional['RedisCacheService'] = None):
        """
        Async factory method for lifespan-managed initialization.

        Args:
            cache_service: Optional RedisCacheService instance

        Returns:
            Initialized AuthService instance
        """
        instance = cls(cache_service=cache_service)
        log.info("AuthService initialized for lifespan management")
        return instance

    def _make_session_key(self, session_id: str) -> str:
        """Generate Redis key for session storage."""
        return f"session:{session_id}"

    def _get_session_ttl_seconds(self) -> int:
        """Get session TTL in seconds."""
        return int(self.session_ttl_hours * 3600)

    def _deserialize_session_data(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert ISO datetime strings back to datetime objects."""
        if session_data is None:
            return None

        if "created_at" in session_data and isinstance(session_data["created_at"], str):
            session_data["created_at"] = datetime.fromisoformat(session_data["created_at"])

        if "last_activity" in session_data and isinstance(session_data["last_activity"], str):
            session_data["last_activity"] = datetime.fromisoformat(session_data["last_activity"])

        return session_data

    async def create_anonymous_session(self, request_info: Optional[Dict[str, Any]] = None) -> str:
        """Create an anonymous session for tracking purposes."""
        session_id = str(uuid.uuid4())

        session_data = {
            "session_id": session_id,
            "user_id": None,
            "anonymous": True,
            "created_at": datetime.now(timezone.utc),
            "last_activity": datetime.now(timezone.utc),
            "provider": None,
            "metadata": request_info or {}
        }

        # Graceful degradation: return session_id even if cache unavailable
        if self.cache_service is None:
            log.debug(f"Created non-persistent anonymous session {session_id} (cache unavailable)")
            return session_id

        session_key = self._make_session_key(session_id)
        ttl_seconds = self._get_session_ttl_seconds()
        success = await self.cache_service.set(session_key, session_data, ttl_seconds, cache_type='session')

        if not success:
            log.warning(f"Failed to store anonymous session {session_id} in Redis")

        return session_id

    async def create_authenticated_session(
        self,
        user_id: str,
        provider: str,
        user_info: Dict[str, Any]
    ) -> str:
        """Create an authenticated user session."""
        session_id = str(uuid.uuid4())

        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "anonymous": False,
            "created_at": datetime.now(timezone.utc),
            "last_activity": datetime.now(timezone.utc),
            "provider": provider,
            "user_info": user_info,
            "metadata": {}
        }

        # Graceful degradation: return session_id even if cache unavailable
        if self.cache_service is None:
            log.debug(f"Created non-persistent authenticated session {session_id} for user {user_id} (cache unavailable)")
            return session_id

        session_key = self._make_session_key(session_id)
        ttl_seconds = self._get_session_ttl_seconds()
        success = await self.cache_service.set(session_key, session_data, ttl_seconds, cache_type='session')

        if not success:
            log.warning(f"Failed to store authenticated session {session_id} in Redis")

        log.info(f"Created authenticated session for user {user_id} via {provider}")
        return session_id

    async def get_session(self, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Get session information if it exists."""
        if not session_id:
            return None

        # Graceful degradation: return None if cache unavailable
        if self.cache_service is None:
            log.debug(f"Cannot retrieve session {session_id} (cache unavailable)")
            return None

        session_key = self._make_session_key(session_id)
        session_data = await self.cache_service.get(session_key, cache_type='session')

        if session_data is None:
            return None

        session_data = self._deserialize_session_data(session_data)

        session_data["last_activity"] = datetime.now(timezone.utc)
        ttl_seconds = self._get_session_ttl_seconds()
        await self.cache_service.set(session_key, session_data, ttl_seconds, cache_type='session')

        return session_data

    async def get_user_context(self, session_id: Optional[str]) -> Dict[str, Any]:
        """
        Get user context for request processing.

        Returns user information if available, or anonymous context.
        This enables user-specific features without gating access.
        """
        session = await self.get_session(session_id)

        if session and not session["anonymous"]:
            return {
                "authenticated": True,
                "user_id": session["user_id"],
                "provider": session["provider"],
                "session_id": session["session_id"],
                "user_info": session.get("user_info", {}),
                "features": {
                    "chat_history": get_chat_history_enabled(),
                    "enhanced_uploads": get_uploads_enabled(),
                    "priority_processing": True  # Example enhanced feature
                }
            }
        else:
            # Anonymous context - still gets full access
            return {
                "authenticated": False,
                "user_id": None,
                "provider": None,
                "session_id": session["session_id"] if session else None,
                "features": {
                    "chat_history": False,  # Anonymous users don't get persistent history
                    "enhanced_uploads": False,
                    "priority_processing": False
                }
            }

    def get_available_providers(self) -> Dict[str, Dict[str, str]]:
        """Get list of available OAuth providers."""
        if not self.oauth_enabled:
            return {}

        available = {}
        for provider, config in self.enabled_providers.items():
            # Only return non-sensitive config info
            available[provider] = {
                "name": provider.title(),
                "enabled": True,
                "auth_url": f"/auth/{provider}",  # Would be implemented
                "description": f"Sign in with {provider.title()}"
            }

        return available

    # Session expiry is now handled automatically by Redis TTL

    async def associate_data_with_user(
        self,
        session_id: Optional[str],
        data_type: str,
        data_id: str
    ) -> bool:
        """
        Associate data (like drafts, chat history) with a user session.

        This enables user-specific data retrieval for authenticated users
        while allowing anonymous usage.
        """
        session = await self.get_session(session_id)
        if not session:
            return False

        # In a real implementation, this would update database records
        # to associate the data with the user_id
        log.info(f"Associated {data_type} {data_id} with session {session_id}")
        return True

    async def cleanup_expired_sessions(self):
        """No-op method - Redis TTL handles automatic session expiry."""
        # Redis TTL handles automatic expiry, so this method is now a no-op.
        # Kept for backward compatibility with any scheduled cleanup tasks.
        log.debug("Session cleanup is handled automatically by Redis TTL")

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session explicitly (e.g., for logout).

        Args:
            session_id: Session ID to delete

        Returns:
            True if session was deleted, False if not found or error
        """
        if not session_id:
            return False

        # Graceful degradation: return False if cache unavailable
        if self.cache_service is None:
            log.debug(f"Cannot delete session {session_id} (cache unavailable)")
            return False

        session_key = self._make_session_key(session_id)

        session_data = await self.cache_service.get(session_key, cache_type='session')
        if session_data is None:
            return False

        try:
            await self.cache_service.clear_cache(pattern=session_key)
            log.info(f"Deleted session {session_id}")
            return True
        except Exception as e:
            log.warning(f"Failed to delete session {session_id}: {e}")
            return False
