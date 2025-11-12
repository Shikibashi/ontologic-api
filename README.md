# Ontologic API

A sophisticated backend API service for semantic knowledge retrieval from philosophical texts, combining vector search with large language model integration.

## 🚀 Features

- **Hybrid Vector Search**: SPLADE + Dense embeddings for precise semantic search
- **PDF Context Integration**: Upload and query your own documents with AI
- **Philosopher-Specific Queries**: Immersive mode conversations with historical thinkers
- **Chat History**: Persistent conversation tracking with vector search
- **Academic Paper Generation**: AI-powered research papers with proper citations
- **Review Functionality**: Multiple academic review formats (peer review, conference, etc.)
- **Payment System**: Complete Stripe integration for subscription management
- **Comprehensive Health Monitoring**: Full system observability and diagnostics

## 📁 Project Structure

```
ontologic-api/
├── app/                    # Main application code
│   ├── core/              # Core functionality and models
│   ├── router/            # API route definitions
│   ├── services/          # Business logic services
│   └── config/            # Configuration files
├── tests/                  # Test suite
│   ├── integration/       # API endpoint integration tests
│   ├── unit/              # Unit tests for components
│   └── performance/       # Performance and load tests
├── docs/                   # Documentation
│   ├── api/               # API documentation
│   └── testing/           # Testing documentation
├── reports/                # Test results and analysis
│   └── endpoint-testing/  # Endpoint test reports
├── logs/                   # Application logs
│   └── archive/           # Archived log files
├── scripts/                # Utility scripts
└── README.md              # This file
```

See [DIRECTORY_STRUCTURE.md](DIRECTORY_STRUCTURE.md) for detailed organization.

## 🧪 Testing

The project includes comprehensive test coverage with 100% endpoint success rate:

### Quick Test Commands
```bash
# Run all tests
python tests/run_tests.py all

# Run integration tests only
python tests/run_tests.py integration

# Run authentication tests
python tests/run_tests.py auth

# Run comprehensive endpoint tests
python tests/run_tests.py comprehensive
```

### Test Categories
- **Integration Tests**: Complete API endpoint testing (60 endpoints)
- **Authentication Tests**: JWT and OAuth functionality
- **Streaming Tests**: Real-time response streaming
- **Performance Tests**: Response time and load testing

### Test Results
- ✅ **100% Success Rate** achieved
- ✅ All 60 endpoints working correctly
- ✅ Streaming responses functional
- ✅ Authentication system operational

See `docs/testing/` for detailed test reports and `reports/endpoint-testing/` for JSON results.

## 📚 API Documentation

### OpenAPI Schema Generation

The project automatically generates OpenAPI specifications from the running FastAPI application:

```bash
# Start the server
uv run app/main.py

# In another terminal, generate the schema
python3 scripts/generate_api_docs.py
```

This creates `docs/openapi_schema.json` (generated file) with the current API specification.

### Schema Drift Detection

To ensure the committed `openapi_spec.json` (committed spec) stays in sync with the actual API:

```bash
# Check for drift (useful in CI)
./scripts/check_openapi_drift.sh
```

This script:
1. Generates a fresh schema from the running app → `docs/openapi_schema.json`
2. Compares it with the committed spec → `openapi_spec.json`
3. Exits with error if differences are detected

**File Naming Convention**:
- **Generated file**: `docs/openapi_schema.json` (auto-generated, not committed)
- **Committed spec**: `openapi_spec.json` (version-controlled source of truth)

**CI Integration**: Add this to your CI pipeline to catch API changes that aren't reflected in documentation:

```yaml
# Example GitHub Actions workflow
- name: Check OpenAPI drift
  run: |
    python3 scripts/generate_api_docs.py  # Generates docs/openapi_schema.json
    ./scripts/check_openapi_drift.sh      # Compares with openapi_spec.json
```

If drift is detected, update the committed spec:
```bash
cp docs/openapi_schema.json openapi_spec.json
git add openapi_spec.json
git commit -m "Update OpenAPI spec"
```

## 💳 Payment System

Ontologic API includes a complete Stripe integration for subscription management:

- 🔐 Secure payment processing with Stripe
- 📊 Multiple subscription tiers (Free, Basic, Premium, Academic)
- 💳 Automated billing and invoicing
- 🔄 Refund and dispute management
- 📈 Usage tracking and quota enforcement
- 🪝 Webhook handling for real-time payment events

**Quick Start**: See [Payment Setup Guide](docs/PAYMENT_SETUP.md) for detailed instructions.

