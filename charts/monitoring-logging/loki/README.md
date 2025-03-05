# loki

![Version: 6.27.0](https://img.shields.io/badge/Version-6.27.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 3.4.2](https://img.shields.io/badge/AppVersion-3.4.2-informational?style=flat-square)

Helm chart for Grafana Loki and Grafana Enterprise Logs supporting both simple, scalable and distributed modes.

**Homepage:** <https://grafana.github.io/helm-charts>

## Source Code

* <https://github.com/grafana/loki>
* <https://grafana.com/oss/loki/>
* <https://grafana.com/docs/loki/latest/>

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| backend.replicas | int | `0` |  |
| bloomBuilder.replicas | int | `0` |  |
| bloomGateway.replicas | int | `0` |  |
| bloomPlanner.replicas | int | `0` |  |
| chunksCache.enabled | bool | `false` |  |
| compactor.replicas | int | `1` |  |
| deploymentMode | string | `"Distributed"` |  |
| distributor.maxUnavailable | int | `2` |  |
| distributor.replicas | int | `3` |  |
| gateway.enabled | bool | `true` |  |
| gateway.image.registry | string | `"REP_ACR_NAME_REP.azurecr.io"` |  |
| gateway.image.repository | string | `"nginx"` |  |
| gateway.image.tag | string | `"stable"` |  |
| gateway.nodeSelector."kubernetes.azure.com/mode" | string | `"system"` |  |
| gateway.resources.limits.cpu | string | `"50m"` |  |
| gateway.resources.limits.memory | string | `"32Mi"` |  |
| gateway.resources.requests.cpu | string | `"10m"` |  |
| gateway.resources.requests.memory | string | `"16Mi"` |  |
| indexGateway.maxUnavailable | int | `1` |  |
| indexGateway.replicas | int | `2` |  |
| ingester.replicas | int | `3` |  |
| loki.auth_enabled | bool | `false` |  |
| loki.image.registry | string | `"REP_ACR_NAME_REP.azurecr.io"` |  |
| loki.image.repository | string | `"loki"` |  |
| loki.image.tag | string | `"3.1.0"` |  |
| loki.schemaConfig.configs[0].from | string | `"2024-04-01"` |  |
| loki.schemaConfig.configs[0].index.period | string | `"24h"` |  |
| loki.schemaConfig.configs[0].index.prefix | string | `"index_"` |  |
| loki.schemaConfig.configs[0].object_store | string | `"azure"` |  |
| loki.schemaConfig.configs[0].schema | string | `"v13"` |  |
| loki.schemaConfig.configs[0].store | string | `"tsdb"` |  |
| loki.storage.azure.accountKey | string | `"REP_STORAGE_ACCOUNT_KEY_REP"` |  |
| loki.storage.azure.accountName | string | `"REP_STORAGE_ACCOUNT_REP"` |  |
| loki.storage.azure.container | string | `"logs"` |  |
| loki.storage.azure.request_timeout | int | `0` |  |
| loki.storage.bucketNames.chunks | string | `"chunks"` |  |
| loki.storage.bucketNames.ruler | string | `"ruler"` |  |
| loki.storage.type | string | `"azure"` |  |
| lokiCanary.enabled | bool | `false` |  |
| monitoring.dashboards.enabled | bool | `false` |  |
| monitoring.rules.enabled | bool | `false` |  |
| monitoring.selfMonitoring.enabled | bool | `false` |  |
| monitoring.selfMonitoring.grafanaAgent.installOperator | bool | `false` |  |
| querier.maxUnavailable | int | `2` |  |
| querier.replicas | int | `3` |  |
| queryFrontend.maxUnavailable | int | `1` |  |
| queryFrontend.replicas | int | `2` |  |
| queryScheduler.replicas | int | `2` |  |
| read.replicas | int | `0` |  |
| resultsCache.enabled | bool | `false` |  |
| sidecar.dashboards.skipReload | bool | `true` |  |
| sidecar.image.registry | string | `"REP_ACR_NAME_REP.azurecr.io"` |  |
| sidecar.image.repository | string | `"REP_ACR_NAME_REP.azurecr.io/grafana-sidecar"` |  |
| sidecar.image.tag | string | `"1.26.1"` |  |
| singleBinary.replicas | int | `0` |  |
| table_manager.retention_deletes_enabled | bool | `true` |  |
| table_manager.retention_period | string | `"90d"` |  |
| test.enabled | bool | `false` |  |
| write.replicas | int | `0` |  |