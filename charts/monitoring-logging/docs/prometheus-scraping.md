# Prometheus Scraping — monitoring-logging

This document describes every metric source available in a PodiumD cluster, how Prometheus discovers them, and the ServiceMonitor resources needed to activate scraping for each application.

> **OTel-first:** Do **not** create a ServiceMonitor or PodMonitor for any application that already sends metrics via OTLP to the OTel Collector. The collector pushes metrics to Prometheus via remote write — a ServiceMonitor on the same app would cause duplicate series. See `otel.md` for the pipeline status of each service.

---

## How discovery works

Prometheus is managed by the Prometheus Operator (kube-prometheus-stack) and configured with:

```yaml
# values.yaml / values-monitoring.yaml
kube-prometheus-stack:
  prometheus:
    prometheusSpec:
      serviceMonitorSelectorNilUsesHelmValues: false
      podMonitorSelectorNilUsesHelmValues: false
```

Setting these to `false` means the operator watches **all namespaces** for `ServiceMonitor` and `PodMonitor` resources, not only those created by its own Helm release.

**This means**: creating a `ServiceMonitor` in the `podiumd` namespace is sufficient for Prometheus (running in the `monitoring` namespace) to pick it up automatically.

The remote-write receiver is also enabled (`--web.enable-remote-write-receiver`), so the OpenTelemetry Collector can push OTLP metrics directly to Prometheus without a ServiceMonitor.

---

## Infrastructure metrics (scraped automatically)

These are scraped by the Prometheus chart itself — no ServiceMonitor resources needed.

| Component | Source | Port | Path |
|---|---|---|---|
| Prometheus server | self-scrape | 9090 | `/metrics` |
| kube-state-metrics | DaemonSet | 8080 | `/metrics` |
| node-exporter | DaemonSet | 9100 | `/metrics` |
| pushgateway | Deployment | 9091 | `/metrics` |
| Alloy (log agent) | DaemonSet | 12345 | `/metrics` |
| **Traefik** | PodMonitor (monitoring chart) | 9100 | `/metrics` |
| **OTel Collector** | ServiceMonitor (monitoring chart) | 8888 | `/metrics` |
| **Django apps** | OTel remote write | — | pushes to `/api/v1/write` |

---

## Application metrics (require ServiceMonitors)

### Status legend
| Symbol | Meaning |
|---|---|
| ✅ | Confirmed working |
| ⚠️ | Standard for this framework — verify against app image |
| ❓ | Unknown — investigate before creating ServiceMonitor |

---

### Traefik ✅

Traefik is deployed with `--metrics.prometheus=true` and exposes metrics on a dedicated pod port (9100). The monitoring chart deploys a `PodMonitor` that discovers Traefik pods across all namespaces.

| Field | Value |
|---|---|
| Port | `9100` (pod port name: `metrics`) |
| Path | `/metrics` |
| Monitor | `PodMonitor/monitoring-traefik` (created by `monitoring-logging` chart) |
| Config key | `traefikMonitor.enabled` (default: `true`) |

No action needed in `podiumd/values-enable-observability.yaml` — the PodMonitor is owned by the monitoring chart.

---

### OpenTelemetry Collector ✅

The OTel Collector exposes its own health/pipeline metrics on port 8888 (`otelcol_*`). A `ServiceMonitor` is deployed by the monitoring chart.

| Field | Value |
|---|---|
| Port | `8888` (port name: `metrics`) |
| Path | `/metrics` |
| Monitor | `ServiceMonitor/monitoring-otel-collector` (created by `monitoring-logging` chart) |
| Config key | `otelCollectorMonitor.enabled` (default: `true`) |

No action needed in `podiumd/values-enable-observability.yaml` — the ServiceMonitor is owned by the monitoring chart.

---

### Keycloak ✅

Metrics are explicitly enabled in `podiumd/values.yaml`:

```yaml
# podiumd/values.yaml
keycloak-operator:
  additionalOptions:
    - name: metrics-enabled
      value: "true"
  # init container:
  #   KC_METRICS_ENABLED=true
```

