# Engineering Principles

**Version**: 1.0.0
**Last Updated**: 2025-11-12
**Project**: Ontologic API

This document defines the core engineering principles that govern all feature development in this project. Every specification, plan, and implementation must align with these principles.

---

## Purpose

The Engineering Principles serve as your team's engineering standards. When in doubt, refer to these principles. When principles conflict with convenience, principles win.

---

## Core Principles

### 1. Specification First

**Principle**: Every feature begins with a written specification that defines requirements, success criteria, and acceptance tests before any code is written.

**Why**: Specifications prevent scope creep, align stakeholders, and create an auditable trail of decisions.

**Implementation**:
- Use `/feature` to create specifications
- Specifications must define: purpose, user stories, acceptance criteria, out-of-scope items
- No implementation work starts until spec is reviewed and approved
- Changes to requirements require spec updates first

**Examples (Python/FastAPI)**:
```python
# ✅ Correct: Spec-first approach
# 1. Create spec.md in specs/005-paper-generation/
# 2. Define: "POST /api/papers/generate generates academic papers from queries"
# 3. Acceptance criteria: "Returns paper with APA citations, <30s generation time"
# 4. Implement after spec approved

# ❌ Wrong: Code-first approach
@router.post("/api/papers/generate")
async def generate_paper(request: PaperRequest):
    # Started coding without spec - what format? what citations? what timeline?
    pass
```

**Violations**:
- ❌ Starting implementation without a spec
- ❌ Adding features not in the spec without updating it first
- ❌ Skipping stakeholder review of specifications

---

### 2. Testing Standards

**Principle**: All production code must have automated tests with minimum 80% code coverage.

**Why**: Tests prevent regressions, document behavior, and enable confident refactoring.

**Implementation**:
- Unit tests for business logic (80%+ coverage required)
- Integration tests for API contracts
- E2E tests for critical user flows
- Tests written alongside implementation (not after)
- Use `/tasks` phase to include test tasks in implementation plan

**Examples (Python/FastAPI)**:
```python
# ✅ Correct: Test-driven development
# app/services/paper_service.py
class PaperService:
    def generate_paper(self, query: str, philosopher: str) -> str:
        """Generate academic paper from query."""
        return self._format_paper(query, philosopher)

# tests/unit/test_paper_service.py
def test_generate_paper_returns_formatted_text():
    service = PaperService()
    paper = service.generate_paper("What is virtue?", "Aristotle")

    assert "Introduction" in paper
    assert "References" in paper
    assert len(paper) > 100

# tests/integration/test_paper_api.py
@pytest.mark.asyncio
async def test_generate_paper_endpoint(client: AsyncClient, auth_token: str):
    response = await client.post(
        "/api/papers/generate",
        json={"query": "What is virtue?", "philosopher": "Aristotle"},
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert response.status_code == 200
    assert "paper_text" in response.json()

# ❌ Wrong: No tests
@router.post("/api/papers/generate")
async def generate_paper(request: PaperRequest):
    return {"paper_text": "..."}  # No tests - how do we know it works?
```

**Violations**:
- ❌ Merging code without tests
- ❌ Skipping tests for "simple" features
- ❌ Writing tests only after implementation is complete

---

### 3. Performance Requirements

**Principle**: Define and enforce performance thresholds for all user-facing features.

**Why**: Performance is a feature, not an optimization task. Users abandon slow experiences.

**Implementation**:
- API responses: <200ms p50, <500ms p95
- LLM queries: <3s p95 (streamed to reduce perceived latency)
- Database queries: <50ms for reads, <100ms for writes
- Define thresholds in spec, measure in `/optimize` phase
- Use Prometheus for validation

**Examples (Python/FastAPI)**:
```python
# ✅ Correct: Performance monitoring
from prometheus_client import Histogram

http_request_duration = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["method", "endpoint"]
)

@router.post("/api/query")
async def query_philosopher(request: QueryRequest):
    with http_request_duration.labels("POST", "/api/query").time():
        # Timed operation
        result = await llm.generate_response(request.query)
        return result

# ✅ Correct: Database query optimization
# Bad: N+1 query (fetches users one by one)
for conversation in conversations:
    user = await db.get(User, conversation.user_id)  # N queries

# Good: Eager loading (single query with JOIN)
conversations = await db.execute(
    select(ChatConversation)
    .options(joinedload(ChatConversation.user))
)

# ❌ Wrong: Unoptimized query
@router.get("/api/conversations")
async def get_conversations():
    conversations = await db.query(ChatConversation).all()
    for conv in conversations:
        conv.user = await db.get(User, conv.user_id)  # N+1 query
    return conversations
```

