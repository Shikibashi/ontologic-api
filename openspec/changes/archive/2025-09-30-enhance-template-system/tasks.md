## 1. Immediate Improvements (Phase 1)
- [x] 1.1 Standardize naming to `<context>/<workflow>/{system|user}.j2` and `{workflow}_{role}.j2` when flat (documented; no renames yet)
- [x] 1.2 Create missing template pairs:
  - [x] writer/academic_user.j2
  - [x] reviewer/user.j2 (pair for reviewer/system)
  - [x] expansion/rag_fusion_system.j2
- [x] 1.3 Add base templates: base/system_base.j2, base/citation_format.j2
- [x] 1.4 Add documentation headers to existing templates (chat/*, vet/*)
- [ ] 1.5 Update LLMManager paths if any names moved (none yet)
- [x] 1.6 Validate rendering for chat + vet flows (spec validated)

## 2. Enhanced Functionality (Phase 2)
- [x] 2.1 Add adaptive templates: chat/adaptive_system.j2, workflows/expansion/adaptive_query.j2
- [x] 2.2 Add validation + error handling macros: base/input_validation.j2, base/error_handling.j2
- [x] 2.3 Add philosopher assembled profile template: philosophers/profile.j2
- [x] 2.4 Create template registry JSON with required/optional vars

## 3. Advanced Features (Phase 3)
- [x] 3.1 Implement template inheritance (base/academic_base.j2; workflows/writer/immersive_system.j2 extends it)
- [x] 3.2 Add macros for philosopher traits + axioms (macros/philosopher_macros.j2)
- [x] 3.3 Add primitive caching in PromptRenderer (LRU on template+context hash)
- [ ] 3.4 Add i18n keys for multi-language support (scoped placeholders)

## 4. Validation
- [x] 4.1 Run `openspec validate enhance-template-system --strict`
- [ ] 4.2 Smoke run: `uv run python -m app.main --no-reload` and exercise endpoints
- [ ] 4.3 Confirm no behaviour change in API responses (only prompt content paths)
