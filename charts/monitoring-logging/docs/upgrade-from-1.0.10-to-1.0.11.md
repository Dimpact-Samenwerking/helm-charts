# Upgrade guide: monitoring-logging 1.0.10 → 1.0.11

## Summary of changes

### Architecture & features

| Area | Change |
|---|---|
| Log agent | **Promtail removed** — replaced by Grafana Alloy |
| Prometheus | **Standalone chart replaced by kube-prometheus-stack** (Prometheus Operator) — enables ServiceMonitor and PodMonitor support |
| New component | **OpenTelemetry Collector** — OTLP gateway for logs, metrics, traces |
| New component | **Grafana Tempo** — distributed tracing backend (disabled by default) |
| New feature | **OTel HTTP bearer token auth** — OTLP HTTP endpoint (port 4318) protected with bearer token |
| Architecture | **OTel-first pipeline** — OpenTelemetry Collector introduced as shared OTLP gateway for logs, metrics, and traces; Alloy collects logs from all pods unconditionally as fallback |

### Chart dependency changes

| Chart | 1.0.10 | 1.0.11 | App version |
|---|---|---|---|
| loki | 6.40.0 | 6.55.0 | 3.5.5 → 3.6.7 |
| grafana | 10.0.0 | 10.5.15 | 10.x → 12.3.0 |
| prometheus *(removed)* | 27.39.0 | — | — |
| kube-prometheus-stack *(replaces prometheus)* | — | 83.0.0 | Prometheus v3.6.0, Operator v0.90.1 |
| prometheus-pushgateway *(extracted from prometheus chart)* | — | 3.6.0 | v1.11.1 |
| alloy *(replaces promtail)* | — | 1.6.2 | v1.14.0 |
| promtail *(removed)* | 6.17.0 | — | — |
| opentelemetry-collector *(new)* | — | 0.147.1 | 0.147.0 |
| tempo *(new, disabled by default)* | — | 1.24.4 | 2.9.0 |

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

Alloy collects logs from **all pods** unconditionally — no pod labels or configuration changes in `podiumd/values.yaml` are needed. OTel-instrumented apps can send logs via OTLP in addition; Alloy serves as the universal fallback.

### OpenTelemetry Collector

A shared OTLP gateway is deployed as a Deployment. Applications send logs, metrics, and traces to:

| Protocol | Address |
|---|---|
| gRPC | `<release>-opentelemetry-collector.<monitoring-ns>.svc.cluster.local:4317` |
| HTTP | `<release>-opentelemetry-collector.<monitoring-ns>.svc.cluster.local:4318` |

The collector forwards to Loki (logs), Prometheus remote write (metrics), and Tempo (traces when enabled).

### OTel HTTP bearer token authentication

The OTLP HTTP endpoint (port 4318) is protected with bearer token authentication. The token is configured via the `OTEL_HTTP_AUTH_TOKEN` environment variable in the collector, which defaults to the SSC placeholder `REP_OTEL_HTTP_AUTH_TOKEN_REP`.

Set the actual token value in your environment values file:

```yaml
opentelemetry-collector:
  extraEnvs:
    - name: OTEL_HTTP_AUTH_TOKEN
      value: "<your-token>"
```

Applications sending OTLP to the HTTP endpoint must include the `Authorization: Bearer <token>` header. See `docs/otel.md` (Securing the HTTP endpoint) for per-SDK configuration snippets.

> The gRPC endpoint (port 4317) is cluster-internal and does not require authentication.

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

## Node selectors

**Node selectors have been removed from `values.yaml`** in 1.0.11. The chart no longer defaults to `agentpool: userpool`. Every environment must now set node selectors explicitly in its own values file.

### Why

Different environments use different node pool label values (e.g. `agentpool: userpool`, `kubernetes.azure.com/agentpool: userpool`, or custom names). Baking a single default into the chart caused `coalesce` warnings and confusion when environments tried to override with `null`.

### How to set node selectors

Every component that runs pods needs a `nodeSelector` entry. The full list of keys is:

