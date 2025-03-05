# Monitoring-Logging PodiumD

![Version: 0.1.0](https://img.shields.io/badge/Version-0.1.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 1.0](https://img.shields.io/badge/AppVersion-1.0-informational?style=flat-square)

A monitoring stack using Loki, Promtail and Grafana

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| https://grafana.github.io/helm-charts | loki |  |
| https://grafana.github.io/helm-charts | promtail |  |
| https://grafana.github.io/helm-charts | grafana |  |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| grafana.additionalDataSources[0].access | string | `"proxy"` |  |
| grafana.additionalDataSources[0].editable | bool | `true` |  |
| grafana.additionalDataSources[0].jsonData.derivedFields[0].datasourceUid | string | `"tempo"` |  |
| grafana.additionalDataSources[0].jsonData.derivedFields[0].matcherRegex | string | `"((\\d+|[a-z]+)(\\d+|[a-z]+)(\\d+|[a-z]+)(\\d+|[a-z]+)(\\d+|[a-z]+)(\\d+|[a-z]+)(\\d+|[a-z]+)(\\d+|[a-z]+)(\\d+|[a-z]+)(\\d+|[a-z]+)(\\d+|[a-z]+))"` |  |
| grafana.additionalDataSources[0].jsonData.derivedFields[0].name | string | `"TraceID"` |  |
| grafana.additionalDataSources[0].jsonData.derivedFields[0].url | string | `"$${__value.raw}"` |  |
| grafana.additionalDataSources[0].jsonData.maxLines | int | `1000` |  |
| grafana.additionalDataSources[0].name | string | `"loki"` |  |
| grafana.additionalDataSources[0].readOnly | bool | `false` |  |
| grafana.additionalDataSources[0].type | string | `"loki"` |  |
| grafana.additionalDataSources[0].uid | string | `"loki"` |  |
| grafana.additionalDataSources[0].url | string | `"http://loki:3100"` |  |
| grafana.additionalDataSources[0].version | int | `1` |  |
| grafana.additionalDataSources[1].access | string | `"proxy"` |  |
| grafana.additionalDataSources[1].editable | bool | `true` |  |
| grafana.additionalDataSources[1].name | string | `"Tempo"` |  |
| grafana.additionalDataSources[1].readOnly | bool | `false` |  |
| grafana.additionalDataSources[1].type | string | `"tempo"` |  |
| grafana.additionalDataSources[1].uid | string | `"tempo"` |  |
| grafana.additionalDataSources[1].url | string | `"http://tempo:3100"` |  |
| grafana.additionalDataSources[1].version | int | `1` |  |
| grafana.assertNoLeakedSecrets | bool | `false` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".apiVersion | int | `1` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].allowUiUpdates | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].disableDeletion | bool | `false` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].editable | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].folder | string | `""` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].name | string | `"default"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].options.path | string | `"/var/lib/grafana/dashboards/default"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].orgId | int | `1` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].type | string | `"file"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].updateIntervalSeconds | int | `10` |  |
| grafana.dashboards.default.Monitoring.datasource | string | `"Loki"` |  |
| grafana.dashboards.default.Monitoring.token | string | `""` |  |
| grafana.dashboards.default.Monitoring.url | string | `nil` |  |
| grafana.persistence.accessModes[0] | string | `"ReadWriteOnce"` |  |
| grafana.persistence.enabled | bool | `true` |  |
| grafana.persistence.size | string | `"50Gi"` |  |
| grafana.persistence.type | string | `"pvc"` |  |
