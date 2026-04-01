# Keycloak — OTel Tracing & Prometheus Metrics

This document describes the manual changes needed in `keycloak-cr.yml` to enable
OpenTelemetry tracing and Prometheus metrics scraping for Keycloak.

---

## 1. OTel Tracing

Keycloak 26.x (Quarkus) has native OTel tracing via `KC_TRACING_*` options.
Tracing is a **build-time** option — it requires both an `additionalOptions` entry
in the CR *and* the matching env var exported in the init container build step.

### 1a. Add to `spec.additionalOptions`

```yaml
additionalOptions:
  # ... existing options ...
  - name: tracing-enabled
    value: "true"
  - name: tracing-endpoint-v2
    value: "http://monitoring-opentelemetry-collector.monitoring.svc.cluster.local:4317"
  - name: tracing-service-name
    value: "keycloak"
  - name: tracing-sampler-type
    value: "parentbased_traceidratio"
  - name: tracing-sampler-ratio
    value: "1.0"   # 1.0 = 100% in dev/test; lower in production
```

### 1b. Add to the init container build command

In `spec.unsupported.podTemplate.spec.initContainers[0].command`, inside the
`if [ "$MODE" = "normal" ]; then` block, add the tracing env var alongside the
existing ones:

```bash
export KC_TRACING_ENABLED=true
```

Full context (the block already has `KC_METRICS_ENABLED`):

```bash
export KC_DB=postgres
export KC_PROXY_HEADERS=xforwarded
export KC_CACHE=ispn
export KC_METRICS_ENABLED=true
export KC_HEALTH_ENABLED=true
export KC_TRACING_ENABLED=true   # <-- add this
```

After applying, Keycloak pods will restart (operator triggers a rolling restart on
CR changes). Once running, traces will appear in the OTel Collector and flow to
Loki/Tempo depending on what is enabled in the monitoring-logging chart.

---

## 2. Prometheus Metrics Scraping

Keycloak already has `metrics-enabled: true` (port 9000, path `/metrics`).
The cluster uses annotation-based Prometheus scraping (no Prometheus Operator CRDs).

The following annotations are already present in `keycloak-cr.yml` under
`spec.unsupported.podTemplate.metadata.annotations`:

```yaml
annotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "9000"
  prometheus.io/path: "/metrics"
```

Once the CR is applied, Prometheus auto-discovers the Keycloak pods via the
`kubernetes-pods` scrape job and collects JVM, HTTP, Agroal DB pool, Infinispan
cache, and Keycloak-specific metrics.

The **Keycloak 26** Grafana dashboard in the `monitoring-logging` chart is built
on these actual KC26/Quarkus metrics: `http_server_*`, `base_memory_*`,
`process_cpu_usage`, `agroal_*`, `vendor_statistics_*`.
