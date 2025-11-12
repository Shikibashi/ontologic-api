## 1. PR 1: Typed Configuration with pydantic-settings

### 1.1 Dependencies and Setup
- [ ] 1.1.1 Add `pydantic-settings>=2.0` to `requirements.txt`
- [ ] 1.1.2 Create `app/config/toml/` directory structure
- [ ] 1.1.3 Move existing TOML files to `app/config/toml/base.toml` and `app/config/toml/dev.toml`

### 1.2 Implement Settings Classes
- [ ] 1.2.1 Create `app/config/settings.py` with `TOMLSettingsSource` class
- [ ] 1.2.2 Implement `Settings` class with existing configuration fields
- [ ] 1.2.3 Add proper field validation and type hints for all configuration values
- [ ] 1.2.4 Test TOML loading with environment variable overrides

### 1.3 Replace Manual Config Loading
- [ ] 1.3.1 Replace `load_config()` in `app/config/__init__.py` with `get_settings()`
- [ ] 1.3.2 Update all imports from `app.config` throughout codebase
- [ ] 1.3.3 Remove deprecated `merge_configs()` and `apply_env_overrides()` functions
- [ ] 1.3.4 Update configuration access patterns in service classes

### 1.4 Testing and Validation
- [ ] 1.4.1 Add unit tests for `Settings` class with various TOML configurations
- [ ] 1.4.2 Test environment variable override behavior
- [ ] 1.4.3 Verify startup works with both `dev` and `prod` environments
- [ ] 1.4.4 Add CI check for configuration loading in different environments

## 2. PR 2: Modern Dependency Injection with FastAPI Lifespans

### 2.1 Service Interface Updates
- [ ] 2.1.1 Add async `.aclose()` methods to all service classes
- [ ] 2.1.2 Convert service initialization to async `@classmethod start()` patterns
- [ ] 2.1.3 Update `QdrantManager`, `ExpansionService`, `LLMManager` for async lifecycle

### 2.2 App Lifespan Implementation
- [ ] 2.2.1 Update `app/main.py` lifespan to initialize services asynchronously
- [ ] 2.2.2 Store service instances in `app.state` instead of module-level singletons
- [ ] 2.2.3 Implement proper shutdown sequence calling `.aclose()` on all services
- [ ] 2.2.4 Add startup failure handling with graceful degradation

### 2.3 Dependency Provider Updates
- [ ] 2.3.1 Update `app/core/dependencies.py` to extract services from `app.state`
- [ ] 2.3.2 Remove `@singleton` decorators and LRU cache usage
- [ ] 2.3.3 Add request-scoped dependency extraction functions
- [ ] 2.3.4 Update type annotations and dependency injection patterns

### 2.4 Remove Legacy DI Helpers
- [ ] 2.4.1 Remove `app/utils/di_helpers.py` singleton utilities
- [ ] 2.4.2 Update all imports to use new dependency patterns
- [ ] 2.4.3 Clean up `reset_dependency_cache()` and related test helpers

### 2.5 Testing Updates
- [ ] 2.5.1 Update test fixtures to use `dependency_overrides_context`
- [ ] 2.5.2 Test startup/shutdown lifecycle thoroughly
- [ ] 2.5.3 Add tests for service initialization failure scenarios
- [ ] 2.5.4 Verify clean resource cleanup during shutdown

## 3. PR 3: LlamaIndex Workflows for Retrieval Pipeline

### 3.1 Dependencies and Setup
- [ ] 3.1.1 Add `llama-index-workflows` to `requirements.txt`
- [ ] 3.1.2 Add `llama-index-retrievers-fusion` (or equivalent) for `QueryFusionRetriever`
- [ ] 3.1.3 Configure LlamaIndex settings once in app lifespan

### 3.2 Retrieval Pipeline Implementation
- [ ] 3.2.1 Create `app/services/retrieval_pipeline.py` with `QueryFusionRetriever` integration
- [ ] 3.2.2 Implement workflow wrapper around fusion retrieval
- [ ] 3.2.3 Add HyDE-style multi-query generation (4 queries by default)
- [ ] 3.2.4 Configure RRF with `mode="reciprocal_rerank"`

