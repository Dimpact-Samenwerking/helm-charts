# monitoring en logging

![Version: 0.1.0-dev](https://img.shields.io/badge/Version-0.1.0--dev-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 1.0-dev](https://img.shields.io/badge/AppVersion-1.0--dev-informational?style=flat-square)

A monitoring stack using Loki, Prometheus, Promtail and Grafana

## Rollenbeheer in Grafana op basis van Keycloak-groepen:

https://dimpact.atlassian.net/wiki/spaces/PCP/pages/392855594/Handleiding+rollen+toekennen+in+Grafana+via+Keycloak

## Add Used chart repositories:

helm repo add grafana https://grafana.github.io/helm-charts
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| @grafana | grafana | 8.11.3 |
| @grafana | loki | 6.28.0 |
| @grafana | promtail | 6.16.6 |
| @prometheus-community | prometheus | 27.8.0 |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend | object | `{"replicas":0}` | Zero out replica counts of other deployment modes |
| bloomBuilder.replicas | int | `0` |  |
| bloomGateway.replicas | int | `0` |  |
| bloomPlanner | object | `{"replicas":0}` | Optional experimental components |
| chunksCache.allocatedMemory | int | `1024` |  |
| chunksCache.defaultValidity | string | `"6h"` |  |
| chunksCache.enabled | bool | `true` |  |
| compactor.replicas | int | `2` |  |
| deploymentMode | string | `"Distributed"` |  |
| distributor.maxUnavailable | int | `2` |  |
| distributor.replicas | int | `3` |  |
| grafana.additionalDataSources[0].access | string | `"proxy"` |  |
| grafana.additionalDataSources[0].editable | bool | `true` |  |
| grafana.additionalDataSources[0].isDefault | bool | `true` |  |
| grafana.additionalDataSources[0].jsonData.timeout | int | `300` |  |
| grafana.additionalDataSources[0].name | string | `"Loki"` |  |
| grafana.additionalDataSources[0].readOnly | bool | `false` |  |
| grafana.additionalDataSources[0].type | string | `"loki"` |  |
| grafana.additionalDataSources[0].uid | string | `"loki"` |  |
| grafana.additionalDataSources[0].url | string | `"http://loki-gateway"` |  |
| grafana.additionalDataSources[0].version | int | `1` |  |
| grafana.assertNoLeakedSecrets | bool | `false` |  |
| grafana.containerSecurityContext.allowPrivilegeEscalation | bool | `false` |  |
| grafana.containerSecurityContext.readOnlyRootFilesystem | bool | `true` |  |
| grafana.containerSecurityContext.runAsNonRoot | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".apiVersion | int | `1` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].disableDeletion | bool | `false` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].editable | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].folder | string | `"PodiumD_Monitoring_Logging"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].name | string | `"default"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].options.path | string | `"/var/lib/grafana/dashboards/default"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].orgId | int | `1` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].type | string | `"file"` |  |
| grafana.dashboardsConfigMaps.default | string | `"logging-podiumd-dashboard"` |  |
| grafana.datasources."datasources.yaml".apiVersion | int | `1` |  |
| grafana.datasources."datasources.yaml".datasources[0].access | string | `"proxy"` |  |
| grafana.datasources."datasources.yaml".datasources[0].editable | bool | `true` |  |
| grafana.datasources."datasources.yaml".datasources[0].isDefault | bool | `false` |  |
| grafana.datasources."datasources.yaml".datasources[0].name | string | `"prometheus"` |  |
| grafana.datasources."datasources.yaml".datasources[0].readOnly | bool | `false` |  |
| grafana.datasources."datasources.yaml".datasources[0].type | string | `"Prometheus"` |  |
| grafana.datasources."datasources.yaml".datasources[0].url | string | `"http://{{ .Release.Name }}-prometheus-server"` |  |
| grafana.datasources.alertmanager.enabled | bool | `false` |  |
| grafana.deleteDatasources[0].name | string | `"Alertmanager"` |  |
| grafana.enabled | bool | `true` |  |
| grafana.nodeSelector."kubernetes.azure.com/mode" | string | `"system"` |  |
| grafana.persistence.accessModes[0] | string | `"ReadWriteOnce"` |  |
| grafana.persistence.enabled | bool | `true` |  |
| grafana.persistence.finalizers[0] | string | `"kubernetes.io/pvc-protection"` |  |
| grafana.persistence.size | string | `"20Gi"` |  |
| grafana.persistence.storageClassName | string | `""` |  |
| grafana.persistence.type | string | `"pvc"` |  |
| grafana.sidecar.datasources.alertmanager.enabled | bool | `false` |  |
| indexGateway.maxUnavailable | int | `1` |  |
| indexGateway.replicas | int | `2` |  |
| ingester.replicas | int | `3` |  |
| loki.auth_enabled | bool | `false` |  |
| loki.compactor.compaction_interval | string | `"10m"` |  |
| loki.compactor.delete_request_store | string | `"s3"` |  |
| loki.compactor.retention_delete_delay | string | `"2h"` |  |
| loki.compactor.retention_delete_worker_count | int | `150` |  |
| loki.compactor.retention_enabled | bool | `true` |  |
| loki.compactor.working_directory | string | `"/tmp/loki/retention"` |  |
| loki.enabled | bool | `true` |  |
| loki.frontend.max_outstanding_per_tenant | int | `6144` |  |
| loki.ingester.chunk_block_size | int | `262144` |  |
| loki.ingester.chunk_encoding | string | `"snappy"` |  |
| loki.ingester.chunk_idle_period | string | `"30m"` |  |
| loki.ingester.chunk_retain_period | string | `"1m"` |  |
| loki.limits_config | object | `{"allow_structured_metadata":true,"ingestion_burst_size_mb":20,"ingestion_rate_mb":10,"ingestion_rate_strategy":"local","max_cache_freshness_per_query":"10m","max_global_streams_per_user":5000,"max_query_length":"744h","max_query_lookback":"90d","max_query_parallelism":48,"max_streams_per_user":0,"retention_period":"90d","split_queries_by_interval":"15m","volume_enabled":true}` | Query Performance   |
| loki.pattern_ingester.enabled | bool | `true` |  |
| loki.querier.max_concurrent | int | `6` |  |
| loki.query_scheduler.max_outstanding_requests_per_tenant | int | `32768` |  |
| loki.schemaConfig.configs[0].from | string | `"2024-04-01"` |  |
| loki.schemaConfig.configs[0].index.period | string | `"24h"` |  |
| loki.schemaConfig.configs[0].index.prefix | string | `"loki_index_"` |  |
| loki.schemaConfig.configs[0].object_store | string | `"s3"` |  |
| loki.schemaConfig.configs[0].schema | string | `"v13"` |  |
| loki.schemaConfig.configs[0].store | string | `"tsdb"` |  |
| loki.tracing.enabled | bool | `false` |  |
| lokiCanary.enabled | bool | `false` |  |
| minio.enabled | bool | `true` |  |
| monitoring.dashboards.enabled | bool | `false` |  |
| monitoring.rules.enabled | bool | `false` |  |
| monitoring.selfMonitoring.enabled | bool | `false` |  |
| monitoring.selfMonitoring.grafanaAgent.installOperator | bool | `false` |  |
| prometheus.alertmanager.enabled | bool | `false` |  |
| prometheus.enabled | bool | `true` |  |
| prometheus.prometheusSpec.logLevel | string | `"warn"` |  |
| prometheus.prometheusSpec.retention | string | `"7d"` |  |
| prometheus.prometheusSpec.retentionSize | string | `""` |  |
| prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues | bool | `false` |  |
| prometheus.server.persistentVolume.accessModes[0] | string | `"ReadWriteOnce"` |  |
| prometheus.server.persistentVolume.enabled | bool | `true` |  |
| prometheus.server.persistentVolume.size | string | `"20Gi"` |  |
| prometheus.server.persistentVolume.storageClassName | string | `""` |  |
| promtail.config.clients[0].tenant_id | int | `1` |  |
| promtail.config.clients[0].url | string | `"http://loki-gateway/loki/api/v1/push"` |  |
| promtail.config.logLevel | string | `"warn"` |  |
| promtail.enabled | bool | `true` |  |
| promtail.resources.limits.cpu | string | `"100m"` |  |
| promtail.resources.limits.memory | string | `"256Mi"` |  |
| promtail.resources.requests.cpu | string | `"50m"` |  |
| promtail.resources.requests.memory | string | `"96Mi"` |  |
| querier.maxUnavailable | int | `2` |  |
| querier.replicas | int | `3` |  |
| queryFrontend.maxUnavailable | int | `1` |  |
| queryFrontend.replicas | int | `2` |  |
| queryScheduler.replicas | int | `2` |  |
| read.replicas | int | `0` |  |
| resultsCache.defaultValidity | string | `"6h"` |  |
| resultsCache.enabled | bool | `true` |  |
| singleBinary.replicas | int | `0` |  |
| test.enabled | bool | `false` |  |
| write.replicas | int | `0` |  |
