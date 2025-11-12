# Quick Fixes - Critical Issues

**Priority**: URGENT
**Timeline**: Fix within 24 hours
**Impact**: Billing fraud prevention, user experience

---

## Fix 1: Document Upload Token Estimation 🔴 CRITICAL

### Problem:
Token estimation uses metadata string instead of actual content, causing 500x underestimation.

### Location:
`app/router/documents.py:336-337`

### Current Code:
```python
estimated_content = f"{file.filename}_{result['chunks_uploaded']}_chunks"
await track_subscription_usage(
    user, subscription_manager,
    "/documents/upload",
    estimated_content
)
```

### Fixed Code:
```python
# Calculate tokens from actual file size
file_size_chars = len(file_bytes)  # Available at line 253

# Create dummy content string for token estimation
# (We don't need actual content, just correct length)
estimated_content_for_tracking = "X" * (file_size_chars // 2)

await track_subscription_usage(
    user, subscription_manager,
    "/documents/upload",
    estimated_content_for_tracking
)
```

### Testing:
Add to `tests/test_document_endpoints.py`:

```python
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_document_upload_token_estimation_accuracy(authenticated_client, test_user):
    """
    Verify that document upload token estimation is accurate.
    """
    # Create a 1000-character test document
    file_content = "X" * 1000

    # Upload document
    response = authenticated_client.post(
        "/documents/upload",
        files={"file": ("test.txt", file_content, "text/plain")}
    )

    assert response.status_code == 201

    # Get user usage stats
    usage_response = authenticated_client.get("/users/me/usage")
    usage = usage_response.json()

    # Expected tokens: 1000 chars / 4 chars per token = 250 tokens
    expected_tokens = 1000 // 4
    actual_tokens = usage["tokens_used"]

    # Allow 10% margin of error
    assert abs(actual_tokens - expected_tokens) < (expected_tokens * 0.1), \
        f"Token estimation off by {abs(actual_tokens - expected_tokens)} tokens"
```

### Verification:
```bash
# Run the test
pytest tests/test_document_endpoints.py::test_document_upload_token_estimation_accuracy -v

# Expected output:
# PASSED tests/test_document_endpoints.py::test_document_upload_token_estimation_accuracy
```

---

## Fix 2: LLM Timeout Documentation 🟠 HIGH

### Problem:
Timeout behavior with retries is undocumented, causing user confusion.

### Location:
`app/services/llm_manager.py:244-273`

### Current Code:
```python
@with_retry(max_retries=2)
async def aquery(
    self,
    question: str,
    temperature=0.30,
    timeout: int | None = None
) -> CompletionResponse:
    effective_timeout = timeout or self._timeouts["generation"]
    response = await asyncio.wait_for(
        self.llm.acomplete(question),
        timeout=effective_timeout
    )
```

### Fixed Code:
```python
@with_retry(max_retries=2)
async def aquery(
    self,
    question: str,
    temperature=0.30,
    timeout: int | None = None  # Timeout PER RETRY ATTEMPT, not total
) -> CompletionResponse:
    """
    Query the LLM with retry protection.

    Args:
        question: The question to ask the LLM
        temperature: Sampling temperature (0.0-1.0)
        timeout: Timeout in seconds PER ATTEMPT. With max_retries=2,
                 total execution time could be up to 3x this value.
                 Default: 120 seconds per attempt (360s total max)

    Returns:
        CompletionResponse from the LLM

    Raises:
        LLMTimeoutError: If any attempt times out
        LLMResponseError: If LLM returns invalid response
        LLMUnavailableError: If LLM service is unavailable

    Note:
        If you need a hard total timeout, use asyncio.wait_for() when
        calling this method:

        ```python
        # Hard 120s total timeout
        response = await asyncio.wait_for(
            llm_manager.aquery("question"),
            timeout=120
        )
        ```
    """
    effective_timeout = timeout or self._timeouts["generation"]
    response = await asyncio.wait_for(
        self.llm.acomplete(question),
        timeout=effective_timeout
    )
```

### Update API Documentation:
Add to `docs/api/COMPLETE_ENDPOINT_DOCUMENTATION.md`:

```markdown
### LLM Timeout Behavior

**Important**: All LLM endpoints use retry logic for resilience.

- Default timeout: 120 seconds **per attempt**
- Max retries: 2 (total 3 attempts)
- **Total max execution time**: 360 seconds (120s × 3)

**Example:**
```bash
# This request could take up to 360 seconds
curl -X GET "http://localhost:8080/ask?query_str=complex%20question"
```

**For hard timeout limits**, use client-side timeouts:
```python
import httpx

# Hard 120s timeout (will cancel after 120s regardless of retries)
with httpx.Client(timeout=120.0) as client:
    response = client.get("http://localhost:8080/ask?query_str=question")
```
```

---

