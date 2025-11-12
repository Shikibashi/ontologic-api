"""
OpenTelemetry tracing configuration for distributed tracing support.

Provides automatic instrumentation for FastAPI endpoints and custom spans
for critical operations like LLM calls, Qdrant queries, and cache operations.

Supports multiple observability backends:
- Jaeger (local and remote)
- Zipkin 
- Honeycomb
- Grafana Tempo
- Elastic APM
- Console (debugging)
- OTLP (generic)
"""

import os
from typing import Optional, List
from functools import wraps
from contextlib import asynccontextmanager
import asyncio
import inspect
from types import SimpleNamespace


# Handle optional OpenTelemetry dependencies gracefully
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.trace import Status, StatusCode
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    # Create stub classes/functions when OpenTelemetry is not available
    OPENTELEMETRY_AVAILABLE = False
    trace = None
    TracerProvider = None
    BatchSpanProcessor = None
    ConsoleSpanExporter = None
    Resource = None
    SERVICE_NAME = "service.name"
    SERVICE_VERSION = "service.version"
    FastAPIInstrumentor = None
    Status = None
    StatusCode = None
    TraceContextTextMapPropagator = None

from app.core.logger import log

# Handle optional telemetry config
try:
    from app.config.telemetry import TracingConfig as TelemetryConfig, TracingBackend
except ImportError:
    TelemetryConfig = None
    TracingBackend = None

# Import exporters as needed
try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as OTLPGrpcSpanExporter
except ImportError:
    OTLPGrpcSpanExporter = None

try:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as OTLPHttpSpanExporter
except ImportError:
    OTLPHttpSpanExporter = None

try:
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
except ImportError:
    JaegerExporter = None

try:
    from opentelemetry.exporter.zipkin.json import ZipkinExporter
except ImportError:
    ZipkinExporter = None


