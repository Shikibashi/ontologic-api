## Why
Enabling the `refeed` behavior improves retrieval quality by first retrieving top meta nodes from the "Meta Collection" and then enriching the sub-collection query with that context.

## What Changes
- Implement meta refeed in `QdrantManager.gather_points_and_sort` when `refeed=true`
- Respect the `refeed` query parameter in `/ask_philosophy` and `/query_hybrid`
- Maintain current defaults but enable the intended `refeed` functionality

## Impact
- Affected specs: `specs/ontologic-api/spec.md` (POST /ask_philosophy, POST /query_hybrid)
- Affected code: `app/services/qdrant_manager.py`, `app/router/ontologic.py`
