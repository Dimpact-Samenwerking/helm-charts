# Observability — PodiumD

This document explains how logs and metrics flow out of a PodiumD deployment and what you need to configure.

> **Prerequisite:** the `monitoring-logging` Helm chart must be deployed in a `monitoring` namespace on the same cluster. See [monitoring-logging/docs/otel.md](../../monitoring-logging/docs/otel.md) for the full OTel pipeline reference and [prometheus-scraping.md](../../monitoring-logging/docs/prometheus-scraping.md) for ServiceMonitor details.

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
| keycloak | `additionalOptions: metrics-enabled` | ✅ pod annotations port 9000 `/metrics` | `values-enable-observability.yaml` |
| redis-operator | — | ✅ pod annotations port 8080 `/metrics` | `values-enable-observability.yaml` |
| redis-ha | redis_exporter sidecar | ✅ port 9121 via exporter | `values-enable-observability.yaml` |
| solr-operator | — | ✅ pod annotations port 8080 `/metrics` | `values-enable-observability.yaml` |
| zookeeper-operator | — | ✅ pod annotations port 6000 `/metrics` | `values-enable-observability.yaml` |
| clamav | clamav_exporter sidecar | ✅ port 9906 + ServiceMonitor | `values-enable-observability.yaml` |
| eck-operator | `config.metricsPort` + `podMonitor.enabled` | ✅ PodMonitor port 8080 `/metrics` | `values-enable-observability.yaml` |
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

## Logs — nothing to configure

When `monitoring-logging` is deployed with its default Alloy DaemonSet, **every pod in every namespace is collected automatically**. Alloy tails `/var/log/pods/{namespace}_{pod}_{uid}/{container}/0.log` on each node and ships to Loki with labels `namespace`, `pod`, `container`, and `app`.

Nothing needs to be added to `podiumd/values.yaml` for logs.

> **Note:** The `telemetry/otel-logs: "true"` pod label referenced in older docs is no longer used. Alloy no longer filters on that label — all pods are collected regardless.

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

## OTEL Configuration — Maykin Apps

All Maykin subcharts share the same `settings.otel` schema:

**⚠️ Critical:** the correct values path is `<service>.settings.otel.*`, **not** `<service>.otel.*`. The top-level `otel:` block shown in some older documentation is dead code — the subcharts only read `settings.otel.*`.

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

**What this enables:**

| Metric | Description |
|---|---|
| `http_server_active_requests` | Current in-flight HTTP requests |
| `http_server_duration_milliseconds_*` | Request latency histogram (bucket/count/sum) |

Metrics flow via: `pod → OTLP gRPC :4317 → OTel Collector → Prometheus remote write`.

> **Do not** create a ServiceMonitor or PodMonitor for services that have OTel enabled — it causes duplicate series in Prometheus.

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

Keycloak exposes Prometheus metrics on port 9000. `additionalOptions` in `values.yaml` enables the metrics endpoint. Scrape annotations are in `values-enable-observability.yaml`:

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
        prometheus.io/path: "/metrics"
```

See [kubernetes/keycloak-operator/OTEL_AND_METRICS.md](../../../podiumd-infra/kubernetes/keycloak-operator/OTEL_AND_METRICS.md) for adding OTel tracing to Keycloak.

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

## Per-cluster k8s metrics

Prometheus scrapes the following cluster-level metric sources automatically, **without any ServiceMonitor or PodMonitor**. These are enabled by the built-in scrape jobs in the `prometheus-community/prometheus` chart used by `monitoring-logging`.

| Scrape job | What it collects |
|---|---|
| `kubernetes-apiservers` | kube-apiserver request rates, latency, etcd interaction |
| `kubernetes-nodes` | Kubelet metrics per node (pod counts, volume mounts, etc.) |
| `kubernetes-nodes-cadvisor` | Container CPU, memory, filesystem, network usage per pod |
| `kubernetes-pods` | Any pod with `prometheus.io/scrape: "true"` annotation |
| `kubernetes-service-endpoints` | Any Service endpoint with `prometheus.io/scrape: "true"` annotation |

### What you need to do per cluster

#### 1. Prometheus RBAC

The Prometheus service account needs a `ClusterRole` to scrape cluster-wide resources. The `prometheus-community/prometheus` chart creates this automatically. **Verify** the ClusterRole exists after installation:

```bash
kubectl get clusterrole monitoring-prometheus-server
kubectl get clusterrolebinding monitoring-prometheus-server
```

If missing, the chart may have been installed without `rbac.create: true` (the default). Add to `values-monitoring.yaml`:

```yaml
prometheus:
  serviceAccounts:
    server:
      create: true
  rbac:
    create: true
