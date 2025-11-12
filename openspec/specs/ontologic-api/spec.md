# Ontologic API

## Purpose

Philosophy-focused API providing LLM querying and hybrid vector retrieval from Qdrant collections of philosophical texts. Supports both direct LLM queries and context-aware retrieval with persona modes.
## Requirements
### Requirement: GET /ask — Base LLM query
The system SHALL expose a GET endpoint `/ask` that queries the base LLM with a plain text prompt using lifespan-managed dependencies.

#### Scenario: Query with lifespan-managed LLM service
- **WHEN** `query_str` is provided and `temperature` is omitted
- **THEN** the system uses LLMManager from `app.state` instead of singleton
- **AND** temperature defaults to `0.30` and is enforced in `(0, 1)`
- **AND** the system returns the model response text

#### Scenario: Temperature bounds enforced
- **WHEN** `temperature` is provided outside `(0, 1)`
- **THEN** FastAPI validation rejects the request with a 422 error

#### Scenario: Service unavailable handling
- **WHEN** LLMManager is unavailable due to startup failure
- **THEN** endpoint returns 503 Service Unavailable
- **AND** response includes health check endpoint reference

### Requirement: GET /get_philosophers — List available collections
The system SHALL expose a GET endpoint `/get_philosophers` that lists available Qdrant collections used as “philosophers”.

#### Scenario: Exclude meta/combined collections
- WHEN collections are listed from Qdrant
- THEN the response excludes `Meta Collection` and `Combined Collection`
- AND returns a JSON array of strings (collection names)

Examples
- Request:
```bash
curl -s "http://localhost:8080/get_philosophers"
```
- Response:
```json
["Aristotle", "Plato", "Kant"]
```

### Requirement: POST /ask_philosophy — Q&A with retrieval, optional immersion, and optional user/PDF context
The system SHALL expose a POST endpoint `/ask_philosophy` that performs hybrid retrieval from Qdrant and generates an answer via the LLM using modern service management.

- Request body: `HybridQueryRequest` (pydantic)
  - query_str: string (required)
  - collection: string (required)  
  - vector_types: list[string] (optional; default per collection rules)
  - filter: object (optional; field=value or field=[values])
  - payload: list[string] (optional; payload fields to include)
  - conversation_history: list[ConversationMessage] (optional)
- Query params:
  - refeed: bool (default true; see implementation note below)
  - immersive: bool (default false)
  - temperature: float in (0, 1), default 0.30
- Response: `AskPhilosophyResponse { text: string, raw: object }`

#### Scenario: Answer with modern retrieval pipeline
- **WHEN** a valid `HybridQueryRequest` is submitted with new pipeline enabled
- **THEN** the system uses QueryFusionRetriever from `app.state.expansion`
- **AND** retrieval uses 4-query expansion with RRF fusion
- **AND** generates an answer using lifespan-managed LLM
- **AND** returns `text` plus `raw` usage/metrics

#### Scenario: Service dependency availability
- **WHEN** required services (Qdrant, LLM) are unavailable due to startup failure
- **THEN** endpoint returns 503 Service Unavailable
- **AND** response indicates which services are unavailable

#### Scenario: Immersive persona mode
- **WHEN** `immersive=true`
- **THEN** the system responds in the style of the specified `collection` (philosopher persona)

#### Scenario: Temperature bounds enforced  
- **WHEN** `temperature` is provided outside `(0, 1)`
- **THEN** FastAPI validation rejects the request with a 422 error

#### Scenario: Conversation history included
- **WHEN** `conversation_history` is provided
- **THEN** the LLM includes it in context during answer generation

### Requirement: POST /query_hybrid — Hybrid retrieval and optional vetting
The system SHALL expose a POST endpoint `/query_hybrid` that performs hybrid vector retrieval with optional LLM vetting using modern service architecture.

- Request body: `HybridQueryRequest` (pydantic)
- Query params:
  - vet_mode: bool (default false) — when true and `raw_mode=false`, the LLM selects most relevant node IDs
  - raw_mode: bool (default false) — when true, raw results are returned (mutually exclusive with vet_mode)  
  - refeed: bool (default true) — see note below
  - limit: int in [1, 100], default 10
  - temperature: float in (0, 1), default 0.30 (used during vetting)

