# Capacity Planning

**Last Updated**: 2025-11-12
**Project**: Ontologic API
**Current Scale Tier**: Medium (1K-10K users)
**Budget**: $50/month
**Related Docs**: See `system-architecture.md` for architecture, `deployment-strategy.md` for infrastructure

---

## Scale Tiers

**Philosophy**: Plan for 10x growth at each tier, with clear cost and performance models

### Tier 0: Micro (100 users)

**User Characteristics**:
- 100 monthly active users
- 1,000 API requests/day (10 req/user/day average)
- 50 concurrent users (peak)
- 1GB database size

**Infrastructure**:
- Single server (4 CPU, 16GB RAM)
- PostgreSQL (single instance, 10 connections)
- Qdrant (single instance, 100K vectors)
- Ollama (single GPU, qwen3:8b model)

**Performance Targets**:
- API p95 latency: <500ms
- LLM query p95 latency: <5s
- Database query p95: <50ms
- Uptime: 99% (7 hours downtime/month acceptable)

**Costs**:
- Server: $20/month (Hetzner CX31, 4 vCPU, 8GB RAM)
- Storage: $5/month (80GB SSD)
- Bandwidth: $0 (included in server)
- **Total**: $25/month

**Breaking Points**:
- Database connections exhausted (>50 concurrent queries)
- Ollama GPU memory exhausted (>10 concurrent LLM queries)
- Single server failure = full outage

---

### Tier 1: Small (1,000 users) [CURRENT TARGET]

**User Characteristics**:
- 1,000 monthly active users
- 10,000 API requests/day (10 req/user/day average)
- 100 concurrent users (peak)
- 4GB database size

**Infrastructure**:
- Single server (8 CPU, 32GB RAM, NVIDIA GPU)
- PostgreSQL (single instance, 50 connections, asyncpg pool)
- Qdrant (single instance, 1M vectors)
- Ollama (single GPU, qwen3:8b model, 8GB VRAM)
- In-memory cache (embeddings, 60% hit rate)

**Performance Targets**:
- API p95 latency: <500ms
- LLM query p95 latency: <3s
- Database query p95: <50ms
- Cache hit rate: >60%
- Uptime: 99.5% (3.6 hours downtime/month)

**Costs**:
- Dedicated server: $80/month (Hetzner AX41, 8-core, 32GB RAM, GTX 1080)
- PostgreSQL: $0 (self-hosted)
- Qdrant: $0 (self-hosted)
- Ollama: $0 (self-hosted with included GPU)
- Stripe fees: $20/month (assuming $500 MRR × 4% = $20)
- **Total**: $100/month

**Current Budget**: $50/month
**Gap**: -$50/month (need to optimize or increase revenue to $500 MRR)

**Breaking Points**:
- Database writes >500/sec (PostgreSQL single instance limit)
- Ollama GPU memory exhausted (>20 concurrent LLM queries)
- Qdrant vector count >5M (memory exhaustion on 32GB RAM)
- Single server failure = full outage

---

### Tier 2: Medium (10,000 users) [PLANNED]

**User Characteristics**:
- 10,000 monthly active users
- 100,000 API requests/day (10 req/user/day average)
- 500 concurrent users (peak)
- 20GB database size

**Infrastructure**:
- 2× Application servers (8 CPU, 32GB RAM each)
- PostgreSQL primary + 1 read replica (connection pooling with PgBouncer)
- Qdrant cluster (2 nodes, 10M vectors)
- Ollama cluster (2× GPUs for load balancing)
- Redis (distributed cache, replaces in-memory)
- Load balancer (Nginx or cloud LB)

**Performance Targets**:
- API p95 latency: <500ms
- LLM query p95 latency: <2s
- Database query p95: <50ms
- Cache hit rate: >70% (Redis)
- Uptime: 99.9% (43 minutes downtime/month)

