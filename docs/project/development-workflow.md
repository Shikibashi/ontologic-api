# Development Workflow

**Last Updated**: 2025-11-12
**Project**: Ontologic API
**Git Workflow**: GitHub Flow (simplified)
**Team Size**: Solo developer
**Related Docs**: See `deployment-strategy.md` for CI/CD, `engineering-principles.md` for standards

---

## Git Workflow

### GitHub Flow (Simplified for Solo Developer)

**Philosophy**: Keep it simple, ship fast, main branch always deployable

**Branches**:
- `main`: Production branch (auto-deploys to production)
- `feature/*`: Short-lived feature branches (1-3 days max)

**No staging or develop branches** (direct production deployment model)

---

### Branch Strategy

**Branch Naming**:
```
feature/add-paper-generation      # New feature
fix/stripe-webhook-signature      # Bug fix
refactor/extract-llm-service      # Code refactoring
docs/update-api-strategy          # Documentation
```

**Rules**:
- Prefix with type: `feature/`, `fix/`, `refactor/`, `docs/`, `test/`
- Lowercase, hyphen-separated
- Descriptive (not `feature/feature1`)

---

### Feature Development Workflow

**Step 1: Create Branch**
```bash
# Start from main
git checkout main
git pull origin main

# Create feature branch
git checkout -b feature/add-paper-generation
```

**Step 2: Development**
```bash
# Make changes
vim app/services/paper_service.py

# Run tests locally
uv run pytest

# Commit often (small, logical commits)
git add app/services/paper_service.py
git commit -m "feat: add paper generation service"
```

**Step 3: Push and Create Pull Request**
```bash
# Push to GitHub
git push origin feature/add-paper-generation

# Create PR on GitHub (via web UI)
# Title: "feat: add paper generation service"
# Description: Feature summary, testing notes, screenshots
```

**Step 4: Self-Review** (Solo Developer Substitute for Code Review)
- Review diff on GitHub (fresh perspective)
- Check for secrets, hardcoded values
- Verify tests pass locally
- Run manual smoke tests
- Check for breaking changes

**Step 5: Merge to Main**
```bash
# Merge via GitHub UI (or command line)
git checkout main
git merge feature/add-paper-generation
git push origin main

# Delete feature branch
git branch -d feature/add-paper-generation
git push origin --delete feature/add-paper-generation
```

**Step 6: Deployment** (Automatic)
- GitHub Actions triggers on push to `main`
- Deploys to production servers
- Monitor logs and health checks

---

## Commit Messages

### Conventional Commits

**Format**: `<type>(<scope>): <subject>`

**Types**:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `refactor`: Code refactoring (no behavior change)
- `test`: Add or update tests
- `chore`: Maintenance (dependencies, config)
- `perf`: Performance improvements

**Scope** (optional): Module or component affected
- `auth`, `payments`, `chat`, `llm`, `database`, `api`

**Examples**:
```bash
feat(payments): add stripe subscription management
fix(auth): resolve JWT expiration issue
docs(api): update openapi schema for /query endpoint
refactor(llm): extract embedding cache into service
test(chat): add integration tests for conversation CRUD
chore(deps): update fastapi to 0.118.0
perf(database): add composite index on (user_id, timestamp)
```

**Subject Guidelines**:
- Imperative mood ("add feature", not "added feature")
- Lowercase, no period at end
- Max 75 characters

**Commit Body** (for complex changes):
```
feat(papers): add academic paper generation

Implements paper generation using llama-index.
Supports APA and MLA citation formats.
Adds new endpoint POST /api/papers/generate.

Closes #42
```

---

## Pull Request Process

### PR Template

**Title**: `<type>(<scope>): <summary>`

**Description**:
```markdown
## Summary
What does this PR do? Why is it needed?

## Changes
- Added `paper_service.py` for paper generation
- Updated `/api/papers/generate` endpoint
- Added Pydantic models for request/response

## Testing
- [x] Unit tests pass (`pytest`)
- [x] Integration test for paper generation
- [x] Manual test with Aristotle corpus

## Checklist
- [x] No secrets committed
- [x] Tests added/updated
- [x] Documentation updated (if public API changed)
- [x] Database migration tested (if schema changed)
```

**Labels** (GitHub):
- `feature`, `bugfix`, `documentation`, `refactor`
- `breaking-change` (for backwards-incompatible changes)
- `hotfix` (urgent production fix)

---

### Self-Review Checklist (Solo Developer)

**Before Merging**:
- [ ] Code compiles and runs locally
- [ ] Tests pass (`uv run pytest`)
- [ ] Linter passes (`uv run ruff check app/`)
- [ ] No secrets or API keys in code (check with `git secrets` or manual review)
- [ ] Database migration tested (if schema changed)
- [ ] Breaking changes documented (if API contract changed)
- [ ] OpenAPI docs updated (FastAPI auto-generates, verify)
- [ ] Performance impact considered (new N+1 queries? slow algorithms?)
- [ ] Security implications reviewed (new auth bypass? SQL injection risk?)