#### Scenario: Modern retrieval with service state
- **WHEN** `vet_mode=false` and `raw_mode=false`
- **THEN** the system uses ExpansionService from `app.state`
- **AND** response is a list of top nodes across vector types, length ≤ `limit`
- **AND** modern or legacy retrieval pipeline is used based on feature flag

#### Scenario: Service availability validation
- **WHEN** required services are unavailable in `app.state`
- **THEN** endpoint returns 503 Service Unavailable
- **AND** health endpoint provides service status details

#### Scenario: Raw grouped results
- **WHEN** `raw_mode=true`
- **THEN** the response is a JSON object keyed by vector types with arrays of nodes as values
- **AND** if `refeed=true` and `collection != "Meta Collection"`, meta results MAY be included under `"Meta Collection"` (see note)

#### Scenario: LLM-vetted selection
- **WHEN** `vet_mode=true` and `raw_mode=false`
- **THEN** the system performs LLM vetting over retrieved nodes using lifespan-managed LLM and returns the vetted response

#### Scenario: Parameter validation
- **WHEN** `limit` is outside [1, 100] or `temperature` is outside `(0, 1)`
- **THEN** FastAPI validation rejects the request with a 422 error

### Requirement: Hybrid retrieval rules — Vector types and filters
The system SHALL construct hybrid queries based on collection and vector type semantics.

#### Scenario: Vector types per collection
- WHEN `collection != "Meta Collection"`
- THEN default vector_types include: `sparse_original`, `sparse_summary`, `sparse_conjecture`, `dense_original`, `dense_summary`, `dense_conjecture`
- WHEN `collection == "Meta Collection"`
- THEN default vector_types include: `sparse_original`, `sparse_summary`, `dense_original`, `dense_summary`

#### Scenario: Payload filter semantics
- WHEN `filter` is provided as `{ field: value }` or `{ field: [values...] }`
- THEN Qdrant MUST apply logical AND across fields and OR across list values within a field

### Requirement: CORS and trusted hosts
The system SHALL configure CORS and trusted hosts for the API server.

#### Scenario: Allow configured origins and hosts
- WHEN a request originates from an allowed origin (`http://localhost:5173`, `http://localhost:5174`, `https://www.ontologicai.com`, `https://ontologicai.com`) or allowed host (`api.ontologicai.com`, `localhost`, `www.ontologicai.com`)
- THEN the request is permitted by the CORS middleware and TrustedHostMiddleware
- AND a request from a non-configured origin or host is rejected (non-normative note)

### Requirement: Chat history and user document context (integrated)
The system SHALL optionally attribute chat messages and retrieval context to a username and MAY enrich chat/QA answers with user-uploaded document chunks when enabled.

#### Scenario: Store message with username
- WHEN a chat message is stored with a username
- THEN the username is persisted alongside session_id and indexed for retrieval

#### Scenario: Store message without username
- WHEN a chat message omits username
- THEN it is stored with username=NULL and behavior remains backward compatible

#### Scenario: Retrieve history filtered by username
- WHEN history is requested with both session_id and username
- THEN only messages matching both are returned

#### Scenario: Semantic search includes PDF context
- WHEN a user performs chat search with include_pdf_context=true and feature flag enabled
- THEN relevant PDF chunks from that user's uploaded documents are retrieved and merged into results with source attribution

#### Scenario: Feature flag disabled for PDF context
- WHEN include_pdf_context=true but flag is off
- THEN PDF retrieval is skipped and only chat messages are searched

#### Scenario: Graceful handling of no documents
- WHEN a user has no documents uploaded and PDF context is requested
- THEN the operation succeeds with only chat results

#### Scenario: Allowed hosts
- WHEN a request originates from `api.ontologicai.com`, `localhost`, or `www.ontologicai.com`
- THEN the request is allowed by the TrustedHostMiddleware

#### Scenario: Allowed origins
- WHEN a browser request originates from `http://localhost:5173`, `http://localhost:5174`, `https://www.ontologicai.com`, or `https://ontologicai.com`
- THEN the request is allowed by CORS configuration

### Requirement: Database schema includes username fields (NEW)

The system SHALL store username as an optional indexed field in chat-related database tables.

#### Scenario: ChatConversation includes username

- WHEN a new conversation is created
- THEN the conversation record includes a nullable username field
- AND the username is indexed for efficient queries