## Fix 3: Defensive Metric Recording 🟡 MEDIUM

### Problem:
Metric recording in error paths could break graceful degradation.

### Location:
`app/core/subscription_helpers.py:70-73`

### Current Code:
```python
except Exception as e:
    log.error("Subscription check failed...")
    # Track subscription check failure metric
    chat_monitoring.record_counter(...)  # COULD THROW!
    # Continue processing (graceful degradation)
```

### Fixed Code:
```python
except Exception as e:
    log.error(
        f"Subscription check failed for user {user.id if user else 'anonymous'}: {e}",
        extra={"user_id": user.id if user else None, "endpoint": endpoint}
    )

    # Defensive metric recording - don't let monitoring break graceful degradation
    try:
        chat_monitoring.record_counter(
            "subscription_check_failures",
            labels={"endpoint": endpoint, "error_type": type(e).__name__}
        )
    except Exception as metric_error:
        # Log but don't propagate - monitoring failures shouldn't break requests
        log.debug(
            f"Failed to record subscription check failure metric: {metric_error}",
            extra={"original_error": str(e)}
        )

    # Continue processing (graceful degradation preserved)
```

### Apply Pattern to All Error Paths:

Create a helper function in `app/core/monitoring_helpers.py`:

```python
import logging
from typing import Dict, Any, Optional
from app.services.chat_monitoring import chat_monitoring

log = logging.getLogger(__name__)

def safe_record_metric(
    metric_name: str,
    metric_type: str = "counter",
    value: float = 1.0,
    labels: Optional[Dict[str, Any]] = None
) -> None:
    """
    Safely record a metric without breaking graceful degradation.

    Args:
        metric_name: Name of the metric to record
        metric_type: Type of metric (counter, gauge, histogram)
        value: Value to record (default: 1.0 for counters)
        labels: Optional labels for the metric
    """
    try:
        if metric_type == "counter":
            chat_monitoring.record_counter(metric_name, labels=labels or {})
        elif metric_type == "gauge":
            chat_monitoring.record_gauge(metric_name, value, labels=labels or {})
        elif metric_type == "histogram":
            chat_monitoring.record_histogram(metric_name, value, labels=labels or {})
        else:
            log.warning(f"Unknown metric type: {metric_type}")
    except Exception as e:
        # Log but don't propagate - monitoring failures shouldn't break requests
        log.debug(
            f"Failed to record {metric_type} metric '{metric_name}': {e}",
            extra={"metric_name": metric_name, "metric_type": metric_type}
        )
```

Then update all error paths to use this helper:

```python
from app.services.monitoring_helpers import safe_record_metric

except Exception as e:
    log.error(f"Subscription check failed: {e}")
    safe_record_metric(
        "subscription_check_failures",
        labels={"endpoint": endpoint, "error_type": type(e).__name__}
    )
    # Continue processing
```

### Testing:
Add to `tests/test_subscription_helpers.py`:

```python
import pytest
from unittest.mock import Mock, patch
from app.core.subscription_helpers import check_subscription_access
from app.services.chat_monitoring import chat_monitoring

def test_graceful_degradation_with_monitoring_failure():
    """
    Verify that monitoring failures don't break graceful degradation.
    """
    user = Mock(id=1, subscription_tier="free")
    subscription_manager = Mock()

    # Make subscription check fail
    subscription_manager.check_api_access.side_effect = Exception("DB error")

    # Make metric recording also fail
    with patch.object(chat_monitoring, 'record_counter', side_effect=Exception("Metric error")):
        # Should not raise exception - graceful degradation
        result = check_subscription_access(user, subscription_manager, "/test")

        # Should allow access despite failures (graceful degradation)
        assert result is True
```

---

## Deployment Checklist

### Pre-Deployment:
- [ ] All tests passing
- [ ] Code review completed
- [ ] Documentation updated
- [ ] Staging deployment successful
- [ ] Performance testing completed

### Deployment:
- [ ] Deploy to production
- [ ] Monitor error rates
- [ ] Verify token estimation accuracy
- [ ] Check billing records
- [ ] Monitor user feedback

### Post-Deployment:
- [ ] Verify fixes in production
- [ ] Update changelog
- [ ] Notify users of improvements
- [ ] Monitor for 24 hours
- [ ] Document lessons learned

---

## Rollback Plan

If issues occur after deployment:

1. **Immediate Rollback**:
   ```bash
   # Revert to previous version
   kubectl rollout undo deployment/ontologic-api
   ```

2. **Verify Rollback**:
   ```bash
   # Check health
   curl http://api.ontologic.ai/health
   ```

3. **Investigate**:
   - Check logs for errors
   - Review metrics for anomalies
   - Analyze user reports

4. **Fix and Redeploy**:
   - Fix issues in development
   - Test thoroughly
   - Deploy again

---

**End of Quick Fixes**
