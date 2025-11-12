# API Style Guide

**Project**: Ontologic API
**Last Updated**: 2025-11-12
**Version**: 1.0.0

This style guide defines standards for API design, JSON structure, error formats, and code conventions. It serves as the single source of truth for all API-related design decisions.

---

## Philosophy

**"Consistency is the API developer's best friend"** - Predictable patterns reduce cognitive load. Every API endpoint should follow the same conventions for naming, error handling, and response structure.

**"Self-documenting APIs"** - Well-designed APIs should be understandable without extensive documentation. Use descriptive names, standard HTTP methods, and clear error messages.

---

## 1. API Design Principles

### RESTful Resource Modeling

**Rule**: Resources as plural nouns, HTTP verbs for actions

**Why**: REST conventions are widely understood. Consistent naming reduces learning curve.

**Implementation**:
```http
✅ Correct: RESTful design
GET    /api/users/{user_id}           # Get user
POST   /api/chat/conversations        # Create conversation
PATCH  /api/users/me                  # Update current user
DELETE /api/documents/{document_id}   # Delete document

❌ Wrong: Verbs in URLs
GET    /api/getUser/{user_id}         # Verb in URL
POST   /api/createConversation        # Verb in URL
POST   /api/users/me/update           # Use PATCH instead
```

**Naming Conventions**:
- Plural nouns for collections: `/users`, `/conversations`, `/documents`
- Singular IDs for specific resources: `/users/{user_id}`
- Lowercase, hyphen-separated: `/chat-conversations` (not `/chatConversations`)
- No file extensions: `/api/users/me` (not `/api/users/me.json`)

---

### HTTP Methods

**Standard Methods**:

| Method | Purpose | Idempotent | Safe | Response |
|--------|---------|------------|------|----------|
| GET | Retrieve resource | Yes | Yes | 200 OK, 404 Not Found |
| POST | Create resource | No | No | 201 Created, 400 Bad Request |
| PATCH | Update resource (partial) | No | No | 200 OK, 404 Not Found |
| PUT | Replace resource (full) | Yes | No | 200 OK, 404 Not Found |
| DELETE | Delete resource | Yes | No | 204 No Content, 404 Not Found |

**Examples**:
```python
# ✅ Correct: Use appropriate HTTP methods
@router.get("/api/users/{user_id}")
async def get_user(user_id: int):
    return await db.get(User, user_id)

@router.post("/api/chat/conversations")
async def create_conversation(request: CreateConversationRequest):
    conversation = ChatConversation(**request.dict())
    await db.add(conversation)
    return conversation

@router.patch("/api/users/me")
async def update_user(request: UpdateUserRequest, user: User = Depends(get_current_user)):
    for key, value in request.dict(exclude_unset=True).items():
        setattr(user, key, value)
    await db.commit()
    return user

@router.delete("/api/documents/{document_id}")
async def delete_document(document_id: int):
    document = await db.get(Document, document_id)
    await db.delete(document)
    return {"status": "deleted"}

# ❌ Wrong: Using POST for updates
@router.post("/api/users/me/update")  # Should be PATCH
async def update_user_wrong(request: UpdateUserRequest):
    pass
```

---

### URL Structure

**Pattern**: `/api/{resource}/{identifier}/{subresource}`

**Hierarchy**:
```
/api/chat/conversations                       # Collection
/api/chat/conversations/{conversation_id}     # Specific resource
/api/chat/conversations/{conversation_id}/messages  # Nested collection
```

**Query Parameters**:
- Filtering: `?philosopher=Aristotle&status=active`
- Pagination: `?cursor=2025-11-12T10:00:00Z&limit=20`
- Sorting: `?sort=created_at&order=desc`
- Fields: `?fields=id,email,username` (sparse fieldsets)

**Examples**:
```http
✅ Correct: Structured URLs
GET /api/users/me
GET /api/chat/conversations?philosopher=Aristotle&limit=20
GET /api/chat/conversations/{conversation_id}/messages?cursor=2025-11-12T10:00:00Z

❌ Wrong: Inconsistent structure
GET /api/getMyUser
GET /api/conversations/list?philosopher=Aristotle
GET /api/messages?conversation_id={id}  # Should be nested: /conversations/{id}/messages
```

---

## 2. JSON Structure

### Response Formats

**Success Response (Single Resource)**:
```json
{
  "id": 123,
  "email": "user@example.com",
  "username": "john_doe",
  "subscription_tier": "PREMIUM",
  "created_at": "2025-11-12T10:00:00Z"
}
```

**Success Response (Collection)**:
```json
{
  "data": [
    {"id": 1, "philosopher": "Aristotle", "created_at": "2025-11-12T09:00:00Z"},
    {"id": 2, "philosopher": "Plato", "created_at": "2025-11-12T08:00:00Z"}
  ],
  "next_cursor": "2025-11-12T08:00:00Z",
  "has_more": true
}
```

