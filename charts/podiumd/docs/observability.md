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

`additionalOptions` in `values.yaml` enables the metrics endpoint. Scrape annotations are in `values-enable-observability.yaml`:

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
