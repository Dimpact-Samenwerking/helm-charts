# OpenTelemetry Instrumentation — PodiumD

This document describes the OTel signal flow through the monitoring stack, the instrumentation status of every PodiumD service, and the configuration snippets needed to activate each one.

---

## Architecture

```
PodiumD applications
    │
    │  OTLP gRPC (:4317) or HTTP (:4318)
    ▼
┌─────────────────────────────────────────────────────┐
│  OpenTelemetry Collector  (Deployment, monitoring ns) │
│                                                       │
│  Pipelines:                                           │
│    logs    ──otlphttp──▶  Loki gateway                │
│    metrics ──remotewrite▶ Prometheus server           │
│    traces  ──otlp──────▶  Tempo  (tempo.enabled=true) │
└─────────────────────────────────────────────────────┘
```

### Collector endpoint

Applications in the `podiumd` namespace reach the collector cross-namespace:

| Protocol | Address |
|---|---|
| gRPC (OTLP) | `http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4317` |
| HTTP (OTLP) | `http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4318` |

Replace `<MONITORING_RELEASE>` and `<MONITORING_NS>` with the Helm release name and namespace of the monitoring-logging deployment (e.g. `monitoring` / `monitoring`).

> The HTTP endpoint is simpler for apps that don't support gRPC. Both are always available — no extra config needed in the collector.

---

## Status legend

| Symbol | Meaning |
|---|---|
| ✅ | Confirmed — config schema known, ready to enable |
| ⚠️ | Supported by the framework — endpoint must be wired |
| 🔧 | Partially in place — dependencies exist, not yet initialised |
| ❓ | Unknown — needs investigation |

---

## Django applications

**Services:** OpenZaak, OpenNotificaties, Objecten, Objecttypen, OpenKlant, OpenArchiefBeheer  
**Status:** ✅ — `otel:` block exists in `podiumd/values.yaml`, currently `disabled: true`

