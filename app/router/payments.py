"""
Payment processing router for subscription management and billing.

Provides endpoints for:
- Checkout session creation
- Subscription management (get, cancel, update)
- Billing history and usage tracking
- Stripe webhook handling
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from datetime import datetime
import stripe

from app.core.auth_config import current_active_user, current_user_optional
from app.core.user_models import User, UserRead
from app.core.rate_limiting import limiter, get_default_limit
from app.core.logger import log
from app.config.settings import get_settings
from app.core.error_responses import (
    create_validation_error,
    create_not_found_error,
    create_internal_error,
    create_service_unavailable_error,
    create_authorization_error
)


# Router setup
router = APIRouter(prefix="/payments", tags=["payments"])


# Request/Response Models
class CheckoutRequest(BaseModel):
    """Request model for creating a checkout session."""
    price_id: str = Field(..., description="Stripe price ID for the subscription")
    success_url: str = Field(..., description="URL to redirect after successful payment")
    cancel_url: str = Field(..., description="URL to redirect after cancelled payment")


class CheckoutResponse(BaseModel):
    """Response model for checkout session creation."""
    checkout_url: str = Field(..., description="Stripe checkout session URL")
    session_id: str = Field(..., description="Stripe checkout session ID")


class SubscriptionResponse(BaseModel):
    """Response model for subscription information."""
    id: Optional[str] = Field(None, description="Stripe subscription ID")
    tier: str = Field(..., description="Subscription tier")
    status: str = Field(..., description="Subscription status")
    current_period_start: Optional[datetime] = Field(None, description="Current billing period start")
    current_period_end: Optional[datetime] = Field(None, description="Current billing period end")
    cancel_at_period_end: bool = Field(False, description="Whether subscription will cancel at period end")


class UsageStats(BaseModel):
    """Response model for usage statistics."""
    current_period_requests: int = Field(..., description="API requests in current billing period")
    current_period_tokens: int = Field(..., description="Tokens used in current billing period")
    monthly_limit_requests: int = Field(..., description="Monthly request limit for current tier")
    monthly_limit_tokens: int = Field(..., description="Monthly token limit for current tier")
    usage_percentage: float = Field(..., description="Usage percentage of monthly limits")


class BillingRecord(BaseModel):
    """Response model for billing history records."""
    id: str = Field(..., description="Payment record ID")
    amount_cents: int = Field(..., description="Payment amount in cents")
    currency: str = Field(..., description="Payment currency")
    status: str = Field(..., description="Payment status")
    description: Optional[str] = Field(None, description="Payment description")
    created_at: datetime = Field(..., description="Payment creation timestamp")


class BillingHistoryResponse(BaseModel):
    """Response model for billing history."""
    records: List[BillingRecord] = Field(..., description="List of billing records")
    total_count: int = Field(..., description="Total number of billing records")


class SubscriptionLimits(BaseModel):
    """Response model for subscription limits and status."""
    tier: str = Field(..., description="Current subscription tier")
    status: str = Field(..., description="Subscription status")
    requests_per_month: int = Field(..., description="Monthly request limit")
    max_tokens_per_request: int = Field(..., description="Maximum tokens per request")
    features: List[str] = Field(..., description="Available features for this tier")
    current_period_start: Optional[datetime] = Field(None, description="Current billing period start")
    current_period_end: Optional[datetime] = Field(None, description="Current billing period end")


class InvoiceResponse(BaseModel):
    """Response model for invoice download."""
    invoice_id: str = Field(..., description="Invoice ID")
    download_url: str = Field(..., description="Temporary download URL for invoice PDF")
    expires_at: datetime = Field(..., description="URL expiration timestamp")


class WebhookResponse(BaseModel):
    """Response model for webhook processing."""
    received: bool = Field(True, description="Whether webhook was received successfully")
    processed: bool = Field(..., description="Whether webhook was processed successfully")
    event_type: str = Field(..., description="Stripe event type")


# Helper functions

async def _verify_webhook_signature(
    payload: bytes,
    sig_header: str,
    webhook_secret: str,
    request_id: Optional[str]
) -> Dict[str, Any]:
    """
    Verify Stripe webhook signature and construct event.

    Args:
        payload: Raw request body bytes
        sig_header: Stripe-Signature header value
        webhook_secret: Stripe webhook secret
        request_id: Request ID for error tracking

    Returns:
        Validated Stripe event dictionary

    Raises:
        HTTPException: 400 if signature verification fails or payload is invalid
    """
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=webhook_secret
        )
        log.debug(f"Successfully validated webhook signature for event type: {event.get('type', 'unknown')}")
        return event
    except ValueError as e:
        log.warning(f"Invalid Stripe webhook payload: {e}")
        error = create_validation_error(
            field="payload",
            message=f"Invalid payload: {str(e)}",
            request_id=request_id
        )
        raise HTTPException(status_code=400, detail=error.model_dump())
    except stripe.error.SignatureVerificationError as e:
        log.warning(f"Invalid Stripe webhook signature: {e}")
        error = create_validation_error(
            field="signature",
            message=f"Invalid signature: {str(e)}",
            request_id=request_id
        )
        raise HTTPException(status_code=400, detail=error.model_dump())
    except Exception as e:
        log.error(f"Unexpected error during webhook signature verification: {e}")
        error = create_internal_error(
            message=f"Signature verification failed: {str(e)}",
            request_id=request_id
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


# Dependency functions
async def get_payment_service(request: Request):
    """Get payment service from app state."""
    payment_service = getattr(request.app.state, 'payment_service', None)
    if payment_service is None:
        raise HTTPException(
            status_code=503,
            detail="Payment service unavailable. Payments may be disabled."
        )
    return payment_service


async def get_subscription_manager(request: Request):
    """Get subscription manager from app state."""
    subscription_manager = getattr(request.app.state, 'subscription_manager', None)
    if subscription_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Subscription manager unavailable. Payments may be disabled."
        )
    return subscription_manager


async def get_billing_service(request: Request):
    """Get billing service from app state."""
    billing_service = getattr(request.app.state, 'billing_service', None)
    if billing_service is None:
        raise HTTPException(
            status_code=503,
            detail="Billing service unavailable. Payments may be disabled."
        )
    return billing_service


# Checkout endpoints
@router.post("/checkout", response_model=CheckoutResponse)
@limiter.limit(get_default_limit)
async def create_checkout_session(
    request: Request,
    checkout_request: CheckoutRequest,
    current_user: User = Depends(current_active_user),
    payment_service = Depends(get_payment_service)
) -> CheckoutResponse:
    """
    Create a Stripe checkout session for subscription purchase.
    
    Requires authentication. Creates a checkout session that redirects the user
    to Stripe's hosted checkout page for secure payment processing.
    """
    try:
        log.info(
            f"Creating checkout session for user {current_user.id}, price_id: {checkout_request.price_id}"
        )

        if not current_user.stripe_customer_id:
            error = create_validation_error(
                field="user",
                message="User must have a Stripe customer account. Please contact support.",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=400, detail=error.model_dump())

        checkout_session = await payment_service.create_checkout_session(
            customer=current_user,
            price_id=checkout_request.price_id,
            success_url=checkout_request.success_url,
            cancel_url=checkout_request.cancel_url
        )

        request_id = getattr(request.state, 'request_id', None)

        try:
            session_id = checkout_session["id"]
            session_url = checkout_session["url"]
        except KeyError as e:
            missing_key = e.args[0] if e.args else "unknown"
            log.error(
                f"Stripe checkout session missing required field: {missing_key}, "
                f"request_id={request_id}"
            )
            error = create_internal_error(
                message=f"Malformed Stripe response: missing {missing_key}",
                request_id=request_id
            )
            raise HTTPException(status_code=500, detail=error.model_dump())

        log.info(f"Checkout session created: {session_id}")

        return CheckoutResponse(
            checkout_url=session_url,
            session_id=session_id
        )

    except ValueError as e:
        log.warning(f"Invalid checkout request for user {current_user.id}: {e}")
        error = create_validation_error(
            field="price_id",
            message=str(e),
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=400, detail=error.model_dump())

    except Exception as e:
        log.error(f"Failed to create checkout session for user {current_user.id}: {e}")
        error = create_internal_error(
            message="Failed to create checkout session",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


# Subscription management endpoints
@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    request: Request,
    current_user: User = Depends(current_active_user),
    subscription_manager = Depends(get_subscription_manager)
) -> SubscriptionResponse:
    """
    Get current user's subscription information.
    
    Returns subscription details including tier, status, and billing period.
    """
    try:
        log.debug(f"Getting subscription for user {current_user.id}")
        
        subscription = await subscription_manager.get_user_subscription(current_user.id)
        
        if subscription is None:
            # User has no subscription (free tier)
            return SubscriptionResponse(
                tier=current_user.subscription_tier,
                status=current_user.subscription_status,
                cancel_at_period_end=False
            )
        
        return SubscriptionResponse(
            id=subscription.stripe_subscription_id,
            tier=subscription.tier,
            status=subscription.status,
            current_period_start=subscription.current_period_start,
            current_period_end=subscription.current_period_end,
            cancel_at_period_end=False  # Will be set from Stripe data
        )
        
    except Exception as e:
        log.error(f"Failed to get subscription for user {current_user.id}: {e}")
        error = create_internal_error(
            message="Failed to retrieve subscription information",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.post("/subscription/cancel")
async def cancel_subscription(
    request: Request,
    current_user: User = Depends(current_active_user),
    payment_service = Depends(get_payment_service),
    subscription_manager = Depends(get_subscription_manager)
) -> Dict[str, Any]:
    """
    Cancel current user's subscription.
    
    Cancels the subscription at the end of the current billing period.
    User retains access until the period ends.
    """
    try:
        log.info(f"Cancelling subscription for user {current_user.id}")
        
        subscription = await subscription_manager.get_user_subscription(current_user.id)

        if subscription is None or subscription.stripe_subscription_id is None:
            # Use 403 instead of 404 to prevent subscription enumeration attacks
            error = create_authorization_error(
                message="No active subscription to cancel",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=403, detail=error.model_dump())
        
        # Cancel subscription via payment service
        success = await payment_service.cancel_subscription(subscription.stripe_subscription_id)
        
        if success:
            log.info(f"Subscription cancelled for user {current_user.id}")
            return {
                "message": "Subscription cancelled successfully",
                "cancelled": True,
                "access_until": subscription.current_period_end
            }
        else:
            raise Exception("Failed to cancel subscription")
            
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to cancel subscription for user {current_user.id}: {e}")
        error = create_internal_error(
            message="Failed to cancel subscription",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


# Usage and billing endpoints
@router.get("/usage", response_model=UsageStats)
async def get_usage_stats(
    request: Request,
    current_user: User = Depends(current_active_user),
    billing_service = Depends(get_billing_service),
    subscription_manager = Depends(get_subscription_manager)
) -> UsageStats:
    """
    Get current user's usage statistics for the current billing period.
    
    Returns API usage, token consumption, and limits based on subscription tier.
    """
    try:
        log.debug(f"Getting usage stats for user {current_user.id}")
        
        # Get current period usage
        usage_stats = await billing_service.get_usage_stats(
            user_id=current_user.id,
            period="current"
        )
        
        # Get usage limits for current tier
        tier = await subscription_manager.get_user_tier(current_user.id)
        usage_limits = await subscription_manager.get_usage_limits(tier)
        
        # Calculate usage percentage
        request_percentage = (usage_stats.requests / usage_limits.requests_per_month) * 100
        token_percentage = (usage_stats.tokens / usage_limits.max_tokens_per_request) * 100
        usage_percentage = max(request_percentage, token_percentage)
        
        return UsageStats(
            current_period_requests=usage_stats.requests,
            current_period_tokens=usage_stats.tokens,
            monthly_limit_requests=usage_limits.requests_per_month,
            monthly_limit_tokens=usage_limits.max_tokens_per_request,
            usage_percentage=min(usage_percentage, 100.0)
        )
        
    except Exception as e:
        log.error(f"Failed to get usage stats for user {current_user.id}: {e}")
        error = create_internal_error(
            message="Failed to retrieve usage statistics",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.get("/billing/history", response_model=BillingHistoryResponse)
async def get_billing_history(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(current_active_user),
    billing_service = Depends(get_billing_service)
) -> BillingHistoryResponse:
    """
    Get user's billing history with pagination.
    
    Returns a list of past payments and transactions.
    """
    try:
        log.debug(f"Getting billing history for user {current_user.id}")
        
        billing_records = await billing_service.get_billing_history(
            user_id=current_user.id,
            limit=limit,
            offset=offset
        )
        
        # Convert to response format
        records = [
            BillingRecord(
                id=record.stripe_payment_intent_id,
                amount_cents=record.amount_cents,
                currency=record.currency,
                status=record.status,
                description=record.description,
                created_at=record.created_at
            )
            for record in billing_records
        ]
        
        return BillingHistoryResponse(
            records=records,
            total_count=len(records)  # TODO: Implement proper count query
        )
        
    except Exception as e:
        log.error(f"Failed to get billing history for user {current_user.id}: {e}")
        error = create_internal_error(
            message="Failed to retrieve billing history",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.get("/subscription/limits", response_model=SubscriptionLimits)
async def get_subscription_limits(
    request: Request,
    current_user: User = Depends(current_active_user),
    subscription_manager = Depends(get_subscription_manager)
) -> SubscriptionLimits:
    """
    Get current user's subscription limits and status.
    
    Returns detailed information about subscription tier, limits, and available features.
    """
    try:
        log.debug(f"Getting subscription limits for user {current_user.id}")
        
        # Get user's current tier and subscription
        tier = await subscription_manager.get_user_tier(current_user.id)
        subscription = await subscription_manager.get_user_subscription(current_user.id)
        usage_limits = await subscription_manager.get_usage_limits(tier)
        
        # Get tier features from configuration
        features = await subscription_manager.get_tier_features(tier)
        
        return SubscriptionLimits(
            tier=tier.value,
            status=current_user.subscription_status.value,
            requests_per_month=usage_limits.requests_per_month,
            max_tokens_per_request=usage_limits.max_tokens_per_request,
            features=features,
            current_period_start=subscription.current_period_start if subscription else None,
            current_period_end=subscription.current_period_end if subscription else None
        )
        
    except Exception as e:
        log.error(f"Failed to get subscription limits for user {current_user.id}: {e}")
        error = create_internal_error(
            message="Failed to retrieve subscription limits",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.get("/billing/invoices/{invoice_id}/download", response_model=InvoiceResponse)
async def download_invoice(
    request: Request,
    invoice_id: str,
    current_user: User = Depends(current_active_user),
    billing_service = Depends(get_billing_service)
) -> InvoiceResponse:
    """
    Generate a temporary download URL for an invoice PDF.
    
    Returns a secure, time-limited URL for downloading the invoice.
    """
    try:
        log.debug(f"Generating invoice download URL for user {current_user.id}, invoice {invoice_id}")
        
        # Verify user owns this invoice
        invoice_exists = await billing_service.verify_invoice_ownership(
            user_id=current_user.id,
            invoice_id=invoice_id
        )

        # Return 403 on ownership failure to avoid leaking invoice existence
        if not invoice_exists:
            error = create_authorization_error(
                message="Access denied to this invoice",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=403, detail=error.model_dump())
        
        # Generate temporary download URL
        download_info = await billing_service.generate_invoice_download_url(invoice_id)
        
        return InvoiceResponse(
            invoice_id=invoice_id,
            download_url=download_info['url'],
            expires_at=download_info['expires_at']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to generate invoice download URL for user {current_user.id}: {e}")
        error = create_internal_error(
            message="Failed to generate invoice download URL",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.get("/billing/dashboard")
async def get_billing_dashboard(
    request: Request,
    current_user: User = Depends(current_active_user),
    subscription_manager = Depends(get_subscription_manager),
    billing_service = Depends(get_billing_service)
) -> Dict[str, Any]:
    """
    Get comprehensive billing dashboard data.
    
    Returns subscription info, usage stats, recent billing history, and limits.
    """
    try:
        log.debug(f"Getting billing dashboard for user {current_user.id}")
        
        # Get subscription information
        subscription = await subscription_manager.get_user_subscription(current_user.id)
        tier = await subscription_manager.get_user_tier(current_user.id)
        usage_limits = await subscription_manager.get_usage_limits(tier)
        
        # Get current usage stats
        usage_stats = await billing_service.get_usage_stats(
            user_id=current_user.id,
            period="current"
        )
        
        # Get recent billing history (last 5 records)
        recent_billing = await billing_service.get_billing_history(
            user_id=current_user.id,
            limit=5,
            offset=0
        )
        
        # Calculate usage percentages
        request_percentage = (usage_stats.requests / usage_limits.requests_per_month) * 100
        usage_percentage = min(request_percentage, 100.0)
        
        # Get tier features
        features = await subscription_manager.get_tier_features(tier)
        
        dashboard_data = {
            "subscription": {
                "tier": tier.value,
                "status": current_user.subscription_status.value,
                "current_period_start": subscription.current_period_start if subscription else None,
                "current_period_end": subscription.current_period_end if subscription else None,
                "features": features
            },
            "usage": {
                "current_period_requests": usage_stats.requests,
                "current_period_tokens": usage_stats.tokens,
                "monthly_limit_requests": usage_limits.requests_per_month,
                "max_tokens_per_request": usage_limits.max_tokens_per_request,
                "usage_percentage": usage_percentage
            },
            "billing": {
                "recent_payments": [
                    {
                        "id": record.stripe_payment_intent_id,
                        "amount_cents": record.amount_cents,
                        "currency": record.currency,
                        "status": record.status,
                        "description": record.description,
                        "created_at": record.created_at
                    }
                    for record in recent_billing
                ],
                "next_billing_date": subscription.current_period_end if subscription else None
            },
            "limits": {
                "requests_per_month": usage_limits.requests_per_month,
                "max_tokens_per_request": usage_limits.max_tokens_per_request,
                "approaching_limit": usage_percentage > 80.0,
                "limit_exceeded": usage_percentage >= 100.0
            }
        }
        
        return dashboard_data
        
    except Exception as e:
        log.error(f"Failed to get billing dashboard for user {current_user.id}: {e}")
        error = create_internal_error(
            message="Failed to retrieve billing dashboard",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


# Webhook endpoint
@router.post("/webhooks/stripe", response_model=WebhookResponse)
async def handle_stripe_webhook(
    request: Request,
    payment_service = Depends(get_payment_service)
) -> WebhookResponse:
    """
    Handle Stripe webhook events.

    Processes subscription lifecycle events and payment notifications.
    Validates webhook signature for security and enforces idempotency.
    """
    try:
        # Get raw request body for signature validation
        payload = await request.body()
        sig_header = request.headers.get('stripe-signature')

        if not sig_header:
            log.warning("Stripe webhook received without signature header")
            error = create_validation_error(
                field="stripe-signature",
                message="Missing Stripe signature header",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=400, detail=error.model_dump())

        # Get webhook secret from settings
        settings = get_settings()

        if not settings.stripe_webhook_secret:
            log.error("Stripe webhook secret not configured")
            error = create_internal_error(
                message="Webhook secret not configured",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=500, detail=error.model_dump())

        webhook_secret = settings.stripe_webhook_secret.get_secret_value()
        request_id = getattr(request.state, 'request_id', None)

        # Verify webhook signature using helper
        event = await _verify_webhook_signature(payload, sig_header, webhook_secret, request_id)

        event_id = event.get('id')
        event_type = event.get('type', 'unknown')

        # Stripe webhooks MUST have an event ID for idempotency
        if not event_id:
            log.error(f"Stripe webhook missing event ID for event type: {event_type}")
            error = create_validation_error(
                field="event.id",
                message="Event missing required ID field",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=400, detail=error.model_dump())

        # Check idempotency: have we already processed this event?
        already_processed = await payment_service.check_webhook_processed(event_id)
        if already_processed:
            log.info(f"Webhook event {event_id} ({event_type}) already processed, returning success")
            return WebhookResponse(
                received=True,
                processed=True,
                event_type=event_type
            )

        log.info(f"Processing Stripe webhook event: {event_id} ({event_type})")
        
        # Process different event types
        processed = False
        
        if event_type == 'checkout.session.completed':
            processed = await _handle_checkout_completed(event, payment_service)
            
        elif event_type == 'customer.subscription.created':
            processed = await _handle_subscription_created(event, payment_service)
            
        elif event_type == 'customer.subscription.updated':
            processed = await _handle_subscription_updated(event, payment_service)
            
        elif event_type == 'customer.subscription.deleted':
            processed = await _handle_subscription_deleted(event, payment_service)
            
        elif event_type == 'invoice.payment_succeeded':
            processed = await _handle_payment_succeeded(event, payment_service)
            
        elif event_type == 'invoice.payment_failed':
            processed = await _handle_payment_failed(event, payment_service)
            
        else:
            log.info(f"Unhandled Stripe webhook event type: {event_type}")
            processed = True  # Mark as processed to avoid retries
        
        if processed:
            log.info(f"Successfully processed Stripe webhook event: {event_type}")
            # Mark event as processed for idempotency (event_id guaranteed to exist at this point)
            await payment_service.mark_webhook_processed(event_id, event_type)
        else:
            log.error(f"Failed to process Stripe webhook event: {event_type}")

        return WebhookResponse(
            received=True,
            processed=processed,
            event_type=event_type
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Unexpected error processing Stripe webhook: {e}")
        error = create_internal_error(
            message="Failed to process webhook",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


# Webhook event handlers
async def _handle_checkout_completed(event: Dict[str, Any], payment_service) -> bool:
    """Handle successful checkout session completion."""
    try:
        data = event.get('data', {})
        session = data.get('object', {})
        customer_id = session.get('customer')
        subscription_id = session.get('subscription')
        
        if customer_id and subscription_id:
            # Sync subscription data from Stripe
            await payment_service.sync_subscription_from_stripe(subscription_id)
            log.info(f"Synced subscription {subscription_id} for customer {customer_id}")
            return True
        else:
            log.warning(f"Checkout session missing customer or subscription ID: {session.get('id')}")
            return False
            
    except Exception as e:
        log.error(f"Error handling checkout completion: {e}")
        return False


async def _handle_subscription_created(event: Dict[str, Any], payment_service) -> bool:
    """Handle subscription creation."""
    try:
        data = event.get('data', {})
        subscription = data.get('object', {})
        subscription_id = subscription.get('id')
        
        # Sync subscription data from Stripe
        await payment_service.sync_subscription_from_stripe(subscription_id)
        log.info(f"Synced new subscription: {subscription_id}")
        return True
        
    except Exception as e:
        log.error(f"Error handling subscription creation: {e}")
        return False


async def _handle_subscription_updated(event: Dict[str, Any], payment_service) -> bool:
    """Handle subscription updates (status changes, plan changes, etc.)."""
    try:
        data = event.get('data', {})
        subscription = data.get('object', {})
        subscription_id = subscription.get('id')
        
        # Sync updated subscription data from Stripe
        await payment_service.sync_subscription_from_stripe(subscription_id)
        log.info(f"Synced updated subscription: {subscription_id}")
        return True
        
    except Exception as e:
        log.error(f"Error handling subscription update: {e}")
        return False


async def _handle_subscription_deleted(event: Dict[str, Any], payment_service) -> bool:
    """Handle subscription cancellation/deletion."""
    try:
        data = event.get('data', {})
        subscription = data.get('object', {})
        subscription_id = subscription.get('id')
        
        # Update subscription status to cancelled
        await payment_service.handle_subscription_cancelled(subscription_id)
        log.info(f"Handled subscription cancellation: {subscription_id}")
        return True
        
    except Exception as e:
        log.error(f"Error handling subscription deletion: {e}")
        return False


async def _handle_payment_succeeded(event: Dict[str, Any], payment_service) -> bool:
    """Handle successful payment."""
    try:
        data = event.get('data', {})
        invoice = data.get('object', {})
        customer_id = invoice.get('customer')
        subscription_id = invoice.get('subscription')
        
        if subscription_id:
            # Ensure subscription is active after successful payment
            await payment_service.sync_subscription_from_stripe(subscription_id)
            log.info(f"Payment succeeded for subscription: {subscription_id}")
        
        # Record payment in billing history
        await payment_service.record_successful_payment(invoice)
        return True
        
    except Exception as e:
        log.error(f"Error handling payment success: {e}")
        return False


async def _handle_payment_failed(event: Dict[str, Any], payment_service) -> bool:
    """Handle failed payment."""
    try:
        data = event.get('data', {})
        invoice = data.get('object', {})
        customer_id = invoice.get('customer')
        subscription_id = invoice.get('subscription')
        
        if subscription_id:
            # Handle payment failure (may trigger grace period)
            await payment_service.handle_payment_failure(subscription_id, invoice)
            log.info(f"Payment failed for subscription: {subscription_id}")
        
        # Record failed payment in billing history
        await payment_service.record_failed_payment(invoice)
        return True
        
    except Exception as e:
        log.error(f"Error handling payment failure: {e}")
        return False
