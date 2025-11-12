import logging
import os
from typing import Any

import uvicorn


log_level = os.environ.get("LOG_LEVEL", "INFO")

log_config = uvicorn.config.LOGGING_CONFIG
log_config["formatters"]["access"]["fmt"] = '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d %(funcName)s - %(message)s'
log_config["formatters"]["default"]["fmt"] = '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d %(funcName)s - %(message)s'


class ShortPathFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.shortpathname = os.path.relpath(record.pathname, start=os.getcwd())
        return True


class TraceContextFilter(logging.Filter):
    """
    Add OpenTelemetry trace context to log records for correlation.

    Adds trace_id and span_id to every log record when available.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Add OpenTelemetry trace context to log record for correlation.

        Note: Import is done at runtime (not module-level) to avoid circular
        dependency: tracing.py imports logger.py, and this method imports
        from tracing.py. This is safe because filter() is only called after
        both modules are fully initialized.
        """
        try:
            from app.core.tracing import get_current_trace_context
            trace_context = get_current_trace_context()
            record.trace_id = trace_context.get('trace_id', '')
            record.span_id = trace_context.get('span_id', '')
        except Exception:
            # Graceful degradation if tracing not available
            record.trace_id = ''
            record.span_id = ''
        return True


def logger() -> logging.Logger:
    """Get configured logger instance with trace correlation."""
    logger = logging.getLogger("ontologic-api")

    if not logger.hasHandlers():
        handler = logging.StreamHandler()
        handler.addFilter(ShortPathFilter())
        handler.addFilter(TraceContextFilter())
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - [trace_id=%(trace_id)s span_id=%(span_id)s] - %(name)s/%(shortpathname)s:%(lineno)d %(funcName)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.setLevel(log_level)
    return logger

log = logger()


def get_log_directory() -> "Path":
    """
    Get log directory path from settings with graceful fallback.

    Returns:
        Path: Log directory from settings or fallback to current directory on failure

    Examples:
        >>> from app.core.logger import get_log_directory
        >>> log_dir = get_log_directory()
        >>> file_handler = logging.FileHandler(log_dir / "app.log")
    """
    from pathlib import Path
    from app.config.settings import get_settings

    try:
        settings = get_settings()
        log_dir = Path(settings.log_dir)
    except (ImportError, AttributeError, KeyError) as e:
        # Expected configuration errors - use fallback
        log.warning(
            f"Could not read log_dir from settings: {type(e).__name__}: {e}. Using fallback 'logs'."
        )
        log_dir = Path("logs")
    except Exception as e:
        # Unexpected errors - log but still fallback gracefully
        log.error(
            f"Unexpected error reading log_dir: {type(e).__name__}: {e}. Using fallback 'logs'.",
            exc_info=True
        )
        log_dir = Path("logs")

    # Create directory with fallback to current directory on failure
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError) as e:
        log.warning(
            f"Failed to create log directory '{log_dir}': {type(e).__name__}: {e}. "
            f"Falling back to current directory for logs."
        )
        log_dir = Path(".")

    return log_dir
