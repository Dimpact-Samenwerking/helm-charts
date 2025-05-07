# podiumd monitoring en logging

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
| @grafana | grafana | 8.15.0 |
| @grafana | loki | 6.29.0 |
| @grafana | promtail | 6.16.6 |
| @prometheus-community | prometheus | 27.12.0 |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| grafana."grafana.ini"."auth.anonymous".enabled | bool | `false` |  |
| grafana."grafana.ini"."auth.anonymous".hide_version | bool | `true` |  |
| grafana."grafana.ini"."auth.generic_oauth" | object | `{"allow_assign_grafana_admin":true,"allow_sign_up":true,"api_url":"https://keycloak.test.nl/realms/podiumd/protocol/openid-connect/userinfo","auth_url":"https://keycloak.test.nl/realms/podiumd/protocol/openid-connect/auth","client_id":"","client_secret":"","email_attribute_path":"email","enabled":true,"groups_attribute_path":"groups","login_attribute_path":"username","name":"Keycloak-podiumd","name_attribute_path":"name","role_attribute_path":"contains(monitoring_roles[*], 'admin') && 'Admin' || contains(monitoring_roles[*], 'editor') && 'Editor' || 'Viewer'","role_attribute_strict":true,"scopes":"openid email profile offline_access roles","skip_org_role_sync":false,"sync_ttl":60,"token_url":"https://keycloak.test.nl/realms/podiumd/protocol/openid-connect/token","use_pkce":true,"use_refresh_token":true}` | Authentication and Authorization with Keycloak |
| grafana."grafana.ini".auth.allow_sign_up | bool | `true` |  |
| grafana."grafana.ini".auth.disable_login_form | bool | `true` |  |
| grafana."grafana.ini".auth.disable_signout_menu | bool | `false` |  |
| grafana."grafana.ini".auth.oauth_auto_login | bool | `true` |  |
| grafana."grafana.ini".auth.oauth_skip_org_role_update_sync | bool | `false` |  |
| grafana."grafana.ini".metrics.enabled | bool | `false` |  |
| grafana."grafana.ini".security.content_security_policy | bool | `true` |  |
| grafana."grafana.ini".security.content_security_policy_template | string | `"script-src 'self' 'unsafe-eval' 'unsafe-inline' 'strict-dynamic' $NONCE;object-src 'none';font-src 'self';style-src 'self' 'unsafe-inline' blob:;img-src * data:;base-uri 'self';connect-src 'self' grafana.com ws://$ROOT_PATH wss://$ROOT_PATH;manifest-src 'self';media-src 'none';form-action 'self';"` |  |
| grafana."grafana.ini".security.cookie_samesite | string | `"lax"` |  |
| grafana."grafana.ini".security.cookie_secure | bool | `true` |  |
| grafana."grafana.ini".security.hide_version | bool | `true` |  |
| grafana."grafana.ini".server.domain | string | `"https://logs.test.nl/"` |  |
| grafana."grafana.ini".server.enforce_domain | bool | `true` |  |
| grafana."grafana.ini".server.root_url | string | `"https://logs.test.nl/"` |  |
| grafana.assertNoLeakedSecrets | bool | `false` |  |
| grafana.containerSecurityContext.allowPrivilegeEscalation | bool | `false` |  |
| grafana.containerSecurityContext.readOnlyRootFilesystem | bool | `false` |  |
| grafana.containerSecurityContext.runAsNonRoot | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".apiVersion | int | `1` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].allowUiUpdates | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].disableDeletion | bool | `false` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].editable | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].folder | string | `"PodiumD_Monitoring_Logging"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].name | string | `"default"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].options.path | string | `"/var/lib/grafana/dashboards/default"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].orgId | int | `1` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].type | string | `"file"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].updateIntervalSeconds | int | `30` |  |
| grafana.dashboardsConfigMaps | object | `{"default":"logging-podiumd-dashboard"}` | Dashboard opgenomen in ConfigMap |
| grafana.datasources."datasources.yaml".apiVersion | int | `1` |  |
| grafana.datasources."datasources.yaml".datasources[0].access | string | `"proxy"` |  |
| grafana.datasources."datasources.yaml".datasources[0].editable | bool | `true` |  |
| grafana.datasources."datasources.yaml".datasources[0].isDefault | bool | `false` |  |
| grafana.datasources."datasources.yaml".datasources[0].name | string | `"Prometheus"` |  |
| grafana.datasources."datasources.yaml".datasources[0].readOnly | bool | `false` |  |
| grafana.datasources."datasources.yaml".datasources[0].type | string | `"prometheus"` |  |
| grafana.datasources."datasources.yaml".datasources[0].url | string | `"http://{{ .Release.Name }}-prometheus-server"` |  |
| grafana.datasources."datasources.yaml".datasources[1].access | string | `"proxy"` |  |
| grafana.datasources."datasources.yaml".datasources[1].editable | bool | `true` |  |
| grafana.datasources."datasources.yaml".datasources[1].isDefault | bool | `true` |  |
| grafana.datasources."datasources.yaml".datasources[1].jsonData.timeout | int | `300` |  |
| grafana.datasources."datasources.yaml".datasources[1].name | string | `"loki"` |  |
| grafana.datasources."datasources.yaml".datasources[1].readOnly | bool | `false` |  |
| grafana.datasources."datasources.yaml".datasources[1].type | string | `"loki"` |  |
| grafana.datasources."datasources.yaml".datasources[1].uid | string | `"loki"` |  |
| grafana.datasources."datasources.yaml".datasources[1].url | string | `"http://{{ .Release.Name }}-loki-gateway"` |  |
| grafana.datasources."datasources.yaml".datasources[1].version | int | `1` |  |
| grafana.datasources.alertmanager.enabled | bool | `false` |  |
| grafana.deleteDatasources[0].name | string | `"Alertmanager"` |  |
| grafana.enabled | bool | `true` |  |
| grafana.image.pullPolicy | string | `"IfNotPresent"` |  |
| grafana.image.pullSecrets | list | `[]` |  |
| grafana.image.registry | string | `"docker.io"` |  |
| grafana.image.repository | string | `"grafana/grafana"` |  |
| grafana.image.sha | string | `""` |  |
| grafana.image.tag | string | `""` |  |
| grafana.persistence.accessModes[0] | string | `"ReadWriteOnce"` |  |
| grafana.persistence.enabled | bool | `true` |  |
| grafana.persistence.finalizers[0] | string | `"kubernetes.io/pvc-protection"` |  |
| grafana.persistence.size | string | `"20Gi"` |  |
| grafana.persistence.storageClassName | string | `"managed-csi"` |  |
| grafana.persistence.type | string | `"pvc"` |  |
| grafana.sidecar.datasources.alertmanager.enabled | bool | `false` |  |
| loki.backend.replicas | int | `0` |  |
| loki.chunksCache.allocatedMemory | int | `1024` |  |
| loki.chunksCache.defaultValidity | string | `"6h"` |  |
| loki.chunksCache.enabled | bool | `true` |  |
| loki.compactor.replicas | int | `1` |  |
| loki.deploymentMode | string | `"Distributed"` |  |
| loki.distributor.maxUnavailable | int | `2` |  |
| loki.distributor.replicas | int | `3` |  |
| loki.enabled | bool | `true` |  |
| loki.indexGateway.maxUnavailable | int | `1` |  |
| loki.indexGateway.replicas | int | `2` |  |
| loki.ingester.replicas | int | `3` |  |
| loki.loki.auth_enabled | bool | `false` |  |
| loki.loki.compactor.compaction_interval | string | `"10m"` |  |
| loki.loki.compactor.delete_request_store | string | `"s3"` |  |
| loki.loki.compactor.retention_delete_delay | string | `"2h"` |  |
| loki.loki.compactor.retention_delete_worker_count | int | `150` |  |
| loki.loki.compactor.retention_enabled | bool | `true` |  |
| loki.loki.frontend.max_outstanding_per_tenant | int | `6144` |  |
| loki.loki.ingester.chunk_block_size | int | `262144` |  |
| loki.loki.ingester.chunk_encoding | string | `"snappy"` |  |
| loki.loki.ingester.chunk_idle_period | string | `"30m"` |  |
| loki.loki.ingester.chunk_retain_period | string | `"1m"` |  |
| loki.loki.limits_config.allow_structured_metadata | bool | `true` |  |
| loki.loki.limits_config.ingestion_burst_size_mb | int | `20` |  |
| loki.loki.limits_config.ingestion_rate_mb | int | `10` |  |
| loki.loki.limits_config.ingestion_rate_strategy | string | `"local"` |  |
| loki.loki.limits_config.max_cache_freshness_per_query | string | `"10m"` |  |
| loki.loki.limits_config.max_global_streams_per_user | int | `5000` |  |
| loki.loki.limits_config.max_query_length | string | `"744h"` |  |
| loki.loki.limits_config.max_query_lookback | string | `"31d"` |  |
| loki.loki.limits_config.max_query_parallelism | int | `48` |  |
| loki.loki.limits_config.max_streams_per_user | int | `0` |  |
| loki.loki.limits_config.retention_period | string | `"30d"` |  |
| loki.loki.limits_config.split_queries_by_interval | string | `"15m"` |  |
| loki.loki.limits_config.volume_enabled | bool | `true` |  |
| loki.loki.pattern_ingester.enabled | bool | `true` |  |
| loki.loki.querier.max_concurrent | int | `6` |  |
| loki.loki.query_scheduler.max_outstanding_requests_per_tenant | int | `32768` |  |
| loki.loki.schemaConfig.configs[0].from | string | `"2024-04-01"` |  |
| loki.loki.schemaConfig.configs[0].index.period | string | `"24h"` |  |
| loki.loki.schemaConfig.configs[0].index.prefix | string | `"loki_index_"` |  |
| loki.loki.schemaConfig.configs[0].object_store | string | `"s3"` |  |
| loki.loki.schemaConfig.configs[0].schema | string | `"v13"` |  |
| loki.loki.schemaConfig.configs[0].store | string | `"tsdb"` |  |
| loki.loki.storage.object_store.s3.endpoint | string | `"http://{{ .Release.Name }}-minio-svc:9000"` |  |
| loki.loki.storage.object_store.s3.insecure | bool | `true` |  |
| loki.loki.storage.object_store.type | string | `"s3"` |  |
| loki.loki.storage.s3.endpoint | string | `"http://{{ .Release.Name }}-minio-svc:9000"` |  |
| loki.loki.storage.s3.insecure | bool | `true` |  |
| loki.loki.storage.s3.s3forcepathstyle | bool | `true` |  |
| loki.loki.tracing.enabled | bool | `true` |  |
| loki.lokiCanary.enabled | bool | `false` |  |
| loki.minio.enabled | bool | `true` |  |
| loki.minio.persistence.size | string | `"20Gi"` |  |
| loki.minio.persistence.storageClass | string | `"managed-csi"` |  |
| loki.monitoring.dashboards.enabled | bool | `false` |  |
| loki.monitoring.rules.enabled | bool | `false` |  |
| loki.monitoring.selfMonitoring.enabled | bool | `false` |  |
| loki.monitoring.selfMonitoring.grafanaAgent.installOperator | bool | `false` |  |
| loki.querier.maxUnavailable | int | `2` |  |
| loki.querier.replicas | int | `3` |  |
| loki.queryFrontend.maxUnavailable | int | `1` |  |
| loki.queryFrontend.replicas | int | `2` |  |
| loki.queryScheduler.replicas | int | `2` |  |
| loki.read.replicas | int | `0` |  |
| loki.resultsCache.defaultValidity | string | `"6h"` |  |
| loki.resultsCache.enabled | bool | `true` |  |
| loki.test.enabled | bool | `false` |  |
| loki.write.replicas | int | `0` |  |
| prometheus.alertmanager.enabled | bool | `false` |  |
| prometheus.enabled | bool | `true` |  |
| prometheus.prometheusSpec.logLevel | string | `"warn"` |  |
| prometheus.prometheusSpec.retention | string | `"7d"` |  |
| prometheus.prometheusSpec.retentionSize | string | `""` |  |
| prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues | bool | `false` |  |
| prometheus.server.image.digest | string | `""` |  |
| prometheus.server.image.pullPolicy | string | `"IfNotPresent"` |  |
| prometheus.server.image.repository | string | `"quay.io/prometheus/prometheus"` |  |
| prometheus.server.image.tag | string | `""` |  |
| prometheus.server.persistentVolume.accessModes[0] | string | `"ReadWriteOnce"` |  |
| prometheus.server.persistentVolume.enabled | bool | `true` |  |
| prometheus.server.persistentVolume.size | string | `"20Gi"` |  |
| prometheus.server.persistentVolume.storageClass | string | `"managed-csi"` |  |
| promtail.config.clients[0].tenant_id | int | `1` |  |
| promtail.config.clients[0].url | string | `"http://{{ .Release.Name }}-loki-gateway/loki/api/v1/push"` |  |
| promtail.config.logLevel | string | `"warn"` |  |
| promtail.enabled | bool | `true` |  |
| promtail.image.pullPolicy | string | `"IfNotPresent"` |  |
| promtail.image.registry | string | `"docker.io"` |  |
| promtail.image.repository | string | `"grafana/promtail"` |  |
| promtail.image.tag | string | `""` |  |
| promtail.resources.limits.cpu | string | `"100m"` |  |
| promtail.resources.limits.memory | string | `"256Mi"` |  |
| promtail.resources.requests.cpu | string | `"50m"` |  |
| promtail.resources.requests.memory | string | `"96Mi"` |  |
