# This file now uses dynamic template loading instead of hardcoded data
# Import the new template-based system
from app.core.philosopher_loader import PHILOSOPHER_INFO, reload_philosopher_info

# Expose the same interface for backward compatibility
__all__ = ['PHILOSOPHER_INFO', 'reload_philosopher_info']