**Costs**:
- Application servers (2×): $160/month
- PostgreSQL primary: $40/month
- PostgreSQL read replica: $40/month
- Qdrant cluster (2 nodes): $80/month
- Redis: $20/month
- Load balancer: $10/month
- Stripe fees: $100/month (assuming $2,500 MRR × 4%)
- **Total**: $450/month

**Revenue Target**: $2,500 MRR (to cover costs + 20% margin)

**Breaking Points**:
- Database writes >2,000/sec (need sharding)
- Ollama GPU cluster saturated (>50 concurrent queries)
- Qdrant memory exhaustion (>50M vectors)

---

### Tier 3: Large (100,000 users)

**User Characteristics**:
- 100,000 monthly active users
- 1,000,000 API requests/day
- 2,000 concurrent users (peak)
- 100GB database size

**Infrastructure**:
- 10× Application servers (Kubernetes cluster)
- PostgreSQL cluster (1 primary + 3 read replicas, sharded by user_id)
- Qdrant cluster (5 nodes, 100M vectors)
- Ollama cluster (10× GPUs, auto-scaling)
- Redis cluster (3 nodes, distributed cache)
- CDN (Cloudflare or AWS CloudFront)
- Load balancer (AWS ALB or Kubernetes Ingress)

**Performance Targets**:
- API p95 latency: <300ms
- LLM query p95 latency: <2s
- Database query p95: <50ms
- Cache hit rate: >80%
- Uptime: 99.95% (22 minutes downtime/month)

**Costs**:
- Kubernetes cluster: $2,000/month
- PostgreSQL cluster: $500/month
- Qdrant cluster: $800/month
- Ollama GPU cluster: $1,500/month
- Redis cluster: $200/month
- CDN: $100/month
- Monitoring (Datadog/New Relic): $300/month
- Stripe fees: $1,000/month (assuming $25K MRR × 4%)
- **Total**: $6,400/month

**Revenue Target**: $25,000 MRR (to cover costs + 20% margin)

---

## Cost Model

### Current Tier (Small - 1K Users)

**Monthly Costs**:

| Category | Item | Monthly Cost | Notes |
|----------|------|--------------|-------|
| Compute | Dedicated server (Hetzner AX41) | $80 | 8-core, 32GB RAM, GTX 1080 |
| Database | PostgreSQL (self-hosted) | $0 | Included in server |
| Vector DB | Qdrant (self-hosted) | $0 | Included in server |
| LLM | Ollama (self-hosted) | $0 | Included with GPU |
| Payments | Stripe fees (4% of $500 MRR) | $20 | $500 MRR assumption |
| **Total** | | **$100/month** | |

**Current Budget**: $50/month
**Budget Gap**: -$50/month

**Cost Optimization Options**:
1. **Reduce server specs**: Downgrade to Hetzner CX51 (4 vCPU, 16GB RAM, $40/mo) - **Risk**: Performance degradation
2. **Use cloud LLM for premium users**: Keep Ollama for FREE/BASIC, use OpenAI GPT-4 for PREMIUM (charge $30/mo instead of $20/mo) - **Benefit**: Better quality for premium users
3. **Increase revenue**: Focus on user acquisition to reach $500 MRR

**Recommended**: Option 3 (increase revenue) to avoid technical debt

---

### Cost Breakdown by Component

**Compute Costs**:
- **Application servers**: Scale linearly (1 server per 1,000 users)
- **GPU for LLM**: Scale linearly (1 GPU per 10 concurrent queries)
- **Cost per user**: $0.08/month at 1K users, $0.045/month at 10K users (economies of scale)

**Database Costs**:
- **PostgreSQL storage**: $0.10/GB/month (SSD)
- **Connection pooling**: Free (PgBouncer), reduces connection overhead by 80%
- **Read replicas**: $40/month per replica (needed at 10K+ users)

**Vector Database Costs**:
- **Qdrant**: $0 (self-hosted), $0.08/GB/month for storage
- **Vectors**: 1M vectors = ~3GB (768-dim embeddings × 4 bytes × 1M)
- **Cost per million vectors**: $0.24/month