**Success Response (Operation Result)**:
```json
{
  "status": "success",
  "message": "Conversation deleted successfully",
  "conversation_id": 42
}
```

---

### Field Naming

**Rule**: snake_case for JSON fields (Python convention)

**Why**: Consistency with Python codebase (FastAPI/Pydantic use snake_case)

**Examples**:
```json
✅ Correct: snake_case
{
  "user_id": 123,
  "subscription_tier": "PREMIUM",
  "created_at": "2025-11-12T10:00:00Z",
  "is_active": true
}

❌ Wrong: camelCase (JavaScript convention, not Python)
{
  "userId": 123,
  "subscriptionTier": "PREMIUM",
  "createdAt": "2025-11-12T10:00:00Z"
}
```

---

### Timestamp Format

**Rule**: ISO 8601 with timezone (UTC)

**Format**: `YYYY-MM-DDTHH:MM:SSZ` (Z indicates UTC)

**Examples**:
```json
✅ Correct: ISO 8601 with UTC
{
  "created_at": "2025-11-12T10:00:00Z",
  "updated_at": "2025-11-12T14:30:45Z"
}

❌ Wrong: Epoch timestamp or ambiguous format
{
  "created_at": 1699873200,  # Epoch timestamp (harder for humans)
  "updated_at": "2025-11-12 14:30:45"  # Missing timezone
}
```

**Implementation (Pydantic)**:
```python
from pydantic import BaseModel
from datetime import datetime

class ConversationResponse(BaseModel):
    id: int
    created_at: datetime  # Pydantic serializes to ISO 8601 with timezone

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
```

---

### Enum Values

**Rule**: UPPERCASE for enum values

**Why**: Distinguish enums from regular strings, prevent case-sensitivity issues

**Examples**:
```json
✅ Correct: UPPERCASE enums
{
  "subscription_tier": "PREMIUM",
  "subscription_status": "ACTIVE",
  "role": "USER"
}

❌ Wrong: Mixed case
{
  "subscription_tier": "Premium",  # Inconsistent capitalization
  "subscription_status": "active"  # Lowercase
}
```

**Implementation (Pydantic)**:
```python
from enum import Enum

class SubscriptionTier(str, Enum):
    FREE = "FREE"
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"
    ACADEMIC = "ACADEMIC"
```

---

## 3. Error Handling

### RFC 7807 Problem Details

**Format**: Standardized error responses following RFC 7807

**Structure**:
```json
{
  "type": "https://ontologic.api/errors/rate-limit-exceeded",
  "title": "Rate Limit Exceeded",
  "status": 429,
  "detail": "You have exceeded your daily quota of 100 requests. Upgrade to BASIC tier for 1,000 requests/day.",
  "instance": "/api/query",
  "quota_limit": 100,
  "quota_used": 100,
  "quota_reset": "2025-11-13T00:00:00Z"
}
```

**Fields**:
- `type`: URI reference identifying the problem type
- `title`: Human-readable summary (short)
- `status`: HTTP status code (400, 401, 404, etc.)
- `detail`: Human-readable explanation (long, actionable)
- `instance`: URI reference to the specific occurrence
- Custom fields: Additional context (quota_limit, quota_used, etc.)

---

### HTTP Status Codes

**Standard Codes**:

| Code | Meaning | Usage |
|------|---------|-------|
| 200 | OK | Successful GET, PATCH, or operation |
| 201 | Created | Successful POST (resource created) |
| 204 | No Content | Successful DELETE (no response body) |
| 400 | Bad Request | Invalid request body, missing required fields |
| 401 | Unauthorized | Missing or invalid JWT token |
| 402 | Payment Required | Subscription upgrade needed |
| 403 | Forbidden | Insufficient permissions (not superuser) |
| 404 | Not Found | Resource doesn't exist |
| 409 | Conflict | Resource already exists (duplicate email) |
| 422 | Unprocessable Entity | Validation error (Pydantic validation) |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Unexpected server error |
| 502 | Bad Gateway | External service failure (Ollama, Qdrant) |
| 503 | Service Unavailable | Database connection failure |

---

### Error Response Examples

**Validation Error (422)**:
```json
{
  "type": "https://ontologic.api/errors/validation-error",
  "title": "Validation Error",
  "status": 422,
  "detail": "Request body validation failed",
  "errors": [
    {
      "loc": ["body", "query"],
      "msg": "field required",
      "type": "value_error.missing"
    },
    {
      "loc": ["body", "philosopher"],
      "msg": "philosopher must be one of: Aristotle, Plato, Kant, Nietzsche",
      "type": "value_error"
    }
  ]
}
```