```yaml
grafana:
  nodeSelector:
    <key>: <value>

kube-prometheus-stack:
  prometheus:
    prometheusSpec:
      nodeSelector:
        <key>: <value>
  prometheusOperator:
    nodeSelector:
      <key>: <value>
    admissionWebhooks:
      patch:
        # certgen Job — runs at install/upgrade to provision webhook TLS cert
        nodeSelector:
          <key>: <value>
  prometheus-node-exporter:
    nodeSelector:
      <key>: <value>
  kube-state-metrics:
    nodeSelector:
      <key>: <value>
  # alertmanager is disabled by default (alertmanager.enabled: false).
  # Set nodeSelector here if you enable it.
  alertmanager:
    alertmanagerSpec:
      nodeSelector:
        <key>: <value>

prometheus-pushgateway:
  nodeSelector:
    <key>: <value>

alloy:
  nodeSelector:
    <key>: <value>

loki:
  resultsCache:
    nodeSelector:
      <key>: <value>
  chunksCache:
    nodeSelector:
      <key>: <value>
  indexGateway:
    nodeSelector:
      <key>: <value>
  queryScheduler:
    nodeSelector:
      <key>: <value>
  queryFrontend:
    nodeSelector:
      <key>: <value>
  distributor:
    nodeSelector:
      <key>: <value>
  querier:
    nodeSelector:
      <key>: <value>
  gateway:
    nodeSelector:
      <key>: <value>
  ingester:
    nodeSelector:
      <key>: <value>
    zoneAwareReplication:
      zoneA:
        nodeSelector:
          <key>: <value>
      zoneB:
        nodeSelector:
          <key>: <value>
      zoneC:
        nodeSelector:
          <key>: <value>
  compactor:
    nodeSelector:
      <key>: <value>
  minio:
    nodeSelector:
      <key>: <value>

tempo:
  nodeSelector:
    <key>: <value>

opentelemetry-collector:
  nodeSelector:
    <key>: <value>
```

> **Fields intentionally omitted from the list above:**
> - `kube-prometheus-stack.prometheusOperator.admissionWebhooks.deployment.nodeSelector` — only relevant when `admissionWebhooks.deployment.enabled: true` (disabled by default)
> - `kube-prometheus-stack.alertmanager.alertmanagerSpec.nodeSelector` is included above but `alertmanager.enabled: false` in this chart; only set it if you enable alertmanager
> - `kube-prometheus-stack.crds.upgradeJob.nodeSelector` — only relevant when `crds.enabled: true`; this chart manages CRDs externally
> - `kube-prometheus-stack.thanosRuler.thanosRulerSpec.nodeSelector` — ThanosRuler is not used in this chart

### Automatic migration script

