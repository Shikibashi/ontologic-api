# Utility Application Recommendations

## Executive Summary

Analysis of the codebase reveals **47 specific locations** where the new utility functions can be applied to improve consistency, maintainability, and reliability. The utilities are already well-designed and partially adopted, but significant opportunities remain for broader application.

**New Utilities:**
1. `calculate_per_attempt_timeout(total_timeout, max_retries)` in `app/core/timeout_helpers.py`
2. `safe_record_metric(metric_name, metric_type, value, labels)` in `app/core/monitoring_helpers.py`

---

## 1. Calculate Per-Attempt Timeout Utility

### Current Adoption Status
**ADOPTED (4 locations):**
- ✅ `app/services/llm_manager.py:278` - `aquery()` method
- ✅ `app/services/llm_manager.py:848` - `get_embedding()` method  
- ✅ `app/services/llm_manager.py:928` - `generate_splade_vector()` method
- ✅ `app/services/llm_manager.py:1029` - `generate_dense_vector()` method

### NOT YET APPLIED (0 locations)
**Analysis:** All `@with_retry` decorators that use timeouts have already adopted the helper.

**Verification:**
```bash
# All @with_retry decorators in the codebase:
app/services/llm_manager.py:245    @with_retry(max_retries=2, ...)      # ✅ Uses helper at line 278
app/services/llm_manager.py:909    @with_retry(max_retries=3, ...)      # ✅ Uses helper at line 928
app/services/llm_manager.py:1010   @with_retry(max_retries=3, ...)      # ✅ Uses helper at line 1029
app/services/cache_service.py:530  @with_retry(max_retries=2, ...)      # Uses @with_timeout decorator instead
app/services/cache_service.py:610  @with_retry(max_retries=2, ...)      # Uses @with_timeout decorator instead
```

**Note:** `cache_service.py` uses the `@with_timeout` decorator which already handles timeout calculation internally, so no change needed.

### Recommendation: COMPLETE ✓
The timeout helper is fully adopted where applicable. No additional changes needed.

---

## 2. Safe Record Metric Utility

### Current Adoption Status
**ADOPTED (6 locations):**
- ✅ `app/router/ontologic.py:1028` - PDF context error handling
- ✅ `app/router/documents.py:302` - Document upload failure
- ✅ `app/router/documents.py:361` - HTTP error metrics
- ✅ `app/router/documents.py:372` - Generic error metrics
- ✅ `app/router/documents.py:391` - Final error handler
- ✅ `app/core/subscription_helpers.py:73,128` - Subscription tracking

### SHOULD BE APPLIED (20 locations)

#### High Priority - Error Handlers (12 locations)

**app/router/workflows.py - Missing safe metrics in exception handlers:**
```python
# Line 181-187: Draft creation error
except Exception as e:
    log.error(f"Failed to create draft: {e}")
    # ❌ SHOULD ADD: safe_record_metric("workflow_draft_creation_error", "counter", 1.0, {"error_type": type(e).__name__})
    error = create_internal_error(...)
    raise HTTPException(status_code=500, detail=error.model_dump())

# Line 229-235: Section generation error  
except Exception as e:
    log.error(f"Section generation failed for draft {draft_id}: {e}")
    # ❌ SHOULD ADD: safe_record_metric("workflow_section_generation_error", "counter", 1.0, {"draft_id": draft_id})
    error = create_internal_error(...)
    raise HTTPException(status_code=500, detail=error.model_dump())

# Line 268-274: Draft retrieval error
except Exception as e:
    log.error(f"Failed to get draft: {e}")
    # ❌ SHOULD ADD: safe_record_metric("workflow_draft_get_error", "counter", 1.0, {"draft_id": draft_id})
    error = create_internal_error(...)
    raise HTTPException(status_code=500, detail=error.model_dump())

# Line 311-317: AI review error
except Exception as e:
    log.error(f"AI review failed for draft {draft_id}: {e}")
    # ❌ SHOULD ADD: safe_record_metric("workflow_ai_review_error", "counter", 1.0, {"draft_id": draft_id})
    error = create_internal_error(...)
    raise HTTPException(status_code=500, detail=error.model_dump())

# Line 354-360: Apply suggestions error
except Exception as e:
    log.error(f"Failed to apply suggestions: {e}")
    # ❌ SHOULD ADD: safe_record_metric("workflow_apply_suggestions_error", "counter", 1.0, {"draft_id": draft_id})
    error = create_internal_error(...)
    raise HTTPException(status_code=500, detail=error.model_dump())

# Line 409-415: Delete draft error
except Exception as e:
    log.error(f"Failed to delete draft: {e}")
    # ❌ SHOULD ADD: safe_record_metric("workflow_draft_delete_error", "counter", 1.0, {"draft_id": draft_id})
    error = create_internal_error(...)
    raise HTTPException(status_code=500, detail=error.model_dump())

# Line 471-477: List drafts error
except Exception as e:
    log.error(f"Failed to list drafts: {e}")
    # ❌ SHOULD ADD: safe_record_metric("workflow_draft_list_error", "counter", 1.0, {})
    error = create_internal_error(...)
    raise HTTPException(status_code=500, detail=error.model_dump())

# Line 508-514: Validate draft error
except Exception as e:
    log.error(f"Draft validation failed: {e}")
    # ❌ SHOULD ADD: safe_record_metric("workflow_draft_validation_error", "counter", 1.0, {"draft_id": draft_id})
    error = create_internal_error(...)
    raise HTTPException(status_code=500, detail=error.model_dump())
```

