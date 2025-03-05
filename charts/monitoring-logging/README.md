# Monitoring-Logging PodiumD

![Version: 0.1.0](https://img.shields.io/badge/Version-0.1.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 1.0](https://img.shields.io/badge/AppVersion-1.0-informational?style=flat-square)

A monitoring stack using Loki, Promtail and Grafana

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| https://grafana.github.io/helm-charts | loki  | 6.27.0 |
| https://grafana.github.io/helm-charts | grafana | 8.10.1 |
| https://grafana.github.io/helm-charts | promtail | 6.16.6 |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| chunksCache.enabled | bool | `false` |  |
| gateway.enabled | bool | `true` |  |
| gateway.image.registry | string | `"REP_ACR_NAME_REP.azurecr.io"` |  |
| gateway.image.repository | string | `"nginx"` |  |
| gateway.image.tag | string | `"stable"` |  |
| gateway.nodeSelector."kubernetes.azure.com/mode" | string | `"system"` |  |
| gateway.resources.limits.cpu | string | `"50m"` |  |
| gateway.resources.limits.memory | string | `"32Mi"` |  |
| gateway.resources.requests.cpu | string | `"10m"` |  |
| gateway.resources.requests.memory | string | `"16Mi"` |  |
| grafana."grafana.ini"."auth.azuread".allow_assign_grafana_admin | bool | `true` |  |
| grafana."grafana.ini"."auth.azuread".allow_sign_up | bool | `true` |  |
| grafana."grafana.ini"."auth.azuread".allowed_domains | string | `nil` |  |
| grafana."grafana.ini"."auth.azuread".allowed_groups | string | `nil` |  |
| grafana."grafana.ini"."auth.azuread".allowed_organizations | string | `"996a05f9-6875-4960-a833-6e3aff171400"` |  |
| grafana."grafana.ini"."auth.azuread".auth_url | string | `"https://login.microsoftonline.com/996a05f9-6875-4960-a833-6e3aff171400/oauth2/v2.0/authorize"` |  |
| grafana."grafana.ini"."auth.azuread".auto_login | bool | `true` |  |
| grafana."grafana.ini"."auth.azuread".client_id | string | `"REP_GRAFANA_ID_REP"` |  |
| grafana."grafana.ini"."auth.azuread".client_secret | string | `"$__env{gf-client-secret}"` |  |
| grafana."grafana.ini"."auth.azuread".enabled | bool | `true` |  |
| grafana."grafana.ini"."auth.azuread".name | string | `"Azure AD"` |  |
| grafana."grafana.ini"."auth.azuread".role_attribute_strict | bool | `false` |  |
| grafana."grafana.ini"."auth.azuread".scopes | string | `"openid email profile"` |  |
| grafana."grafana.ini"."auth.azuread".skip_org_role_sync | bool | `false` |  |
| grafana."grafana.ini"."auth.azuread".token_url | string | `"https://login.microsoftonline.com/996a05f9-6875-4960-a833-6e3aff171400/oauth2/v2.0/token"` |  |
| grafana."grafana.ini"."auth.azuread".use_pkce | bool | `true` |  |
| grafana."grafana.ini"."auth.basic".allow_sign_up | bool | `false` |  |
| grafana."grafana.ini"."auth.basic".disable_login_form | bool | `true` |  |
| grafana."grafana.ini"."auth.basic".enabled | bool | `false` |  |
| grafana."grafana.ini".dashboards.default_home_dashboard_path | string | `"/var/lib/grafana/dashboards/default/loki-dashboard.json"` |  |
| grafana."grafana.ini".database.host | string | `"psql-REP_ENVIRONMENT_REP-REP_GEMEENTE_REP.postgres.database.azure.com:5432"` |  |
| grafana."grafana.ini".database.name | string | `"grafana"` |  |
| grafana."grafana.ini".database.password | string | `"$__env{gf-database-password}"` |  |
| grafana."grafana.ini".database.ssl_mode | string | `"require"` |  |
| grafana."grafana.ini".database.type | string | `"postgres"` |  |
| grafana."grafana.ini".database.user | string | `"grafana"` |  |
| grafana."grafana.ini".dataproxy.keep_alive_seconds | int | `300` |  |
| grafana."grafana.ini".dataproxy.timeout | int | `300` |  |
| grafana."grafana.ini".metrics.enabled | bool | `false` |  |
| grafana."grafana.ini".server.root_url | string | `"https://REP_DOMAIN_REP"` |  |
| grafana."grafana.ini".smtp.enabled | bool | `true` |  |
| grafana."grafana.ini".smtp.from_address | string | `"noreply@REP_GRAFANA_DOMAIN_REP"` |  |
| grafana."grafana.ini".smtp.host | string | `"mail.enschede.nl:587"` |  |
| grafana."grafana.ini".smtp.skip_verify | bool | `true` |  |
| grafana.adminPassword | string | `"KV_GRAFANA_ADMIN_KV"` |  |
| grafana.containerSecurityContext.allowPrivilegeEscalation | bool | `false` |  |
| grafana.containerSecurityContext.readOnlyRootFilesystem | bool | `true` |  |
| grafana.containerSecurityContext.runAsNonRoot | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".apiVersion | int | `1` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].disableDeletion | bool | `false` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].editable | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].folder | string | `"loki"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].name | string | `"default"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].options.path | string | `"/var/lib/grafana/dashboards/default"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].orgId | int | `1` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].type | string | `"file"` |  |
| grafana.dashboards.default.Logging_PodiumD.datasource | string | `"Loki"` |  |
| grafana.dashboards.default.Logging_PodiumD.token | string | `""` |  |
| grafana.dashboards.default.Logging_PodiumD.url | string | `"https://github.com/Dimpact-Samenwerking/helm-charts/blob/feature/IN-72_monitoring-logging/charts/monitoring-logging/grafana/dashboards/logging_PodiumD.json"` |  |
| grafana.dashboardsConfigMaps.default | string | `"loki-dashboard"` |  |
| grafana.datasources."datasources.yaml".apiVersion | int | `1` |  |
| grafana.datasources."datasources.yaml".datasources[0].editable | bool | `false` |  |
| grafana.datasources."datasources.yaml".datasources[0].isDefault | bool | `true` |  |
| grafana.datasources."datasources.yaml".datasources[0].jsonData.timeout | int | `300` |  |
| grafana.datasources."datasources.yaml".datasources[0].name | string | `"Loki"` |  |
| grafana.datasources."datasources.yaml".datasources[0].type | string | `"loki"` |  |
| grafana.datasources."datasources.yaml".datasources[0].url | string | `"http://loki:3100"` |  |
| grafana.datasources."datasources.yaml".deleteDatasources[0].name | string | `"Prometheus"` |  |
| grafana.datasources."datasources.yaml".deleteDatasources[1].name | string | `"Alertmanager"` |  |
| grafana.downloadDashboardsImage.registry | string | `"REP_ACR_NAME_REP.azurecr.io"` |  |
| grafana.downloadDashboardsImage.repository | string | `"curl"` |  |
| grafana.downloadDashboardsImage.tag | string | `"7.85.0"` |  |
| grafana.envFromSecrets[0].name | string | `"gf-database-password"` |  |
| grafana.envFromSecrets[1].name | string | `"gf-client-secret"` |  |
| grafana.image.registry | string | `"REP_ACR_NAME_REP.azurecr.io"` |  |
| grafana.image.repository | string | `"grafana"` |  |
| grafana.image.tag | string | `"11.5.2"` |  |
| grafana.initChownData.image.registry | string | `"REP_ACR_NAME_REP.azurecr.io"` |  |
| grafana.initChownData.image.repository | string | `"grafana-init-chown-data"` |  |
| grafana.initChownData.image.tag | string | `"1.31.1"` |  |
| grafana.nodeSelector."kubernetes.azure.com/mode" | string | `"system"` |  |
| grafana.resources.limits.cpu | string | `"50m"` |  |
| grafana.resources.limits.memory | string | `"128Mi"` |  |
| grafana.resources.requests.cpu | string | `"10m"` |  |
| grafana.resources.requests.memory | string | `"96Mi"` |  |
| loki.auth_enabled | bool | `false` |  |
| loki.backend.replicas | int | `0` |  |
| loki.bloomBuilder.replicas | int | `0` |  |
| loki.bloomGateway.replicas | int | `0` |  |
| loki.bloomPlanner.replicas | int | `0` |  |
| loki.compactor.replicas | int | `1` |  |
| loki.deploymentMode | string | `"Distributed"` |  |
| loki.distributor.maxUnavailable | int | `2` |  |
| loki.distributor.replicas | int | `3` |  |
| loki.image.registry | string | `"REP_ACR_NAME_REP.azurecr.io"` |  |
| loki.image.repository | string | `"loki"` |  |
| loki.image.tag | string | `"3.1.0"` |  |
| loki.indexGateway.maxUnavailable | int | `1` |  |
| loki.indexGateway.replicas | int | `2` |  |
| loki.ingester.replicas | int | `3` |  |
| loki.querier.maxUnavailable | int | `2` |  |
| loki.querier.replicas | int | `3` |  |
| loki.queryFrontend.maxUnavailable | int | `1` |  |
| loki.queryFrontend.replicas | int | `2` |  |
| loki.queryScheduler.replicas | int | `2` |  |
| loki.read.replicas | int | `0` |  |
| loki.schemaConfig.configs[0].from | string | `"2024-04-01"` |  |
| loki.schemaConfig.configs[0].index.period | string | `"24h"` |  |
| loki.schemaConfig.configs[0].index.prefix | string | `"index_"` |  |
| loki.schemaConfig.configs[0].object_store | string | `"azure"` |  |
| loki.schemaConfig.configs[0].schema | string | `"v13"` |  |
| loki.schemaConfig.configs[0].store | string | `"tsdb"` |  |
| loki.singleBinary.replicas | int | `0` |  |
| loki.storage.azure.accountKey | string | `"REP_STORAGE_ACCOUNT_KEY_REP"` |  |
| loki.storage.azure.accountName | string | `"REP_STORAGE_ACCOUNT_REP"` |  |
| loki.storage.azure.container | string | `"logs"` |  |
| loki.storage.azure.request_timeout | int | `0` |  |
| loki.storage.bucketNames.chunks | string | `"chunks"` |  |
| loki.storage.bucketNames.ruler | string | `"ruler"` |  |
| loki.storage.type | string | `"azure"` |  |
| loki.write.replicas | int | `0` |  |
| lokiCanary.enabled | bool | `false` |  |
| monitoring.dashboards.enabled | bool | `false` |  |
| monitoring.rules.enabled | bool | `false` |  |
| monitoring.selfMonitoring.enabled | bool | `false` |  |
| monitoring.selfMonitoring.grafanaAgent.installOperator | bool | `false` |  |
| promtail.image.registry | string | `"REP_ACR_NAME_REP.azurecr.io"` |  |
| promtail.image.repository | string | `"promtail"` |  |
| promtail.image.tag | string | `"3.0.0"` |  |
| promtail.resources.limits.cpu | string | `"100m"` |  |
| promtail.resources.limits.memory | string | `"256Mi"` |  |
| promtail.resources.requests.cpu | string | `"50m"` |  |
| promtail.resources.requests.memory | string | `"96Mi"` |  |
| resultsCache.enabled | bool | `false` |  |
| sidecar.dashboards.skipReload | bool | `true` |  |
| sidecar.image.registry | string | `"REP_ACR_NAME_REP.azurecr.io"` |  |
| sidecar.image.repository | string | `"REP_ACR_NAME_REP.azurecr.io/grafana-sidecar"` |  |
| sidecar.image.tag | string | `"1.26.1"` |  |
| table_manager.retention_deletes_enabled | bool | `true` |  |
| table_manager.retention_period | string | `"90d"` |  |
| test.enabled | bool | `false` |  |
