# Required Fixes for Subscription Enforcement

This document provides exact code changes needed to complete the subscription enforcement implementation.

## Fix 1: Update subscription_helpers.py (Token Estimation)

**File**: `/home/tcs/Downloads/ontologic-api-main/app/core/subscription_helpers.py`

**Current (Line 95)**:
```python
estimated_tokens = len(response_text) // 4
```

**Replace with**:
```python
estimated_tokens = len(response_text) // CHARS_PER_TOKEN_ESTIMATE
```

**Add import at top of file**:
```python
from app.core.constants import CHARS_PER_TOKEN_ESTIMATE
```

---

## Fix 2: Add Subscription Enforcement to workflows.py

**File**: `/home/tcs/Downloads/ontologic-api-main/app/router/workflows.py`

### Step 1: Add imports (after line 14)

```python
from app.core.dependencies import SubscriptionManagerDep
from app.core.subscription_helpers import (
    check_subscription_access,
    track_subscription_usage
)
from app.core.user_models import User
```

### Step 2: Update create_draft endpoint

**Find** (around line 120):
```python
@router.post("/create")
@limiter.limit(get_heavy_limit)
async def create_draft(
    request: Request,
    body: CreateDraftRequest,
    paper_workflow: PaperWorkflowDep,
    current_user: User = Depends(current_active_user),
):
```

**Replace with**:
```python
@router.post("/create")
@limiter.limit(get_heavy_limit)
async def create_draft(
    request: Request,
    body: CreateDraftRequest,
    paper_workflow: PaperWorkflowDep,
    subscription_manager: SubscriptionManagerDep,
    user: Optional[User] = Depends(get_optional_user_with_logging),
):
    # Subscription check: Enforce access control if payments are enabled
    await check_subscription_access(
        user,
        subscription_manager,
        "/workflows/create",
        request
    )
```

### Step 3: Update generate_sections endpoint

**Find** (around line 200):
```python
@router.post("/{draft_id}/generate")
@limiter.limit(get_heavy_limit)
async def generate_sections(
    request: Request,
    draft_id: str,
    body: GenerateSectionsRequest,
    paper_workflow: PaperWorkflowDep,
    current_user: User = Depends(current_active_user),
):
```

**Replace with**:
```python
@router.post("/{draft_id}/generate")
@limiter.limit(get_heavy_limit)
async def generate_sections(
    request: Request,
    draft_id: str,
    paper_workflow: PaperWorkflowDep,
    subscription_manager: SubscriptionManagerDep,
    body: GenerateSectionsRequest = Body(...),
    user: Optional[User] = Depends(get_optional_user_with_logging),
):
    # Subscription check: Enforce access control if payments are enabled
    await check_subscription_access(
        user,
        subscription_manager,
        "/workflows/generate",
        request
    )
```

**Add usage tracking after response** (find where response is returned):
```python
# Before: return SectionGenerationResponse(...)
response = SectionGenerationResponse(
    draft_id=draft_id,
    sections_generated=sections_generated,
    # ... other fields
)

# Track usage if payments enabled and user authenticated
if response:
    # Estimate tokens from generated sections
    total_text = " ".join([section.get("content", "") for section in sections_generated])
    await track_subscription_usage(
        current_user,
        subscription_manager,
        "/workflows/generate",
        total_text
    )

return response
```

---

## Fix 3: Add Subscription Enforcement to documents.py

**File**: `/home/tcs/Downloads/ontologic-api-main/app/router/documents.py`

### Step 1: Add imports (after line 32)

```python
from app.core.dependencies import SubscriptionManagerDep
from app.core.subscription_helpers import (
    check_subscription_access,
    track_subscription_usage
)
```

### Step 2: Update upload_document endpoint

**Find** (around line 150):
```python
@router.post("/upload")
@limiter.limit(get_upload_limit)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    qdrant_manager: QdrantManagerDep = Depends(),
    current_user: User = Depends(current_active_user),
    # ... other params
):
```

**Replace with**:
```python
@router.post("/upload")
@limiter.limit(get_upload_limit)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    qdrant_manager: QdrantManagerDep = Depends(),
    subscription_manager: SubscriptionManagerDep,
    current_user: User = Depends(current_active_user),
    # ... other params
):
    # Subscription check: Enforce access control if payments are enabled
    await check_subscription_access(
        current_user, 
        subscription_manager, 
        "/documents/upload", 
        request
    )
```

**Add usage tracking after upload** (find where upload completes successfully):
```python
# After successful upload
response = DocumentUploadResponse(
    status="success",
    file_id=file_id,
    # ... other fields
)

# Track usage (estimate tokens from chunks)
if response and response.chunks_uploaded > 0:
    # Rough estimate: 500 chars per chunk average
    estimated_text_length = response.chunks_uploaded * 500
    estimated_response = f"Uploaded {response.chunks_uploaded} chunks"
    await track_subscription_usage(
        current_user,
        subscription_manager,
        "/documents/upload",
        estimated_response
    )

return response
```

---

## Fix 4: Optional - Add to query_hybrid (Recommended)

