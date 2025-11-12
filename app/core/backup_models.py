"""
Pydantic models for backup operations.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from enum import Enum


class BackupStatusEnum(str, Enum):
    """Backup operation status enumeration."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackupRequest(BaseModel):
    """Request model for backup operations."""
    collections: Optional[List[str]] = Field(
        default=None, 
        description="Specific collections to backup. If empty, backup all philosophy collections"
    )
    collection_filter: Optional[str] = Field(
        default=None,
        description="Filter pattern for collection names (supports wildcards like 'Aristotle*')"
    )
    target_prefix: Optional[str] = Field(
        default=None, 
        description="Prefix to add to target collection names"
    )
    overwrite: bool = Field(
        default=False, 
        description="Whether to overwrite existing target collections"
    )
    include_patterns: Optional[List[str]] = Field(
        default=None,
        description="Include patterns for selective backup"
    )
    exclude_patterns: Optional[List[str]] = Field(
        default=None,
        description="Exclude patterns for selective backup"
    )


class CollectionBackupResult(BaseModel):
    """Result of backing up a single collection."""
    source_collection: str
    target_collection: str
    success: bool
    source_points: Optional[int] = None
    target_points: Optional[int] = None
    processed_points: int = 0
    batches_processed: int = 0
    error: Optional[str] = None


class BackupProgressResponse(BaseModel):
    """Response model for backup progress."""
    backup_id: str
    status: BackupStatusEnum
    total_collections: int
    completed_collections: int
    current_collection: Optional[str] = None
    total_points: int
    processed_points: int
    collection_progress_percent: float
    point_progress_percent: float
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    errors: List[str] = Field(default_factory=list)


class BackupResponse(BaseModel):
    """Response model for backup operations."""
    backup_id: str
    status: str
    total_collections: int
    successful_backups: int
    failed_backups: int
    total_source_points: int
    total_target_points: int
    duration_seconds: Optional[float] = None
    collections: List[CollectionBackupResult]
    errors: List[str] = Field(default_factory=list)


class ValidationRequest(BaseModel):
    """Request model for backup validation."""
    source_collection: str
    target_collection: str
    sample_size: int = Field(default=100, ge=1, le=1000, description="Number of points to sample for validation")


class ValidationCheck(BaseModel):
    """Individual validation check result."""
    source_exists: bool
    target_exists: bool
    point_count_match: bool
    source_points: int
    target_points: int
    config_match: bool
    sample_validation: Optional[Dict[str, Any]] = None


class ValidationResponse(BaseModel):
    """Response model for backup validation."""
    source_collection: str
    target_collection: str
    valid: bool
    checks: ValidationCheck
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class CollectionInfoResponse(BaseModel):
    """Response model for collection information."""
    name: str
    vectors_count: int
    indexed_vectors_count: int
    points_count: int
    segments_count: int
    config: Dict[str, Any]
    payload_schema: Dict[str, Any] = Field(default_factory=dict)


class RepairRequest(BaseModel):
    """Request model for collection repair operations."""
    source_collection: str
    target_collection: str
    repair_mode: str = Field(
        default="missing_points",
        description="Repair mode: 'missing_points' or 'full_sync'"
    )


class RepairResponse(BaseModel):
    """Response model for repair operations."""
    source_collection: str
    target_collection: str
    repair_mode: str
    success: bool
    repaired_points: int
    errors: List[str] = Field(default_factory=list)


class CollectionListResponse(BaseModel):
    """Response model for listing collections."""
    collections: List[str]
    total_count: int
    source: str  # "production" or "local"