**Authentication Error (401)**:
```json
{
  "type": "https://ontologic.api/errors/invalid-token",
  "title": "Invalid Token",
  "status": 401,
  "detail": "JWT token is expired or invalid. Please login again."
}
```

**Rate Limit Error (429)**:
```json
{
  "type": "https://ontologic.api/errors/rate-limit-exceeded",
  "title": "Rate Limit Exceeded",
  "status": 429,
  "detail": "You have exceeded your daily quota. Upgrade your subscription for higher limits.",
  "quota_limit": 100,
  "quota_used": 100,
  "quota_reset": "2025-11-13T00:00:00Z"
}
```

**Not Found Error (404)**:
```json
{
  "type": "https://ontologic.api/errors/resource-not-found",
  "title": "Resource Not Found",
  "status": 404,
  "detail": "Conversation with ID 999 not found",
  "resource_type": "conversation",
  "resource_id": 999
}
```

---

### Implementation (FastAPI)

```python
from fastapi import HTTPException

class ProblemDetailException(HTTPException):
    def __init__(self, status_code: int, title: str, detail: str, **kwargs):
        self.status_code = status_code
        self.detail = {
            "type": f"https://ontologic.api/errors/{title.lower().replace(' ', '-')}",
            "title": title,
            "status": status_code,
            "detail": detail,
            **kwargs
        }

# Usage
raise ProblemDetailException(
    status_code=429,
    title="Rate Limit Exceeded",
    detail="You have exceeded your daily quota.",
    quota_limit=100,
    quota_used=100,
    quota_reset="2025-11-13T00:00:00Z"
)
```

---

## 4. Pagination

### Cursor-Based Pagination

**Rule**: Use cursor-based pagination for all collections

**Why**: Consistent results (no skipped/duplicate rows when data changes), efficient for large datasets

**Request**:
```http
GET /api/chat/conversations?limit=20&cursor=2025-11-12T10:00:00Z
```

**Response**:
```json
{
  "data": [
    {"id": 1, "philosopher": "Aristotle", "created_at": "2025-11-12T09:00:00Z"},
    {"id": 2, "philosopher": "Plato", "created_at": "2025-11-12T08:00:00Z"}
  ],
  "next_cursor": "2025-11-12T08:00:00Z",
  "has_more": true
}
```

**Implementation**:
```python
@router.get("/api/chat/conversations")
async def get_conversations(
    cursor: str | None = None,
    limit: int = 20
):
    query = select(ChatConversation)
    if cursor:
        query = query.where(ChatConversation.created_at < cursor)
    query = query.order_by(ChatConversation.created_at.desc()).limit(limit)

    results = await db.execute(query)
    conversations = results.scalars().all()

    return {
        "data": conversations,
        "next_cursor": conversations[-1].created_at.isoformat() if conversations else None,
        "has_more": len(conversations) == limit
    }
```

---

## 5. Request Headers

### Standard Headers

**Required Headers**:
```http
Content-Type: application/json
Authorization: Bearer <JWT>
```

**Optional Headers**:
```http
Idempotency-Key: unique-key-12345  # For payment operations
Accept: application/json            # Default, can omit
User-Agent: MyApp/1.0.0             # Client identification
```

**Rate Limit Headers** (in response):
```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 42
X-RateLimit-Reset: 1699999999
Retry-After: 3600
```

---

## 6. API Versioning

### URL-Based Versioning (Future)

**Current**: No versioning (v1.0 implicit, all routes at `/api/*`)

**Future** (when breaking changes needed):
```
/api/v1/users/me  (current, stable)
/api/v2/users/me  (new version with breaking changes)
```

**Versioning Rules**:
- Major version (v1 → v2): Breaking changes (remove field, change response structure)
- Minor version: Additive changes (new fields, new endpoints) - no version bump needed

**Deprecation Policy**:
- Maintain old version for 6 months
- Add `Deprecation` header: `Deprecation: Sun, 01 Jun 2026 00:00:00 GMT`
- After 6 months: Return `410 Gone` with migration guide

---

## 7. OpenAPI Documentation

### Auto-Generated Documentation

**FastAPI generates OpenAPI 3.0 spec automatically**

**Access**:
- Swagger UI: `https://api.ontologic.com/docs`
- ReDoc: `https://api.ontologic.com/redoc`
- OpenAPI JSON: `https://api.ontologic.com/openapi.json`

