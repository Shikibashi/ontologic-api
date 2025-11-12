# Test Suite Maintenance Guidelines

## Overview

This document provides guidelines for maintaining the ontologic-api test suite to prevent regression and ensure continued reliability. These guidelines are based on the comprehensive fixes applied during the test-suite-fixes implementation.

## Critical Maintenance Rules

### 1. DateTime Handling (CRITICAL)

**Rule**: Always use proper datetime imports and timezone-aware datetime objects.

**Correct Pattern**:
```python
from datetime import datetime, timezone

# Correct usage
timestamp = datetime.now(timezone.utc)
```

**Incorrect Pattern** (NEVER USE):
```python
from datetime import datetime

# WRONG - will cause AttributeError
timestamp = datetime.datetime.now(datetime.timezone.utc)
```

**Files to Monitor**: Any new files in `app/core/`, `app/services/`, `app/utils/`, `app/workflow_services/`

### 2. Philosopher Name Validation

**Rule**: Always use normalized philosopher names that match the system configuration.

**Valid Philosopher Names**:
- "Aristotle"
- "Immanuel Kant" 
- "David Hume"
- "John Locke"
- "Friedrich Nietzsche"
- "Meta Collection"

**Test Data Updates**: When updating test fixtures, ensure philosopher names match exactly.

### 3. Service Mocking Patterns

**Rule**: Use consistent async-aware mocking for all services.

**Correct Pattern**:
```python
from unittest.mock import AsyncMock, MagicMock

# For async services
mock_service = AsyncMock()

# For sync services  
mock_service = MagicMock()
```

### 4. Database Model Testing

**Rule**: Always use proper timezone-aware datetime defaults in model tests.

**Pattern**:
```python
# Model definition
created_at: datetime = Field(
    default_factory=lambda: datetime.now(timezone.utc),
    sa_column=Column(DateTime(timezone=True), server_default=func.now())
)
```

## Test Categories and Maintenance

### High-Reliability Categories (100% Success Rate)

These categories should NEVER regress:

1. **Philosophy Prompts** (`test_ask_philosophy_prompts.py`)
   - Monitor for philosopher name changes
   - Validate collection parameter handling
   - Check response structure consistency

2. **API Endpoints** (`test_ask_and_query_endpoints.py`)
   - Validate parameter forwarding
   - Check error handling consistency
   - Monitor authentication requirements

3. **Authentication** (`test_auth_router.py`)
   - Validate status code expectations
   - Check session handling
   - Monitor OAuth flow changes

### Medium-Reliability Categories (Needs Monitoring)

1. **Payment System Tests**
   - Monitor service initialization patterns
   - Validate Stripe API mocking
   - Check database model creation

2. **Chat System Tests**
   - Monitor service availability
   - Validate vector store integration
   - Check database connections

## Pytest Configuration Maintenance

### Warning Filters

Keep these warning filters updated in `pytest.ini`:

```ini
filterwarnings =
    ignore::DeprecationWarning
    ignore::PendingDeprecationWarning
    ignore:.*datetime.datetime.utcnow.*:DeprecationWarning
    ignore:.*builtin type.*:DeprecationWarning
    ignore:coroutine.*was never awaited:RuntimeWarning
    ignore::DeprecationWarning:sqlalchemy.*
```

**Never Add**: `SADeprecationWarning` (not a valid warning type)

### Test Markers

Maintain these markers for test categorization:

```ini
markers =
    llm_test: Tests that involve LLM interactions
    qdrant_test: Tests that involve Qdrant vector database
    integration: Integration tests requiring multiple services
    philosophy_prompt: Tests for specific philosophy prompts
    payment: Tests for payment system functionality
    unit: Unit tests for individual components
```

## Common Issues and Solutions

### Issue 1: DateTime AttributeError

**Symptom**: `AttributeError: type object 'datetime.datetime' has no attribute 'datetime'`

**Solution**:
1. Check import: `from datetime import datetime, timezone`
2. Fix usage: `datetime.now(timezone.utc)`
3. Update all occurrences in the file

### Issue 2: Philosopher Name Mismatch

**Symptom**: Tests failing with "Invalid collection" or philosopher not found

**Solution**:
1. Use exact names from philosopher loader
2. Update test fixtures with valid names
3. Check collection normalization logic

### Issue 3: Service Initialization Failures

**Symptom**: "Service not available" or initialization errors

**Solution**:
1. Check service startup dependencies
2. Validate mock configurations
3. Ensure proper async handling

### Issue 4: Payment Service Attribute Errors

**Symptom**: AttributeError for service attributes

**Solution**:
1. Use public attributes (not private `_` prefixed)
2. Check service initialization patterns
3. Validate mock attribute setup

## Test Health Monitoring

### Daily Checks

Run these commands to monitor test health:

```bash
# Quick health check (core functionality)
uv run python -m pytest tests/test_ask_philosophy_prompts.py tests/test_ask_and_query_endpoints.py tests/test_auth_router.py --tb=no -q

# Full suite summary
uv run python -m pytest tests/ --tb=no -q | tail -1
```

### Weekly Checks

```bash
# Performance check
time uv run python -m pytest tests/test_ask_philosophy_prompts.py --tb=no -q

# Consistency check (run twice, compare results)
uv run python -m pytest tests/test_collection_normalization.py --tb=no -q
```

### Monthly Reviews

1. Review test success rates by category
2. Check for new deprecation warnings
3. Validate test execution times
4. Update test fixtures if needed

## Regression Prevention

### Code Review Checklist

When reviewing code changes:

- [ ] Check datetime imports and usage
- [ ] Validate philosopher names in test data
- [ ] Ensure proper async/await patterns
- [ ] Check service initialization patterns
- [ ] Validate database model changes

### Pre-commit Hooks (Recommended)

```bash
# Check for datetime issues
grep -r "datetime\.datetime\.now" app/ && echo "FAIL: Fix datetime usage" || echo "PASS"

# Check for invalid philosopher names
grep -r "Ethics Core\|Business Ethics" tests/ && echo "FAIL: Fix philosopher names" || echo "PASS"
```

## Emergency Procedures

### If Test Suite Breaks

1. **Identify Scope**: Run quick health check to see affected categories
2. **Check Recent Changes**: Review recent commits for datetime/service changes
3. **Apply Quick Fixes**: Use patterns from this guide
4. **Validate Fix**: Run affected test category to confirm
5. **Full Validation**: Run complete suite once fixes are applied

### Rollback Procedure

If fixes cause new issues:

1. Revert datetime changes: `git checkout HEAD~1 -- app/core/db_models.py`
2. Revert pytest config: `git checkout HEAD~1 -- pytest.ini`
3. Run validation: `uv run python -m pytest tests/test_ask_philosophy_prompts.py`
4. Investigate root cause before re-applying fixes

## Success Metrics

### Target Metrics

- **Overall Success Rate**: >75%
- **Core Categories**: 100% (Philosophy, Endpoints, Auth)
- **Test Execution Time**: <30 seconds for full suite
- **Consistency**: Same results across multiple runs

### Alert Thresholds

- **Critical**: Core category success rate drops below 95%
- **Warning**: Overall success rate drops below 65%
- **Info**: New deprecation warnings appear

## Contact and Escalation

For test suite issues:

1. **First**: Check this maintenance guide
2. **Second**: Review TEST_SUITE_VALIDATION_REPORT.md
3. **Third**: Check recent commits for breaking changes
4. **Last Resort**: Revert to last known good state and investigate

Remember: The test suite is a critical quality gate. Maintaining its reliability is essential for development velocity and product quality.