---

## Testing Strategy

### Test Pyramid

**Philosophy**: Fast, isolated unit tests at base; slower integration tests at top

```
       /\
      /  \     E2E Tests (5%)
     /----\    Integration Tests (15%)
    /      \   Unit Tests (80%)
   /________\
```

**Unit Tests** (80%):
- Test individual functions, classes
- Mock external dependencies (database, LLM, Qdrant)
- Fast (<1s total runtime for all unit tests)

**Integration Tests** (15%):
- Test API endpoints with real database (test DB)
- Mock expensive operations (LLM, Qdrant)
- Moderate speed (10-30s runtime)

**E2E Tests** (5%):
- Test full user flows (register → query → view results)
- Use test Stripe account, test Ollama model
- Slow (1-5 minutes runtime)

---

### Running Tests

**Run All Tests**:
```bash
uv run pytest
```

**Run Specific Test File**:
```bash
uv run pytest tests/test_auth.py
```

**Run with Coverage**:
```bash
uv run pytest --cov=app --cov-report=html
open htmlcov/index.html  # View coverage report
```

**Run Only Fast Tests** (skip integration tests):
```bash
uv run pytest -m "not integration"
```

**Watch Mode** (re-run on file changes):
```bash
uv run pytest-watch
```

---

### Test Structure

**Example Unit Test**:
```python
# tests/unit/test_auth_service.py
import pytest
from app.services.auth_service import AuthService

def test_hash_password():
    """Test password hashing."""
    service = AuthService()
    hashed = service.hash_password("secret123")

    assert hashed != "secret123"  # Password is hashed
    assert service.verify_password("secret123", hashed)  # Verification works

def test_verify_password_fails_for_wrong_password():
    """Test password verification fails for wrong password."""
    service = AuthService()
    hashed = service.hash_password("secret123")

    assert not service.verify_password("wrong_password", hashed)
```

**Example Integration Test**:
```python
# tests/integration/test_query_api.py
import pytest
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_query_philosopher_endpoint(client: AsyncClient, auth_token: str):
    """Test /api/query endpoint with authenticated user."""
    response = await client.post(
        "/api/query",
        json={"query": "What is virtue?", "philosopher": "Aristotle"},
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert "sources" in data
    assert len(data["sources"]) > 0
```

---

### Test Fixtures

**Fixture: Test Database**:
```python
# tests/conftest.py
import pytest
from sqlmodel import create_engine, Session

@pytest.fixture
def test_db():
    """Provide test database session."""
    engine = create_engine("sqlite:///test.db")
    with Session(engine) as session:
        yield session
    # Teardown: Delete test database
    os.remove("test.db")
```

**Fixture: Authenticated User**:
```python
@pytest.fixture
async def auth_token(client: AsyncClient):
    """Provide JWT token for authenticated user."""
    # Register user
    await client.post("/auth/register", json={
        "email": "test@example.com",
        "password": "secret123"
    })

    # Login
    response = await client.post("/auth/login", json={
        "email": "test@example.com",
        "password": "secret123"
    })

    return response.json()["access_token"]
```

---

## Code Quality

### Linting & Formatting

**Tool**: Ruff (fast Python linter and formatter)

**Configuration** (`pyproject.toml`):
```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N"]  # Error, pyflakes, warnings, import order, naming
ignore = ["E501"]  # Ignore line length (handled by formatter)
```

**Run Linter**:
```bash
# Check for issues
uv run ruff check app/

# Auto-fix issues
uv run ruff check --fix app/

# Format code
uv run ruff format app/
```

**Pre-Commit Hook** (Optional):
```bash
# .git/hooks/pre-commit
#!/bin/bash
uv run ruff check app/ || exit 1
uv run pytest || exit 1
```

---

### Type Checking

**Tool**: Pyright (static type checker for Python)

**Configuration** (`pyproject.toml`):
```toml
[tool.pyright]
pythonVersion = "3.11"
typeCheckingMode = "basic"
reportMissingTypeStubs = false
```

**Run Type Checker**:
```bash
uv run pyright app/
```

**Example Type Hints**:
```python
from typing import Optional

def get_user(user_id: int) -> Optional[User]:
    """Get user by ID."""
    return db.query(User).filter(User.id == user_id).first()
```

---

## Documentation

### Code Documentation

**Docstrings**: Use Google-style docstrings

**Example**:
```python
def generate_paper(
    query: str,
    philosopher: str,
    format: str = "APA"
) -> str:
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
```

**When to Document**:
- All public API functions (endpoints)
- Complex business logic
- Non-obvious algorithms
- Database queries with CTEs or complex JOINs

**When NOT to Document**:
- Simple getters/setters
- Self-explanatory functions (`get_user_by_id`)