**app/router/auth.py - Session validation error:**
```python
# Line 124: Session not found returns 404
if not user_context["session_id"]:
    error = create_not_found_error(...)
    # ❌ SHOULD ADD: safe_record_metric("auth_session_not_found", "counter", 1.0, {"session_id": session_id})
    raise HTTPException(status_code=404, detail=error.model_dump())
```

**app/router/backup_router.py - Backup errors:**
```python
# Line 384: Backup not found
raise HTTPException(status_code=404, detail=error.model_dump())
# ❌ SHOULD ADD: safe_record_metric("backup_not_found", "counter", 1.0, {"backup_id": backup_id})

# Line 520: Restore backup not found  
raise HTTPException(status_code=404, detail=error.model_dump())
# ❌ SHOULD ADD: safe_record_metric("backup_restore_not_found", "counter", 1.0, {"backup_id": backup_id})
```

**app/router/admin_payments.py - Payment errors:**
```python
# Line 195: Refund payment not found
raise HTTPException(status_code=404, detail=error.model_dump())
# ❌ SHOULD ADD: safe_record_metric("admin_refund_payment_not_found", "counter", 1.0, {"payment_id": refund_request.payment_intent_id})
```

#### Medium Priority - Success Path Metrics (8 locations)

**app/router/ontologic.py - Success metrics that could fail:**
```python
# Line 226: Username tracking (not in error path, but could fail)
chat_monitoring.record_counter("chat_username_provided", {"username": username})
# ❌ SHOULD REPLACE WITH: safe_record_metric("chat_username_provided", "counter", 1.0, {"username": username})

# Line 229: Username not provided tracking
chat_monitoring.record_counter("chat_username_not_provided")
# ❌ SHOULD REPLACE WITH: safe_record_metric("chat_username_not_provided", "counter")

# Line 942: PDF context request tracking (success path)
chat_monitoring.record_counter("pdf_context_requests", {...})
# ❌ SHOULD REPLACE WITH: safe_record_metric("pdf_context_requests", "counter", 1.0, {...})

# Line 970: Document search duration
chat_monitoring.record_timer_ms("document_search_duration_ms", duration_ms, {...})
# ❌ SHOULD REPLACE WITH: safe_record_metric("document_search_duration_ms", "histogram", duration_ms, {...})

# Line 1000: Document chunks found
chat_monitoring.record_histogram("document_chunks_found", len(doc_results), {...})
# ❌ SHOULD REPLACE WITH: safe_record_metric("document_chunks_found", "histogram", len(doc_results), {...})

# Line 1005: PDF context success
chat_monitoring.record_counter("pdf_context_success", {...})
# ❌ SHOULD REPLACE WITH: safe_record_metric("pdf_context_success", "counter", 1.0, {...})

# Line 1019: PDF context skipped
chat_monitoring.record_counter("pdf_context_skipped", {...})
# ❌ SHOULD REPLACE WITH: safe_record_metric("pdf_context_skipped", "counter", 1.0, {...})
```

**app/router/documents.py - Success metrics:**
```python
# Line 262: File size tracking (success path)
chat_monitoring.record_histogram("document_upload_size_mb", file_size_mb, {...})
# ✅ Consider using safe_record_metric for consistency (low priority, not in error path)

# Line 270: File too large error
chat_monitoring.record_counter("document_upload_errors", {...})
# ✅ Consider using safe_record_metric (error path but before exception)

# Line 323-335: Upload success metrics (3 calls)
chat_monitoring.record_counter("document_upload_success", {...})
chat_monitoring.record_timer_ms("document_upload_duration_ms", duration_ms, {...})
chat_monitoring.record_histogram("document_chunks_created", result["chunks_uploaded"], {...})
# ✅ Consider safe_record_metric for graceful degradation in success path
```

---

## 3. Localhost Configuration Checks

