## Why
Health endpoints and query expansion behaviors exist in code but are not specified.

## What Changes
- Add requirements for /health, /health/ready, /health/live endpoints
- Add requirements for query expansion methods (HyDE, RAG-Fusion, Self-Ask, PRF)
- Add requirement for ExpansionService fallback behavior and feature flag

## Impact
- Affected specs: ontologic-api
- Affected code: app/router/health.py, app/services/expansion_service.py