```bash
# Enable payments
cp .env.example .env
# Add your Stripe test keys to .env
./scripts/start_with_payments.sh
```

## 🏃 Quick Start

### Prerequisites
- Python 3.9+
- Ollama with qwen3:8b model
- Qdrant vector database
- PostgreSQL (for chat history)

### Installation

1. **Install dependencies**:
```bash
uv sync
```
This installs all required packages including Stripe SDK for payment processing.

2. **Configure environment**:
```bash
cp .env.example .env
# Edit .env with your configuration (see .env.example for all options)
```

3. **Run the server**:
```bash
uv run app/main.py --env dev --host 0.0.0.0 --port 8080
```

4. **Access the API**:
- API Documentation: `http://localhost:8080/docs`
- Health Check: `http://localhost:8080/health`
- Interactive API: `http://localhost:8080/docs`

## 🔒 Security

### Production Deployment Requirements

**CRITICAL**: Before deploying to production, you MUST configure secure secrets:

```bash
# Generate secure secrets (32+ characters)
export APP_JWT_SECRET=$(openssl rand -hex 32)
export APP_SESSION_SECRET=$(openssl rand -hex 32)

# Configure Stripe (if payments enabled)
export APP_STRIPE_SECRET_KEY="sk_live_..."
export APP_STRIPE_WEBHOOK_SECRET="whsec_..."

# Restrict CORS to your domains
export APP_CORS_ORIGINS="https://yourdomain.com,https://app.yourdomain.com"
```

**Startup Validation**: The application will automatically validate security configuration on startup. If validation fails in production mode, the `/health/ready` endpoint will return 503 and log detailed error messages.

### Security Features

- ✅ JWT-based authentication with configurable lifetime
- ✅ Stripe webhook signature verification
- ✅ Rate limiting per IP and subscription tier
- ✅ Session-based chat history isolation
- ✅ Document upload authentication and ownership verification
- ✅ Security headers (X-Frame-Options, CSP, etc.)
- ✅ CORS origin restrictions
- ✅ Comprehensive audit logging

See [docs/SECURITY.md](docs/SECURITY.md) for complete security documentation.

## 🔧 Configuration

### Configuration Sources

Ontologic API settings come from multiple providers in the following priority order (highest first):

1. Direct arguments passed when instantiating `Settings`
2. Environment variables prefixed with `APP_`
3. TOML configuration files (`app/config/dev.toml`, `app/config/prod.toml`)
4. Defaults defined in `app/config/settings.py`

### Environment Files
- `app/config/dev.toml` - Development settings
- `app/config/prod.toml` - Production settings
- `docs/examples/dev.toml.example` - Example configuration

### Key Settings

**Security (REQUIRED for production):**
- `APP_JWT_SECRET` - JWT signing secret (32+ chars, MUST be changed from default)
- `APP_SESSION_SECRET` - Session secret (32+ chars)
- `APP_CORS_ORIGINS` - Comma-separated list of allowed CORS origins

**LLM & Vector Database:**
- `APP_LLM_MODEL` - Ollama model name (default: qwen3:8b)
- `APP_QDRANT_URL` - Qdrant connection URL
- `APP_LLM_REQUEST_TIMEOUT` - LLM request timeout in seconds (default: 300)

**Features:**
- `APP_CHAT_HISTORY` - Enable chat history (default: true)
- `APP_CHAT_USE_PDF_CONTEXT` - Enable PDF context in chat (default: false)
- `APP_DOCUMENT_UPLOADS_ENABLED` - Enable document uploads (default: true)
- `APP_PAYMENTS_ENABLED` - Enable Stripe payments (default: false)

**Observability:**
- `OTEL_ENABLED` - Enable OpenTelemetry tracing (default: true)
- `OTEL_EXPORTER_OTLP_ENDPOINT` - OTLP collector endpoint

### Response Compression

Ontologic API uses GZip compression to reduce bandwidth usage and improve response times for large JSON payloads. Compression is enabled by default and automatically applied to responses larger than 1KB.

**Configuration:**

```bash
# Enable/disable compression (default: true)
export APP_COMPRESSION_ENABLED=true

# Set minimum response size for compression in bytes (default: 1000)
export APP_COMPRESSION_MINIMUM_SIZE=1000
```

**TOML Configuration:**

```toml
[compression]
enabled = true
minimum_size = 1000  # Minimum response size in bytes (1KB)
```

**How It Works:**
- Responses smaller than `minimum_size` are sent uncompressed (overhead not worth it)
- Responses larger than `minimum_size` are automatically compressed with GZip
- Compression is only applied when the client supports it (checks `Accept-Encoding` header)
- Typical compression ratios: 60-80% reduction for JSON responses

