# Deployment Strategy

**Last Updated**: 2025-11-12
**Project**: Ontologic API
**Deployment Model**: Direct Production (main branch → production)
**CI/CD Tool**: GitHub Actions
**Related Docs**: See `system-architecture.md` for infrastructure, `capacity-planning.md` for scaling

---

## Deployment Model

### Direct Production Deployment

**Current Model**: Direct production deployment without staging

**Why Direct Production**:
- Team size: Solo developer (no need for multi-environment complexity)
- Deployment frequency: 1-2× per week (low risk)
- Fast iteration: No staging validation gate (faster feature delivery)
- Budget: $50/month (cannot afford separate staging infrastructure)

**Trade-offs**:
- Higher risk: No staging validation before production
- Mitigation: Comprehensive local testing + health checks + rollback plan

**Future**: Add staging environment when team grows to 3+ developers or revenue hits $2,500 MRR

---

## Environments

### Development (Local)

**Purpose**: Local development and testing

**Infrastructure**:
- Developer machine (laptop/desktop)
- PostgreSQL (Docker container or local install)
- Qdrant (Docker container)
- Ollama (local install with GPU)

**Access**: Localhost only

**Configuration**:
```toml
# app/config/dev.toml
[database]
url = "postgresql://localhost:5432/ontologic_dev"

[ollama]
url = "http://localhost:11434"

[qdrant]
url = "http://localhost:6333"

[stripe]
secret_key = "sk_test_..."  # Test mode
webhook_secret = "whsec_test_..."
```

**Database**: Separate dev database (not shared with production)

---

### Production

**Purpose**: Live user-facing API