**Enhancements**:
```python
from fastapi import FastAPI

app = FastAPI(
    title="Ontologic API",
    description="Semantic philosophical knowledge retrieval",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

@app.post(
    "/api/query",
    summary="Query philosopher",
    description="Perform semantic query with philosopher-specific context using hybrid vector search",
    response_description="Generated response with sources and metadata",
    tags=["Query"]
)
async def query_philosopher(request: QueryRequest):
    """
    Query a philosopher with semantic search.

    - **query**: Your question (e.g., "What is virtue?")
    - **philosopher**: Philosopher name (Aristotle, Plato, Kant, Nietzsche)
    - **immersive_mode**: Whether to use philosopher's voice (default: true)
    - **top_k**: Number of sources to retrieve (default: 10)
    """
    pass
```

---

## 8. Code Style (Python/FastAPI)

### Naming Conventions

**Functions**: snake_case
```python
✅ Correct
async def generate_philosopher_response(query: str) -> dict:
    pass

❌ Wrong
async def generatePhilosopherResponse(query: str):  # camelCase
    pass
```

**Classes**: PascalCase
```python
✅ Correct
class QueryRequest(BaseModel):
    query: str

❌ Wrong
class query_request(BaseModel):  # snake_case
    pass
```

**Constants**: UPPERCASE
```python
✅ Correct
MAX_QUERY_LENGTH = 500
DEFAULT_TOP_K = 10

❌ Wrong
maxQueryLength = 500  # camelCase
```

---

### Type Hints

**Rule**: Use type hints for all function parameters and return values

```python
✅ Correct: Full type hints
async def get_user_by_email(email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()

❌ Wrong: No type hints
async def get_user_by_email(email):  # Missing types
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()
```

---

### Docstrings

**Rule**: Use Google-style docstrings for all public functions

```python
✅ Correct
def generate_paper(query: str, philosopher: str, format: str = "APA") -> str:
    """Generate academic paper from query.

    Args:
        query: Research question or topic
        philosopher: Philosopher to focus on (e.g., "Aristotle")
        format: Citation format ("APA" or "MLA")

    Returns:
        Generated paper text with citations

    Raises:
        ValueError: If philosopher not found in database
        LLMError: If LLM generation fails
    """
    pass

❌ Wrong: No docstring
def generate_paper(query: str, philosopher: str, format: str = "APA") -> str:
    pass
```

---

## 9. Validation Rules

### Automated Checks

**Pre-Commit Checks**:
1. Linter passes (`ruff check app/`)
2. Formatter passes (`ruff format app/`)
3. Type checker passes (`pyright`)
4. Tests pass (`pytest`)

**Code Review Checks**:
1. No hardcoded secrets (JWT_SECRET, Stripe keys, etc.)
2. RFC 7807 format for all errors
3. Cursor-based pagination for collections
4. Type hints on all functions
5. Docstrings on public functions

---

## Appendix: Example API

### Complete Endpoint Example

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, validator
from datetime import datetime

router = APIRouter(prefix="/api", tags=["Query"])

class QueryRequest(BaseModel):
    """Request body for philosopher query."""
    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        example="What is virtue?"
    )
    philosopher: str = Field(
        ...,
        regex="^[A-Za-z]+$",
        example="Aristotle"
    )
    immersive_mode: bool = Field(
        True,
        example=True,
        description="Whether to use philosopher's voice"
    )
    top_k: int = Field(10, ge=1, le=50, example=10)

    @validator("philosopher")
    def validate_philosopher(cls, v):
        allowed = ["Aristotle", "Plato", "Kant", "Nietzsche"]
        if v not in allowed:
            raise ValueError(f"Philosopher must be one of: {allowed}")
        return v

class QueryResponse(BaseModel):
    """Response body for philosopher query."""
    response: str = Field(..., description="Generated response text")
    sources: list[dict] = Field(..., description="Ranked sources with scores")
    metadata: dict = Field(..., description="Query metadata (tokens, latency, cached)")

@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Query philosopher",
    description="Perform semantic query with philosopher-specific context",
    responses={
        200: {"description": "Successful query"},
        400: {"description": "Invalid request body"},
        401: {"description": "Missing or invalid JWT token"},
        429: {"description": "Rate limit exceeded"}
    }
)
async def query_philosopher(
    request: QueryRequest,
    user: User = Depends(get_current_user)
) -> QueryResponse:
    """Query philosopher with semantic search.

    Args:
        request: Query request body
        user: Authenticated user (from JWT)

    Returns:
        QueryResponse with generated response, sources, and metadata

    Raises:
        ProblemDetailException: If rate limit exceeded or philosopher not found
    """
    # Implementation
    pass
```

---

## References

- RFC 7807 Problem Details: https://tools.ietf.org/html/rfc7807
- OpenAPI Specification: https://swagger.io/specification
- FastAPI Best Practices: https://fastapi.tiangolo.com/tutorial
- REST API Guidelines: https://restfulapi.net
