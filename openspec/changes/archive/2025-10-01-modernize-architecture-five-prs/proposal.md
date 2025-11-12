## Why

The current architecture has several technical debt issues affecting maintainability, testability, and performance:
- Manual configuration merging in `app/config/__init__.py:8` is error-prone and lacks type safety
- LRU singletons throughout `app/main.py:52`, `app/core/dependencies.py:9`, `app/utils/di_helpers.py:5` create lifecycle management complexity and testing difficulties  
- Hand-rolled HyDE/RRF implementation duplicates functionality available in modern retrieval libraries
- SPLADE model compilation happens repeatedly instead of once at startup, degrading performance
- Test infrastructure using custom scaffolding instead of modern async test patterns

## What Changes

### PR 1: Typed Configuration with pydantic-settings 2.x
- **BREAKING**: Replace manual config merging with `Settings` class using `pydantic-settings`
- Add TOML-first configuration with environment variable overrides
- Maintain existing TOML file locations (`base.toml`, `dev.toml`)
- Replace `load_config()` calls with `get_settings()` throughout codebase

### PR 2: Modern Dependency Injection with FastAPI Lifespans
- **BREAKING**: Replace LRU singleton pattern with FastAPI lifespan management
- Move service initialization from module level to app/router lifespan contexts
- Add proper async resource cleanup with `.aclose()` methods
- Enable clean testing via `dependency_overrides_context`

### PR 3: LlamaIndex Workflows for Retrieval Pipeline  
- Replace hand-rolled HyDE/RRF with `llama_index_workflows` + `QueryFusionRetriever`
- Maintain existing `ExpansionService` and `QdrantManager` interfaces for compatibility
- Add declarative workflow patterns with built-in retry/metrics support
- Feature flag for gradual rollout and quick rollback

### PR 4: Optimized SPLADE Initialization
- Pre-compile SPLADE model once at startup instead of per-request
- Enable BetterTransformer fast path when available  
- Remove repeated `asyncio.to_thread()` calls during encoding
- Add compilation toggle `APP_COMPILE=false` for safe fallback

### PR 5: Modern Test Infrastructure
- **BREAKING**: Replace custom TestClient scaffolding with `httpx.AsyncClient` + `ASGITransport`
- Enable `lifespan="auto"` for proper startup/shutdown testing
- Use `dependency_overrides_context` for clean dependency mocking
- Remove custom test client builders in `tests/conftest.py`

## Impact

- **Affected specs**: `ontologic-api` (core architecture and configuration patterns)
- **Affected code**: 
  - Configuration: `app/config/__init__.py`, TOML files
  - Dependency injection: `app/main.py`, `app/core/dependencies.py`, `app/utils/di_helpers.py`
  - Retrieval services: `app/services/expansion_service.py`, `app/services/llm_manager.py:535`
  - Testing: `tests/conftest.py`, all test files using custom TestClient patterns
- **External dependencies**: Add `pydantic-settings>=2.0`, `llama-index-workflows`, potentially `llama-index-retrievers-fusion`
- **Migration path**: Each PR is independently deployable with feature flags and fallback mechanisms
- **Risk mitigation**: Gradual rollout with environment-specific toggles and comprehensive testing at each stage