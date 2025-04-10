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
| gateway.basicAuth.enabled | bool | `true` |  |
| gateway.basicAuth.existingSecret | string | `"loki-basic-auth"` |  |
| gateway.service.type | string | `"LoadBalancer"` |  |
| indexGateway.maxUnavailable | int | `1` |  |
| indexGateway.replicas | int | `2` |  |
| ingester.replicas | int | `3` |  |
| loki.auth_enabled | bool | `false` |  |
| loki.compactor.compaction_interval | string | `"10m"` |  |
| loki.compactor.delete_request_store | string | `"azure"` |  |
| loki.compactor.retention_delete_delay | string | `"2h"` |  |
| loki.compactor.retention_delete_worker_count | int | `150` |  |
| loki.compactor.retention_enabled | bool | `true` |  |
| loki.compactor.working_directory | string | `"/data/retention"` |  |
| loki.frontend.max_outstanding_per_tenant | int | `6144` |  |
| loki.image.registry | string | `""` |  |
| loki.image.repository | string | `"loki"` |  |
| loki.image.tag | string | `""` |  |
| loki.ingester.chunk_block_size | int | `262144` |  |
| loki.ingester.chunk_encoding | string | `"snappy"` |  |
| loki.ingester.chunk_idle_period | string | `"30m"` |  |
| loki.ingester.chunk_retain_period | string | `"1m"` |  |
| loki.limits_config | object | `{"allow_structured_metadata":true,"ingestion_burst_size_mb":20,"ingestion_rate_mb":10,"ingestion_rate_strategy":"local","max_cache_freshness_per_query":"10m","max_global_streams_per_user":10000,"max_query_length":"744h","max_query_lookback":"744h","max_query_parallelism":48,"max_streams_per_user":0,"retention_period":"744h","split_queries_by_interval":"15m","volume_enabled":true}` | Query Performance   |
| loki.pattern_ingester.enabled | bool | `true` |  |
| loki.podLabels."azure.workload.identity/use" | string | `"true"` |  |
| loki.querier.max_concurrent | int | `6` |  |
| loki.query_scheduler.max_outstanding_requests_per_tenant | int | `32768` |  |
| loki.ruler.enable_api | bool | `true` |  |
| loki.ruler.storage.azure.account_name | string | `"<INSERT-STORAGE-ACCOUNT-NAME>"` |  |
| loki.ruler.storage.azure.container_name | string | `"<RULER-CONTAINER-NAME>"` |  |
| loki.ruler.storage.azure.use_federated_token | bool | `true` |  |
| loki.ruler.storage.type | string | `"azure"` |  |
| loki.schemaConfig.configs[0].from | string | `"2024-04-01"` |  |
| loki.schemaConfig.configs[0].index.period | string | `"24h"` |  |
| loki.schemaConfig.configs[0].index.prefix | string | `"loki_index_"` |  |
| loki.schemaConfig.configs[0].object_store | string | `"azure"` |  |
| loki.schemaConfig.configs[0].schema | string | `"v13"` |  |
| loki.schemaConfig.configs[0].store | string | `"tsdb"` |  |
| loki.storage.azure.accountName | string | `""` |  |
| loki.storage.azure.useFederatedToken | bool | `true` |  |
| loki.storage.bucketNames.chunks | string | `""` |  |
| loki.storage.bucketNames.ruler | string | `""` |  |
| loki.storage.type | string | `"azure"` |  |
| loki.storage_config.azure.account_name | string | `""` |  |
| loki.storage_config.azure.container_name | string | `""` |  |
| loki.storage_config.azure.use_federated_token | bool | `true` |  |
| loki.tracing.enabled | bool | `false` |  |
| lokiCanary.enabled | bool | `false` |  |
| minio.enabled | bool | `false` |  |
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
| resultsCache.defaultValidity | string | `"6h"` |  |
| resultsCache.enabled | bool | `true` |  |
| ruler.maxUnavailable | int | `1` |  |
| ruler.replicas | int | `1` |  |
| serviceAccount.annotations."azure.workload.identity/client-id" | string | `"<APP-ID>"` |  |
| serviceAccount.labels."azure.workload.identity/use" | string | `"true"` |  |
| serviceAccount.name | string | `"loki"` |  |
| sidecar.dashboards.skipReload | bool | `true` |  |
| sidecar.image.registry | string | `""` |  |
| sidecar.image.repository | string | `""` |  |
| sidecar.image.tag | string | `""` |  |
| singleBinary.replicas | int | `0` |  |
| test.enabled | bool | `false` |  |
| write.replicas | int | `0` |  |
