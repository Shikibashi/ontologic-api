"""
Durable retry queue for failed billing operations.

Provides a retry mechanism for billing operations that fail due to transient
issues. In production, integrates with a message broker or database-backed queue.
In tests, provides no-op/fake implementations.
"""

import os
import json
from typing import Dict, Any
from datetime import datetime, timezone
from app.core.logger import log


def enqueue_billing_usage_retry(payload: Dict[str, Any]) -> None:
    """
    Enqueue a failed usage tracking operation for retry.

    Args:
        payload: Dictionary containing all data needed to retry the operation.
                Should include: user_id, endpoint, tokens_used, method,
                request_duration_ms, period, timestamp.

    Note:
        In production, this should write to a durable queue (e.g., RabbitMQ,
        Redis queue, database table). In tests/development, logs the payload.
    """
    try:
        # Add retry metadata
        retry_payload = {
            **payload,
            "retry_queued_at": datetime.now(timezone.utc).isoformat(),
            "retry_count": 0,
            "operation": "billing_usage_tracking"
        }

        # Check if running in production
        env = os.getenv("APP_ENV", "development")

        if env == "production":
            # TODO: Integrate with production retry queue
            # Examples:
            # - Write to RabbitMQ queue
            # - LPUSH to Redis list
            # - Insert into retry_queue database table
            # - Publish to SQS/SNS
            log.info(
                f"[RETRY QUEUE] Enqueued billing usage retry: {retry_payload}",
                extra={"retry_payload": retry_payload}
            )

            # Example database integration (uncomment when ready):
            # from app.core.database import AsyncSessionLocal
            # from app.core.db_models import RetryQueue
            # async with AsyncSessionLocal() as session:
            #     retry_record = RetryQueue(
            #         operation_type="billing_usage_tracking",
            #         payload=json.dumps(retry_payload),
            #         status="queued",
            #         created_at=datetime.now(timezone.utc)
            #     )
            #     session.add(retry_record)
            #     await session.commit()

        else:
            # Development/test mode: just log
            log.debug(
                f"[RETRY QUEUE - {env}] Would enqueue: {json.dumps(retry_payload, indent=2)}",
                extra={"retry_payload": retry_payload}
            )

    except Exception as e:
        # Never fail the caller due to retry queue issues
        log.error(f"Failed to enqueue billing usage retry: {e}", exc_info=True)
