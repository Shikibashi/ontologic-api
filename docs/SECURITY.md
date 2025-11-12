# Security Guide

This document outlines security requirements and best practices for deploying Ontologic API.

## Production Deployment Checklist

### Required Environment Variables

Before deploying to production, ensure these environment variables are set:

```bash
# JWT Authentication (REQUIRED)
export APP_JWT_SECRET="<32+ character random string>"
export APP_SESSION_SECRET="<32+ character random string>"

# Generate secure secrets:
openssl rand -hex 32
```

### Stripe Payment Configuration

If payments are enabled (`APP_PAYMENTS_ENABLED=true`):

```bash
export APP_STRIPE_SECRET_KEY="sk_live_..."
export APP_STRIPE_PUBLISHABLE_KEY="pk_live_..."
export APP_STRIPE_WEBHOOK_SECRET="whsec_..."

# Stripe Price IDs (from Stripe Dashboard)
export APP_STRIPE_PRICE_BASIC_MONTHLY="price_..."
export APP_STRIPE_PRICE_PREMIUM_MONTHLY="price_..."
export APP_STRIPE_PRICE_ACADEMIC_MONTHLY="price_..."
```

### CORS Configuration

Restrict CORS to trusted origins:

```bash
# Comma-separated list of allowed origins
export APP_CORS_ORIGINS="https://yourdomain.com,https://app.yourdomain.com"
```

### Database Security

```bash
# Use SSL/TLS for database connections
export APP_DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/db?ssl=require"
```

## Startup Validation

The application performs automatic security validation on startup:

- **JWT Secret**: Must be changed from default and be at least 32 characters
- **Session Secret**: Must be at least 32 characters if set
- **Stripe Secrets**: Required if payments are enabled
- **Environment**: Production mode requires all security checks to pass

If validation fails, the application will:
1. Log detailed error messages
2. Mark startup as failed
3. Return 503 Service Unavailable on `/health/ready`

## Authentication

### JWT Tokens

- Tokens are signed with HS256 algorithm
- Default lifetime: 1 hour (configurable via `APP_JWT_LIFETIME_SECONDS`)
- Tokens include user ID and are validated on every authenticated request

### Protected Endpoints

These endpoints require JWT authentication:

- `/payments/*` - All payment and subscription endpoints
- `/documents/*` - Document upload, list, and delete
- `/auth/jwt/*` - User registration and login

### Optional Authentication

These endpoints work with or without authentication:

- `/api/ask` - Philosophy queries (rate limits apply)
- `/api/chat` - Chat conversations (session-based)
- `/chat/history/*` - Chat history (session-based isolation)

## Webhook Security

### Stripe Webhooks

The `/payments/webhooks/stripe` endpoint:

1. **Signature Verification**: Uses `stripe.Webhook.construct_event()` to verify signatures
2. **Idempotency**: Tracks processed event IDs to prevent duplicate processing
3. **Error Handling**: Returns 400 for invalid signatures, 500 for processing errors

**Setup:**

1. Configure webhook endpoint in Stripe Dashboard: `https://yourdomain.com/payments/webhooks/stripe`
2. Copy webhook signing secret to `APP_STRIPE_WEBHOOK_SECRET`
3. Test with Stripe CLI: `stripe listen --forward-to localhost:8080/payments/webhooks/stripe`

## Rate Limiting

Rate limits are enforced via SlowAPI:

- Default: 60 requests/minute per IP
- Upload endpoints: 10 requests/minute
- Heavy operations (search): 20 requests/minute

Subscription tiers have additional limits:

- Free: 1,000 requests/month
- Basic: 10,000 requests/month
- Premium: 100,000 requests/month
- Academic: 50,000 requests/month

## Security Headers

All responses include:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- `X-XSS-Protection: 1; mode=block`
- `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`

## Data Privacy

### Chat History

- Session-based isolation: Users can only access their own session data
- Session IDs are validated to prevent path traversal
- No cross-session data leakage

### Document Uploads

- User-specific Qdrant collections (username-based)
- JWT authentication required for all document operations
- Ownership verified on list and delete operations

### Payment Data

- Sensitive payment data stored in Stripe, not locally
- Invoice downloads require ownership verification
- PII is not leaked in error messages

## Monitoring & Alerts

### Security Events to Monitor

1. Failed authentication attempts (401 responses)
2. Authorization failures (403 responses)
3. Invalid webhook signatures
4. Rate limit violations
5. Startup validation failures

### Recommended Alerts

```promql
# High rate of authentication failures
rate(http_requests_total{status="401"}[5m]) > 10

# Invalid webhook signatures
rate(stripe_webhook_errors_total{error_type="signature"}[5m]) > 1

# Startup validation failures
startup_validation_errors_total > 0
```

## Incident Response

### Compromised JWT Secret

1. Immediately rotate `APP_JWT_SECRET`
2. Restart all application instances
3. All existing tokens will be invalidated
4. Users must re-authenticate

### Compromised Stripe Secret

1. Roll secret in Stripe Dashboard
2. Update `APP_STRIPE_SECRET_KEY` and `APP_STRIPE_WEBHOOK_SECRET`
3. Restart application
4. Monitor for unauthorized charges

### Data Breach

1. Identify scope of breach (chat history, documents, payment data)
2. Notify affected users
3. Review access logs and audit trails
4. Implement additional security controls

## Security Updates

Keep dependencies up to date:

```bash
# Check for security vulnerabilities
pip-audit

# Update dependencies
uv sync --upgrade
```

## Contact

For security issues, please contact: security@yourdomain.com
