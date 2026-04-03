# Observability — OpenTelemetry & Prometheus

This document describes how metrics and tracing are configured across the podiumd chart components.

---

## Architecture Overview

| Component | OTEL support | Prometheus scrape | Collector endpoint |
|---|---|---|---|
| openzaak | ✅ `settings.otel.*` | ❌ via OTEL only | grpc :4317 |
| openklant | ✅ `settings.otel.*` | ❌ via OTEL only | grpc :4317 |
| openformulieren | ✅ `settings.otel.*` | ❌ via OTEL only | grpc :4317 |
| opennotificaties | ✅ `settings.otel.*` | ❌ via OTEL only | grpc :4317 |
| objecten | ✅ `settings.otel.*` | ❌ via OTEL only | grpc :4317 |
| objecttypen | ✅ `settings.otel.*` | ❌ via OTEL only | grpc :4317 |
| zac | ✅ `opentelemetry_zaakafhandelcomponent.*` + `javaOptions` | ❌ via OTEL only | grpc :4317 |
| keycloak | ✅ `additionalOptions: metrics-enabled` | ✅ pod annotations port 9000 `/metrics` | — |

The Maykin Django apps (openzaak, openklant, etc.) do **not** expose a direct Prometheus scrape endpoint. Metrics are pushed via OTLP to a collector, which can then forward to Prometheus.

---

## OTEL Configuration — Maykin Apps

All Maykin subcharts (openzaak, openklant, openformulieren, opennotificaties, objecten, objecttypen) share the same `settings.otel` schema.

### Available keys per component

```yaml
<component>:
  settings:
    otel:
      disabled: true              # Set to false to enable OTEL
      exporterOtlpEndpoint: ""    # e.g. http://monitoring-opentelemetry-collector.monitoring.svc.cluster.local:4317
      exporterOtlpProtocol: grpc  # grpc or http/protobuf
      exporterOtlpMetricsInsecure: false  # true if endpoint is not TLS-protected
      exporterOtlpHeaders: []     # optional: [{key: Authorization, value: Basic ...}]
      resourceAttributes: []      # optional: [{key: env, value: prod}]
      metricExportInterval: 60000 # ms, how often metrics are exported
      metricExportTimeout: 10000  # ms, export request timeout
```

### Current state in `values.yaml`

| Component | `disabled` | endpoint | protocol | insecure | interval | timeout |
|---|---|---|---|---|---|---|
| openzaak | `true` | ❌ not set | ❌ not set | ❌ not set | ❌ not set | ❌ not set |
| openklant | `true` | ❌ not set | ❌ not set | ❌ not set | ❌ not set | ❌ not set |
| openformulieren | ❌ no otel block | ❌ not set | ❌ not set | ❌ not set | ❌ not set | ❌ not set |
| opennotificaties | `true` | ❌ not set | ❌ not set | ❌ not set | ❌ not set | ❌ not set |
| objecten | `true` | ❌ not set | ❌ not set | ❌ not set | ❌ not set | ❌ not set |
| objecttypen | `true` | ❌ not set | ❌ not set | ❌ not set | ❌ not set | ❌ not set |

> **Note:** On `podiumd-johnb00-aks`, all these components have OTEL **enabled** (`OTEL_SDK_DISABLED: False`) and are sending to `http://monitoring-opentelemetry-collector.monitoring.svc.cluster.local:4317` via grpc with `OTEL_EXPORTER_OTLP_METRICS_INSECURE: True`. These settings are applied via environment-specific values files, **not** from the chart defaults.

To enable OTEL for an environment, override in your env values file:

```yaml
openzaak:
  settings:
    otel:
      disabled: false
      exporterOtlpEndpoint: "http://monitoring-opentelemetry-collector.monitoring.svc.cluster.local:4317"
      exporterOtlpProtocol: grpc
      exporterOtlpMetricsInsecure: true
      metricExportInterval: 60000
      metricExportTimeout: 10000
# repeat for openklant, openformulieren, opennotificaties, objecten, objecttypen
```

---

## OTEL Configuration — ZAC

ZAC uses two mechanisms:

### 1. `opentelemetry_zaakafhandelcomponent` (for the built-in collector sidecar)

```yaml
zac:
  opentelemetry_zaakafhandelcomponent:
    disabled: "-true"   # "-true" disables, "" enables
    endpoint: ""        # e.g. http://monitoring-opentelemetry-collector.monitoring.svc.cluster.local:4317
```

### 2. `javaOptions` (for JVM-level OTEL agent flags)

```yaml
zac:
  javaOptions: >-
    -Xmx1024m -Xms1024m -Xlog:gc::time,uptime
    -Dotel.service.name=zac
    -Dotel.exporter.otlp.endpoint=http://monitoring-opentelemetry-collector.monitoring.svc.cluster.local:4317
    -Dotel.exporter.otlp.protocol=grpc
    -Dotel.traces.exporter=otlp
    -Dotel.metrics.exporter=none
    -Dotel.logs.exporter=none
```

### Current state on `podiumd-johnb00-aks`

ZAC has OTEL enabled via `_JAVA_OPTIONS` with:
- Endpoint: `http://monitoring-opentelemetry-collector.monitoring.svc.cluster.local:4317`
- Protocol: grpc
- Traces: exported via OTLP
- Metrics: **none** (disabled)
- Logs: **none** (disabled)

This is set via env values file, not chart defaults. The chart default is `javaOptions: ""`.

---

## Prometheus Scraping — Keycloak

Keycloak is the only component with a direct Prometheus scrape endpoint.

Metrics are enabled via `additionalOptions` and exposed on port `9000` at `/metrics`:

```yaml
keycloak:
  additionalOptions:
    - name: metrics-enabled
      value: "true"
  podTemplate:
    metadata:
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9000"
        prometheus.io/path: /metrics
```

Both of these are set in the chart defaults (`values.yaml`).

---

## Collector Endpoint Reference

The standard collector endpoint used across all environments is:

```
http://monitoring-opentelemetry-collector.monitoring.svc.cluster.local:4317
```

This is the OpenTelemetry Collector deployed by the `monitoring-logging` chart in the `monitoring` namespace. It runs in `deployment` mode and accepts OTLP over gRPC on port 4317.
