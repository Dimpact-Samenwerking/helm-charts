# monitoring en logging

![Version: 0.1.0-dev](https://img.shields.io/badge/Version-0.1.0--dev-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 1.0-dev](https://img.shields.io/badge/AppVersion-1.0--dev-informational?style=flat-square)

A monitoring stack using Loki, Prometheus, Promtail and Grafana

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| @grafana | grafana | 8.10.1 |
| @grafana | loki | 6.27.0 |
| @grafana | promtail | 6.16.6 |
| @prometheus-community | prometheus | 70.3.0 |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| "grafana.ini"."auth.azuread".allow_assign_grafana_admin | bool | `true` |  |
| "grafana.ini"."auth.azuread".allow_sign_up | bool | `true` |  |
| "grafana.ini"."auth.azuread".allowed_domains | list | `[]` |  |
| "grafana.ini"."auth.azuread".allowed_groups | list | `[]` |  |
| "grafana.ini"."auth.azuread".allowed_organizations | string | `"996a05f9-6875-4960-a833-6e3aff171400"` |  |
| "grafana.ini"."auth.azuread".auth_url | string | `"https://login.microsoftonline.com/996a05f9-6875-4960-a833-6e3aff171400/oauth2/v2.0/authorize"` |  |
| "grafana.ini"."auth.azuread".auto_login | bool | `true` |  |
| "grafana.ini"."auth.azuread".client_id | string | `"REP_GRAFANA_ID_REP"` |  |
| "grafana.ini"."auth.azuread".client_secret | string | `"$__env{gf-client-secret}"` |  |
| "grafana.ini"."auth.azuread".enabled | bool | `true` |  |
| "grafana.ini"."auth.azuread".name | string | `"Azure AD"` |  |
| "grafana.ini"."auth.azuread".role_attribute_strict | bool | `false` |  |
| "grafana.ini"."auth.azuread".scopes | string | `"openid email profile"` |  |
| "grafana.ini"."auth.azuread".skip_org_role_sync | bool | `false` |  |
| "grafana.ini"."auth.azuread".token_url | string | `"https://login.microsoftonline.com/996a05f9-6875-4960-a833-6e3aff171400/oauth2/v2.0/token"` |  |
| "grafana.ini"."auth.azuread".use_pkce | bool | `true` |  |
| "grafana.ini"."auth.basic".allow_sign_up | bool | `false` |  |
| "grafana.ini"."auth.basic".disable_login_form | bool | `true` |  |
| "grafana.ini"."auth.basic".enabled | bool | `false` |  |
| "grafana.ini".dashboards.default_home_dashboard_path | string | `"/var/lib/grafana/dashboards/default/loki-dashboard.json"` |  |
| "grafana.ini".database.host | string | `"psql-REP_ENVIRONMENT_REP-REP_GEMEENTE_REP.postgres.database.azure.com:5432"` |  |
| "grafana.ini".database.name | string | `"grafana"` |  |
| "grafana.ini".database.password | string | `"$__env{gf-database-password}"` |  |
| "grafana.ini".database.ssl_mode | string | `"require"` |  |
| "grafana.ini".database.type | string | `"postgres"` |  |
| "grafana.ini".database.user | string | `"grafana"` |  |
| "grafana.ini".dataproxy.keep_alive_seconds | int | `300` |  |
| "grafana.ini".dataproxy.timeout | int | `300` |  |
| "grafana.ini".metrics.enabled | bool | `false` |  |
| "grafana.ini".server.root_url | string | `"https://REP_DOMAIN_REP"` |  |
| "grafana.ini".smtp.enabled | bool | `true` |  |
| "grafana.ini".smtp.from_address | string | `"noreply@REP_GRAFANA_DOMAIN_REP"` |  |
| "grafana.ini".smtp.host | string | `"mail.enschede.nl:587"` |  |
| "grafana.ini".smtp.skip_verify | bool | `true` |  |
| additionalDataSources[0].access | string | `"proxy"` |  |
| additionalDataSources[0].editable | bool | `true` |  |
| additionalDataSources[0].isDefault | bool | `true` |  |
| additionalDataSources[0].jsonData.timeout | int | `300` |  |
| additionalDataSources[0].name | string | `"Loki"` |  |
| additionalDataSources[0].readOnly | bool | `false` |  |
| additionalDataSources[0].type | string | `"loki"` |  |
| additionalDataSources[0].uid | string | `"loki"` |  |
| additionalDataSources[0].url | string | `"http://{{ .Release.Name }}-gateway"` |  |
| additionalDataSources[0].version | int | `1` |  |
| adminPassword | string | `"KV_GRAFANA_ADMIN_KV"` |  |
| alertmanager.enabled | bool | `false` |  |
| backend | object | `{"replicas":0}` | Zero out replica counts of other deployment modes |
| bloomBuilder.replicas | int | `0` |  |
| bloomGateway.replicas | int | `0` |  |
| bloomPlanner | object | `{"replicas":0}` | Optional experimental components |
| chunksCache.allocatedMemory | int | `1024` |  |
| chunksCache.defaultValidity | string | `"6h"` |  |
| chunksCache.enabled | bool | `true` |  |
| compactor.replicas | int | `1` |  |
| containerSecurityContext.allowPrivilegeEscalation | bool | `false` |  |
| containerSecurityContext.readOnlyRootFilesystem | bool | `true` |  |
| containerSecurityContext.runAsNonRoot | bool | `true` |  |
| dashboardProviders."dashboardproviders.yaml".apiVersion | int | `1` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].disableDeletion | bool | `false` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].editable | bool | `true` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].folder | string | `"PodiumD_Monitoring_Logging"` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].name | string | `"default"` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].options.path | string | `"/var/lib/grafana/dashboards/default"` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].orgId | int | `1` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].type | string | `"file"` |  |
| dashboards.default.Logging-PodiumD.datasource | string | `"Loki"` |  |
| dashboards.default.Logging-PodiumD.token | string | `""` |  |
| dashboards.default.Logging-PodiumD.url | string | `"https://raw.githubusercontent.com/Dimpact-Samenwerking/helm-charts/refs/heads/feature/IN-72_monitoring-logging/charts/monitoring-logging/grafana/dashboards/logging_PodiumD.json"` |  |
| dashboardsConfigMaps.default | string | `"loki-dashboard"` |  |
| datasources."datasources.yaml".apiVersion | int | `1` |  |
| datasources."datasources.yaml".datasources[0].access | string | `"proxy"` |  |
| datasources."datasources.yaml".datasources[0].editable | bool | `true` |  |
| datasources."datasources.yaml".datasources[0].isDefault | bool | `false` |  |
| datasources."datasources.yaml".datasources[0].name | string | `"Prometheus"` |  |
| datasources."datasources.yaml".datasources[0].readOnly | bool | `false` |  |
| datasources."datasources.yaml".datasources[0].type | string | `"prometheus"` |  |
| datasources."datasources.yaml".datasources[0].url | string | `"http://{{ .Release.Name }}-prometheus:9090"` |  |
| datasources."datasources.yaml".deleteDatasources[0].name | string | `"Alertmanager"` |  |
| datasources.alertmanager.enabled | bool | `false` |  |
| deploymentMode | string | `"Distributed"` |  |
| distributor.maxUnavailable | int | `2` |  |
| distributor.replicas | int | `3` |  |
| downloadDashboardsImage.registry. | string | `nil` |  |
| downloadDashboardsImage.repository | string | `"curl"` |  |
| downloadDashboardsImage.tag | string | `"7.85.0"` |  |
| envFromSecrets[0].name | string | `"gf-database-password"` |  |
| envFromSecrets[1].name | string | `"gf-client-secret"` |  |
| gateway.basicAuth.enabled | bool | `true` |  |
| gateway.basicAuth.existingSecret | string | `"loki-basic-auth"` |  |
| gateway.enabled | bool | `true` |  |
| gateway.image.registry. | string | `nil` |  |
| gateway.image.repository | string | `"nginx"` |  |
| gateway.image.tag | string | `"stable"` |  |
| gateway.nodeSelector."kubernetes.azure.com/mode" | string | `"system"` |  |
| gateway.resources.limits.cpu | string | `"50m"` |  |
| gateway.resources.limits.memory | string | `"32Mi"` |  |
| gateway.resources.requests.cpu | string | `"10m"` |  |
| gateway.resources.requests.memory | string | `"16Mi"` |  |
| global.imageRegistry | string | `"REP_ACR_NAME_REP.azurecr.io"` |  |
| grafana.enabled | bool | `true` |  |
| grafana.image.registry. | string | `nil` |  |
| grafana.image.repository | string | `"grafana"` |  |
| grafana.image.tag | string | `"11.5.2"` |  |
| indexGateway.maxUnavailable | int | `1` |  |
| indexGateway.replicas | int | `2` |  |
| ingester.replicas | int | `3` |  |
| initChownData.image.registry. | string | `nil` |  |
| initChownData.image.repository | string | `"grafana-init-chown-data"` |  |
| initChownData.image.tag | string | `"1.31.1"` |  |
| loki.auth_enabled | bool | `false` |  |
| loki.compactor.compaction_interval | string | `"10m"` |  |
| loki.compactor.delete_request_store | string | `"azure"` |  |
| loki.compactor.retention_delete_delay | string | `"2h"` |  |
| loki.compactor.retention_delete_worker_count | int | `150` |  |
| loki.compactor.retention_enabled | bool | `true` |  |
| loki.compactor.working_directory | string | `"/etc/loki/"` |  |
| loki.enabled | bool | `true` |  |
| loki.frontend.max_outstanding_per_tenant | int | `6144` |  |
| loki.image.registry. | string | `nil` |  |
| loki.image.repository | string | `"loki"` |  |
| loki.image.tag | string | `"3.4.2"` |  |
| loki.ingester.chunk_encoding | string | `"snappy"` |  |
| loki.ingester.chunk_idle_period | string | `"30m"` |  |
| loki.limits_config | object | `{"allow_structured_metadata":true,"ingestion_rate_strategy":"local","max_cache_freshness_per_query":"10m","max_global_streams_per_user":10000,"max_query_length":"744h","max_query_lookback":"744h","max_query_parallelism":48,"max_streams_per_user":0,"retention_period":"744h","split_queries_by_interval":"15m","volume_enabled":true}` | Query Performance   |
| loki.pattern_ingester.enabled | bool | `true` |  |
| loki.podLabels."azure.workload.identity/use" | string | `"true"` |  |
| loki.querier.max_concurrent | int | `16` |  |
| loki.queryFrontend.log_queries_longer_than | string | `"15s"` |  |
| loki.queryFrontend.max_body_size | string | `"20MB"` |  |
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
| loki.storage.azure.accountName | string | `"<INSERT-STORAGE-ACCOUNT-NAME>"` |  |
| loki.storage.azure.useFederatedToken | bool | `true` |  |
| loki.storage.bucketNames.chunks | string | `"<CHUNK-CONTAINER-NAME>"` |  |
| loki.storage.bucketNames.ruler | string | `"<RULER-CONTAINER-NAME>"` |  |
| loki.storage.type | string | `"azure"` |  |
| loki.storage_config.azure.account_name | string | `"<INSERT-STORAGE-ACCOUNT-NAME>"` |  |
| loki.storage_config.azure.container_name | string | `"<CHUNK-CONTAINER-NAME>"` |  |
| loki.storage_config.azure.use_federated_token | bool | `true` |  |
| loki.tracing.enabled | bool | `false` |  |
| lokiCanary.enabled | bool | `false` |  |
| minio.enabled | bool | `false` |  |
| monitoring.dashboards.enabled | bool | `false` |  |
| monitoring.rules.enabled | bool | `false` |  |
| monitoring.selfMonitoring.enabled | bool | `false` |  |
| monitoring.selfMonitoring.grafanaAgent.installOperator | bool | `false` |  |
| nodeSelector."kubernetes.azure.com/mode" | string | `"system"` |  |
| persistence.accessModes[0] | string | `"ReadWriteOnce"` |  |
| persistence.enabled | bool | `true` |  |
| persistence.finalizers[0] | string | `"kubernetes.io/pvc-protection"` |  |
| persistence.size | string | `"20Gi"` |  |
| persistence.storageClassName | string | `"default"` |  |
| persistence.type | string | `"pvc"` |  |
| prometheus.enabled | bool | `true` |  |
| prometheus.prometheusSpec.logLevel | string | `"debug"` |  |
| prometheus.prometheusSpec.retention | string | `"72h"` |  |
| prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues | bool | `false` |  |
| prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.accessModes[0] | string | `"ReadWriteOnce"` |  |
| prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage | string | `"50Gi"` |  |
| promtail.config.clients | list | `[{"tenant_id":1,"url":"http://{{ .Release.Name }}-gateway/loki/api/v1/push"}]` | publish data to loki |
| promtail.config.logLevel | string | `"warn"` |  |
| promtail.enabled | bool | `true` |  |
| promtail.image.registry. | string | `nil` |  |
| promtail.image.repository | string | `"promtail"` |  |
| promtail.image.tag | string | `"3.0.0"` |  |
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
| ruler.maxUnavailable | int | `1` |  |
| ruler.replicas | int | `1` |  |
| serviceAccount.annotations."azure.workload.identity/client-id" | string | `"<APP-ID>"` |  |
| serviceAccount.labels."azure.workload.identity/use" | string | `"true"` |  |
| serviceAccount.name | string | `"loki"` |  |
| sidecar.dashboards.skipReload | bool | `true` |  |
| sidecar.image.registry. | string | `nil` |  |
| sidecar.image.repository | string | `"grafana-sidecar"` |  |
| sidecar.image.tag | string | `"1.26.1"` |  |
| singleBinary.replicas | int | `0` |  |
| test.enabled | bool | `false` |  |
| write.replicas | int | `0` |  |
