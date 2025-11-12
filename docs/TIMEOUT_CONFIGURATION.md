# Timeout Configuration Guide

## Overview

The ontologic-api has multiple timeout layers to handle long-running LLM operations that can take up to a minute or more. This document explains the timeout configuration and how to adjust it for your needs.

## Timeout Layers

### 1. Uvicorn Server Timeouts

**Location**: `app/main.py`

```python
config = uvicorn.Config(
    app,
    timeout_keep_alive=600,  # 10 minutes for long-running operations
    timeout_graceful_shutdown=30,  # Allow graceful shutdown
)
```

- `timeout_keep_alive`: How long to keep HTTP connections alive (600s = 10 minutes)
- `timeout_graceful_shutdown`: Time to wait for graceful shutdown (30s)

### 2. Application-Level LLM Timeouts

**Location**: `app/config/dev.toml` and `app/config/prod.toml`

#### Development Environment (`dev.toml`)
```toml
[llm]
request_timeout_seconds = 120    # General LLM requests
generation_timeout_seconds = 120 # Text generation operations
chat_timeout_seconds = 120       # Chat/conversation operations
vet_timeout_seconds = 90         # Vetting operations
```

#### Production Environment (`prod.toml`)
```toml
[llm]
request_timeout_seconds = 300    # 5 minutes for production
generation_timeout_seconds = 300
chat_timeout_seconds = 300
vet_timeout_seconds = 300
```

### 3. API Endpoint Timeouts

**Location**: `app/router/ontologic.py`

```python
timeout: Annotated[int, Query(ge=5, le=180)] = 90
```

- Users can specify timeout per request (5-180 seconds)
- Default is 90 seconds for development

### 4. Qdrant Database Timeouts

**Location**: Configuration files

```toml
[qdrant]
timeout = 60  # Increased from 30 to 60 seconds
```

## Timeout Flow

```
Client Request → FastAPI (180s max) → LLM Manager (120s dev/300s prod) → Ollama (request_timeout) → Model Generation
                                   ↓
                              Qdrant (60s) → Vector Operations
```

## Configuration by Environment

### Development (`APP_ENV=dev`)
- **LLM Operations**: 120 seconds (2 minutes)
- **API Timeout Range**: 5-180 seconds (user configurable)
- **Qdrant**: 60 seconds
- **Keep-Alive**: 600 seconds (10 minutes)

### Production (`APP_ENV=prod`)
- **LLM Operations**: 300 seconds (5 minutes)
- **API Timeout Range**: 5-180 seconds (user configurable)
- **Qdrant**: 60 seconds
- **Keep-Alive**: 600 seconds (10 minutes)

## Adjusting Timeouts

### For Slower Models
If you're using larger/slower models, increase timeouts in your environment config:

```toml
[llm]
request_timeout_seconds = 600    # 10 minutes
generation_timeout_seconds = 600
chat_timeout_seconds = 600
vet_timeout_seconds = 300
```

### For Faster Models
For faster models, you can reduce timeouts:

```toml
[llm]
request_timeout_seconds = 60     # 1 minute
generation_timeout_seconds = 60
chat_timeout_seconds = 60
vet_timeout_seconds = 30
```

### Environment Variable Overrides
You can override any timeout via environment variables:

```bash
export APP_LLM_REQUEST_TIMEOUT=300
export APP_LLM_GENERATION_TIMEOUT=300
export APP_LLM_CHAT_TIMEOUT=300
export APP_LLM_VET_TIMEOUT=180
```

## Error Handling

The application handles timeouts gracefully:

1. **LLMTimeoutError**: Raised when LLM operations exceed timeout
2. **HTTP 408**: Request timeout for API calls
3. **HTTP 504**: Gateway timeout for service unavailability

## Monitoring Timeouts

Check logs for timeout-related messages:

```bash
# Look for timeout warnings
grep -i "timeout" logs/app.log

# Monitor LLM operation times
grep "LLM.*timed out" logs/app.log
```

## Best Practices

1. **Development**: Use shorter timeouts (60-120s) for faster feedback
2. **Production**: Use longer timeouts (300s+) for reliability
3. **Load Balancers**: Ensure upstream timeouts are longer than application timeouts
4. **Monitoring**: Set up alerts for frequent timeout errors
5. **Client-Side**: Implement proper timeout handling in frontend applications

## Troubleshooting

### Common Issues

1. **Frequent Timeouts**: Increase LLM timeouts or use faster models
2. **Connection Drops**: Increase `timeout_keep_alive`
3. **Slow Responses**: Check model performance and system resources
4. **Client Timeouts**: Ensure client timeout > server timeout

### Testing Timeouts

Use the provided test script:

```bash
python scripts/test_timeouts.py
```

This will test various timeout scenarios and help identify configuration issues.