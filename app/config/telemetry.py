"""
OpenTelemetry configuration for various observability backends.

Supports multiple exporters:
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
from dataclasses import dataclass
from enum import Enum

from app.core.logger import log


class TracingBackend(str, Enum):
    """Supported tracing backends."""
    CONSOLE = "console"
    JAEGER = "jaeger"
    ZIPKIN = "zipkin"
    HONEYCOMB = "honeycomb"
    TEMPO = "tempo"
    ELASTIC = "elastic"
    OTLP_GRPC = "otlp-grpc"
    OTLP_HTTP = "otlp-http"


@dataclass
class TracingConfig:
    """OpenTelemetry tracing configuration."""
    
    # Basic settings
    enabled: bool = True
    service_name: str = "ontologic-api"
    service_version: str = "1.0.0"
    environment: str = "development"
    
    # Backends to export to
    backends: List[TracingBackend] = None
    
    # Jaeger settings
    jaeger_endpoint: Optional[str] = None
    jaeger_agent_host: str = "localhost"
    jaeger_agent_port: int = 6831
    
    # Zipkin settings
    zipkin_endpoint: Optional[str] = None
    
    # Honeycomb settings
    honeycomb_api_key: Optional[str] = None
    honeycomb_dataset: str = "ontologic-api"
    
    # Grafana Tempo settings
    tempo_endpoint: Optional[str] = None
    
    # Elastic APM settings
    elastic_apm_endpoint: Optional[str] = None
    elastic_apm_token: Optional[str] = None
    
    # Generic OTLP settings
    otlp_endpoint: Optional[str] = None
    otlp_headers: Optional[dict] = None
    otlp_insecure: bool = True
    
    # Sampling settings
    sampling_rate: float = 1.0  # 1.0 = 100% sampling
    
    # Resource attributes
    resource_attributes: Optional[dict] = None
    
    def __post_init__(self):
        """Set defaults and validate configuration."""
        if self.backends is None:
            self.backends = [TracingBackend.CONSOLE]
        
        if self.resource_attributes is None:
            self.resource_attributes = {}

        if not 0.0 <= self.sampling_rate <= 1.0:
            raise ValueError(f"sampling_rate must be between 0.0 and 1.0, got {self.sampling_rate}")
    
    @classmethod
    def from_environment(cls) -> "TracingConfig":
        """Create configuration from environment variables."""
        
        # Parse backends from environment
        backends_str = os.getenv("OTEL_BACKENDS", "console")
        configured_backends = [b.strip() for b in backends_str.split(",")]
        backends: List[TracingBackend] = []
        valid_backend_names = [backend.value for backend in TracingBackend]

        for backend_name in configured_backends:
            if not backend_name:
                continue
            try:
                backends.append(TracingBackend(backend_name))
            except ValueError:
                log.warning(
                    "Invalid tracing backend '%s' ignored. Valid backends: %s",
                    backend_name,
                    valid_backend_names,
                )

        if not backends:
            valid_list = ", ".join(valid_backend_names)
            raise ValueError(f"No valid tracing backends configured. Set OTEL_BACKENDS to one or more of: {valid_list}")
        
        # Resource attributes from environment
        resource_attributes = {}
        if deployment_env := os.getenv("DEPLOYMENT_ENVIRONMENT"):
            resource_attributes["deployment.environment"] = deployment_env
        if k8s_namespace := os.getenv("KUBERNETES_NAMESPACE"):
            resource_attributes["k8s.namespace.name"] = k8s_namespace
        if k8s_pod := os.getenv("KUBERNETES_POD_NAME"):
            resource_attributes["k8s.pod.name"] = k8s_pod
        
        return cls(
            enabled=os.getenv("OTEL_ENABLED", "true").lower() == "true",
            service_name=os.getenv("OTEL_SERVICE_NAME", "ontologic-api"),
            service_version=os.getenv("OTEL_SERVICE_VERSION", "1.0.0"),
            environment=os.getenv("ENVIRONMENT", "development"),
            backends=backends,
            
            # Jaeger
            jaeger_endpoint=os.getenv("JAEGER_ENDPOINT"),
            jaeger_agent_host=os.getenv("JAEGER_AGENT_HOST", "localhost"),
            jaeger_agent_port=int(os.getenv("JAEGER_AGENT_PORT", "6831")),
            
            # Zipkin
            zipkin_endpoint=os.getenv("ZIPKIN_ENDPOINT"),
            
            # Honeycomb
            honeycomb_api_key=os.getenv("HONEYCOMB_API_KEY"),
            honeycomb_dataset=os.getenv("HONEYCOMB_DATASET", "ontologic-api"),
            
            # Tempo
            tempo_endpoint=os.getenv("TEMPO_ENDPOINT"),
            
            # Elastic APM
            elastic_apm_endpoint=os.getenv("ELASTIC_APM_ENDPOINT"),
            elastic_apm_token=os.getenv("ELASTIC_APM_TOKEN"),
            
            # Generic OTLP
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
            otlp_insecure=os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").lower() == "true",
            
            # Sampling
            sampling_rate=float(os.getenv("OTEL_SAMPLING_RATE", "1.0")),
            
            # Resource attributes
            resource_attributes=resource_attributes,
        )


def get_quick_setup_configs() -> dict:
    """Get quick setup configurations for popular backends."""
    
    return {
        "jaeger_local": TracingConfig(
            backends=[TracingBackend.JAEGER],
            jaeger_endpoint="http://localhost:14268/api/traces",
            service_name="ontologic-api"
        ),
        
        "jaeger_docker": TracingConfig(
            backends=[TracingBackend.JAEGER],
            jaeger_endpoint="http://jaeger:14268/api/traces",
            service_name="ontologic-api"
        ),
        
        "zipkin_local": TracingConfig(
            backends=[TracingBackend.ZIPKIN],
            zipkin_endpoint="http://localhost:9411/api/v2/spans",
            service_name="ontologic-api"
        ),
        
        "tempo_local": TracingConfig(
            backends=[TracingBackend.TEMPO],
            tempo_endpoint="http://localhost:3200",
            service_name="ontologic-api"
        ),
        
        "console_debug": TracingConfig(
            backends=[TracingBackend.CONSOLE],
            service_name="ontologic-api"
        ),
        
        "multi_backend": TracingConfig(
            backends=[TracingBackend.CONSOLE, TracingBackend.JAEGER],
            jaeger_endpoint="http://localhost:14268/api/traces",
            service_name="ontologic-api"
        ),
    }


def print_setup_instructions():
    """Print setup instructions for various backends."""
    
    instructions = """
