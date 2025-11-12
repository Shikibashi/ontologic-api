# Project Overview

**Last Updated**: 2025-11-12
**Status**: Active

## Vision Statement

Ontologic API is a sophisticated backend API service for semantic knowledge retrieval from philosophical texts, combining vector search with large language model integration. We exist to make philosophical research and analysis accessible through modern AI technology, enabling researchers, students, and the general public to engage with philosophical knowledge in unprecedented ways. Our goal is to democratize access to philosophical wisdom through intelligent search, immersive philosopher conversations, and AI-powered academic paper generation.

---

## Target Users

### Primary Persona: Academic Researcher

**Who**: Graduate students, professors, and independent scholars conducting philosophical research with 2-10+ years experience in academic philosophy.

**Goals**:
- Quickly find relevant philosophical texts across multiple traditions
- Generate literature reviews and research papers with proper academic citations
- Engage in immersive conversations with historical philosophers (Aristotle, Plato, etc.)
- Upload and semantically search their own research documents

**Pain Points**:
- Manual literature review takes weeks of reading and note-taking
- Existing search tools lack semantic understanding of philosophical concepts
- No easy way to explore philosophical ideas through dialogue
- Academic paper writing is time-intensive and repetitive

### Secondary Persona: Philosophy Student

**Who**: Undergraduate and graduate students studying philosophy, typically 18-30 years old, working on essays, theses, or general learning.

**Goals**:
- Understand complex philosophical arguments quickly
- Find relevant quotes and citations for essays
- Practice philosophical reasoning through AI dialogue
- Learn from multiple philosophical traditions simultaneously

**Pain Points**:
- Dense philosophical texts are difficult to parse
- Limited time to read primary sources
- Need guidance on philosophical concepts
- Difficulty synthesizing ideas from multiple philosophers

### Tertiary Persona**: General Public / Curious Learner

**Who**: Educated individuals (college-educated) interested in philosophy, ethics, and critical thinking, ages 25-65.

**Goals**:
- Explore philosophical ideas for personal growth
- Understand ethical frameworks for decision-making
- Engage with classical wisdom in modern context
- Learn philosophy without formal academic training

**Pain Points**:
- Academic philosophy is inaccessible (jargon, dense prose)
- No structured learning path for self-study
- Existing AI chatbots lack philosophical depth
- Hard to find relevant philosophical texts on specific topics

---

## Core Value Proposition

**For** academic researchers, philosophy students, and curious learners
**Who** need fast, semantic access to philosophical knowledge and AI-powered research tools
**The** Ontologic API
**Is a** RESTful backend API service
**That** combines hybrid vector search (SPLADE + Dense embeddings) with LLM integration for semantic knowledge retrieval, immersive philosopher conversations, and academic paper generation
**Unlike** generic AI chatbots (ChatGPT, Claude) or traditional search engines
**Our product** specializes in philosophical texts with philosopher-specific immersive modes, proper academic citation, and hybrid vector search for precise semantic matching

---

## Success Metrics

**Business KPIs** (how we measure project success):

| Metric | Target | Timeframe | Measurement Source |
|--------|--------|-----------|-------------------|
| Monthly Active Users (MAU) | 1,000 | 6 months | `SELECT COUNT(DISTINCT user_id) FROM usage_records WHERE timestamp >= NOW() - INTERVAL '30 days'` |
| API Requests per Day | 10,000 | 6 months | Prometheus metrics (`sum(rate(http_requests_total[1d]))`) |
| Subscription Revenue (MRR) | $500 | 6 months | Stripe dashboard + `SELECT SUM(amount_cents) / 100 FROM payment_records WHERE status='succeeded' AND created_at >= NOW() - INTERVAL '30 days'` |
| User Retention (30-day) | >60% | 3 months | `SELECT COUNT(DISTINCT user_id) FROM usage_records WHERE timestamp >= NOW() - INTERVAL '60 days' AND user_id IN (SELECT user_id FROM usage_records WHERE timestamp >= NOW() - INTERVAL '30 days')` |
| Average Response Time (p95) | <2s | Ongoing | Prometheus (`histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))`) |

---

## Scope Boundaries

### In Scope (what we ARE building)

- Hybrid vector search (SPLADE + Dense embeddings) for philosophical texts
- Philosopher-specific immersive chat mode (Aristotle, Plato, etc.)
- PDF document upload with semantic search integration
- Chat history with conversation persistence (PostgreSQL)
- Academic paper generation with proper citations
- Review functionality (peer review, conference review formats)
- Payment system (Stripe) with subscription tiers (Free, Basic, Premium, Academic)
- RESTful API with JWT authentication
- Comprehensive observability (OpenTelemetry, Prometheus metrics)
- Health monitoring endpoints

### Out of Scope (what we are NOT building)

