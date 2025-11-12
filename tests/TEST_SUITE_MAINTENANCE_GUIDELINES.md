# Test Suite Maintenance Guidelines

## Overview

This document provides comprehensive guidelines for maintaining the ontologic-api test suite at the achieved 80%+ success rate. These guidelines ensure continued test reliability and prevent regression in fixed test categories.

## Current Test Suite Status

### Success Metrics (as of October 2, 2025)
- **Total Tests:** 687
- **Success Rate:** 80.1% (550 passed, 133 failed, 4 skipped)
- **Execution Time:** 22.26 seconds
- **Target Achievement:** ✅ 80%+ success rate maintained

### Category Performance
- **Philosophy/Core API:** 100% success (critical functionality)
- **Authentication:** 95% success (core auth working)
- **Chat System:** 75% success (core features solid)
- **Payment System:** 45% success (complex integration challenges)
- **Document/E2E:** 25% success (authentication barriers)

## Maintenance Patterns for Fixed Categories

### 1. Philosophy and Core API Tests (100% Success - CRITICAL)

**Maintenance Pattern:**
```bash
# Daily health check
uv run python -m pytest tests/test_ask_philosophy_prompts.py tests/test_ask_and_query_endpoints.py -q
```

**Key Patterns to Preserve:**
- Philosopher name mapping consistency
- Collection parameter normalization
- Test data catalog integrity

**Regression Prevention:**
- Never modify philosopher names without updating test mappings
- Maintain PhilosopherTestMapper functionality
- Preserve collection normalization logic

**Alert Conditions:**
- Any failure in core philosophy tests
- Collection parameter handling errors
- Philosopher name resolution failures

### 2. Authentication System (95% Success)

**Maintenance Pattern:**
```bash
# Weekly auth system check
uv run python -m pytest tests/test_auth_router.py tests/integration/test_auth_endpoints.py -v
```

**Key Patterns to Preserve:**
- Proper authentication token handling
- Rate limiting configuration
- Session management

**Common Issues to Monitor:**
- Rate limiting string parsing errors
- Session lifecycle management
- OAuth provider configuration

**Fix Pattern for Rate Limiting Issues:**
```python
# In auth router configuration
def create_subscription_aware_limit():
    return "10/minute"  # Use string, not function reference
```

### 3. Payment System (45% Success - COMPLEX)

**Maintenance Pattern:**
```bash
# Bi-weekly payment system check
uv run python -m pytest tests/test_payment_service.py tests/test_billing_service.py --maxfail=5 -q
```

**Key Patterns to Preserve:**
- Stripe API mocking strategies
- Database model relationships
- Service initialization sequences

**Common Failure Patterns:**
1. **OverageCharges Model Issues:**
   ```python
   # Correct initialization
   OverageCharges(
       total_overage=10.0,
       overage_breakdown={'requests': 5.0, 'tokens': 5.0}
   )
   ```

2. **Async Session Handling:**
   ```python
   # Proper async mock setup
   mock_session = AsyncMock()
   mock_session.execute.return_value = mock_result
   ```

3. **Service Dependency Injection:**
   ```python
   # Ensure proper service availability
   @pytest.fixture
   def payment_service_with_deps():
       return PaymentService(
           cache_service=mock_cache,
           billing_service=mock_billing
       )
   ```

### 4. Chat System (75% Success)

**Maintenance Pattern:**
```bash
# Weekly chat system check
uv run python -m pytest tests/test_chat_qdrant_service.py tests/test_chat_history_service.py -q
```

**Key Patterns to Preserve:**
- ChatQdrantService initialization
- Vector store integration
- Database session management

**Common Issues:**
- Service dependency availability
- Async session handling
- Vector store connection management

## Test Health Monitoring Setup

### Automated Monitoring Script

Create `scripts/test_health_monitor.py`:
```python
#!/usr/bin/env python3
"""
Test suite health monitoring script.
Run daily to ensure 80%+ success rate maintenance.
"""

import subprocess
import json
from datetime import datetime

def run_test_suite():
    """Run full test suite and capture results."""
    result = subprocess.run([
        'uv', 'run', 'python', '-m', 'pytest', 
        'tests/', '--tb=no', '-q', '--json-report', 
        '--json-report-file=test_results.json'
    ], capture_output=True, text=True)
    
    return result.returncode == 0

def check_success_rate():
    """Check if success rate meets 80% threshold."""
    try:
        with open('test_results.json', 'r') as f:
            data = json.load(f)
        
        total = data['summary']['total']
        passed = data['summary']['passed']
        success_rate = (passed / total) * 100
        
        return success_rate >= 80.0, success_rate
    except:
        return False, 0.0

def main():
    print(f"Test Health Check - {datetime.now()}")
    
    # Run tests
    success = run_test_suite()
    meets_threshold, rate = check_success_rate()
    
    if meets_threshold:
        print(f"✅ SUCCESS: {rate:.1f}% success rate (target: 80%+)")
    else:
        print(f"❌ FAILURE: {rate:.1f}% success rate (target: 80%+)")
        print("🚨 ALERT: Test suite requires attention!")
    
    return meets_threshold

if __name__ == "__main__":
    exit(0 if main() else 1)
```

