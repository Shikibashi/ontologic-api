## 1. Implementation
- [x] 1.1 Scaffold DB layer (SQLModel `PaperDraft`), ONTOLOGIC_DB_URL, init tables
- [x] 1.2 Extend QdrantManager: env key, `rrf_fuse(k)`, `with_vectors`, preserve `refeed`
- [x] 1.3 Implement ExpansionService: HyDE, RAG-Fusion, PRF on SPLADE, Self-Ask, dedupe/limit
- [x] 1.4 Implement PaperWorkflow: create, generate sections, status, apply suggestions
- [x] 1.5 Implement ReviewWorkflow: verification plan, evidence retrieval, suggestions w/ blocking
- [x] 1.6 Prompt kits: writer (academic + immersive), reviewer, verification, HyDE, Self-Ask
- [x] 1.7 Router: /workflows (create, generate, status, ai-review, apply), include in app
- [x] 1.8 OAuth + sessions (optional via dev.toml providers list + per-provider enabled): Google, Discord (Apple optional); chat history + uploads; public endpoints allowed
- [x] 1.9 Security & config: env secrets, temperature bounds, metadata exclusions, safe subprocess
- [x] 1.10 Performance: async batching, caching hooks, RRF k configurable

## 2. Validation
- [x] 2.1 Unit tests: ExpansionService, citation helper, parser
- [x] 2.2 Integration tests: paper flow, review flow, query expansion pipeline
- [x] 2.3 E2E smoke: create → generate → review → apply → status
- [x] 2.4 Config checks: defaults for DB URL, LOG_LEVEL; QDRANT_API_KEY read
- [x] 2.5 OAuth flows: 0/1/many providers from dev.toml; unknown provider ignored; missing-secret skip; login via Google/Discord; anonymous usage supported
