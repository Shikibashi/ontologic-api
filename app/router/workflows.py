from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Body, Request, Depends
from app.core.dependencies import PaperWorkflowDep, ReviewWorkflowDep, SubscriptionManagerDep
from app.core.rate_limiting import limiter, get_heavy_limit
from pydantic import BaseModel, Field

from app.core.logger import log
from app.core.validation import workflow_validator
from app.core.exceptions import ValidationError, DraftNotFoundError, WorkflowError
from app.core.error_responses import (
    create_validation_error,
    create_not_found_error,
    create_internal_error
)
from app.core.user_models import User
from app.core.auth_helpers import get_optional_user_with_logging
from app.core.subscription_helpers import check_subscription_access

router = APIRouter(prefix="/workflows", tags=["workflows"])

# Workflow instances now injected via FastAPI dependencies instead of module-level globals


# Request Models
class CreateDraftRequest(BaseModel):
    title: str = Field(..., description="Paper title")
    topic: str = Field(..., description="Main research topic or question")
    collection: str = Field(..., description="Philosopher collection to focus on")
    immersive_mode: bool = Field(default=False, description="Use immersive philosopher voice")
    temperature: float = Field(default=0.3, ge=0.0, le=1.0, description="LLM temperature")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")


class GenerateSectionsRequest(BaseModel):
    sections: Optional[List[str]] = Field(
        default=None,
        description="Sections to generate. Default: all sections"
    )
    use_expansion: bool = Field(
        default=True,
        description="Use query expansion for enhanced retrieval"
    )
    expansion_methods: Optional[List[str]] = Field(
        default=None,
        description="Query expansion methods: ['hyde', 'rag_fusion', 'self_ask', 'prf']"
    )


class ReviewDraftRequest(BaseModel):
    rubric: Optional[List[str]] = Field(
        default=None,
        description="Review criteria. Default: ['accuracy', 'argument', 'coherence', 'citations', 'style']"
    )
    severity_gate: str = Field(
        default="medium",
        description="Minimum severity for blocking issues: 'low', 'medium', 'high'"
    )
    max_evidence_per_question: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum evidence items per verification question"
    )


class ApplySuggestionsRequest(BaseModel):
    accept_all: bool = Field(default=False, description="Accept all suggestions")
    accept_sections: Optional[List[str]] = Field(
        default=None,
        description="Accept suggestions for specific sections"
    )
    suggestion_ids: Optional[List[str]] = Field(
        default=None,
        description="Accept specific suggestion IDs"
    )


# Response Models
class DraftCreatedResponse(BaseModel):
    draft_id: str
    status: str
    message: str


class SectionGenerationResponse(BaseModel):
    draft_id: str
    sections_generated: List[str]
    sections_failed: List[str]
    total_sections: int
    final_status: str


class ReviewResponse(BaseModel):
    draft_id: str
    review_id: str
    status: str
    summary: Dict[str, Any]
    blocking_issues: int
    verification_coverage: str


class DraftStatusResponse(BaseModel):
    draft_id: str
    title: str
    topic: str
    collection: str
    status: str
    progress: Dict[str, Any]
    created_at: str
    updated_at: str
    sections: Dict[str, Optional[str]]
    has_review: bool
    suggestions_count: int


