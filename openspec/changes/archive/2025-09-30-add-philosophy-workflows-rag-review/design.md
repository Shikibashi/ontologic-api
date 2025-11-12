## Context
Add a human-in-the-loop philosophy paper generator and AI review cycles on top of existing FastAPI + Qdrant + Ollama services. Preserve direct instantiation patterns for managers. Introduce a minimal SQLModel persistence layer and OAuth for chat history/uploads without gating endpoints.

## Goals / Non-Goals
- Goals: paper generation, AI review, query expansion, persistence, prompts, OAuth + uploads
- Non-Goals: real-time collaborative editing, PDF/DOCX export, multi-language generation

## Decisions
- Use SQLModel for `PaperDraft` with SQLite default and PostgreSQL via ONTOLOGIC_DB_URL
- Add `rrf_fuse(k)` and `with_vectors` to QdrantManager; read QDRANT_API_KEY from env; preserve `refeed`
- ExpansionService orchestrates HyDE, RAG-Fusion, PRF (SPLADE), Self-Ask; dedupe to ≤10
- Prompt kits encode writer (academic/immersive), reviewer, verification, HyDE, Self-Ask
- OAuth via Google/Discord (Apple optional). Endpoints open; auth links data to user when present

## Risks / Trade-offs
- Parsing robustness → mitigate with structured parser and retries
- Expansion latency → mitigate with asyncio batching and caching
- DB portability → use URL-driven engines; start SQLite

## Migration Plan
1) Land DB schema + config scaffolding
2) Extend Qdrant/LLM managers and add ExpansionService
3) Add PaperWorkflow + endpoints, then ReviewWorkflow
4) Add OAuth + uploads and wire chat history

## Open Questions
- Collections naming and availability contracts?
- Evidence minimum thresholds for review?
- Preferred cache (Redis?) if introduced later