```

#### 2. Annotation-based pod scraping

For any pod that exposes a `/metrics` endpoint but has no ServiceMonitor, add these annotations to the pod template in the relevant `podiumd/values.yaml` block:

```yaml
<service>:
  podAnnotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "<metrics-port>"
    prometheus.io/path: "/metrics"
```

The `kubernetes-pods` scrape job picks these up automatically — no ServiceMonitor needed.

#### 3. Traefik (ingress controller)

Traefik exposes Prometheus metrics at `/metrics` on port `9100` (or as configured). Enable via annotation or ServiceMonitor depending on the cluster's Traefik deployment. For AKS clusters where Traefik is deployed separately:

```yaml
# traefik/values.yaml or via annotations on the Traefik deployment
traefik:
  podAnnotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "9100"
    prometheus.io/path: "/metrics"
```

#### 4. kube-state-metrics and node-exporter

These are deployed as sub-charts of `monitoring-logging` (via `prometheus-community/prometheus`). They are enabled by default:

```yaml
# monitoring-logging/values.yaml defaults — these are already set
prometheus:
  kube-state-metrics:
    enabled: true
  prometheus-node-exporter:
    enabled: true
```

No extra cluster configuration is needed. Both DaemonSets/Deployments run with the correct RBAC automatically.

#### 5. Remote write receiver

The OTel Collector pushes metrics to Prometheus via remote write. This requires the Prometheus server to start with `--web.enable-remote-write-receiver`. This is already configured in `monitoring-logging/values.yaml`:

```yaml
prometheus:
  server:
    extraFlags:
      - web.enable-remote-write-receiver
```

No per-cluster change needed — it is part of the chart defaults.

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

Verify: `kubectl get servicemonitor -n podiumd | grep solr`, then query `solr_` in Prometheus.

---

### Zookeeper (cluster)

Zookeeper 3.5+ has a built-in Prometheus metrics provider on port `7000`. The ZAC chart's
`solrcloud.yaml` template does **not** pass `spec.conf` to the `ZookeeperCluster` CR — this
requires either a ZAC chart change (upstream) or a manual one-time patch of the CR.

The `ZookeeperCluster` CRD supports a `spec.conf.additionalConfig` map. Patch the live CR:

```bash
kubectl patch zookeepercluster -n podiumd <name> --type merge -p '{
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

---

## Summary

| Signal | Source | How | Config needed? |
|---|---|---|---|
| **Logs** | All pods | Alloy tails log files | ❌ None |
| **Metrics (Django apps)** | OpenZaak, Objecten, etc. | OTel SDK → OTLP gRPC → Collector → Prometheus | ✅ `settings.otel.*` in values |
| **Metrics (Keycloak)** | Keycloak pod | Prometheus annotation scrape (port 9000) | ✅ Annotations in Keycloak CR |
| **Metrics (cluster)** | kube-apiserver, kubelet, cadvisor | Built-in Prometheus scrape jobs | ✅ RBAC ClusterRole (auto via chart) |
| **Metrics (infra pods)** | kube-state-metrics, node-exporter, Traefik | Built-in scrape jobs + annotations | ✅ Annotations on Traefik pod |