**Violations**:
- ❌ Shipping features without performance benchmarks
- ❌ Ignoring performance regressions in code review
- ❌ N+1 queries, unbounded loops, blocking operations

---

### 4. Accessibility (a11y)

**Principle**: All API responses must be machine-readable and follow standard formats for accessibility tools.

**Why**: APIs serve diverse clients (web, mobile, screen readers, third-party integrations). Standard formats enable accessibility.

**Implementation (API-specific)**:
- Use semantic HTTP status codes (200, 400, 401, 404, 500)
- Follow RFC 7807 Problem Details for errors
- Provide clear error messages with actionable guidance
- Use standard OpenAPI documentation (auto-generated by FastAPI)
- Support pagination for large datasets (cursor-based pagination)

**Examples (Python/FastAPI)**:
```python
# ✅ Correct: RFC 7807 Problem Details
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
    detail="You have exceeded your daily quota of 100 requests. Upgrade to BASIC tier for 1,000 requests/day.",
    quota_limit=100,
    quota_used=100,
    quota_reset="2025-11-13T00:00:00Z"
)

# ✅ Correct: Cursor-based pagination
@router.get("/api/conversations")
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
        "next_cursor": conversations[-1].created_at if conversations else None,
        "has_more": len(conversations) == limit
    }

# ❌ Wrong: Generic error message
@router.post("/api/query")
async def query_philosopher(request: QueryRequest):
    if not request.query:
        raise HTTPException(400, "Bad request")  # Not helpful
```

**Violations**:
- ❌ Generic error messages ("Bad request", "Server error")
- ❌ Missing pagination (returning 10,000 items in single response)
- ❌ Non-standard error formats (custom JSON without RFC 7807)

---

### 5. Security Practices

**Principle**: Security is not optional. All features must follow secure coding practices.

**Why**: Breaches destroy trust and can be catastrophic for users and the business.

**Implementation**:
- Input validation on all user-provided data (Pydantic models)
- Parameterized queries (SQLModel ORM, no string concatenation for SQL)
- Authentication/authorization checks on all protected routes (JWT)
- Secrets in environment variables, never committed to code
- Security review during `/optimize` phase

**Examples (Python/FastAPI)**:
```python
# ✅ Correct: Input validation with Pydantic
from pydantic import BaseModel, Field, validator

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    philosopher: str = Field(..., regex="^[A-Za-z]+$")
    immersive_mode: bool = True

    @validator("philosopher")
    def validate_philosopher(cls, v):
        allowed = ["Aristotle", "Plato", "Kant", "Nietzsche"]
        if v not in allowed:
            raise ValueError(f"Philosopher must be one of: {allowed}")
        return v

# ✅ Correct: Parameterized query (SQLModel ORM)
async def get_user_by_email(email: str) -> User | None:
    result = await db.execute(
        select(User).where(User.email == email)  # Parameterized, safe
    )
    return result.scalar_one_or_none()

# ✅ Correct: JWT authentication on protected routes
from app.core.security import get_current_user

@router.get("/api/users/me")
async def get_current_user_profile(
    user: User = Depends(get_current_user)  # JWT validation
):
    return user

# ❌ Wrong: SQL injection vulnerability
async def get_user_by_email_unsafe(email: str):
    query = f"SELECT * FROM users WHERE email = '{email}'"  # Injectable!
    return await db.execute(query)

# ❌ Wrong: No authentication check
@router.get("/api/users/{user_id}")
async def get_user(user_id: int):
    return await db.get(User, user_id)  # Anyone can access any user!

# ❌ Wrong: Hardcoded secret
JWT_SECRET = "mysecretkey123"  # Never hardcode secrets!
```

**Violations**:
- ❌ Trusting user input without validation
- ❌ Exposing sensitive data in logs, errors, or responses
- ❌ Hardcoded credentials or API keys

---

### 6. Code Quality

