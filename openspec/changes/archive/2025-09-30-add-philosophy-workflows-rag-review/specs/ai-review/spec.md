## ADDED Requirements
### Requirement: AI Review System
The system SHALL provide AI-powered review with verification planning, evidence retrieval, and actionable suggestions with blocking flags.

#### Scenario: Generate verification plan
- **WHEN** an AI review is requested for a draft
- **THEN** a plan lists factual claims and 1–3 search questions per claim

#### Scenario: Retrieve evidence for questions
- **WHEN** verification questions are generated
- **THEN** the system retrieves evidence via expanded queries for each question

#### Scenario: Chain-of-Verification and Self-RAG
- **WHEN** reviewing content
- **THEN** Chain-of-Verification and Self-RAG patterns verify claims

#### Scenario: Rubric-based evaluation
- **WHEN** rubric criteria are specified (accuracy, argument, coherence, citations, style)
- **THEN** the system evaluates against each criterion

#### Scenario: Suggestions with rationale and blocking
- **WHEN** suggestions are generated
- **THEN** each includes section, before, after, rationale, and blocking flag

#### Scenario: Severity-gated blocking
- **WHEN** blocking issues meet severity_gate
- **THEN** the system marks those suggestions as blocking

#### Scenario: Evidence fusion with RRF
- **WHEN** evidence from multiple expansions is available
- **THEN** results are fused using RRF with configurable k