# Endpoints
@router.post("/create", response_model=DraftCreatedResponse)
@limiter.limit(get_heavy_limit)
async def create_draft(
    request: Request,
    body: CreateDraftRequest,
    paper_workflow: PaperWorkflowDep,
    subscription_manager: SubscriptionManagerDep,
    user: Optional[User] = Depends(get_optional_user_with_logging),
):
    """
    Create a new paper draft.

    Initializes a new draft with the specified configuration and returns
    a unique draft ID for subsequent operations.
    """
    log.debug(f"Processing draft creation from {request.client.host} within rate limit")

    # Subscription check: Enforce access control if payments are enabled
    await check_subscription_access(user, subscription_manager, "/workflows/create", request)

    try:
        # Validate request at router level for consistency
        workflow_validator.validate_paper_creation(
            title=body.title,
            topic=body.topic,
            collection=body.collection,
            immersive_mode=body.immersive_mode,
            temperature=body.temperature,
            metadata=body.metadata
        )

        draft_id = await paper_workflow.create_draft(
            title=body.title,
            topic=body.topic,
            collection=body.collection,
            immersive_mode=body.immersive_mode,
            temperature=body.temperature,
            workflow_metadata=body.metadata
        )

        return DraftCreatedResponse(
            draft_id=draft_id,
            status="created",
            message=f"Draft '{body.title}' created successfully"
        )

    except ValidationError as e:
        log.warning(f"Draft creation validation failed: {e}")
        error = create_validation_error(
            field="request",
            message=f"Invalid request: {str(e)}",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=400, detail=error.model_dump())
    except WorkflowError as e:
        log.error(f"Draft creation workflow error: {e}")
        error = create_validation_error(
            field="workflow",
            message=f"Workflow error: {str(e)}",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=422, detail=error.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to create draft: {e}")
        error = create_internal_error(
            message=f"Draft creation failed: {str(e)}",
            error_type="DraftCreationError",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.post("/{draft_id}/generate", response_model=SectionGenerationResponse)
async def generate_sections(
    request: Request,
    draft_id: str,
    paper_workflow: PaperWorkflowDep,
    subscription_manager: SubscriptionManagerDep,
    body: GenerateSectionsRequest = Body(...),
    user: Optional[User] = Depends(get_optional_user_with_logging),
):
    """
    Generate content for specified sections of a paper draft.

    Uses advanced retrieval with query expansion and the configured
    prompt templates (academic or immersive mode) to generate
    high-quality philosophical content.
    """
    # Subscription check: Enforce access control if payments are enabled
    await check_subscription_access(user, subscription_manager, "/workflows/generate", request)

    try:
        result = await paper_workflow.generate_sections(
            draft_id=draft_id,
            sections=body.sections,
            use_expansion=body.use_expansion,
            expansion_methods=body.expansion_methods
        )

        return SectionGenerationResponse(**result)

    except ValueError as e:
        error = create_not_found_error(
            resource="draft",
            identifier=draft_id,
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=404, detail=error.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Section generation failed for draft {draft_id}: {e}")
        error = create_internal_error(
            message=f"Section generation failed: {str(e)}",
            error_type="SectionGenerationError",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.get("/{draft_id}/status", response_model=DraftStatusResponse)
async def get_draft_status(
    request: Request,
    draft_id: str,
    paper_workflow: PaperWorkflowDep
):
    """
    Get comprehensive status information for a draft.

    Returns draft metadata, generation progress, section content,
    review status, and suggestion counts.
    """
    try:
        # Validate draft_id format
        workflow_validator.validate_draft_id(draft_id)
        status = await paper_workflow.get_draft_status(draft_id)

        if not status:
            error = create_not_found_error(
                resource="draft",
                identifier=draft_id,
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=404, detail=error.model_dump())

        return DraftStatusResponse(**status)

    except ValidationError as e:
        log.warning(f"Draft status validation failed: {e}")
        error = create_validation_error(
            field="draft_id",
            message=f"Invalid draft ID: {str(e)}",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=400, detail=error.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to get status for draft {draft_id}: {e}")
        error = create_internal_error(
            message=f"Status retrieval failed: {str(e)}",
            error_type="StatusRetrievalError",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.post("/{draft_id}/ai-review", response_model=ReviewResponse)
async def ai_review_draft(
    request: Request,
    draft_id: str,
    review_workflow: ReviewWorkflowDep,
    body: ReviewDraftRequest = Body(...)
):
    """
    Perform comprehensive AI review of a paper draft.

    Implements Chain-of-Verification, Self-RAG, and evidence-based
    review to generate actionable suggestions with blocking flags.
    Uses query expansion to gather supporting evidence.
    """
    try:
        result = await review_workflow.review_draft(
            draft_id=draft_id,
            rubric=body.rubric,
            severity_gate=body.severity_gate,
            max_evidence_per_question=body.max_evidence_per_question
        )

        return ReviewResponse(**result)

    except ValueError as e:
        error = create_not_found_error(
            resource="draft",
            identifier=draft_id,
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=404, detail=error.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"AI review failed for draft {draft_id}: {e}")
        error = create_internal_error(
            message=f"AI review failed: {str(e)}",
            error_type="AIReviewError",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.post("/{draft_id}/apply")
async def apply_suggestions(
    request: Request,
    draft_id: str,
    paper_workflow: PaperWorkflowDep,
    body: ApplySuggestionsRequest = Body(...)
):
    """
    Apply review suggestions to a draft.

    Supports selective application by section, suggestion ID,
    or accepting all suggestions. Updates the draft content
    based on the review recommendations.
    """
    try:
        result = await paper_workflow.apply_suggestions(
            draft_id=draft_id,
            accept_all=body.accept_all,
            accept_sections=body.accept_sections,
            suggestion_ids=body.suggestion_ids
        )

        return result

    except ValueError as e:
        error = create_not_found_error(
            resource="draft",
            identifier=draft_id,
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=404, detail=error.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to apply suggestions for draft {draft_id}: {e}")
        error = create_internal_error(
            message=f"Suggestion application failed: {str(e)}",
            error_type="SuggestionApplicationError",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


# Additional utility endpoints
@router.get("/{draft_id}/review")
async def get_review_data(
    request: Request,
    draft_id: str,
    paper_workflow: PaperWorkflowDep
):
    """Get detailed review data for a draft."""
    try:
        status = await paper_workflow.get_draft_status(draft_id)

        if not status:
            error = create_not_found_error(
                resource="draft",
                identifier=draft_id,
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=404, detail=error.model_dump())

        # Get the full draft to access review data
        from app.services.paper_service import PaperDraftService
        draft = await PaperDraftService.get_draft(draft_id)

        if not draft.review_data:
            error = create_not_found_error(
                resource="review_data",
                identifier=draft_id,
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=404, detail=error.model_dump())

        return {
            "draft_id": draft_id,
            "review_data": draft.review_data,
            "suggestions": draft.suggestions,
            "review_summary": {
                "total_suggestions": len(draft.suggestions) if draft.suggestions else 0,
                "blocking_suggestions": sum(1 for s in draft.suggestions if s.get("blocking", False)) if draft.suggestions else 0,
                "reviewed_at": draft.review_data.get("reviewed_at"),
                "verification_questions": len(draft.review_data.get("verification_plan", [])),
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to get review data for draft {draft_id}: {e}")
        error = create_internal_error(
            message=f"Review data retrieval failed: {str(e)}",
            error_type="ReviewDataRetrievalError",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.get("/")
async def list_drafts(
    request: Request,
    limit: int = Query(10, ge=1, le=100, description="Number of drafts to return"),
    offset: int = Query(0, ge=0, description="Number of drafts to skip"),
    status_filter: Optional[str] = Query(None, description="Filter by status")
):
    """List drafts with optional filtering."""
    try:
        from app.services.paper_service import PaperDraftService
        from app.core.db_models import DraftStatus

        # Convert status filter if provided
        status_enum = None
        if status_filter:
            try:
                status_enum = DraftStatus(status_filter)
            except ValueError:
                error = create_validation_error(
                    field="status_filter",
                    message=f"Invalid status: {status_filter}. Valid statuses: {[s.value for s in DraftStatus]}",
                    request_id=getattr(request.state, 'request_id', None)
                )
                raise HTTPException(status_code=400, detail=error.model_dump())

        drafts = await PaperDraftService.list_drafts(
            limit=limit,
            offset=offset,
            status_filter=status_enum
        )

        return {
            "drafts": [
                {
                    "draft_id": draft.draft_id,
                    "title": draft.title,
                    "topic": draft.topic,
                    "collection": draft.collection,
                    "status": draft.status,
                    "created_at": draft.created_at.isoformat(),
                    "updated_at": draft.updated_at.isoformat(),
                    "progress": draft.get_progress()
                }
                for draft in drafts
            ],
            "total_returned": len(drafts),
            "offset": offset,
            "limit": limit
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to list drafts: {e}")
        error = create_internal_error(
            message=f"Draft listing failed: {str(e)}",
            error_type="DraftListingError",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


# Health check endpoint
@router.get("/health")
async def health_check():
    """Check workflow system health."""
    try:
        # Basic health checks
        health_status = {
            "status": "healthy",
            "workflows": {
                "paper_workflow": "available",
                "review_workflow": "available"
            },
            "services": {
                "expansion_service": "available",
                "database": "available",
                "prompt_system": "available"
            },
            "features": {
                "jinja2_templates": "enabled",
                "query_expansion": "enabled",
                "rrf_fusion": "enabled",
                "chain_of_verification": "enabled"
            }
        }

        return health_status

    except Exception as e:
        log.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }
