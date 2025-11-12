"""
Chat History Monitoring and Metrics Service.

This service provides comprehensive monitoring, logging, and health checks
for the chat history system with privacy compliance tracking.
"""

import time
import asyncio
from datetime import datetime, timezone
from datetime import timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque

from app.core.logger import log
from app.core.chat_exceptions import ChatError, ChatErrorCategory, ChatErrorSeverity
from app.core.database import AsyncSessionLocal
from app.core.db_models import ChatConversation, ChatMessage
from sqlmodel import select, func
from sqlalchemy.ext.asyncio import AsyncSession


class HealthStatus(Enum):
    """Health check status levels."""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class MetricType(Enum):
    """Types of metrics to track."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


@dataclass
class PerformanceMetric:
    """Performance metric data structure."""
    name: str
    value: float
    metric_type: MetricType
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    labels: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "type": self.metric_type.value,
            "timestamp": self.timestamp.isoformat(),
            "labels": self.labels
        }


@dataclass
class HealthCheckResult:
    """Health check result data structure."""
    component: str
    status: HealthStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    response_time_ms: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "component": self.component,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "response_time_ms": self.response_time_ms
        }


class ChatMonitoringService:
    """
    Comprehensive monitoring service for chat history operations.
    
    Features:
    - Performance metrics collection and aggregation
    - Error tracking and analysis
    - Health checks for all chat components
    - Privacy compliance monitoring
    - Resource usage tracking
    - Alerting thresholds and notifications
    """
    
    def __init__(self):
        self.metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.error_counts: Dict[str, int] = defaultdict(int)
        self.performance_timers: Dict[str, float] = {}
        self.health_checks: Dict[str, HealthCheckResult] = {}
        self.privacy_violations: List[Dict[str, Any]] = []
        self.alert_thresholds = self._initialize_alert_thresholds()
        self.last_cleanup = datetime.now(timezone.utc)
    
    def _initialize_alert_thresholds(self) -> Dict[str, Dict[str, float]]:
        """Initialize default alert thresholds."""
        return {
            "error_rate": {
                "warning": 0.05,  # 5% error rate
                "critical": 0.15  # 15% error rate
            },
            "response_time": {
                "warning": 2000,  # 2 seconds
                "critical": 5000  # 5 seconds
            },
            "database_connections": {
                "warning": 80,    # 80% of max connections
                "critical": 95    # 95% of max connections
            },
            "memory_usage": {
                "warning": 80,    # 80% memory usage
                "critical": 90    # 90% memory usage
            }
        }
    
    def record_metric(self, name: str, value: float, metric_type: MetricType,
                     labels: Optional[Dict[str, str]] = None) -> None:
        """Record a performance metric."""
        metric = PerformanceMetric(
            name=name,
            value=value,
            metric_type=metric_type,
            labels=labels or {}
        )

        self.metrics[name].append(metric)

        # Log significant metrics
        if metric_type == MetricType.COUNTER:
            log.debug(f"Metric counter {name}: {value}", extra={"labels": labels})
        elif metric_type == MetricType.TIMER and value > 1000:  # Log slow operations
            log.info(f"Slow operation {name}: {value}ms", extra={"labels": labels})

    def record_counter(self, name: str, labels: Optional[Dict[str, str]] = None) -> None:
        """
        Convenience method for incrementing counters.

        Args:
            name: Metric name
            labels: Optional labels for the metric

        Example:
            chat_monitoring.record_counter("document_upload_success", {"file_type": "pdf"})
        """
        self.record_metric(name=name, value=1, metric_type=MetricType.COUNTER, labels=labels)

    def record_timer_ms(self, name: str, duration_ms: float, labels: Optional[Dict[str, str]] = None) -> None:
        """
        Convenience method for recording duration in milliseconds.

        Args:
            name: Metric name
            duration_ms: Duration in milliseconds
            labels: Optional labels for the metric

        Example:
            duration = (time.time() - start) * 1000
            chat_monitoring.record_timer_ms("operation_duration_ms", duration, {"operation": "upload"})
        """
        self.record_metric(name=name, value=duration_ms, metric_type=MetricType.TIMER, labels=labels)

    def record_histogram(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """
        Convenience method for recording histogram values.

        Args:
            name: Metric name
            value: Histogram value
            labels: Optional labels for the metric

        Example:
            chat_monitoring.record_histogram("document_size_mb", 15.5, {"file_type": "pdf"})
        """
        self.record_metric(name=name, value=value, metric_type=MetricType.HISTOGRAM, labels=labels)

    def start_timer(self, operation_name: str) -> str:
        """Start a performance timer for an operation."""
        timer_id = f"{operation_name}_{int(time.time() * 1000)}"
        self.performance_timers[timer_id] = time.time()
        return timer_id
    
    def end_timer(self, timer_id: str, labels: Optional[Dict[str, str]] = None) -> float:
        """End a performance timer and record the metric."""
        if timer_id not in self.performance_timers:
            log.warning(f"Timer {timer_id} not found")
            return 0.0
        
        start_time = self.performance_timers.pop(timer_id)
        duration_ms = (time.time() - start_time) * 1000
        
        # Extract operation name from timer_id
        operation_name = "_".join(timer_id.split("_")[:-1])
        
        self.record_metric(
            name=f"{operation_name}_duration",
            value=duration_ms,
            metric_type=MetricType.TIMER,
            labels=labels
        )
        
        return duration_ms
    
    def record_error(self, error: ChatError, operation: str, session_id: Optional[str] = None) -> None:
        """Record an error for monitoring and analysis."""
        error_key = f"{operation}:{error.category.value}:{error.severity.value}"
        self.error_counts[error_key] += 1
        
        # Record error metric
        self.record_metric(
            name="chat_errors_total",
            value=1,
            metric_type=MetricType.COUNTER,
            labels={
                "operation": operation,
                "category": error.category.value,
                "severity": error.severity.value,
                "recoverable": str(error.recoverable)
            }
        )
        
        # Log error details
        log.error(f"Chat error in {operation}: {error.message}", extra={
            "error_category": error.category.value,
            "error_severity": error.severity.value,
            "session_id": session_id,
            "recoverable": error.recoverable,
            "details": error.details
        })
        
        # Check for privacy violations
        if error.category == ChatErrorCategory.PRIVACY:
            self.record_privacy_violation(error, operation, session_id)
    
    def record_privacy_violation(self, error: ChatError, operation: str, 
                               session_id: Optional[str] = None) -> None:
        """Record a privacy violation for compliance monitoring."""
        violation = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "session_id": session_id,
            "error_message": error.message,
            "details": error.details,
            "severity": error.severity.value
        }
        
        self.privacy_violations.append(violation)
        
        # Keep only recent violations (last 1000)
        if len(self.privacy_violations) > 1000:
            self.privacy_violations = self.privacy_violations[-1000:]
        
        # Log critical privacy violations
        log.critical(f"Privacy violation detected in {operation}", extra={
            "session_id": session_id,
            "violation_details": error.details,
            "error_message": error.message
        })
    
    def record_operation_success(self, operation: str, duration_ms: float, 
                               labels: Optional[Dict[str, str]] = None) -> None:
        """Record a successful operation."""
        self.record_metric(
            name="chat_operations_total",
            value=1,
            metric_type=MetricType.COUNTER,
            labels={
                "operation": operation,
                "status": "success",
                **(labels or {})
            }
        )
        
        self.record_metric(
            name=f"{operation}_duration",
            value=duration_ms,
            metric_type=MetricType.TIMER,
            labels=labels
        )
    
    async def check_database_health(self) -> HealthCheckResult:
        """Check PostgreSQL database health."""
        start_time = time.time()
        
        try:
            async with AsyncSessionLocal() as session:
                # Test basic connectivity
                result = await session.execute(select(func.count()).select_from(ChatConversation))
                conversation_count = result.scalar()
                
                # Test message table
                result = await session.execute(select(func.count()).select_from(ChatMessage))
                message_count = result.scalar()
                
                response_time = (time.time() - start_time) * 1000
                
                # Check response time thresholds
                if response_time > self.alert_thresholds["response_time"]["critical"]:
                    status = HealthStatus.CRITICAL
                    message = f"Database response time critical: {response_time:.2f}ms"
                elif response_time > self.alert_thresholds["response_time"]["warning"]:
                    status = HealthStatus.WARNING
                    message = f"Database response time slow: {response_time:.2f}ms"
                else:
                    status = HealthStatus.HEALTHY
                    message = "Database connection healthy"
                
                return HealthCheckResult(
                    component="postgresql_database",
                    status=status,
                    message=message,
                    details={
                        "conversation_count": conversation_count,
                        "message_count": message_count,
                        "connection_test": "passed"
                    },
                    response_time_ms=response_time
                )
                
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            log.error(f"Database health check failed: {e}")
            
            return HealthCheckResult(
                component="postgresql_database",
                status=HealthStatus.CRITICAL,
                message=f"Database health check failed: {str(e)}",
                details={
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                response_time_ms=response_time
            )
    
    async def check_qdrant_health(self, qdrant_client, collection_name: str) -> HealthCheckResult:
        """Check Qdrant vector database health."""
        start_time = time.time()
        
        try:
            # Test basic connectivity
            collections = await qdrant_client.get_collections()
            
            # Check if chat collection exists
            collection_exists = any(col.name == collection_name for col in collections.collections)
            
            if collection_exists:
                # Get collection info
                collection_info = await qdrant_client.get_collection(collection_name)
                points_count = collection_info.points_count
                
                response_time = (time.time() - start_time) * 1000
                
                # Check response time thresholds
                if response_time > self.alert_thresholds["response_time"]["critical"]:
                    status = HealthStatus.CRITICAL
                    message = f"Qdrant response time critical: {response_time:.2f}ms"
                elif response_time > self.alert_thresholds["response_time"]["warning"]:
                    status = HealthStatus.WARNING
                    message = f"Qdrant response time slow: {response_time:.2f}ms"
                else:
                    status = HealthStatus.HEALTHY
                    message = "Qdrant connection healthy"
                
                return HealthCheckResult(
                    component="qdrant_vector_db",
                    status=status,
                    message=message,
                    details={
                        "collection_name": collection_name,
                        "collection_exists": True,
                        "points_count": points_count,
                        "collections_total": len(collections.collections)
                    },
                    response_time_ms=response_time
                )
            else:
                return HealthCheckResult(
                    component="qdrant_vector_db",
                    status=HealthStatus.WARNING,
                    message=f"Chat collection '{collection_name}' does not exist",
                    details={
                        "collection_name": collection_name,
                        "collection_exists": False,
                        "collections_total": len(collections.collections)
                    },
                    response_time_ms=(time.time() - start_time) * 1000
                )
                
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            log.error(f"Qdrant health check failed: {e}")
            
            return HealthCheckResult(
                component="qdrant_vector_db",
                status=HealthStatus.CRITICAL,
                message=f"Qdrant health check failed: {str(e)}",
                details={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "collection_name": collection_name
                },
                response_time_ms=response_time
            )
    
    def check_error_rates(self) -> HealthCheckResult:
        """Check error rates across all operations."""
        try:
            # Calculate error rates for the last hour
            now = datetime.now(timezone.utc)
            one_hour_ago = now - timedelta(hours=1)
            
            total_operations = 0
            total_errors = 0
            
            # Count operations and errors from metrics
            for metric_name, metric_queue in self.metrics.items():
                if "operations_total" in metric_name:
                    for metric in metric_queue:
                        if metric.timestamp >= one_hour_ago:
                            total_operations += metric.value
                elif "errors_total" in metric_name:
                    for metric in metric_queue:
                        if metric.timestamp >= one_hour_ago:
                            total_errors += metric.value
            
            if total_operations == 0:
                error_rate = 0.0
            else:
                error_rate = total_errors / total_operations
            
            # Check thresholds
            if error_rate >= self.alert_thresholds["error_rate"]["critical"]:
                status = HealthStatus.CRITICAL
                message = f"Critical error rate: {error_rate:.2%}"
            elif error_rate >= self.alert_thresholds["error_rate"]["warning"]:
                status = HealthStatus.WARNING
                message = f"High error rate: {error_rate:.2%}"
            else:
                status = HealthStatus.HEALTHY
                message = f"Error rate normal: {error_rate:.2%}"
            
            return HealthCheckResult(
                component="error_rates",
                status=status,
                message=message,
                details={
                    "error_rate": error_rate,
                    "total_operations": total_operations,
                    "total_errors": total_errors,
                    "time_window": "1 hour"
                }
            )
            
        except Exception as e:
            log.error(f"Error rate check failed: {e}")
            return HealthCheckResult(
                component="error_rates",
                status=HealthStatus.UNKNOWN,
                message=f"Error rate check failed: {str(e)}",
                details={"error": str(e)}
            )
    
    def check_privacy_compliance(self) -> HealthCheckResult:
        """Check privacy compliance status."""
        try:
            # Count recent privacy violations
            now = datetime.now(timezone.utc)
            one_hour_ago = now - timedelta(hours=1)
            
            recent_violations = [
                v for v in self.privacy_violations
                if datetime.fromisoformat(v["timestamp"]) >= one_hour_ago
            ]
            
            violation_count = len(recent_violations)
            
            # Any privacy violation is serious
            if violation_count > 0:
                status = HealthStatus.CRITICAL
                message = f"Privacy violations detected: {violation_count} in last hour"
            else:
                status = HealthStatus.HEALTHY
                message = "No privacy violations detected"
            
            return HealthCheckResult(
                component="privacy_compliance",
                status=status,
                message=message,
                details={
                    "violations_last_hour": violation_count,
                    "total_violations": len(self.privacy_violations),
                    "recent_violations": recent_violations[:5]  # Show first 5
                }
            )
            
        except Exception as e:
            log.error(f"Privacy compliance check failed: {e}")
            return HealthCheckResult(
                component="privacy_compliance",
                status=HealthStatus.UNKNOWN,
                message=f"Privacy compliance check failed: {str(e)}",
                details={"error": str(e)}
            )
    
    async def run_comprehensive_health_check(self, qdrant_client=None, 
                                           collection_name: str = "Chat_History") -> Dict[str, Any]:
        """Run comprehensive health checks for all chat components."""
        health_results = {}
        
        # Database health check
        db_health = await self.check_database_health()
        health_results["database"] = db_health.to_dict()
        
        # Qdrant health check (if client provided)
        if qdrant_client:
            qdrant_health = await self.check_qdrant_health(qdrant_client, collection_name)
            health_results["qdrant"] = qdrant_health.to_dict()
        
        # Error rate check
        error_health = self.check_error_rates()
        health_results["error_rates"] = error_health.to_dict()
        
        # Privacy compliance check
        privacy_health = self.check_privacy_compliance()
        health_results["privacy_compliance"] = privacy_health.to_dict()
        
        # Overall status
        all_statuses = [result["status"] for result in health_results.values()]
        
        if "critical" in all_statuses:
            overall_status = "critical"
        elif "warning" in all_statuses:
            overall_status = "warning"
        elif "unknown" in all_statuses:
            overall_status = "unknown"
        else:
            overall_status = "healthy"
        
        return {
            "overall_status": overall_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": health_results,
            "summary": {
                "total_components": len(health_results),
                "healthy_components": sum(1 for r in health_results.values() if r["status"] == "healthy"),
                "warning_components": sum(1 for r in health_results.values() if r["status"] == "warning"),
                "critical_components": sum(1 for r in health_results.values() if r["status"] == "critical")
            }
        }
    
    def get_performance_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get performance metrics summary for the specified time period."""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        summary = {
            "time_period_hours": hours,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": {}
        }
        
        for metric_name, metric_queue in self.metrics.items():
            recent_metrics = [m for m in metric_queue if m.timestamp >= cutoff_time]
            
            if not recent_metrics:
                continue
            
            values = [m.value for m in recent_metrics]
            
            if recent_metrics[0].metric_type == MetricType.TIMER:
                # For timers, calculate statistics
                summary["metrics"][metric_name] = {
                    "count": len(values),
                    "avg": sum(values) / len(values),
                    "min": min(values),
                    "max": max(values),
                    "p95": sorted(values)[int(len(values) * 0.95)] if len(values) > 0 else 0
                }
            elif recent_metrics[0].metric_type == MetricType.COUNTER:
                # For counters, sum the values
                summary["metrics"][metric_name] = {
                    "total": sum(values),
                    "count": len(values)
                }
            else:
                # For gauges, show latest value
                summary["metrics"][metric_name] = {
                    "current": values[-1] if values else 0,
                    "count": len(values)
                }
        
        return summary
    
    def cleanup_old_data(self) -> None:
        """Clean up old monitoring data to prevent memory leaks."""
        now = datetime.now(timezone.utc)
        
        # Clean up old privacy violations (keep last 7 days)
        seven_days_ago = now - timedelta(days=7)
        self.privacy_violations = [
            v for v in self.privacy_violations
            if datetime.fromisoformat(v["timestamp"]) >= seven_days_ago
        ]
        
        # Clean up old error counts (reset daily)
        if (now - self.last_cleanup).days >= 1:
            self.error_counts.clear()
            self.last_cleanup = now
        
        log.info("Monitoring data cleanup completed")
    
    def get_monitoring_status(self) -> Dict[str, Any]:
        """Get current monitoring service status."""
        return {
            "service": "chat_monitoring",
            "status": "active",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics_tracked": len(self.metrics),
            "error_types_tracked": len(self.error_counts),
            "privacy_violations": len(self.privacy_violations),
            "active_timers": len(self.performance_timers),
            "last_cleanup": self.last_cleanup.isoformat()
        }


# Global monitoring service instance
chat_monitoring = ChatMonitoringService()


def monitor_chat_operation(operation_name: str):
    """
    Decorator to automatically monitor chat operations.
    
    Args:
        operation_name: Name of the operation to monitor
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            timer_id = chat_monitoring.start_timer(operation_name)
            
            try:
                result = await func(*args, **kwargs)
                
                # Record successful operation
                duration = chat_monitoring.end_timer(timer_id, {"status": "success"})
                chat_monitoring.record_operation_success(operation_name, duration)
                
                return result
                
            except ChatError as e:
                # Record chat error
                duration = chat_monitoring.end_timer(timer_id, {"status": "error"})
                session_id = kwargs.get('session_id') or (args[0] if args else None)
                chat_monitoring.record_error(e, operation_name, session_id)
                raise
                
            except Exception as e:
                # Record unexpected error
                duration = chat_monitoring.end_timer(timer_id, {"status": "error"})
                log.error(f"Unexpected error in monitored operation {operation_name}: {e}")
                raise
        
        return wrapper
    return decorator