"""Workflow utility functions and helpers."""

from typing import Dict, Any, Optional
from datetime import datetime, timezone
from app.core.logger import log

class WorkflowUtils:
    """Utility functions for workflow management."""
    
    @staticmethod
    def create_metadata(
        stage: str,
        progress: float = 0.0,
        **kwargs
    ) -> Dict[str, Any]:
        """Create standardized workflow metadata."""
        metadata = {
            "stage": stage,
            "progress": progress,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **kwargs
        }
        log.debug(f"Created workflow metadata: {metadata}")
        return metadata
    
    @staticmethod
    def update_progress(
        metadata: Dict[str, Any],
        stage: str,
        progress: float
    ) -> Dict[str, Any]:
        """Update workflow progress in metadata."""
        metadata.update({
            "stage": stage,
            "progress": progress,
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
        log.debug(f"Updated workflow progress: stage={stage}, progress={progress}")
        return metadata
    
    @staticmethod
    def validate_stage_transition(
        current_stage: str,
        new_stage: str,
        allowed_transitions: Dict[str, list]
    ) -> bool:
        """Validate if stage transition is allowed."""
        if current_stage not in allowed_transitions:
            return False
        return new_stage in allowed_transitions[current_stage]