**LLM Costs**:
- **Ollama (self-hosted)**: $0 per query (GPU amortized in server cost)
- **OpenAI GPT-4 (cloud)**: $0.03 per query (if used as fallback)
- **Trade-off**: Self-hosted = lower cost, slower response; Cloud = higher cost, faster response

---

## Performance Budgets

### Response Time Budgets

**Total API Response Time**: <500ms (p95)

**Breakdown**:
- Network latency: 50ms (client ↔ server)
- Authentication (JWT decode): 5ms
- Database query (user lookup): 10ms
- LLM embedding generation: 100ms (cached: 5ms)
- Qdrant vector search: 30ms
- LLM response generation: 2,000ms (streamed)
- Response serialization: 5ms

**Total**: 2,200ms (p95 for LLM queries)

**Optimization Strategies**:
- Cache embeddings (60% hit rate → avg 100ms × 0.4 + 5ms × 0.6 = 43ms)
- Use streaming (SSE) to deliver chunks before full response completes
- Preload frequently-queried philosophers (Aristotle, Plato) into Qdrant memory

---

### Database Performance

**Query Targets**:

| Query Type | Target Latency (p95) | Current Latency | Optimization |
|------------|---------------------|-----------------|--------------|
| User lookup by ID | <10ms | 5ms | Index on id (primary key) |
| Chat conversations by user | <20ms | 12ms | Composite index (user_id, updated_at) |
| Payment records by user | <30ms | 18ms | Index on (user_id, created_at) |
| Usage aggregation (quota check) | <50ms | 35ms | Index on (user_id, billing_period) |

**Connection Pool Settings**:
- **Min connections**: 5
- **Max connections**: 50
- **Idle timeout**: 10 minutes
- **Max lifetime**: 1 hour

**Query Optimization**:
- Use `EXPLAIN ANALYZE` for slow queries (>100ms)
- Add indexes for all foreign keys
- Use JSONB indexes for metadata queries (`CREATE INDEX ON chat_conversations USING gin (metadata)`)

---

### Vector Search Performance

**Qdrant Targets**:

| Operation | Target Latency (p95) | Current Latency | Notes |
|-----------|---------------------|-----------------|-------|
| Hybrid search (10K vectors) | <30ms | 25ms | In-memory index |
| Hybrid search (1M vectors) | <50ms | 45ms | In-memory index |
| Upload point (single) | <10ms | 8ms | Batching recommended |
| Upload points (batch 100) | <100ms | 85ms | Preferred method |

**Configuration**:
```yaml
# qdrant/config.yaml
storage:
  in_memory: true  # Keep index in memory for <10M vectors
  wal_capacity_mb: 512

hnsw_config:
  m: 16  # Number of edges per node
  ef_construct: 200  # Construction search quality
```

---

### LLM Performance

**Ollama Targets**:

| Operation | Target Latency (p95) | Current Latency | Notes |
|-----------|---------------------|-----------------|-------|
| Embedding generation (512 tokens) | <100ms | 80ms | Cached 60% of time |
| Text generation (first token) | <500ms | 350ms | Time to first byte |
| Text generation (full 2K response) | <3s | 2.3s | Streamed to client |

**GPU Utilization**:
- Target: 60-80% average utilization (room for spikes)
- Current: 45% average (qwen3:8b model, 8GB VRAM)
- Max concurrent queries: 20 (with queueing)

**Optimization**:
- Use smaller context window (2K tokens instead of 4K) for faster generation
- Implement request queueing (max 5 concurrent, queue rest)
- Cache common queries ("What is virtue?", "Explain Plato's forms")

---

## Scaling Triggers

**When to scale to next tier**:

| Metric | Small → Medium Trigger | Medium → Large Trigger |
|--------|----------------------|----------------------|
| Monthly Active Users | >5,000 users (50% of capacity) | >50,000 users |
| API Requests/Day | >50,000 (50% of capacity) | >500,000 |
| Database Size | >10GB (50% of capacity) | >50GB |
| API p95 Latency | >700ms (40% above target) | >400ms |
| Error Rate | >2% (2x target) | >2% |
| Revenue | $2,500 MRR (to fund upgrade) | $25,000 MRR |