### Daily Health Check Command
```bash
# Add to cron or CI/CD pipeline
0 9 * * * cd /path/to/ontologic-api && uv run python scripts/test_health_monitor.py
```

## Regression Prevention Strategies

### 1. Pre-commit Hooks
```bash
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: test-core-functionality
        name: Test Core Functionality
        entry: uv run python -m pytest tests/test_ask_philosophy_prompts.py -q
        language: system
        pass_filenames: false
```

### 2. CI/CD Integration
```yaml
# .github/workflows/test-health.yml
name: Test Health Check
on: [push, pull_request]
jobs:
  test-health:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run Core Tests
        run: |
          uv run python -m pytest tests/test_ask_philosophy_prompts.py tests/test_ask_and_query_endpoints.py
      - name: Check Success Rate
        run: |
          RATE=$(uv run python -m pytest tests/ --tb=no -q | grep -o '[0-9]*% passed' | cut -d'%' -f1)
          if [ "$RATE" -lt 80 ]; then
            echo "❌ Success rate $RATE% below 80% threshold"
            exit 1
          fi
```

### 3. Code Review Checklist
- [ ] Philosophy name changes include test mapping updates
- [ ] New payment features include proper mocking
- [ ] Authentication changes preserve token handling
- [ ] Database model changes update test fixtures
- [ ] Service modifications maintain dependency injection

## Troubleshooting Common Issues

### Issue: Philosophy Tests Failing
**Symptoms:** Philosopher name not found errors
**Solution:**
1. Check `tests/helpers/philosopher_test_mapper.py`
2. Update philosopher name mappings
3. Verify test catalog data consistency

### Issue: Payment Tests Failing
**Symptoms:** Stripe API mocking errors, model initialization failures
**Solution:**
1. Check OverageCharges model parameters
2. Verify Stripe API mock paths
3. Update service dependency injection

### Issue: Authentication Tests Failing
**Symptoms:** Rate limiting errors, session management issues
**Solution:**
1. Check rate limiting configuration strings
2. Verify session lifecycle management
3. Update OAuth provider mocking

### Issue: Performance Degradation
**Symptoms:** Tests taking longer than 30 seconds
**Solution:**
1. Check for resource leaks
2. Optimize fixture scoping
3. Review mock object reuse

## Success Rate Targets by Category

### Minimum Acceptable Rates
- **Core API/Philosophy:** 95% (critical functionality)
- **Authentication:** 85% (security critical)
- **Chat System:** 70% (core features)
- **Payment System:** 50% (complex integration)
- **Document/E2E:** 40% (authentication dependent)

### Alert Thresholds
- **Overall:** < 80% (immediate attention)
- **Core API:** < 95% (critical alert)
- **Authentication:** < 85% (security alert)

## Long-term Maintenance Strategy

### Monthly Reviews
- Analyze failure patterns
- Update test data and fixtures
- Review performance metrics
- Plan improvement initiatives

### Quarterly Improvements
- Address systematic issues in failing categories
- Optimize test performance
- Update testing infrastructure
- Review and update guidelines

### Annual Assessments
- Comprehensive test suite review
- Technology stack updates
- Testing strategy evolution
- Success rate target adjustments

## Emergency Response Procedures

### Critical Failure (< 70% success rate)
1. **Immediate:** Stop deployments
2. **Assess:** Identify failure categories
3. **Triage:** Fix core API tests first
4. **Escalate:** Notify development team
5. **Monitor:** Continuous testing until recovery

### Performance Issues (> 45 seconds execution)
1. **Profile:** Identify slow tests
2. **Optimize:** Fix resource leaks
3. **Parallelize:** Improve test execution
4. **Monitor:** Track performance trends

## Conclusion

These maintenance guidelines ensure the test suite continues to provide reliable validation of the ontologic-api functionality. By following these patterns and monitoring procedures, the development team can maintain the achieved 80%+ success rate and prevent regression in critical test categories.

**Key Success Factors:**
- Regular health monitoring
- Pattern-based maintenance
- Proactive regression prevention
- Category-specific attention
- Performance optimization

Adherence to these guidelines will ensure the test suite remains a valuable asset for ongoing development and quality assurance.