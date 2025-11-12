## Why
The Jinja2 template system is extracted and functional but lacks consistent structure, pairing, naming, and reusable building blocks. Adding a coherent architecture (base templates, macros, registry), completing missing system/user pairs, and standardizing names will improve maintainability, reuse, and velocity.

## What Changes
- Standardize naming to `{context}/{workflow}/{role}.j2` and `{workflow}_{role}.j2` where appropriate
- Create missing system/user pairs for identified workflows (writer/academic, reviewer/system, expansion/rag_fusion)
- Add base, macro, and shared templates (system base, citation format, validation/error handling, philosopher base)
- Introduce dynamic/adaptive templates for conversation and expansion modes
- Add template documentation headers and a machine-readable template registry
- Restructure directories for clarity (base, philosophers, workflows, macros)

## Impact
- Specs affected: `ontologic-api` (non-API behaviour doc note only); new capability: `prompt-system`
- Code affected: `app/services/llm_manager.py` (template paths), `app/services/prompt_renderer.py`, templates under `app/prompts/`
- Non-breaking: Prompt content and organization only (no route or schema changes)
