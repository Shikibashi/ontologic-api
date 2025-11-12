## ADDED Requirements
### Requirement: Prompt Management
The system SHALL provide specialized prompts for writing and review modes.

#### Scenario: Immersive writer persona
- **WHEN** immersive writing is enabled
- **THEN** writer_system uses first-person philosopher perspective

#### Scenario: Academic writer persona
- **WHEN** standard academic writing is requested
- **THEN** writer_system uses "Sophia" persona with analytical prose

#### Scenario: Reviewer emphasis
- **WHEN** review is performed
- **THEN** reviewer_system emphasizes claim extraction, verification, and concrete rewrites

#### Scenario: Verification plan prompt
- **WHEN** verification is needed
- **THEN** the prompt generates 1–3 search questions per factual claim

#### Scenario: HyDE prompt
- **WHEN** HyDE generation is requested
- **THEN** the prompt requests concise, content-rich answers without hedging

#### Scenario: Self-Ask prompt
- **WHEN** Self-Ask is used
- **THEN** the prompt requests concrete references to works, concepts, and terms

### Requirement: Citation and Reference Management
The system SHALL generate appropriate footnotes and canonical references.

#### Scenario: Footnote generation
- **WHEN** nodes are converted to footnotes
- **THEN** markdown footnotes include author, title, and score

#### Scenario: Canonical references
- **WHEN** canonical references are needed
- **THEN** philosopher-specific formats are built (e.g., Bekker, BGE §)

#### Scenario: Indexed payload filtering
- **WHEN** payload indexes exist
- **THEN** indexed fields (author, work, chapter_number, publication_year) are used for fast filtering

#### Scenario: Evidence anchoring spans
- **WHEN** anchoring evidence
- **THEN** start_char_idx and end_char_idx are used to mark spans

#### Scenario: Source tier boosting
- **WHEN** source_tier is specified
- **THEN** primary sources are preferred over secondary in retrieval boosting
