import logging
from typing import Dict, Any, Optional
from app.services.chat_monitoring import chat_monitoring

log = logging.getLogger(__name__)

def safe_record_metric(
    metric_name: str,
    metric_type: str = "counter",
    value: float = 1.0,
    labels: Optional[Dict[str, Any]] = None
) -> None:
    """
    Safely record a metric without breaking graceful degradation.

    Args:
        metric_name: Name of the metric to record
        metric_type: Type of metric (counter, gauge, histogram)
        value: Value to record (default: 1.0). Used for gauges and histograms;
               ignored for counters (counters are incremented via labels only).
        labels: Optional labels for the metric

    Examples:
        # Counter - value parameter is ignored, increment via labels
        safe_record_metric("requests_total", "counter", labels={"status": "success"})

        # Gauge - value parameter is used
        safe_record_metric("active_connections", "gauge", value=42.0)

        # Histogram - value parameter is used
        safe_record_metric("request_duration", "histogram", value=0.125)
    """
    try:
        if metric_type == "counter":
            chat_monitoring.record_counter(metric_name, labels=labels or {})
        elif metric_type == "gauge":
            chat_monitoring.record_gauge(metric_name, value, labels=labels or {})
        elif metric_type == "histogram":
            chat_monitoring.record_histogram(metric_name, value, labels=labels or {})
        else:
            log.warning(f"Unknown metric type: {metric_type}")
    except Exception as e:
        # Log but don't propagate - monitoring failures shouldn't break requests
        log.debug(
            f"Failed to record {metric_type} metric '{metric_name}': {e}",
            extra={"metric_name": metric_name, "metric_type": metric_type}
        )
