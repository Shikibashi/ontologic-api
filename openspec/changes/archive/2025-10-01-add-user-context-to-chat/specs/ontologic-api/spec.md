# Ontologic API Spec Delta

## ADDED Requirements

### Requirement: Chat history with user context tracking

The system SHALL track chat conversations and messages with optional username attribution for multi-user support and PDF context integration.

#### Scenario: Store message with username

- WHEN a chat message is stored via the chat history service with a username parameter
- THEN the message is saved in PostgreSQL with the username field populated
- AND the message is uploaded to Qdrant with username in the payload metadata
- AND the username is indexed for efficient user-based queries

#### Scenario: Store message without username (backward compatible)

- WHEN a chat message is stored without a username parameter
- THEN the message is saved with username=NULL
- AND the system functions normally using session_id for isolation

#### Scenario: Retrieve conversation history by username

- WHEN conversation history is queried with both session_id and username
- THEN the system returns only messages matching both criteria
- AND results are ordered by creation timestamp (oldest first)

#### Scenario: Search user's PDF context during chat

- WHEN a chat query includes username and `include_pdf_context=true`
- AND the user has uploaded PDFs to their collection
- AND the configuration flag `APP_CHAT_USE_PDF_CONTEXT` is enabled
- THEN the system searches the user's PDF collection in Qdrant
- AND retrieves top 5 relevant PDF chunks based on semantic similarity
- AND includes PDF context in the conversation history for LLM processing

#### Scenario: Handle missing PDF collection gracefully

- WHEN PDF context is requested for a username with no uploaded documents
- THEN the system logs an info message and continues without PDF context
- AND the chat request succeeds without throwing an error

### Requirement: POST /chat/message — Store chat message with user context

The system SHALL expose a POST endpoint `/chat/message` for storing chat messages with optional username tracking.

#### Scenario: Store user message

- WHEN a valid chat message request is submitted with role="user"
- THEN the message is stored in PostgreSQL chat_messages table
- AND the message is uploaded to Qdrant Chat_History collection with vector embedding
- AND a 201 Created response is returned with the message_id

#### Scenario: Include username in storage

- WHEN the request includes a `username` query parameter
- THEN the username is stored in both PostgreSQL and Qdrant payload
- AND the message is associated with the user for future retrieval

#### Scenario: Session isolation maintained

- WHEN messages are stored with different session_ids
- THEN each session's messages remain isolated
- AND username parameter does not bypass session privacy

Examples:
- Request:
```bash
curl -X POST "http://localhost:8080/chat/message?session_id=abc123&username=john_doe" \
  -H "Content-Type: application/json" \
  -d '{
    "role": "user",
    "content": "What is virtue ethics?",
    "philosopher_collection": "Aristotle"
  }'
```
- Response:
```json
{
  "message_id": "msg-uuid-123",
  "session_id": "abc123",
  "conversation_id": "conv-uuid-456",
  "username": "john_doe",
  "role": "user",
  "content": "What is virtue ethics?",
  "created_at": "2025-10-01T12:34:56Z"
}
```

### Requirement: GET /chat/history — Retrieve conversation history with user filtering

The system SHALL expose a GET endpoint `/chat/history` for retrieving stored conversation messages with optional user-based filtering.

#### Scenario: Retrieve by session only

- WHEN session_id is provided without username
- THEN all messages for that session are returned (existing behavior)

#### Scenario: Retrieve by session and username

- WHEN both session_id and username are provided
- THEN only messages matching both criteria are returned
- AND privacy isolation is enforced (session_id must match)

#### Scenario: Pagination support

- WHEN limit and offset parameters are provided
- THEN results are paginated accordingly
- AND total count is included in the response metadata

Examples:
- Request:
```bash
curl "http://localhost:8080/chat/history?session_id=abc123&username=john_doe&limit=50&offset=0"
```
- Response:
```json
{
  "messages": [
    {
      "message_id": "msg-1",
      "role": "user",
      "content": "What is virtue ethics?",
      "created_at": "2025-10-01T12:34:56Z"
    },
    {
      "message_id": "msg-2",
      "role": "assistant",
      "content": "Virtue ethics emphasizes...",
      "created_at": "2025-10-01T12:35:10Z"
    }
  ],
  "total": 2,
  "limit": 50,
  "offset": 0
}
```

