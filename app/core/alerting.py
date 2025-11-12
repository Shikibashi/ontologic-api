"""
Alerting and notification helpers for critical billing failures.

Provides monitoring alerts for billing system failures with integration
to observability platforms. In production, integrate with services like
PagerDuty, Opsgenie, or Slack. In tests, provides no-op/fake implementations.
"""

import os
from typing import Optional, Dict, Any
from app.core.logger import log


def notify_billing_failure(
    failure_type: str,
    user_id: Optional[int] = None,
    endpoint: Optional[str] = None,
    period: Optional[str] = None,
    tokens_used: Optional[int] = None,
    **kwargs
) -> None:
    """
    Send alert notification for billing system failures.

    Args:
        failure_type: Type of failure (e.g., "usage_tracking", "invoice_generation")
        user_id: User ID associated with the failure
        endpoint: API endpoint involved
        period: Billing period key
        tokens_used: Number of tokens in failed operation
        **kwargs: Additional context for the alert

    Note:
        In production, this should integrate with your alerting service.
        In tests/development, logs a warning message.
    """
    try:
        alert_context = {
            "failure_type": failure_type,
            "user_id": user_id,
            "endpoint": endpoint,
            "period": period,
            "tokens_used": tokens_used,
            **kwargs
        }

        # Check if running in production
        env = os.getenv("APP_ENV", "development")

        if env == "production":
            # TODO: Integrate with production alerting service
            # Examples:
            # - Send to PagerDuty API
            # - Post to Slack webhook
            # - Trigger Opsgenie alert
            # - Send SNS notification
            log.critical(
                f"[BILLING ALERT] {failure_type}: {alert_context}",
                extra={"alert_context": alert_context}
            )
        else:
            # Development/test mode: just log
            log.warning(
                f"[BILLING ALERT - {env}] {failure_type}: {alert_context}",
                extra={"alert_context": alert_context}
            )

    except Exception as e:
        # Never fail the caller due to alerting issues
        log.error(f"Failed to send billing failure alert: {e}", exc_info=True)
