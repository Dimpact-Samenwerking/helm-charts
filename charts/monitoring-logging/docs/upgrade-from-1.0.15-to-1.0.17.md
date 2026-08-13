# Upgrade guide: monitoring-logging 1.0.15 → 1.0.17

## Summary of changes

Two new Grafana dashboards for Frank!Gateway (APISIX), one of them off by
default. **No operator action, no values changes, no component version
changes.** Frank!Gateway is not deployed in any customer environment, so this
hop is a no-op everywhere today.

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

### New, and off: Frank!Gateway alert panels

A second dashboard (`dashboards/frankgateway-alerts.json`, ConfigMap key
`grafana.dashboardsConfigMaps."frankgateway-alerts"`, default `""` = **not
rendered**) carrying threshold panels: gateways and etcd members up, 5xx and
401/403 rates per traffic class, certificate days-to-expiry, and failed
certificate-sync and route-seeding Jobs.

**These are panels, not alerts.** Nothing fires and nothing routes: production
alerting is Datadog, and Alertmanager is disabled in this chart
(`alertmanager.enabled: false`), so a `PrometheusRule` added here would
evaluate into a void and read as coverage that does not exist. The panels state
the conditions worth alerting on, with their thresholds visible, so the Datadog
monitors have a source and an investigation has a starting point.

Turn it on where someone actually looks at Grafana:

```yaml
grafana:
  dashboardsConfigMaps:
    frankgateway-alerts: "frankgateway-alerts-dashboard"
```

Two panels need metrics this chart does not itself produce: days-to-expiry
needs cert-manager's own metrics scraped, and the Job panels need
`kube-state-metrics` (shipped with kube-prometheus-stack). Both render empty
rather than wrong when the metric is absent.

### Disabling the dashboards

Environments that do not run Frank!Gateway can skip both:

```yaml
grafana:
  dashboardsConfigMaps:
    frankgateway: ""
    frankgateway-alerts: ""
```

The provider entries are harmless when the ConfigMaps are absent — Grafana
simply finds an empty directory.