🔭 OpenTelemetry Backend Setup Instructions

## Jaeger (Recommended for Development)

### Docker Compose:
```yaml
version: '3.8'
services:
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"  # Jaeger UI
      - "14268:14268"  # HTTP collector
    environment:
      - COLLECTOR_OTLP_ENABLED=true
```

### Environment Variables:
```bash
export OTEL_BACKENDS=jaeger
export JAEGER_ENDPOINT=http://localhost:14268/api/traces
```

### Access: http://localhost:16686

## Zipkin

### Docker:
```bash
docker run -d -p 9411:9411 openzipkin/zipkin
```

### Environment Variables:
```bash
export OTEL_BACKENDS=zipkin
export ZIPKIN_ENDPOINT=http://localhost:9411/api/v2/spans
```

### Access: http://localhost:9411

## Grafana Tempo + Grafana

### Docker Compose:
```yaml
version: '3.8'
services:
  tempo:
    image: grafana/tempo:latest
    command: [ "-config.file=/etc/tempo.yaml" ]
    ports:
      - "3200:3200"
      - "4317:4317"  # OTLP gRPC
  
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
```

### Environment Variables:
```bash
export OTEL_BACKENDS=otlp-grpc
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

## Honeycomb (SaaS)

### Environment Variables:
```bash
export OTEL_BACKENDS=honeycomb
export HONEYCOMB_API_KEY=your_api_key
export HONEYCOMB_DATASET=ontologic-api
```

## Multiple Backends

### Environment Variables:
```bash
export OTEL_BACKENDS=console,jaeger
export JAEGER_ENDPOINT=http://localhost:14268/api/traces
```

## Production Setup

### Kubernetes with OTEL Collector:
```bash
export OTEL_BACKENDS=otlp-grpc
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
export OTEL_SAMPLING_RATE=0.1  # 10% sampling for production
```
"""
    
    print(instructions)


if __name__ == "__main__":
    print_setup_instructions()
