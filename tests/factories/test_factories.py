"""Centralized test data factories."""

import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from app.core.db_models import PaperDraft, DraftStatus
from app.core.draft_options import DraftCreateOptions

class TestFactories:
    """Centralized factory methods for test data creation."""
    
    @staticmethod
    def draft_options(
        title: str = "Test Paper",
        topic: str = "Test Topic",
        collection: str = "test-collection",
        **kwargs
    ) -> DraftCreateOptions:
        """Create test DraftCreateOptions."""
        return DraftCreateOptions(
            title=title,
            topic=topic,
            collection=collection,
            **kwargs
        )
    
    @staticmethod
    def paper_draft(
        title: str = "Test Paper",
        topic: str = "Test Topic",
        collection: str = "test-collection",
        status: DraftStatus = DraftStatus.CREATED,
        **kwargs
    ) -> PaperDraft:
        """Create test PaperDraft instance."""
        return PaperDraft(
            draft_id=str(uuid.uuid4()),
            title=title,
            topic=topic,
            collection=collection,
            status=status,
            created_at=datetime.utcnow(),
            **kwargs
        )
    
    @staticmethod
    def workflow_metadata(
        stage: str = "initial",
        progress: float = 0.0,
        **kwargs
    ) -> Dict[str, Any]:
        """Create test workflow metadata."""
        return {
            "stage": stage,
            "progress": progress,
            "created_at": datetime.utcnow().isoformat(),
            **kwargs
        }
