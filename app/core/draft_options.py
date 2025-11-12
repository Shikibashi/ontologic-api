"""Data structures for paper draft creation."""

from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class DraftCreateOptions:
    """
    Centralized options for draft creation to prevent argument packing drift.
    """
    title: str
    topic: str
    collection: str
    immersive_mode: bool = False
    temperature: float = 0.3
    workflow_metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "title": self.title,
            "topic": self.topic,
            "collection": self.collection,
            "immersive_mode": self.immersive_mode,
            "temperature": self.temperature,
            "workflow_metadata": self.workflow_metadata or {}
        }
