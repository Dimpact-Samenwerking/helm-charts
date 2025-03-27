# kube-prometheus-stack

![Version: 70.3.0](https://img.shields.io/badge/Version-70.3.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: v0.81.0](https://img.shields.io/badge/AppVersion-v0.81.0-informational?style=flat-square)

kube-prometheus-stack collects Kubernetes manifests, Grafana dashboards, and Prometheus rules combined with documentation and scripts to provide easy to operate end-to-end Kubernetes cluster monitoring with Prometheus using the Prometheus Operator.

**Homepage:** <https://github.com/prometheus-operator/kube-prometheus>

## Maintainers

| Name | Email | Url |
| ---- | ------ | --- |
| andrewgkew | <andrew@quadcorps.co.uk> | <https://github.com/andrewgkew> |
| gianrubio | <gianrubio@gmail.com> | <https://github.com/gianrubio> |
| gkarthiks | <github.gkarthiks@gmail.com> | <https://github.com/gkarthiks> |
| GMartinez-Sisti | <kube-prometheus-stack@sisti.pt> | <https://github.com/GMartinez-Sisti> |
| jkroepke | <github@jkroepke.de> | <https://github.com/jkroepke> |
| scottrigby | <scott@r6by.com> | <https://github.com/scottrigby> |
| Xtigyro | <miroslav.hadzhiev@gmail.com> | <https://github.com/Xtigyro> |
| QuentinBisson | <quentin.bisson@gmail.com> | <https://github.com/QuentinBisson> |

## Source Code

* <https://github.com/prometheus-community/helm-charts>
* <https://github.com/prometheus-operator/kube-prometheus>

## Requirements

Kubernetes: `>=1.19.0-0`

| Repository | Name | Version |
|------------|------|---------|
|  | crds | 0.0.0 |
| https://grafana.github.io/helm-charts | grafana | 8.10.* |
| https://prometheus-community.github.io/helm-charts | kube-state-metrics | 5.31.* |
| https://prometheus-community.github.io/helm-charts | prometheus-node-exporter | 4.45.* |
| https://prometheus-community.github.io/helm-charts | prometheus-windows-exporter | 0.9.* |

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
| additionalDataSources[0].url | string | `"http://loki-gateway"` |  |
| additionalDataSources[0].version | int | `1` |  |
| adminPassword | string | `"KV_GRAFANA_ADMIN_KV"` |  |
| alertmanager.enabled | bool | `false` |  |
| containerSecurityContext.allowPrivilegeEscalation | bool | `false` |  |
| containerSecurityContext.readOnlyRootFilesystem | bool | `true` |  |
| containerSecurityContext.runAsNonRoot | bool | `true` |  |
| dashboardProviders."dashboardproviders.yaml".apiVersion | int | `1` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].disableDeletion | bool | `false` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].editable | bool | `true` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].folder | string | `""` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].name | string | `"default"` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].options.path | string | `"/var/lib/grafana/dashboards/default"` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].orgId | int | `1` |  |
| dashboardProviders."dashboardproviders.yaml".providers[0].type | string | `"file"` |  |
| dashboards.default.Logging_PodiumD.datasource | string | `"Loki"` |  |
| dashboards.default.Logging_PodiumD.token | string | `""` |  |
| dashboards.default.Logging_PodiumD.url | string | `"https://raw.githubusercontent.com/Dimpact-Samenwerking/helm-charts/refs/heads/feature/IN-72_monitoring-logging/charts/monitoring-logging/grafana/dashboards/logging_PodiumD.json"` |  |
| dashboardsConfigMaps.default | string | `"loki-dashboard"` |  |
| datasources."datasources.yaml".apiVersion | int | `1` |  |
| datasources."datasources.yaml".datasources[0].access | string | `"proxy"` |  |
| datasources."datasources.yaml".datasources[0].editable | bool | `false` |  |
| datasources."datasources.yaml".datasources[0].isDefault | bool | `false` |  |
| datasources."datasources.yaml".datasources[0].name | string | `"Prometheus"` |  |
| datasources."datasources.yaml".datasources[0].type | string | `"prometheus"` |  |
| datasources."datasources.yaml".datasources[0].url | string | `"http://prometheus-prometheus:9090"` |  |
| datasources."datasources.yaml".deleteDatasources[0].name | string | `"Alertmanager"` |  |
| datasources.alertmanager.enabled | bool | `false` |  |
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

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
