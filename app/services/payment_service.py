"""
Payment service for Stripe integration.

Handles customer creation, subscription management, and payment processing
using Stripe API. Follows existing service patterns with async factory method
and graceful degradation when payments are disabled.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Union, TYPE_CHECKING

try:
    import stripe
    from stripe import StripeError, CardError
except ImportError:
    stripe = None
    StripeError = Exception
    CardError = Exception

from app.config.settings import get_settings
from app.core.logger import log
from app.core.db_models import Subscription, PaymentRecord, SubscriptionTier, SubscriptionStatus, WebhookEvent
from app.core.user_models import User

if TYPE_CHECKING:
    from app.services.cache_service import RedisCacheService


class PaymentException(Exception):
    """Base exception for payment-related errors."""
    pass


class InsufficientFundsException(PaymentException):
    """Raised when payment fails due to insufficient funds."""
    pass


class SubscriptionNotFoundException(PaymentException):
    """Raised when subscription is not found."""
    pass


class PaymentService:
    """
    Stripe payment service for subscription and payment management.

    Provides customer creation, subscription lifecycle management, and payment
    processing with integration to existing cache service for performance.

    LIFECYCLE: This service should be initialized during application startup
    and stored in app.state for request-time access via dependency injection.
    """

    # Map common Stripe decline codes to appropriate exception types and user messages
    STRIPE_DECLINE_CODE_MAP = {
        'insufficient_funds': (InsufficientFundsException, "Insufficient funds"),
        'card_declined': (PaymentException, "Card declined by issuing bank"),
        'expired_card': (PaymentException, "Card has expired"),
        'incorrect_cvc': (PaymentException, "Incorrect CVC code"),
        'processing_error': (PaymentException, "Processing error - please try again"),
        'card_not_supported': (PaymentException, "Card type not supported"),
    }

    def __init__(self, cache_service: Optional['RedisCacheService'] = None):
        """
        Initialize PaymentService with optional cache service.

        Args:
            cache_service: Optional RedisCacheService for caching payment data.
                          If None, operations will not be cached.
        """
        self.cache_service = cache_service
        self.settings = get_settings()
        self._payments_enabled = False
        self._stripe_configured = False
        
        # Initialize Stripe if payments are enabled
        self._initialize_stripe()

        if cache_service is None:
            log.warning("PaymentService initialized without cache_service - payment data will not be cached")

    @classmethod
    async def start(cls, cache_service: Optional['RedisCacheService'] = None):
        """
        Async factory method for lifespan-managed initialization.

        Args:
            cache_service: Optional RedisCacheService instance

        Returns:
            Initialized PaymentService instance
        """
        instance = cls(cache_service=cache_service)
        
        if instance._payments_enabled:
            log.info("PaymentService initialized with Stripe integration enabled")
        else:
            log.info("PaymentService initialized with payments disabled")
            
        return instance

    def _initialize_stripe(self):
        """Initialize Stripe configuration and API key."""
        try:
            # Check if Stripe is available
            if stripe is None:
                log.warning("Stripe library not available - payments will be disabled")
                self._payments_enabled = False
                return

            # Check if payments are enabled
            self._payments_enabled = getattr(self.settings, 'payments_enabled', False)

            if not self._payments_enabled:
                log.info("Payments disabled in configuration")
                return

            # Get Stripe configuration
            stripe_secret_key = getattr(self.settings, 'stripe_secret_key', None)

            if not stripe_secret_key:
                log.warning("Stripe secret key not configured - payments will be disabled")
                self._payments_enabled = False
                return

            secret_value = (
                stripe_secret_key.get_secret_value()
                if hasattr(stripe_secret_key, "get_secret_value")
                else stripe_secret_key
            )

            if not secret_value or not secret_value.startswith("sk_"):
                log.error("Invalid Stripe API key format - payments will be disabled")
                self._payments_enabled = False
                self._stripe_configured = False
                return

            # Configure Stripe
            stripe.api_key = secret_value
            self._stripe_configured = True

            log.info("Stripe API configured successfully")

        except Exception as e:
            log.warning(f"Stripe initialization failed: {e} - payments will be disabled")
            self._payments_enabled = False
            self._stripe_configured = False

    def _make_cache_key(self, prefix: str, *args) -> str:
        """Generate cache key for payment data."""
        if not self.cache_service:
            return ""
        return self.cache_service._make_cache_key(f"payment:{prefix}", *args)

    def _normalize_customer_id(self, customer: Union[User, str]) -> tuple[str, Optional[int]]:
        """
        Normalize customer input to Stripe customer ID and optional user ID.

        Args:
            customer: User instance or Stripe customer ID string

        Returns:
            Tuple of (stripe_customer_id, user_id)

        Raises:
            PaymentException: If customer ID is invalid or empty
        """
        if isinstance(customer, User):
            stripe_customer_id = customer.stripe_customer_id
            user_id = customer.id

            # Validate user has a Stripe customer ID
            if not stripe_customer_id or not stripe_customer_id.strip():
                raise PaymentException(
                    f"User {user_id} does not have a Stripe customer ID. "
                    "Call create_stripe_customer(user) first to create a Stripe customer, "
                    "or ensure the user.stripe_customer_id field is populated."
                )
        else:
            stripe_customer_id = customer
            user_id = None

            # Validate customer ID is non-empty
            if not stripe_customer_id or not stripe_customer_id.strip():
                raise PaymentException(
                    "Stripe customer ID is required and cannot be empty. "
                    "Provide a valid Stripe customer ID (format: 'cus_...')."
                )

        stripe_customer_id = stripe_customer_id.strip()

        # Validate Stripe customer ID format
        if not stripe_customer_id.startswith('cus_'):
            raise PaymentException(
                f"Invalid Stripe customer ID format: '{stripe_customer_id}'. "
                "Stripe customer IDs must start with 'cus_' prefix."
            )

        # Validate maximum length (Stripe IDs are typically under 255 characters)
        if len(stripe_customer_id) > 255:
            raise PaymentException(
                f"Invalid Stripe customer ID format: '{stripe_customer_id}'. "
                "Stripe customer IDs must be 255 characters or less."
            )

        return stripe_customer_id, user_id

    async def _get_cached_customer(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get cached Stripe customer data."""
        if not self.cache_service:
            return None
            
        cache_key = self._make_cache_key("customer", user_id)
        return await self.cache_service.get(cache_key, cache_type='payment')

    async def _cache_customer(self, user_id: int, customer_data: Dict[str, Any], ttl: int = 3600):
        """Cache Stripe customer data."""
        if not self.cache_service:
            return
            
        cache_key = self._make_cache_key("customer", user_id)
        await self.cache_service.set(cache_key, customer_data, ttl, cache_type='payment')

    async def create_stripe_customer(self, user: User) -> str:
        """
        Create a Stripe customer for the user.

        Args:
            user: User instance to create customer for

        Returns:
            Stripe customer ID

        Raises:
            PaymentException: If customer creation fails
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        # Check if user already has a Stripe customer ID
        if user.stripe_customer_id:
            log.debug(f"User {user.id} already has Stripe customer ID: {user.stripe_customer_id}")
            return user.stripe_customer_id

        try:
            # Create Stripe customer
            customer = stripe.Customer.create(
                email=user.email,
                name=user.username or f"User {user.id}",
                metadata={
                    "user_id": str(user.id),
                    "username": user.username or "",
                }
            )

            # Cache customer data
            await self._cache_customer(user.id, {
                "id": customer.id,
                "email": customer.email,
                "name": customer.name,
                "created": customer.created
            })

            log.info(f"Created Stripe customer {customer.id} for user {user.id}")
            return customer.id

        except StripeError as e:
            log.error(f"Failed to create Stripe customer for user {user.id}: {e}")
            raise PaymentException(f"Failed to create customer: {str(e)}")

    async def create_subscription(
        self,
        customer: Union[User, str],
        price_id: str,
    ) -> Dict[str, Any]:
        """
        Create a subscription for a Stripe customer.

        Args:
            customer: User instance or Stripe customer ID string to create subscription for
            price_id: Stripe price ID for the subscription

        Returns:
            Dictionary containing subscription data

        Raises:
            PaymentException: If subscription creation fails or customer ID is invalid
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        # Normalize customer to stripe_customer_id
        customer_id, user_id = self._normalize_customer_id(customer)

        try:
            # Create subscription
            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                payment_behavior="default_incomplete",
                payment_settings={"save_default_payment_method": "on_subscription"},
                expand=["latest_invoice.payment_intent"],
            )

            subscription_data = {
                "id": subscription.id,
                "customer": subscription.customer,
                "status": subscription.status,
                "current_period_start": datetime.fromtimestamp(subscription.current_period_start),
                "current_period_end": datetime.fromtimestamp(subscription.current_period_end),
                "price_id": price_id,
            }

            log_context = f" (user {user_id})" if user_id is not None else ""
            log.info(
                f"Created subscription {subscription.id} for customer {customer_id}" + log_context
            )
            return subscription_data

        except CardError as e:
            log_context = f" (user {user_id})" if user_id is not None else ""
            log.error(f"Card error creating subscription for customer {customer_id}" + log_context + f": {e}")
            # Map specific card errors to appropriate exceptions
            error_code = getattr(e, 'code', None)
            decline_code = getattr(e, 'decline_code', None)

            # Check decline_code first (more specific than error_code)
            if decline_code and decline_code in self.STRIPE_DECLINE_CODE_MAP:
                exception_class, message = self.STRIPE_DECLINE_CODE_MAP[decline_code]
                raise exception_class(f"{message}: {str(e)}")

            # Fallback to error_code check for insufficient_funds
            if error_code == 'insufficient_funds':
                raise InsufficientFundsException(f"Insufficient funds: {str(e)}")

            # Generic card error with decline code for tracking
            decline_info = f" (decline_code: {decline_code})" if decline_code else f" (error_code: {error_code})" if error_code else ""
            raise PaymentException(f"Card error{decline_info}: {str(e)}")
        except StripeError as e:
            log_context = f" (user {user_id})" if user_id is not None else ""
            log.error(f"Failed to create subscription for customer {customer_id}" + log_context + f": {e}")
            raise PaymentException(f"Failed to create subscription: {str(e)}")

    async def cancel_subscription(self, subscription_id: str) -> bool:
        """
        Cancel a subscription.

        Args:
            subscription_id: Stripe subscription ID to cancel

        Returns:
            True if cancellation was successful

        Raises:
            PaymentException: If cancellation fails
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        try:
            # Cancel subscription at period end
            subscription = stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=True
            )

            log.info(f"Cancelled subscription {subscription_id}")
            return True

        except StripeError as e:
            log.error(f"Failed to cancel subscription {subscription_id}: {e}")
            raise PaymentException(f"Failed to cancel subscription: {str(e)}")

    async def create_checkout_session(
        self,
        customer: Union[User, str],
        price_id: str,
        success_url: str,
        cancel_url: str,
        trial_period_days: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Create a Stripe checkout session for subscription payment.

        Args:
            customer: User instance or Stripe customer ID string creating the checkout
            price_id: Stripe price ID for the subscription
            success_url: URL to redirect to on successful payment
            cancel_url: URL to redirect to on cancelled payment
            trial_period_days: Optional trial period length in days

        Returns:
            Dictionary containing checkout session data

        Raises:
            PaymentException: If checkout session creation fails or customer ID is invalid
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        # Normalize customer to stripe_customer_id
        customer_id, user_id = self._normalize_customer_id(customer)

        try:
            # Create checkout session
            session_params = {
                "payment_method_types": ["card"],
                "line_items": [{"price": price_id, "quantity": 1}],
                "mode": "subscription",
                "success_url": success_url,
                "cancel_url": cancel_url,
                "customer": customer_id,
            }

            # Include user_id in metadata only when available
            metadata = {"user_id": str(user_id)} if user_id is not None else {}
            if metadata:
                session_params["metadata"] = metadata

            if trial_period_days is not None:
                session_params["subscription_data"] = {"trial_period_days": trial_period_days}

            session = stripe.checkout.Session.create(**session_params)

            session_data = {
                "id": session.id,
                "url": session.url,
                "payment_status": session.payment_status,
            }

            log_context = f" (user {user_id})" if user_id is not None else ""
            log.info(f"Created checkout session {session.id} for customer {customer_id}" + log_context)
            return session_data

        except StripeError as e:
            log_context = f" (user {user_id})" if user_id is not None else ""
            log.error(f"Failed to create checkout session for customer {customer_id}" + log_context + f": {e}")
            raise PaymentException(f"Failed to create checkout session: {str(e)}")

    async def process_refund(
        self, 
        payment_intent_id: str, 
        amount: Optional[int] = None,
        reason: str = "requested_by_customer",
        admin_user_id: Optional[int] = None,
        admin_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a refund for a payment with comprehensive tracking.

        Args:
            payment_intent_id: Stripe payment intent ID to refund
            amount: Optional amount to refund in cents (None for full refund)
            reason: Reason for the refund (for audit purposes)
            admin_user_id: ID of admin user initiating refund (if applicable)
            admin_notes: Administrative notes about the refund

        Returns:
            Dictionary containing refund data

        Raises:
            PaymentException: If refund processing fails
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        try:
            # Create refund in Stripe
            refund_params = {"payment_intent": payment_intent_id}
            if amount is not None:
                refund_params["amount"] = amount
            
            # Add metadata for tracking
            refund_params["metadata"] = {
                "reason": reason,
                "admin_user_id": str(admin_user_id) if admin_user_id else "",
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }

            refund = stripe.Refund.create(**refund_params)

            refund_data = {
                "id": refund.id,
                "amount": refund.amount,
                "currency": refund.currency,
                "status": refund.status,
                "payment_intent": refund.payment_intent,
                "charge": refund.charge,
                "reason": refund.reason,
                "receipt_number": refund.receipt_number,
                "created": refund.created,
                "metadata": refund.metadata,
                "admin_user_id": admin_user_id,
                "admin_notes": admin_notes,
            }

            log.info(f"Processed refund {refund.id} for payment intent {payment_intent_id} (amount: {refund.amount}, reason: {reason})")
            return refund_data

        except StripeError as e:
            log.error(f"Failed to process refund for payment intent {payment_intent_id}: {e}")
            raise PaymentException(f"Failed to process refund: {str(e)}")

    async def get_refund_status(self, refund_id: str) -> Dict[str, Any]:
        """
        Get the current status of a refund from Stripe.

        Args:
            refund_id: Stripe refund ID to check

        Returns:
            Dictionary containing refund status data

        Raises:
            PaymentException: If status retrieval fails
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        try:
            refund = stripe.Refund.retrieve(refund_id)

            status_data = {
                "id": refund.id,
                "amount": refund.amount,
                "currency": refund.currency,
                "status": refund.status,
                "payment_intent": refund.payment_intent,
                "charge": refund.charge,
                "reason": refund.reason,
                "receipt_number": refund.receipt_number,
                "created": refund.created,
                "metadata": refund.metadata,
                "failure_reason": getattr(refund, 'failure_reason', None),
            }

            return status_data

        except StripeError as e:
            log.error(f"Failed to get refund status for {refund_id}: {e}")
            raise PaymentException(f"Failed to get refund status: {str(e)}")

    async def list_refunds_for_payment(self, payment_intent_id: str) -> List[Dict[str, Any]]:
        """
        List all refunds for a specific payment intent.

        Args:
            payment_intent_id: Stripe payment intent ID

        Returns:
            List of refund dictionaries

        Raises:
            PaymentException: If listing fails
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        try:
            refunds = stripe.Refund.list(payment_intent=payment_intent_id)

            refunds_data = []
            for refund in refunds.data:
                refunds_data.append({
                    "id": refund.id,
                    "amount": refund.amount,
                    "currency": refund.currency,
                    "status": refund.status,
                    "payment_intent": refund.payment_intent,
                    "charge": refund.charge,
                    "reason": refund.reason,
                    "receipt_number": refund.receipt_number,
                    "created": refund.created,
                    "metadata": refund.metadata,
                })

            return refunds_data

        except StripeError as e:
            log.error(f"Failed to list refunds for payment intent {payment_intent_id}: {e}")
            raise PaymentException(f"Failed to list refunds: {str(e)}")

    async def cancel_refund(self, refund_id: str, admin_user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Cancel a pending refund (only possible for certain refund types).

        Args:
            refund_id: Stripe refund ID to cancel
            admin_user_id: ID of admin user canceling refund

        Returns:
            Dictionary containing updated refund data

        Raises:
            PaymentException: If cancellation fails
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        try:
            # Cancel refund in Stripe
            refund = stripe.Refund.cancel(refund_id)

            refund_data = {
                "id": refund.id,
                "amount": refund.amount,
                "currency": refund.currency,
                "status": refund.status,
                "payment_intent": refund.payment_intent,
                "charge": refund.charge,
                "reason": refund.reason,
                "created": refund.created,
                "metadata": refund.metadata,
                "canceled_by_admin": admin_user_id,
            }

            log.info(f"Canceled refund {refund_id} by admin user {admin_user_id}")
            return refund_data

        except StripeError as e:
            log.error(f"Failed to cancel refund {refund_id}: {e}")
            raise PaymentException(f"Failed to cancel refund: {str(e)}")

    async def sync_subscription_from_stripe(self, stripe_subscription_id: str) -> Optional[Dict[str, Any]]:
        """
        Sync subscription data from Stripe.

        Args:
            stripe_subscription_id: Stripe subscription ID to sync

        Returns:
            Dictionary containing updated subscription data or None if not found

        Raises:
            PaymentException: If sync fails
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        try:
            # Retrieve subscription from Stripe
            subscription = stripe.Subscription.retrieve(stripe_subscription_id)

            subscription_data = {
                "id": subscription.id,
                "customer": subscription.customer,
                "status": subscription.status,
                "current_period_start": datetime.fromtimestamp(subscription.current_period_start),
                "current_period_end": datetime.fromtimestamp(subscription.current_period_end),
                "cancel_at_period_end": subscription.cancel_at_period_end,
                "items": [
                    {
                        "price_id": item.price.id,
                        "quantity": item.quantity,
                    }
                    for item in subscription.items.data
                ],
            }

            log.debug(f"Synced subscription {stripe_subscription_id} from Stripe")
            return subscription_data

        except stripe.error.InvalidRequestError:
            log.warning(f"Subscription {stripe_subscription_id} not found in Stripe")
            return None
        except StripeError as e:
            log.error(f"Failed to sync subscription {stripe_subscription_id}: {e}")
            raise PaymentException(f"Failed to sync subscription: {str(e)}")

    async def get_customer_payment_methods(self, customer_id: str) -> List[Dict[str, Any]]:
        """
        Get payment methods for a customer.

        Args:
            customer_id: Stripe customer ID

        Returns:
            List of payment method dictionaries

        Raises:
            PaymentException: If retrieval fails
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        try:
            # List payment methods
            payment_methods = stripe.PaymentMethod.list(
                customer=customer_id,
                type="card"
            )

            methods_data = []
            for pm in payment_methods.data:
                methods_data.append({
                    "id": pm.id,
                    "type": pm.type,
                    "card": {
                        "brand": pm.card.brand,
                        "last4": pm.card.last4,
                        "exp_month": pm.card.exp_month,
                        "exp_year": pm.card.exp_year,
                    } if pm.card else None,
                })

            return methods_data

        except StripeError as e:
            log.error(f"Failed to get payment methods for customer {customer_id}: {e}")
            raise PaymentException(f"Failed to get payment methods: {str(e)}")

    def is_payments_enabled(self) -> bool:
        """Check if payments are enabled and configured."""
        return self._payments_enabled and self._stripe_configured

    def get_webhook_secret(self) -> Optional[str]:
        """Get Stripe webhook secret for signature validation."""
        webhook_secret = getattr(self.settings, 'stripe_webhook_secret', None)
        if webhook_secret:
            return webhook_secret.get_secret_value()
        return None

    async def construct_webhook_event(self, payload: bytes, signature_header: str) -> Dict[str, Any]:
        """
        Construct and validate Stripe webhook event from payload and signature.

        Args:
            payload: Raw webhook payload bytes
            signature_header: Stripe signature header value

        Returns:
            Dictionary containing the validated webhook event

        Raises:
            PaymentException: If webhook validation fails
            ValueError: If payload is invalid
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        if stripe is None:
            raise PaymentException("Stripe library not available")

        webhook_secret = self.get_webhook_secret()
        if not webhook_secret:
            raise PaymentException("Webhook secret not configured")

        try:
            # Use Stripe's webhook signature validation
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=signature_header,
                secret=webhook_secret
            )
            
            log.debug(f"Successfully validated webhook event: {event.get('type', 'unknown')}")
            return event

        except ValueError as e:
            log.warning(f"Invalid webhook payload: {e}")
            raise ValueError(f"Invalid payload: {str(e)}")
        except (StripeError, Exception) as e:
            if "SignatureVerificationError" in str(type(e)):
                log.warning(f"Invalid webhook signature: {e}")
                raise PaymentException(f"Invalid signature: {str(e)}")
            else:
                log.error(f"Unexpected error validating webhook: {e}")
                raise PaymentException(f"Webhook validation failed: {str(e)}")

    async def handle_subscription_cancelled(self, subscription_id: str) -> None:
        """
        Handle subscription cancellation from webhook.

        Args:
            subscription_id: Stripe subscription ID that was cancelled
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        try:
            # In a real implementation, this would update the database
            # to mark the subscription as cancelled
            log.info(f"Handling subscription cancellation: {subscription_id}")
            
            # Update subscription status in database
            # This would typically involve:
            # 1. Finding the subscription record
            # 2. Updating status to cancelled
            # 3. Setting cancellation date
            # 4. Clearing cache
            
        except Exception as e:
            log.error(f"Failed to handle subscription cancellation {subscription_id}: {e}")
            raise PaymentException(f"Failed to handle cancellation: {str(e)}")

    async def record_successful_payment(self, invoice_data: Dict[str, Any]) -> None:
        """
        Record successful payment from webhook.

        Args:
            invoice_data: Stripe invoice data from webhook
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        try:
            log.info(f"Recording successful payment for invoice: {invoice_data.get('id')}")
            
            # In a real implementation, this would:
            # 1. Create PaymentRecord in database
            # 2. Update subscription status if needed
            # 3. Send confirmation email
            # 4. Update usage quotas
            
        except Exception as e:
            log.error(f"Failed to record successful payment: {e}")
            raise PaymentException(f"Failed to record payment: {str(e)}")

    async def record_failed_payment(self, invoice_data: Dict[str, Any]) -> None:
        """
        Record failed payment from webhook.

        Args:
            invoice_data: Stripe invoice data from webhook
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        try:
            log.info(f"Recording failed payment for invoice: {invoice_data.get('id')}")
            
            # In a real implementation, this would:
            # 1. Create PaymentRecord with failed status
            # 2. Trigger grace period if applicable
            # 3. Send payment failure notification
            # 4. Update subscription status if needed
            
        except Exception as e:
            log.error(f"Failed to record failed payment: {e}")
            raise PaymentException(f"Failed to record payment failure: {str(e)}")

    async def handle_payment_failure(self, subscription_id: str, invoice_data: Dict[str, Any]) -> None:
        """
        Handle payment failure with grace period logic.

        Args:
            subscription_id: Stripe subscription ID with failed payment
            invoice_data: Stripe invoice data from webhook
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        try:
            log.info(f"Handling payment failure for subscription: {subscription_id}")
            
            # In a real implementation, this would:
            # 1. Check if user is in grace period
            # 2. Update subscription status to past_due
            # 3. Send payment failure notification
            # 4. Schedule account suspension if grace period expires
            
        except Exception as e:
            log.error(f"Failed to handle payment failure for {subscription_id}: {e}")
            raise PaymentException(f"Failed to handle payment failure: {str(e)}")

    async def get_dispute_details(self, dispute_id: str) -> Dict[str, Any]:
        """
        Get details of a dispute from Stripe.

        Args:
            dispute_id: Stripe dispute ID

        Returns:
            Dictionary containing dispute details

        Raises:
            PaymentException: If retrieval fails
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        try:
            dispute = stripe.Dispute.retrieve(dispute_id)

            dispute_data = {
                "id": dispute.id,
                "amount": dispute.amount,
                "currency": dispute.currency,
                "status": dispute.status,
                "reason": dispute.reason,
                "charge": dispute.charge,
                "created": dispute.created,
                "evidence_due_by": dispute.evidence_details.due_by if dispute.evidence_details else None,
                "evidence_submission_count": dispute.evidence_details.submission_count if dispute.evidence_details else 0,
                "evidence_has_evidence": dispute.evidence_details.has_evidence if dispute.evidence_details else False,
                "is_charge_refundable": dispute.is_charge_refundable,
                "livemode": dispute.livemode,
                "metadata": dispute.metadata,
                "network_reason_code": dispute.network_reason_code,
                "payment_intent": getattr(dispute, 'payment_intent', None),
            }

            return dispute_data

        except StripeError as e:
            log.error(f"Failed to get dispute details for {dispute_id}: {e}")
            raise PaymentException(f"Failed to get dispute details: {str(e)}")

    async def submit_dispute_evidence(
        self, 
        dispute_id: str, 
        evidence: Dict[str, Any],
        admin_user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Submit evidence for a dispute.

        Args:
            dispute_id: Stripe dispute ID
            evidence: Evidence dictionary (customer_communication, receipt, etc.)
            admin_user_id: ID of admin user submitting evidence

        Returns:
            Dictionary containing updated dispute data

        Raises:
            PaymentException: If evidence submission fails
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        try:
            # Submit evidence to Stripe
            dispute = stripe.Dispute.modify(
                dispute_id,
                evidence=evidence,
                metadata={
                    "evidence_submitted_by": str(admin_user_id) if admin_user_id else "",
                    "evidence_submitted_at": datetime.now(timezone.utc).isoformat(),
                }
            )

            dispute_data = {
                "id": dispute.id,
                "amount": dispute.amount,
                "currency": dispute.currency,
                "status": dispute.status,
                "reason": dispute.reason,
                "charge": dispute.charge,
                "evidence_due_by": dispute.evidence_details.due_by if dispute.evidence_details else None,
                "evidence_submission_count": dispute.evidence_details.submission_count if dispute.evidence_details else 0,
                "evidence_has_evidence": dispute.evidence_details.has_evidence if dispute.evidence_details else False,
                "metadata": dispute.metadata,
                "submitted_by_admin": admin_user_id,
            }

            log.info(f"Submitted evidence for dispute {dispute_id} by admin user {admin_user_id}")
            return dispute_data

        except StripeError as e:
            log.error(f"Failed to submit evidence for dispute {dispute_id}: {e}")
            raise PaymentException(f"Failed to submit dispute evidence: {str(e)}")

    async def close_dispute(self, dispute_id: str, admin_user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Close a dispute (accept the dispute).

        Args:
            dispute_id: Stripe dispute ID to close
            admin_user_id: ID of admin user closing dispute

        Returns:
            Dictionary containing updated dispute data

        Raises:
            PaymentException: If closing fails
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        try:
            # Close dispute in Stripe
            dispute = stripe.Dispute.close(dispute_id)

            dispute_data = {
                "id": dispute.id,
                "amount": dispute.amount,
                "currency": dispute.currency,
                "status": dispute.status,
                "reason": dispute.reason,
                "charge": dispute.charge,
                "created": dispute.created,
                "metadata": dispute.metadata,
                "closed_by_admin": admin_user_id,
            }

            log.info(f"Closed dispute {dispute_id} by admin user {admin_user_id}")
            return dispute_data

        except StripeError as e:
            log.error(f"Failed to close dispute {dispute_id}: {e}")
            raise PaymentException(f"Failed to close dispute: {str(e)}")

    async def list_disputes_for_customer(self, customer_id: str) -> List[Dict[str, Any]]:
        """
        List all disputes for a specific customer.

        Args:
            customer_id: Stripe customer ID

        Returns:
            List of dispute dictionaries

        Raises:
            PaymentException: If listing fails
        """
        if not self._payments_enabled or not self._stripe_configured:
            raise PaymentException("Payments are not enabled or configured")

        try:
            # Get charges for customer first, then disputes for those charges
            charges = stripe.Charge.list(customer=customer_id, limit=100)
            
            disputes_data = []
            for charge in charges.data:
                if charge.dispute:
                    dispute = charge.dispute
                    disputes_data.append({
                        "id": dispute.id,
                        "amount": dispute.amount,
                        "currency": dispute.currency,
                        "status": dispute.status,
                        "reason": dispute.reason,
                        "charge": dispute.charge,
                        "created": dispute.created,
                        "evidence_due_by": dispute.evidence_details.due_by if dispute.evidence_details else None,
                        "evidence_has_evidence": dispute.evidence_details.has_evidence if dispute.evidence_details else False,
                        "metadata": dispute.metadata,
                    })

            return disputes_data

        except StripeError as e:
            log.error(f"Failed to list disputes for customer {customer_id}: {e}")
            raise PaymentException(f"Failed to list disputes: {str(e)}")

    async def check_webhook_processed(self, event_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None) -> bool:
        """
        Atomically check if a webhook event has been processed using INSERT ... ON CONFLICT.

        This method uses a database-level atomic operation to ensure that duplicate
        webhook events are never processed twice, even under concurrent requests.

        Args:
            event_id: Stripe event ID (must be unique)
            event_type: Type of webhook event
            payload: Optional raw event payload for debugging

        Returns:
            True if this is the first time processing this event (event was inserted)
            False if the event was already processed (conflict detected)

        Raises:
            PaymentException: If database operation fails
        """
        from app.core.database import get_async_session
        from sqlalchemy import text
        import json

        try:
            async for session in get_async_session():
                # Use PostgreSQL INSERT ... ON CONFLICT DO NOTHING for atomic idempotency
                # This ensures that only ONE process can successfully insert a given event_id
                query = text("""
                    INSERT INTO webhook_events (event_id, event_type, payload, processed_at)
                    VALUES (:event_id, :event_type, :payload, NOW())
                    ON CONFLICT (event_id) DO NOTHING
                    RETURNING id
                """)

                result = await session.execute(
                    query,
                    {
                        "event_id": event_id,
                        "event_type": event_type,
                        "payload": json.dumps(payload) if payload else None
                    }
                )
                await session.commit()

                # If a row was returned, the insert succeeded (first time processing)
                # If no row was returned, there was a conflict (already processed)
                row = result.fetchone()
                was_inserted = row is not None

                if was_inserted:
                    log.info(f"Webhook event {event_id} ({event_type}) marked for processing (first time)")
                else:
                    log.warning(f"Webhook event {event_id} ({event_type}) already processed - skipping duplicate")

                return was_inserted

        except Exception as e:
            log.error(f"Failed to check webhook idempotency for event {event_id}: {e}")
            raise PaymentException(f"Webhook idempotency check failed: {str(e)}")

    async def mark_webhook_processed(self, event_id: str, event_type: str) -> None:
        """
        Legacy method for marking webhook as processed.

        NOTE: This method is kept for backwards compatibility but is NO LONGER NEEDED
        when using check_webhook_processed(), which atomically checks and marks in one operation.

        For new code, use check_webhook_processed() instead, which provides atomic
        idempotency checking with INSERT ... ON CONFLICT.

        Args:
            event_id: Stripe event ID
            event_type: Type of webhook event
        """
        log.debug(f"mark_webhook_processed called for {event_id} - this is a no-op when using check_webhook_processed()")
        # No-op: check_webhook_processed already marked the event
        pass
