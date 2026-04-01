# Upgrade guide: monitoring-logging 1.0.10 → 1.0.11

## Summary of changes

| Area | Change |
|---|---|
| Log agent | **Promtail removed** — replaced by Grafana Alloy |
| New component | **OpenTelemetry Collector** — OTLP gateway for logs, metrics, traces |
| New component | **Grafana Tempo** — distributed tracing backend (disabled by default) |
| Architecture | **OTel-first pipeline** — pods labelled `telemetry/otel-logs: "true"` are excluded from Alloy log collection |
| Loki | 6.40.0 (app 3.5.5) → 6.55.0 (app 3.6.7) |
| Grafana | 10.0.0 (app 10.x) → 10.5.15 (app 12.3.0) |
| Prometheus | 27.39.0 → 28.14.1 — **breaking: `scrape_configs` key renamed to `scrapeConfigs`** |

---

## Breaking changes

### Promtail removed

Remove all `promtail:` blocks from every environment values file. Alloy replaces Promtail as the node-level log agent and requires no per-environment configuration — it collects logs from all pods automatically.

```yaml
# Remove from values-monitoring-<env>.yaml:
promtail:
  enabled: true
  ...
```

### Prometheus 28.x — `scrape_configs` renamed

If any environment values file defines custom scrape configs using the old key, rename it:

```yaml
# Old (no longer works):
prometheus:
  server:
    scrape_configs: ...

# New:
prometheus:
  server:
    scrapeConfigs: ...
```

---

## New features

### Grafana Alloy (replaces Promtail)

Alloy is deployed as a DaemonSet and tails pod log files from `/var/log/pods/`. No environment values changes are needed — the chart default collects logs from all pods in all namespaces.

**OTel-first exclusion:** pods that already send logs via OTLP can be excluded from Alloy collection by adding the pod label `telemetry/otel-logs: "true"` in `podiumd/values.yaml`. See `docs/otel.md` for per-service guidance.

### OpenTelemetry Collector

A shared OTLP gateway is deployed as a Deployment. Applications send logs, metrics, and traces to:

| Protocol | Address |
|---|---|
| gRPC | `<release>-opentelemetry-collector.<monitoring-ns>.svc.cluster.local:4317` |
| HTTP | `<release>-opentelemetry-collector.<monitoring-ns>.svc.cluster.local:4318` |

The collector forwards to Loki (logs), Prometheus remote write (metrics), and Tempo (traces when enabled).

### Grafana Tempo (disabled by default)

Enable distributed tracing storage with:

```yaml
tempo:
  enabled: true
```

Requires `opentelemetry-collector.enabled: true` (default) and applications configured to send traces via OTLP.

---

## Environment values changes

### Remove Promtail, verify Alloy is enabled

```yaml
# values-monitoring-<env>.yaml

# Remove:
promtail:
  enabled: true
  ...

# Alloy is enabled by default — no entry needed.
# To disable (not recommended):
alloy:
  enabled: false
```

### Loki storage

The Loki chart upgrade (6.40.0 → 6.55.0) is backward-compatible with the MinIO storage backend. No migration needed for environments using the embedded MinIO.

For environments planning to migrate to Azure Blob Storage, see `docs/loki-storage.md`.

---

## ACR image overrides

For environments that pull images from an Azure Container Registry (ACR), override the following keys in `values-monitoring-<env>.yaml`. Replace `<acr>` with your registry hostname (e.g. `acrprodmgmt.azurecr.io`).

### Grafana

| Image | Original URL |
|---|---|
| Grafana | `docker.io/grafana/grafana:12.3.0-17814087142-ubuntu` |
| curl (dashboard download) | `docker.io/curlimages/curl:8.16.0` |
| busybox (init) | `docker.io/library/busybox:1.37.0-uclibc` |
| grafana-image-renderer | `docker.io/grafana/grafana-image-renderer:v4.0.14` |
| bats (test framework) | `docker.io/bats/bats:1.12.0` |
| k8s-sidecar | `docker.io/kiwigrid/k8s-sidecar:1.30.10` |

```yaml
grafana:
  image:
    registry: <acr>
    repository: grafana/grafana
  downloadDashboardsImage:
    registry: <acr>
    repository: curlimages/curl
  initChownData:
    image:
      registry: <acr>
      repository: library/busybox
  imageRenderer:
    image:
      registry: <acr>
      repository: grafana/grafana-image-renderer
  testFramework:
    image:
      registry: <acr>
      repository: bats/bats
  sidecar:
    image:
      registry: <acr>
      repository: kiwigrid/k8s-sidecar
```

### Prometheus