#### Scenario: ChatMessage includes username

- WHEN a new message is stored
- THEN the message record includes a nullable username field
- AND the username is indexed for efficient queries
- AND composite index (username, created_at) supports user history queries

### Requirement: Paper draft and review workflows with user context tracking (NEW)

The system SHALL support optional username attribution across paper draft generation and review workflows.

#### Scenario: Create draft with username

- WHEN a draft is created with a username field in the request
- THEN the draft is stored with username in the paper_drafts table
- AND username is indexed for efficient filtering

#### Scenario: Create draft without username (backward compatible)

- WHEN a draft is created without specifying username
- THEN the draft is stored with username=NULL
- AND existing clients continue functioning

#### Scenario: Generate sections with ownership validation

- WHEN sections are generated for a draft_id and username is provided
- THEN the system verifies the draft's stored username (if present) matches the provided username
- AND rejects with 403 if mismatch occurs

#### Scenario: Review draft with user context

- WHEN /workflows/{draft_id}/ai-review is called with matching username
- THEN the review workflow proceeds normally
- AND MAY incorporate user-uploaded document context in future enhancements (non-normative note)

#### Scenario: Apply suggestions with ownership validation

- WHEN /workflows/{draft_id}/apply is called with a username
- THEN the system verifies ownership before applying suggestions
- AND rejects with 403 if username mismatch

#### Scenario: List drafts filtered by username

- WHEN /workflows endpoint is queried with username parameter
- THEN only drafts belonging to that username are returned
- AND pagination parameters (limit, offset) remain supported

#### Scenario: Unauthorized draft access

- WHEN a draft operation (status, review, generate, apply) is attempted with a different username than stored
- THEN the system returns 403 Forbidden

### Requirement: Integrated workflow testing for documents, chat, and review (NEW)

The system SHALL provide end-to-end support for a user to (a) upload documents, (b) generate a research paper draft, (c) perform an AI review, and (d) conduct chat queries enriched by uploaded document context.

#### Scenario: End-to-end paper generation with prior PDF upload
- WHEN a user uploads a PDF document with philosophical content
- AND then creates a paper draft with the same username
- AND generates all sections
- THEN the draft workflow completes through GENERATED status without errors
- AND the system logs (non-normative) that document context is available for potential future integration

#### Scenario: Review after document upload
- WHEN a draft reaches GENERATED status for a username with uploaded documents
- AND the user invokes /workflows/{draft_id}/ai-review with the same username
- THEN the review completes successfully with REVIEWED status
- AND suggestions are generated (≥ 1) unless content is trivially empty

#### Scenario: Chat query referencing uploaded document
- WHEN the user performs POST /chat/search with include_pdf_context=true and username
- AND the user has at least one uploaded document
- THEN the response contains at least one result with source="pdf" (assuming embedding and similarity above internal threshold)

#### Scenario: Ask philosophy with document context
- WHEN the user calls /ask_philosophy with include_pdf_context=true and username
- THEN the system attempts retrieval from both philosopher collection and user document collection
- AND returns an answer (HTTP 200) even if no document context is found

#### Scenario: Ownership isolation across workflows
- WHEN user A uploads a document and creates a draft
- AND user B attempts to review or generate sections for user A's draft using a different username
- THEN the system returns 403 Forbidden

#### Scenario: Multiple document types support workflow
- WHEN the user uploads PDF, MD, DOCX, and TXT files
- AND performs a chat search with include_pdf_context=true
- THEN results MAY include chunks from any of the uploaded document types (non-deterministic ordering)

#### Scenario: Draft listing filtered by username with documents present
- WHEN the user lists drafts with ?username=john_doe
- THEN only drafts created by john_doe are returned regardless of other users' uploads

#### Scenario: Backward compatibility with NULL username

- WHEN existing records have username=NULL
- THEN queries and operations handle NULL gracefully
- AND filtering by username uses IS NULL or matches provided value

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

### Requirement: Typed Configuration Management
The system SHALL use Pydantic v2 settings for type-safe configuration management with TOML and environment variable support.

#### Scenario: TOML configuration loading
- **WHEN** the application starts with `base.toml` and environment-specific TOML files
- **THEN** configuration is loaded with proper type validation
- **AND** environment variables override TOML values using `APP_` prefix

