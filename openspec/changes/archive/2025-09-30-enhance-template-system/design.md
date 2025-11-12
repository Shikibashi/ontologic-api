## Context
Prompt content has been extracted to Jinja2, but structure and reuse are limited. We propose a hierarchical template system with base templates, macros, and consistent pairing to improve maintainability and flexibility.

## Goals / Non-Goals
- Goals: Pair completeness, naming consistency, base + macros, adaptive templates, registry
- Non-Goals: API route changes, persistence layer changes, LLM provider swap

## Decisions
- Directory structure with `base/`, `philosophers/`, `workflows/`, and `macros/`
- Naming convention `{context}/{workflow}/{role}.j2` (prefer `system.j2` and `user.j2` pairs)
- Introduce template registry JSON for discovery and tooling
- Optional: Simple in-process cache on rendered template + context hash

## Alternatives
- Keep ad-hoc templates (harder to maintain)
- Monolithic templates per workflow (less reuse)

## Risks / Trade-offs
- Short-term churn from renames; mitigated by phased rollout and compatibility shims in LLMManager
- Over-templating risk; mitigated by base/macros being optional and incremental adoption

## Migration Plan
1) Create missing pairs and base templates without renaming existing files
2) Add adaptive/validation templates and registry
3) Optionally rename to standardized pattern; update references in LLMManager
4) Validate rendering; document in `openspec/specs/ontologic-api/spec.md`

## Open Questions
- Which philosopher set is considered GA for profiles/metadata?
- Do we need per-workflow caching or global cache in PromptRenderer?