- **Frontend application** - **Why**: API-only service, clients consume via REST
- **Mobile apps** - **Why**: Focus on API first, mobile apps can be third-party clients
- **Real-time collaborative editing** - **Why**: Out of MVP scope, defer to v2.0
- **Video/audio analysis** - **Why**: Text-only for MVP, multimedia analysis is complex
- **Social features (sharing, comments)** - **Why**: Academic focus, not a social platform
- **Multi-language support (beyond English)** - **Why**: Philosophical texts primarily in English (translations), defer to v2.0

---

## Competitive Landscape

### Direct Competitors

| Product | Strengths | Weaknesses | Price | Market Position |
|---------|-----------|------------|-------|----------------|
| ChatGPT (OpenAI) | General-purpose, excellent UX, large user base | Not specialized in philosophy, no citations, generic responses | $20/mo (Plus) | Market leader, 100M+ users |
| Claude (Anthropic) | Long context window, good at reasoning | Not specialized, no philosopher modes, no vector search | $20/mo (Pro) | Growing, 10M+ users |
| Perplexity AI | Real-time web search, citations | No philosophical specialization, no immersive modes | $20/mo (Pro) | Niche, 5M+ users |
| Google Scholar | Comprehensive academic search | No semantic search, no AI dialogue, citation-only | Free | Academic standard |

### Our Positioning

**Positioning Statement**: "Ontologic API targets philosophy researchers, students, and learners who need specialized philosophical knowledge retrieval with proper academic rigor. We're the only API that combines hybrid vector search with philosopher-specific immersive dialogue modes and academic citation generation."

**Competitive Advantages**:
1. **Specialization**: Philosophy-specific (not general-purpose AI), deep domain focus
2. **Hybrid Search**: SPLADE + Dense embeddings (better semantic matching than keyword search)
3. **Immersive Modes**: Philosopher-specific dialogue (Aristotle, Plato) with historically accurate responses
4. **Academic Rigor**: Proper citations, peer review formats, research paper generation
5. **API-first**: Developers can build custom UIs, integrations, workflows

---

## Project Timeline

**Phases**:

| Phase | Milestone | Target Date | Status |
|-------|-----------|-------------|--------|
| Phase 0 | Project design complete | 2025-11-12 | In progress |
| Phase 1 | MVP operational (hybrid search + chat) | 2025-09-01 | Complete |
| Phase 2 | Payment system integrated | 2025-10-01 | Complete |
| Phase 3 | Academic features (paper generation, reviews) | 2025-10-15 | Complete |
| Phase 4 | Scale to 1K users, observability + optimization | 2025-12-31 | In progress |

---

## Assumptions

**Critical assumptions** (if wrong, project strategy changes):

1. **Philosophy researchers will pay $10-50/mo for specialized tools** - **Validation**: Landing page conversion rate >3%, user interviews
2. **Hybrid vector search provides better results than keyword search** - **Validation**: A/B testing (ongoing), user satisfaction surveys
3. **Medium scale (1K-10K users) is achievable with current architecture** - **Validation**: Load testing, capacity planning
4. **PostgreSQL + Qdrant can handle 10K daily queries with <2s latency** - **Validation**: Performance benchmarks (p95 < 2s achieved)

---

## Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Ollama LLM slow response times (>10s) | High | Medium | Cache embeddings, optimize prompts, consider cloud LLM fallback (OpenAI GPT-4) |
| Qdrant vector DB scaling bottleneck | High | Low | Horizontal scaling plan documented, test at 100K documents |
| Stripe payment integration failures | Medium | Low | Comprehensive webhook testing, retry logic, manual invoicing fallback |
| Low user adoption (< 100 MAU) | High | Medium | Marketing via academic channels (Twitter, Reddit r/philosophy), free tier generous |
| PostgreSQL connection exhaustion | Medium | Medium | Connection pooling (PgBouncer), read replicas plan documented |
| GDPR compliance for EU users | Medium | Low | Data retention policies documented, user data export endpoint exists |

---

## Team & Stakeholders

**Current Team**:
- Engineering: Solo developer - Full-stack development (Python FastAPI, PostgreSQL, Qdrant), DevOps, product decisions
- Domain Advisor (TBD): Philosophy professor or researcher - Academic validation, philosopher accuracy, citation standards

**As Team Grows** (future):
- Frontend Engineer - Build web UI for API
- DevOps Engineer - Scale infrastructure, monitoring, CI/CD
- Philosophy Content Specialist - Curate philosophical texts, validate AI responses
- Product Manager - User research, roadmap prioritization

**Stakeholders**:
- Beta users (target: 50 researchers/students): Feature feedback, bug reports, academic validation
- Philosophy departments: Potential institutional customers, academic credibility

---

## Change Log

| Date | Change | Reason |
|------|--------|--------|
| 2025-11-12 | Initial project overview created | /init-project phase |
| 2025-10-01 | Added payment system (Stripe) | Monetization strategy |
| 2025-09-15 | Launched MVP with hybrid search + chat | Core functionality complete |
