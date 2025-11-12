# Design: User Context in Chat History

## Context

The ontologic-api currently has two separate systems for managing user content:

1. **PDF Upload System**: Stores documents in user-specific Qdrant collections with `username` in metadata
2. **Chat History System**: Stores conversations in PostgreSQL and Qdrant with only `session_id` for isolation

These systems are disconnected, preventing users from leveraging their uploaded PDFs during chat conversations. Additionally, chat history lacks proper user attribution needed for multi-user scenarios and data governance.

## Goals

- Enable username-based tracking for all chat conversations
- Expose document upload API for PDF, Markdown, DOCX, and TXT files
- Allow chat system to optionally retrieve context from user's uploaded documents
- Maintain backward compatibility with existing session-based API usage
- Prepare foundation for future user authentication integration

## Non-Goals

- Full user authentication system (future work)
- Automatic PDF context injection (opt-in only)
- Migration of existing session_id-only data to username-based (nullable field approach)
- Real-time PDF processing during chat (search existing uploaded content only)

## Decisions

### 0. Document Upload API Architecture

**Decision**: Create new `/documents/*` router exposing existing `QdrantUploadService` functionality

**Rationale**:
- Backend upload service already exists and supports all required file types (PDF, MD, DOCX, TXT)
- Service already handles parsing, chunking, embedding, and Qdrant storage
- Just needs API endpoints to expose this functionality to clients
- Reuse proven implementation rather than rebuilding

**Implementation**:
- Create `app/router/documents.py` with three endpoints:
  - `POST /documents/upload` - Upload single document with multipart/form-data
  - `GET /documents/list` - List user's uploaded documents
  - `DELETE /documents/{file_id}` - Delete document and all chunks
- Wire to existing `QdrantUploadService` instance
- Add username validation and authorization checks

**File handling**:
```python
# Endpoint receives FastAPI UploadFile
@router.post("/documents/upload")
async def upload_document(
    file: UploadFile,
    username: str = Query(...),
    qdrant_upload_service: QdrantUploadServiceDep
):
    # Read file bytes
    file_bytes = await file.read()

    # Call existing service (already handles all file types)
    result = await qdrant_upload_service.upload_file(
        file_bytes=file_bytes,
        filename=file.filename,
        collection=username,  # User-specific collection
        metadata={"username": username}
    )

    return result
```

**Supported file types** (already implemented in backend):
- PDF: Parsed with pymupdf4llm (LLM-optimized extraction)
- Markdown: Direct text parsing with structure preservation
- DOCX: Parsed with python-docx library
- TXT: Direct text reading

**Security considerations**:
- File size limits (configuration: `MAX_UPLOAD_SIZE_MB`)
- File type validation via extension and magic bytes
- Username required for all uploads (no anonymous uploads)
- Future: Add antivirus scanning integration point

## Decisions

### 1. Database Schema Changes

**Decision**: Add nullable `username` column to both `ChatConversation` and `ChatMessage` tables

**Rationale**:
- Nullable allows gradual migration without breaking existing data
- Storing on both tables enables efficient queries (avoid joins for common operations)
- Denormalization acceptable given low update frequency

**Schema changes**:
```python
class ChatConversation(SQLModel, table=True):
    # ... existing fields ...
    username: Optional[str] = Field(default=None, index=True, description="User identifier for multi-user support")

class ChatMessage(SQLModel, table=True):
    # ... existing fields ...
    username: Optional[str] = Field(default=None, index=True, description="User identifier for multi-user support")
```

**Indexes**:
- Add index on `username` column for both tables
- Add composite index `(username, created_at)` for efficient user history queries

### 2. Qdrant Payload Enhancement

**Decision**: Add `username` field to chat message payloads in Qdrant collections

**Rationale**:
- Enables username-based filtering in vector search
- Maintains consistency between PostgreSQL and Qdrant metadata
- Backward compatible (existing points without username still function)

**Payload structure**:
```python
payload = {
    "message_id": str,
    "session_id": str,
    "conversation_id": str,
    "username": Optional[str],  # NEW FIELD
    "role": str,
    "content": str,
    # ... other existing fields ...
}
```

### 3. PDF Context Integration Strategy

**Decision**: Implement opt-in PDF context search via configuration flag and explicit API parameter

**Rationale**:
- Opt-in approach prevents unexpected behavior changes
- Allows performance monitoring before default enablement
- Gives users control over when to use their uploaded documents

**Implementation approach**:
- Add `APP_CHAT_USE_PDF_CONTEXT` configuration flag (default: false)
- Add optional `include_pdf_context` parameter to chat endpoints
- When enabled and username provided:
  1. Search user's PDF collection in Qdrant using chat query
  2. Retrieve top 3-5 relevant PDF chunks
  3. Append PDF context to conversation history for LLM

