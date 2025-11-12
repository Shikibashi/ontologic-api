"""
Refund and dispute management service.

Handles refund processing workflows, dispute management, and subscription
adjustments with comprehensive audit logging and database tracking.
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, TYPE_CHECKING
from sqlmodel import Session, select

from app.config.settings import get_settings
from app.core.logger import log
from app.core.database import get_session
from app.core.db_models import (
    RefundRecord, RefundStatus, RefundReason,
    DisputeRecord, DisputeStatus, DisputeReason,
    PaymentRecord, Subscription, SubscriptionStatus
)
from app.core.user_models import User
from app.services.payment_service import PaymentService, PaymentException

if TYPE_CHECKING:
    from app.services.cache_service import RedisCacheService
    from app.services.subscription_manager import SubscriptionManager


class RefundDisputeException(Exception):
    """Base exception for refund and dispute operations."""
    pass


class RefundDisputeService:
    """
    Service for managing refunds and disputes with comprehensive tracking.

    Handles refund initiation, processing, status tracking, and subscription
    adjustments. Also manages dispute workflows and evidence submission.
    """

    def __init__(
        self, 
        payment_service: PaymentService,
        subscription_manager: Optional['SubscriptionManager'] = None,
        cache_service: Optional['RedisCacheService'] = None
    ):
        """
        Initialize RefundDisputeService.

        Args:
            payment_service: PaymentService instance for Stripe operations
            subscription_manager: Optional SubscriptionManager for subscription adjustments
            cache_service: Optional RedisCacheService for caching
        """
        self.payment_service = payment_service
        self.subscription_manager = subscription_manager
        self.cache_service = cache_service
        self.settings = get_settings()

    @classmethod
    async def start(
        cls,
        payment_service: PaymentService,
        subscription_manager: Optional['SubscriptionManager'] = None,
        cache_service: Optional['RedisCacheService'] = None
    ):
        """
        Async factory method for lifespan-managed initialization.

        Args:
            payment_service: PaymentService instance
            subscription_manager: Optional SubscriptionManager instance
            cache_service: Optional RedisCacheService instance

        Returns:
            Initialized RefundDisputeService instance
        """
        instance = cls(
            payment_service=payment_service,
            subscription_manager=subscription_manager,
            cache_service=cache_service
        )
        
        log.info("RefundDisputeService initialized")
        return instance

    async def initiate_refund(
        self,
        user_id: int,
        payment_intent_id: str,
        amount_cents: Optional[int] = None,
        reason: RefundReason = RefundReason.CUSTOMER_REQUEST,
        admin_user_id: Optional[int] = None,
        admin_notes: Optional[str] = None,
        adjust_subscription: bool = True
    ) -> RefundRecord:
        """
        Initiate a refund with comprehensive tracking and subscription adjustment.

        Args:
            user_id: User ID requesting refund
            payment_intent_id: Stripe payment intent ID to refund
            amount_cents: Optional partial refund amount (None for full refund)
            reason: Reason for refund
            admin_user_id: Admin user initiating refund (if applicable)
            admin_notes: Administrative notes
            adjust_subscription: Whether to adjust subscription on successful refund

        Returns:
            RefundRecord instance

        Raises:
            RefundDisputeException: If refund initiation fails
        """
        try:
            # Process refund through Stripe
            refund_data = await self.payment_service.process_refund(
                payment_intent_id=payment_intent_id,
                amount=amount_cents,
                reason=reason.value,
                admin_user_id=admin_user_id,
                admin_notes=admin_notes
            )

            # Create refund record in database
            async with get_session() as session:
                # Find related payment record
                payment_record = session.exec(
                    select(PaymentRecord).where(
                        PaymentRecord.stripe_payment_intent_id == payment_intent_id
                    )
                ).first()

                # Create refund record
                refund_record = RefundRecord(
                    user_id=user_id,
                    payment_record_id=payment_record.id if payment_record else None,
                    stripe_refund_id=refund_data["id"],
                    stripe_payment_intent_id=payment_intent_id,
                    stripe_charge_id=refund_data.get("charge"),
                    amount_cents=refund_data["amount"],
                    currency=refund_data["currency"],
                    status=RefundStatus(refund_data["status"]),
                    reason=reason,
                    initiated_by_user_id=admin_user_id,
                    admin_notes=admin_notes,
                    refund_metadata=refund_data.get("metadata", {}),
                    processed_at=datetime.fromtimestamp(refund_data["created"]) if refund_data.get("created") else None
                )

                session.add(refund_record)
                session.commit()
                session.refresh(refund_record)

                # Adjust subscription if requested and refund is successful
                if adjust_subscription and refund_data["status"] == "succeeded":
                    await self._adjust_subscription_for_refund(
                        session, user_id, refund_record, admin_user_id
                    )

                log.info(f"Initiated refund {refund_record.stripe_refund_id} for user {user_id} (amount: {refund_record.amount_cents})")
                return refund_record

        except PaymentException as e:
            log.error(f"Failed to initiate refund for user {user_id}: {e}")
            raise RefundDisputeException(f"Failed to initiate refund: {str(e)}")
        except Exception as e:
            log.error(f"Unexpected error initiating refund for user {user_id}: {e}")
            raise RefundDisputeException(f"Unexpected error: {str(e)}")

    async def update_refund_status(self, refund_id: str) -> RefundRecord:
        """
        Update refund status from Stripe and adjust subscription if needed.

        Args:
            refund_id: Stripe refund ID to update

        Returns:
            Updated RefundRecord instance

        Raises:
            RefundDisputeException: If status update fails
        """
        try:
            # Get current status from Stripe
            refund_data = await self.payment_service.get_refund_status(refund_id)

            async with get_session() as session:
                # Find refund record
                refund_record = session.exec(
                    select(RefundRecord).where(RefundRecord.stripe_refund_id == refund_id)
                ).first()

                if not refund_record:
                    raise RefundDisputeException(f"Refund record not found for {refund_id}")

                # Update status and metadata
                old_status = refund_record.status
                refund_record.status = RefundStatus(refund_data["status"])
                refund_record.refund_metadata = refund_data.get("metadata", {})

                # If refund just succeeded and subscription wasn't adjusted yet, do it now
                if (old_status != RefundStatus.SUCCEEDED and 
                    refund_record.status == RefundStatus.SUCCEEDED and 
                    not refund_record.subscription_adjusted):
                    
                    await self._adjust_subscription_for_refund(
                        session, refund_record.user_id, refund_record
                    )

                session.commit()
                session.refresh(refund_record)

                log.info(f"Updated refund {refund_id} status from {old_status} to {refund_record.status}")
                return refund_record

        except PaymentException as e:
            log.error(f"Failed to update refund status for {refund_id}: {e}")
            raise RefundDisputeException(f"Failed to update refund status: {str(e)}")

    async def get_user_refunds(self, user_id: int, limit: int = 50) -> List[RefundRecord]:
        """
        Get refund history for a user.

        Args:
            user_id: User ID to get refunds for
            limit: Maximum number of refunds to return

        Returns:
            List of RefundRecord instances
        """
        async with get_session() as session:
            refunds = session.exec(
                select(RefundRecord)
                .where(RefundRecord.user_id == user_id)
                .order_by(RefundRecord.created_at.desc())
                .limit(limit)
            ).all()

            return list(refunds)

    async def create_dispute_record(
        self,
        user_id: int,
        stripe_dispute_id: str,
        suspend_account: bool = True,
        assigned_admin_id: Optional[int] = None
    ) -> DisputeRecord:
        """
        Create a dispute record when a chargeback occurs.

        Args:
            user_id: User ID for the disputed payment
            stripe_dispute_id: Stripe dispute ID
            suspend_account: Whether to suspend user account
            assigned_admin_id: Admin user assigned to handle dispute

        Returns:
            DisputeRecord instance

        Raises:
            RefundDisputeException: If dispute record creation fails
        """
        try:
            # Get dispute details from Stripe
            dispute_data = await self.payment_service.get_dispute_details(stripe_dispute_id)

            async with get_session() as session:
                # Find related payment record
                payment_record = None
                if dispute_data.get("payment_intent"):
                    payment_record = session.exec(
                        select(PaymentRecord).where(
                            PaymentRecord.stripe_payment_intent_id == dispute_data["payment_intent"]
                        )
                    ).first()

                # Create dispute record
                dispute_record = DisputeRecord(
                    user_id=user_id,
                    payment_record_id=payment_record.id if payment_record else None,
                    stripe_dispute_id=stripe_dispute_id,
                    stripe_charge_id=dispute_data["charge"],
                    stripe_payment_intent_id=dispute_data.get("payment_intent"),
                    amount_cents=dispute_data["amount"],
                    currency=dispute_data["currency"],
                    status=DisputeStatus(dispute_data["status"]),
                    reason=DisputeReason(dispute_data["reason"]),
                    evidence_due_by=datetime.fromtimestamp(dispute_data["evidence_due_by"]) if dispute_data.get("evidence_due_by") else None,
                    evidence_submitted=dispute_data.get("evidence_has_evidence", False),
                    assigned_to_user_id=assigned_admin_id,
                    account_suspended=suspend_account,
                    dispute_metadata=dispute_data.get("metadata", {})
                )

                session.add(dispute_record)
                session.commit()
                session.refresh(dispute_record)

                # Suspend user account if requested
                if suspend_account:
                    await self._suspend_user_account(session, user_id, dispute_record.id)

                log.info(f"Created dispute record {dispute_record.id} for user {user_id} (dispute: {stripe_dispute_id})")
                return dispute_record

        except PaymentException as e:
            log.error(f"Failed to create dispute record for {stripe_dispute_id}: {e}")
            raise RefundDisputeException(f"Failed to create dispute record: {str(e)}")

    async def submit_dispute_evidence(
        self,
        dispute_record_id: int,
        evidence: Dict[str, Any],
        admin_user_id: int,
        admin_notes: Optional[str] = None
    ) -> DisputeRecord:
        """
        Submit evidence for a dispute.

        Args:
            dispute_record_id: Database dispute record ID
            evidence: Evidence dictionary for Stripe
            admin_user_id: Admin user submitting evidence
            admin_notes: Administrative notes

        Returns:
            Updated DisputeRecord instance

        Raises:
            RefundDisputeException: If evidence submission fails
        """
        try:
            async with get_session() as session:
                dispute_record = session.get(DisputeRecord, dispute_record_id)
                if not dispute_record:
                    raise RefundDisputeException(f"Dispute record {dispute_record_id} not found")

                # Submit evidence to Stripe
                dispute_data = await self.payment_service.submit_dispute_evidence(
                    dispute_record.stripe_dispute_id,
                    evidence,
                    admin_user_id
                )

                # Update dispute record
                dispute_record.evidence_submitted = True
                dispute_record.evidence_details = evidence
                dispute_record.admin_notes = admin_notes
                dispute_record.assigned_to_user_id = admin_user_id

                session.commit()
                session.refresh(dispute_record)

                log.info(f"Submitted evidence for dispute {dispute_record.stripe_dispute_id} by admin {admin_user_id}")
                return dispute_record

        except PaymentException as e:
            log.error(f"Failed to submit evidence for dispute {dispute_record_id}: {e}")
            raise RefundDisputeException(f"Failed to submit evidence: {str(e)}")

    async def resolve_dispute(
        self,
        dispute_record_id: int,
        resolution: str,
        admin_user_id: int,
        lift_suspension: bool = True,
        admin_notes: Optional[str] = None
    ) -> DisputeRecord:
        """
        Resolve a dispute and optionally lift account suspension.

        Args:
            dispute_record_id: Database dispute record ID
            resolution: Resolution outcome (won, lost, etc.)
            admin_user_id: Admin user resolving dispute
            lift_suspension: Whether to lift account suspension
            admin_notes: Administrative notes about resolution

        Returns:
            Updated DisputeRecord instance
        """
        async with get_session() as session:
            dispute_record = session.get(DisputeRecord, dispute_record_id)
            if not dispute_record:
                raise RefundDisputeException(f"Dispute record {dispute_record_id} not found")

            # Update dispute record
            dispute_record.status = DisputeStatus(resolution)
            dispute_record.admin_notes = admin_notes
            dispute_record.assigned_to_user_id = admin_user_id

            # Lift account suspension if requested and dispute was won
            if lift_suspension and resolution in ["won", "warning_closed"]:
                dispute_record.account_suspended = False
                dispute_record.suspension_lifted_at = datetime.now(timezone.utc)
                
                # Reactivate user subscription if applicable
                await self._reactivate_user_subscription(session, dispute_record.user_id)

            session.commit()
            session.refresh(dispute_record)

            log.info(f"Resolved dispute {dispute_record.stripe_dispute_id} with outcome {resolution}")
            return dispute_record

    async def _adjust_subscription_for_refund(
        self,
        session: Session,
        user_id: int,
        refund_record: RefundRecord,
        admin_user_id: Optional[int] = None
    ):
        """Adjust user subscription based on refund amount and reason."""
        if not self.subscription_manager:
            log.warning("SubscriptionManager not available - skipping subscription adjustment")
            return

        try:
            # Get user's current subscription
            subscription = session.exec(
                select(Subscription).where(Subscription.user_id == user_id)
            ).first()

            if not subscription:
                log.info(f"No subscription found for user {user_id} - skipping adjustment")
                return

            # Determine adjustment based on refund reason and amount
            adjustment_notes = f"Subscription adjusted due to refund {refund_record.stripe_refund_id}"
            
            if refund_record.reason in [RefundReason.SUBSCRIPTION_CANCELED, RefundReason.CUSTOMER_REQUEST]:
                # Cancel subscription for full refunds or cancellation requests
                subscription.status = SubscriptionStatus.CANCELED
                adjustment_notes += " - subscription canceled"
                
            elif refund_record.reason == RefundReason.FRAUDULENT:
                # Suspend subscription for fraudulent refunds
                subscription.status = SubscriptionStatus.UNPAID
                adjustment_notes += " - subscription suspended due to fraud"

            # Update refund record to indicate subscription was adjusted
            refund_record.subscription_adjusted = True
            refund_record.subscription_adjustment_notes = adjustment_notes

            session.commit()
            log.info(f"Adjusted subscription for user {user_id} due to refund")

        except Exception as e:
            log.error(f"Failed to adjust subscription for refund {refund_record.id}: {e}")

    async def _suspend_user_account(self, session: Session, user_id: int, dispute_id: int):
        """Suspend user account due to dispute."""
        try:
            # Update user's subscription status
            subscription = session.exec(
                select(Subscription).where(Subscription.user_id == user_id)
            ).first()

            if subscription:
                subscription.status = SubscriptionStatus.UNPAID
                session.commit()

            log.info(f"Suspended account for user {user_id} due to dispute {dispute_id}")

        except Exception as e:
            log.error(f"Failed to suspend account for user {user_id}: {e}")

    async def _reactivate_user_subscription(self, session: Session, user_id: int):
        """Reactivate user subscription after dispute resolution."""
        try:
            subscription = session.exec(
                select(Subscription).where(Subscription.user_id == user_id)
            ).first()

            if subscription and subscription.status == SubscriptionStatus.UNPAID:
                subscription.status = SubscriptionStatus.ACTIVE
                session.commit()

            log.info(f"Reactivated subscription for user {user_id} after dispute resolution")

        except Exception as e:
            log.error(f"Failed to reactivate subscription for user {user_id}: {e}")