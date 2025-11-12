## ADDED Requirements
### Requirement: Paper Generation Workflow
The system SHALL provide a paper generation workflow that creates drafts, generates structured sections with citations, and maintains immersive or academic styles.

#### Scenario: Create draft with unique id
- **WHEN** a user submits title, topic, and collection
- **THEN** a draft_id is created and stored with status "created"

#### Scenario: Generate sections for existing draft
- **WHEN** generate is requested for a draft
- **THEN** the system creates Abstract, Introduction, Argument, Counterarguments, and Conclusion

#### Scenario: Use expanded queries during generation
- **WHEN** generating sections
- **THEN** HyDE, RAG-Fusion, SPLADE PRF, and Self-Ask expansions inform retrieval

#### Scenario: Immersive first-person style
- **WHEN** immersive mode is enabled
- **THEN** the writer uses first-person rhetorical style of the philosopher

#### Scenario: Apply RRF with k=60
- **WHEN** assembling context from multiple result lists
- **THEN** the system fuses lists using Reciprocal Rank Fusion with k=60

#### Scenario: Temperature control
- **WHEN** a temperature is specified
- **THEN** the system uses that value, defaulting to 0.3 and enforcing [0.0, 1.0]

#### Scenario: Include footnote citations
- **WHEN** citations are needed
- **THEN** markdown footnotes include author, work, and score from node metadata

### Requirement: Human-in-the-Loop Controls
Users SHALL control AI suggestions and draft application.

#### Scenario: Apply all suggestions
- **WHEN** apply is requested with accept_all=true
- **THEN** all AI-generated suggestions are applied to the draft

#### Scenario: Apply by section
- **WHEN** accept_sections is provided
- **THEN** only suggestions for listed sections are applied

#### Scenario: Retrieve draft status
- **WHEN** status is requested
- **THEN** the system returns draft content with sections and metadata

#### Scenario: Preserve original on reject
- **WHEN** user rejects all suggestions
- **THEN** the original draft content remains unchanged
