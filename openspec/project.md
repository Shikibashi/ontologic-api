# Project Context

## Purpose
Ontologic API serves philosopher-centric RAG and LLM experiences: hybrid retrieval from Qdrant collections and LLM responses in neutral or immersive persona modes.

## Tech Stack
- Python 3.11+
- FastAPI + Uvicorn
- Pydantic v2 models
- Qdrant (AsyncQdrantClient)
- SPLADE + dense embedding generation via `LLMManager`

## Project Conventions

### Code Style
- Type hints for public functions
- Pydantic models for request/response schemas
- Minimal shared singletons (QdrantManager, LLMManager)

### Architecture Patterns
- FastAPI router modules under `app/router`
- Service classes under `app/services`
- Core models and logging under `app/core`
- Single Uvicorn server entrypoint in `app/main.py`

### Testing Strategy
- Unit tests for service logic (LLMManager, QdrantManager)
- Contract tests for API routes (request/response shape)
- Smoke test for app startup

### Git Workflow
- Trunk-based with feature branches
- Conventional commit style on merge
- No direct pushes to main

## Domain Context
- “Philosophers” map to Qdrant collections; a “Meta Collection” aggregates cross-philosopher metadata
- Hybrid retrieval combines sparse and dense vectors per collection rules
- Persona mode (immersive) responds in the style of the selected philosopher

## Important Constraints
- Enforce temperature bounds `(0, 1)` for endpoints using LLM
- CORS allowed origins: `http://localhost:5173`, `http://localhost:5174`, `https://www.ontologicai.com`, `https://ontologicai.com`
- Trusted hosts: `api.ontologicai.com`, `localhost`, `www.ontologicai.com`

## External Dependencies
- Qdrant cluster at `https://qdrant.ontologicai.com`
- LLM provider accessed via `LLMManager` (local/remote per environment)
- Tokenizers and embedding models used by SPLADE/dense pipelines
