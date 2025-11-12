"""
Administrative payment management router.

Provides admin-only endpoints for:
- Refund processing and management
- Dispute handling and evidence submission
- Subscription overrides and adjustments
- Payment audit trails and reporting
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from datetime import datetime, timezone

from app.core.auth_config import current_active_user
from app.core.user_models import User
from app.core.rate_limiting import limiter, get_default_limit
from app.core.logger import log
from app.core.error_responses import (
    create_validation_error,
    create_not_found_error,
    create_internal_error,
    create_forbidden_error
)
from app.core.db_models import RefundReason, RefundStatus, DisputeStatus, SubscriptionTier, SubscriptionStatus


# Router setup
router = APIRouter(prefix="/admin/payments", tags=["admin-payments"])


# Request/Response Models
class RefundRequest(BaseModel):
    """Request model for initiating a refund."""
    payment_intent_id: str = Field(..., description="Stripe payment intent ID to refund")
    amount_cents: Optional[int] = Field(None, description="Partial refund amount in cents (None for full refund)")
    reason: RefundReason = Field(RefundReason.ADMIN_ADJUSTMENT, description="Reason for refund")
    admin_notes: Optional[str] = Field(None, description="Administrative notes about the refund")
    adjust_subscription: bool = Field(True, description="Whether to adjust user subscription")


class RefundResponse(BaseModel):
    """Response model for refund operations."""
    refund_id: str = Field(..., description="Database refund record ID")
    stripe_refund_id: str = Field(..., description="Stripe refund ID")
    amount_cents: int = Field(..., description="Refund amount in cents")
    status: RefundStatus = Field(..., description="Current refund status")
    reason: RefundReason = Field(..., description="Refund reason")
    created_at: datetime = Field(..., description="Refund creation timestamp")
    processed_at: Optional[datetime] = Field(None, description="Refund processing timestamp")
    subscription_adjusted: bool = Field(..., description="Whether subscription was adjusted")


class DisputeEvidenceRequest(BaseModel):
    """Request model for submitting dispute evidence."""
    customer_communication: Optional[str] = Field(None, description="Customer communication evidence")
    receipt: Optional[str] = Field(None, description="Receipt or proof of purchase")
    shipping_documentation: Optional[str] = Field(None, description="Shipping documentation")
    duplicate_charge_documentation: Optional[str] = Field(None, description="Duplicate charge evidence")
    product_description: Optional[str] = Field(None, description="Product or service description")
    admin_notes: Optional[str] = Field(None, description="Administrative notes")


class DisputeResponse(BaseModel):
    """Response model for dispute operations."""
    dispute_id: str = Field(..., description="Database dispute record ID")
    stripe_dispute_id: str = Field(..., description="Stripe dispute ID")
    amount_cents: int = Field(..., description="Disputed amount in cents")
    status: DisputeStatus = Field(..., description="Current dispute status")
    reason: str = Field(..., description="Dispute reason")
    evidence_due_by: Optional[datetime] = Field(None, description="Evidence submission deadline")
    evidence_submitted: bool = Field(..., description="Whether evidence has been submitted")
    account_suspended: bool = Field(..., description="Whether user account is suspended")


class SubscriptionOverrideRequest(BaseModel):
    """Request model for subscription overrides."""
    user_id: int = Field(..., description="User ID to modify")
    tier: Optional[SubscriptionTier] = Field(None, description="New subscription tier")
    status: Optional[SubscriptionStatus] = Field(None, description="New subscription status")
    extend_period_days: Optional[int] = Field(None, description="Days to extend current period")
    admin_notes: str = Field(..., description="Administrative notes for the override")


class SubscriptionOverrideResponse(BaseModel):
    """Response model for subscription override operations."""
    user_id: int = Field(..., description="User ID that was modified")
    old_tier: SubscriptionTier = Field(..., description="Previous subscription tier")
    new_tier: SubscriptionTier = Field(..., description="New subscription tier")
    old_status: SubscriptionStatus = Field(..., description="Previous subscription status")
    new_status: SubscriptionStatus = Field(..., description="New subscription status")
    period_extended: bool = Field(..., description="Whether billing period was extended")
    admin_notes: str = Field(..., description="Administrative notes")


class PaymentAuditRecord(BaseModel):
    """Response model for payment audit records."""
    id: int = Field(..., description="Record ID")
    user_id: int = Field(..., description="User ID")
    action_type: str = Field(..., description="Type of action (refund, dispute, override)")
    action_details: Dict[str, Any] = Field(..., description="Action details")
    admin_user_id: Optional[int] = Field(None, description="Admin user who performed action")
    timestamp: datetime = Field(..., description="Action timestamp")
    notes: Optional[str] = Field(None, description="Administrative notes")


class PaymentSummaryResponse(BaseModel):
    """Response model for payment summary statistics."""
    total_payments: int = Field(..., description="Total number of payments")
    total_amount_cents: int = Field(..., description="Total payment amount in cents")
    total_refunds: int = Field(..., description="Total number of refunds")
    total_refund_amount_cents: int = Field(..., description="Total refund amount in cents")
    active_disputes: int = Field(..., description="Number of active disputes")
    suspended_accounts: int = Field(..., description="Number of suspended accounts")
    period_start: datetime = Field(..., description="Summary period start")
    period_end: datetime = Field(..., description="Summary period end")


# Dependency functions
async def get_refund_dispute_service(request: Request):
    """Get refund dispute service from app state."""
    service = getattr(request.app.state, 'refund_dispute_service', None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Refund dispute service unavailable. Payments may be disabled."
        )
    return service


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


async def verify_admin_user(current_user: User = Depends(current_active_user)) -> User:
    """Verify that the current user has admin privileges."""
    # TODO: Implement proper admin role checking
    # For now, we'll check if user has a specific admin field or role
    if not getattr(current_user, 'is_admin', False):
        raise HTTPException(
            status_code=403,
            detail="Admin privileges required for this operation"
        )
    return current_user


# Refund management endpoints
@router.post("/refunds", response_model=RefundResponse)
@limiter.limit("10/minute")  # Stricter rate limit for admin operations
async def initiate_refund(
    request: Request,
    refund_request: RefundRequest,
    admin_user: User = Depends(verify_admin_user),
    refund_dispute_service = Depends(get_refund_dispute_service)
) -> RefundResponse:
    """
    Initiate a refund for a payment with comprehensive tracking.
    
    Admin-only endpoint for processing refunds with automatic subscription
    adjustments and audit logging.
    """
    try:
        log.info(f"Admin {admin_user.id} initiating refund for payment {refund_request.payment_intent_id}")
        
        # Find user ID from payment intent (this would need to be implemented)
        # For now, we'll assume it's provided or can be looked up
        user_id = await _get_user_id_from_payment_intent(refund_request.payment_intent_id)
        
        if not user_id:
            error = create_not_found_error(
                resource="payment",
                identifier=refund_request.payment_intent_id,
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=404, detail=error.model_dump())
        
        # Initiate refund
        refund_record = await refund_dispute_service.initiate_refund(
            user_id=user_id,
            payment_intent_id=refund_request.payment_intent_id,
            amount_cents=refund_request.amount_cents,
            reason=refund_request.reason,
            admin_user_id=admin_user.id,
            admin_notes=refund_request.admin_notes,
            adjust_subscription=refund_request.adjust_subscription
        )
        
        log.info(f"Refund {refund_record.stripe_refund_id} initiated by admin {admin_user.id}")
        
        return RefundResponse(
            refund_id=str(refund_record.id),
            stripe_refund_id=refund_record.stripe_refund_id,
            amount_cents=refund_record.amount_cents,
            status=refund_record.status,
            reason=refund_record.reason,
            created_at=refund_record.created_at,
            processed_at=refund_record.processed_at,
            subscription_adjusted=refund_record.subscription_adjusted
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to initiate refund: {e}")
        error = create_internal_error(
            message="Failed to initiate refund",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.get("/refunds/{refund_id}", response_model=RefundResponse)
async def get_refund_details(
    request: Request,
    refund_id: str,
    admin_user: User = Depends(verify_admin_user),
    refund_dispute_service = Depends(get_refund_dispute_service)
) -> RefundResponse:
    """
    Get detailed information about a specific refund.
    
    Admin-only endpoint for viewing refund status and details.
    """
    request_id = getattr(request.state, 'request_id', None)

    try:
        refund_record_id = _parse_path_identifier(
            refund_id,
            request=request,
            field_name="refund_id",
            resource_label="Refund",
        )

        # Get refund record from database
        refund_record = await _get_refund_record(refund_record_id)

        if not refund_record:
            error = create_not_found_error(
                resource="refund",
                identifier=str(refund_record_id),
                request_id=request_id
            )
            raise HTTPException(status_code=404, detail=error.model_dump())

        return RefundResponse(
            refund_id=str(refund_record.id),
            stripe_refund_id=refund_record.stripe_refund_id,
            amount_cents=refund_record.amount_cents,
            status=refund_record.status,
            reason=refund_record.reason,
            created_at=refund_record.created_at,
            processed_at=refund_record.processed_at,
            subscription_adjusted=refund_record.subscription_adjusted
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to get refund details: {e}")
        error = create_internal_error(
            message="Failed to retrieve refund details",
            request_id=request_id
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.get("/users/{user_id}/refunds")
async def get_user_refunds(
    request: Request,
    user_id: int,
    limit: int = 50,
    admin_user: User = Depends(verify_admin_user),
    refund_dispute_service = Depends(get_refund_dispute_service)
) -> List[RefundResponse]:
    """
    Get all refunds for a specific user.
    
    Admin-only endpoint for viewing user's refund history.
    """
    try:
        refund_records = await refund_dispute_service.get_user_refunds(user_id, limit)
        
        return [
            RefundResponse(
                refund_id=str(record.id),
                stripe_refund_id=record.stripe_refund_id,
                amount_cents=record.amount_cents,
                status=record.status,
                reason=record.reason,
                created_at=record.created_at,
                processed_at=record.processed_at,
                subscription_adjusted=record.subscription_adjusted
            )
            for record in refund_records
        ]
        
    except Exception as e:
        log.error(f"Failed to get user refunds: {e}")
        error = create_internal_error(
            message="Failed to retrieve user refunds",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


# Dispute management endpoints
@router.get("/disputes/{dispute_id}", response_model=DisputeResponse)
async def get_dispute_details(
    request: Request,
    dispute_id: str,
    admin_user: User = Depends(verify_admin_user),
    refund_dispute_service = Depends(get_refund_dispute_service)
) -> DisputeResponse:
    """
    Get detailed information about a specific dispute.
    
    Admin-only endpoint for viewing dispute status and details.
    """
    request_id = getattr(request.state, 'request_id', None)

    try:
        dispute_record_id = _parse_path_identifier(
            dispute_id,
            request=request,
            field_name="dispute_id",
            resource_label="Dispute",
        )

        # Get dispute record from database
        dispute_record = await _get_dispute_record(dispute_record_id)

        if not dispute_record:
            error = create_not_found_error(
                resource="dispute",
                identifier=str(dispute_record_id),
                request_id=request_id
            )
            raise HTTPException(status_code=404, detail=error.model_dump())

        return DisputeResponse(
            dispute_id=str(dispute_record.id),
            stripe_dispute_id=dispute_record.stripe_dispute_id,
            amount_cents=dispute_record.amount_cents,
            status=dispute_record.status,
            reason=dispute_record.reason.value,
            evidence_due_by=dispute_record.evidence_due_by,
            evidence_submitted=dispute_record.evidence_submitted,
            account_suspended=dispute_record.account_suspended
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to get dispute details: {e}")
        error = create_internal_error(
            message="Failed to retrieve dispute details",
            request_id=request_id
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.post("/disputes/{dispute_id}/evidence", response_model=DisputeResponse)
@limiter.limit("5/minute")
async def submit_dispute_evidence(
    request: Request,
    dispute_id: str,
    evidence_request: DisputeEvidenceRequest,
    admin_user: User = Depends(verify_admin_user),
    refund_dispute_service = Depends(get_refund_dispute_service)
) -> DisputeResponse:
    """
    Submit evidence for a dispute.
    
    Admin-only endpoint for submitting evidence to Stripe for dispute resolution.
    """
    request_id = getattr(request.state, 'request_id', None)

    try:
        dispute_record_id = _parse_path_identifier(
            dispute_id,
            request=request,
            field_name="dispute_id",
            resource_label="Dispute",
        )

        log.info(f"Admin {admin_user.id} submitting evidence for dispute {dispute_record_id}")
        
        # Prepare evidence dictionary for Stripe
        evidence = {}
        if evidence_request.customer_communication:
            evidence["customer_communication"] = evidence_request.customer_communication
        if evidence_request.receipt:
            evidence["receipt"] = evidence_request.receipt
        if evidence_request.shipping_documentation:
            evidence["shipping_documentation"] = evidence_request.shipping_documentation
        if evidence_request.duplicate_charge_documentation:
            evidence["duplicate_charge_documentation"] = evidence_request.duplicate_charge_documentation
        if evidence_request.product_description:
            evidence["product_description"] = evidence_request.product_description
        
        # Submit evidence
        dispute_record = await refund_dispute_service.submit_dispute_evidence(
            dispute_record_id=dispute_record_id,
            evidence=evidence,
            admin_user_id=admin_user.id,
            admin_notes=evidence_request.admin_notes
        )
        
        log.info(f"Evidence submitted for dispute {dispute_record.stripe_dispute_id}")
        
        return DisputeResponse(
            dispute_id=str(dispute_record.id),
            stripe_dispute_id=dispute_record.stripe_dispute_id,
            amount_cents=dispute_record.amount_cents,
            status=dispute_record.status,
            reason=dispute_record.reason.value,
            evidence_due_by=dispute_record.evidence_due_by,
            evidence_submitted=dispute_record.evidence_submitted,
            account_suspended=dispute_record.account_suspended
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to submit dispute evidence: {e}")
        error = create_internal_error(
            message="Failed to submit dispute evidence",
            request_id=request_id
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.post("/disputes/{dispute_id}/resolve", response_model=DisputeResponse)
@limiter.limit("5/minute")
async def resolve_dispute(
    request: Request,
    dispute_id: str,
    resolution: str,
    lift_suspension: bool = True,
    admin_notes: Optional[str] = None,
    admin_user: User = Depends(verify_admin_user),
    refund_dispute_service = Depends(get_refund_dispute_service)
) -> DisputeResponse:
    """
    Resolve a dispute and optionally lift account suspension.
    
    Admin-only endpoint for marking disputes as resolved and managing account status.
    """
    request_id = getattr(request.state, 'request_id', None)

    try:
        dispute_record_id = _parse_path_identifier(
            dispute_id,
            request=request,
            field_name="dispute_id",
            resource_label="Dispute",
        )

        log.info(f"Admin {admin_user.id} resolving dispute {dispute_record_id} with outcome {resolution}")

        dispute_record = await refund_dispute_service.resolve_dispute(
            dispute_record_id=dispute_record_id,
            resolution=resolution,
            admin_user_id=admin_user.id,
            lift_suspension=lift_suspension,
            admin_notes=admin_notes
        )
        
        log.info(f"Dispute {dispute_record.stripe_dispute_id} resolved")
        
        return DisputeResponse(
            dispute_id=str(dispute_record.id),
            stripe_dispute_id=dispute_record.stripe_dispute_id,
            amount_cents=dispute_record.amount_cents,
            status=dispute_record.status,
            reason=dispute_record.reason.value,
            evidence_due_by=dispute_record.evidence_due_by,
            evidence_submitted=dispute_record.evidence_submitted,
            account_suspended=dispute_record.account_suspended
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to resolve dispute: {e}")
        error = create_internal_error(
            message="Failed to resolve dispute",
            request_id=request_id
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


# Subscription override endpoints
@router.post("/subscriptions/override", response_model=SubscriptionOverrideResponse)
@limiter.limit("10/minute")
async def override_subscription(
    request: Request,
    override_request: SubscriptionOverrideRequest,
    admin_user: User = Depends(verify_admin_user),
    subscription_manager = Depends(get_subscription_manager)
) -> SubscriptionOverrideResponse:
    """
    Override user subscription settings.
    
    Admin-only endpoint for manually adjusting user subscriptions, extending periods,
    or changing tiers outside of normal billing cycles.
    """
    try:
        log.info(f"Admin {admin_user.id} overriding subscription for user {override_request.user_id}")
        
        # Get current subscription details
        current_subscription = await subscription_manager.get_user_subscription(override_request.user_id)
        if not current_subscription:
            error = create_not_found_error(
                resource="subscription",
                identifier=str(override_request.user_id),
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=404, detail=error.model_dump())
        
        old_tier = current_subscription.tier
        old_status = current_subscription.status
        
        # Apply overrides
        override_result = await subscription_manager.apply_admin_override(
            user_id=override_request.user_id,
            new_tier=override_request.tier,
            new_status=override_request.status,
            extend_period_days=override_request.extend_period_days,
            admin_user_id=admin_user.id,
            admin_notes=override_request.admin_notes
        )
        
        log.info(f"Subscription override applied for user {override_request.user_id}")
        
        return SubscriptionOverrideResponse(
            user_id=override_request.user_id,
            old_tier=old_tier,
            new_tier=override_result.new_tier,
            old_status=old_status,
            new_status=override_result.new_status,
            period_extended=override_result.period_extended,
            admin_notes=override_request.admin_notes
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to override subscription: {e}")
        error = create_internal_error(
            message="Failed to override subscription",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


# Audit and reporting endpoints
@router.get("/audit/summary", response_model=PaymentSummaryResponse)
async def get_payment_summary(
    request: Request,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    admin_user: User = Depends(verify_admin_user)
) -> PaymentSummaryResponse:
    """
    Get payment summary statistics for a given period.
    
    Admin-only endpoint for viewing payment metrics and statistics.
    """
    try:
        # Set default date range if not provided
        if not end_date:
            end_date = datetime.now(timezone.utc)
        if not start_date:
            start_date = datetime(end_date.year, end_date.month, 1)  # Start of current month
        
        # Get payment statistics
        summary = await _get_payment_summary(start_date, end_date)
        
        return PaymentSummaryResponse(
            total_payments=summary["total_payments"],
            total_amount_cents=summary["total_amount_cents"],
            total_refunds=summary["total_refunds"],
            total_refund_amount_cents=summary["total_refund_amount_cents"],
            active_disputes=summary["active_disputes"],
            suspended_accounts=summary["suspended_accounts"],
            period_start=start_date,
            period_end=end_date
        )
        
    except Exception as e:
        log.error(f"Failed to get payment summary: {e}")
        error = create_internal_error(
            message="Failed to retrieve payment summary",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.get("/audit/trail")
async def get_audit_trail(
    request: Request,
    user_id: Optional[int] = None,
    action_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    admin_user: User = Depends(verify_admin_user)
) -> List[PaymentAuditRecord]:
    """
    Get audit trail of payment-related administrative actions.
    
    Admin-only endpoint for viewing comprehensive audit logs.
    """
    try:
        audit_records = await _get_audit_trail(
            user_id=user_id,
            action_type=action_type,
            limit=limit,
            offset=offset
        )
        
        return [
            PaymentAuditRecord(
                id=record.id,
                user_id=record.user_id,
                action_type=record.action_type,
                action_details=record.action_details,
                admin_user_id=record.admin_user_id,
                timestamp=record.timestamp,
                notes=record.notes
            )
            for record in audit_records
        ]
        
    except Exception as e:
        log.error(f"Failed to get audit trail: {e}")
        error = create_internal_error(
            message="Failed to retrieve audit trail",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


# Helper functions
def _parse_path_identifier(raw_id: str, request: Request, field_name: str, resource_label: str) -> int:
    """Parse path parameters that reference database identifiers."""
    request_id = getattr(request.state, "request_id", None)
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        error = create_validation_error(
            field=field_name,
            message=f"{resource_label} ID must be a numeric value",
            request_id=request_id,
        )
        raise HTTPException(status_code=422, detail=error.model_dump())


async def _get_user_id_from_payment_intent(payment_intent_id: str) -> Optional[int]:
    """Get user ID from payment intent ID."""
    from app.core.database import get_session
    from app.core.db_models import PaymentRecord
    from sqlmodel import select
    
    async with get_session() as session:
        payment_record = session.exec(
            select(PaymentRecord).where(
                PaymentRecord.stripe_payment_intent_id == payment_intent_id
            )
        ).first()
        
        return payment_record.user_id if payment_record else None


async def _get_refund_record(refund_id: int):
    """Get refund record from database."""
    from app.core.database import get_session
    from app.core.db_models import RefundRecord
    
    async with get_session() as session:
        return session.get(RefundRecord, refund_id)


async def _get_dispute_record(dispute_id: int):
    """Get dispute record from database."""
    from app.core.database import get_session
    from app.core.db_models import DisputeRecord
    
    async with get_session() as session:
        return session.get(DisputeRecord, dispute_id)


async def _get_payment_summary(start_date: datetime, end_date: datetime) -> Dict[str, Any]:
    """Get payment summary statistics for date range."""
    from app.core.database import get_session
    from app.core.db_models import PaymentRecord, RefundRecord, DisputeRecord, Subscription
    from sqlmodel import select, func
    
    async with get_session() as session:
        # Total payments in period
        payment_stats = session.exec(
            select(
                func.count(PaymentRecord.id).label("count"),
                func.sum(PaymentRecord.amount_cents).label("total_amount")
            ).where(
                PaymentRecord.created_at >= start_date,
                PaymentRecord.created_at <= end_date,
                PaymentRecord.status == "succeeded"
            )
        ).first()
        
        # Total refunds in period
        refund_stats = session.exec(
            select(
                func.count(RefundRecord.id).label("count"),
                func.sum(RefundRecord.amount_cents).label("total_amount")
            ).where(
                RefundRecord.created_at >= start_date,
                RefundRecord.created_at <= end_date,
                RefundRecord.status == "succeeded"
            )
        ).first()
        
        # Active disputes
        active_disputes = session.exec(
            select(func.count(DisputeRecord.id)).where(
                DisputeRecord.status.in_(["needs_response", "under_review", "warning_needs_response"])
            )
        ).first()
        
        # Suspended accounts
        suspended_accounts = session.exec(
            select(func.count(DisputeRecord.id)).where(
                DisputeRecord.account_suspended == True
            )
        ).first()
        
        return {
            "total_payments": payment_stats.count or 0,
            "total_amount_cents": payment_stats.total_amount or 0,
            "total_refunds": refund_stats.count or 0,
            "total_refund_amount_cents": refund_stats.total_amount or 0,
            "active_disputes": active_disputes or 0,
            "suspended_accounts": suspended_accounts or 0
        }


async def _get_audit_trail(
    user_id: Optional[int] = None,
    action_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> List[Any]:
    """Get audit trail records."""
    # For now, we'll return refund and dispute records as audit trail
    # In a full implementation, you'd have a dedicated audit log table
    from app.core.database import get_session
    from app.core.db_models import RefundRecord, DisputeRecord
    from sqlmodel import select
    
    audit_records = []
    
    async with get_session() as session:
        # Get refund records as audit entries
        refund_query = select(RefundRecord).order_by(RefundRecord.created_at.desc())
        if user_id:
            refund_query = refund_query.where(RefundRecord.user_id == user_id)
        
        refunds = session.exec(refund_query.limit(limit//2).offset(offset//2)).all()
        
        for refund in refunds:
            audit_records.append({
                "id": refund.id,
                "user_id": refund.user_id,
                "action_type": "refund",
                "action_details": {
                    "stripe_refund_id": refund.stripe_refund_id,
                    "amount_cents": refund.amount_cents,
                    "reason": refund.reason.value,
                    "status": refund.status.value
                },
                "admin_user_id": refund.initiated_by_user_id,
                "timestamp": refund.created_at,
                "notes": refund.admin_notes
            })
        
        # Get dispute records as audit entries
        dispute_query = select(DisputeRecord).order_by(DisputeRecord.created_at.desc())
        if user_id:
            dispute_query = dispute_query.where(DisputeRecord.user_id == user_id)
        
        disputes = session.exec(dispute_query.limit(limit//2).offset(offset//2)).all()
        
        for dispute in disputes:
            audit_records.append({
                "id": dispute.id + 10000,  # Offset to avoid ID conflicts
                "user_id": dispute.user_id,
                "action_type": "dispute",
                "action_details": {
                    "stripe_dispute_id": dispute.stripe_dispute_id,
                    "amount_cents": dispute.amount_cents,
                    "reason": dispute.reason.value,
                    "status": dispute.status.value,
                    "account_suspended": dispute.account_suspended
                },
                "admin_user_id": dispute.assigned_to_user_id,
                "timestamp": dispute.created_at,
                "notes": dispute.admin_notes
            })
    
    # Sort by timestamp descending
    audit_records.sort(key=lambda x: x["timestamp"], reverse=True)
    
    return audit_records[:limit]
