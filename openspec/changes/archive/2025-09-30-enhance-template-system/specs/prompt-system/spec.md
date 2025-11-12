## ADDED Requirements

### Requirement: Template Pair Consistency
Every workflow template MUST provide both `system.j2` and `user.j2` files.

#### Scenario: Academic writer pair exists
- WHEN the writer/academic workflow is used
- THEN `app/prompts/workflows/writer/academic_system.j2` and `app/prompts/workflows/writer/academic_user.j2` are present

#### Scenario: Reviewer pair exists
- WHEN the reviewer workflow is used
- THEN `app/prompts/workflows/reviewer/system.j2` and `app/prompts/workflows/reviewer/user.j2` are present

#### Scenario: RAG-Fusion pair exists
- WHEN the expansion/rag_fusion workflow is used
- THEN `app/prompts/workflows/expansion/rag_fusion_system.j2` and `app/prompts/workflows/expansion/rag_fusion_user.j2` are present

### Requirement: Naming Convention
Template files MUST follow `{context}/{workflow}/{role}.j2` or `{workflow}_{role}.j2` when flat.

#### Scenario: Chat immersive naming
- WHEN immersive chat templates are referenced
- THEN files are named `chat/immersive_system.j2` and `chat/immersive_user.j2`

#### Scenario: Verification naming
- WHEN verification templates are referenced
- THEN files use `verification_system.j2` and `verification_user.j2`

### Requirement: Base and Shared Templates
Reusable base, citation, and validation components SHALL exist under `app/prompts/base/` and macros under `app/prompts/macros/`.

#### Scenario: System base available
- WHEN rendering system prompts
- THEN `app/prompts/base/system_base.j2` is available for inheritance/blocks

#### Scenario: Citation format available
- WHEN rendering citations
- THEN `app/prompts/base/citation_format.j2` defines footnote format and style parameter

#### Scenario: Validation macros available
- WHEN validating inputs or handling errors
- THEN `app/prompts/base/input_validation.j2` and `app/prompts/base/error_handling.j2` expose macros

### Requirement: Philosopher Template Structure
Philosopher templates SHALL include metadata, works with context, and profiles assembled via includes.

#### Scenario: Philosopher metadata
- WHEN rendering philosopher data
- THEN `philosophers/{name}/metadata.j2` provides standard fields (name, era, school, birth, death, focus)

#### Scenario: Work template with context
- WHEN rendering a work
- THEN `philosophers/{name}/works/{work}.j2` contains quote, context, and significance sections

#### Scenario: Complete profile assembly
- WHEN building a full profile
- THEN `philosophers/{name}/complete_profile.j2` includes personality, tone, and axioms via includes

### Requirement: Adaptive Templates
Adaptive templates SHALL support conditional modes and parameters for chat and expansion workflows.

#### Scenario: Adaptive chat modes
- WHEN `chat/adaptive_system.j2` is rendered with `conversation_mode`
- THEN output changes for `debate`, `tutorial`, and `socratic` modes

#### Scenario: Adaptive query expansion
- WHEN `workflows/expansion/adaptive_query.j2` is rendered with `query_complexity`
- THEN output adapts to `simple` or `complex` with variable `num_queries`

### Requirement: Template Registry
Template registry MUST define purpose, required/optional vars, and category for key templates.

#### Scenario: Registry file exists
- WHEN tooling inspects templates
- THEN `app/prompts/template_registry.json` is present with entries for `chat/immersive_system.j2` (purpose, required_vars, optional_vars, category, complexity)
