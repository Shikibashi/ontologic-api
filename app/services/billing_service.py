
"""
Billing service for usage tracking and invoice generation.

Handles API usage tracking, billing history management, and usage analytics
with integration to existing database session management and logging.
"""

from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
from typing import Optional, Dict, Any, List, TYPE_CHECKING
from dataclasses import dataclass
from decimal import Decimal

from sqlmodel import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.logger import log
from app.core.db_models import UsageRecord, PaymentRecord, SubscriptionTier
from app.core.database import AsyncSessionLocal

if TYPE_CHECKING:
    from app.services.cache_service import RedisCacheService


@dataclass
class BillingPeriod:
    """Billing period information."""
    start_date: datetime
    end_date: datetime
    period_key: str  # YYYY-MM format


@dataclass
class BillingRecord:
    """Individual billing record."""
    id: Optional[int]
    user_id: int
    amount_cents: int
    currency: str
    description: str
    status: str
    created_at: datetime
    payment_intent_id: Optional[str] = None
    invoice_id: Optional[str] = None


@dataclass
class UsageStats:
    """Usage statistics for a billing period."""
    user_id: int
    period: str
    total_requests: int
    total_tokens: int
    endpoints_used: Dict[str, int]
    subscription_tier: SubscriptionTier = SubscriptionTier.FREE
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


@dataclass
class OverageCharges:
    """Overage charges calculation."""
    user_id: int
    period: str
    base_limit: int
    actual_usage: int
    overage_amount: int
    charge_per_unit: Decimal
    total_charge_cents: int
    
    @property
    def requests_overage(self) -> int:
        """Alias for overage_amount for backward compatibility."""
        return self.overage_amount
    
    @property
    def overage_amount_cents(self) -> int:
        """Alias for total_charge_cents for backward compatibility."""
        return self.total_charge_cents
    
    @property
    def has_overage(self) -> bool:
        """Check if there are any overage charges."""
        return self.overage_amount > 0


@dataclass
class Invoice:
    """Generated invoice data."""
    invoice_id: str
    user_id: int
    period: BillingPeriod
    line_items: List[Dict[str, Any]]
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    currency: str
    status: str
    created_at: datetime
    
    # Additional fields for backward compatibility
    base_amount_cents: Optional[int] = None
    total_amount_cents: Optional[int] = None
    usage_stats: Optional[Any] = None
    overage_charges: Optional[Any] = None
    generated_at: Optional[datetime] = None
    
    def __post_init__(self):
        """Set default values for backward compatibility."""
        if self.base_amount_cents is None:
            self.base_amount_cents = self.subtotal_cents
            if self.total_amount_cents is None:
                tax = self.tax_cents if self.tax_cents is not None else 0
                self.total_amount_cents = self.subtotal_cents + tax
        if self.generated_at is None:
            self.generated_at = self.created_at