**Performance Impact:**
- **Bandwidth savings**: 60-80% reduction for large JSON responses
- **CPU overhead**: Minimal (~1-5ms for typical responses)
- **Best for**: API responses > 1KB, especially text/JSON data
- **Not recommended for**: Already-compressed data (images, videos, pre-compressed files)

**When to Disable:**
- Behind a reverse proxy (nginx, Cloudflare) that handles compression
- Debugging response payloads (easier to read uncompressed)
- Very low-latency requirements where CPU overhead matters
- Serving primarily small responses (< 1KB)

**Example:**

```bash
# Disable compression for local development
export APP_COMPRESSION_ENABLED=false
python app/main.py --env dev

# Increase threshold for production (only compress responses > 5KB)
export APP_COMPRESSION_MINIMUM_SIZE=5000
python app/main.py --env prod
```

**Verification:**

Check if compression is working:

```bash
# Request with compression support
curl -H "Accept-Encoding: gzip" http://localhost:8080/api/philosophers -v

# Look for "Content-Encoding: gzip" in response headers
# Compare Content-Length with uncompressed size
```

### Clearing Development Environment Variables

If you previously exported `APP_*` variables for local testing, they will continue to override TOML values:

```bash
# Review currently exported variables
env | grep '^APP_'

# Remove them from your current shell session
unset APP_QDRANT_URL APP_CHAT_USE_PDF_CONTEXT APP_PDF_CONTEXT_LIMIT \
      APP_DOCUMENT_UPLOADS_ENABLED APP_LLM_MODEL

# Or clear every APP_* variable at once
for var in $(env | awk -F= '/^APP_/ {print $1}'); do unset "$var"; done
```

## 📚 Documentation

- **API Reference**: `/docs` (Swagger UI) when server is running
- **System Health**: `/health` endpoint for monitoring
- **Examples**: `docs/examples/` directory
- **Reports**: `docs/reports/` for system analysis and test results
- **Architecture**: See `docs/` for detailed documentation

## 🧪 Testing

```bash
# Run all tests
pytest

# Run specific test categories
pytest tests/unit/
pytest tests/integration/

# Development test scripts available in temp/test-files/
```

## 🚀 Production Deployment

1. **Set environment variables**:
```bash
export QDRANT_API_KEY=your_api_key
export SESSION_SECRET=your_secret_key
```

2. **Use production config**:
```bash
python app/main.py --env prod --host 0.0.0.0 --port 8080
```

3. **Monitor health**:
- Health endpoint: `/health`
- Ready probe: `/health/ready`
- Live probe: `/health/live`

## 📈 Metrics & Monitoring

### Prometheus Metrics

Ontologic API exposes comprehensive Prometheus-compatible metrics at `/metrics` endpoint for monitoring and observability.

**Standard HTTP Metrics:**
- Request/response duration histograms
- HTTP status code counters
- In-progress request gauges
- Request rate and latency percentiles

**Custom Application Metrics:**

**LLM Metrics:**
- `llm_query_duration_seconds` - Histogram of LLM query latency by model and operation type
- `llm_query_total` - Counter of total LLM queries by model, operation, and status
- `llm_query_tokens_total` - Counter of tokens processed (prompt, completion, total)
- `llm_embedding_duration_seconds` - Histogram of embedding generation latency
- `llm_splade_duration_seconds` - Histogram of SPLADE vector generation latency

**Cache Metrics:**
- `cache_operations_total` - Counter of cache operations by type (get/set) and status (hit/miss/error)
- `cache_hit_rate` - Gauge of cache hit rate percentage by cache type (embedding, splade, query, overall)
- `cache_size_bytes` - Gauge of estimated cache size in bytes
- `cache_ttl_seconds` - Gauge of cache TTL configuration by cache type

**Qdrant Metrics:**
- `qdrant_query_duration_seconds` - Histogram of Qdrant query latency by collection and query type
- `qdrant_query_results_total` - Histogram of result counts by collection and query type
- `qdrant_query_total` - Counter of total Qdrant queries by collection, query type, and status
- `qdrant_collection_points` - Gauge of point counts in each Qdrant collection

**Chat History Metrics:**
- `chat_operations_total` - Counter of chat history operations by operation and status
- `chat_message_size_bytes` - Histogram of chat message sizes by role
- `chat_session_duration_seconds` - Histogram of chat session durations

