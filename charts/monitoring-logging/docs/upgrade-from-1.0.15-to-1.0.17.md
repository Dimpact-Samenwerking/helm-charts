# Upgrade guide: monitoring-logging 1.0.15 → 1.0.17

## Summary of changes

One new Grafana dashboard for Frank!Gateway (APISIX). **No operator action, no
values changes, no component version changes.** Frank!Gateway is not deployed in
any customer environment, so this hop is a no-op everywhere today.

> **Version numbering**: 1.0.16 is reserved by a separate in-flight change, so
> this release takes 1.0.17.

### New: Frank!Gateway dashboard

The dashboard was previously carried per-environment in the deploy repository.
It now ships next to the ServiceMonitor that produces the metrics it reads
(podiumd chart, `frankgateway.metrics.serviceMonitor.enabled`).

| What | Where |
|---|---|
| Dashboard JSON | `dashboards/frankgateway.json` |
| ConfigMap template | `templates/frankgateway-dashboard.yaml` |
| Provider entry | `grafana.dashboardProviders."dashboardproviders.yaml".providers[5]`, folder `PodiumD_Metrics` |
| ConfigMap name | `grafana.dashboardsConfigMaps.frankgateway`, default `"frankgateway-dashboard"` |

A **Traffic class** variable filters on the `instance_name` label, so one
dashboard serves all three gateways (inway / outway / internal).

Panels read `apisix_http_status`, `apisix_http_latency_bucket{type="request"}`,
`apisix_bandwidth`, `apisix_nginx_http_current_connections`,
`up{job=~".*frankgateway.*"}`, and a Loki stream on
`{namespace="podiumd", pod=~"frankgateway.*", container="frankgateway"}`.

### Disabling it

Environments that do not run Frank!Gateway can skip the dashboard:

```yaml
grafana:
  dashboardsConfigMaps:
    frankgateway: ""
```

The provider entry is harmless when the ConfigMap is absent — Grafana simply
finds an empty directory.
