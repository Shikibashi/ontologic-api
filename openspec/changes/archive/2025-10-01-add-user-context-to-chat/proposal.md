# Add User Context to Chat History and Link PDFs

## Why

Currently, the chat history system tracks conversations using `session_id` only, with no username/user identification. PDF uploads store username in Qdrant metadata, but this data is isolated from chat sessions. This creates several problems:

1. **No PDF context in chat**: When users upload PDFs, the content is stored in Qdrant but cannot be automatically retrieved during chat sessions because there's no link between the PDF's username and the chat's session_id
2. **Missing user tracking**: Chat history lacks user attribution, making it impossible to query "all conversations for user X" or provide user-specific analytics
3. **Privacy gaps**: Without username tracking, it's harder to implement proper data retention policies per user
4. **Inconsistent data model**: PDFs have username metadata, but chat messages don't

## What Changes

Add username tracking to the chat history system, enable document uploads (PDF, Markdown, DOCX, TXT), and enable optional document context retrieval during chat:

- **BREAKING**: Add `username` field to `ChatConversation` and `ChatMessage` database models
- **NEW**: Add document upload API endpoints (POST /documents/upload, GET /documents/list, DELETE /documents/{file_id})
- **NEW**: Support for uploading PDF, Markdown, DOCX, and TXT files with username-based organization
- Add username parameter to chat history API endpoints (optional but recommended)
- Modify chat storage services to accept and store username
- Add document context search capability: when username is provided, chat can optionally search user's uploaded documents for relevant context
- Update Qdrant chat collections to include username in payload metadata
- Leverage existing QdrantUploadService backend (already supports all file types)
- Maintain backward compatibility: username is optional to not break existing integrations

## Impact

### Affected Specs
- `ontologic-api/spec.md` - New chat history endpoints and user context requirements

### Affected Code
- `app/core/db_models.py` - **BREAKING**: Schema changes to ChatConversation and ChatMessage
- `app/services/chat_history_service.py` - Accept username parameter
- `app/services/chat_qdrant_service.py` - Include username in vector metadata
- `app/services/qdrant_upload.py` - Already supports all file types (leverage existing)
- `app/router/chat_history.py` - Update endpoints to accept username
- `app/router/documents.py` - **NEW**: Create document upload/list/delete endpoints
- `app/router/ontologic.py` - Pass username to chat storage
- Database migration required for adding username columns

### Migration Strategy
1. Add nullable `username` column to existing tables
2. Existing records will have `username = NULL`
3. New API requests can optionally provide username
4. Future enhancement: require username for new sessions (configurable)

### Breaking Changes
- Database schema modification requires migration
- Qdrant chat collection payload structure changes (backward compatible - new field)

### Non-Breaking Changes
- API endpoints accept optional `username` parameter (defaults to None)
- Existing clients continue working without modification
- PDF context retrieval is opt-in via configuration flag










- Extend username context support to paper draft generation and review workflows (create, generate, review, apply, list)



## Implementation Status (Interim Report)

### Implementation Complete ✅

#### Core Features

✅ Username Tracking in Chat History
- Added nullable username fields to ChatConversation and ChatMessage models
- Created and applied database migration with proper indexes
- Updated services (ChatHistoryService, ChatQdrantService) to accept and store username
- Modified /ask_philosophy endpoint to accept optional username parameter
- Maintained full backward compatibility (username is optional)

✅ Document Upload Infrastructure
- Created new /documents router with 3 endpoints (upload, list, delete)
- Integrated with existing QdrantUploadService for PDF/Markdown/DOCX/TXT support
- Added file size validation and type checking
- Created Pydantic models for all responses
- Added configuration settings (max_upload_size_mb, chat_use_pdf_context, pdf_context_limit)

✅ Configuration & Integration
- Added settings to settings.py with proper Field() declarations
- Registered documents router in main app
- Updated helper functions to pass username through the stack
- Proper logging throughout

### Critical Review Findings

The code-review-expert identified 3 CRITICAL and 5 HIGH priority issues that need attention before production:

🔴 CRITICAL Issues
1. Security: Missing content-based file validation (extension checking alone is insufficient; need magic byte validation)
2. Security: Missing authentication/authorization (any user can potentially access/delete other users' documents)
3. Incomplete Feature: PDF context retrieval not implemented (settings exist but actual document context injection during chat is missing)

🟡 HIGH Priority Issues
4. Document list endpoint returns empty results (stubbed out)
5. Migration drops useful indexes unnecessarily
6. Poor error messages on parsing failures
7. No test coverage for new endpoints
8. Memory inefficiency in document listing (loads all points)

✅ Strengths Noted
- Solid database schema design with proper indexes
- Consistent service layer patterns
- Good type safety with Pydantic
- Backward compatibility maintained
- Configuration management follows existing patterns

### Recommendations

For Development/Testing:
- Implementation is functional for basic username tracking and chat history.
- Document upload infrastructure is in place but needs hardening.

Before Production (Must Address First):
1. Add authentication dependency (e.g., CurrentUsernameDep) to protect document endpoints
2. Implement content-based file validation using python-magic or similar
3. Complete the PDF context retrieval feature in /ask_philosophy
4. Implement the document list endpoint properly
5. Add comprehensive test coverage

Immediate Next Steps:
1. Review detailed feedback from code-review-expert
2. Prioritize fixing the 3 CRITICAL security issues
3. Consider adding a feature flag (document_uploads_enabled) to disable uploads until hardened
4. Write integration tests for the full upload → chat workflow

Status Summary:
- Username tracking for chat history: Production-ready
- Document upload system: Requires security hardening & feature completion
- PDF context integration: Pending implementation