Keycloak (Quarkus) exposes metrics on the management port, separate from the HTTP port.

| Field | Value |
|---|---|
| Port | `9000` |
| Path | `/metrics` |
| Service label | `app: keycloak` |
| Namespace | `podiumd` |

<details>
<summary>ServiceMonitor</summary>

```yaml
# #Prometheus scraping
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: keycloak
  namespace: podiumd
spec:
  selector:
    matchLabels:
      app: keycloak
  endpoints:
    - port: management          # port 9000
      path: /metrics
      interval: 30s
```

</details>

---

### Redis HA ✅

The redis-operator in `podiumd/values.yaml` deploys a redis-exporter sidecar:

```yaml
# podiumd/values.yaml
redisCluster:
  redisExporter:
    enabled: true
    image: quay.io/opstree/redis-exporter:v1.44.0
```

| Field | Value |
|---|---|
| Port | `9090` |
| Path | `/metrics` |
| Service label | `app: redis-cluster` (check operator-generated label) |
| Namespace | `podiumd` |

<details>
<summary>ServiceMonitor</summary>

```yaml
# #Prometheus scraping
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: redis-cluster
  namespace: podiumd
spec:
  selector:
    matchLabels:
      app: redis-cluster
  endpoints:
    - port: redis-exporter       # port 9090
      path: /metrics
      interval: 30s
```

</details>

---

### Django applications ✅ (via OTel)

All Django services (OpenZaak, OpenNotificaties, Objecten, Objecttypen, OpenKlant, OpenFormulieren, OpenInwoner) send metrics via OTLP to the OTel Collector, which pushes them to Prometheus via remote write. **Do not create ServiceMonitors or PodMonitors for these services** — it will cause duplicate series.

Enable via `values-enable-observability.yaml`:

```yaml
openzaak:
  settings:
    otel:
      disabled: false
      exporterOtlpEndpoint: "http://monitoring-opentelemetry-collector.monitoring.svc.cluster.local:4317"
      exporterOtlpProtocol: grpc
      exporterOtlpMetricsInsecure: true
```

See `otel.md` for the full configuration for each service.

| Service | Helm alias | App port | Expected metrics port |
|---|---|---|---|
| OpenZaak | `openzaak` | 8000 | 9091 ⚠️ |
| OpenNotificaties | `opennotificaties` | 8000 | 9091 ⚠️ |
| Objecten | `objecten` | 8000 | 9091 ⚠️ |
| Objecttypen | `objecttypen` | 8000 | 9091 ⚠️ |
| OpenKlant | `openklant` | 8000 | 9091 ⚠️ |
| OpenFormulieren | `openformulieren` | 8000 | 9091 ⚠️ |
| OpenInwoner | `openinwoner` | 8000 | 9091 ⚠️ |
| OpenArchiefBeheer | `openarchiefbeheer` | 8000 | 9091 ⚠️ |

All Django services expose their metrics through a pod port that is **not** forwarded through the nginx sidecar. The ServiceMonitor must target the pod port directly using a `PodMonitor` or a headless service on that port.

<details>
<summary>PodMonitor template (works for all Django apps)</summary>

Replace `<alias>` with the Helm alias from the table above.

```yaml
# #Prometheus scraping
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: <alias>
  namespace: podiumd
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: <alias>
  podMetricsEndpoints:
    - port: metrics              # verify port name in pod spec
      path: /metrics
      targetPort: 9091
      interval: 30s
```

</details>

<details>
<summary>Enable metrics port in subchart values (podiumd/values.yaml)</summary>

Each Django subchart typically has a `metrics` section. Add to the relevant block in `podiumd/values.yaml`:

```yaml
# example for openzaak — repeat for each Django app
openzaak:
  metrics:
    enabled: true
    port: 9091
    path: /metrics
    serviceMonitor:
      enabled: true             # if supported by the subchart
      namespace: podiumd
```