class TracingConfig:
    """
    OpenTelemetry tracing configuration and setup.

    Supports multiple export backends:
    - Console (development/debugging)
    - Jaeger (local and remote)
    - Zipkin
    - Honeycomb
    - Grafana Tempo
    - Elastic APM
    - OTLP (generic gRPC/HTTP)
    
    Gracefully handles missing OpenTelemetry dependencies.
    """

    _tracer_provider: Optional = None
    _instrumentor: Optional = None

    @classmethod
    def initialize(
        cls,
        config: Optional[TelemetryConfig] = None,
        service_name: str = "ontologic-api",
        service_version: str = "1.0.0",
        enabled: bool = True,
        export_to_console: bool = False,
        otlp_endpoint: Optional[str] = None
    ) -> None:
        """
        Initialize OpenTelemetry tracing with support for multiple backends.

        Args:
            config: TelemetryConfig object with full configuration
            service_name: Name of the service for tracing (fallback)
            service_version: Version of the service (fallback)
            enabled: Whether tracing is enabled (fallback)
            export_to_console: Export traces to console (fallback)
            otlp_endpoint: OTLP collector endpoint (fallback)

        Environment Variables:
            OTEL_ENABLED: Enable/disable tracing (default: true)
            OTEL_SERVICE_NAME: Service name (default: ontologic-api)
            OTEL_BACKENDS: Comma-separated list of backends (default: console)
            JAEGER_ENDPOINT: Jaeger collector endpoint
            ZIPKIN_ENDPOINT: Zipkin collector endpoint
            HONEYCOMB_API_KEY: Honeycomb API key
            TEMPO_ENDPOINT: Grafana Tempo endpoint
            OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint for trace export
        """
        # Check if OpenTelemetry is available
        if not OPENTELEMETRY_AVAILABLE:
            log.info("OpenTelemetry not available - tracing disabled")
            return
        
        # Check if tracing is disabled
        if not enabled or os.getenv("OTEL_ENABLED", "true").lower() == "false":
            log.info("OpenTelemetry tracing disabled via configuration")
            return
        # Use provided config or create from environment
        if config is None:
            if TelemetryConfig is None:
                log.warning("TelemetryConfig not available - tracing disabled")
                return
            config = TelemetryConfig.from_environment() if TelemetryConfig else {}

        # Wrap dict configs for attribute-style access
        if isinstance(config, dict):
            config = SimpleNamespace(**config)  # type: ignore

        # Ensure required attributes safely before any access
        defaults = {
            'enabled': enabled,
            'service_name': service_name,
            'service_version': service_version,
            'backends': [],
            'otlp_endpoint': otlp_endpoint,
            'resource_attributes': {},
            'environment': os.getenv('ENVIRONMENT', 'dev')
        }
        missing = []
        for k, v in defaults.items():
            if not hasattr(config, k):
                setattr(config, k, v)
                missing.append(k)
        if missing:
            log.warning(f"Tracing config missing attributes {missing} - defaults applied")

        # Normalize backends (handle simple strings)
        if getattr(config, 'backends', None) and TracingBackend:
            normalized = []
            for b in config.backends:
                if isinstance(b, TracingBackend):
                    normalized.append(b)
                else:
                    try:
                        normalized.append(TracingBackend[b.upper()])
                    except Exception:
                        continue
            config.backends = normalized

        if export_to_console and TracingBackend and TracingBackend.CONSOLE not in config.backends:
            config.backends.append(TracingBackend.CONSOLE)
        if otlp_endpoint and not getattr(config, 'otlp_endpoint', None):
            config.otlp_endpoint = otlp_endpoint

        if not getattr(config, 'enabled', False):
            log.info("OpenTelemetry tracing is disabled")
            return

        try:
            # Create resource with service information
            resource_attrs = {
                SERVICE_NAME: config.service_name,
                SERVICE_VERSION: config.service_version,
                "environment": config.environment,
            }
            resource_attrs.update(config.resource_attributes)
            resource = Resource.create(resource_attrs)

            # Create tracer provider
            cls._tracer_provider = TracerProvider(resource=resource)

            # Configure exporters based on backends
            exporters_configured = []
            
            for backend in config.backends:
                exporter = cls._create_exporter(backend, config)
                if exporter:
                    processor = BatchSpanProcessor(exporter)
                    cls._tracer_provider.add_span_processor(processor)
                    exporters_configured.append(backend.value)

            # Set as global tracer provider
            trace.set_tracer_provider(cls._tracer_provider)

            log.info(f"OpenTelemetry tracing initialized for service: {config.service_name}")
            log.info(f"Configured exporters: {', '.join(exporters_configured)}")

        except Exception as e:
            log.error(f"Failed to initialize OpenTelemetry tracing: {e}", exc_info=True)

    @classmethod
    def _create_exporter(cls, backend: TracingBackend, config: TelemetryConfig):
        """Create an exporter for the specified backend."""
        try:
            if backend == TracingBackend.CONSOLE:
                log.info("Configuring Console exporter for debugging")
                return ConsoleSpanExporter()
            
            elif backend == TracingBackend.JAEGER:
                if not JaegerExporter:
                    log.warning("Jaeger exporter not available. Install: pip install opentelemetry-exporter-jaeger")
                    return None
                
                if config.jaeger_endpoint:
                    log.info(f"Configuring Jaeger HTTP collector exporter: {config.jaeger_endpoint}")
                    return JaegerExporter(collector_endpoint=config.jaeger_endpoint)
                else:
                    log.info(f"Configuring Jaeger UDP agent exporter: {config.jaeger_agent_host}:{config.jaeger_agent_port}")
                    return JaegerExporter(
                        agent_host_name=config.jaeger_agent_host,
                        agent_port=config.jaeger_agent_port,
                    )
            
            elif backend == TracingBackend.ZIPKIN:
                if not ZipkinExporter:
                    log.warning("Zipkin exporter not available. Install: pip install opentelemetry-exporter-zipkin")
                    return None
                
                if not config.zipkin_endpoint:
                    log.warning("Zipkin endpoint not configured. Set ZIPKIN_ENDPOINT environment variable")
                    return None
                
                log.info(f"Configuring Zipkin exporter: {config.zipkin_endpoint}")
                return ZipkinExporter(endpoint=config.zipkin_endpoint)
            
            elif backend == TracingBackend.HONEYCOMB:
                if not OTLPHttpSpanExporter:
                    log.warning("OTLP HTTP exporter not available for Honeycomb")
                    return None
                
                if not config.honeycomb_api_key:
                    log.warning("Honeycomb API key not configured. Set HONEYCOMB_API_KEY environment variable")
                    return None
                
                headers = {
                    "x-honeycomb-team": config.honeycomb_api_key,
                    "x-honeycomb-dataset": config.honeycomb_dataset,
                }
                log.info(f"Configuring Honeycomb exporter for dataset: {config.honeycomb_dataset}")
                return OTLPHttpSpanExporter(
                    endpoint="https://api.honeycomb.io/v1/traces",
                    headers=headers,
                )
            
            elif backend == TracingBackend.TEMPO:
                if not OTLPGrpcSpanExporter:
                    log.warning("OTLP gRPC exporter not available for Tempo")
                    return None
                
                if not config.tempo_endpoint:
                    log.warning("Tempo endpoint not configured. Set TEMPO_ENDPOINT environment variable")
                    return None
                
                endpoint = f"{config.tempo_endpoint}/api/traces"
                log.info(f"Configuring Grafana Tempo exporter: {endpoint}")
                return OTLPGrpcSpanExporter(endpoint=endpoint, insecure=config.otlp_insecure)
            
            elif backend == TracingBackend.ELASTIC:
                if not OTLPHttpSpanExporter:
                    log.warning("OTLP HTTP exporter not available for Elastic APM")
                    return None
                
                if not config.elastic_apm_endpoint:
                    log.warning("Elastic APM endpoint not configured. Set ELASTIC_APM_ENDPOINT environment variable")
                    return None
                
                headers = {}
                if config.elastic_apm_token:
                    headers["Authorization"] = f"Bearer {config.elastic_apm_token}"
                
                log.info(f"Configuring Elastic APM exporter: {config.elastic_apm_endpoint}")
                return OTLPHttpSpanExporter(
                    endpoint=f"{config.elastic_apm_endpoint}/v1/traces",
                    headers=headers,
                )
            
            elif backend == TracingBackend.OTLP_GRPC:
                if not OTLPGrpcSpanExporter:
                    log.warning("OTLP gRPC exporter not available")
                    return None
                
                if not config.otlp_endpoint:
                    log.warning("OTLP endpoint not configured. Set OTEL_EXPORTER_OTLP_ENDPOINT environment variable")
                    return None
                
                log.info(f"Configuring OTLP gRPC exporter: {config.otlp_endpoint}")
                return OTLPGrpcSpanExporter(
                    endpoint=config.otlp_endpoint,
                    headers=config.otlp_headers,
                    insecure=config.otlp_insecure,
                )
            
            elif backend == TracingBackend.OTLP_HTTP:
                if not OTLPHttpSpanExporter:
                    log.warning("OTLP HTTP exporter not available")
                    return None
                
                if not config.otlp_endpoint:
                    log.warning("OTLP endpoint not configured. Set OTEL_EXPORTER_OTLP_ENDPOINT environment variable")
                    return None
                
                log.info(f"Configuring OTLP HTTP exporter: {config.otlp_endpoint}")
                return OTLPHttpSpanExporter(
                    endpoint=config.otlp_endpoint,
                    headers=config.otlp_headers,
                )
            
            else:
                log.warning(f"Unknown tracing backend: {backend}")
                return None
                
        except Exception as e:
            log.error(f"Failed to create {backend} exporter: {e}", exc_info=True)
            return None

    @classmethod
    def instrument_fastapi(cls, app) -> None:
        """
        Instrument FastAPI application with automatic tracing.

        Args:
            app: FastAPI application instance
        """
        if cls._tracer_provider is None:
            log.warning("Skipping FastAPI instrumentation: tracing not initialized")
            return

        try:
            cls._instrumentor = FastAPIInstrumentor.instrument_app(app)
            log.info("FastAPI automatic instrumentation enabled")
        except Exception as e:
            log.error(f"Failed to instrument FastAPI with OpenTelemetry: {e}", exc_info=True)

    @classmethod
    def shutdown(cls) -> None:
        """Shutdown tracing and flush any pending spans."""
        if cls._tracer_provider:
            try:
                cls._tracer_provider.shutdown()
                log.info("OpenTelemetry tracing shutdown complete")
            except Exception as e:
                log.warning(f"Error during tracing shutdown: {e}")

    @classmethod
    def get_tracer(cls, name: str = __name__):
        """
        Get a tracer for creating custom spans.

        Args:
            name: Name of the tracer (typically __name__ of the module)

        Returns:
            Tracer instance for creating spans
        """
        return trace.get_tracer(name)


# Convenience function for creating custom spans
def create_span(name: str, attributes: Optional[dict] = None):
    """
    Create a custom span for tracing operations.

    Usage:
        with create_span("llm_query", {"model": "qwen3:8b"}):
            result = await llm.query(prompt)

    Args:
        name: Name of the span
        attributes: Optional attributes to add to the span

    Returns:
        Context manager for the span
    """
    tracer = TracingConfig.get_tracer()
    span = tracer.start_span(name)

    if attributes:
        for key, value in attributes.items():
            span.set_attribute(key, value)

    return span


def trace_async_operation(span_name: str, attributes: Optional[dict] = None):
    """
    Decorator for tracing async operations with automatic span management.
    
    Supports both async coroutines and async generators.

    Usage:
        @trace_async_operation("llm_query", {"model": "qwen3:8b"})
        async def aquery(self, question: str):
            ...
            
        @trace_async_operation("llm_stream", {"model": "qwen3:8b"})
        async def aquery_stream(self, question: str):
            async for chunk in stream:
                yield chunk

    Args:
        span_name: Name of the span
        attributes: Optional attributes to add to the span

    Returns:
        Decorated async function with automatic span creation
    """
    def decorator(func):
        if inspect.isasyncgenfunction(func):
            # Handle async generator functions
            @wraps(func)
            async def async_gen_wrapper(*args, **kwargs):
                tracer = TracingConfig.get_tracer(func.__module__)
                
                with tracer.start_as_current_span(span_name) as span:
                    # Add static attributes
                    if attributes:
                        for key, value in attributes.items():
                            span.set_attribute(key, str(value))
                    
                    # Add function metadata
                    span.set_attribute("function.name", func.__name__)
                    span.set_attribute("function.module", func.__module__)
                    span.set_attribute("function.type", "async_generator")
                    
                    try:
                        async for item in func(*args, **kwargs):
                            yield item
                        span.set_status(Status(StatusCode.OK))
                    except Exception as e:
                        # Record exception in span
                        span.set_status(Status(StatusCode.ERROR, str(e)))
                        span.record_exception(e)
                        raise
            
            return async_gen_wrapper
        else:
            # Handle regular async coroutine functions
            @wraps(func)
            async def wrapper(*args, **kwargs):
                tracer = TracingConfig.get_tracer(func.__module__)

                with tracer.start_as_current_span(span_name) as span:
                    # Add static attributes
                    if attributes:
                        for key, value in attributes.items():
                            span.set_attribute(key, str(value))

                    # Add function metadata
                    span.set_attribute("function.name", func.__name__)
                    span.set_attribute("function.module", func.__module__)
                    span.set_attribute("function.type", "async_coroutine")

                    try:
                        result = await func(*args, **kwargs)
                        span.set_status(Status(StatusCode.OK))
                        return result
                    except Exception as e:
                        # Record exception in span
                        span.set_status(Status(StatusCode.ERROR, str(e)))
                        span.record_exception(e)
                        raise

            return wrapper
    return decorator


def get_current_trace_context() -> dict:
    """
    Get current trace and span IDs for log correlation.

    Returns:
        Dictionary with trace_id and span_id (empty strings if no active span)
    """
    span = trace.get_current_span()
    if span and span.is_recording():
        span_context = span.get_span_context()
        return {
            "trace_id": format(span_context.trace_id, '032x'),
            "span_id": format(span_context.span_id, '016x'),
        }
    return {"trace_id": "", "span_id": ""}  # Consistent structure


def add_span_event(event_name: str, attributes: Optional[dict] = None):
    """
    Add an event to the current span.

    Usage:
        add_span_event("cache_hit", {"cache_type": "embedding"})

    Args:
        event_name: Name of the event
        attributes: Optional attributes for the event
    """
    span = trace.get_current_span()
    if span and span.is_recording():
        span.add_event(event_name, attributes=attributes or {})


def get_current_span():
    """Return the current active span if tracing is enabled."""
    if not OPENTELEMETRY_AVAILABLE or trace is None:
        return None
    return trace.get_current_span()


def set_span_attributes(attributes: dict):
    """
    Add attributes to the current span.

    Usage:
        set_span_attributes({"model": "qwen3:8b", "temperature": 0.3})

    Args:
        attributes: Dictionary of attributes to add
    """
    span = trace.get_current_span()
    if span and span.is_recording():
        for key, value in attributes.items():
            span.set_attribute(key, str(value))

# Stub functions when OpenTelemetry is not available
if not OPENTELEMETRY_AVAILABLE:
    def trace_async_operation(span_name: str, attributes: Optional[dict] = None):
        """Stub decorator when OpenTelemetry is not available."""
        def decorator(func):
            return func
        return decorator
    
    def get_current_span():
        """Stub span accessor when OpenTelemetry is not available."""
        return None

    def set_span_attributes(attributes: dict) -> None:
        """Stub function when OpenTelemetry is not available."""
        pass
    
    def add_span_event(name: str, attributes: Optional[dict] = None) -> None:
        """Stub function when OpenTelemetry is not available."""
        pass
    
    class TracingConfig:
        """Stub TracingConfig when OpenTelemetry is not available."""
        
        @classmethod
        def initialize(cls, **kwargs) -> None:
            """Stub initialize method."""
            log.info("OpenTelemetry not available - tracing disabled")
        
        @classmethod
        def instrument_fastapi(cls, app) -> None:
            """Stub FastAPI instrumentation."""
            pass
        
        @classmethod
        def shutdown(cls) -> None:
            """Stub shutdown method."""
            pass
