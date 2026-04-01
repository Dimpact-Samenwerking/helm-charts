# OpenTelemetry Instrumentation — PodiumD

This document describes the OTel signal flow through the monitoring stack, the instrumentation status of every PodiumD service, and the configuration snippets needed to activate each one.

---

## OTel-first design principle

**OTel is the preferred telemetry pipeline.** When an application sends a signal via OTLP, the parallel fallback path for that signal is disabled:

| Signal | OTel path | Fallback (non-OTel apps only) |
|---|---|---|
| Logs | OTLP → OTel Collector → Loki | Alloy tails pod log files |
| Metrics | OTLP → OTel Collector → Prometheus remote write | ServiceMonitor / PodMonitor |
| Traces | OTLP → OTel Collector → Tempo | — (no fallback) |

**Do not** create a ServiceMonitor or PodMonitor for an app that already sends metrics via OTLP — it will cause duplicate data in Prometheus.

### Excluding OTel pods from Alloy log collection

Alloy uses the pod label `telemetry/otel-logs: "true"` to skip log collection for pods that already ship logs via OTLP. Add this label to any pod whose application is configured to send logs to the OTel Collector:

```yaml
# podiumd/values.yaml — add to pod template labels for OTel-enabled apps
<service>:
  podLabels:
    telemetry/otel-logs: "true"
```

The Alloy River pipeline (in `monitoring-logging/values.yaml`) drops any pod matching this label before tailing its log files.

---

## Architecture

```
PodiumD applications
    │
    │  OTLP gRPC (:4317) or HTTP (:4318)          [PRIMARY PATH]
    ▼
┌─────────────────────────────────────────────────────┐
│  OpenTelemetry Collector  (Deployment, monitoring ns) │
│                                                       │
│  Pipelines:                                           │
│    logs    ──otlphttp──▶  Loki gateway                │
│    metrics ──remotewrite▶ Prometheus server           │
│    traces  ──otlp──────▶  Tempo  (tempo.enabled=true) │
└─────────────────────────────────────────────────────┘

Non-OTel apps only (fallback):
    │
    ├── logs    ──▶  Alloy (pod log file tailing) ──▶  Loki
    └── metrics ──▶  ServiceMonitor / PodMonitor  ──▶  Prometheus
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
**Status:** ✅ — `settings.otel:` block supported in VNG subcharts

These are VNG-gegevensstandaarden Django apps. All have native OTel support in their Helm subcharts via [opentelemetry-python](https://opentelemetry-python.readthedocs.io) instrumentation.

**Signals supported:** traces, metrics, logs  
**App port:** 8000 (internal), 80 via nginx

### Enable per service

> **⚠️ Critical:** the correct path is `<service>.settings.otel.*`. The top-level `<service>.otel.*` key is **dead code** — subcharts do not read it. Using the wrong path silently leaves OTel disabled.

```yaml
# #OTel instrumentation — podiumd/values.yaml
openzaak:
  settings:
    otel:
      disabled: false
      exporterOtlpEndpoint: "http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4317"
      exporterOtlpMetricsInsecure: true   # required for gRPC over plaintext (non-TLS) endpoint
```

Repeat the same `settings.otel` block for each service: `opennotificaties`, `objecten`, `objecttypen`, `openklant`, `openformulieren`, `openarchiefbeheer`.

**Env vars the subchart injects when `disabled: false`:**

| Variable | Value |
|---|---|
| `OTEL_SDK_DISABLED` | `False` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Value of `settings.otel.exporterOtlpEndpoint` |
| `OTEL_EXPORTER_OTLP_METRICS_INSECURE` | `True` when `exporterOtlpMetricsInsecure: true` |
| `OTEL_SERVICE_NAME` | Set to the app name by the subchart |

> **`exporterOtlpMetricsInsecure: true` is required** when using gRPC (`OTEL_EXPORTER_OTLP_PROTOCOL=grpc`) to a plaintext endpoint. Without it, the gRPC client attempts TLS and the connection fails with `StatusCode.UNAVAILABLE`.

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

## Alloy (log agent) — fallback for non-OTel pods

Alloy tails pod log files and ships them to Loki. It serves as the **fallback** for apps that do not send logs via OTLP, but in practice it collects **all pod logs** automatically — no pod labels or configuration in `podiumd/values.yaml` are needed.

The `telemetry/otel-logs: "true"` pod label filtering described in earlier versions of this document has been removed. Alloy filters by node (each DaemonSet pod only tails files on its own node), not by pod label.

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

**Pipeline column:** `OTel` = primary path via OTLP; `fallback` = Alloy log tailing / ServiceMonitor scraping.  
When a service is marked `OTel`, add `podLabels: { telemetry/otel-logs: "true" }` in `podiumd/values.yaml` and do **not** create a ServiceMonitor for that service.

| Service | Traces | Metrics | Logs | Pipeline | Action |
|---|---|---|---|---|---|
| **OTel Collector** | receives | receives | receives | — | ✅ deployed |
| **Keycloak** | ✅ ready | ✅ active (port 9000) | — | OTel (traces) / fallback (metrics) | Add `additionalOptions`; add `telemetry/otel-logs: "true"` once traces enabled |
| **OpenZaak** | ✅ ready | ⚠️ via prometheus | ⚠️ | OTel when enabled | Set `otel.disabled: false` + endpoint + `podLabels` |
| **OpenNotificaties** | ✅ ready | ⚠️ via prometheus | ⚠️ | OTel when enabled | Set `otel.disabled: false` + endpoint + `podLabels` |
| **Objecten** | ✅ ready | ⚠️ via prometheus | ⚠️ | OTel when enabled | Set `otel.disabled: false` + endpoint + `podLabels` |
| **Objecttypen** | ✅ ready | ⚠️ via prometheus | ⚠️ | OTel when enabled | Set `otel.disabled: false` + endpoint + `podLabels` |
| **OpenKlant** | ✅ ready | ⚠️ via prometheus | ⚠️ | OTel when enabled | Set `otel.disabled: false` + endpoint + `podLabels` |
| **OpenFormulieren** | ⚠️ | ⚠️ | ⚠️ | OTel when enabled | Add `otel:` block + endpoint + `podLabels` |
| **OpenInwoner** | ⚠️ | ⚠️ | ⚠️ | OTel when enabled | Add `otel:` block + endpoint + `podLabels` |
| **OpenArchiefBeheer** | ✅ ready | ⚠️ | ⚠️ | OTel when enabled | Enable service + `otel.disabled: false` + `podLabels` |
| **ZAC** | 🔧 partial | ⚠️ via prometheus | — | OTel (traces) | Set `javaOptions`; keep bundled collector disabled |
| **KISS** | ❓ | ❓ | — | fallback until confirmed | Verify SDK, then set `extraEnv` + `podLabels` |
| **ITA** | ❓ | ❓ | — | fallback until confirmed | Verify SDK, then set `extraEnv` |
| **PABC** | ❓ | ❓ | — | fallback until confirmed | Verify SDK, then set `extraEnv` |
| **OMC** | ❓ | ❓ | — | fallback until confirmed | Verify SDK, then set `extraEnv` |
| **Alloy** | — | — | ✅ active | fallback (non-OTel pods) | Skip pods with `telemetry/otel-logs: "true"` |
| **Tempo** | receives | — | — | — | Enable with `tempo.enabled: true` |
