## ADDED Requirements

### Requirement: GET /health — Comprehensive Health Check
The system SHALL expose a GET endpoint `/health` that returns overall system status and individual service statuses.

#### Scenario: All critical services healthy
- **WHEN** database, Qdrant, and LLM services are healthy
- **THEN** the endpoint returns 200
- **AND** `status` equals `healthy`
- **AND** each critical service status equals `healthy`

#### Scenario: One or more critical services unhealthy
- **WHEN** any of database, Qdrant, or LLM is unhealthy or error
- **THEN** the endpoint returns 503
- **AND** `status` equals `unhealthy`
- **AND** individual service objects include `status` and `message`

#### Scenario: Non-critical service degraded
- **WHEN** Redis cache is disabled or unhealthy but critical services are healthy
- **THEN** the endpoint returns 200
- **AND** overall `status` equals `healthy`
- **AND** redis status is `disabled` or `unhealthy`

#### Scenario: Chat history feature error isolation
- **WHEN** chat history health check raises an exception
- **THEN** overall status calculation ignores chat history error for availability
- **AND** `services.chat_history.status` is `error`

### Requirement: GET /health/ready — Readiness Probe
The system SHALL expose a GET endpoint `/health/ready` that reports readiness based solely on critical services.

#### Scenario: All critical services ready
- **WHEN** database, Qdrant, and LLM are healthy
- **THEN** the endpoint returns 200
- **AND** payload `{ "status": "ready" }`

#### Scenario: Any critical service not ready
- **WHEN** at least one of database, Qdrant, or LLM is unhealthy, error, or timeout
- **THEN** the endpoint returns 503
- **AND** payload `{ "status": "not ready" }`

#### Scenario: Unexpected exception handling
- **WHEN** an unexpected exception occurs during readiness gathering
- **THEN** the endpoint returns 503
- **AND** payload includes `error` field with message

### Requirement: GET /health/live — Liveness Probe
The system SHALL expose a GET endpoint `/health/live` that always reports application liveness unless the process is failing.

#### Scenario: Application alive
- **WHEN** the FastAPI process is running
- **THEN** the endpoint returns 200
- **AND** payload `{ "status": "alive" }`

### Requirement: Query Expansion Methods
The system SHALL support multiple query expansion methods for retrieval enhancement: `hyde`, `rag_fusion`, `self_ask`, and `prf`.

#### Scenario: Default methods selection
- **WHEN** expand_query is invoked without specifying methods
- **THEN** the system uses a default method set including `hyde`, `rag_fusion`, `self_ask`

#### Scenario: HyDE generation fallback
- **WHEN** HyDE LLM content generation fails
- **THEN** the method returns a single query tagged with `[expansion_failed:hyde]`
- **AND** expansion continues with other methods

#### Scenario: RAG-Fusion multi-query generation
- **WHEN** `rag_fusion` executes successfully
- **THEN** multiple diverse query reformulations are generated (up to configured limit)
- **AND** original query is included among queries

#### Scenario: Self-Ask decomposition
- **WHEN** `self_ask` executes successfully
- **THEN** the method generates at least the original query plus zero or more sub-questions

#### Scenario: PRF enhancement
- **WHEN** `prf` is requested and initial retrieval returns results
- **THEN** a PRF-enhanced query is generated using key term extraction

#### Scenario: PRF no-results short-circuit
- **WHEN** initial retrieval returns no results
- **THEN** PRF returns an empty expanded query list and empty results

### Requirement: ExpansionService Parallel Execution & Fusion
The system SHALL execute enabled expansion methods in parallel, collect their results, and fuse them using Reciprocal Rank Fusion (RRF) when multiple result sets are available.

#### Scenario: Parallel execution timing
- **WHEN** two or more methods run
- **THEN** total parallel time is measured
- **AND** per-method durations are recorded in metadata

#### Scenario: RRF fusion across methods
- **WHEN** two or more methods return non-empty results
- **THEN** results are fused using RRF with parameter `rrf_k`
- **AND** deduplication occurs before limiting final results

#### Scenario: Single method short-circuit
- **WHEN** only one method returns results
- **THEN** fusion is skipped
- **AND** deduplicated results are returned directly

#### Scenario: All methods fail gracefully
- **WHEN** all methods error or produce only failure-tagged queries
- **THEN** final `retrieval_results` is an empty list
- **AND** metadata reflects zero final results

### Requirement: Modern vs Legacy Expansion Pipeline Selection
The system SHALL select between a modern (feature-flagged) expansion pipeline and the legacy pipeline based on configuration.

#### Scenario: Modern pipeline enabled
- **WHEN** feature flag `use_llama_index_workflows` is true
- **THEN** expand_query uses modern path `_expand_query_modern`
- **AND** metadata.pipeline equals `modern_llamaindex`

