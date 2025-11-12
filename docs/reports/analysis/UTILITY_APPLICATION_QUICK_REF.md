# Utility Application Quick Reference

## TL;DR

**21 locations** need `safe_record_metric` applied (12 high priority, 8 medium priority, 1 config check).
**Timeout helper** is already fully adopted ✓.
**404 vs 403 patterns** are already correct ✓.

---

## High Priority Fixes (12 locations)

### 1. Workflows Router (8 locations)
**File:** `/home/tcs/Downloads/ontologic-api-main/app/router/workflows.py`

```python
# Add import at top
from app.services.monitoring_helpers import safe_record_metric

# Line 181: Draft creation error
safe_record_metric("workflow_draft_creation_error", "counter", 1.0, {"error_type": type(e).__name__})

# Line 229: Section generation error
safe_record_metric("workflow_section_generation_error", "counter", 1.0, {"draft_id": draft_id})

# Line 268: Draft retrieval error
safe_record_metric("workflow_draft_get_error", "counter", 1.0, {"draft_id": draft_id})

# Line 311: AI review error
safe_record_metric("workflow_ai_review_error", "counter", 1.0, {"draft_id": draft_id})

# Line 354: Apply suggestions error
safe_record_metric("workflow_apply_suggestions_error", "counter", 1.0, {"draft_id": draft_id})

# Line 409: Delete draft error
safe_record_metric("workflow_draft_delete_error", "counter", 1.0, {"draft_id": draft_id})

# Line 471: List drafts error
safe_record_metric("workflow_draft_list_error", "counter", 1.0, {})

# Line 508: Validate draft error
safe_record_metric("workflow_draft_validation_error", "counter", 1.0, {"draft_id": draft_id})
```

### 2. Auth Router (1 location)
**File:** `/home/tcs/Downloads/ontologic-api-main/app/router/auth.py`

```python
# Add import at top
from app.services.monitoring_helpers import safe_record_metric

# Line 124: Before raising 404
safe_record_metric("auth_session_not_found", "counter", 1.0, {"session_id": session_id})
```

### 3. Backup Router (2 locations)
**File:** `/home/tcs/Downloads/ontologic-api-main/app/router/backup_router.py`

```python
# Add import at top
from app.services.monitoring_helpers import safe_record_metric

# Line 384: Backup not found
safe_record_metric("backup_not_found", "counter", 1.0, {"backup_id": backup_id})

# Line 520: Restore backup not found
safe_record_metric("backup_restore_not_found", "counter", 1.0, {"backup_id": backup_id})
```

### 4. Admin Payments Router (1 location)
**File:** `/home/tcs/Downloads/ontologic-api-main/app/router/admin_payments.py`

```python
# Add import at top
from app.services.monitoring_helpers import safe_record_metric

# Line 195: Refund payment not found
safe_record_metric("admin_refund_payment_not_found", "counter", 1.0, {"payment_id": refund_request.payment_intent_id})
```

---

## Medium Priority Fixes (8 locations)

### Ontologic Router - Replace unsafe metrics
**File:** `/home/tcs/Downloads/ontologic-api-main/app/router/ontologic.py`

```python
# Lines to replace (import safe_record_metric at top):
# Line 226
safe_record_metric("chat_username_provided", "counter", 1.0, {"username": username})

# Line 229
safe_record_metric("chat_username_not_provided", "counter", 1.0, {})

# Line 942
safe_record_metric("pdf_context_requests", "counter", 1.0, {"username": username, "collection": body.collection})

# Line 970
safe_record_metric("document_search_duration_ms", "histogram", duration_ms, {"username": username})

# Line 1000
safe_record_metric("document_chunks_found", "histogram", len(doc_results), {"username": username})

# Line 1005
safe_record_metric("pdf_context_success", "counter", 1.0, {"username": username})

# Line 1019
safe_record_metric("pdf_context_skipped", "counter", 1.0, {"reason": reason})
```

---

## Configuration Check (1 location)

### Main Application - Qdrant Localhost Check
**File:** `/home/tcs/Downloads/ontologic-api-main/app/main.py`

```python
# Add at line 209 (after Redis check, inside production block):

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

## Files to Edit Summary

| File | Changes | Priority |
|------|---------|----------|
| `app/router/workflows.py` | Add import + 8 metrics | HIGH |
| `app/router/auth.py` | Add import + 1 metric | HIGH |
| `app/router/backup_router.py` | Add import + 2 metrics | HIGH |
| `app/router/admin_payments.py` | Add import + 1 metric | HIGH |
| `app/router/ontologic.py` | Replace 8 metrics | MEDIUM |
| `app/main.py` | Add 1 config check | LOW |

---

## Test Commands

```bash
# After changes, test error paths
pytest tests/test_workflows.py -v
pytest tests/integration/test_auth_endpoints.py -v

# Verify metrics don't break graceful degradation
pytest tests/test_chat_monitoring.py -v

# Check production startup validation
APP_ENVIRONMENT=production python -c "from app.main import app"
```

---

## Verification Checklist

- [ ] All imports added to router files
- [ ] All 12 high-priority metrics added to error handlers
- [ ] All 8 medium-priority metrics replaced in ontologic.py
- [ ] Qdrant localhost check added to main.py
- [ ] Tests pass for all modified files
- [ ] Production startup validates Qdrant configuration
- [ ] Metrics visible in monitoring dashboard
- [ ] Error paths don't break on metric failures

---

## Implementation Time Estimate

- High Priority (12 changes): 60-90 minutes
- Medium Priority (8 changes): 30-45 minutes  
- Config Check (1 change): 15 minutes
- Testing & Validation: 30-60 minutes

**Total: 2-3 hours**
