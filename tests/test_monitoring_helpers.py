"""Tests for safe metric recording helpers."""

import pytest
from unittest.mock import Mock, patch
from app.services.monitoring_helpers import safe_record_metric


class TestSafeRecordMetric:
    """Test safe metric recording with graceful degradation."""

    @patch('app.services.monitoring_helpers.chat_monitoring')
    def test_counter_recording_success(self, mock_monitoring):
        """Successfully record counter metric."""
        safe_record_metric("test_counter", metric_type="counter", labels={"key": "value"})

        mock_monitoring.record_counter.assert_called_once_with(
            "test_counter",
            labels={"key": "value"}
        )

    @patch('app.services.monitoring_helpers.chat_monitoring')
    def test_gauge_recording_success(self, mock_monitoring):
        """Successfully record gauge metric with value."""
        safe_record_metric("test_gauge", metric_type="gauge", value=42.5, labels={"env": "test"})

        mock_monitoring.record_gauge.assert_called_once_with(
            "test_gauge",
            42.5,
            labels={"env": "test"}
        )

    @patch('app.services.monitoring_helpers.chat_monitoring')
    def test_histogram_recording_success(self, mock_monitoring):
        """Successfully record histogram metric."""
        safe_record_metric("test_histogram", metric_type="histogram", value=100.0)

        mock_monitoring.record_histogram.assert_called_once_with(
            "test_histogram",
            100.0,
            labels={}
        )

    @patch('app.services.monitoring_helpers.chat_monitoring')
    def test_counter_default_labels(self, mock_monitoring):
        """Counter uses empty dict when labels=None."""
        safe_record_metric("test_counter", metric_type="counter", labels=None)

        mock_monitoring.record_counter.assert_called_once_with(
            "test_counter",
            labels={}
        )

    @patch('app.services.monitoring_helpers.chat_monitoring')
    def test_gauge_default_labels(self, mock_monitoring):
        """Gauge uses empty dict when labels=None."""
        safe_record_metric("test_gauge", metric_type="gauge", value=10.0, labels=None)

        mock_monitoring.record_gauge.assert_called_once_with(
            "test_gauge",
            10.0,
            labels={}
        )

    @patch('app.services.monitoring_helpers.chat_monitoring')
    def test_unknown_metric_type_logs_warning(self, mock_monitoring, caplog):
        """Unknown metric type logs warning but doesn't raise."""
        safe_record_metric("test_metric", metric_type="unknown_type")

        # Should not call any recording methods
        mock_monitoring.record_counter.assert_not_called()
        mock_monitoring.record_gauge.assert_not_called()
        mock_monitoring.record_histogram.assert_not_called()

        # Should log warning
        assert "Unknown metric type: unknown_type" in caplog.text

    @patch('app.services.monitoring_helpers.chat_monitoring')
    def test_counter_exception_graceful_degradation(self, mock_monitoring, caplog):
        """Counter recording failure doesn't raise exception."""
        mock_monitoring.record_counter.side_effect = ConnectionError("Redis unavailable")

        # Should not raise - graceful degradation
        safe_record_metric("test_counter", metric_type="counter")

        # Should log debug message
        assert "Failed to record counter metric 'test_counter'" in caplog.text
        assert "Redis unavailable" in caplog.text

    @patch('app.services.monitoring_helpers.chat_monitoring')
    def test_gauge_exception_graceful_degradation(self, mock_monitoring, caplog):
        """Gauge recording failure doesn't raise exception."""
        mock_monitoring.record_gauge.side_effect = Exception("Monitoring service down")

        # Should not raise
        safe_record_metric("test_gauge", metric_type="gauge", value=5.0)

        # Should log debug message with metric details
        assert "Failed to record gauge metric 'test_gauge'" in caplog.text
        assert "Monitoring service down" in caplog.text

    @patch('app.services.monitoring_helpers.chat_monitoring')
    def test_histogram_exception_graceful_degradation(self, mock_monitoring, caplog):
        """Histogram recording failure doesn't raise exception."""
        mock_monitoring.record_histogram.side_effect = RuntimeError("Prometheus unavailable")

        # Should not raise
        safe_record_metric("test_histogram", metric_type="histogram", value=200.0)

        assert "Failed to record histogram metric 'test_histogram'" in caplog.text
        assert "Prometheus unavailable" in caplog.text

    @patch('app.services.monitoring_helpers.chat_monitoring')
    def test_counter_default_value_not_used(self, mock_monitoring):
        """Counter ignores value parameter (uses default increment)."""
        # Counter should only use labels, not value
        safe_record_metric("test_counter", metric_type="counter", value=99.9, labels={"x": "y"})

        mock_monitoring.record_counter.assert_called_once_with(
            "test_counter",
            labels={"x": "y"}
        )

    @patch('app.services.monitoring_helpers.chat_monitoring')
    def test_multiple_metrics_independent_failures(self, mock_monitoring, caplog):
        """Multiple metric recordings fail independently."""
        # First call fails
        mock_monitoring.record_counter.side_effect = ConnectionError("Failed")
        safe_record_metric("metric1", metric_type="counter")

        # Reset side effect for second call
        mock_monitoring.record_counter.side_effect = None
        safe_record_metric("metric2", metric_type="counter")

        # Both calls attempted
        assert mock_monitoring.record_counter.call_count == 2
        # Only first logged error
        assert "Failed to record counter metric 'metric1'" in caplog.text

    @patch('app.services.monitoring_helpers.chat_monitoring')
    def test_complex_labels_preserved(self, mock_monitoring):
        """Complex label structures passed through correctly."""
        complex_labels = {
            "user_id": "user_123",
            "error_type": "timeout",
            "status_code": "500",
            "endpoint": "/api/v1/query"
        }

        safe_record_metric("api_errors", metric_type="counter", labels=complex_labels)

        mock_monitoring.record_counter.assert_called_once_with(
            "api_errors",
            labels=complex_labels
        )

    @patch('app.services.monitoring_helpers.chat_monitoring')
    def test_production_llm_timeout_scenario(self, mock_monitoring):
        """Real-world LLM timeout error recording scenario."""
        # Simulates app/services/llm_manager.py:341 error handler
        safe_record_metric(
            "llm_timeout_errors",
            metric_type="counter",
            labels={"model": "gpt-4", "timeout_seconds": "40"}
        )

        mock_monitoring.record_counter.assert_called_once()

    @patch('app.services.monitoring_helpers.chat_monitoring')
    def test_production_document_upload_scenario(self, mock_monitoring):
        """Real-world document upload error recording scenario."""
        # Simulates app/router/documents.py:305 error handler
        safe_record_metric(
            "document_upload_errors",
            metric_type="counter",
            labels={"error_type": "500_upload_failed", "file_type": "pdf"}
        )

        mock_monitoring.record_counter.assert_called_once()