#### Scenario: Modern pipeline failure fallback
- **WHEN** modern pipeline raises ImportError or unexpected exception
- **THEN** system falls back to legacy path `_expand_query_legacy`
- **AND** operation completes without raising to caller

#### Scenario: Legacy pipeline default
- **WHEN** feature flag is absent or false
- **THEN** legacy pipeline executes
- **AND** metadata includes `methods_used` and `parallel_speedup`

### Requirement: ExpansionResult Metadata Integrity
The system SHALL return an ExpansionResult with consistent metadata fields for observability.

#### Scenario: Required metadata fields
- **WHEN** expansion completes (any path)
- **THEN** metadata includes at least: `methods_used`, `total_expanded_queries`, `results_before_fusion`, `results_after_dedup`, `final_results`

#### Scenario: Performance metrics presence
- **WHEN** two or more methods succeed
- **THEN** metadata includes `parallel_execution_time`, `parallel_speedup`, and `method_timings`

### Requirement: Rate Limiting Policies
The system SHALL enforce per-endpoint rate limits using SlowAPI with the configured limiter.

#### Scenario: Base model query rate limit
- **WHEN** a client exceeds 30 requests per minute to `/ask`
- **THEN** subsequent requests within the window return 429
- **AND** the response body indicates a rate limit error

#### Scenario: Philosophy answer rate limit
- **WHEN** a client exceeds 10 requests per minute to `/ask_philosophy`
- **THEN** subsequent requests within the window return 429

#### Scenario: Hybrid query rate limit
- **WHEN** a client exceeds 20 requests per minute to `/query_hybrid`
- **THEN** subsequent requests within the window return 429

#### Scenario: Get philosophers rate limit
- **WHEN** a client exceeds 60 requests per minute to `/get_philosophers`
- **THEN** subsequent requests within the window return 429

#### Scenario: Workflow draft creation rate limit
- **WHEN** a client exceeds 5 requests per minute to `/workflows/create`
- **THEN** subsequent requests within the window return 429

### Requirement: Error Contract Consistency
The system SHALL return structured error responses with `detail` for HTTPExceptions and service-specific messages.

#### Scenario: Validation error formatting
- **WHEN** a request fails FastAPI/Pydantic validation
- **THEN** the response status is 422
- **AND** response contains a JSON body with `detail` listing validation issues

#### Scenario: Not found errors
- **WHEN** a resource (draft or review) is not found
- **THEN** the response status is 404
- **AND** `detail` contains a human-readable message referencing the missing resource

#### Scenario: Service unavailable errors
- **WHEN** dependent upstream services (LLM, Qdrant) are unavailable
- **THEN** endpoints raise 503
- **AND** `detail` communicates temporary unavailability

#### Scenario: Internal server errors
- **WHEN** an unexpected exception occurs
- **THEN** the response status is 500
- **AND** `detail` is a generic message without leaking implementation details

### Requirement: Workflow Draft Lifecycle Endpoints
The system SHALL provide endpoints under `/workflows` for draft creation, section generation, review, applying suggestions, listing, status retrieval, and review data access.

#### Scenario: Create draft success
- **WHEN** valid draft metadata is POSTed to `/workflows/create`
- **THEN** response includes `draft_id`, `status='created'`, and success message

#### Scenario: Generate sections partial success
- **WHEN** some requested sections generate successfully and others fail
- **THEN** response lists `sections_generated` and `sections_failed`
- **AND** `final_status` reflects overall progress

#### Scenario: Draft status retrieval
- **WHEN** GET `/workflows/{draft_id}/status` is called for an existing draft
- **THEN** response includes progress map, section content keys, and review indicators

#### Scenario: AI review success
- **WHEN** POST `/workflows/{draft_id}/ai-review` with valid rubric
- **THEN** response includes `review_id`, `summary`, and `blocking_issues`

#### Scenario: Apply suggestions selective
- **WHEN** POST `/workflows/{draft_id}/apply` with specific `suggestion_ids`
- **THEN** only those suggestions are applied and response reflects updated counts

#### Scenario: List drafts pagination
- **WHEN** GET `/workflows?limit=5&offset=5`
- **THEN** response includes at most 5 drafts starting from offset 5
- **AND** returns `total_returned`, `offset`, and `limit`

#### Scenario: Review data retrieval
- **WHEN** GET `/workflows/{draft_id}/review` is called and review data exists
- **THEN** response includes `review_data`, `suggestions`, and `review_summary`

#### Scenario: Missing review data
- **WHEN** GET `/workflows/{draft_id}/review` is called before review runs
- **THEN** response status is 404 with `detail` = "No review data found for this draft"