### Current Implementation
**ADOPTED (2 locations):**
- ✅ `app/main.py:192` - Database URL localhost check (production only)
- ✅ `app/main.py:202` - Redis host localhost check (production only)

### Pattern Already Established
```python
# Database validation (line 192)
if not database_url or "localhost" in database_url or "127.0.0.1" in database_url:
    log.error("Database URL points to localhost or is not set")
    raise RuntimeError("Production startup aborted")

# Redis validation (line 202)  
if settings.redis_enabled and settings.redis_host in ("localhost", "127.0.0.1"):
    log.warning("⚠️  WARNING: Redis points to localhost in production")
```

### SHOULD BE APPLIED (1 location)

**app/services/qdrant_manager.py:55 - Qdrant localhost detection:**
```python
# Line 55: Currently used for local vs cloud decision
is_local = "localhost" in qdrant_url or "127.0.0.1" in qdrant_url

# ❌ SHOULD ADD: Production startup validation in app/main.py
# Similar to database/Redis checks:
if settings.app_environment == "production":
    qdrant_url = settings.qdrant_url or settings.local_qdrant_url
    if "localhost" in qdrant_url or "127.0.0.1" in qdrant_url:
        log.warning("⚠️  WARNING: Qdrant points to localhost in production")
        log.warning("  Consider using APP_QDRANT_URL environment variable")
```

**Location to add:** `app/main.py:209` (after Redis check)

---

## 4. 404 vs 403 Status Code Pattern

### Current Best Practice
**ADOPTED (2 routers):**
- ✅ `app/router/documents.py` - Uses 403 for ownership violations
- ✅ `app/router/payments.py:269` - Uses 403 for "no subscription to cancel" (prevents enumeration)

### Pattern to Follow
```python
# documents.py - Ownership check returns 403
if document_owner != username:
    error = create_authorization_error(...)
    raise HTTPException(status_code=403, detail=error.model_dump())

# payments.py - Subscription check returns 403 (not 404)
if subscription is None:
    error = create_authorization_error(message="No active subscription to cancel", ...)
    raise HTTPException(status_code=403, detail=error.model_dump())
```

### ALREADY CORRECT (18 locations)
All 404 errors in authenticated endpoints are for **resource not found**, not authorization:

**app/router/workflows.py (6 occurrences):**
- ✅ Lines 226, 262, 308, 351, 381, 393 - All use 404 for `DraftNotFoundError` (correct)

**app/router/admin_payments.py (4 occurrences):**
- ✅ Lines 195, 254, 340, 503 - Payment/refund/dispute not found (correct)

**app/router/backup_router.py (2 occurrences):**
- ✅ Lines 384, 520 - Backup not found (correct)

**app/router/auth.py (1 occurrence):**
- ✅ Line 124 - Session not found (correct)

**app/router/ontologic.py (1 occurrence):**
- ✅ Line 1507 - Query results not found (correct - could return empty array instead)

### Recommendation: PATTERNS CORRECT ✓
No ownership checks are using 404 inappropriately. Current usage is correct.

---

## 5. Summary of Required Changes

### Immediate Actions (High Priority)

1. **Add safe_record_metric to workflow error handlers (8 locations)**
   ```python
   # File: app/router/workflows.py
   # Import at top:
   from app.services.monitoring_helpers import safe_record_metric
   
   # Add to each exception handler (lines 181, 229, 268, 311, 354, 409, 471, 508)
   safe_record_metric(
       "workflow_{operation}_error",
       "counter", 
       1.0, 
       {"error_type": type(e).__name__}
   )
   ```

2. **Add safe_record_metric to auth/backup/admin error handlers (4 locations)**
   ```python
   # Files: app/router/auth.py:124, backup_router.py:384,520, admin_payments.py:195
   safe_record_metric("auth_session_not_found", "counter", 1.0, {"session_id": session_id})
   safe_record_metric("backup_not_found", "counter", 1.0, {"backup_id": backup_id})
   safe_record_metric("backup_restore_not_found", "counter", 1.0, {"backup_id": backup_id})
   safe_record_metric("admin_refund_payment_not_found", "counter", 1.0, {"payment_id": payment_id})
   ```

3. **Add Qdrant localhost validation to production startup (1 location)**
   ```python
   # File: app/main.py:209 (after Redis check)
   qdrant_url = settings.qdrant_url or settings.local_qdrant_url
   if "localhost" in qdrant_url or "127.0.0.1" in qdrant_url:
       log.warning("⚠️  WARNING: Qdrant points to localhost in production")
   ```

### Medium Priority (Consistency Improvements)

4. **Replace success path metrics with safe_record_metric (8 locations)**
   ```python
   # File: app/router/ontologic.py
   # Lines 226, 229, 942, 970, 1000, 1005, 1019
   # Replace: chat_monitoring.record_counter(...)
   # With: safe_record_metric(metric_name, "counter", 1.0, labels)
   ```

