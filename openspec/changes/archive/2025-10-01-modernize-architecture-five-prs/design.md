## Context

The Ontologic API currently uses patterns from earlier FastAPI and Python ecosystem practices:
- Manual TOML configuration merging without type safety
- LRU cache-based singletons for dependency injection 
- Custom retrieval implementations instead of mature libraries
- Synchronous service initialization in module scope
- Custom test client patterns predating modern async testing

This creates maintenance burden, testing complexity, and performance issues. The proposed modernization adopts contemporary best practices while maintaining API compatibility.

**Stakeholders**: Development team, deployment infrastructure, API consumers
**Constraints**: Zero-downtime deployment requirement, existing TOML configuration format, current API contract preservation

## Goals / Non-Goals

### Goals
- **Type Safety**: Replace manual config merging with Pydantic v2 validation
- **Clean Lifecycle**: Move from LRU singletons to proper async resource management
- **Modern Libraries**: Adopt LlamaIndex ecosystem for retrieval instead of hand-rolled implementations
- **Performance**: Pre-compile models once at startup, eliminate repeated thread-pool bouncing
- **Testability**: Enable clean dependency mocking and lifespan testing
- **Incremental Deployment**: Each PR independently deployable with rollback capability

### Non-Goals
- Changing existing API endpoints or response schemas
- Modifying TOML configuration file locations or structure
- Rewriting core business logic in services
- Adding new external service dependencies beyond Python packages
- Performance optimization beyond startup compilation and better library usage

## Decisions

### Decision 1: pydantic-settings over Custom Configuration
**Choice**: Use `pydantic-settings` with custom `TOMLSettingsSource` 
**Rationale**: 
- Type safety and validation built-in
- Environment variable override semantics match current behavior
- Settings inheritance and composition patterns
- Industry standard for FastAPI applications
**Alternatives considered**: 
- Keep manual merging + add Pydantic validation layer (more complex)
- Use dynaconf or other config libraries (less FastAPI-idiomatic)
- Custom TOML loader with dataclasses (less validation features)