### Requirement: POST /chat/search — Semantic search with PDF context integration

The system SHALL expose a POST endpoint `/chat/search` for semantic search across chat history with optional PDF context retrieval.

#### Scenario: Search chat history only

- WHEN a search query is submitted without `include_pdf_context`
- THEN the system searches only the chat message vectors in Qdrant
- AND returns messages ranked by semantic similarity

#### Scenario: Search with PDF context enabled

- WHEN `include_pdf_context=true` and username is provided
- AND the user has uploaded PDFs
- THEN the system searches both chat history and user's PDF collection
- AND returns combined results with source attribution (chat vs PDF)

#### Scenario: PDF context disabled by configuration

- WHEN `include_pdf_context=true` but `APP_CHAT_USE_PDF_CONTEXT=false`
- THEN PDF context search is skipped
- AND only chat history results are returned

Examples:
- Request:
```bash
curl -X POST "http://localhost:8080/chat/search?session_id=abc123&username=john_doe" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "virtue ethics",
    "include_pdf_context": true,
    "limit": 10
  }'
```
- Response:
```json
{
  "results": [
    {
      "source": "chat",
      "message_id": "msg-123",
      "content": "Virtue ethics emphasizes...",
      "score": 0.92,
      "created_at": "2025-10-01T12:35:10Z"
    },
    {
      "source": "pdf",
      "file_id": "file-uuid-789",
      "filename": "Nicomachean_Ethics.pdf",
      "content": "Aristotle argues that eudaimonia...",
      "score": 0.87,
      "chunk_index": 5
    }
  ],
  "total": 2
}
```

### Requirement: POST /documents/upload — Upload documents for user context

The system SHALL expose a POST endpoint `/documents/upload` for uploading documents (PDF, Markdown, DOCX, TXT) to user-specific Qdrant collections with username-based organization.

#### Scenario: Upload PDF document

- WHEN a PDF file is uploaded with username parameter
- THEN the system extracts text from the PDF using pymupdf4llm
- AND chunks the content semantically using LlamaIndex
- AND generates dense vector embeddings for each chunk
- AND stores chunks in Qdrant under the username collection
- AND includes metadata (filename, author, title, topic, username, chunk_index)

#### Scenario: Upload Markdown document

- WHEN a Markdown (.md) file is uploaded with username parameter
- THEN the system parses the markdown content
- AND chunks the content semantically
- AND generates embeddings and stores in username's Qdrant collection
- AND preserves markdown structure in metadata

#### Scenario: Upload DOCX document

- WHEN a DOCX file is uploaded with username parameter
- THEN the system extracts text using python-docx
- AND chunks the content semantically
- AND generates embeddings and stores in username's Qdrant collection
- AND extracts document metadata (title, author, subject) when available

#### Scenario: Upload TXT document

- WHEN a plain text (.txt) file is uploaded with username parameter
- THEN the system reads the text content
- AND chunks the content semantically
- AND generates embeddings and stores in username's Qdrant collection

#### Scenario: Username required for uploads

- WHEN a document upload is attempted without username parameter
- THEN the system returns a 400 Bad Request error
- AND provides a clear error message requiring username

#### Scenario: Duplicate file handling

- WHEN a file with the same name is uploaded by the same user
- THEN the system generates a new file_id for the upload
- AND both versions are stored independently
- AND metadata includes upload timestamp for differentiation

#### Scenario: File size validation

- WHEN an uploaded file exceeds the maximum size limit (configured)
- THEN the system returns a 413 Payload Too Large error
- AND includes the size limit in the error message

Examples:
- Request:
```bash
curl -X POST "http://localhost:8080/documents/upload?username=john_doe" \
  -F "file=@Nicomachean_Ethics.pdf"
```
- Response:
```json
{
  "status": "success",
  "file_id": "file-uuid-123",
  "filename": "Nicomachean_Ethics.pdf",
  "collection": "john_doe",
  "chunks_uploaded": 42,
  "metadata": {
    "title": "Nicomachean Ethics",
    "author": "Aristotle",
    "document_type": "PDF"
  }
}
```

