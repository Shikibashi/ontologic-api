from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlmodel import SQLModel, Field, JSON, Column, Relationship
from sqlalchemy import DateTime, func, String, Index
from enum import Enum


class DraftStatus(str, Enum):
    """Status of a paper draft."""
    CREATED = "created"
    GENERATING = "generating"
    GENERATED = "generated"
    REVIEWING = "reviewing"
    REVIEWED = "reviewed"
    APPLYING = "applying"
    COMPLETED = "completed"
    ERROR = "error"


class SuggestionStatus(str, Enum):
    """Status of review suggestions."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    APPLIED = "applied"


class MessageRole(str, Enum):
    """Role of a message in a conversation."""
    USER = "user"
    ASSISTANT = "assistant"


class SubscriptionTier(str, Enum):
    """Subscription tier levels."""
    FREE = "free"
    BASIC = "basic"
    PREMIUM = "premium"
    ACADEMIC = "academic"


class SubscriptionStatus(str, Enum):
    """Stripe subscription status values."""
    ACTIVE = "active"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"
    PAST_DUE = "past_due"
    TRIALING = "trialing"
    UNPAID = "unpaid"


class PaperDraft(SQLModel, table=True):
    """
    Model for storing paper drafts and their generation workflow state.

    Supports the full paper generation and review lifecycle.
    """
    __tablename__ = "paper_drafts"

    # Primary identification
    id: Optional[int] = Field(default=None, primary_key=True)
    draft_id: str = Field(unique=True, index=True, description="Unique identifier for the draft")

    # Paper metadata
    title: str = Field(description="Title of the paper")
    topic: str = Field(description="Main topic or subject matter")
    collection: str = Field(description="Philosopher collection to focus on")

    # Configuration
    immersive_mode: bool = Field(default=False, description="Whether to use immersive philosopher voice")
    temperature: float = Field(default=0.3, description="LLM temperature for generation")

    # Status and workflow
    status: DraftStatus = Field(default=DraftStatus.CREATED, description="Current workflow status")

    # Content sections
    abstract: Optional[str] = Field(default=None, description="Abstract section content")
    introduction: Optional[str] = Field(default=None, description="Introduction section content")
    argument: Optional[str] = Field(default=None, description="Main argument section content")
    counterarguments: Optional[str] = Field(default=None, description="Counterarguments section content")
    conclusion: Optional[str] = Field(default=None, description="Conclusion section content")

    # Review and suggestions
    review_data: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="AI review results and analysis"
    )
    suggestions: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="Review suggestions with status tracking"
    )

    # Metadata and tracking
    workflow_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="Additional metadata and configuration"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), onupdate=func.now())
    )

    # Generation tracking
    generation_started_at: Optional[datetime] = Field(default=None)
    generation_completed_at: Optional[datetime] = Field(default=None)
    review_started_at: Optional[datetime] = Field(default=None)
    review_completed_at: Optional[datetime] = Field(default=None)

    class Config:
        arbitrary_types_allowed = True

    def get_sections(self) -> Dict[str, Optional[str]]:
        """Get all content sections as a dictionary."""
        return {
            "abstract": self.abstract,
            "introduction": self.introduction,
            "argument": self.argument,
            "counterarguments": self.counterarguments,
            "conclusion": self.conclusion
        }

    def set_section(self, section_name: str, content: str) -> None:
        """Set content for a specific section."""
        if section_name == "abstract":
            self.abstract = content
        elif section_name == "introduction":
            self.introduction = content
        elif section_name == "argument":
            self.argument = content
        elif section_name == "counterarguments":
            self.counterarguments = content
        elif section_name == "conclusion":
            self.conclusion = content
        else:
            raise ValueError(f"Unknown section: {section_name}")

    def get_progress(self) -> Dict[str, Any]:
        """Get generation progress information."""
        sections = self.get_sections()
        completed_sections = sum(1 for content in sections.values() if content is not None)
        total_sections = len(sections)

        return {
            "status": self.status,
            "completed_sections": completed_sections,
            "total_sections": total_sections,
            "progress_percentage": round((completed_sections / total_sections) * 100, 1),
            "sections": {name: bool(content) for name, content in sections.items()}
        }


class ReviewSuggestion(SQLModel):
    """
    Model for individual review suggestions.

    Used within the suggestions JSON field of PaperDraft.
    """
    section: str = Field(description="Section this suggestion applies to")
    before: str = Field(description="Original text that needs revision")
    after: str = Field(description="Suggested replacement text")
    rationale: str = Field(description="Explanation for why this change is recommended")
    blocking: bool = Field(default=False, description="Whether this is a blocking issue")
    status: SuggestionStatus = Field(default=SuggestionStatus.PENDING, description="Status of this suggestion")
    suggestion_id: Optional[str] = Field(default=None, description="Unique identifier for this suggestion")

    class Config:
        arbitrary_types_allowed = True


class ChatConversation(SQLModel, table=True):
    """
    Model for storing chat conversations with proper session tracking.
    
    Supports conversation grouping and metadata for chat history management.
    """
    __tablename__ = "chat_conversations"

    # Primary identification
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: str = Field(unique=True, index=True, description="Unique identifier for the conversation")
    
    # Session and user tracking
    session_id: str = Field(index=True, description="Session identifier for privacy isolation")
    username: Optional[str] = Field(default=None, index=True, description="User identifier for multi-user support")

    # Conversation metadata
    title: Optional[str] = Field(default=None, description="Optional conversation title")
    philosopher_collection: Optional[str] = Field(default=None, description="Primary philosopher collection used")
    
    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), server_default=func.now()),
        description="When the conversation was created"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), onupdate=func.now()),
        description="When the conversation was last updated"
    )

    # Relationship to messages
    messages: List["ChatMessage"] = Relationship(back_populates="conversation")

    class Config:
        arbitrary_types_allowed = True

    __table_args__ = (
        Index('ix_chat_conversations_session_created', 'session_id', 'created_at'),
        Index('ix_chat_conversations_username_created', 'username', 'created_at'),
    )


class ChatMessage(SQLModel, table=True):
    """
    Model for storing individual chat messages with vector database integration.
    
    Supports both user and AI messages with proper session isolation and Qdrant integration.
    """
    __tablename__ = "chat_messages"

    # Primary identification
    id: Optional[int] = Field(default=None, primary_key=True)
    message_id: str = Field(unique=True, index=True, description="Unique identifier for the message")
    
    # Conversation and session tracking
    conversation_id: str = Field(
        foreign_key="chat_conversations.conversation_id",
        index=True,
        description="Reference to the conversation this message belongs to"
    )
    session_id: str = Field(index=True, description="Session identifier for privacy isolation")
    username: Optional[str] = Field(default=None, index=True, description="User identifier for multi-user support")

    # Message content and metadata
    role: MessageRole = Field(description="Role of the message sender (user or assistant)")
    content: str = Field(description="The actual message content")
    philosopher_collection: Optional[str] = Field(default=None, description="Philosopher collection context")
    
    # Qdrant integration
    qdrant_point_id: Optional[str] = Field(default=None, description="Corresponding Qdrant point ID for vector search")
    
    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), server_default=func.now()),
        description="When the message was created"
    )

    # Relationship to conversation
    conversation: Optional[ChatConversation] = Relationship(back_populates="messages")

    class Config:
        arbitrary_types_allowed = True

    __table_args__ = (
        Index('ix_chat_messages_session_created', 'session_id', 'created_at'),
        Index('ix_chat_messages_conversation_created', 'conversation_id', 'created_at'),
        Index('ix_chat_messages_username_created', 'username', 'created_at'),
    )


class Subscription(SQLModel, table=True):
    """
    User subscription information synced with Stripe.
    
    Tracks subscription tiers, billing periods, and Stripe integration data.
    """
    __tablename__ = "subscriptions"
    
    # Primary identification
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    
    # Stripe integration
    stripe_customer_id: str = Field(unique=True, index=True)
    stripe_subscription_id: Optional[str] = Field(default=None, unique=True, index=True)
    stripe_price_id: Optional[str] = Field(default=None)
    
    # Subscription details
    tier: SubscriptionTier = Field(default=SubscriptionTier.FREE)
    status: SubscriptionStatus = Field(default=SubscriptionStatus.ACTIVE)
    
    # Billing periods
    current_period_start: Optional[datetime] = Field(default=None)
    current_period_end: Optional[datetime] = Field(default=None)
    
    # Timestamps (following existing pattern)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), onupdate=func.now())
    )

    class Config:
        arbitrary_types_allowed = True

    __table_args__ = (
        Index('ix_subscriptions_user_status', 'user_id', 'status'),
        Index('ix_subscriptions_tier_status', 'tier', 'status'),
    )


class UsageRecord(SQLModel, table=True):
    """
    API usage tracking for billing.
    
    Records individual API requests for usage-based billing and analytics.
    """
    __tablename__ = "usage_records"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    
    # Usage details
    endpoint: str = Field(index=True)
    method: str = Field(default="POST")
    tokens_used: int = Field(default=0)
    request_duration_ms: Optional[int] = Field(default=None)
    
    # Billing context
    billing_period: str = Field(index=True, description="YYYY-MM format")
    subscription_tier: SubscriptionTier = Field(index=True)
    
    # Timestamp
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), index=True)
    )

    class Config:
        arbitrary_types_allowed = True

    __table_args__ = (
        Index('ix_usage_records_user_period', 'user_id', 'billing_period'),
        Index('ix_usage_records_user_timestamp', 'user_id', 'timestamp'),
        Index('ix_usage_records_endpoint_timestamp', 'endpoint', 'timestamp'),
    )


class PaymentRecord(SQLModel, table=True):
    """
    Payment transaction history.
    
    Tracks all payment transactions and their status for audit and billing purposes.
    """
    __tablename__ = "payment_records"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    
    # Stripe integration
    stripe_payment_intent_id: str = Field(unique=True, index=True)
    stripe_invoice_id: Optional[str] = Field(default=None, index=True)
    
    # Payment details
    amount_cents: int = Field(description="Amount in cents")
    currency: str = Field(default="usd")
    status: str = Field(index=True, description="succeeded, failed, pending, etc.")
    
    # Metadata
    description: Optional[str] = Field(default=None)
    payment_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON)
    )
    
    # Timestamp
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )

    class Config:
        arbitrary_types_allowed = True

    __table_args__ = (
        Index('ix_payment_records_user_status', 'user_id', 'status'),
        Index('ix_payment_records_user_created', 'user_id', 'created_at'),
        Index('ix_payment_records_status_created', 'status', 'created_at'),
    )


class RefundStatus(str, Enum):
    """Refund status values from Stripe."""
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    REQUIRES_ACTION = "requires_action"


class RefundReason(str, Enum):
    """Reason for refund initiation."""
    CUSTOMER_REQUEST = "customer_request"
    DUPLICATE = "duplicate"
    FRAUDULENT = "fraudulent"
    SUBSCRIPTION_CANCELED = "subscription_canceled"
    ADMIN_ADJUSTMENT = "admin_adjustment"
    DISPUTE = "dispute"


class RefundRecord(SQLModel, table=True):
    """
    Refund transaction history and tracking.
    
    Tracks all refund requests, their processing status, and audit information.
    """
    __tablename__ = "refund_records"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    
    # Related payment
    payment_record_id: Optional[int] = Field(foreign_key="payment_records.id", index=True)
    
    # Stripe integration
    stripe_refund_id: str = Field(unique=True, index=True)
    stripe_payment_intent_id: str = Field(index=True)
    stripe_charge_id: Optional[str] = Field(default=None, index=True)
    
    # Refund details
    amount_cents: int = Field(description="Refund amount in cents")
    currency: str = Field(default="usd")
    status: RefundStatus = Field(index=True)
    reason: RefundReason = Field(index=True)
    
    # Processing information
    initiated_by_user_id: Optional[int] = Field(foreign_key="users.id", description="Admin user who initiated refund")
    admin_notes: Optional[str] = Field(default=None, description="Administrative notes about the refund")
    
    # Subscription impact
    subscription_adjusted: bool = Field(default=False, description="Whether subscription was adjusted due to refund")
    subscription_adjustment_notes: Optional[str] = Field(default=None)
    
    # Metadata
    refund_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="Additional refund metadata from Stripe"
    )
    
    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    processed_at: Optional[datetime] = Field(default=None, description="When refund was processed by Stripe")

    class Config:
        arbitrary_types_allowed = True

    __table_args__ = (
        Index('ix_refund_records_user_status', 'user_id', 'status'),
        Index('ix_refund_records_user_created', 'user_id', 'created_at'),
        Index('ix_refund_records_status_created', 'status', 'created_at'),
        Index('ix_refund_records_payment_intent', 'stripe_payment_intent_id'),
    )

class DisputeStatus(str, Enum):
    """Dispute status values from Stripe."""
    WARNING_NEEDS_RESPONSE = "warning_needs_response"
    WARNING_UNDER_REVIEW = "warning_under_review"
    WARNING_CLOSED = "warning_closed"
    NEEDS_RESPONSE = "needs_response"
    UNDER_REVIEW = "under_review"
    CHARGE_REFUNDED = "charge_refunded"
    WON = "won"
    LOST = "lost"


class DisputeReason(str, Enum):
    """Dispute reason from Stripe."""
    DUPLICATE = "duplicate"
    FRAUDULENT = "fraudulent"
    SUBSCRIPTION_CANCELED = "subscription_canceled"
    PRODUCT_UNACCEPTABLE = "product_unacceptable"
    PRODUCT_NOT_RECEIVED = "product_not_received"
    UNRECOGNIZED = "unrecognized"
    CREDIT_NOT_PROCESSED = "credit_not_processed"
    GENERAL = "general"
    INCORRECT_ACCOUNT_DETAILS = "incorrect_account_details"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    BANK_CANNOT_PROCESS = "bank_cannot_process"
    DEBIT_NOT_AUTHORIZED = "debit_not_authorized"
    CUSTOMER_INITIATED = "customer_initiated"


class DisputeRecord(SQLModel, table=True):
    """
    Payment dispute tracking and management.
    
    Tracks chargebacks, disputes, and their resolution process.
    """
    __tablename__ = "dispute_records"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    
    # Related payment
    payment_record_id: Optional[int] = Field(foreign_key="payment_records.id", index=True)
    
    # Stripe integration
    stripe_dispute_id: str = Field(unique=True, index=True)
    stripe_charge_id: str = Field(index=True)
    stripe_payment_intent_id: Optional[str] = Field(default=None, index=True)
    
    # Dispute details
    amount_cents: int = Field(description="Disputed amount in cents")
    currency: str = Field(default="usd")
    status: DisputeStatus = Field(index=True)
    reason: DisputeReason = Field(index=True)
    
    # Evidence and response
    evidence_due_by: Optional[datetime] = Field(default=None, description="Deadline for submitting evidence")
    evidence_submitted: bool = Field(default=False, description="Whether evidence has been submitted")
    evidence_details: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="Evidence submitted for dispute"
    )
    
    # Administrative handling
    assigned_to_user_id: Optional[int] = Field(foreign_key="users.id", description="Admin user handling dispute")
    admin_notes: Optional[str] = Field(default=None, description="Administrative notes about dispute handling")
    
    # Account impact
    account_suspended: bool = Field(default=False, description="Whether user account was suspended due to dispute")
    suspension_lifted_at: Optional[datetime] = Field(default=None, description="When account suspension was lifted")
    
    # Metadata
    dispute_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="Additional dispute metadata from Stripe"
    )
    
    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), onupdate=func.now())
    )

    class Config:
        arbitrary_types_allowed = True

    __table_args__ = (
        Index('ix_dispute_records_user_status', 'user_id', 'status'),
        Index('ix_dispute_records_user_created', 'user_id', 'created_at'),
        Index('ix_dispute_records_status_created', 'status', 'created_at'),
        Index('ix_dispute_records_charge_id', 'stripe_charge_id'),
        Index('ix_dispute_records_evidence_due', 'evidence_due_by'),
    )

class WebhookEvent(SQLModel, table=True):
    """
    Model for tracking webhook events to ensure idempotency.
    
    Prevents duplicate webhook processing by storing event IDs with atomic
    INSERT ... ON CONFLICT operations.
    """
    __tablename__ = "webhook_events"
    
    # Primary identification
    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: str = Field(unique=True, index=True, max_length=255, description="Stripe event ID (must be unique)")
    
    # Event metadata
    event_type: str = Field(max_length=100, description="Type of webhook event")
    processed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), server_default=func.now()),
        description="When the event was processed"
    )
    
    # Optional payload storage for debugging
    payload: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="Raw event payload for debugging"
    )
    
    class Config:
        arbitrary_types_allowed = True
    
    __table_args__ = (
        Index('ix_webhook_events_event_type', 'event_type'),
        Index('ix_webhook_events_processed_at', 'processed_at'),
    )
