## ADDED Requirements
### Requirement: OAuth and Sessions
The system SHALL support optional OAuth providers configured via dev.toml (`auth.providers` list and `[auth.<provider>].enabled` flags), associate data with users when authenticated, and allow public, ungated access to endpoints. Supported providers include Google and Discord; Apple is optional.

#### Scenario: Public endpoints without gating
- **WHEN** a user calls workflow endpoints without authentication
- **THEN** the request is accepted (no gating) and processed anonymously

#### Scenario: OAuth login
- **WHEN** a user authenticates via Google or Discord (Apple optional)
- **THEN** a session is established and future requests are associated to the user

#### Scenario: Anonymous continuity
- **WHEN** a user starts anonymously and later logs in
- **THEN** the system associates prior session context where possible without blocking access

#### Scenario: No providers configured
- **WHEN** `auth.providers=[]` in dev.toml OR all `[auth.<provider>].enabled=false`
- **THEN** endpoints remain public and functional in anonymous mode

#### Scenario: Single provider enabled
- **WHEN** a provider is present in `auth.providers` AND `[auth.<provider>].enabled=true`
- **THEN** only that provider issues sessions; others are unavailable

#### Scenario: Multiple providers enabled
- **WHEN** multiple providers appear in `auth.providers` AND have `enabled=true`
- **THEN** any listed+enabled provider can be used for authentication

#### Scenario: Unknown provider in list
- **WHEN** an unknown provider string appears in `auth.providers`
- **THEN** it is logged and ignored without failing initialization

#### Scenario: Enabled but missing secrets
- **WHEN** a listed+enabled provider lacks required secrets via environment
- **THEN** it is logged and skipped; other providers and anonymous access continue operating

### Requirement: Chat History
The system SHALL persist chat messages per user (or anonymous session) and support retrieval.

#### Scenario: Store chat message
- **WHEN** a message is sent
- **THEN** it is stored with timestamps and linked to user or anonymous session

#### Scenario: Retrieve chat history
- **WHEN** history is requested
- **THEN** messages for the user or session are returned in order

### Requirement: Document Uploads
The system SHALL support document uploads tied to users or anonymous sessions.

#### Scenario: Upload document
- **WHEN** a document is uploaded
- **THEN** it is stored, scanned safely, and indexed for retrieval; metadata links to user or session

#### Scenario: List uploaded documents
- **WHEN** uploads are listed
- **THEN** metadata (name, size, type, created_at) is returned for that user or session