### Decision 2: FastAPI Lifespan over LRU Singletons
**Choice**: Move service initialization to `@asynccontextmanager` lifespan with `app.state` storage
**Rationale**:
- Proper async resource management with cleanup
- Testing via `dependency_overrides_context` instead of cache clearing
- Explicit startup/shutdown ordering and error handling
- Modern FastAPI pattern since v0.109+
**Alternatives considered**:
- Keep LRU pattern + add manual cleanup (still testing complexity)
- Use FastAPI dependency caching (doesn't solve lifespan issues)
- Dependency injection framework like `dependency-injector` (added complexity)

### Decision 3: LlamaIndex Workflows over Hand-rolled RAG
**Choice**: Adopt `QueryFusionRetriever` + `llama_index_workflows` with feature flag
**Rationale**:
- HyDE and RRF are built-in, tested, optimized
- Workflow engine provides retry, metrics, composability
- Reduces maintenance burden for custom retrieval logic
- Easy rollback via feature flag during transition
**Alternatives considered**:
- Keep existing implementation (technical debt continues)
- Build workflow engine in-house (reinventing wheel)
- Use Langchain instead (less focused on retrieval, more complex)

### Decision 4: Startup Model Compilation over Per-Request
**Choice**: Pre-compile SPLADE in lifespan with BetterTransformer + torch.compile
**Rationale**:
- Compilation cost paid once instead of per-request
- BetterTransformer provides free speedup on supported architectures
- Eliminates thread pool overhead for already-compiled models
- Graceful fallback when compilation unavailable
**Alternatives considered**:
- Lazy compilation on first use (still impacts first user)
- Model caching without compilation (misses optimization opportunities)
- External model serving (adds infrastructure complexity)

### Decision 5: httpx.AsyncClient over Custom Test Patterns
**Choice**: Replace custom TestClient with `httpx.AsyncClient` + `ASGITransport(lifespan="auto")`
**Rationale**:
- Tests actual lifespan behavior instead of mocking it
- `dependency_overrides_context` provides clean isolation
- Industry standard for async FastAPI testing
- Removes custom scaffolding maintenance
**Alternatives considered**:
- Keep TestClient + add lifespan testing separately (duplicated test infra)
- Use pytest-async patterns without lifespan (incomplete testing)
- Synchronous test patterns (doesn't test actual async behavior)

## Risks / Trade-offs

### Risk 1: Configuration Migration Errors
**Risk**: TOML file paths or environment variable handling changes break existing deployments
**Mitigation**: 
- Keep existing file locations (`base.toml`, `dev.toml`)
- Maintain exact environment variable override semantics
- Add comprehensive configuration tests for all environments
- Deploy with extensive pre-production validation

### Risk 2: Service Startup Race Conditions
**Risk**: Async service initialization creates new failure modes or timing issues
**Mitigation**:
- Explicit dependency ordering in lifespan (database → Qdrant → LLM → cache)
- Startup failure handling with clear error messages
- Health checks that validate service state before serving traffic
- Graceful degradation for non-critical services (cache)

### Risk 3: Performance Regression from Library Changes
**Risk**: LlamaIndex overhead or different retrieval semantics impact API response times
**Mitigation**:
- Feature flag enables quick rollback to existing implementation
- Performance benchmarking before/after each change
- Gradual rollout starting with development environment
- Preserve existing method signatures and behavior contracts

### Risk 4: Model Compilation Failures
**Risk**: PyTorch compilation or BetterTransformer fail on production hardware
**Mitigation**:
- Silent fallback to non-compiled models when compilation fails
- Configuration toggle `APP_COMPILE=false` for debugging
- Extensive testing on production-like hardware
- Monitoring and alerting for compilation success/failure rates

### Risk 5: Test Infrastructure Disruption
**Risk**: Async test migration breaks CI or creates flaky test behavior
**Mitigation**:
- Parallel implementation initially (keep both patterns temporarily)  
- Comprehensive test of lifespan behavior and dependency overrides
- CI validation on multiple Python versions and environments
- Clear rollback plan if test reliability degrades

## Migration Plan

### Phase 1: PR 1 - Configuration (Low Risk)
1. **Pre-deployment**: Add pydantic-settings dependency, create Settings class
2. **Deployment**: Replace config loading, maintain TOML file compatibility
3. **Validation**: Test all configuration scenarios in staging
4. **Rollback**: Revert to manual config loading if validation issues

### Phase 2: PR 2 - Dependency Injection (Medium Risk)  
1. **Pre-deployment**: Add .aclose() methods, test lifespan locally
2. **Deployment**: Switch to lifespan-based DI, monitor startup times
3. **Validation**: Health checks confirm all services initialized
4. **Rollback**: Revert to LRU singleton pattern if startup failures

### Phase 3: PR 3 - Retrieval Pipeline (Medium Risk)
1. **Pre-deployment**: Feature flag implementation, performance benchmarking
2. **Deployment**: Deploy with flag disabled, enable for subset of traffic
3. **Validation**: Compare retrieval quality and performance metrics
4. **Rollback**: Disable feature flag to revert to existing pipeline

### Phase 4: PR 4 - SPLADE Optimization (Low Risk)
1. **Pre-deployment**: Test compilation on production hardware types
2. **Deployment**: Enable with fallback, monitor compilation success rates
3. **Validation**: Measure inference performance improvements
4. **Rollback**: Disable compilation toggle if performance degrades

### Phase 5: PR 5 - Test Infrastructure (Low Risk)
1. **Pre-deployment**: Migrate tests gradually, validate CI reliability
2. **Deployment**: Developer tooling update, no runtime impact
3. **Validation**: CI passes consistently, test execution time acceptable
4. **Rollback**: Revert to previous test patterns if CI becomes unreliable

### Cross-Phase Monitoring
- Application startup time and success rates
- API response time distributions (p50, p95, p99)
- Memory usage patterns and garbage collection behavior
- Error rates and failure modes during service initialization
- Model inference performance and accuracy metrics

## Open Questions

1. **LlamaIndex Version Compatibility**: Should we pin to specific llama-index versions or use version ranges for automatic updates?
   - **Recommendation**: Pin major versions, allow minor updates for security patches

2. **Compilation Hardware Requirements**: What's the minimum hardware specification for PyTorch compilation to be beneficial?
   - **Action**: Benchmark on current production hardware and document requirements

3. **Configuration Migration**: Do we need backward compatibility for any undocumented configuration patterns?
   - **Action**: Audit existing deployments for non-standard configuration usage

4. **Service Dependency Graph**: Are there implicit dependencies between services that aren't captured in the current initialization order?
   - **Action**: Review service constructors and document dependency relationships

5. **Test Data Management**: How should we handle test data with lifespan-managed services?
   - **Recommendation**: Use dependency overrides with in-memory implementations for fast, isolated tests