| Image | Original URL |
|---|---|
| Prometheus server | `quay.io/prometheus/prometheus:v3.6.0` |
| config-reloader | `quay.io/prometheus-operator/prometheus-config-reloader:v0.85.0` |
| node-exporter | `quay.io/prometheus/node-exporter:v1.9.1` |
| kube-rbac-proxy | `quay.io/brancz/kube-rbac-proxy:0.19.1` |
| pushgateway | `quay.io/prometheus/pushgateway:v1.11.1` |
| kube-state-metrics | `registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.17.0` |

```yaml
prometheus:
  server:
    image:
      repository: <acr>/prometheus/prometheus
  configmapReload:
    prometheus:
      image:
        repository: <acr>/prometheus-operator/prometheus-config-reloader
  prometheus-node-exporter:
    image:
      registry: <acr>
      repository: prometheus/node-exporter
    kubeRBACProxy:
      image:
        registry: <acr>
        repository: brancz/kube-rbac-proxy
  prometheus-pushgateway:
    image:
      repository: <acr>/prometheus/pushgateway
  kube-state-metrics:
    image:
      registry: <acr>
      repository: kube-state-metrics/kube-state-metrics
```

> **Note:** `prometheus.server` and `prometheus-pushgateway` embed the registry in `repository` (no separate `registry` field). Prefix with `<acr>/` and omit the original registry prefix (`quay.io/`).

### Grafana Alloy *(new in 1.0.11)*

| Image | Original URL |
|---|---|
| Alloy | `docker.io/grafana/alloy:v1.14.0` |

```yaml
alloy:
  image:
    registry: <acr>
    repository: grafana/alloy
```

### Loki

| Image | Original URL |
|---|---|
| Loki (all components) | `docker.io/grafana/loki:3.6.7` |
| nginx-unprivileged (gateway) | `docker.io/nginxinc/nginx-unprivileged:alpine3.22-perl` |
| memcached (chunks/results cache) | `docker.io/library/memcached:alpine3.22` |
| memcached-exporter | `docker.io/prom/memcached-exporter:v0.15.3` |
| k8s-sidecar | `docker.io/kiwigrid/k8s-sidecar:1.30.10` |
| kubectl (migration jobs) | `docker.io/bitnami/kubectl:1.33.3-debian-12-r1` |
| MinIO | `quay.io/minio/minio:RELEASE.2025-07-23T15-54-02Z-cpuv1` |
| MinIO mc | `quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z-cpuv1` |

```yaml
loki:
  loki:
    image:
      registry: <acr>
      repository: grafana/loki
  gateway:
    image:
      registry: <acr>
      repository: nginxinc/nginx-unprivileged
  memcached:
    image:
      registry: <acr>
      repository: library/memcached
  memcachedExporter:
    image:
      registry: <acr>
      repository: prom/memcached-exporter
  sidecar:
    image:
      registry: <acr>
      repository: kiwigrid/k8s-sidecar
  kubectlImage:
    registry: <acr>
    repository: bitnami/kubectl
  minio:
    global:
      image:
        registry: <acr>
    image:
      repository: minio/minio
    mcImage:
      repository: minio/mc
```

### OpenTelemetry Collector *(new in 1.0.11)*

| Image | Original URL |
|---|---|
| OTel Collector K8s | `ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-k8s:0.147.0` |

```yaml
opentelemetry-collector:
  image:
    repository: <acr>/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-k8s
```

> The OTel collector chart embeds the registry in `repository`. Prefix with `<acr>/` and omit `ghcr.io/`.

### Grafana Tempo *(new in 1.0.11, disabled by default)*

| Image | Original URL |
|---|---|
| Tempo | `docker.io/grafana/tempo:2.9.0` |

```yaml
tempo:
  tempo:
    image:
      registry: <acr>
      repository: grafana/tempo
```

---

## Pre-deploy steps

1. **Remove Promtail values** from every environment values file (see [Breaking changes](#breaking-changes)).

2. **Add Helm repos** if not already present:
   ```bash
   helm repo add grafana https://grafana.github.io/helm-charts
   helm repo add opentelemetry https://open-telemetry.github.io/opentelemetry-helm-charts
   helm repo update
   ```

3. **Update chart dependencies:**
   ```bash
   cd charts/monitoring-logging
   helm dependency update
   ```

4. **Verify the rendered templates** before deploying:
   ```bash
   helm template monitoring charts/monitoring-logging \
     -f values-monitoring-<env>.yaml \
     -n monitoring
   ```

5. **Deploy:**
   ```bash
   helm upgrade --install monitoring charts/monitoring-logging \
     -f values-monitoring-<env>.yaml \
     -n monitoring \
     --create-namespace
   ```