To add `nodeSelector` entries to an existing environment values file (only for components that don't already have one):

```bash
./charts/monitoring-logging/scripts/add-node-selectors.sh values-monitoring-<env>.yaml \
  --key agentpool \
  --value userpool
```

Options:

| Flag | Default | Description |
|---|---|---|
| `--key` | `kubernetes.azure.com/agentpool` | Node label key |
| `--value` | `userpool` | Node label value |
| `--dry-run` | — | Preview changes without writing |

The script skips any component that already has a `nodeSelector` block, so it is safe to run on partially-migrated files.

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

### kube-prometheus-stack *(replaces prometheus)*

| Image | Original URL |
|---|---|
| Prometheus server | `quay.io/prometheus/prometheus:v3.6.0` |
| Prometheus Operator | `quay.io/prometheus-operator/prometheus-operator:v0.90.1` |
| admission-webhook | `quay.io/prometheus-operator/admission-webhook:v0.90.1` |
| prometheus-config-reloader (operator → Prometheus StatefulSet) | `quay.io/prometheus-operator/prometheus-config-reloader:v0.90.1` |
| kube-webhook-certgen (admission webhook TLS job) | `ghcr.io/jkroepke/kube-webhook-certgen:1.8.0` |
| node-exporter | `quay.io/prometheus/node-exporter:v1.9.1` |
| kube-state-metrics | `registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.17.0` |
| pushgateway | `quay.io/prometheus/pushgateway:v1.11.1` |

```yaml
kube-prometheus-stack:
  prometheusOperator:
    image:
      registry: <acr>
      repository: prometheus-operator/prometheus-operator
    admissionWebhooks:
      image:
        registry: <acr>
        repository: prometheus-operator/admission-webhook
      patch:
        image:
          registry: <acr>
          repository: jkroepke/kube-webhook-certgen
    prometheusConfigReloader:
      image:
        registry: <acr>
        repository: prometheus-operator/prometheus-config-reloader
  prometheus:
    prometheusSpec:
      image:
        registry: <acr>
        repository: prometheus/prometheus
  prometheus-node-exporter:
    image:
      registry: <acr>
      repository: prometheus/node-exporter
  kube-state-metrics:
    image:
      registry: <acr>
      repository: kube-state-metrics/kube-state-metrics

prometheus-pushgateway:
  image:
    repository: <acr>/prometheus/pushgateway
```

> **Note:** `prometheus-pushgateway` embeds the registry in `repository` (no separate `registry` field). Prefix with `<acr>/` and omit the original `quay.io/` prefix.

### Grafana Alloy *(new in 1.0.11)*

| Image | Original URL |
|---|---|
| Alloy | `docker.io/grafana/alloy:v1.14.0` |
| config-reloader sidecar (Alloy hot-reload) | `quay.io/prometheus-operator/prometheus-config-reloader:v0.81.0` |

```yaml
alloy:
  image:
    registry: <acr>
    repository: grafana/alloy
  configReloader:
    image:
      registry: <acr>
      repository: prometheus-operator/prometheus-config-reloader
```

> **Note:** The Alloy config-reloader (`v0.81.0`) is a separate image from the operator's config-reloader (`v0.90.1`). Both must be overridden independently.

### Loki

| Image | Original URL |
|---|---|
| Loki (all components) | `docker.io/grafana/loki:3.6.7` |
| nginx-unprivileged (gateway) | `docker.io/nginxinc/nginx-unprivileged:alpine3.22-perl` |
| memcached (chunks/results cache) | `docker.io/library/memcached:alpine3.22` |
| memcached-exporter | `docker.io/prom/memcached-exporter:v0.15.3` |
| k8s-sidecar | `docker.io/kiwigrid/k8s-sidecar:1.30.10` |
| kubectl (migration jobs) | `registry.k8s.io/kubectl:v1.33.0` |
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
    repository: kubectl
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
| OTel Collector contrib | `ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-contrib:0.147.0` |

```yaml
opentelemetry-collector:
  image:
    repository: <acr>/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-contrib
```

> The OTel collector chart embeds the registry in `repository`. Prefix with `<acr>/` and omit `ghcr.io/`.

### Loki kubectl image *(changed in 1.0.11)*

The Loki migration-job kubectl image has been changed from `docker.io/bitnami/kubectl` to `registry.k8s.io/kubectl:v1.33.0`.

| Image | Original URL |
|---|---|
| kubectl | `registry.k8s.io/kubectl:v1.33.0` |

```yaml
loki:
  kubectlImage:
    registry: <acr>
    repository: kubectl
```

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

## Storage gotchas

### PVC sizes must not decrease

Kubernetes does not allow shrinking a PVC. If your environment values file sets a `size` smaller than the currently provisioned PVC capacity, the upgrade will fail with:

```
PersistentVolumeClaim "<name>" is invalid: spec.resources.requests.storage: Forbidden: field can not be less than status.capacity
```

Affected components and the keys to check:

| Component | Values key | Default in chart |
|---|---|---|
| Grafana | `grafana.persistence.size` | `10Gi` |
| MinIO (Loki) | `loki.minio.persistence.size` | `5Gi` |
| Prometheus (new) | `kube-prometheus-stack.prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage` | `20Gi` |

If your cluster already has larger PVCs from a previous deployment, **set the size in your environment values file to match the existing PVC capacity** (at minimum). You can check existing sizes with:

```bash
kubectl --context <cluster> get pvc -n <monitoring-namespace>
```

### Minio StatefulSet volumeClaimTemplates are immutable

Kubernetes forbids changing `spec.volumeClaimTemplates` on an existing StatefulSet. If the MinIO PVC `size` in your values file differs from what was used when the StatefulSet was first created, the upgrade will fail with:

```
StatefulSet.apps "monitoring-minio" is invalid: spec: Forbidden: updates to statefulset spec for fields other than 'replicas', ...
```

The fix is the same: set `loki.minio.persistence.size` to match the size that was used when MinIO was first deployed (i.e. the capacity of the existing `export-*-monitoring-minio-*` PVCs). Do **not** try to resize — if you need more space, manually resize the underlying PVC via the storage class and keep the values file in sync.

### Orphaned Prometheus PVC after migration

After a successful upgrade from the standalone `prometheus` chart, the old PVC (`<release>-prometheus-server`) is no longer claimed by any pod. Helm will remove the old Deployment but Kubernetes retains PVCs with `Retain` reclaim policy. You can safely delete it once the new Prometheus StatefulSet is running and scraping correctly:

```bash
kubectl --context <cluster> delete pvc <release>-prometheus-server -n <monitoring-namespace>
```

---

## Pre-deploy steps

1. **Remove Promtail values** from every environment values file (see [Breaking changes](#breaking-changes)).

2. **Install Prometheus Operator CRDs** before deploying the chart (the chart no longer installs CRDs itself):
   ```bash
   helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
   helm repo update
   ./charts/monitoring-logging/scripts/install-prometheus-operator-crds.sh --context <cluster>
   ```
   This installs the `monitoring.coreos.com` CRDs (ServiceMonitor, PodMonitor, Prometheus, PrometheusRule, etc.) via server-side apply. The `--upgrade` flag re-applies them if they already exist from a previous installation.

3. **Add Helm repos** if not already present:
   ```bash
   helm repo add grafana https://grafana.github.io/helm-charts
   helm repo add opentelemetry https://open-telemetry.github.io/opentelemetry-helm-charts
   helm repo update
   ```

4. **Update chart dependencies:**
   ```bash
   cd charts/monitoring-logging
   helm dependency update
   ```

5. **Migrate environment values files** — see [Prometheus operator migration](#prometheus-operator-migration) below.

6. **Verify the rendered templates** before deploying:
   ```bash
   helm template monitoring charts/monitoring-logging \
     -f values-monitoring-<env>.yaml \
     -n monitoring
   ```

7. **Deploy:**
   ```bash
   helm upgrade --install monitoring charts/monitoring-logging \
     -f values-monitoring-<env>.yaml \
     -n monitoring \
     --create-namespace
   ```

---

## Prometheus operator migration

Prometheus is now managed by **kube-prometheus-stack 83.0.0** (Prometheus Operator v0.90.1) instead of the standalone `prometheus-community/prometheus` chart. This enables native ServiceMonitor and PodMonitor support.

### Breaking changes

#### Values structure

All `prometheus.*` keys are replaced with `kube-prometheus-stack.*`. Use the migration script to handle the mechanical renames:

```bash
./charts/monitoring-logging/scripts/migrate-prometheus-to-kube-prometheus-stack.sh \
  values-monitoring-<env>.yaml
```

The script applies all automatic substitutions and flags items that need manual attention (storage, pushgateway). Review its output and the generated `-migrated.yaml` file before deploying.

Key mapping summary:

| Old key | New key |
|---|---|
| `prometheus.enabled` | `kube-prometheus-stack.enabled` |
| `prometheus.server.image` | `kube-prometheus-stack.prometheus.prometheusSpec.image` |
| `prometheus.server.extraFlags: [web.enable-remote-write-receiver]` | `kube-prometheus-stack.prometheus.prometheusSpec.additionalArgs: [{name: web.enable-remote-write-receiver, value: ""}]` |
| `prometheus.server.persistentVolume.*` | `kube-prometheus-stack.prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.*` |
| `prometheus.server.nodeSelector` | `kube-prometheus-stack.prometheus.prometheusSpec.nodeSelector` |
| `prometheus.server.resources` | `kube-prometheus-stack.prometheus.prometheusSpec.resources` |
| `prometheus.prometheusSpec.retention` | `kube-prometheus-stack.prometheus.prometheusSpec.retention` |
| `prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues` | `kube-prometheus-stack.prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues` |
| `prometheus.alertmanager.enabled: false` | `kube-prometheus-stack.alertmanager.enabled: false` |
| `prometheus.prometheus-node-exporter.*` | `kube-prometheus-stack.prometheus-node-exporter.*` |
| `prometheus.kube-state-metrics.*` | `kube-prometheus-stack.kube-state-metrics.*` |
| `prometheus.configmapReload.prometheus.*` | `kube-prometheus-stack.prometheusOperator.prometheusConfigReloader.*` |
| `prometheus.prometheus-pushgateway.*` | `prometheus-pushgateway.*` *(top-level — no longer a sub-chart of prometheus)* |

#### Prometheus service name change

The Prometheus ClusterIP service is renamed:

| | Old | New |
|---|---|---|
| Service name | `<release>-prometheus-server` | `<release>-kube-prometheus-stack-prometheus` |
| Port | `80` | `9090` |

Update the following in every environment values file:

```yaml
# Grafana datasource
grafana:
  datasources:
    datasources.yaml:
      datasources:
        - name: Prometheus
          url: http://<release>-kube-prometheus-stack-prometheus:9090  # was: -prometheus-server

# OTel Collector remote-write endpoint
opentelemetry-collector:
  config:
    exporters:
      prometheusremotewrite:
        endpoint: http://<release>-kube-prometheus-stack-prometheus:9090/api/v1/write  # was: -prometheus-server/api/v1/write
```

#### CRDs not installed by the chart

`kube-prometheus-stack.crds.enabled` is set to `false`. The CRDs must be installed separately before the first deploy and upgraded independently of the chart (see step 2 in pre-deploy steps above). This prevents accidental CRD deletion on `helm uninstall`.

#### Pushgateway is now a top-level dependency

`prometheus-pushgateway` is no longer bundled inside the `prometheus` chart. It is now a separate top-level dependency. Move any pushgateway configuration out of the `prometheus:` block:

```yaml
# Remove from inside prometheus:
# prometheus:
#   prometheus-pushgateway:
#     ...

# Add at top level:
prometheus-pushgateway:
  enabled: true
  nodeSelector:
    agentpool: userpool
  image:
    repository: quay.io/prometheus/pushgateway
    tag: v1.11.1
```

> For ACR overrides, see the [kube-prometheus-stack](#kube-prometheus-stack-replaces-prometheus) section in ACR image overrides above.
