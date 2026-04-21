# Observability — OpenTelemetry & Prometheus

This document describes how metrics and tracing are configured across the podiumd chart components.

---

## Component Overview

| Component | OTEL mechanism | Prometheus scrape | Enabled via |
|---|---|---|---|
| openzaak | `settings.otel.*` | ❌ OTEL only → collector | `values-enable-observability.yaml` |
| openklant | `settings.otel.*` | ❌ OTEL only → collector | `values-enable-observability.yaml` |
| openformulieren | `settings.otel.*` | ❌ OTEL only → collector | `values-enable-observability.yaml` |
| opennotificaties | `settings.otel.*` | ❌ OTEL only → collector | `values-enable-observability.yaml` |
| objecten | `settings.otel.*` | ❌ OTEL only → collector | `values-enable-observability.yaml` |
| objecttypen | `settings.otel.*` | ❌ OTEL only → collector | `values-enable-observability.yaml` |
| openinwoner | `settings.otel.*` | ❌ OTEL only → collector | `values-enable-observability.yaml` |
| zac | `opentelemetry_zaakafhandelcomponent.*` + `javaOptions` | ❌ OTEL only → collector | `values-enable-observability.yaml` |
| keycloak | `additionalOptions: metrics-enabled` | ✅ ServiceMonitor port 9000 `/metrics` (auto by keycloak-operator) | built-in |
| redis-operator | — | ✅ pod annotations port 8080 `/metrics` | `values-enable-observability.yaml` |
| redis-ha | redis_exporter sidecar | ✅ PodMonitor port 9121 | `values-enable-observability.yaml` |
| solr-operator | — | ✅ pod annotations port 8080 `/metrics` | `values-enable-observability.yaml` |
| zookeeper-operator | — | ✅ pod annotations port 6000 `/metrics` | `values-enable-observability.yaml` |
| clamav | clamav_exporter sidecar | ✅ port 9906 + ServiceMonitor | `values-enable-observability.yaml` |
| eck-operator | `config.metricsPort` + `podMonitor.enabled` | ✅ PodMonitor port 8080 `/metrics` | `values-enable-observability.yaml` |
| traefik | — | ✅ PodMonitor port 9100 `/metrics` (monitoring chart) | `monitoring-logging` chart |
| otel-collector | — | ✅ ServiceMonitor port 8888 `/metrics` (monitoring chart) | `monitoring-logging` chart |
| api-proxy | — | ❌ plain nginx, no metrics endpoint | requires template changes |
| openarchiefbeheer | — | ❌ no OTEL support in chart | — |
| solr (SolrCloud) | — | ❌ not yet configured | see todo below |
| zookeeper (cluster) | — | ❌ not yet configured | see todo below |
| elasticsearch (ECK) | — | ❌ no native endpoint | see todo below |
| kibana (ECK) | — | ❌ no native endpoint | see todo below |

The Maykin Django apps do **not** expose a direct Prometheus scrape endpoint. Metrics are pushed via OTLP to a collector, which forwards to Prometheus.

Shared collector endpoint:
```
http://monitoring-opentelemetry-collector.monitoring.svc.cluster.local:4317
```

---

## Enabling Observability

Use `values-enable-observability.yaml` alongside your environment values file:

```bash
helm upgrade podiumd charts/podiumd \
  -f values.yaml \
  -f values-enable-observability.yaml \
  -f values-<env>.yaml \
  -n podiumd
```

---

## Prerequisites — Prometheus Operator CRDs

