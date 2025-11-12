## Why
The project needs AI-assisted paper generation, AI review workflows, and advanced query expansion tailored to philosophy, while preserving the existing FastAPI + Qdrant + Ollama architecture. Adding minimal persistence, prompt kits, and integration fixes (Qdrant API key, refeed) enables a cohesive authoring and review experience.

## What Changes
- Add paper generation workflow (draft lifecycle, section generation, citations)
- Add AI review workflow (verification plan, evidence, actionable suggestions)
- Add query expansion service (HyDE, RAG-Fusion+RRF, SPLADE PRF, Self-Ask)
- Add persistence with SQLModel and ONTOLOGIC_DB_URL
- Integrate with existing FastAPI router and managers; fix Qdrant key + refeed
- Provide prompt kits for writer, reviewer, HyDE, Self-Ask
- Add OAuth via dev.toml (providers list + per-provider enabled; Google/Discord; Apple optional) and chat history + document uploads; endpoints remain publicly callable (no gating)

## Impact
- Affected specs: workflows-paper, ai-review, query-expansion-retrieval, data-config, prompts-citations, auth-chat-uploads
- Affected code: FastAPI routers, QdrantManager, LLMManager, new SQLModel draft model, OAuth setup, upload handling
- Config: ONTOLOGIC_DB_URL, QDRANT_API_KEY, LOG_LEVEL
- Security: Environment-based secrets, safe subprocess, metadata scrubbing