class BillingService:
    """
    Billing service for usage tracking and invoice generation.

    Provides API usage tracking, billing history management, and usage analytics
    with integration to existing cache service and database session management.

    LIFECYCLE: This service should be initialized during application startup
    and stored in app.state for request-time access via dependency injection.
    """

    def __init__(self, cache_service: Optional['RedisCacheService'] = None):
        """
        Initialize BillingService with optional cache service.

        Args:
            cache_service: Optional RedisCacheService for caching billing data.
                          If None, operations will not be cached.
        """
        self.cache_service = cache_service
        self.settings = get_settings()
        
        # Billing configuration
        self._overage_rates = self._load_overage_rates()
        self._tax_rate = Decimal('0.08')  # 8% default tax rate
        
        # Degraded mode flag indicates initialization failures
        self.degraded_mode = False
        
        if cache_service is None:
            log.warning("BillingService initialized without cache_service - billing data will not be cached")

    async def _initialize(self):
        """
        Initialize the billing service with async operations.
        
        This method handles any async initialization that needs to be done
        after the service is created, such as database connections or
        external service validations.
        """
        self._initialized = False
        self._initialization_error = None
        try:
            # Test database connectivity
            async with AsyncSessionLocal() as session:
                # Simple query to test database connection
                await session.execute(select(1))
                log.info("BillingService database connection verified")
            # Initialize cache service if available
            if self.cache_service:
                # Test cache connectivity
                test_key = self._make_cache_key("test", "connection")
                await self.cache_service.set(test_key, {"status": "ok"}, 60, cache_type='billing')
                await self.cache_service.delete(test_key)
                log.info("BillingService cache connection verified")
            self._initialized = True
        except Exception as e:
            self._initialization_error = str(e)
            self.degraded_mode = True
            log.critical(f"BillingService initialization error: {e}")
            raise

    @classmethod
    async def start(cls, cache_service: Optional['RedisCacheService'] = None):
        """
        Async factory method for lifespan-managed initialization.

        Args:
            cache_service: Optional RedisCacheService instance

        Returns:
            Initialized BillingService instance
        """
        instance = cls(cache_service=cache_service)
        await instance._initialize()
        log.info("BillingService initialized for lifespan management")
        return instance

    def _load_overage_rates(self) -> Dict[SubscriptionTier, Decimal]:
        """Load overage rates for different subscription tiers."""
        return {
            SubscriptionTier.FREE: Decimal('0.01'),      # $0.01 per request over limit
            SubscriptionTier.BASIC: Decimal('0.01'),     # $0.01 per request over limit  
            SubscriptionTier.PREMIUM: Decimal('0.002'),  # $0.002 per request over limit
            SubscriptionTier.ACADEMIC: Decimal('0.003'), # $0.003 per request over limit
        }

    def _calculate_overage_pricing(self, overage_requests: int, subscription_tier: SubscriptionTier) -> int:
        """
        Calculate overage pricing in cents for a given number of overage requests.
        
        Args:
            overage_requests: Number of requests over the limit
            subscription_tier: User's subscription tier
            
        Returns:
            Total overage cost in cents
        """
        rate_per_request = self._overage_rates.get(subscription_tier, Decimal('0.01'))
        return int(overage_requests * rate_per_request * 100)

    def _make_cache_key(self, prefix: str, *args) -> str:
        """Generate cache key for billing data."""
        if not self.cache_service:
            return ""
        return self.cache_service._make_cache_key(f"billing:{prefix}", *args)

    def _get_current_billing_period(self) -> BillingPeriod:
        """Get current billing period (monthly)."""
        now = datetime.now(timezone.utc)
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Calculate next month's first day
        if now.month == 12:
            end_date = start_date.replace(year=now.year + 1, month=1)
        else:
            end_date = start_date.replace(month=now.month + 1)
        
        period_key = start_date.strftime("%Y-%m")
        
        return BillingPeriod(
            start_date=start_date,
            end_date=end_date,
            period_key=period_key
        )

    def _get_billing_period(self, year: int, month: int) -> BillingPeriod:
        """Get billing period for specific year and month."""
        start_date = datetime(year, month, 1)
        
        # Calculate next month's first day
        if month == 12:
            end_date = datetime(year + 1, 1, 1)
        else:
            end_date = datetime(year, month + 1, 1)
        
        period_key = start_date.strftime("%Y-%m")
        
        return BillingPeriod(
            start_date=start_date,
            end_date=end_date,
            period_key=period_key
        )

    async def track_api_usage(
        self,
        user_id: int,
        endpoint: str,
        tokens_used: int,
        method: str = "POST",
        request_duration_ms: Optional[int] = None,
        subscription_tier: SubscriptionTier = SubscriptionTier.FREE
    ) -> None:
        """
        Track API usage for billing purposes.

        Args:
            user_id: User ID making the request
            endpoint: API endpoint being accessed
            tokens_used: Number of tokens used in the request
            method: HTTP method used
            request_duration_ms: Request duration in milliseconds
            subscription_tier: User's current subscription tier
        """
        if getattr(self, "degraded_mode", False):
            log.warning("BillingService in degraded_mode - skipping usage tracking")
            return
        # Input validation
        if tokens_used < 0:
            raise ValueError("Tokens used cannot be negative")
        if user_id <= 0:
            raise ValueError("User ID must be positive")
        if not endpoint:
            raise ValueError("Endpoint cannot be empty")
            
        current_period = self._get_current_billing_period()

        # Create usage record in database
        async with AsyncSessionLocal() as session:
            try:
                usage_record = UsageRecord(
                    user_id=user_id,
                    endpoint=endpoint,
                    method=method,
                    tokens_used=tokens_used,
                    request_duration_ms=request_duration_ms,
                    billing_period=current_period.period_key,
                    subscription_tier=subscription_tier,
                    timestamp=datetime.now(timezone.utc)
                )
                session.add(usage_record)
                await session.commit()
                log.debug(f"Tracked API usage in database for user {user_id}: {endpoint} ({tokens_used} tokens)")
            except Exception as e:
                log.error(
                    f"Failed to track usage for user {user_id}, endpoint {endpoint}: {e}",
                    exc_info=True,
                    extra={
                        "user_id": user_id,
                        "endpoint": endpoint,
                        "tokens_used": tokens_used,
                        "period": current_period.period_key
                    }
                )
                await session.rollback()

                # Record failure metric for monitoring
                try:
                    from app.core.metrics import chat_monitoring
                    chat_monitoring.record_counter(
                        "usage_tracking_failures",
                        {"user_id": str(user_id), "endpoint": endpoint}
                    )
                except Exception:
                    pass  # Don't fail if metrics recording fails

                # Send monitoring alert
                try:
                    from app.core.alerting import notify_billing_failure
                    notify_billing_failure(
                        "usage_tracking",
                        user_id=user_id,
                        endpoint=endpoint,
                        period=current_period.period_key,
                        tokens_used=tokens_used
                    )
                except Exception:
                    pass  # Don't fail if alerting fails

                # Enqueue for durable retry
                try:
                    from app.core.retry_queue import enqueue_billing_usage_retry
                    payload_dict = {
                        "user_id": user_id,
                        "endpoint": endpoint,
                        "tokens_used": tokens_used,
                        "method": method,
                        "request_duration_ms": request_duration_ms,
                        "period": current_period.period_key,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    enqueue_billing_usage_retry(payload_dict)
                except Exception:
                    pass  # Don't fail if retry queue fails

                # Don't re-raise to allow the application to continue

        # Invalidate cache to ensure fresh data on next read
        if self.cache_service:
            cache_key = self._make_cache_key("usage", user_id, current_period.period_key)
            await self.cache_service.delete(cache_key)

    async def verify_invoice_ownership(self, user_id: int, invoice_id: str) -> bool:
        """
        Verify that a user owns a specific invoice.

        Args:
            user_id: User ID to verify ownership for
            invoice_id: Invoice ID to verify

        Returns:
            True if user owns the invoice, False otherwise
        """
        try:
            # In a real implementation, this would query the database
            # to verify that the invoice belongs to the user
            
            # For now, we'll do a simple check based on invoice ID format
            # Real implementation would use proper database query
            if f"_{user_id}_" in invoice_id:
                log.debug(f"Verified invoice ownership: user {user_id} owns {invoice_id}")
                return True
            else:
                log.warning(f"Invoice ownership verification failed: user {user_id} does not own {invoice_id}")
                return False
                
        except Exception as e:
            log.error(f"Error verifying invoice ownership for user {user_id}, invoice {invoice_id}: {e}")
            return False

    async def generate_invoice_download_url(self, invoice_id: str) -> Dict[str, Any]:
        """
        Generate a temporary download URL for an invoice PDF.

        Args:
            invoice_id: Invoice ID to generate download URL for

        Returns:
            Dictionary containing download URL and expiration info
        """
        try:
            # In a real implementation, this would:
            # 1. Generate or retrieve the invoice PDF
            # 2. Create a signed URL with expiration
            # 3. Return the temporary URL
            
            # For now, we'll return a mock URL structure
            expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
            
            download_info = {
                "url": f"https://api.example.com/invoices/{invoice_id}/download?token=temp_token",
                "expires_at": expires_at,
                "content_type": "application/pdf",
                "filename": f"invoice_{invoice_id}.pdf"
            }
            
            log.info(f"Generated invoice download URL for {invoice_id}")
            return download_info
            
        except Exception as e:
            log.error(f"Error generating invoice download URL for {invoice_id}: {e}")
            raise Exception(f"Failed to generate download URL: {str(e)}")

    async def get_usage_stats(self, user_id: int, period: str) -> UsageStats:
        """
        Get usage statistics for a user in a specific period.

        Args:
            user_id: User ID to get stats for
            period: Period to get stats for ("current" or YYYY-MM format)

        Returns:
            UsageStats object with usage information
        """
        try:
            # Determine the actual period
            if period == "current":
                current_date = datetime.now(timezone.utc)
                period_key = current_date.strftime("%Y-%m")
            else:
                period_key = period
                # Validate period format
                if period_key != "current":
                    try:
                        year, month = map(int, period_key.split('-'))
                        if not (1 <= month <= 12) or year < 2000 or year > 2100:
                            raise ValueError("Invalid billing period format")
                    except (ValueError, AttributeError):
                        raise ValueError("Invalid billing period format")

            # Try to get from cache first
            if self.cache_service:
                cache_key = self._make_cache_key("usage", user_id, period_key)
                cached_stats = await self.cache_service.get(cache_key, cache_type='billing')

                if cached_stats:
                    return UsageStats(
                        user_id=user_id,
                        period=period_key,
                        total_requests=cached_stats.get("total_requests", 0),
                        total_tokens=cached_stats.get("total_tokens", 0),
                        endpoints_used=cached_stats.get("endpoints", {}),
                        subscription_tier=cached_stats.get("subscription_tier", SubscriptionTier.FREE)
                    )

            # Query from database
            async with AsyncSessionLocal() as session:
                stmt = select(UsageRecord).where(
                    UsageRecord.user_id == user_id,
                    UsageRecord.billing_period == period_key
                )
                result = await session.execute(stmt)
                records = list(result.scalars().all())

                # Parse period to get dates
                year, month = map(int, period_key.split('-'))
                billing_period = self._get_billing_period(year, month)

                if not records:
                    return UsageStats(
                        user_id=user_id,
                        period=period_key,
                        total_requests=0,
                        total_tokens=0,
                        endpoints_used={},
                        subscription_tier=SubscriptionTier.FREE,
                        period_start=billing_period.start_date,
                        period_end=billing_period.end_date
                    )

                # Aggregate statistics
                total_requests = len(records)
                total_tokens = sum(r.tokens_used for r in records)
                endpoints = {}
                subscription_tier = records[0].subscription_tier if records else SubscriptionTier.FREE

                for record in records:
                    endpoint = record.endpoint
                    endpoints[endpoint] = endpoints.get(endpoint, 0) + 1

                stats = UsageStats(
                    user_id=user_id,
                    period=period_key,
                    total_requests=total_requests,
                    total_tokens=total_tokens,
                    endpoints_used=endpoints,
                    subscription_tier=subscription_tier,
                    period_start=billing_period.start_date,
                    period_end=billing_period.end_date
                )

                # Cache the results
                if self.cache_service:
                    cache_data = {
                        "total_requests": total_requests,
                        "total_tokens": total_tokens,
                        "endpoints": endpoints,
                        "subscription_tier": subscription_tier
                    }
                    await self.cache_service.set(cache_key, cache_data, 3600, cache_type='billing')

                return stats

        except Exception as e:
            log.error(f"Error getting usage stats for user {user_id}, period {period}: {e}")
            # Return empty stats on error
            return UsageStats(
                user_id=user_id,
                period=period,
                total_requests=0,
                total_tokens=0,
                endpoints_used={},
                subscription_tier=SubscriptionTier.FREE
            )



    async def generate_invoice(self, user_id: int, period: BillingPeriod) -> Invoice:
        """
        Generate invoice for a user's usage in a billing period.

        Args:
            user_id: User ID to generate invoice for
            period: Billing period to generate invoice for

        Returns:
            Generated Invoice object
        """
        # Get usage stats for the period
        usage_stats = await self.get_usage_stats(user_id, period.period_key)
        
        # Calculate charges
        overage_charges = await self.calculate_overage_charges(user_id, usage_stats.subscription_tier)
        
        # Build line items
        line_items = []
        subtotal_cents = 0

        # Base subscription (if any)
        # This would typically come from the subscription data
        base_subscription_cents = 0  # Free tier has no base cost
        if base_subscription_cents > 0:
            line_items.append({
                "description": f"Subscription - {usage_stats.subscription_tier.value.title()}",
                "quantity": 1,
                "unit_price_cents": base_subscription_cents,
                "total_cents": base_subscription_cents
            })
            subtotal_cents += base_subscription_cents

        # Overage charges
        if overage_charges.total_charge_cents > 0:
            line_items.append({
                "description": f"Overage charges ({overage_charges.overage_amount} requests over limit)",
                "quantity": overage_charges.overage_amount,
                "unit_price_cents": int(overage_charges.charge_per_unit * 100),
                "total_cents": overage_charges.total_charge_cents
            })
            subtotal_cents += overage_charges.total_charge_cents

        # Calculate tax
        tax_cents = int(subtotal_cents * self._tax_rate)
        total_cents = subtotal_cents + tax_cents

        # Generate invoice ID
        invoice_id = f"inv_{user_id}_{period.period_key}_{int(datetime.now(timezone.utc).timestamp())}"

        invoice = Invoice(
            invoice_id=invoice_id,
            user_id=user_id,
            period=period,
            line_items=line_items,
            subtotal_cents=subtotal_cents,
            tax_cents=tax_cents,
            total_cents=total_cents,
            currency="usd",
            status="generated",
            created_at=datetime.now(timezone.utc)
        )

        log.info(f"Generated invoice {invoice_id} for user {user_id} (${total_cents/100:.2f})")
        return invoice

    async def get_billing_history(
        self, 
        user_id: int, 
        limit: int = 50, 
        offset: int = 0,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[BillingRecord]:
        """
        Get billing history for a user with optional date filtering.

        Args:
            user_id: User ID to get history for
            limit: Maximum number of records to return
            offset: Number of records to skip
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            List of BillingRecord objects
        """
        # In a real implementation, this would query the PaymentRecord table
        # For now, we'll return mock data
        
        # Check cache first (only if no date filters)
        if self.cache_service and start_date is None and end_date is None:
            cache_key = self._make_cache_key("history", user_id, limit, offset)
            cached_history = await self.cache_service.get(cache_key, cache_type='billing')
            if cached_history:
                log.debug(f"Retrieved cached billing history for user {user_id}")
                # Handle both dict and BillingRecord objects in cache
                result = []
                for record in cached_history[:limit]:
                    if isinstance(record, dict):
                        result.append(BillingRecord(**record))
                    else:
                        result.append(record)
                return result

        # Mock billing history - replace with actual database query
        mock_records = []
        total_records = 5  # Mock total available records
        
        # Apply offset and limit
        start_idx = offset
        end_idx = min(offset + limit, total_records)
        
        for i in range(start_idx, end_idx):
            record_date = datetime.now(timezone.utc) - timedelta(days=30 * i)
            
            # Apply date filters if provided
            if start_date:
                # Ensure both datetimes have the same timezone info for comparison
                start_compare = start_date.replace(tzinfo=timezone.utc) if start_date.tzinfo is None else start_date
                if record_date < start_compare:
                    continue
            if end_date:
                # Ensure both datetimes have the same timezone info for comparison
                end_compare = end_date.replace(tzinfo=timezone.utc) if end_date.tzinfo is None else end_date
                if record_date > end_compare:
                    continue
                
            record = BillingRecord(
                id=i + 1,
                user_id=user_id,
                amount_cents=1000 + (i * 500),  # $10.00, $15.00, etc.
                currency="usd",
                description=f"Monthly subscription - {record_date.strftime('%B %Y')}",
                status="succeeded",
                created_at=record_date,
                payment_intent_id=f"pi_mock_{user_id}_{i}",
                invoice_id=f"inv_mock_{user_id}_{i}"
            )
            mock_records.append(record)

        # Cache the results (only if no date filters)
        if self.cache_service and start_date is None and end_date is None:
            cache_data = [
                {
                    "id": record.id,
                    "user_id": record.user_id,
                    "amount_cents": record.amount_cents,
                    "currency": record.currency,
                    "description": record.description,
                    "status": record.status,
                    "created_at": record.created_at,
                    "payment_intent_id": record.payment_intent_id,
                    "invoice_id": record.invoice_id
                }
                for record in mock_records
            ]
            await self.cache_service.set(cache_key, cache_data, 1800, cache_type='billing')  # 30 minutes

        log.debug(f"Retrieved billing history for user {user_id} ({len(mock_records)} records)")
        return mock_records

    async def calculate_overage_charges(self, user_id: int, subscription_tier: SubscriptionTier) -> OverageCharges:
        """
        Calculate overage charges for a user with a specific subscription tier.

        Args:
            user_id: User ID to calculate charges for
            subscription_tier: User's subscription tier

        Returns:
            OverageCharges object with calculation details
        """
        # Get current period usage stats
        current_period = self._get_current_billing_period()
        usage_stats = await self.get_usage_stats(user_id, current_period.period_key)
        
        # Get tier limits
        tier_limits = {
            SubscriptionTier.FREE: 1000,
            SubscriptionTier.BASIC: 10000,
            SubscriptionTier.PREMIUM: 100000,
            SubscriptionTier.ACADEMIC: 50000,
        }
        
        base_limit = tier_limits.get(subscription_tier, 1000)
        overage_amount = max(0, usage_stats.total_requests - base_limit)
        
        charge_per_unit = self._overage_rates.get(subscription_tier, Decimal('0.01'))
        total_charge_cents = int(overage_amount * charge_per_unit * 100)

        return OverageCharges(
            user_id=user_id,
            period=current_period.period_key,
            base_limit=base_limit,
            actual_usage=usage_stats.total_requests,
            overage_amount=overage_amount,
            charge_per_unit=charge_per_unit,
            total_charge_cents=total_charge_cents
        )

    async def get_usage_analytics(
        self, 
        user_id: int, 
        period_type: str = "range",
        start_date: Optional[datetime] = None, 
        end_date: Optional[datetime] = None,
        months: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get usage analytics for a user over a date range or number of months.

        Args:
            user_id: User ID to get analytics for
            period_type: Type of period analysis ("range", "monthly")
            start_date: Start date for analytics (for range type)
            end_date: End date for analytics (for range type)
            months: Number of months to analyze (for monthly type)

        Returns:
            Dictionary containing usage analytics
        """
        # Generate list of periods based on type
        periods = []
        
        if period_type == "monthly" and months:
            # Generate periods for the last N months
            current_date = datetime.now(timezone.utc)
            for i in range(months):
                period_date = current_date - relativedelta(months=i)
                period_key = period_date.strftime("%Y-%m")
                periods.append(period_key)
        elif start_date and end_date:
            # Generate periods for date range
            current_date = start_date.replace(day=1)
            
            while current_date <= end_date:
                period_key = current_date.strftime("%Y-%m")
                periods.append(period_key)
                
                # Move to next month
                if current_date.month == 12:
                    current_date = current_date.replace(year=current_date.year + 1, month=1)
                else:
                    current_date = current_date.replace(month=current_date.month + 1)
        else:
            # Default to current month
            current_date = datetime.now(timezone.utc)
            periods = [current_date.strftime("%Y-%m")]

        # Collect usage stats for all periods
        total_requests = 0
        total_tokens = 0
        endpoint_breakdown = {}
        monthly_usage = []

        for period in periods:
            stats = await self.get_usage_stats(user_id, period)
            total_requests += stats.total_requests
            total_tokens += stats.total_tokens
            
            # Aggregate endpoint usage
            for endpoint, count in stats.endpoints_used.items():
                if endpoint not in endpoint_breakdown:
                    endpoint_breakdown[endpoint] = 0
                endpoint_breakdown[endpoint] += count
            
            monthly_usage.append({
                "period": period,
                "requests": stats.total_requests,
                "tokens": stats.total_tokens
            })

        analytics = {
            "user_id": user_id,
            "period_type": period_type,
            "summary": {
                "total_requests": total_requests,
                "total_tokens": total_tokens,
                "average_requests_per_month": total_requests / len(periods) if periods else 0,
                "average_tokens_per_request": total_tokens / total_requests if total_requests > 0 else 0
            },
            "endpoint_breakdown": endpoint_breakdown,
            "monthly_usage": monthly_usage,
            "periods_analyzed": len(periods)
        }
        
        # Add date range if provided
        if start_date and end_date:
            analytics["date_range"] = {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            }

        log.debug(f"Generated usage analytics for user {user_id} ({len(periods)} periods)")
        return analytics

    async def export_usage_data(
        self, 
        user_id: int, 
        start_date: datetime, 
        end_date: datetime,
        format: str = "json"
    ) -> Dict[str, Any]:
        """
        Export detailed usage data for a user.

        Args:
            user_id: User ID to export data for
            start_date: Start date for export
            end_date: End date for export
            format: Export format (json, csv)

        Returns:
            Dictionary containing exported data
        """
        analytics = await self.get_usage_analytics(user_id, start_date, end_date)
        
        # Add detailed breakdown
        export_data = {
            "export_info": {
                "user_id": user_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "format": format,
                "date_range": analytics["date_range"]
            },
            "usage_summary": analytics["summary"],
            "detailed_usage": analytics["monthly_usage"],
            "endpoint_analysis": analytics["endpoint_breakdown"]
        }

        log.info(f"Exported usage data for user {user_id} ({format} format)")
        return export_data

    async def get_current_month_usage(self, user_id: int) -> UsageStats:
        """
        Get current month usage statistics for a user.

        Args:
            user_id: User ID to get current usage for

        Returns:
            UsageStats object for current month
        """
        current_period = self._get_current_billing_period()
        return await self.get_usage_stats(user_id, current_period.period_key)

    async def get_usage_trends(self, user_id: int, months: int = 3) -> Dict[str, Any]:
        """
        Get usage trends for a user over the specified number of months.
        
        Args:
            user_id: User ID to get trends for
            months: Number of months to analyze (default: 3)
            
        Returns:
            Dictionary containing trend analysis
        """
        current_date = datetime.now(timezone.utc)
        trends_data = []

        for i in range(months):
            # Calculate the period date using relativedelta for correct month arithmetic
            period_date = current_date - relativedelta(months=i)
            period_key = period_date.strftime("%Y-%m")
            stats = await self.get_usage_stats(user_id, period_key)
            
            trends_data.append({
                "period": period_key,
                "requests": stats.total_requests,
                "tokens": stats.total_tokens,
                "endpoints": len(stats.endpoints_used)
            })
        
        # Calculate trends
        if len(trends_data) >= 2:
            recent_requests = trends_data[0]["requests"]
            previous_requests = trends_data[1]["requests"]
            request_trend = ((recent_requests - previous_requests) / max(previous_requests, 1)) * 100
            
            recent_tokens = trends_data[0]["tokens"]
            previous_tokens = trends_data[1]["tokens"]
            token_trend = ((recent_tokens - previous_tokens) / max(previous_tokens, 1)) * 100
        else:
            request_trend = 0
            token_trend = 0
            
        return {
            "user_id": user_id,
            "months_analyzed": months,
            "trend_data": trends_data,
            "request_trend_percent": round(request_trend, 2),
            "request_growth_rate": round(request_trend, 2),  # Alias for backward compatibility
            "token_growth_rate": round(token_trend, 2),
            "average_monthly_requests": round(sum(d["requests"] for d in trends_data) / len(trends_data), 2) if trends_data else 0
        }

    async def get_cost_breakdown(
        self, 
        user_id: int, 
        period: str, 
        tier: SubscriptionTier
    ) -> Dict[str, Any]:
        """
        Get detailed cost breakdown for a user's billing period.

        Args:
            user_id: User ID to get breakdown for
            period: Billing period (YYYY-MM format)
            tier: User's subscription tier

        Returns:
            Dictionary containing cost breakdown details
        """
        # Get usage stats for the period
        usage_stats = await self.get_usage_stats(user_id, period)
        
        # Calculate base subscription cost based on tier
        base_costs = {
            SubscriptionTier.FREE: 0,
            SubscriptionTier.BASIC: 999,  # $9.99
            SubscriptionTier.PREMIUM: 2999,  # $29.99
            SubscriptionTier.ACADEMIC: 1999,  # $19.99
        }
        
        base_cost_cents = base_costs.get(tier, 0)
        
        # Calculate overage charges
        overage_charges = await self.calculate_overage_charges(user_id, tier)
        
        # Calculate total cost
        total_cost_cents = base_cost_cents + overage_charges.total_charge_cents
        
        breakdown = {
            "user_id": user_id,
            "period": period,
            "tier": tier.value,
            "base_cost_cents": base_cost_cents,
            "overage_cost_cents": overage_charges.total_charge_cents,
            "total_cost_cents": total_cost_cents,
            "cost_per_request": total_cost_cents / max(usage_stats.total_requests, 1),
            "usage_stats": {
                "total_requests": usage_stats.total_requests,
                "total_tokens": usage_stats.total_tokens,
                "endpoints_used": usage_stats.endpoints_used
            },
            "currency": "usd"
        }
        
        log.debug(f"Generated cost breakdown for user {user_id}, period {period}: ${total_cost_cents/100:.2f}")
        return breakdown