**Principle**: Code must be readable, maintainable, and follow established patterns.

**Why**: Code is read 10x more than it's written. Optimize for future maintainers.

**Implementation**:
- Follow project style guides (Ruff linter/formatter)
- Functions <50 lines, classes <300 lines
- Meaningful names (not `x`, `temp`, `data`)
- Comments explain "why", not "what"
- DRY (Don't Repeat Yourself): Extract reusable utilities
- KISS (Keep It Simple, Stupid): Simplest solution that works

**Examples (Python/FastAPI)**:
```python
# ✅ Correct: Clear, readable code
async def generate_philosopher_response(
    query: str,
    philosopher: str,
    immersive_mode: bool = True
) -> dict[str, Any]:
    """Generate philosopher-specific response to user query.

    Args:
        query: User's question
        philosopher: Philosopher name (e.g., "Aristotle")
        immersive_mode: Whether to use philosopher's voice

    Returns:
        Dict with 'response', 'sources', and 'metadata'
    """
    # Check cache first (60% hit rate)
    cache_key = f"{philosopher}:{query}"
    if cached := await cache.get(cache_key):
        return cached

    # Generate embeddings and search
    embeddings = await llm.generate_embeddings(query)
    sources = await qdrant.hybrid_search(philosopher, embeddings, top_k=10)

    # Generate response (with or without immersive mode)
    prompt = build_prompt(query, sources, immersive_mode)
    response = await llm.generate_response(prompt)

    result = {
        "response": response,
        "sources": sources,
        "metadata": {"cached": False, "model": "qwen3:8b"}
    }

    await cache.set(cache_key, result, ttl=3600)
    return result

# ❌ Wrong: Unreadable, no comments
async def gen_resp(q: str, p: str, im: bool = True):
    k = f"{p}:{q}"
    if c := await cache.get(k):
        return c
    e = await llm.gen_emb(q)
    s = await qdrant.search(p, e, 10)
    pr = build_prompt(q, s, im)
    r = await llm.gen_resp(pr)
    res = {"response": r, "sources": s, "metadata": {"cached": False}}
    await cache.set(k, res, 3600)
    return res

# ✅ Correct: DRY - Extract common logic
def validate_subscription_tier(user: User, required_tier: SubscriptionTier):
    """Check if user's subscription tier meets requirement."""
    if user.subscription_tier.value < required_tier.value:
        raise ProblemDetailException(
            402,
            "Payment Required",
            f"Upgrade to {required_tier.name} tier to access this feature"
        )

# Usage
@router.post("/api/papers/generate")
async def generate_paper(user: User = Depends(get_current_user)):
    validate_subscription_tier(user, SubscriptionTier.PREMIUM)
    # ... generate paper

# ❌ Wrong: Copy-pasted logic (not DRY)
@router.post("/api/papers/generate")
async def generate_paper(user: User = Depends(get_current_user)):
    if user.subscription_tier.value < SubscriptionTier.PREMIUM.value:
        raise HTTPException(402, "Upgrade required")

@router.post("/api/reviews/create")
async def create_review(user: User = Depends(get_current_user)):
    if user.subscription_tier.value < SubscriptionTier.PREMIUM.value:
        raise HTTPException(402, "Upgrade required")
```

**Violations**:
- ❌ Copy-pasting code instead of extracting functions
- ❌ Overly clever one-liners that obscure intent
- ❌ Skipping code review feedback

---

### 7. Documentation Standards

**Principle**: Document decisions, not just code. Future you will thank you.

**Why**: Context decays fast. Documentation preserves the "why" behind decisions.

**Implementation**:
- Update `NOTES.md` during feature development (decisions, blockers, pivots)
- API endpoints: Document request/response schemas (OpenAPI/Swagger - FastAPI auto-generates)
- Complex logic: Add inline comments explaining rationale
- Breaking changes: Update CHANGELOG.md
- User-facing features: Update user docs

**Examples (Python/FastAPI)**:
```python
# ✅ Correct: Docstring explains "why"
async def cache_embeddings(query: str, embeddings: list[float], ttl: int = 3600):
    """Cache embeddings with 1-hour TTL.

    We cache embeddings because generating them takes 80-100ms, and 60% of queries
    are duplicates (e.g., "What is virtue?" asked repeatedly). Caching reduces
    average latency from 100ms to 5ms for cache hits.

    Args:
        query: Original query text (cache key)
        embeddings: 768-dim vector from Ollama
        ttl: Time to live in seconds (default 1 hour)
    """
    cache_key = f"embedding:{query}"
    await cache.set(cache_key, embeddings, ttl)

# ✅ Correct: OpenAPI documentation (FastAPI auto-generates)
@router.post(
    "/api/query",
    summary="Query philosopher",
    description="Perform semantic query with philosopher-specific context using hybrid vector search (SPLADE + Dense embeddings)",
    response_description="Generated response with ranked sources and metadata",
    tags=["Query"]
)
async def query_philosopher(request: QueryRequest):
    pass

# ❌ Wrong: Cryptic code, no comments
async def proc(q: str, p: str):  # What does this do?
    e = await llm.emb(q)  # Why embed?
    r = await qdrant.s(p, e)  # What is 's'?
    return r
```

**Violations**:
- ❌ Undocumented API changes
- ❌ Empty NOTES.md after multi-week features
- ❌ Cryptic commit messages ("fix stuff", "updates")

---

### 8. Do Not Overengineer

**Principle**: Ship the simplest solution that meets requirements. Iterate later.

**Why**: Premature optimization wastes time and creates complexity debt.

**Implementation**:
- YAGNI (You Aren't Gonna Need It): Build for today, not hypothetical futures
- Use proven libraries instead of custom implementations
- Defer abstractions until patterns emerge (Rule of Three)
- Ship MVPs, gather feedback, iterate

**Examples (Python/FastAPI)**:
```python
# ✅ Correct: Simple, direct implementation
@router.post("/api/query")
async def query_philosopher(request: QueryRequest):
    """Simple implementation: generate embeddings, search, respond."""
    embeddings = await llm.generate_embeddings(request.query)
    sources = await qdrant.hybrid_search(request.philosopher, embeddings)
    response = await llm.generate_response(request.query, sources)
    return {"response": response, "sources": sources}

# ❌ Wrong: Over-engineered with unnecessary abstraction
class AbstractQueryStrategy(ABC):
    @abstractmethod
    async def execute(self, request: QueryRequest) -> QueryResponse:
        pass

class PhilosopherQueryStrategy(AbstractQueryStrategy):
    async def execute(self, request: QueryRequest) -> QueryResponse:
        # ... complex strategy pattern for single use case

class QueryStrategyFactory:
    def create_strategy(self, request: QueryRequest) -> AbstractQueryStrategy:
        # ... factory pattern when we only have one strategy

# ✅ Correct: Use existing library (Stripe SDK)
import stripe

stripe.api_key = settings.STRIPE_SECRET_KEY
intent = stripe.PaymentIntent.create(amount=1000, currency="usd")

# ❌ Wrong: Custom payment implementation
class CustomPaymentProcessor:
    def __init__(self):
        self.api_url = "https://api.stripe.com/v1"
        # ... reinventing Stripe SDK (already exists and well-tested)
```

**Violations**:
- ❌ Building frameworks when a library exists
- ❌ Abstracting after one use case
- ❌ Optimization without profiling data

---

## Conflict Resolution

When principles conflict (e.g., "ship fast" vs "test thoroughly"), prioritize in this order:

1. **Security** - Never compromise on security
2. **Accessibility** - Legal and ethical obligation (API contracts, error formats)
3. **Testing** - Prevents regressions, enables velocity
4. **Specification** - Alignment prevents waste
5. **Performance** - User experience matters
6. **Code Quality** - Long-term maintainability
7. **Documentation** - Preserves context
8. **Simplicity** - Avoid premature optimization

---

## Amendment Process

These principles evolve with your project. To propose changes:

1. Run `/update-project-config` with your proposed change
2. Review the diff
3. Commit if approved

**Versioning**:
- **MAJOR**: Removed principle or added mandatory requirement
- **MINOR**: Added principle or expanded guidance
- **PATCH**: Fixed typo or updated date

---

## References

- Project Overview: `docs/project/overview.md`
- Tech Stack: `docs/project/tech-stack.md`
- System Architecture: `docs/project/system-architecture.md`
- Development Workflow: `docs/project/development-workflow.md`
