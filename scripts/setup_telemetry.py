#!/usr/bin/env python3
"""
OpenTelemetry setup helper script.

Helps configure and test different observability backends.
"""

import os
import sys
import subprocess
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.config.telemetry import get_quick_setup_configs, print_setup_instructions, TracingBackend
from app.utils.file_operations import atomic_write


def install_exporters():
    """Install additional OpenTelemetry exporters."""
    
    exporters = [
        "opentelemetry-exporter-jaeger",
        "opentelemetry-exporter-zipkin-json", 
        "opentelemetry-exporter-otlp-proto-http",
    ]
    
    print("📦 Installing OpenTelemetry exporters...")
    
    for exporter in exporters:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", exporter])
            print(f"✅ Installed {exporter}")
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to install {exporter}: {e}")


def create_docker_compose():
    """Create a docker-compose.yml for local observability stack."""
    
    docker_compose = """version: '3.8'

services:
  # Jaeger - Distributed Tracing
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"  # Jaeger UI
      - "14268:14268"  # HTTP collector
      - "6831:6831/udp"  # UDP agent
    environment:
      - COLLECTOR_OTLP_ENABLED=true
    networks:
      - observability

  # Zipkin - Alternative tracing backend
  zipkin:
    image: openzipkin/zipkin:latest
    ports:
      - "9411:9411"    # Zipkin UI and API
    networks:
      - observability

  # Grafana Tempo - Distributed tracing
  tempo:
    image: grafana/tempo:latest
    command: [ "-config.file=/etc/tempo.yaml" ]
    volumes:
      - ./tempo.yaml:/etc/tempo.yaml
    ports:
      - "3200:3200"    # Tempo API
    networks:
      - observability

  # Grafana - Observability dashboard
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"    # Grafana UI
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana-storage:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning
    networks:
      - observability

  # Prometheus - Metrics collection
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"    # Prometheus UI
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    networks:
      - observability

  # OpenTelemetry Collector
  otel-collector:
    image: otel/opentelemetry-collector-contrib:latest
    command: ["--config=/etc/otel-collector-config.yaml"]
    volumes:
      - ./otel-collector-config.yaml:/etc/otel-collector-config.yaml
    ports:
      - "4317:4317"    # OTLP gRPC
      - "4318:4318"    # OTLP HTTP
      - "8889:8889"    # Prometheus metrics
    depends_on:
      - jaeger
      - tempo
    networks:
      - observability

volumes:
  grafana-storage:

networks:
  observability:
    driver: bridge
"""

    # Create Tempo configuration
    tempo_config = """server:
  http_listen_port: 3200

distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
        http:
          endpoint: 0.0.0.0:4318

ingester:
  trace_idle_period: 10s
  max_block_bytes: 1_000_000
  max_block_duration: 5m

compactor:
  compaction:
    compaction_window: 1h
    max_compaction_objects: 1000000
    max_block_bytes: 100_000_000
    retention_duration: 1h

storage:
  trace:
    backend: local
    local:
      path: /tmp/tempo/traces
    wal:
      path: /tmp/tempo/wal
"""

    # Create OTEL Collector configuration
    otel_config = """receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:

exporters:
  jaeger:
    endpoint: jaeger:14250
    tls:
      insecure: true
  
  otlp/tempo:
    endpoint: tempo:4317
    tls:
      insecure: true
  
  prometheus:
    endpoint: "0.0.0.0:8889"

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [jaeger, otlp/tempo]
    
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [prometheus]
"""

    # Create Prometheus configuration
    prometheus_config = """global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'ontologic-api'
    static_configs:
      - targets: ['host.docker.internal:8001']
    metrics_path: '/metrics'
  
  - job_name: 'otel-collector'
    static_configs:
      - targets: ['otel-collector:8889']
"""

    # Check for existing files and prompt for overwrite
    existing_files = []
    for filepath in ["docker-compose.yml", "tempo.yaml", "otel-collector-config.yaml", "prometheus.yml"]:
        if Path(filepath).exists():
            existing_files.append(filepath)

    if existing_files and "--force" not in sys.argv:
        print(f"⚠️  The following files already exist: {', '.join(existing_files)}")
        response = input("Overwrite? (y/n): ").strip().lower()
        if response != 'y':
            print("Aborted. Use --force flag to skip this prompt.")
            sys.exit(0)

    # Write files atomically with error handling
    config_files = {
        "docker-compose.yml": docker_compose,
        "tempo.yaml": tempo_config,
        "otel-collector-config.yaml": otel_config,
        "prometheus.yml": prometheus_config,
    }

    try:
        for filepath, content in config_files.items():
            atomic_write(content, Path(filepath))
    except PermissionError as e:
        # PermissionError is more specific than OSError
        print(f"❌ Permission denied writing configuration files: {e}")
        print(f"   Try running with appropriate permissions or in a different directory")
        sys.exit(1)
    except OSError as e:
        print(f"❌ Failed to write configuration files: {e}")
        print(f"   Make sure you have write permissions in the current directory")
        print(f"   Current directory: {Path.cwd()}")
        sys.exit(1)

    # Create Grafana provisioning directory and datasources configuration
    try:
        provisioning_dir = Path("grafana/provisioning/datasources")
        provisioning_dir.mkdir(parents=True, exist_ok=True)

        datasources_yaml = """apiVersion: 1
datasources:
  - name: Tempo
    type: tempo
    access: proxy
    url: http://tempo:3200
    isDefault: false
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
"""
        atomic_write(datasources_yaml, provisioning_dir / "datasources.yaml")
    except PermissionError as e:
        # PermissionError is more specific than OSError
        print(f"❌ Permission denied creating Grafana directory: {e}")
        print(f"   Try running with appropriate permissions")
        sys.exit(1)
    except OSError as e:
        print(f"❌ Failed to create Grafana provisioning directory: {e}")
        print(f"   Make sure you have write permissions in the current directory")
        sys.exit(1)

    print("📁 Created observability stack files:")
    print("   - docker-compose.yml")
    print("   - tempo.yaml")
    print("   - otel-collector-config.yaml")
    print("   - prometheus.yml")
    print("   - grafana/provisioning/datasources/datasources.yaml")
    print()
    print("🚀 To start the stack:")
    print("   docker-compose up -d")
    print()
    print("🔗 Access URLs:")
    print("   - Jaeger UI:  http://localhost:16686")
    print("   - Zipkin UI:  http://localhost:9411")
    print("   - Grafana:    http://localhost:3000 (admin/admin)")
    print("   - Prometheus: http://localhost:9090")


