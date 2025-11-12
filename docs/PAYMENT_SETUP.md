# Payment System Setup Guide

This guide explains how to set up and test the Stripe payment integration in the Ontologic API.

## Overview

The payment system provides:
- Subscription management (Free, Basic, Premium, Academic tiers)
- Stripe checkout integration
- Usage tracking and billing
- Refund and dispute handling
- Webhook processing for payment events

## Prerequisites

1. **Stripe Account**: Create a free account at [stripe.com](https://stripe.com)
2. **Test API Keys**: Get your test keys from the [Stripe Dashboard](https://dashboard.stripe.com/test/apikeys)
3. **Dependencies**: Ensure `stripe` package is installed (included in `pyproject.toml`)

## Quick Start

### 1. Install Dependencies

```bash
uv sync
```

This installs all dependencies including the Stripe SDK.

### 2. Configure Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` and add your Stripe test keys:

```bash
APP_PAYMENTS_ENABLED=true
APP_STRIPE_PUBLISHABLE_KEY=pk_test_your_key_here
APP_STRIPE_SECRET_KEY=sk_test_your_key_here
APP_STRIPE_WEBHOOK_SECRET=whsec_your_secret_here
```

**Important**: Use test keys (starting with `pk_test_` and `sk_test_`) for development.

### 3. Enable Payments in Configuration

Payments are enabled by default in `app/config/toml/dev.toml`. Verify:

```toml
[payments]
enabled = true
grace_period_days = 7
```

### 4. Start the Server

Use the convenience script:

```bash
./scripts/start_with_payments.sh
```

Or start manually:

```bash
export APP_PAYMENTS_ENABLED=true
uv run app/main.py --env dev
```

### 5. Verify Payment Endpoints

Check that payment routes are available:

```bash
curl http://localhost:8080/payments/
```

You should see payment endpoint information (not a 404).

## Payment Endpoints

### User Endpoints

- `POST /payments/checkout` - Create Stripe checkout session
- `GET /payments/subscription` - Get current subscription
- `POST /payments/subscription/cancel` - Cancel subscription
- `GET /payments/usage` - Get usage statistics
- `GET /payments/billing/history` - Get billing history
- `POST /payments/webhook` - Stripe webhook handler

### Admin Endpoints

- `GET /admin/payments/health` - Payment system health check
- `GET /admin/payments/subscriptions` - List all subscriptions
- `POST /admin/payments/refund` - Process refund
- `GET /admin/payments/disputes` - List disputes
- `POST /admin/payments/disputes/{id}/evidence` - Submit dispute evidence

## Testing Payments

### 1. Run Payment System Tests

```bash
uv run pytest tests/test_payment_system_integration.py -v
```

### 2. Test Checkout Flow

```bash
# Register a user
curl -X POST http://localhost:8080/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass123","username":"testuser"}'

# Login to get JWT token
curl -X POST http://localhost:8080/auth/jwt/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@example.com&password=testpass123"

# Create checkout session
curl -X POST http://localhost:8080/payments/checkout \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"price_id":"price_test_basic","success_url":"http://localhost:3000/success","cancel_url":"http://localhost:3000/cancel"}'
```

### 3. Test Stripe Webhooks Locally

Install Stripe CLI:

```bash
brew install stripe/stripe-cli/stripe
# or
scoop install stripe
```

Forward webhooks to your local server:

```bash
stripe listen --forward-to localhost:8080/payments/webhook
```

Trigger test events:

```bash
stripe trigger payment_intent.succeeded
stripe trigger customer.subscription.deleted
```

## Subscription Tiers

| Tier | Price | Requests/Month | Features |
|------|-------|----------------|----------|
| Free | $0 | 2,000 | Basic access |
| Basic | $9.99 | 20,000 | Standard features |
| Premium | $29.99 | 100,000 | All features + priority support |
| Academic | $14.99 | 50,000 | Academic discount |

## Troubleshooting

### Payment endpoints return 404

**Cause**: Payments not enabled or Stripe not installed.

**Solution**:
1. Check `APP_PAYMENTS_ENABLED=true` in environment
2. Verify Stripe is installed: `uv pip list | grep stripe`
3. Check server logs for "PaymentService initialized"

### "Stripe library not available" error

**Cause**: Stripe package not in dependencies.

**Solution**:
1. Verify `stripe` is in `pyproject.toml`
2. Run `uv sync` to install dependencies
3. Restart the server

### Webhook signature verification fails

**Cause**: Incorrect webhook secret or payload.

**Solution**:
1. Get webhook secret from Stripe Dashboard
2. Set `APP_STRIPE_WEBHOOK_SECRET` in `.env`
3. Use Stripe CLI for local testing

### Payment service disabled despite configuration

**Cause**: Missing Stripe API keys.

**Solution**:
1. Verify `APP_STRIPE_SECRET_KEY` is set
2. Check key starts with `sk_test_` for test mode
3. Check server logs for initialization errors

## Security Best Practices

1. **Never commit API keys**: Keep `.env` in `.gitignore`
2. **Use test keys in development**: Only use live keys in production
3. **Validate webhooks**: Always verify Stripe webhook signatures
4. **Secure endpoints**: Payment endpoints require authentication
5. **Log payment events**: Monitor all payment operations

## Production Deployment

### 1. Use Live API Keys

Replace test keys with live keys from [Stripe Dashboard](https://dashboard.stripe.com/apikeys):

```bash
APP_STRIPE_PUBLISHABLE_KEY=pk_live_...
APP_STRIPE_SECRET_KEY=sk_live_...
```

### 2. Configure Webhooks

1. Go to [Stripe Webhooks](https://dashboard.stripe.com/webhooks)
2. Add endpoint: `https://your-domain.com/payments/webhook`
3. Select events to listen for:
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
   - `charge.dispute.created`
   - `charge.dispute.updated`
4. Copy webhook secret to `APP_STRIPE_WEBHOOK_SECRET`

### 3. Enable Production Mode

```bash
APP_ENV=prod
APP_PAYMENTS_ENABLED=true
```

### 4. Monitor Payment Events

Check logs for payment operations:

```bash
grep "payment\|stripe\|subscription" logs/server.log
```

## Additional Resources

- [Stripe API Documentation](https://stripe.com/docs/api)
- [Stripe Testing Guide](https://stripe.com/docs/testing)
- [Webhook Best Practices](https://stripe.com/docs/webhooks/best-practices)
- [Payment Security](https://stripe.com/docs/security)

## Support

For issues or questions:
1. Check server logs: `logs/server.log`
2. Run diagnostic tests: `uv run pytest tests/test_payment_*.py -v`
3. Review Stripe Dashboard for payment events