**Search logic**:
```python
if include_pdf_context and username and config.chat_use_pdf_context:
    # Search user's uploaded PDFs
    pdf_results = await qdrant_service.search(
        collection_name=username,  # User's PDF collection
        query_vector=query_embedding,
        filter={"username": username},
        limit=5
    )
    # Add to context for LLM
    context = format_pdf_context(pdf_results)
```

### 4. API Parameter Strategy

**Decision**: Add optional `username` query parameter to all chat endpoints

**Rationale**:
- Query parameter allows easy addition without breaking request bodies
- Optional parameter maintains backward compatibility
- Consistent with existing `session_id` parameter pattern

**Affected endpoints**:
- `POST /chat/history` - Store message with username
- `GET /chat/history/{session_id}` - Add `?username=...` filter
- `POST /chat/search/{session_id}` - Add `?username=...` for PDF context
- `POST /ask_philosophy` - Add `?username=...` for context

### 5. Backward Compatibility

**Decision**: Use nullable fields and optional parameters; no required breaking changes

**Strategy**:
- Existing API calls without username continue working
- Database migration creates nullable columns
- Services handle `username=None` gracefully
- Qdrant queries work with or without username filter

**Migration path**:
1. **Phase 1**: Add nullable columns, deploy code (this change)
2. **Phase 2** (future): Encourage username adoption via documentation
3. **Phase 3** (future): Consider requiring username for new sessions (configurable)

## Alternatives Considered

### Alternative 1: Session-to-Username Mapping Table

**Rejected**: Adds complexity with separate mapping table instead of direct field

**Trade-offs**:
- Pro: Could support multiple usernames per session
- Con: Extra join for every query
- Con: Doesn't fit current single-user-per-session model

### Alternative 2: Automatic PDF Context Injection

**Rejected**: Auto-inject PDF context for all user queries

**Trade-offs**:
- Pro: Seamless user experience
- Con: Performance impact (extra search per query)
- Con: May retrieve irrelevant content
- Con: Unexpected behavior for users
- Decision: Make opt-in instead

### Alternative 3: Require Username Immediately

**Rejected**: Make username required field in this change

**Trade-offs**:
- Pro: Clean data model from start
- Con: Breaking change for existing clients
- Con: No gradual migration path
- Decision: Use nullable for smooth transition

## Risks & Trade-offs

### Risk 1: Performance Impact from PDF Context Search

**Mitigation**:
- Opt-in design (controlled enablement)
- Cache PDF search results per query (5-minute TTL)
- Limit PDF context to top 5 chunks (configurable)
- Monitor query latency with feature flag A/B testing

### Risk 2: Data Consistency During Migration

**Mitigation**:
- Nullable columns prevent data integrity issues
- Existing records remain valid with `username=NULL`
- Application handles null username gracefully
- Monitoring for username adoption rate

### Risk 3: Username Spoofing (No Authentication)

**Mitigation**:
- Document that username is not authenticated in current phase
- Add warning in API docs about trust model
- Plan future integration with proper auth system
- Consider adding `verified_user` boolean flag for future auth

## Migration Plan

### Database Migration

```sql
-- Add username columns
ALTER TABLE chat_conversations
ADD COLUMN username VARCHAR(255);

ALTER TABLE chat_messages
ADD COLUMN username VARCHAR(255);

-- Add indexes for performance
CREATE INDEX ix_chat_conversations_username
ON chat_conversations(username);

CREATE INDEX ix_chat_messages_username
ON chat_messages(username);

CREATE INDEX ix_chat_conversations_username_created
ON chat_conversations(username, created_at);

CREATE INDEX ix_chat_messages_username_created
ON chat_messages(username, created_at);
```

### Qdrant Migration

**No migration required** - new field is additive:
- Existing points: `username` field absent (queries still work)
- New points: Include `username` in payload
- Queries can filter by username when present

### Rollback Plan

1. Remove username parameters from API endpoints
2. Drop database indexes
3. Drop username columns (if needed; can also leave as nullable)
4. Revert code changes

## Open Questions

1. **Q**: Should we validate username format (e.g., email, alphanumeric)?
   **A**: For now, accept any non-empty string. Add validation in future auth integration.

2. **Q**: Should PDF context search use semantic or keyword matching?
   **A**: Use same dense vector search as current chat search (semantic).

3. **Q**: What's the default behavior when username provided but user has no PDFs?
   **A**: Gracefully continue without PDF context (log info, no error).

4. **Q**: Should we add rate limiting per username?
   **A**: Not in this change. Current session-based rate limiting sufficient for now.