### 3.3 Service Integration
- [ ] 3.3.1 Update `ExpansionService` to use new pipeline behind feature flag
- [ ] 3.3.2 Maintain existing method signatures for backward compatibility
- [ ] 3.3.3 Add configuration toggle `APP_USE_LLAMA_INDEX_WORKFLOWS=false`
- [ ] 3.3.4 Implement fallback to existing hand-rolled implementation

### 3.4 Performance and Monitoring
- [ ] 3.4.1 Enable async operation and built-in logging from workflows
- [ ] 3.4.2 Add metrics collection for retrieval performance
- [ ] 3.4.3 Test performance comparison between old and new pipelines
- [ ] 3.4.4 Document migration path for production rollout

## 4. PR 4: Optimized SPLADE Initialization

### 4.1 Model Compilation Infrastructure
- [ ] 4.1.1 Create `app/services/model_compiler.py` for compilation utilities
- [ ] 4.1.2 Add BetterTransformer detection and fallback logic
- [ ] 4.1.3 Implement safe PyTorch compilation with error handling
- [ ] 4.1.4 Add configuration toggle `APP_COMPILE=false` for debugging

### 4.2 SPLADE Service Refactoring
- [ ] 4.2.1 Create `SpladeEncoder` class in `app/services/llm_manager.py`
- [ ] 4.2.2 Move model initialization to async startup in app lifespan
- [ ] 4.2.3 Pre-compile model once during startup warmup
- [ ] 4.2.4 Remove repeated `asyncio.to_thread()` calls from encoding methods

### 4.3 Performance Optimizations
- [ ] 4.3.1 Enable BetterTransformer with silent fallback
- [ ] 4.3.2 Use `torch.inference_mode()` for all inference calls
- [ ] 4.3.3 Optimize tokenization with `use_fast=True` tokenizers
- [ ] 4.3.4 Add device detection and GPU acceleration when available

### 4.4 Integration and Testing
- [ ] 4.4.1 Update existing SPLADE vector generation calls
- [ ] 4.4.2 Add benchmarking for compilation vs non-compilation performance
- [ ] 4.4.3 Test fallback behavior when compilation fails
- [ ] 4.4.4 Verify accuracy preservation after optimizations

## 5. PR 5: Modern Test Infrastructure

### 5.1 AsyncClient Setup
- [ ] 5.1.1 Create `tests/conftest.py` fixture with `httpx.AsyncClient`
- [ ] 5.1.2 Configure `ASGITransport(app=app, lifespan="auto")`
- [ ] 5.1.3 Set up proper base URL and transport configuration
- [ ] 5.1.4 Remove custom TestClient scaffolding code

### 5.2 Dependency Override Patterns
- [ ] 5.2.1 Create example test using `dependency_overrides_context`
- [ ] 5.2.2 Update all existing tests to use new async patterns
- [ ] 5.2.3 Replace manual dependency mocking with clean override context
- [ ] 5.2.4 Add test fixtures for common service mocks

### 5.3 Test Migration
- [ ] 5.3.1 Update all `test_*.py` files to use `@pytest.mark.anyio`
- [ ] 5.3.2 Replace synchronous client calls with `await client.get/post()`
- [ ] 5.3.3 Test lifespan behavior explicitly in integration tests
- [ ] 5.3.4 Verify proper cleanup between test cases

### 5.4 CI and Documentation
- [ ] 5.4.1 Update CI configuration for async test execution
- [ ] 5.4.2 Add test documentation for new patterns
- [ ] 5.4.3 Create development guide for dependency testing
- [ ] 5.4.4 Validate test performance and reliability improvements

## Cross-PR Integration Tasks

### Integration Testing
- [ ] I.1 End-to-end testing after each PR to ensure no regressions
- [ ] I.2 Performance benchmarking comparing before/after each change
- [ ] I.3 Memory usage analysis for lifespan vs singleton patterns
- [ ] I.4 Load testing with optimized SPLADE compilation

### Documentation Updates
- [ ] D.1 Update README.md with new configuration patterns
- [ ] D.2 Document new dependency injection patterns for contributors
- [ ] D.3 Add troubleshooting guide for compilation issues
- [ ] D.4 Update deployment guides with new environment variables

### Rollout and Monitoring
- [ ] R.1 Create feature flags for gradual production rollout
- [ ] R.2 Set up monitoring for new lifespan startup/shutdown events
- [ ] R.3 Add alerting for compilation failures and fallback usage
- [ ] R.4 Plan rollback procedures for each architectural change