def show_env_examples():
    """Show environment variable examples for different backends."""
    
    examples = {
        "Jaeger (Local)": [
            "export OTEL_BACKENDS=jaeger",
            "export JAEGER_ENDPOINT=http://localhost:14268/api/traces",
        ],
        
        "Jaeger (Docker)": [
            "export OTEL_BACKENDS=jaeger",
            "export JAEGER_ENDPOINT=http://jaeger:14268/api/traces",
        ],
        
        "Zipkin": [
            "export OTEL_BACKENDS=zipkin", 
            "export ZIPKIN_ENDPOINT=http://localhost:9411/api/v2/spans",
        ],
        
        "Grafana Tempo": [
            "export OTEL_BACKENDS=otlp-grpc",
            "export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317",
        ],
        
        "Console Debug": [
            "export OTEL_BACKENDS=console",
        ],
        
        "Multiple Backends": [
            "export OTEL_BACKENDS=console,jaeger",
            "export JAEGER_ENDPOINT=http://localhost:14268/api/traces",
        ],
        
        "Honeycomb (SaaS)": [
            "export OTEL_BACKENDS=honeycomb",
            "export HONEYCOMB_API_KEY=your_api_key_here",
            "export HONEYCOMB_DATASET=ontologic-api",
        ],
        
        "Production (with sampling)": [
            "export OTEL_BACKENDS=otlp-grpc",
            "export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317",
            "export OTEL_SAMPLING_RATE=0.1",
        ],
    }
    
    print("🔧 Environment Variable Examples:")
    print("=" * 50)
    
    for name, vars in examples.items():
        print(f"\n{name}:")
        for var in vars:
            print(f"  {var}")


def test_configuration():
    """Test the current OpenTelemetry configuration."""
    
    print("🧪 Testing OpenTelemetry configuration...")
    
    try:
        from app.config.telemetry import TracingConfig as TelemetryConfig
        config = TelemetryConfig.from_environment()
        
        print(f"✅ Service: {config.service_name}")
        print(f"✅ Version: {config.service_version}")
        print(f"✅ Environment: {config.environment}")
        print(f"✅ Enabled: {config.enabled}")
        print(f"✅ Backends: {[b.value for b in config.backends]}")
        
        # Test tracing initialization
        from app.core.tracing import TracingConfig
        TracingConfig.initialize(config=config)
        
        print("✅ Tracing initialization successful")
        
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")


def main():
    """Main CLI interface."""
    
    if len(sys.argv) < 2:
        print("🔭 OpenTelemetry Setup Helper")
        print("Usage: python setup_telemetry.py <command>")
        print()
        print("Commands:")
        print("  install      Install OpenTelemetry exporters")
        print("  docker       Create docker-compose.yml for observability stack")
        print("  examples     Show environment variable examples")
        print("  test         Test current configuration")
        print("  instructions Print detailed setup instructions")
        return
    
    command = sys.argv[1]
    
    if command == "install":
        install_exporters()
    elif command == "docker":
        create_docker_compose()
    elif command == "examples":
        show_env_examples()
    elif command == "test":
        test_configuration()
    elif command == "instructions":
        print_setup_instructions()
    else:
        print(f"Unknown command: {command}")


if __name__ == "__main__":
    main()