### Requirement: GET /documents/list — List uploaded documents

The system SHALL expose a GET endpoint `/documents/list` for retrieving a list of all documents uploaded by a user.

#### Scenario: List user's documents

- WHEN username parameter is provided
- THEN the system queries the username's Qdrant collection
- AND returns unique files with metadata
- AND groups chunks by file_id

#### Scenario: Pagination for document list

- WHEN limit and offset parameters are provided
- THEN results are paginated accordingly
- AND total document count is included

Examples:
- Request:
```bash
curl "http://localhost:8080/documents/list?username=john_doe&limit=20&offset=0"
```
- Response:
```json
{
  "documents": [
    {
      "file_id": "file-uuid-123",
      "filename": "Nicomachean_Ethics.pdf",
      "document_type": "PDF",
      "chunks": 42,
      "uploaded_at": "2025-10-01T10:00:00Z",
      "metadata": {
        "title": "Nicomachean Ethics",
        "author": "Aristotle"
      }
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### Requirement: DELETE /documents/{file_id} — Delete uploaded document

The system SHALL expose a DELETE endpoint `/documents/{file_id}` for removing a document and all its chunks from the user's collection.

#### Scenario: Delete user's document

- WHEN file_id and username are provided
- AND the file belongs to the specified user
- THEN the system deletes all chunks with matching file_id from Qdrant
- AND returns a success confirmation

#### Scenario: Unauthorized deletion attempt

- WHEN file_id is provided but username doesn't match the file owner
- OR username parameter is missing
- THEN the system returns a 403 Forbidden error

Examples:
- Request:
```bash
curl -X DELETE "http://localhost:8080/documents/file-uuid-123?username=john_doe"
```
- Response:
```json
{
  "status": "success",
  "file_id": "file-uuid-123",
  "filename": "Nicomachean_Ethics.pdf",
  "chunks_deleted": 42
}
```

### Requirement: MODIFIED /ask_philosophy endpoint — Include username and PDF context

The system SHALL accept optional username parameter in the `/ask_philosophy` endpoint and support PDF context integration during answer generation.

#### Scenario: Answer with PDF context

- WHEN `username` query parameter is provided
- AND user has uploaded relevant PDFs
- AND `include_pdf_context=true` in request body
- THEN the system retrieves relevant PDF chunks from user's collection
- AND includes PDF context alongside philosopher collection context in the LLM prompt
- AND generates answer considering both sources

#### Scenario: Backward compatibility maintained

- WHEN username is not provided (existing behavior)
- THEN the endpoint functions as before using only philosopher collections
- AND no breaking changes occur for existing clients

Examples:
- Request:
```bash
curl -X POST "http://localhost:8080/ask_philosophy?session_id=abc123&username=john_doe&temperature=0.3" \
  -H "Content-Type: application/json" \
  -d '{
    "query_str": "What is eudaimonia?",
    "collection": "Aristotle",
    "include_pdf_context": true,
    "conversation_history": []
  }'
