## ADDED Requirements

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

## MODIFIED Requirements

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