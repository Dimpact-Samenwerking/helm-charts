# Observability — PodiumD

This document explains how logs and metrics flow out of a PodiumD deployment and what you need to configure.

> **Prerequisite:** the `monitoring-logging` Helm chart must be deployed in a `monitoring` namespace on the same cluster. See [monitoring-logging/docs/otel.md](../../monitoring-logging/docs/otel.md) for the full OTel pipeline reference and [prometheus-scraping.md](../../monitoring-logging/docs/prometheus-scraping.md) for ServiceMonitor details.

---

## Logs — nothing to configure

When `monitoring-logging` is deployed with its default Alloy DaemonSet, **every pod in every namespace is collected automatically**. Alloy tails `/var/log/pods/{namespace}_{pod}_{uid}/{container}/0.log` on each node and ships to Loki with labels `namespace`, `pod`, `container`, and `app`.

Nothing needs to be added to `podiumd/values.yaml` for logs.

> **Note:** The `telemetry/otel-logs: "true"` pod label referenced in older docs is no longer used. Alloy no longer filters on that label — all pods are collected regardless.

---

## Metrics

### Django applications (OpenZaak, OpenNotificaties, Objecten, Objecttypen, OpenKlant, OpenFormulieren)

These VNG Django subcharts support native OpenTelemetry metrics via `opentelemetry-python`.

**⚠️ Critical:** the correct values path is `<service>.settings.otel.*`, **not** `<service>.otel.*`. The top-level `otel:` block shown in some older documentation is dead code — the subcharts only read `settings.otel.*`.

Add this block for each service you want to instrument:

```yaml
# podiumd/values.yaml — repeat for each Django service
openzaak:
  settings:
    otel:
      disabled: false
      exporterOtlpEndpoint: "http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4317"
      exporterOtlpMetricsInsecure: true   # required: gRPC to a plaintext endpoint needs this

opennotificaties:
  settings:
    otel:
      disabled: false
      exporterOtlpEndpoint: "http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4317"
      exporterOtlpMetricsInsecure: true

objecten:
  settings:
    otel:
      disabled: false
      exporterOtlpEndpoint: "http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4317"
      exporterOtlpMetricsInsecure: true

objecttypen:
  settings:
    otel:
      disabled: false
      exporterOtlpEndpoint: "http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4317"
      exporterOtlpMetricsInsecure: true

openklant:
  settings:
    otel:
      disabled: false
      exporterOtlpEndpoint: "http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4317"
      exporterOtlpMetricsInsecure: true

openformulieren:
  settings:
    otel:
      disabled: false
      exporterOtlpEndpoint: "http://<MONITORING_RELEASE>-opentelemetry-collector.<MONITORING_NS>.svc.cluster.local:4317"
      exporterOtlpMetricsInsecure: true
```

Replace `<MONITORING_RELEASE>` (e.g. `monitoring`) and `<MONITORING_NS>` (e.g. `monitoring`) with the values from your `monitoring-logging` deployment.

**What this enables:**

| Metric | Description |
|---|---|
| `http_server_active_requests` | Current in-flight HTTP requests |
| `http_server_duration_milliseconds_*` | Request latency histogram (bucket/count/sum) |

Metrics flow via: `pod → OTLP gRPC :4317 → OTel Collector → Prometheus remote write`.

> **Do not** create a ServiceMonitor or PodMonitor for services that have OTel enabled — it causes duplicate series in Prometheus.

---

### Keycloak

Keycloak exposes Prometheus metrics on port 9000 automatically (`metrics-enabled: true` is already set in `podiumd/values.yaml`).

To make Prometheus discover the Keycloak pods, add scrape annotations to the pod template via the Keycloak CR (not via `podiumd/values.yaml` — Keycloak is managed by the operator):

```yaml
# keycloak-cr.yaml — spec.unsupported.podTemplate.metadata
unsupported:
  podTemplate:
    metadata:
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9000"
        prometheus.io/path: "/metrics"
```

See [kubernetes/keycloak-operator/OTEL_AND_METRICS.md](../../../podiumd-infra/kubernetes/keycloak-operator/OTEL_AND_METRICS.md) for adding OTel tracing to Keycloak.

---

### Other components

| Component | How | Notes |
|---|---|---|
| ZAC | `javaOptions` JVM flags | See [monitoring-logging/docs/otel.md](../../monitoring-logging/docs/otel.md#zac) |
| KISS | `extraEnv` | Verify .NET OTel SDK is present first |
| Traefik | annotation-based scraping | See [Per-cluster k8s metrics](#per-cluster-k8s-metrics) below |

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

## Summary

| Signal | Source | How | Config needed? |
|---|---|---|---|
| **Logs** | All pods | Alloy tails log files | ❌ None |
| **Metrics (Django apps)** | OpenZaak, Objecten, etc. | OTel SDK → OTLP gRPC → Collector → Prometheus | ✅ `settings.otel.*` in values |
| **Metrics (Keycloak)** | Keycloak pod | Prometheus annotation scrape (port 9000) | ✅ Annotations in Keycloak CR |
| **Metrics (cluster)** | kube-apiserver, kubelet, cadvisor | Built-in Prometheus scrape jobs | ✅ RBAC ClusterRole (auto via chart) |
| **Metrics (infra pods)** | kube-state-metrics, node-exporter, Traefik | Built-in scrape jobs + annotations | ✅ Annotations on Traefik pod |
