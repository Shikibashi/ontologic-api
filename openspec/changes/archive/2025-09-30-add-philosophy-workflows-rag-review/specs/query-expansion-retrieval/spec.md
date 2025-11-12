## ADDED Requirements
### Requirement: Query Expansion Services
The system SHALL provide advanced query expansion for philosophical text retrieval.

#### Scenario: HyDE expansion
- **WHEN** HyDE is requested
- **THEN** a 120–200 word hypothetical answer is generated and used as an expanded query

#### Scenario: Immersive HyDE persona
- **WHEN** immersive mode is enabled
- **THEN** HyDE uses the philosopher's persona and terminology

#### Scenario: RAG-Fusion paraphrases
- **WHEN** RAG-Fusion is applied
- **THEN** 4–6 paraphrases are generated (define, contextualize, critiques, key passages)

#### Scenario: SPLADE PRF terms
- **WHEN** SPLADE vectors are available
- **THEN** PRF harvests high-weight tokens from initial results for expansion

#### Scenario: Self-Ask decomposition
- **WHEN** Self-Ask is requested
- **THEN** 3–6 concrete sub-questions are generated

#### Scenario: Immersion term injection
- **WHEN** philosopher-specific terms exist in IMMERSION_TERMS
- **THEN** relevant terms are injected into expansions

#### Scenario: Deduplicate and limit
- **WHEN** multiple methods are combined
- **THEN** queries are deduplicated and limited to a maximum of 10

### Requirement: Retrieval Integration
The system SHALL integrate expansions with Qdrant and provide fusion utilities.

#### Scenario: with_vectors for PRF
- **WHEN** vector queries include with_vectors
- **THEN** the Qdrant manager returns vectors required for PRF operations

#### Scenario: Preserve refeed flag
- **WHEN** gather_points_and_sort is called with refeed=true
- **THEN** the manager preserves refeed through the pipeline

#### Scenario: RRF fuse helper
- **WHEN** fusion is needed
- **THEN** a `rrf_fuse(k)` method is available for reciprocal-rank fusion