**Configuration:**
```bash
# Metrics are enabled by default
# To disable, set environment variable:
export ENABLE_METRICS=false
```

**Accessing Metrics:**
```bash
# View all metrics
curl http://localhost:8080/metrics

# Filter specific metrics
curl http://localhost:8080/metrics | grep llm_query_duration
curl http://localhost:8080/metrics | grep cache_hit_rate
curl http://localhost:8080/metrics | grep qdrant_query_duration
```

**Example Metrics Output:**
```prometheus
# LLM query latency
llm_query_duration_seconds_bucket{model="qwen3:8b",operation_type="query",status="success",le="1.0"} 45
llm_query_duration_seconds_sum{model="qwen3:8b",operation_type="query",status="success"} 23.5
llm_query_duration_seconds_count{model="qwen3:8b",operation_type="query",status="success"} 50

# Cache hit rate
cache_hit_rate{cache_type="embedding"} 87.5
cache_hit_rate{cache_type="query"} 72.3
cache_hit_rate{cache_type="overall"} 81.2

# Qdrant query performance
qdrant_query_duration_seconds_bucket{collection="Aristotle",query_type="hybrid",status="success",le="0.1"} 120
qdrant_collection_points{collection="Aristotle"} 15234
```

**Integration with Monitoring Systems:**

**Prometheus:** Add to `prometheus.yml`:
```yaml
scrape_configs:
  - job_name: 'ontologic-api'
    scrape_interval: 15s
    static_configs:
      - targets: ['localhost:8080']
```

**Grafana Dashboard:** Create visualizations using PromQL queries:
```promql
# Average LLM query latency (last 5 minutes)
rate(llm_query_duration_seconds_sum[5m]) / rate(llm_query_duration_seconds_count[5m])

# Cache hit rate percentage
cache_hit_rate{cache_type="overall"}

# Qdrant query p95 latency
histogram_quantile(0.95, rate(qdrant_query_duration_seconds_bucket[5m]))

# Total queries per second
sum(rate(llm_query_total[1m]))
```

**Alerting Rules:** Example Prometheus alerting rules:
```yaml
groups:
  - name: ontologic_api
    rules:
      - alert: HighLLMLatency
        expr: histogram_quantile(0.95, rate(llm_query_duration_seconds_bucket[5m])) > 10
        for: 5m
        annotations:
          summary: "High LLM query latency detected"

      - alert: LowCacheHitRate
        expr: cache_hit_rate{cache_type="overall"} < 50
        for: 10m
        annotations:
          summary: "Cache hit rate below 50%"

      - alert: HighQdrantLatency
        expr: histogram_quantile(0.95, rate(qdrant_query_duration_seconds_bucket[5m])) > 1
        for: 5m
        annotations:
          summary: "High Qdrant query latency detected"
```

**Cloud Provider Integration:**
- **AWS CloudWatch:** Use CloudWatch Agent with Prometheus scraping
- **GCP Monitoring:** Use Google Cloud Managed Service for Prometheus
- **Azure Monitor:** Use Azure Monitor managed Prometheus service

### OpenTelemetry Distributed Tracing

Ontologic API includes OpenTelemetry instrumentation for distributed tracing and observability.

**Features:**
- Automatic FastAPI endpoint tracing
- Request/response correlation with trace IDs
- Support for multiple exporters (OTLP, Console)
- Custom spans for critical operations (coming soon):
  - LLM query spans with token counts
  - Qdrant vector search spans
  - Cache operation spans

**Configuration:**
```bash
# Enable/disable tracing (default: enabled)
export OTEL_ENABLED=true

# Service identification
export OTEL_SERVICE_NAME=ontologic-api

# Export to OTLP collector (Jaeger, Tempo, etc.)
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Export to console for debugging
export OTEL_EXPORT_CONSOLE=true
```

**Integration Examples:**

**Jaeger (via OTLP):**
```bash
# Start Jaeger with OTLP support
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  jaegertracing/all-in-one:latest

# Configure Ontologic API
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
python app/main.py
```

**Grafana Tempo:**
```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317
```

**Honeycomb / Other SaaS:**
```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io:443
export OTEL_EXPORTER_OTLP_HEADERS="x-honeycomb-team=YOUR_API_KEY"
```

## 📊 System Status

✅ **Production Ready** - All endpoints operational (100% success rate)
- Authentication system working
- PDF context integration functional
- Chat history operational
- Backup system configured
- Performance optimized

## 🤝 Contributing

Development and testing utilities are available in `temp/test-files/` for debugging and validation.

## 📄 License

[Add your license information here]