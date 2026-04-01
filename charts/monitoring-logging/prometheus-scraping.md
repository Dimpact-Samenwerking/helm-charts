# Prometheus Scraping — monitoring-logging

This document describes every metric source available in a PodiumD cluster, how Prometheus discovers them, and the ServiceMonitor resources needed to activate scraping for each application.

---

## How discovery works

Prometheus is configured with:

```yaml
# values.yaml / values-monitoring.yaml
prometheus:
  prometheusSpec:
    serviceMonitorSelectorNilUsesHelmValues: false
```

Setting this to `false` means Prometheus watches **all namespaces** for `ServiceMonitor` resources, not only those created by its own Helm release. No label selector restrictions apply.

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
| OTel Collector | remote write | — | pushes to `/api/v1/write` |

---

## Application metrics (require ServiceMonitors)

### Status legend
| Symbol | Meaning |
|---|---|
| ✅ | Confirmed in chart values |
| ⚠️ | Standard for this framework — verify against app image |
| ❓ | Unknown — investigate before creating ServiceMonitor |

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

### Django applications ⚠️

The following services are all VNG/Dimpact Django applications. They are expected to expose Prometheus metrics via [`django-prometheus`](https://github.com/korfuri/django-prometheus) on a dedicated metrics port separate from the main application port (`8000`). The metrics port is typically `9091` in VNG charts.

**Verify** by checking each image's `requirements.txt` or `pyproject.toml` for `django-prometheus`.

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
prometheus:
  server:
    extraFlags:
      - web.enable-remote-write-receiver
  extraScrapeConfigs: |
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

> Prefer `ServiceMonitor` / `PodMonitor` resources over `extraScrapeConfigs`. They are more maintainable and integrate with Prometheus Operator's RBAC model. Use `extraScrapeConfigs` only for services that cannot expose a Kubernetes Service on the metrics port.

---

## Current status summary

| Service | Metrics available | ServiceMonitor exists | Action needed |
|---|---|---|---|
| Prometheus (self) | ✅ | ✅ auto | — |
| kube-state-metrics | ✅ | ✅ auto | — |
| node-exporter | ✅ | ✅ auto | — |
| Alloy | ✅ | ✅ auto | — |
| OTel Collector | ✅ (remote write) | — | — |
| **Keycloak** | ✅ confirmed | ❌ | Create ServiceMonitor |
| **Redis** | ✅ confirmed | ❌ | Create ServiceMonitor |
| **OpenZaak** | ⚠️ likely | ❌ | Verify port, create PodMonitor |
| **OpenNotificaties** | ⚠️ likely | ❌ | Verify port, create PodMonitor |
| **Objecten** | ⚠️ likely | ❌ | Verify port, create PodMonitor |
| **Objecttypen** | ⚠️ likely | ❌ | Verify port, create PodMonitor |
| **OpenKlant** | ⚠️ likely | ❌ | Verify port, create PodMonitor |
| **OpenFormulieren** | ⚠️ likely | ❌ | Verify port, create PodMonitor |
| **OpenInwoner** | ⚠️ likely | ❌ | Verify port, create PodMonitor |
| **OpenArchiefBeheer** | ⚠️ likely | ❌ | Verify port, create PodMonitor |
| **ZAC** | ⚠️ likely | ❌ | Verify endpoint, create ServiceMonitor |
| **KISS** | ⚠️ likely | ❌ | Verify `/metrics`, create ServiceMonitor |
| **RabbitMQ** | ⚠️ needs plugin | ❌ | Enable `rabbitmq_prometheus`, create ServiceMonitor |
| ITA | ❓ | ❌ | Investigate |
| PABC | ❓ | ❌ | Investigate |
| OMC | ❓ | ❌ | Investigate |
| Loki | ⚠️ self-monitoring off | ❌ | Enable `monitoring.selfMonitoring` |
