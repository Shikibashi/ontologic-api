## ADDED Requirements
### Requirement: Data Management
The system SHALL persist drafts and related review metadata using SQLModel, with robust JSON handling.

#### Scenario: Create and store drafts
- **WHEN** a draft is created
- **THEN** it is stored with a unique ID in the database

#### Scenario: Store sections as JSON
- **WHEN** sections are generated
- **THEN** they are stored in sections_json

#### Scenario: Track draft status
- **WHEN** draft lifecycle changes
- **THEN** the status is updated among created, generated, and reviewed

#### Scenario: Database configuration
- **WHEN** connecting to database
- **THEN** ONTOLOGIC_DB_URL is used, defaulting to sqlite:///./ontologic.db

#### Scenario: JSON parse fallback
- **WHEN** sections_json cannot be parsed
- **THEN** an empty list fallback is used gracefully

### Requirement: Integration and Configuration
The system SHALL integrate routers and managers with environment-based configuration and logging defaults, and read optional OAuth provider configuration from dev.toml.

#### Scenario: Router inclusion
- **WHEN** workflows router is initialized
- **THEN** it is included in the main FastAPI application router

#### Scenario: Qdrant environment variables
- **WHEN** Qdrant queries are made
- **THEN** QDRANT_URL and QDRANT_API_KEY are read from the environment

#### Scenario: LLM/Ollama configuration
- **WHEN** LLM queries are made
- **THEN** the configured Ollama model (e.g., qwen3:8b) is used

#### Scenario: Logging default
- **WHEN** LOG_LEVEL is not set
- **THEN** the logger defaults to INFO

#### Scenario: OAuth providers from dev.toml
- **WHEN** reading authentication configuration
- **THEN** `auth.providers` (list) and `[auth.<provider>].enabled` flags are read from dev.toml (default: providers=[], enabled=false)

#### Scenario: Provider activation precedence
- **WHEN** determining active providers
- **THEN** a provider is active only if it appears in `auth.providers` AND its `[auth.<provider>].enabled=true`

#### Scenario: Zero or disabled providers
- **WHEN** `auth.providers=[]` or all `[auth.<provider>].enabled=false`
- **THEN** endpoints operate in anonymous mode and remain ungated

#### Scenario: Unknown providers ignored
- **WHEN** an unknown provider is listed in `auth.providers`
- **THEN** it is logged and ignored without failing startup

#### Scenario: Missing secrets skip
- **WHEN** a listed+enabled provider’s secrets are missing from environment
- **THEN** that provider is logged and skipped; others continue functioning; endpoints remain public

#### Scenario: Secrets resolved from environment
- **WHEN** provider secrets are needed
- **THEN** they are read from environment variables; dev.toml stores only non-secret keys and redirect URIs

### Requirement: Security & Configuration
The system SHALL protect secrets, scrub paths, and enforce safety.

#### Scenario: Read API keys from env
- **WHEN** Qdrant API key is needed
- **THEN** the system reads QDRANT_API_KEY from environment

#### Scenario: Scrub local file paths
- **WHEN** local filesystem paths appear in metadata
- **THEN** they are replaced with hashed provenance_id values

#### Scenario: Temperature bounds
- **WHEN** temperature is used
- **THEN** values are constrained between 0.0 and 1.0

#### Scenario: Metadata exclusions
- **WHEN** keys are excluded from payload
- **THEN** excluded_embed_metadata_keys and excluded_llm_metadata_keys are honored

#### Scenario: Safe subprocess
- **WHEN** running subprocesses
- **THEN** shell=True is not used and arguments are safely passed