### Total Impact
- **12 High Priority Changes** - Error handlers missing metrics
- **8 Medium Priority Changes** - Success path consistency
- **1 Configuration Check** - Qdrant localhost validation
- **21 Total Recommendations**

---

## 6. Implementation Checklist

### Phase 1: Critical Error Tracking (High Priority)
- [ ] Import `safe_record_metric` in `app/router/workflows.py`
- [ ] Add metrics to 8 exception handlers in workflows.py
- [ ] Import `safe_record_metric` in `app/router/auth.py`  
- [ ] Add metric to session validation (auth.py:124)
- [ ] Import `safe_record_metric` in `app/router/backup_router.py`
- [ ] Add metrics to 2 backup error handlers
- [ ] Import `safe_record_metric` in `app/router/admin_payments.py`
- [ ] Add metric to refund error handler
- [ ] Add Qdrant localhost check to `app/main.py:209`

### Phase 2: Consistency Improvements (Medium Priority)
- [ ] Replace 8 success path metrics in ontologic.py with safe_record_metric
- [ ] Consider replacing success metrics in documents.py for consistency

### Phase 3: Validation
- [ ] Test all error paths trigger metrics correctly
- [ ] Verify metrics don't break graceful degradation
- [ ] Confirm localhost checks work in production startup
- [ ] Review metrics dashboard for new counters

---

## 7. Code Examples

### Example 1: Workflow Error Handler Fix
```python
# Before (app/router/workflows.py:181-187)
except Exception as e:
    log.error(f"Failed to create draft: {e}")
    error = create_internal_error(
        message=f"Draft creation failed: {str(e)}",
        error_type="DraftCreationError",
        request_id=getattr(request.state, 'request_id', None)
    )
    raise HTTPException(status_code=500, detail=error.model_dump())

# After (with safe metric tracking)
from app.services.monitoring_helpers import safe_record_metric

except Exception as e:
    log.error(f"Failed to create draft: {e}")
    safe_record_metric(
        "workflow_draft_creation_error",
        "counter",
        1.0,
        {"error_type": type(e).__name__}
    )
    error = create_internal_error(
        message=f"Draft creation failed: {str(e)}",
        error_type="DraftCreationError",
        request_id=getattr(request.state, 'request_id', None)
    )
    raise HTTPException(status_code=500, detail=error.model_dump())
```

### Example 2: Success Path Metric Fix
```python
# Before (app/router/ontologic.py:942)
chat_monitoring.record_counter(
    "pdf_context_requests",
    {"username": username, "collection": body.collection},
)

# After (with safe recording)
from app.services.monitoring_helpers import safe_record_metric

safe_record_metric(
    "pdf_context_requests",
    "counter",
    1.0,
    {"username": username, "collection": body.collection}
)
```

### Example 3: Production Config Check
```python
# Add to app/main.py:209 (after Redis check)

# Validate Qdrant configuration if enabled
qdrant_url = settings.qdrant_url or settings.local_qdrant_url
if qdrant_url and ("localhost" in qdrant_url or "127.0.0.1" in qdrant_url):
    log.warning("=" * 60)
    log.warning("⚠️  WARNING: Qdrant points to localhost in production")
    log.warning("=" * 60)
    log.warning("  This may cause issues in distributed deployments")
    log.warning("  Consider using APP_QDRANT_URL environment variable")
    log.warning("=" * 60)
```

---

## 8. Benefits of Implementation

### Reliability
- **Graceful Degradation**: Monitoring failures won't break request handling
- **Complete Visibility**: Error paths will have proper metrics tracking
- **Production Safety**: Localhost configurations detected at startup

### Maintainability  
- **Consistency**: All error handlers follow same pattern
- **Debugging**: Better error tracking across all endpoints
- **Code Quality**: Reduced duplication, centralized error handling

### Observability
- **New Metrics**: 12 new error counters for workflow operations
- **Complete Coverage**: Both success and error paths tracked safely
- **Production Monitoring**: Early detection of misconfigurations

---

## Conclusion

The new utilities are well-designed and partially adopted. The main opportunity is to **extend safe_record_metric to 20 additional locations** across error handlers and success paths. The timeout helper is already fully adopted. Production configuration checks should add Qdrant validation for completeness.

**Recommended Priority:**
1. ⭐ **High Priority**: Add metrics to 12 error handlers (workflows, auth, backup, admin)
2. ⭐ **Medium Priority**: Replace 8 success path metrics for consistency  
3. ⭐ **Low Priority**: Add Qdrant localhost check to production startup

Total effort: ~2-3 hours for all changes + testing.