> Check each subchart's `values.yaml` for the exact key names — they differ slightly between VNG charts.

</details>

---

### ZAC (zaakafhandelcomponent) ⚠️

ZAC is a Kotlin/Jakarta EE application running on WildFly. WildFly exposes metrics via MicroProfile Metrics or Micrometer with a Prometheus registry.

| Field | Value |
|---|---|
| Helm alias | `zac` |
| App port | `8080` (via nginx on `80`) |
| Expected metrics port | `9990` (WildFly management) or `8080/metrics` ⚠️ |
| Path | `/metrics` |
| Namespace | `podiumd` |

Check the ZAC `src/main/resources/META-INF/microprofile-config.properties` or WildFly configuration for the exact metrics endpoint.

<details>
<summary>ServiceMonitor (once port confirmed)</summary>

```yaml
# #Prometheus scraping
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: zac
  namespace: podiumd
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: zaakafhandelcomponent
  endpoints:
    - port: metrics              # verify port name
      path: /metrics
      interval: 30s
```

</details>

---

### KISS ⚠️

KISS is a .NET Core application. If it uses [`prometheus-net`](https://github.com/prometheus-net/prometheus-net), metrics are exposed at `/metrics` on the application port.

| Field | Value |
|---|---|
| Helm alias | `kiss` |
| App port | `8080` |
| Expected metrics port | `8080` ⚠️ |
| Path | `/metrics` |
| Namespace | `podiumd` |

<details>
<summary>ServiceMonitor (once confirmed)</summary>

```yaml
# #Prometheus scraping
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: kiss
  namespace: podiumd
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: kiss
  endpoints:
    - port: http                 # port 8080
      path: /metrics
      interval: 30s
```

</details>

---

### RabbitMQ (OpenNotificaties) ⚠️

RabbitMQ is deployed as a dependency of OpenNotificaties. The Prometheus plugin exposes metrics on a dedicated port if enabled.

| Field | Value |
|---|---|
| Management port | `15672` |
| Prometheus metrics port | `15692` ⚠️ (requires `rabbitmq_prometheus` plugin) |
| Path | `/metrics` |
| Namespace | `podiumd` |

Enable the plugin in the OpenNotificaties subchart values:

```yaml
# podiumd/values.yaml
opennotificaties:
  rabbitmq:
    extraPlugins: "rabbitmq_prometheus"
```

<details>
<summary>ServiceMonitor (once plugin enabled)</summary>

```yaml
# #Prometheus scraping
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: opennotificaties-rabbitmq
  namespace: podiumd
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: rabbitmq
      app.kubernetes.io/instance: podiumd
  endpoints:
    - port: metrics              # port 15692
      path: /metrics
      interval: 30s
```

</details>

---

### ITA, PABC, OMC ❓

These services have limited observability configuration in the chart values. They are also disabled by default (`enabled: false`).

| Service | Helm alias | App port | Metrics |
|---|---|---|---|
| InternetTaakAfhandeling | `ita` | 80 | ❓ unknown |
| Platform Auth Beheer | `pabc` | unknown | ❓ unknown |
| NotifyNL OMC | `omc` | 5270 | ❓ unknown |

Investigate the upstream images for each before creating ServiceMonitors.

---

### Loki (self-monitoring) ❓

Loki's self-monitoring is disabled in the current values:

```yaml
loki:
  monitoring:
    selfMonitoring:
      enabled: false
    dashboards:
      enabled: false
    rules:
      enabled: false
```

Loki does expose a `/metrics` endpoint on its gateway and component pods. Enable self-monitoring to get Loki scraping:

```yaml
loki:
  monitoring:
    selfMonitoring:
      enabled: true
    dashboards:
      enabled: true
```

---

## Values file configuration reference

Both values files need the `#Prometheus scraping` block. The chart defaults live in `charts/monitoring-logging/values.yaml`; environment-specific overrides go in `podiumd-infra/values-monitoring.yaml`.

### Adding static scrape configs (fallback if no ServiceMonitor support)

```yaml
# #Prometheus scraping
kube-prometheus-stack:
  prometheus:
    prometheusSpec:
      additionalArgs:
        - name: web.enable-remote-write-receiver
          value: ""
      additionalScrapeConfigs: |
        # Keycloak — only needed if ServiceMonitor is not used
        - job_name: keycloak
          static_configs:
            - targets: ['keycloak.podiumd.svc.cluster.local:9000']
          metrics_path: /metrics
          relabel_configs:
            - target_label: namespace
              replacement: podiumd
            - target_label: service
              replacement: keycloak

        # Redis exporter
        - job_name: redis-cluster
          static_configs:
            - targets: ['redis-cluster.podiumd.svc.cluster.local:9090']
          metrics_path: /metrics
          relabel_configs:
            - target_label: namespace
              replacement: podiumd
            - target_label: service
              replacement: redis-cluster
```

> Prefer `ServiceMonitor` / `PodMonitor` resources over `additionalScrapeConfigs`. They are more maintainable and integrate with Prometheus Operator's RBAC model. Use `additionalScrapeConfigs` only for services that cannot expose a Kubernetes Service on the metrics port.

---

## Current status summary

**Before creating a ServiceMonitor**, check `otel.md` — if the service is on the OTel pipeline, skip the ServiceMonitor.

| Service | Metrics available | Monitor | Pipeline | Status |
|---|---|---|---|---|
| Prometheus (self) | ✅ | ✅ auto | — | — |
| kube-state-metrics | ✅ | ✅ auto | — | — |
| node-exporter | ✅ | ✅ auto | — | — |
| Alloy | ✅ | ✅ auto | — | — |
| **OTel Collector** | ✅ | ✅ `ServiceMonitor/monitoring-otel-collector` | monitoring chart | ✅ done |
| **Traefik** | ✅ | ✅ `PodMonitor/monitoring-traefik` | monitoring chart | ✅ done |
| **Keycloak** | ✅ | ✅ `ServiceMonitor/keycloak` (auto by operator) | keycloak-operator | ✅ done |
| **Redis HA** | ✅ | ✅ `serviceMonitor.enabled: true` (redis-ha subchart) | podiumd chart | ✅ done |
| **ClamAV** | ✅ | ✅ `serviceMonitor.enabled: true` (clamav subchart) | podiumd chart | ✅ done |
| **ECK operator** | ✅ | ✅ `podMonitor.enabled: true` (eck-operator subchart) | podiumd chart | ✅ done |
| **OpenZaak** | ✅ | — (OTel pipeline) | OTel → remote write | ✅ done |
| **OpenNotificaties** | ✅ | — (OTel pipeline) | OTel → remote write | ✅ done |
| **Objecten** | ✅ | — (OTel pipeline) | OTel → remote write | ✅ done |
| **Objecttypen** | ✅ | — (OTel pipeline) | OTel → remote write | ✅ done |
| **OpenKlant** | ✅ | — (OTel pipeline) | OTel → remote write | ✅ done |
| **OpenFormulieren** | ✅ | — (OTel pipeline) | OTel → remote write | ✅ done |
| **OpenInwoner** | ✅ | — (OTel pipeline) | OTel → remote write | ✅ done |
| **ZAC** | ⚠️ | ❌ ServiceMonitor pending | OTel (traces) / fallback (metrics) | Create ServiceMonitor for metrics |
| **KISS** | ⚠️ | ❌ | fallback until confirmed | Verify `/metrics`, create ServiceMonitor |
| **RabbitMQ** | ⚠️ | ❌ | fallback | Enable `rabbitmq_prometheus`, create ServiceMonitor |
| ITA | ❓ | ❌ | fallback | Investigate |
| PABC | ❓ | ❌ | fallback | Investigate |
| OMC | ❓ | ❌ | fallback | Investigate |
| Loki | ⚠️ | ❌ | — | Enable `monitoring.selfMonitoring` |