#### Scenario: Configuration validation failure
- **WHEN** configuration contains invalid types or missing required fields  
- **THEN** application startup fails with clear error messages
- **AND** validation errors specify the exact field and expected type

#### Scenario: Environment-specific configuration
- **WHEN** `ENV=dev` environment variable is set
- **THEN** `app/config/toml/dev.toml` overlays `app/config/toml/base.toml`
- **AND** environment variables still take highest precedence

### Requirement: FastAPI Lifespan Service Management
The system SHALL manage service lifecycles using FastAPI lifespan context managers instead of module-level singletons.

#### Scenario: Service initialization during startup
- **WHEN** FastAPI application starts up
- **THEN** services are initialized asynchronously in dependency order
- **AND** all services are stored in `app.state` for request-time access
- **AND** startup continues only after critical services (database, Qdrant) are validated

#### Scenario: Graceful service shutdown
- **WHEN** FastAPI application shuts down
- **THEN** all services are closed via their `.aclose()` methods
- **AND** resources are released in reverse initialization order
- **AND** shutdown errors are logged but don't prevent clean termination

#### Scenario: Startup failure handling
- **WHEN** critical service initialization fails during startup
- **THEN** application serves 503 responses for non-health endpoints
- **AND** health endpoint returns startup error details
- **AND** serving resumes when services are manually restored

### Requirement: Modern Retrieval Pipeline Integration
The system SHALL support LlamaIndex QueryFusionRetriever for hybrid retrieval with HyDE and RRF capabilities.

#### Scenario: Feature-flagged retrieval pipeline
- **WHEN** `APP_USE_LLAMA_INDEX_WORKFLOWS=true` environment variable is set
- **THEN** ExpansionService uses QueryFusionRetriever for hybrid queries
- **AND** existing API contracts and response formats are preserved
- **AND** performance metrics are collected for comparison

#### Scenario: Fallback to existing implementation
- **WHEN** `APP_USE_LLAMA_INDEX_WORKFLOWS=false` or flag is unset
- **THEN** ExpansionService uses existing hand-rolled HyDE/RRF implementation
- **AND** no functionality differences are observable via API

#### Scenario: Multi-query fusion retrieval
- **WHEN** QueryFusionRetriever is enabled and processes a query
- **THEN** system generates 4 query variations for expanded retrieval
- **AND** results are fused using reciprocal rank fusion (RRF)
- **AND** async processing and logging are enabled automatically

### Requirement: Optimized Model Compilation
The system SHALL pre-compile SPLADE models during startup for improved inference performance.

#### Scenario: Startup model compilation
- **WHEN** application starts with `APP_COMPILE=true` (default)
- **THEN** SPLADE model is compiled using PyTorch compilation
- **AND** BetterTransformer optimization is applied when available
- **AND** compilation failures fall back gracefully to non-compiled models

#### Scenario: Compilation disabled for debugging
- **WHEN** `APP_COMPILE=false` environment variable is set
- **THEN** SPLADE models run without compilation
- **AND** inference still works correctly with baseline performance
- **AND** no compilation errors or warnings are logged

#### Scenario: Optimized inference execution
- **WHEN** SPLADE vector generation is requested after compilation
- **THEN** models run in `torch.inference_mode()` for performance
- **AND** thread pool overhead is eliminated for compiled models
- **AND** inference performance is measurably improved over baseline

### Requirement: Modern Async Test Infrastructure
The system SHALL use httpx.AsyncClient with ASGITransport for testing instead of custom TestClient patterns.

#### Scenario: Lifespan-aware test execution
- **WHEN** tests run with `ASGITransport(lifespan="auto")`
- **THEN** actual startup and shutdown lifecycles are exercised
- **AND** services are properly initialized and cleaned up between tests
- **AND** test isolation is maintained without manual cache clearing

#### Scenario: Clean dependency overrides
- **WHEN** tests use `dependency_overrides_context` for mocking services
- **THEN** overrides are scoped to individual test functions
- **AND** original dependencies are restored automatically after test completion
- **AND** no manual cleanup or reset logic is required

#### Scenario: Async test patterns
- **WHEN** tests are marked with `@pytest.mark.anyio`
- **THEN** all HTTP client calls use `await client.get/post()` patterns
- **AND** async service behavior is tested accurately
- **AND** test performance is comparable to or better than synchronous patterns