Some components use **ServiceMonitor** or **PodMonitor** custom resources (CRDs from the
[Prometheus Operator](https://github.com/prometheus-operator/prometheus-operator)) to declare
their scrape targets. These CRDs must be present in the cluster before applying
`values-enable-observability.yaml`, otherwise Helm will fail or the resources will be silently ignored.

| Component | Resource type | CRD required |
|---|---|---|
| keycloak-operator | `ServiceMonitor` | `monitoring.coreos.com/v1` (auto-created) |
| redis-ha | `PodMonitor` | `monitoring.coreos.com/v1` |
| clamav | `ServiceMonitor` | `monitoring.coreos.com/v1` |
| eck-operator (kisselastic) | `PodMonitor` | `monitoring.coreos.com/v1` |
| solr (todo) | `ServiceMonitor` | `monitoring.coreos.com/v1` (created by solr-operator) |
| zookeeper (todo) | `ServiceMonitor` | `monitoring.coreos.com/v1` (manual) |
| elasticsearch (todo) | `ServiceMonitor` | `monitoring.coreos.com/v1` (via exporter chart) |

The remaining components (Maykin apps, ZAC, Keycloak, Redis, Solr/Zookeeper operators) use
OTEL push or plain pod annotations — **no CRDs required** for those.

### Checking if the CRDs are installed

```bash
kubectl get crd servicemonitors.monitoring.coreos.com
kubectl get crd podmonitors.monitoring.coreos.com
```

### Installing the CRDs (without the full Prometheus Operator)

If the cluster runs a standalone Prometheus (e.g. via `kube-prometheus-stack`) the CRDs are
already present. If not, install just the CRDs:

```bash
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/bundle.yaml
```

Or install only the CRD manifests from the operator's GitHub release.

> Until the CRDs are installed, keep `redis-operator.redis-ha.redisExporter.podMonitor.enabled: false`,
> `clamav.metrics.serviceMonitor.enabled: false`, and `kisselastic.eck-operator.podMonitor.enabled: false`
> (the defaults in `values.yaml`). `values-enable-observability.yaml` overrides all three to `true`.

---

## RBAC for ServiceMonitor / PodMonitor creation

Some components create `ServiceMonitor` or `PodMonitor` resources **at runtime** (dynamically, not at Helm
deploy time). These components are operators — they watch CRDs and create monitoring resources on behalf of
managed instances. Without the correct RBAC they fail silently or fail hard.

The podiumd chart ships two RBAC templates to cover this:

### `keycloak-operator-servicemonitor-rbac.yaml`

Rendered when `keycloak-operator.enabled: true`.

| Resource | Scope | Verbs | Purpose |
|---|---|---|---|
| `ClusterRole` + `ClusterRoleBinding` | cluster-wide | `get/list/watch` on `servicemonitors` | Allows the operator to probe whether the `monitoring.coreos.com` CRD is installed. Without this, the operator receives HTTP 403 instead of 404 when the CRD is absent and aborts reconciliation — no Keycloak pods start. |
| `Role` + `RoleBinding` | release namespace | `create/patch/update/delete` on `servicemonitors` | Allows the operator to create and manage the `ServiceMonitor` for Keycloak metrics when `enableServiceMonitor: true`. |

The `Role` + `RoleBinding` are only rendered when `keycloak-operator.enableServiceMonitor: true` (set by
`values-enable-observability.yaml`).

### `eck-operator-podmonitor-rbac.yaml`

Rendered when `kisselastic.enabled: true` AND `kisselastic.eck-operator.podMonitor.enabled: true`.

| Resource | Scope | Verbs | Purpose |
|---|---|---|---|
| `Role` + `RoleBinding` | release namespace | `create/get/list/watch/patch/update/delete` on `podmonitors` | ECK operator dynamically creates PodMonitors for managed Elasticsearch, Kibana, and Enterprise Search instances when `spec.monitoring.metrics` is configured on those CRDs. The default ECK `ClusterRole` has no `monitoring.coreos.com` rules, so without this the ECK operator fails to manage scrape targets. |

The ServiceAccount name is always `elastic-operator` because the `eck-operator` chart ships with
`fullnameOverride: "elastic-operator"` as its default.

### Helm-managed monitors (no operator RBAC needed)

The following monitors are rendered as Helm templates at deploy time — Helm runs with the deploying
user's credentials (cluster-admin in typical setups), so no extra operator RBAC is required:

| Monitor | Template | Condition |
|---|---|---|
| `redis-ha` PodMonitor | `templates/redis-ha-podmonitor.yaml` | `redis-operator.redis-ha.redisExporter.podMonitor.enabled: true` |
| `clamav` ServiceMonitor | clamav subchart `servicemonitor.yaml` | `clamav.metrics.enabled: true` AND `clamav.metrics.serviceMonitor.enabled: true` |

> **ClamAV note:** The `clamav_exporter` sidecar and ServiceMonitor were added in clamav chart **v3.7.1**
> (the current version). Prior versions (≤ 3.2.0) had no metrics support. Both are enabled via
> `values-enable-observability.yaml`.

### Prometheus Operator discovery

The `kube-prometheus-stack` Prometheus Operator and Prometheus instance are configured to discover
monitors across **all namespaces** without label restrictions:

| Selector | Value | Effect |
|---|---|---|
| `serviceMonitorNamespaceSelector` | `{}` | All namespaces (incl. `podiumd`) |
| `podMonitorNamespaceSelector` | `{}` | All namespaces |
| `serviceMonitorSelector` | `{}` | All ServiceMonitors regardless of labels |
| `podMonitorSelector` | `{}` | All PodMonitors regardless of labels |

The Prometheus SA (`monitoring-kube-prometheus-prometheus`) has a cluster-wide `ClusterRole` with
`get/list/watch` on `pods`, `services`, `endpoints`, `endpointslices`, and `ingresses`, enabling it
to reach scrape targets in the `podiumd` namespace without any additional RBAC.

---

All Maykin subcharts share the same `settings.otel` schema:

```yaml
<component>:
  settings:
    otel:
      disabled: true
      exporterOtlpEndpoint: ""        # http://monitoring-opentelemetry-collector.monitoring.svc.cluster.local:4317
      exporterOtlpProtocol: grpc      # grpc or http/protobuf
      exporterOtlpMetricsInsecure: false
      exporterOtlpHeaders: []
      resourceAttributes: []
      metricExportInterval: 60000     # ms
      metricExportTimeout: 10000      # ms
```

`values.yaml` defaults all components to `disabled: true` (openformulieren has no otel block at all). All settings are applied via `values-enable-observability.yaml`.

---

## OTEL Configuration — ZAC

ZAC uses two mechanisms:

**1. `opentelemetry_zaakafhandelcomponent`** (built-in collector sidecar):
```yaml
zac:
  opentelemetry_zaakafhandelcomponent:
    disabled: ""      # "-true" to disable, "" to enable
    endpoint: "http://monitoring-opentelemetry-collector.monitoring.svc.cluster.local:4317"
```

**2. `javaOptions`** (JVM-level OTEL agent flags):
```yaml
zac:
  javaOptions: >-
    -Xmx1024m -Xms1024m -Xlog:gc::time,uptime
    -Dotel.service.name=zac
    -Dotel.exporter.otlp.endpoint=http://monitoring-opentelemetry-collector.monitoring.svc.cluster.local:4317
    -Dotel.exporter.otlp.protocol=grpc
    -Dotel.traces.exporter=otlp
    -Dotel.metrics.exporter=otlp
    -Dotel.logs.exporter=none
```

---

## Prometheus Scraping — Keycloak

`additionalOptions` in `values.yaml` enables the metrics endpoint. The `keycloak-operator` chart automatically creates a `ServiceMonitor` in the `podiumd` namespace for port 9000 — no additional scrape configuration is required.

```yaml
keycloak:
  additionalOptions:
    - name: metrics-enabled
      value: "true"
```

> The ServiceMonitor is created automatically by the keycloak-operator chart when `metrics-enabled: true`. Do **not** add pod annotations for Prometheus scraping — the ServiceMonitor is the correct discovery method.

---

## Prometheus Scraping — ECK Operator

The ECK operator is part of `kisselastic`. Configured via `values-enable-observability.yaml`:

```yaml
kisselastic:
  eck-operator:
    config:
      metricsPort: "8080"
    podMonitor:
      enabled: true
      interval: 1m
      scrapeTimeout: 30s
```

---

## Todo — Remaining Metrics (application workloads)

### Solr (SolrCloud)

The `SolrPrometheusExporter` CRD is installed by the solr-operator. The ZAC chart's `solrcloud.yaml`
template does **not** expose a `prometheusExporter` field, so a standalone CR must be created manually.
The solr-operator will pick it up and create a ServiceMonitor automatically.

```yaml
apiVersion: solr.apache.org/v1beta1
kind: SolrPrometheusExporter
metadata:
  name: zac-solr-exporter
  namespace: podiumd
spec:
  solrReference:
    cloud:
      name: zac-solrcloud   # verify: kubectl get solrclouds -n podiumd
  numThreads: 4
  image:
    tag: 9.10.1   # match the SolrCloud version in values.yaml
```

Verify: `kubectl get servicemonitor -n podiumd --context <cluster> | grep solr`, then query `solr_` in Prometheus.

---

### Zookeeper (cluster)

Zookeeper 3.5+ has a built-in Prometheus metrics provider on port `7000`. The ZAC chart's
`solrcloud.yaml` template does **not** pass `spec.conf` to the `ZookeeperCluster` CR — this
requires either a ZAC chart change (upstream) or a manual one-time patch of the CR.

The `ZookeeperCluster` CRD supports a `spec.conf.additionalConfig` map. Patch the live CR:

```bash
kubectl patch zookeepercluster -n podiumd --context <cluster> <name> --type merge -p '{
  "spec": {
    "conf": {
      "additionalConfig": {
        "metricsProvider.className": "org.apache.zookeeper.metrics.prometheus.PrometheusMetricsProvider",
        "metricsProvider.httpPort": "7000",
        "metricsProvider.exportJvmInfo": "true"
      }
    }
  }
}'
```

A ServiceMonitor must be created manually (the pravega operator does not create one):

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: zookeeper
  namespace: podiumd
spec:
  selector:
    matchLabels:
      app: zookeeper   # verify: kubectl get pods -n podiumd --show-labels | grep zoo
  endpoints:
    - port: metrics
      path: /metrics
```

---

### Elasticsearch & Kibana (ECK)

The kiss-elastic chart's `elasticsearch.yaml` and `kibana.yaml` templates are minimal (nodeSets,
nodeSelector, version only) — no monitoring spec is exposed via values.

ECK-managed Elasticsearch has no native Prometheus endpoint. Deploy `prometheus-community/elasticsearch-exporter`
as a separate release:

```yaml
elasticsearch-exporter:
  es:
    uri: http://kiss-es-http.podiumd.svc.cluster.local:9200   # verify: kubectl get svc -n podiumd | grep es-http
  serviceMonitor:
    enabled: true
    namespace: podiumd
```

Kibana does not have a widely-used standalone exporter. Options:
- Use Elastic Stack monitoring features (beats-based, writes to a monitoring cluster)
- Query Kibana's own `/api/stats` endpoint via a custom scrape job

Verify Elasticsearch: query `elasticsearch_` metrics in Prometheus.
