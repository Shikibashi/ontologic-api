## MODIFIED Requirements

### Requirement: POST /ask_philosophy — Q&A with retrieval and optional immersion
The system SHALL expose a POST endpoint `/ask_philosophy` that performs hybrid retrieval from Qdrant and generates an answer via the LLM.

- Request body: `HybridQueryRequest` (pydantic)
- Query params:
  - refeed: bool (default true) — when true and `collection != "Meta Collection"`, the system MUST retrieve top meta nodes and augment the sub-collection query with those texts
  - immersive: bool (default false)
  - temperature: float in (0, 1), default 0.30

#### Scenario: Meta refeed enrichment
- WHEN `refeed=true` and `collection != "Meta Collection"`
- THEN the system retrieves meta nodes filtered by the target `collection`
- AND concatenates top meta texts with the original query to form an enriched query
- AND uses the enriched query for subsequent sub-collection retrieval

#### Scenario: Refeed disabled
- WHEN `refeed=false`
- THEN the system queries the target `collection` using only the provided `query_str`

### Requirement: POST /query_hybrid — Hybrid retrieval and optional vetting
The system SHALL expose a POST endpoint `/query_hybrid` that performs hybrid vector retrieval with optional LLM vetting.

- Request body: `HybridQueryRequest` (pydantic)
- Query params:
  - vet_mode: bool (default false)
  - raw_mode: bool (default false)
  - refeed: bool (default true) — applies the same meta refeed enrichment as `/ask_philosophy`
  - limit: int in [1, 100], default 10
  - temperature: float in (0, 1), default 0.30

#### Scenario: Raw grouped results with meta
- WHEN `raw_mode=true` and `refeed=true` with `collection != "Meta Collection"`
- THEN the response MAY include meta results under `"Meta Collection"` alongside sub-collection results

#### Scenario: Vetting respects enrichment
- WHEN `vet_mode=true` and `refeed=true`
- THEN vetting is performed over nodes retrieved from the enriched sub-collection query