These are VNG-gegevensstandaarden Django apps. All have native `otel:` support in their Helm subcharts via [opentelemetry-python](https://opentelemetry-python.readthedocs.io) instrumentation.

**Signals supported:** traces, metrics, logs  
**App port:** 8000 (internal), 80 via nginx

### Enable per service

```yaml
# #OTel instrumentation — podiumd/values.yaml
openzaak:
  otel:
    disabled: false

opennotificaties:
  otel:
    disabled: false

objecten:
  otel:
    disabled: false

objecttypen:
  otel:
    disabled: false

openklant:
  otel:
    disabled: false

openarchiefbeheer:        # also requires openarchiefbeheer.enabled: true
  otel:
    disabled: false
```

**Env vars the subchart injects when `disabled: false`:**

| Variable | Value |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Subchart default — must override to point to the collector |
| `OTEL_SERVICE_NAME` | Set to the app name by the subchart |
| `OTEL_TRACES_EXPORTER` | `otlp` |
| `OTEL_METRICS_EXPORTER` | `otlp` (if enabled by subchart) |

Override the endpoint by adding to each service's `extraEnv`:

```yaml
# #OTel instrumentation — podiumd/values.yaml
openzaak:
  otel:
    disabled: false
  extraEnv:
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4317"
    - name: OTEL_EXPORTER_OTLP_PROTOCOL
      value: grpc
```

> ⚠️ Check each subchart's `values.yaml` for the exact `otel:` key schema — some may accept an `endpoint:` key directly under `otel:` rather than requiring `extraEnv`.

---

## OpenFormulieren & OpenInwoner

**Status:** ⚠️ — No `otel:` block in `podiumd/values.yaml`; Django-based, so framework support exists.

These two services currently have no `otel:` block in the umbrella chart values. Add it manually:

```yaml
# #OTel instrumentation — podiumd/values.yaml
openformulieren:
  otel:
    disabled: false
  extraEnv:
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4317"
    - name: OTEL_SERVICE_NAME
      value: openformulieren

openinwoner:
  otel:
    disabled: false
  extraEnv:
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4317"
    - name: OTEL_SERVICE_NAME
      value: openinwoner
```

> Verify that `openforms` and `openinwoner` Helm chart versions support the `otel:` key before deploying — if not, `extraEnv` alone is sufficient.

---

## Keycloak (Quarkus) ✅

**Status:** ✅ — Keycloak 26.x (Quarkus) has first-class OTel tracing via `KC_TRACING_*` options. Metrics are already enabled (`metrics-enabled: true`).

**Signals supported:** traces, metrics (already active)  
**Config method:** `additionalOptions` in `podiumd/values.yaml`

```yaml
# #OTel instrumentation — podiumd/values.yaml
keycloak:
  additionalOptions:
    - name: health-enabled
      value: "true"
    - name: metrics-enabled
      value: "true"
    - name: cache
      value: "ispn"
    - name: cache-stack
      value: ""
    # -- OTel tracing (add these)
    - name: tracing-enabled
      value: "true"
    - name: tracing-endpoint-v2
      value: "http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4317"
    - name: tracing-service-name
      value: "keycloak"
    - name: tracing-sampler-type
      value: "parentbased_traceidratio"
    - name: tracing-sampler-ratio
      value: "0.1"        # 10% sampling — adjust per environment
```

> `tracing-sampler-ratio: "0.1"` is a conservative default. Set to `"1.0"` for full tracing in dev/test.  
> These map to `KC_TRACING_ENABLED`, `KC_TRACING_ENDPOINT_V2`, etc. — refer to [Keycloak tracing docs](https://www.keycloak.org/server/tracing).

---

## ZAC (zaakafhandelcomponent) 🔧

**Status:** 🔧 — OTel API libraries are already on the classpath (`opentelemetry-api:1.60.1`, `opentelemetry-instrumentation-annotations:2.26.1`). The ZAC Helm chart also ships with an **optional bundled OTel Collector** (`otel/opentelemetry-collector-contrib:0.148.0`) — keep this **disabled** when using the shared monitoring collector.

**Signals supported:** traces (instrumentation annotations in code), metrics (via WildFly MicroProfile Metrics)  
**Config method:** `javaOptions` in `podiumd/values.yaml`

```yaml
# #OTel instrumentation — podiumd/values.yaml
zac:
  # -- Pass OTel SDK config as JVM system properties.
  # The OTel API is already on the classpath; this activates the SDK and exporter.
  javaOptions: >-
    -Xmx1024m -Xms1024m -Xlog:gc::time,uptime
    -Dotel.service.name=zac
    -Dotel.exporter.otlp.endpoint=http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4317
    -Dotel.exporter.otlp.protocol=grpc
    -Dotel.traces.exporter=otlp
    -Dotel.metrics.exporter=none
    -Dotel.logs.exporter=none

  # -- Disable ZAC's bundled OTel Collector — we use the shared one from monitoring-logging
  opentelemetry-collector:
    enabled: false
```

> The ZAC chart's bundled collector (`opentelemetry-collector.enabled`) defaults to `false` — just make sure it stays off.  
> Metrics via OTel are set to `none` here since Prometheus already scrapes ZAC via ServiceMonitor (see `prometheus-scraping.md`). Set to `otlp` if you want to consolidate through the OTel pipeline instead.

---

## KISS ⚠️

**Status:** ⚠️ — .NET Core application. No OTel configuration exists in the chart. If the frontend or adapter uses [`OpenTelemetry.Exporter.OpenTelemetryProtocol`](https://www.nuget.org/packages/OpenTelemetry.Exporter.OpenTelemetryProtocol/), configure via environment variables.

**Signals supported:** traces (if `prometheus-net` / OTLP SDK present), metrics

```yaml
# #OTel instrumentation — podiumd/values.yaml (once confirmed)
kiss:
  extraEnv:
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4318"  # HTTP
    - name: OTEL_EXPORTER_OTLP_PROTOCOL
      value: http/protobuf
    - name: OTEL_SERVICE_NAME
      value: kiss
    - name: OTEL_TRACES_EXPORTER
      value: otlp
```

> **Action required:** Confirm whether `OpenTelemetry.Exporter.OpenTelemetryProtocol` is in the KISS image's dependencies before deploying this config.

---

## ITA, PABC, OMC ❓

No OTel configuration exists in chart values. These services are also disabled by default (`enabled: false`).

| Service | Runtime | OTel support |
|---|---|---|
| ITA (InternetTaakAfhandeling) | .NET Core | ❓ — use `OTEL_EXPORTER_OTLP_ENDPOINT` if supported |
| PABC (Platform Auth Beheer) | .NET Core | ❓ — same |
| OMC (NotifyNL) | .NET Core, port 5270 | ❓ — same |

Standard .NET OTel environment variables if supported:

```yaml
# #OTel instrumentation — template (verify support first)
<service>:
  extraEnv:
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4318"
    - name: OTEL_SERVICE_NAME
      value: "<service>"
```

---

## Alloy (log agent) — already wired

Alloy ships pod logs directly to Loki and does **not** use the OTel Collector pipeline. No additional config needed.

If you want Alloy to also forward logs via OTLP (e.g. to add OTel resource attributes), add to `alloy.alloy.configMap.content`:

```alloy
// #OTel instrumentation — monitoring-logging/values.yaml (optional)
otelcol.exporter.otlphttp "loki" {
  client {
    endpoint = "http://{{ .Release.Name }}-opentelemetry-collector:4318"
  }
}
```

---

## OTel Collector pipeline reference

Defined in `monitoring-logging/values.yaml` under `opentelemetry-collector.config`:

```yaml
# #OTel instrumentation — monitoring-logging/values.yaml
opentelemetry-collector:
  config:
    receivers:
      otlp:
        protocols:
          grpc: { endpoint: 0.0.0.0:4317 }
          http: { endpoint: 0.0.0.0:4318 }
    processors:
      memory_limiter:
        check_interval: 1s
        limit_percentage: 80
        spike_limit_percentage: 25
      batch:
        timeout: 5s
        send_batch_size: 1000
    exporters:
      otlphttp/loki:
        endpoint: http://${env:RELEASE_NAME}-loki-gateway/otlp
        headers: { X-Scope-OrgID: "1" }
      prometheusremotewrite:
        endpoint: http://${env:RELEASE_NAME}-prometheus-server/api/v1/write
      otlp/tempo:
        endpoint: ${env:RELEASE_NAME}-tempo:4317    # active when tempo.enabled=true
        tls: { insecure: true }
    service:
      pipelines:
        logs:    { receivers: [otlp], processors: [memory_limiter, batch], exporters: [otlphttp/loki] }
        metrics: { receivers: [otlp], processors: [memory_limiter, batch], exporters: [prometheusremotewrite] }
        traces:  { receivers: [otlp], processors: [memory_limiter, batch], exporters: [otlp/tempo] }
```

---

## Current status summary

| Service | Traces | Metrics | Logs | Action |
|---|---|---|---|---|
| **OTel Collector** | receives | receives | receives | ✅ deployed |
| **Keycloak** | ✅ ready | ✅ active (port 9000) | — | Add `additionalOptions` |
| **OpenZaak** | ✅ ready | ⚠️ via prometheus | ⚠️ | Set `otel.disabled: false` + endpoint |
| **OpenNotificaties** | ✅ ready | ⚠️ via prometheus | ⚠️ | Set `otel.disabled: false` + endpoint |
| **Objecten** | ✅ ready | ⚠️ via prometheus | ⚠️ | Set `otel.disabled: false` + endpoint |
| **Objecttypen** | ✅ ready | ⚠️ via prometheus | ⚠️ | Set `otel.disabled: false` + endpoint |
| **OpenKlant** | ✅ ready | ⚠️ via prometheus | ⚠️ | Set `otel.disabled: false` + endpoint |
| **OpenFormulieren** | ⚠️ | ⚠️ | ⚠️ | Add `otel:` block + endpoint |
| **OpenInwoner** | ⚠️ | ⚠️ | ⚠️ | Add `otel:` block + endpoint |
| **OpenArchiefBeheer** | ✅ ready | ⚠️ | ⚠️ | Enable service + `otel.disabled: false` |
| **ZAC** | 🔧 partial | ⚠️ via prometheus | — | Set `javaOptions` with OTel system props |
| **KISS** | ❓ | ❓ | — | Verify SDK, then set `extraEnv` |
| **ITA** | ❓ | ❓ | — | Verify SDK, then set `extraEnv` |
| **PABC** | ❓ | ❓ | — | Verify SDK, then set `extraEnv` |
| **OMC** | ❓ | ❓ | — | Verify SDK, then set `extraEnv` |
| **Alloy** | — | — | ✅ active | Ships logs directly to Loki |
| **Tempo** | receives | — | — | Enable with `tempo.enabled: true` |