**Infrastructure**:
- 2× Dedicated servers (Hetzner AX41):
  - **Primary**: Main application server (8-core, 32GB RAM, GTX 1080)
  - **Backup (John's PC)**: Failover server (same specs)
- PostgreSQL (primary server)
- Qdrant (primary server)
- Ollama (primary server with GPU)
- systemd for process management

**Access**:
- API: `https://api.ontologic.com` (public)
- Metrics: `https://api.ontologic.com/metrics` (public, no auth yet - **SECURITY RISK**)
- SSH: IP whitelisted only (developer's static IP)

**Configuration**:
```toml
# app/config/prod.toml
[database]
url = "postgresql://prod_user:***@localhost:5432/ontologic_prod"

[ollama]
url = "http://localhost:11434"

[qdrant]
url = "http://localhost:6333"

[stripe]
secret_key = "sk_live_..."  # Live mode
webhook_secret = "whsec_live_..."
```

**Database**: Production PostgreSQL with daily backups

---

## CI/CD Pipeline

### GitHub Actions Workflow

**File**: `.github/workflows/deploy.yml`

**Trigger**: Push to `main` branch

**Workflow Steps**:
```yaml
name: Deploy Backend

on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Deploy backend to primary server
        uses: appleboy/ssh-action@v1.0.3
        continue-on-error: true
        with:
          host: ${{ secrets.SERVER_IP }}
          username: ${{ secrets.SERVER_USER }}
          key: ${{ secrets.SERVER_SSH_KEY }}
          script: |
            /opt/ontologic/deploy-backend.sh

      - name: Deploy backend to backup server (John's PC)
        uses: appleboy/ssh-action@v1.0.3
        continue-on-error: true
        with:
          host: ${{ secrets.SERVER_IP_JOHN }}
          username: ${{ secrets.SERVER_USER }}
          key: ${{ secrets.SERVER_SSH_KEY }}
          script: |
            /opt/ontologic/deploy-backend.sh
```

**Deployment Script** (`/opt/ontologic/deploy-backend.sh`):
```bash
#!/bin/bash
set -e

# 1. Pull latest code
cd /opt/ontologic/ontologic-api
git pull origin main

# 2. Install dependencies
uv sync

# 3. Run database migrations
uv run alembic upgrade head

# 4. Restart application (systemd)
sudo systemctl restart ontologic-api

# 5. Health check
sleep 5
curl -f http://localhost:8080/health || exit 1

echo "Deployment successful"
```

**Secrets** (GitHub Repository Settings → Secrets):
- `SERVER_IP`: Primary server IP address
- `SERVER_IP_JOHN`: Backup server IP address
- `SERVER_USER`: SSH username
- `SERVER_SSH_KEY`: Private SSH key for authentication

**Deployment Duration**: ~2 minutes (git pull + uv sync + alembic + restart)

---

## Deployment Process

### Step-by-Step Deployment

**1. Pre-Deployment Checks** (Local):
```bash
# Run tests
uv run pytest

# Check linting
uv run ruff check app/

# Test database migration (rollback after)
uv run alembic upgrade head
uv run alembic downgrade -1
```

**2. Create Pull Request** (GitHub):
- Branch: `feature/my-feature` → `main`
- PR description: Feature summary, testing notes
- Self-review: Code diff, check for secrets, verify tests pass

**3. Merge to Main**:
- GitHub Actions triggers automatically
- Monitors logs in GitHub Actions UI

**4. Post-Deployment Validation**:
```bash
# Health check
curl https://api.ontologic.com/health

# Test key endpoints
curl -X POST https://api.ontologic.com/api/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is virtue?", "philosopher": "Aristotle"}'

# Check error rate in Prometheus
# (Manual for now - no Grafana dashboard yet)
```

**5. Monitor**:
- Watch logs: `ssh server "journalctl -u ontologic-api -f"`
- Check metrics: `curl https://api.ontologic.com/metrics`
- Monitor Stripe webhooks (Stripe dashboard → Webhooks)

---

## Rollback Procedure

### Manual Rollback (If Deployment Fails)

**Scenario**: Deployment introduces critical bug (500 errors, database corruption)

**Steps**:
```bash
# 1. SSH into server
ssh user@api.ontologic.com

# 2. Rollback to previous commit
cd /opt/ontologic/ontologic-api
git log --oneline -5  # Identify last good commit
git reset --hard <previous-commit-sha>

# 3. Rollback database migration (if schema changed)
uv run alembic downgrade -1

# 4. Restart application
sudo systemctl restart ontologic-api

# 5. Verify health
curl http://localhost:8080/health
```

**Rollback Time**: <5 minutes

**Database Rollback Safety**:
- Always write reversible migrations (test `alembic downgrade -1` locally)
- For destructive changes (DROP COLUMN), add data migration step first
- Keep 30 days of database backups for worst-case recovery

---

## Database Migration Strategy

### Alembic Migrations

**Philosophy**: Schema changes are code, versioned in Git

**Migration Workflow**:
```bash
# 1. Make schema changes in app/core/models.py
# Example: Add new column to users table
class User(SQLModel, table=True):
    # ... existing fields
    phone_number: str | None = None  # New field

# 2. Generate migration
uv run alembic revision --autogenerate -m "add_phone_number_to_users"

# 3. Review generated migration (CRITICAL STEP)
vim alembic/versions/XXXX_add_phone_number_to_users.py
# Verify:
# - Column type correct
# - Nullable correct (phone_number is optional)
# - No unintended changes (autogenerate can be overzealous)

# 4. Test migration locally
uv run alembic upgrade head
# Test API endpoints affected by change
uv run alembic downgrade -1  # Test rollback
uv run alembic upgrade head  # Re-apply

# 5. Commit migration
git add alembic/versions/XXXX_add_phone_number_to_users.py
git commit -m "feat: add phone number to users"

# 6. Push to main (triggers deployment)
git push origin main
```

**Migration Naming**:
- Use lowercase with underscores: `add_phone_number_to_users`
- Prefix with action: `add_`, `remove_`, `rename_`, `create_table_`, `drop_table_`

**Migration Safety**:
- **Additive changes** (safe): Add column, add index, add table
- **Destructive changes** (risky): Drop column, drop table, change column type
- **For destructive changes**: Deploy in 2 phases:
  1. Phase 1: Make column nullable, deploy code that ignores column
  2. Phase 2: Drop column in next release

**Example (Safe Two-Phase Drop)**:
```python
# Phase 1: Mark as deprecated (release 1.1.0)
class User(SQLModel, table=True):
    old_field: str | None = None  # Make nullable, stop writing to it

# Phase 2: Drop column (release 1.2.0, 2 weeks later)
# alembic revision: op.drop_column('users', 'old_field')
```

---

## Zero-Downtime Deployment

### Current Strategy: Brief Downtime (<10 seconds)

**Process**:
1. systemd stops old process (graceful shutdown, drains connections)
2. Downtime: 5-10 seconds while new process starts
3. systemd starts new process
4. Health check passes

**Acceptable**: Solo developer, deployment during low-traffic hours (2-4am UTC)

### Future: Zero-Downtime with Rolling Restart

**When team/revenue justifies**:
- Use 2+ application servers behind load balancer
- Rolling restart: Update server 1, wait for health check, update server 2
- No user-facing downtime

**Cost**: +$80/month (second application server)
**Trigger**: When downtime complaints from users OR revenue >$2,500 MRR

---

## Environment Variables

### Secret Management

**Current**: Secrets in `app/config/prod.toml` on server (NOT in Git)

**Security**:
- File permissions: `chmod 600 prod.toml` (only ontologic user can read)
- Never commit secrets to Git (use `.gitignore`)
- Rotate secrets every 90 days

**Example `prod.toml`**:
```toml
[database]
url = "postgresql://prod_user:REDACTED@localhost:5432/ontologic_prod"

[jwt]
secret_key = "REDACTED_32_BYTE_RANDOM_STRING"

[stripe]
secret_key = "sk_live_REDACTED"
webhook_secret = "whsec_REDACTED"

[ollama]
url = "http://localhost:11434"

[qdrant]
url = "http://localhost:6333"
```

**Future**: Use environment variables or secret manager (AWS Secrets Manager, HashiCorp Vault)

---

## Health Checks

### Readiness Check

**Endpoint**: `GET /health/ready`

**Purpose**: Is application ready to serve traffic? (dependencies available)

**Checks**:
- PostgreSQL connection (SELECT 1)
- Qdrant connection (GET /collections)
- Ollama connection (GET /api/tags)

**Response** (All Healthy):
```json
{
  "status": "healthy",
  "checks": {
    "database": "healthy",
    "qdrant": "healthy",
    "ollama": "healthy"
  },
  "timestamp": "2025-11-12T10:00:00Z"
}
```

**Response** (Unhealthy):
```json
{
  "status": "unhealthy",
  "checks": {
    "database": "healthy",
    "qdrant": "unhealthy",
    "ollama": "healthy"
  },
  "errors": ["Qdrant connection failed: Connection refused"],
  "timestamp": "2025-11-12T10:00:00Z"
}
```

**HTTP Status**:
- 200 OK: All checks pass
- 503 Service Unavailable: Any check fails

**Used by**: systemd service health check, monitoring

---

### Liveness Check

**Endpoint**: `GET /health/live`

**Purpose**: Is application alive? (process running, not deadlocked)

**Response**:
```json
{
  "status": "alive",
  "timestamp": "2025-11-12T10:00:00Z"
}
```

**Always returns 200 OK** (unless process crashed)

---

## Monitoring & Alerting

### Application Monitoring

**Metrics Endpoint**: `GET /metrics` (Prometheus format)

**Key Metrics**:
- `http_requests_total{method, endpoint, status}` - Request count
- `http_request_duration_seconds` - Request latency histogram
- `llm_query_duration_seconds` - LLM query latency
- `cache_hit_rate` - Cache effectiveness
- `database_connections_active` - Connection pool usage

**Alerting Rules** (Future - Prometheus Alertmanager):
```yaml
groups:
  - name: ontologic_api_alerts
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        annotations:
          summary: "High 5xx error rate (>5%)"

      - alert: SlowAPIResponses
        expr: histogram_quantile(0.95, http_request_duration_seconds) > 2
        for: 10m
        annotations:
          summary: "API p95 latency >2s for 10 minutes"
```

**Current**: Manual monitoring (check `/metrics` endpoint, review logs)

---

### Logging Strategy

**Log Destination**: systemd journal (journalctl)

**Log Levels**:
- `ERROR`: Application errors (500 responses, exceptions)
- `WARNING`: Degraded state (slow queries, cache misses)
- `INFO`: Request logs, deployment events
- `DEBUG`: Development only (not in production)

**Structured Logging** (JSON):
```python
import logging

logger = logging.getLogger(__name__)
logger.info("User query", extra={
    "user_id": user.id,
    "philosopher": "Aristotle",
    "latency_ms": 2340,
    "cached": False
})
```

**Log Retention**: 30 days (journalctl default)

**View Logs**:
```bash
# Real-time logs
journalctl -u ontologic-api -f

# Last 100 lines
journalctl -u ontologic-api -n 100

# Errors only
journalctl -u ontologic-api -p err

# Filter by time
journalctl -u ontologic-api --since "1 hour ago"
```

---

## Disaster Recovery

### Backup Strategy

**PostgreSQL Backups**:
- Frequency: Daily at 3am UTC
- Retention: 30 days
- Storage: `/opt/backups/postgres/` + AWS S3 (offsite)
- Method: `pg_dump` with compression

**Backup Script** (`/opt/ontologic/backup-postgres.sh`):
```bash
#!/bin/bash
DATE=$(date +%Y%m%d)
BACKUP_FILE="/opt/backups/postgres/ontologic_${DATE}.dump"

pg_dump -h localhost -U postgres ontologic_prod \
    --format=custom --compress=9 \
    --file=$BACKUP_FILE

# Upload to S3 (future)
# aws s3 cp $BACKUP_FILE s3://ontologic-backups/postgres/

# Delete backups older than 30 days
find /opt/backups/postgres/ -name "*.dump" -mtime +30 -delete
```

**Restore from Backup**:
```bash
# 1. Stop application
sudo systemctl stop ontologic-api

# 2. Drop existing database
psql -h localhost -U postgres -c "DROP DATABASE ontologic_prod;"

# 3. Create new database
psql -h localhost -U postgres -c "CREATE DATABASE ontologic_prod;"

# 4. Restore from backup
pg_restore -h localhost -U postgres -d ontologic_prod \
    /opt/backups/postgres/ontologic_20251112.dump

# 5. Start application
sudo systemctl start ontologic-api
```

**Recovery Time Objective (RTO)**: <4 hours
**Recovery Point Objective (RPO)**: <24 hours

---

### Disaster Scenarios

**Scenario 1: Server Hardware Failure**

**Impact**: Full outage

**Recovery**:
1. Provision new server (Hetzner, 1-2 hours)
2. Install dependencies (Python, PostgreSQL, Qdrant, Ollama)
3. Restore database from latest backup
4. Deploy application code
5. Update DNS (if IP changed)

**RTO**: <4 hours

---

**Scenario 2: Database Corruption**

**Impact**: Data loss, 500 errors

**Recovery**:
1. Identify corruption source (check PostgreSQL logs)
2. Stop application (prevent further writes)
3. Restore from latest backup
4. Replay Write-Ahead Logs (WAL) if available
5. Restart application

**RTO**: <2 hours

---

**Scenario 3: Accidental Table Drop**

**Impact**: Data loss (e.g., `DROP TABLE users`)

**Recovery**:
1. Stop application immediately
2. Restore from latest backup (may lose last 24 hours)
3. Notify affected users of data loss
4. Implement safeguards (restrict DROP permissions)

**RTO**: <4 hours
**RPO**: <24 hours (last backup)

---

## Security Considerations

### Deployment Security

**SSH Access**:
- Public key authentication only (no password login)
- IP whitelist (only developer's static IP)
- Disable root login (`PermitRootLogin no`)

**Application Security**:
- Run as non-root user (`ontologic` user)
- File permissions: 640 for configs, 600 for secrets
- No secrets in Git (use `.gitignore`, verify with `git secrets`)

**Network Security**:
- Firewall (ufw): Only ports 22 (SSH), 80 (HTTP), 443 (HTTPS) open
- HTTPS only (TLS 1.3 minimum, Let's Encrypt certificate)
- No direct database access from internet (PostgreSQL bound to localhost)

**Secret Rotation**:
- JWT secret: Every 90 days
- Stripe webhook secret: On compromise
- SSH keys: Annually

---

## Future Improvements

**When team grows or revenue justifies**:

1. **Add Staging Environment** ($100/mo):
   - Separate server for staging deployments
   - Test migrations before production
   - Staging URL: `https://staging-api.ontologic.com`

2. **Zero-Downtime Deployment** (+$80/mo):
   - Load balancer + 2 application servers
   - Rolling restart (no user-facing downtime)

3. **Automated Testing in CI** (free):
   - Run pytest in GitHub Actions before deployment
   - Block merge if tests fail

4. **Blue-Green Deployment** (+$80/mo):
   - Two production environments (blue + green)
   - Switch traffic instantly (rollback in seconds)

5. **Secret Manager** ($10/mo):
   - AWS Secrets Manager or HashiCorp Vault
   - Rotate secrets automatically

6. **Monitoring Dashboard** (free - self-hosted Grafana):
   - Visualize Prometheus metrics
   - Pre-built dashboards for FastAPI

---

## References

- GitHub Actions Documentation: https://docs.github.com/actions
- Alembic Documentation: https://alembic.sqlalchemy.org
- systemd Service Management: https://www.freedesktop.org/software/systemd/man/systemd.service.html
- PostgreSQL Backup: https://www.postgresql.org/docs/current/backup.html
- Hetzner Dedicated Servers: https://www.hetzner.com/dedicated-rootserver
