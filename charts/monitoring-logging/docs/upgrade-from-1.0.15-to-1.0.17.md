# Upgrade guide: monitoring-logging 1.0.15 → 1.0.17

## Summary of changes

One new Grafana dashboard for Frank!Gateway (APISIX). No component version changes, no breaking values changes, no operator action required in environments that do not run the gateway.

> **Version numbering**: 1.0.16 is reserved by a separate in-flight change, so this release takes 1.0.17.

### New: Frank!Gateway dashboard

The dashboard was previously carried per-environment in the deploy repository, so every municipality enabling the gateway had to copy the JSON by hand. It now ships next to the ServiceMonitor that produces the metrics it reads (podiumd chart, `frankgateway.metrics.serviceMonitor.enabled`).

Three new files/keys:

| What | Where |
|---|---|
| Dashboard JSON | `dashboards/frankgateway.json` |
| ConfigMap template | `templates/frankgateway-dashboard.yaml` |
| Provider entry | `grafana.dashboardProviders."dashboardproviders.yaml".providers[5]`, folder `PodiumD_Metrics` |
| ConfigMap name | `grafana.dashboardsConfigMaps.frankgateway`, default `"frankgateway-dashboard"` |

The dashboard carries a **Traffic class** variable filtering on the `instance_name` label, so a single dashboard serves all three gateways once the per-traffic-class split (inway / outway / internal) is enabled. Its `All` value is a `.*` regex rather than Grafana's normal all-value, which also matches series carrying no `instance_name` label at all — so the dashboard renders correctly on single-instance deployments too.

The log panel parses the JSON access-log format shipped alongside it, prefixing each line with instance, status, method and URI.

Panels read: `apisix_http_status`, `apisix_http_latency_bucket{type="request"}`, `apisix_bandwidth`, `apisix_nginx_http_current_connections`, `up{job=~".*frankgateway.*"}`, and a Loki stream on `{namespace="podiumd", pod=~"frankgateway.*", container="apisix"}`.

### Disabling it

Environments that do not run Frank!Gateway can skip the dashboard:

```yaml
grafana:
  dashboardsConfigMaps:
    frankgateway: ""
```

The provider entry is harmless when the ConfigMap is absent — Grafana simply finds an empty directory.

---

## No other changes

No breaking changes, no image updates, no values schema migrations. Dependency versions are unchanged from 1.0.15.