---

### API Documentation

**Auto-Generated**: FastAPI generates OpenAPI documentation

**Access**:
- Swagger UI: `http://localhost:8080/docs`
- ReDoc: `http://localhost:8080/redoc`

**Enhance with Examples**:
```python
from fastapi import FastAPI
from pydantic import BaseModel, Field

class QueryRequest(BaseModel):
    query: str = Field(..., example="What is virtue?")
    philosopher: str = Field(..., example="Aristotle")
    immersive_mode: bool = Field(True, example=True)

@app.post(
    "/api/query",
    summary="Query philosopher",
    description="Perform semantic query with philosopher-specific context",
    response_description="Generated response with sources"
)
async def query_philosopher(request: QueryRequest):
    pass
```

---

## Definition of Done

**When is a feature complete?**

**Checklist**:
- [ ] Code implemented and tested locally
- [ ] Unit tests added (80%+ coverage for new code)
- [ ] Integration test added (for API endpoints)
- [ ] Linter passes (`ruff check`)
- [ ] Type checker passes (`pyright`)
- [ ] Documentation updated (if public API changed)
- [ ] Database migration created and tested (if schema changed)
- [ ] Pull request created and self-reviewed
- [ ] Merged to `main` and deployed to production
- [ ] Smoke test in production (manual check)
- [ ] Metrics monitored for 24 hours (no errors, no performance degradation)

---

## Debugging

### Local Debugging

**Print Debugging**:
```python
print(f"User ID: {user.id}, Query: {query}")  # Simple, works
```

**Logging** (Preferred):
```python
import logging

logger = logging.getLogger(__name__)
logger.debug(f"User {user.id} querying {philosopher}")
```

**Debugger** (pdb):
```python
import pdb; pdb.set_trace()  # Breakpoint

# Step through code
# (n)ext, (s)tep into, (c)ontinue, (p)rint variable, (q)uit
```

**VS Code Debugger**:
```json
// .vscode/launch.json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: FastAPI",
      "type": "python",
      "request": "launch",
      "module": "uvicorn",
      "args": ["app.main:app", "--reload"],
      "jinja": true
    }
  ]
}
```

---

### Production Debugging

**View Logs**:
```bash
# SSH into server
ssh user@api.ontologic.com

# Real-time logs
journalctl -u ontologic-api -f

# Filter errors
journalctl -u ontologic-api -p err

# Search for specific user
journalctl -u ontologic-api | grep "user_id=123"
```

**Check Metrics**:
```bash
# Prometheus metrics
curl https://api.ontologic.com/metrics | grep http_request_duration
```

**Reproduce Locally**:
1. Copy production config (`prod.toml`)
2. Restore database backup to local PostgreSQL
3. Run application with production data
4. Step through with debugger

---

## Development Environment Setup

### Initial Setup

**Prerequisites**:
- Python 3.11+
- PostgreSQL 15+
- Qdrant (Docker or local install)
- Ollama (with qwen3:8b model)
- GPU (NVIDIA, 8GB+ VRAM for Ollama)

**Steps**:
```bash
# 1. Clone repository
git clone https://github.com/yourusername/ontologic-api.git
cd ontologic-api

# 2. Install dependencies
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv sync

# 3. Set up database
createdb ontologic_dev
uv run alembic upgrade head

# 4. Start Qdrant (Docker)
docker run -p 6333:6333 qdrant/qdrant

# 5. Start Ollama
ollama serve
ollama pull qwen3:8b

# 6. Run application
uv run uvicorn app.main:app --reload
```

**Verify Setup**:
```bash
# Health check
curl http://localhost:8080/health

# Test query
curl -X POST http://localhost:8080/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is virtue?", "philosopher": "Aristotle"}'
```

---

## Troubleshooting

### Common Issues

**Issue**: PostgreSQL connection refused

**Solution**:
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Verify connection string in app/config/dev.toml
[database]
url = "postgresql://localhost:5432/ontologic_dev"
```

---

**Issue**: Qdrant connection error

**Solution**:
```bash
# Check Qdrant container is running
docker ps | grep qdrant

# Restart Qdrant
docker restart qdrant
```

---

**Issue**: Ollama model not found

**Solution**:
```bash
# Pull qwen3:8b model
ollama pull qwen3:8b

# Verify model exists
ollama list
```

---

**Issue**: Tests fail with database errors

**Solution**:
```bash
# Create test database
createdb ontologic_test

# Update test config to use test database
# tests/conftest.py: use "postgresql://localhost:5432/ontologic_test"
```

---

## References

- GitHub Flow: https://docs.github.com/en/get-started/quickstart/github-flow
- Conventional Commits: https://www.conventionalcommits.org
- pytest Documentation: https://docs.pytest.org
- Ruff Linter: https://docs.astral.sh/ruff
- FastAPI Testing: https://fastapi.tiangolo.com/tutorial/testing