**Early Warning Signs**:
- Database connection pool exhausted (>80% utilization for 10 minutes)
- Ollama GPU memory >90% for 5 minutes
- Qdrant query latency >80ms (p95) for 10 minutes
- API error rate >1.5% for 5 minutes

**Monitoring Alerts**:
- Slack/PagerDuty notification when trigger thresholds reached
- Weekly capacity report (current utilization vs tier capacity)

---

## Disaster Recovery

### Backup Strategy

**PostgreSQL Backups**:
- Frequency: Daily full backup at 3am UTC
- Retention: 30 days
- Storage: Dedicated backup server + cloud storage (AWS S3 or equivalent)
- Recovery Time Objective (RTO): <4 hours
- Recovery Point Objective (RPO): <24 hours

**Qdrant Backups**:
- Frequency: Weekly full snapshot
- Retention: 4 weeks
- Storage: Cloud storage (vectors are reproducible from documents)
- RTO: <8 hours (re-generate embeddings if needed)
- RPO: <7 days

**Disaster Scenarios**:

| Scenario | Impact | Recovery Plan | RTO |
|----------|--------|--------------|-----|
| Server hardware failure | Full outage | Provision new server, restore from backup | <4 hours |
| Database corruption | Data loss | Restore from latest backup, replay WAL logs | <2 hours |
| Qdrant data loss | Vector search unavailable | Restore from snapshot or re-generate embeddings | <8 hours |
| Ollama model corruption | LLM queries fail | Re-download qwen3:8b model (5GB) | <1 hour |

---

## Cost Projections

### 3-Year Growth Projection

**Assumptions**:
- 100% year-over-year user growth
- 60% gross margin (after infrastructure costs)
- Conversion rate: 10% FREE → BASIC, 5% BASIC → PREMIUM

**Year 1** (1,000 users):
- Revenue: $6,000/year ($500 MRR)
- Infrastructure: $1,200/year ($100/month)
- Gross profit: $4,800/year (80% margin)

**Year 2** (10,000 users):
- Revenue: $30,000/year ($2,500 MRR)
- Infrastructure: $5,400/year ($450/month)
- Gross profit: $24,600/year (82% margin)

**Year 3** (100,000 users):
- Revenue: $300,000/year ($25,000 MRR)
- Infrastructure: $76,800/year ($6,400/month)
- Gross profit: $223,200/year (74% margin)

**Break-Even Analysis**:
- Fixed costs: $100/month (current infrastructure)
- Variable cost per user: $0.08/month
- Average revenue per user (ARPU): $0.50/month (assuming 10% paid conversion)
- Break-even: 240 users (fixed costs / [ARPU - variable cost])

---

## Capacity Planning Checklist

**Monthly Review**:
- [ ] Check current user count vs tier capacity (trigger: >50%)
- [ ] Review API p95 latency (trigger: >700ms)
- [ ] Review error rate (trigger: >2%)
- [ ] Review database size (trigger: >10GB for small tier)
- [ ] Review Qdrant vector count (trigger: >5M for small tier)
- [ ] Review GPU utilization (trigger: >80% average)
- [ ] Verify backup success (PostgreSQL + Qdrant)
- [ ] Calculate monthly costs vs budget
- [ ] Project next 3 months growth

**Quarterly Review**:
- [ ] Update cost model with actual spend
- [ ] Revise performance targets based on SLA
- [ ] Plan infrastructure upgrades (if needed)
- [ ] Review disaster recovery plan
- [ ] Load testing (simulate 2x current traffic)

---

## References

- Hetzner Pricing: https://www.hetzner.com/dedicated-rootserver
- PostgreSQL Performance Tuning: https://wiki.postgresql.org/wiki/Performance_Optimization
- Qdrant Scaling Guide: https://qdrant.tech/documentation/guides/scaling/
- Ollama Performance: https://github.com/ollama/ollama#performance
