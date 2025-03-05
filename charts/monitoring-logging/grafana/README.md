# grafana

![Version: 8.10.1](https://img.shields.io/badge/Version-8.10.1-informational?style=flat-square) ![AppVersion: 11.5.2](https://img.shields.io/badge/AppVersion-11.5.2-informational?style=flat-square)

The leading tool for querying and visualizing time series and metrics.

**Homepage:** <https://grafana.com>

## Source Code

* <https://github.com/grafana/grafana>
* <https://github.com/grafana/helm-charts>

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
| adminPassword | string | `"KV_GRAFANA_ADMIN_KV"` |  |
| containerSecurityContext.allowPrivilegeEscalation | bool | `false` |  |
| containerSecurityContext.readOnlyRootFilesystem | bool | `true` |  |
| containerSecurityContext.runAsNonRoot | bool | `true` |  |
| dashboardProviders."dashboardproviders.yaml".apiVersion | int | `1` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].disableDeletion | bool | `false` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].editable | bool | `true` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].folder | string | `"loki"` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].name | string | `"default"` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].options.path | string | `"/var/lib/grafana/dashboards/default"` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].orgId | int | `1` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].type | string | `"file"` |  |
| dashboards.default.Logging_PodiumD.datasource | string | `"Loki"` |  |
| dashboards.default.Logging_PodiumD.token | string | `""` |  |
| dashboards.default.Logging_PodiumD.url | string | `"https://github.com/Dimpact-Samenwerking/helm-charts/blob/feature/IN-72_monitoring-logging/charts/monitoring-logging/grafana/dashboards/logging_PodiumD.json"` |  |
| dashboardsConfigMaps.default | string | `"loki-dashboard"` |  |
| datasources."datasources.yaml".apiVersion | int | `1` |  |
| datasources."datasources.yaml".datasources[0].editable | bool | `false` |  |
| datasources."datasources.yaml".datasources[0].isDefault | bool | `true` |  |
| datasources."datasources.yaml".datasources[0].jsonData.timeout | int | `300` |  |
| datasources."datasources.yaml".datasources[0].name | string | `"Loki"` |  |
| datasources."datasources.yaml".datasources[0].type | string | `"loki"` |  |
| datasources."datasources.yaml".datasources[0].url | string | `"http://loki:3100"` |  |
| datasources."datasources.yaml".deleteDatasources[0].name | string | `"Prometheus"` |  |
| datasources."datasources.yaml".deleteDatasources[1].name | string | `"Alertmanager"` |  |
| downloadDashboardsImage.registry | string | `"REP_ACR_NAME_REP.azurecr.io"` |  |
| downloadDashboardsImage.repository | string | `"curl"` |  |
| downloadDashboardsImage.tag | string | `"7.85.0"` |  |
| envFromSecrets[0].name | string | `"gf-database-password"` |  |
| envFromSecrets[1].name | string | `"gf-client-secret"` |  |
| image.registry | string | `"REP_ACR_NAME_REP.azurecr.io"` |  |
| image.repository | string | `"grafana"` |  |
| image.tag | string | `"11.5.2"` |  |
| initChownData.image.registry | string | `"REP_ACR_NAME_REP.azurecr.io"` |  |
| initChownData.image.repository | string | `"grafana-init-chown-data"` |  |
| initChownData.image.tag | string | `"1.31.1"` |  |
| nodeSelector."kubernetes.azure.com/mode" | string | `"system"` |  |
| resources.limits.cpu | string | `"50m"` |  |
| resources.limits.memory | string | `"128Mi"` |  |
| resources.requests.cpu | string | `"10m"` |  |
| resources.requests.memory | string | `"96Mi"` |  |