```
- Response includes context from both Aristotle collection and user's uploaded PDFs about virtue ethics.

## ADDED Requirements

### Requirement: Database schema includes username fields (NEW)

The system SHALL store username as an optional indexed field in chat-related database tables.

#### Scenario: ChatConversation includes username

- WHEN a new conversation is created
- THEN the conversation record includes a nullable username field
- AND the username is indexed for efficient queries

#### Scenario: ChatMessage includes username

- WHEN a new message is stored
- THEN the message record includes a nullable username field
- AND the username is indexed for efficient queries
- AND composite index (username, created_at) supports user history queries

### Requirement: Paper draft and review workflows with user context tracking (NEW)

The system SHALL support optional username attribution across paper draft generation and review workflows.

#### Scenario: Create draft with username

- WHEN a draft is created with a username field in the request
- THEN the draft is stored with username in the paper_drafts table
- AND username is indexed for efficient filtering

#### Scenario: Create draft without username (backward compatible)

- WHEN a draft is created without specifying username
- THEN the draft is stored with username=NULL
- AND existing clients continue functioning

#### Scenario: Generate sections with ownership validation

- WHEN sections are generated for a draft_id and username is provided
- THEN the system verifies the draft's stored username (if present) matches the provided username
- AND rejects with 403 if mismatch occurs

#### Scenario: Review draft with user context

- WHEN /workflows/{draft_id}/ai-review is called with matching username
- THEN the review workflow proceeds normally
- AND MAY incorporate user-uploaded document context in future enhancements (non-normative note)

#### Scenario: Apply suggestions with ownership validation

- WHEN /workflows/{draft_id}/apply is called with a username
- THEN the system verifies ownership before applying suggestions
- AND rejects with 403 if username mismatch

#### Scenario: List drafts filtered by username

- WHEN /workflows endpoint is queried with username parameter
- THEN only drafts belonging to that username are returned
- AND pagination parameters (limit, offset) remain supported

#### Scenario: Unauthorized draft access

- WHEN a draft operation (status, review, generate, apply) is attempted with a different username than stored
- THEN the system returns 403 Forbidden


### Requirement: Integrated workflow testing for documents, chat, and review (NEW)

The system SHALL provide end-to-end support for a user to (a) upload documents, (b) generate a research paper draft, (c) perform an AI review, and (d) conduct chat queries enriched by uploaded document context.

#### Scenario: End-to-end paper generation with prior PDF upload
- WHEN a user uploads a PDF document with philosophical content
- AND then creates a paper draft with the same username
- AND generates all sections
- THEN the draft workflow completes through GENERATED status without errors
- AND the system logs (non-normative) that document context is available for potential future integration

#### Scenario: Review after document upload
- WHEN a draft reaches GENERATED status for a username with uploaded documents
- AND the user invokes /workflows/{draft_id}/ai-review with the same username
- THEN the review completes successfully with REVIEWED status
- AND suggestions are generated (≥ 1) unless content is trivially empty

#### Scenario: Chat query referencing uploaded document
- WHEN the user performs POST /chat/search with include_pdf_context=true and username
- AND the user has at least one uploaded document
- THEN the response contains at least one result with source="pdf" (assuming embedding and similarity above internal threshold)

#### Scenario: Ask philosophy with document context
- WHEN the user calls /ask_philosophy with include_pdf_context=true and username
- THEN the system attempts retrieval from both philosopher collection and user document collection
- AND returns an answer (HTTP 200) even if no document context is found

#### Scenario: Ownership isolation across workflows
- WHEN user A uploads a document and creates a draft
- AND user B attempts to review or generate sections for user A's draft using a different username
- THEN the system returns 403 Forbidden

#### Scenario: Multiple document types support workflow
- WHEN the user uploads PDF, MD, DOCX, and TXT files
- AND performs a chat search with include_pdf_context=true
- THEN results MAY include chunks from any of the uploaded document types (non-deterministic ordering)

#### Scenario: Draft listing filtered by username with documents present
- WHEN the user lists drafts with ?username=john_doe
- THEN only drafts created by john_doe are returned regardless of other users' uploads




#### Scenario: Backward compatibility with NULL username

- WHEN existing records have username=NULL
- THEN queries and operations handle NULL gracefully
- AND filtering by username uses IS NULL or matches provided value

## Configuration Requirements

### Requirement: PDF context feature flag

The system SHALL provide a configuration flag to enable/disable PDF context integration.

#### Scenario: Feature flag enabled

- WHEN `APP_CHAT_USE_PDF_CONTEXT=true` in environment configuration
- THEN PDF context search is available when requested via API
- AND system searches user PDF collections when username provided

#### Scenario: Feature flag disabled (default)

- WHEN `APP_CHAT_USE_PDF_CONTEXT=false` or unset
- THEN PDF context search is disabled regardless of API parameters
- AND requests with `include_pdf_context=true` log warning and skip PDF search