**File**: `/home/tcs/Downloads/ontologic-api-main/app/router/ontologic.py`

**Find** (line 1442):
```python
@router.post("/query_hybrid")
@limiter.limit(get_default_limit)
async def gather_points_from_collections(
    request: Request,
    body: HybridQueryRequest,
    qdrant_manager: QdrantManagerDep,
    llm_manager: LLMManagerDep,
    # ... other params
):
```

**Add after body validation** (around line 1480):
```python
# Note: This endpoint doesn't have user auth currently
# Consider adding subscription check if you add authentication:

# If you add current_user and subscription_manager params:
# await check_subscription_access(
#     current_user, 
#     subscription_manager, 
#     "/query_hybrid", 
#     request
# )
```

---

## Fix 5: Optional - Add Metrics (Recommended)

**File**: `/home/tcs/Downloads/ontologic-api-main/app/core/subscription_helpers.py`

**Update check_subscription_access** (around line 56):

```python
except HTTPException:
    # Re-raise access denied errors
    raise
except Exception as e:
    # Add metrics tracking
    try:
        from app.services.chat_monitoring import chat_monitoring
        chat_monitoring.record_counter(
            "subscription_check_failures",
            {
                "endpoint": endpoint,
                "error_type": type(e).__name__,
                "user_id": str(user.id) if user else "anonymous"
            }
        )
    except ImportError:
        pass  # Gracefully handle if monitoring not available
    
    log.error(
        f"Subscription access check failed for user {user.id} on {endpoint}: {e}",
        exc_info=True,
        extra={
            "user_id": user.id,
            "endpoint": endpoint,
            "error_type": type(e).__name__,
            "graceful_degradation": True
        }
    )
    # Continue processing if subscription check fails (graceful degradation)
```

**Update track_subscription_usage** (around line 101):

```python
except Exception as e:
    # Add metrics tracking
    try:
        from app.services.chat_monitoring import chat_monitoring
        chat_monitoring.record_counter(
            "subscription_tracking_failures",
            {
                "endpoint": endpoint,
                "error_type": type(e).__name__,
                "user_id": str(user.id) if user else "anonymous"
            }
        )
    except ImportError:
        pass  # Gracefully handle if monitoring not available
    
    log.warning(
        f"Failed to track usage for user {user.id} on {endpoint}: {e}",
        extra={
            "user_id": user.id,
            "endpoint": endpoint,
            "error_type": type(e).__name__,
            "non_fatal": True
        }
    )
    # Non-fatal: continue even if usage tracking fails
```

---

## Fix 6: Consistency - Update llm_manager.py (Optional)

**File**: `/home/tcs/Downloads/ontologic-api-main/app/services/llm_manager.py`

**Find** (lines 283-284):
```python
prompt_tokens = len(question) // 4
completion_tokens = len(str(response)) // 4
```

**Replace with**:
```python
from app.core.constants import CHARS_PER_TOKEN_ESTIMATE

prompt_tokens = len(question) // CHARS_PER_TOKEN_ESTIMATE
completion_tokens = len(str(response)) // CHARS_PER_TOKEN_ESTIMATE
```

---

## Testing After Changes

Run these tests to verify fixes:

```bash
# 1. Test chat endpoints still work
curl -X GET "http://localhost:8000/ask?query_str=test" \
  -H "Authorization: Bearer $TOKEN"

# 2. Test workflows with subscription
curl -X POST "http://localhost:8000/workflows/create" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Test","topic":"Test","collection":"Aristotle"}'

# 3. Test documents upload with subscription
curl -X POST "http://localhost:8000/documents/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@test.pdf"

# 4. Test with expired subscription (should get 403)
curl -X POST "http://localhost:8000/workflows/create" \
  -H "Authorization: Bearer $EXPIRED_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Test","topic":"Test","collection":"Aristotle"}'
# Expected: 403 Forbidden

# 5. Test graceful degradation (disable payments)
# Set payments_enabled=false in config
curl -X GET "http://localhost:8000/ask?query_str=test"
# Expected: Should work without auth
```

---

## Checklist

- [ ] Fix 1: Update subscription_helpers.py token estimation
- [ ] Fix 2: Add subscription to workflows.py (create_draft)
- [ ] Fix 2: Add subscription to workflows.py (generate_sections)
- [ ] Fix 3: Add subscription to documents.py (upload)
- [ ] Fix 4: Consider query_hybrid (if adding auth)
- [ ] Fix 5: Add metrics (recommended)
- [ ] Fix 6: Update llm_manager.py (consistency)
- [ ] Test all endpoints with valid subscription
- [ ] Test all endpoints with expired subscription
- [ ] Test graceful degradation (payments disabled)
- [ ] Verify metrics are recorded (if added)

---

## Estimated Time

- Core fixes (1-3): ~2 hours
- Testing: ~1 hour
- Metrics (optional): ~30 minutes
- Total: ~3-4 hours

---

**Priority**: HIGH - Complete before merge
**Risk**: LOW - Changes are isolated and well-tested pattern
**Impact**: HIGH - Closes revenue bypass and enforces fair usage
