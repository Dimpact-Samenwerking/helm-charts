# monitoring-logging

![Version: 1.0.14](https://img.shields.io/badge/Version-1.0.14-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 1.0.14](https://img.shields.io/badge/AppVersion-1.0.14-informational?style=flat-square)

A monitoring stack using Loki, Prometheus, Grafana Alloy, OpenTelemetry Collector, and Grafana. Optionally includes Grafana Tempo for distributed tracing.

## What's included

| Component | Purpose | Default |
|---|---|---|
| **kube-prometheus-stack** | Prometheus Operator, Prometheus, Alertmanager, node-exporter, kube-state-metrics | ✅ enabled |
| **Grafana** | Dashboards, OIDC auth via Keycloak, PodiumD_Metrics and PodiumD_Monitoring_Logging folders | ✅ enabled |
| **Loki** | Log aggregation backend | ✅ enabled |
| **Grafana Alloy** | Log collection agent (replaces Promtail), OTel-aware pipeline | ✅ enabled |
| **OpenTelemetry Collector** | OTLP receiver (gRPC :4317, HTTP :4318), pipeline to Prometheus + Loki | ✅ enabled |
| **Prometheus Pushgateway** | Push-based metrics ingestion | ✅ enabled |
| **Grafana Tempo** | Distributed tracing backend | ❌ optional (`values-enable-tempo.yaml`) |

## Grafana dashboards

All dashboards are statically mounted via ConfigMaps (no sidecar label required).

| Folder | Dashboards |
|---|---|
| `PodiumD_Monitoring_Logging` | Main monitoring, Logs viewer |
| `PodiumD_Metrics` | Kubernetes cluster, Deployments, Traefik, Keycloak, OTel Collector, Django RED, Node Exporter Full, Redis HA, ECK/Elasticsearch, ClamAV |

## Documentation

- [`docs/otel.md`](docs/otel.md) — OTel Collector pipeline, bearer auth, HTTP/gRPC config
- [`docs/prometheus-scraping.md`](docs/prometheus-scraping.md) — Prometheus scrape targets and ServiceMonitor/PodMonitor setup
- [`docs/grafana-auth.md`](docs/grafana-auth.md) — Grafana Keycloak OIDC auth, break-glass access
- [`docs/loki-storage.md`](docs/loki-storage.md) — Loki storage backends (filesystem, Azure Blob, MinIO)
- [`docs/enabling-alertmanager.md`](docs/enabling-alertmanager.md) — Alertmanager configuration

## Rollenbeheer in Grafana op basis van Keycloak-groepen:

https://dimpact.atlassian.net/wiki/spaces/PCP/pages/412090380/Keycloak+roles+for+monitoring

https://dimpact.atlassian.net/wiki/spaces/PCP/pages/448528393/3.+Gebruikers-+en+rollenbeheer+in+Grafana+via+Keycloak

## Add used chart repositories:

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add opentelemetry https://open-telemetry.github.io/opentelemetry-helm-charts
```

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| @grafana | alloy | 1.6.2 |
| @grafana | grafana | 10.5.15 |
| @grafana | loki | 6.55.0 |
| @grafana | tempo | 1.24.4 |
| @opentelemetry | opentelemetry-collector | 0.147.1 |
| @prometheus-community | kube-prometheus-stack | 83.0.0 |
| @prometheus-community | prometheus-pushgateway | 3.6.0 |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| alloy.alloy.configMap | object | `{"content":"// Discover pod logs only from the configured namespaces.\n// Server-side namespace filter: scopes the API watch, not just a relabel drop.\n// The namespace list comes from .Values.logCollectionNamespaces so it\n// can be customized per environment.\ndiscovery.kubernetes \"pods\" {\n  role = \"pod\"\n\n  namespaces {\n    names = [{{ range $i, $ns := .Values.logCollectionNamespaces }}{{ if $i }}, {{ end }}{{ $ns | quote }}{{ end }}]\n  }\n}\n\n// Relabel: keep only pods on this node, drop terminated pods,\n// build the log path glob, add k8s metadata.\ndiscovery.relabel \"pod_logs\" {\n  targets = discovery.kubernetes.pods.targets\n\n  // Only tail files for pods scheduled on this node\n  rule {\n    source_labels = [\"__meta_kubernetes_pod_node_name\"]\n    regex         = env(\"NODE_NAME\")\n    action        = \"keep\"\n  }\n\n  // Drop pods in terminal phases\n  rule {\n    source_labels = [\"__meta_kubernetes_pod_phase\"]\n    regex         = \"Pending|Succeeded|Failed|Completed\"\n    action        = \"drop\"\n  }\n\n  rule {\n    source_labels = [\"__meta_kubernetes_namespace\"]\n    target_label  = \"namespace\"\n  }\n\n  rule {\n    source_labels = [\"__meta_kubernetes_pod_name\"]\n    target_label  = \"pod\"\n  }\n\n  rule {\n    source_labels = [\"__meta_kubernetes_pod_container_name\"]\n    target_label  = \"container\"\n  }\n\n  rule {\n    source_labels = [\"__meta_kubernetes_pod_label_app_kubernetes_io_name\"]\n    target_label  = \"app\"\n  }\n\n  // Build the log path glob — *.log captures all container restarts\n  // (0.log, 1.log, …). local.file_match below expands the glob into\n  // real file paths; without it, loki.source.file would os.Stat the\n  // literal \"*.log\" string and skip every target.\n  // Use ${n} notation: $n_ would include the underscore in the capture group reference.\n  rule {\n    source_labels = [\"__meta_kubernetes_namespace\", \"__meta_kubernetes_pod_name\", \"__meta_kubernetes_pod_uid\", \"__meta_kubernetes_pod_container_name\"]\n    separator     = \"/\"\n    regex         = \"(.+)/(.+)/(.+)/(.+)\"\n    replacement   = \"/var/log/pods/${1}_${2}_${3}/${4}/*.log\"\n    target_label  = \"__path__\"\n  }\n}\n\n// Resolve __path__ globs into concrete files (0.log, 1.log, …).\n// sync_period determines how often new rotated files are picked up.\nlocal.file_match \"pod_logs\" {\n  path_targets = discovery.relabel.pod_logs.output\n  sync_period  = \"10s\"\n}\n\n// Tail log files, strip CRI prefix (containerd format: timestamp stream flags log)\n// and forward to Loki. Equivalent to Promtail's pipeline_stages: [cri: {}].\nloki.source.file \"pod_logs\" {\n  targets    = local.file_match.pod_logs.targets\n  forward_to = [loki.process.cri.receiver]\n}\n\nloki.process \"cri\" {\n  forward_to = [loki.write.loki_gateway.receiver]\n\n  stage.cri {}\n}\n\nloki.write \"loki_gateway\" {\n  endpoint {\n    url       = \"http://{{ .Release.Name }}-loki-gateway/loki/api/v1/push\"\n    tenant_id = \"1\"\n  }\n}\n"}` | configMap.content is processed by Helm tpl, so {{ .Release.Name }} is valid |
| alloy.alloy.extraEnv[0].name | string | `"NODE_NAME"` |  |
| alloy.alloy.extraEnv[0].valueFrom.fieldRef.fieldPath | string | `"spec.nodeName"` |  |
| alloy.alloy.mounts.dockercontainers | bool | `true` |  |
| alloy.alloy.mounts.varlog | bool | `true` |  |
| alloy.alloy.resources.limits.cpu | string | `"100m"` |  |
| alloy.alloy.resources.limits.memory | string | `"256Mi"` |  |
| alloy.alloy.resources.requests.cpu | string | `"50m"` |  |
| alloy.alloy.resources.requests.memory | string | `"96Mi"` |  |
| alloy.configReloader.image | object | `{"pullPolicy":"IfNotPresent","registry":"quay.io","repository":"prometheus-operator/prometheus-config-reloader","tag":"v0.81.0"}` | config-reloader sidecar image settings (Alloy hot-reload, separate from the operator's config-reloader) quay.io/prometheus-operator/prometheus-config-reloader:v0.81.0 |
| alloy.controller | object | `{"nodeSelector":{"kubernetes.azure.com/agentpool":"userpool"}}` | DaemonSet scheduling. Pin Alloy to the user pool because the discovery.kubernetes namespaces filter below scopes log capture to podiumd + monitoring, both of which run on the user pool. See docs/upgrade-from-1.0.12-to-1.0.13.md for why this overrides the 1.0.11→1.0.12 guidance to leave Alloy without a nodeSelector. |
| alloy.enabled | bool | `true` |  |
| alloy.image | object | `{"pullPolicy":"IfNotPresent","registry":"docker.io","repository":"grafana/alloy","tag":"v1.14.0"}` | alloy image settings docker.io/grafana/alloy:v1.14.0 |
| alloy.logCollectionNamespaces | list | `["podiumd","monitoring"]` | Namespaces Alloy collects pod logs from. This is a server-side namespace filter on the Kubernetes pod discovery (see configMap.content below). Override this if your workloads run in a different namespace, e.g. set to ["default", "monitoring"] when deploying apps to "default". |
| grafana."grafana.ini"."auth.anonymous".enabled | bool | `false` |  |
| grafana."grafana.ini"."auth.anonymous".hide_version | bool | `true` |  |
| grafana."grafana.ini"."auth.generic_oauth" | object | `{"allow_assign_grafana_admin":true,"allow_sign_up":true,"api_url":"https://keycloak.test.nl/realms/podiumd/protocol/openid-connect/userinfo","auth_url":"https://keycloak.test.nl/realms/podiumd/protocol/openid-connect/auth","client_id":"monitoring","client_secret":"","email_attribute_path":"email","enabled":true,"groups_attribute_path":"groups","login_attribute_path":"username","name":"Keycloak-podiumd","name_attribute_path":"name","org_mapping":"*:Viewer","role_attribute_path":"contains(monitoring_roles[*], 'admin') && 'Admin' || contains(monitoring_roles[*], 'editor') && 'Editor' || 'Viewer'","role_attribute_strict":false,"scopes":"openid email profile offline_access roles","skip_org_role_sync":false,"sync_ttl":60,"token_url":"https://keycloak.test.nl/realms/podiumd/protocol/openid-connect/token","use_pkce":true,"use_refresh_token":true}` | Authentication and Authorization with Keycloak |
| grafana."grafana.ini".auth.allow_sign_up | bool | `true` |  |
| grafana."grafana.ini".auth.disable_login_form | bool | `true` |  |
| grafana."grafana.ini".auth.disable_signout_menu | bool | `false` |  |
| grafana."grafana.ini".auth.oauth_auto_login | bool | `true` |  |
| grafana."grafana.ini".auth.oauth_skip_org_role_update_sync | bool | `false` |  |
| grafana."grafana.ini".feature_toggles | object | `{"grafanaAdvisor":true}` | Grafana Advisor surfaces recommendations in the Grafana UI |
| grafana."grafana.ini".metrics.enabled | bool | `false` |  |
| grafana."grafana.ini".security.content_security_policy | bool | `true` |  |
| grafana."grafana.ini".security.content_security_policy_template | string | `"script-src 'self' 'unsafe-eval' 'unsafe-inline' 'strict-dynamic' $NONCE;object-src 'none';font-src 'self';style-src 'self' 'unsafe-inline' blob:;img-src * data:;base-uri 'self';connect-src 'self' grafana.com ws://$ROOT_PATH wss://$ROOT_PATH;manifest-src 'self';media-src 'none';form-action 'self';"` |  |
| grafana."grafana.ini".security.cookie_samesite | string | `"lax"` |  |
| grafana."grafana.ini".security.cookie_secure | bool | `true` |  |
| grafana."grafana.ini".security.hide_version | bool | `true` |  |
| grafana."grafana.ini".server.domain | string | `"logs.test.nl"` |  |
| grafana."grafana.ini".server.enforce_domain | bool | `true` |  |
| grafana."grafana.ini".server.root_url | string | `"https://logs.test.nl/"` |  |
| grafana."grafana.ini".smtp | object | `{"enabled":true,"from_address":"noreply@dimpact.nl","from_name":"PodiumD Monitoring","host":"mail.enschede.nl:587","skip_verify":false,"startTLS_policy":"MandatoryStartTLS"}` | SMTP settings for Grafana alerting e-mail notifications (contact points). The relay accepts mail from cluster egress IPs only; no authentication needed. IMPORTANT: `from_address` must be an address allowed to relay through this environment's mail server — an unlisted sender gets silently rejected/dropped. Check with infra/ops per environment before changing. |
| grafana.assertNoLeakedSecrets | bool | `false` |  |
| grafana.containerSecurityContext.allowPrivilegeEscalation | bool | `false` |  |
| grafana.containerSecurityContext.readOnlyRootFilesystem | bool | `false` |  |
| grafana.containerSecurityContext.runAsNonRoot | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".apiVersion | int | `1` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].allowUiUpdates | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].disableDeletion | bool | `false` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].editable | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].folder | string | `"PodiumD_Monitoring_Logging"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].name | string | `"meta"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].options.path | string | `"/var/lib/grafana/dashboards/meta"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].orgId | int | `1` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].type | string | `"file"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[0].updateIntervalSeconds | int | `30` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[1].allowUiUpdates | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[1].disableDeletion | bool | `false` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[1].editable | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[1].folder | string | `"PodiumD_Monitoring_Logging"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[1].name | string | `"default"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[1].options.path | string | `"/var/lib/grafana/dashboards/default"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[1].orgId | int | `1` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[1].type | string | `"file"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[1].updateIntervalSeconds | int | `30` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[2].allowUiUpdates | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[2].disableDeletion | bool | `false` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[2].editable | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[2].folder | string | `"PodiumD_Monitoring_Logging"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[2].name | string | `"logs"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[2].options.path | string | `"/var/lib/grafana/dashboards/logs"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[2].orgId | int | `1` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[2].type | string | `"file"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[2].updateIntervalSeconds | int | `30` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[3].allowUiUpdates | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[3].disableDeletion | bool | `false` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[3].editable | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[3].folder | string | `"PodiumD_Metrics"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[3].name | string | `"metrics"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[3].options.path | string | `"/var/lib/grafana/dashboards/metrics"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[3].orgId | int | `1` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[3].type | string | `"file"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[3].updateIntervalSeconds | int | `30` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[4].allowUiUpdates | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[4].disableDeletion | bool | `false` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[4].editable | bool | `true` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[4].folder | string | `"PodiumD_Metrics"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[4].name | string | `"metrics-node"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[4].options.path | string | `"/var/lib/grafana/dashboards/metrics-node"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[4].orgId | int | `1` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[4].type | string | `"file"` |  |
| grafana.dashboardProviders."dashboardproviders.yaml".providers[4].updateIntervalSeconds | int | `30` |  |
| grafana.dashboardsConfigMaps | object | `{"default":"logging-main-dashboard","logs":"logging-logs","meta":"meta","metrics":"monitoring-metrics-dashboards","metrics-node":"monitoring-metrics-dashboards-node"}` | Dashboard opgenomen in ConfigMap |
| grafana.datasources."datasources.yaml".apiVersion | int | `1` |  |
| grafana.datasources."datasources.yaml".datasources[0].access | string | `"proxy"` |  |
| grafana.datasources."datasources.yaml".datasources[0].editable | bool | `true` |  |
| grafana.datasources."datasources.yaml".datasources[0].isDefault | bool | `false` |  |
| grafana.datasources."datasources.yaml".datasources[0].name | string | `"Prometheus"` |  |
| grafana.datasources."datasources.yaml".datasources[0].readOnly | bool | `false` |  |
| grafana.datasources."datasources.yaml".datasources[0].type | string | `"prometheus"` |  |
| grafana.datasources."datasources.yaml".datasources[0].uid | string | `"prometheus"` |  |
| grafana.datasources."datasources.yaml".datasources[0].url | string | `"http://{{ .Release.Name }}-kube-prometheus-prometheus:9090"` |  |
| grafana.datasources."datasources.yaml".datasources[1].access | string | `"proxy"` |  |
| grafana.datasources."datasources.yaml".datasources[1].editable | bool | `true` |  |
| grafana.datasources."datasources.yaml".datasources[1].isDefault | bool | `true` |  |
| grafana.datasources."datasources.yaml".datasources[1].jsonData.httpHeaderName1 | string | `"X-Scope-OrgID"` |  |
| grafana.datasources."datasources.yaml".datasources[1].jsonData.timeout | int | `300` |  |
| grafana.datasources."datasources.yaml".datasources[1].name | string | `"loki"` |  |
| grafana.datasources."datasources.yaml".datasources[1].readOnly | bool | `false` |  |
| grafana.datasources."datasources.yaml".datasources[1].secureJsonData.httpHeaderValue1 | string | `"1"` |  |
| grafana.datasources."datasources.yaml".datasources[1].type | string | `"loki"` |  |
| grafana.datasources."datasources.yaml".datasources[1].uid | string | `"loki"` |  |
| grafana.datasources."datasources.yaml".datasources[1].url | string | `"http://{{ .Release.Name }}-loki-gateway"` |  |
| grafana.datasources."datasources.yaml".datasources[1].version | int | `1` |  |
| grafana.datasources."datasources.yaml".datasources[2] | object | `{"access":"proxy","editable":true,"isDefault":false,"jsonData":{"nodeGraph":{"enabled":true},"serviceMap":{"datasourceUid":"prometheus"},"tracesToLogsV2":{"datasourceUid":"loki","filterBySpanID":false,"filterByTraceID":true},"tracesToMetrics":{"datasourceUid":"prometheus"}},"name":"Tempo","readOnly":false,"type":"tempo","uid":"tempo","url":"http://{{ .Release.Name }}-tempo:3200"}` | Tempo datasource: requires tempo.enabled=true |
| grafana.deploymentStrategy.type | string | `"Recreate"` |  |
| grafana.downloadDashboardsImage | object | `{"pullPolicy":"IfNotPresent","sha":"","tag":"8.16.0"}` | curl image settings docker.io/curlimages/curl:8.16.0 |
| grafana.enabled | bool | `true` |  |
| grafana.image | object | `{"pullPolicy":"IfNotPresent","tag":"12.3.0-17814087142-ubuntu"}` | Grafana image settings docker.io/grafana/grafana:12.3.0-17814087142-ubuntu |
| grafana.imageRenderer.image | object | `{"pullPolicy":"Always","tag":"v4.0.14"}` | Grafana image renderer settings docker.io/grafana/grafana-image-renderer:v4.0.14 |
| grafana.initChownData.image | object | `{"pullPolicy":"IfNotPresent","tag":"1.37.0-uclibc"}` | Busybox image settings docker.io/library/busybox:1.37.0-uclibc |
| grafana.persistence.accessModes[0] | string | `"ReadWriteOnce"` |  |
| grafana.persistence.enabled | bool | `true` |  |
| grafana.persistence.finalizers[0] | string | `"kubernetes.io/pvc-protection"` |  |
| grafana.persistence.size | string | `"20Gi"` |  |
| grafana.persistence.storageClassName | string | `"managed-csi"` |  |
| grafana.persistence.type | string | `"pvc"` |  |
| grafana.resources.limits.cpu | string | `"200m"` |  |
| grafana.resources.limits.memory | string | `"256Mi"` |  |
| grafana.resources.requests.cpu | string | `"50m"` |  |
| grafana.resources.requests.memory | string | `"128Mi"` |  |
| grafana.sidecar.dashboards.enabled | bool | `true` |  |
| grafana.sidecar.dashboards.label | string | `"grafana_dashboard"` |  |
| grafana.sidecar.dashboards.labelValue | string | `"1"` |  |
| grafana.sidecar.datasources.enabled | bool | `true` |  |
| grafana.testFramework.image | object | `{"tag":"1.12.0"}` | bats image settings docker.io/bats/bats:1.12.0 |
| grafana.testFramework.imagePullPolicy | string | `"IfNotPresent"` |  |
| kube-prometheus-stack.alertmanager.enabled | bool | `false` |  |
| kube-prometheus-stack.crds.enabled | bool | `false` |  |
| kube-prometheus-stack.enabled | bool | `true` |  |
| kube-prometheus-stack.grafana.enabled | bool | `false` |  |
| kube-prometheus-stack.kube-state-metrics | object | `{"image":{"pullPolicy":"IfNotPresent","registry":"registry.k8s.io","repository":"kube-state-metrics/kube-state-metrics","tag":"v2.17.0"},"resources":{"limits":{"cpu":"100m","memory":"128Mi"},"requests":{"cpu":"10m","memory":"64Mi"}}}` | kube-state-metrics image settings registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.17.0 |
| kube-prometheus-stack.prometheus-node-exporter | object | `{"image":{"pullPolicy":"IfNotPresent","registry":"quay.io","repository":"prometheus/node-exporter","tag":"v1.9.1"},"resources":{"limits":{"cpu":"100m","memory":"64Mi"},"requests":{"cpu":"10m","memory":"32Mi"}}}` | node-exporter image settings quay.io/prometheus/node-exporter:v1.9.1 |
| kube-prometheus-stack.prometheus.prometheusSpec.additionalArgs | list | `[{"name":"web.enable-remote-write-receiver","value":""}]` | Enable remote-write receiver so the OTel Collector can push metrics |
| kube-prometheus-stack.prometheus.prometheusSpec.additionalScrapeConfigs | list | `[{"job_name":"kubernetes-pods","kubernetes_sd_configs":[{"role":"pod"}],"relabel_configs":[{"action":"keep","regex":"true","source_labels":["__meta_kubernetes_pod_annotation_prometheus_io_scrape"]},{"action":"replace","regex":"(.+)","source_labels":["__meta_kubernetes_pod_annotation_prometheus_io_path"],"target_label":"__metrics_path__"},{"action":"replace","regex":"([^:]+)(?::\\d+)?;(\\d+)","replacement":"$1:$2","source_labels":["__address__","__meta_kubernetes_pod_annotation_prometheus_io_port"],"target_label":"__address__"},{"action":"labelmap","regex":"__meta_kubernetes_pod_label_(.+)"},{"source_labels":["__meta_kubernetes_namespace"],"target_label":"namespace"},{"source_labels":["__meta_kubernetes_pod_name"],"target_label":"pod"},{"action":"keep","regex":"Running","source_labels":["__meta_kubernetes_pod_phase"]}]}]` | Scrape pods carrying prometheus.io/scrape annotations. Needed for components whose charts don't ship a ServiceMonitor/PodMonitor (e.g. solr-operator, zookeeper-operator, redis-operator) but do set the standard `prometheus.io/{scrape,port,path}` pod annotations. |
| kube-prometheus-stack.prometheus.prometheusSpec.image | object | `{"registry":"quay.io","repository":"prometheus/prometheus","tag":"v3.6.0"}` | prometheus image settings quay.io/prometheus/prometheus:v3.6.0 |
| kube-prometheus-stack.prometheus.prometheusSpec.logLevel | string | `"warn"` |  |
| kube-prometheus-stack.prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues | bool | `false` |  |
| kube-prometheus-stack.prometheus.prometheusSpec.resources.limits.cpu | string | `"1"` |  |
| kube-prometheus-stack.prometheus.prometheusSpec.resources.limits.memory | string | `"2Gi"` |  |
| kube-prometheus-stack.prometheus.prometheusSpec.resources.requests.cpu | string | `"100m"` |  |
| kube-prometheus-stack.prometheus.prometheusSpec.resources.requests.memory | string | `"512Mi"` |  |
| kube-prometheus-stack.prometheus.prometheusSpec.retention | string | `"7d"` |  |
| kube-prometheus-stack.prometheus.prometheusSpec.retentionSize | string | `""` |  |
| kube-prometheus-stack.prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues | bool | `false` | Watch ALL namespaces for ServiceMonitor and PodMonitor resources. This allows ServiceMonitors deployed in the podiumd namespace to be discovered by Prometheus running in the monitoring namespace. |
| kube-prometheus-stack.prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.metadata.name | string | `"db"` |  |
| kube-prometheus-stack.prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.accessModes[0] | string | `"ReadWriteOnce"` |  |
| kube-prometheus-stack.prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage | string | `"20Gi"` |  |
| kube-prometheus-stack.prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.storageClassName | string | `"managed-csi"` |  |
| kube-prometheus-stack.prometheusOperator.admissionWebhooks.image | object | `{"pullPolicy":"IfNotPresent","registry":"quay.io","repository":"prometheus-operator/admission-webhook","tag":"v0.90.1"}` | admission-webhook image settings (same release as the operator) quay.io/prometheus-operator/admission-webhook:v0.90.1 |
| kube-prometheus-stack.prometheusOperator.admissionWebhooks.patch.image | object | `{"pullPolicy":"IfNotPresent","registry":"ghcr.io","repository":"jkroepke/kube-webhook-certgen","tag":"1.8.0"}` | kube-webhook-certgen image for admission webhook TLS certificate provisioning ghcr.io/jkroepke/kube-webhook-certgen:1.8.0 |
| kube-prometheus-stack.prometheusOperator.image | object | `{"pullPolicy":"IfNotPresent","registry":"quay.io","repository":"prometheus-operator/prometheus-operator","tag":"v0.90.1"}` | prometheus-operator image settings quay.io/prometheus-operator/prometheus-operator:v0.90.1 |
| kube-prometheus-stack.prometheusOperator.prometheusConfigReloader | object | `{"image":{"pullPolicy":"IfNotPresent","registry":"quay.io","repository":"prometheus-operator/prometheus-config-reloader","tag":"v0.90.1"},"resources":{"limits":{"cpu":"50m","memory":"32Mi"},"requests":{"cpu":"5m","memory":"16Mi"}}}` | prometheus-config-reloader image settings (injected into Prometheus StatefulSet by the operator) quay.io/prometheus-operator/prometheus-config-reloader:v0.90.1 |
| kube-prometheus-stack.prometheusOperator.resources.limits.cpu | string | `"200m"` |  |
| kube-prometheus-stack.prometheusOperator.resources.limits.memory | string | `"256Mi"` |  |
| kube-prometheus-stack.prometheusOperator.resources.requests.cpu | string | `"50m"` |  |
| kube-prometheus-stack.prometheusOperator.resources.requests.memory | string | `"64Mi"` |  |
| loki.backend.replicas | int | `0` |  |
| loki.chunksCache.allocatedMemory | int | `1024` |  |
| loki.chunksCache.defaultValidity | string | `"6h"` |  |
| loki.chunksCache.enabled | bool | `true` |  |
| loki.compactor.replicas | int | `1` |  |
| loki.deploymentMode | string | `"Distributed"` |  |
| loki.distributor.maxUnavailable | int | `2` |  |
| loki.distributor.replicas | int | `3` |  |
| loki.distributor.resources.limits.cpu | string | `"500m"` |  |
| loki.distributor.resources.limits.memory | string | `"256Mi"` |  |
| loki.distributor.resources.requests.cpu | string | `"50m"` |  |
| loki.distributor.resources.requests.memory | string | `"128Mi"` |  |
| loki.enabled | bool | `true` |  |
| loki.enterprise.image.pullPolicy | string | `"IfNotPresent"` |  |
| loki.enterprise.image.tag | string | `"3.5.4"` |  |
| loki.enterprise.provisioner.image.pullPolicy | string | `"IfNotPresent"` |  |
| loki.enterprise.provisioner.image.tag | string | `"3.5.2"` |  |
| loki.gateway.image.pullPolicy | string | `"IfNotPresent"` |  |
| loki.gateway.image.tag | string | `"alpine3.22-perl"` |  |
| loki.gateway.resources.limits.cpu | string | `"100m"` |  |
| loki.gateway.resources.limits.memory | string | `"64Mi"` |  |
| loki.gateway.resources.requests.cpu | string | `"10m"` |  |
| loki.gateway.resources.requests.memory | string | `"32Mi"` |  |
| loki.indexGateway.maxUnavailable | int | `1` |  |
| loki.indexGateway.replicas | int | `2` |  |
| loki.indexGateway.resources.limits.cpu | string | `"200m"` |  |
| loki.indexGateway.resources.limits.memory | string | `"128Mi"` |  |
| loki.indexGateway.resources.requests.cpu | string | `"20m"` |  |
| loki.indexGateway.resources.requests.memory | string | `"64Mi"` |  |
| loki.ingester.replicas | int | `3` |  |
| loki.ingester.resources.limits.cpu | string | `"500m"` |  |
| loki.ingester.resources.limits.memory | string | `"512Mi"` |  |
| loki.ingester.resources.requests.cpu | string | `"100m"` |  |
| loki.ingester.resources.requests.memory | string | `"256Mi"` |  |
| loki.ingester.zoneAwareReplication.zoneA | object | `{}` |  |
| loki.ingester.zoneAwareReplication.zoneB | object | `{}` |  |
| loki.ingester.zoneAwareReplication.zoneC | object | `{}` |  |
| loki.kubectlImage.pullPolicy | string | `"IfNotPresent"` |  |
| loki.kubectlImage.registry | string | `"registry.k8s.io"` |  |
| loki.kubectlImage.repository | string | `"kubectl"` |  |
| loki.kubectlImage.tag | string | `"v1.33.0"` |  |
| loki.loki.auth_enabled | bool | `false` |  |
| loki.loki.compactor.compaction_interval | string | `"10m"` |  |
| loki.loki.compactor.delete_request_store | string | `"s3"` |  |
| loki.loki.compactor.retention_delete_delay | string | `"2h"` |  |
| loki.loki.compactor.retention_delete_worker_count | int | `150` |  |
| loki.loki.compactor.retention_enabled | bool | `true` |  |
| loki.loki.frontend.max_outstanding_per_tenant | int | `6144` |  |
| loki.loki.image.pullPolicy | string | `"IfNotPresent"` |  |
| loki.loki.image.tag | string | `"3.6.7"` |  |
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
| loki.loki.limits_config.max_query_length | string | `"721h"` |  |
| loki.loki.limits_config.max_query_lookback | string | `"30d"` |  |
| loki.loki.limits_config.max_query_parallelism | int | `48` |  |
| loki.loki.limits_config.max_query_series | int | `5000` |  |
| loki.loki.limits_config.max_streams_per_user | int | `0` |  |
| loki.loki.limits_config.otlp_config.resource_attributes.attributes_config[0].action | string | `"index_label"` |  |
| loki.loki.limits_config.otlp_config.resource_attributes.attributes_config[0].regex | string | `"app"` |  |
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
| loki.memcached.image.pullPolicy | string | `"IfNotPresent"` |  |
| loki.memcached.image.tag | string | `"alpine3.22"` |  |
| loki.memcachedExporter.image.pullPolicy | string | `"IfNotPresent"` |  |
| loki.memcachedExporter.image.tag | string | `"v0.15.3"` |  |
| loki.minio.enabled | bool | `true` |  |
| loki.minio.global | string | `nil` |  |
| loki.minio.image.pullPolicy | string | `"IfNotPresent"` |  |
| loki.minio.image.tag | string | `"RELEASE.2025-07-23T15-54-02Z-cpuv1"` |  |
| loki.minio.mcImage.pullPolicy | string | `"IfNotPresent"` |  |
| loki.minio.mcImage.tag | string | `"RELEASE.2025-08-13T08-35-41Z-cpuv1"` |  |
| loki.minio.persistence.size | string | `"20Gi"` |  |
| loki.minio.persistence.storageClass | string | `"managed-csi"` |  |
| loki.monitoring.dashboards.enabled | bool | `false` |  |
| loki.monitoring.rules.enabled | bool | `false` |  |
| loki.monitoring.selfMonitoring.enabled | bool | `false` |  |
| loki.monitoring.selfMonitoring.grafanaAgent.installOperator | bool | `false` |  |
| loki.querier.maxUnavailable | int | `2` |  |
| loki.querier.replicas | int | `3` |  |
| loki.querier.resources.limits.cpu | string | `"500m"` |  |
| loki.querier.resources.limits.memory | string | `"512Mi"` |  |
| loki.querier.resources.requests.cpu | string | `"50m"` |  |
| loki.querier.resources.requests.memory | string | `"128Mi"` |  |
| loki.queryFrontend.maxUnavailable | int | `1` |  |
| loki.queryFrontend.replicas | int | `2` |  |
| loki.queryFrontend.resources.limits.cpu | string | `"200m"` |  |
| loki.queryFrontend.resources.limits.memory | string | `"128Mi"` |  |
| loki.queryFrontend.resources.requests.cpu | string | `"20m"` |  |
| loki.queryFrontend.resources.requests.memory | string | `"64Mi"` |  |
| loki.queryScheduler.replicas | int | `2` |  |
| loki.queryScheduler.resources.limits.cpu | string | `"100m"` |  |
| loki.queryScheduler.resources.limits.memory | string | `"128Mi"` |  |
| loki.queryScheduler.resources.requests.cpu | string | `"20m"` |  |
| loki.queryScheduler.resources.requests.memory | string | `"64Mi"` |  |
| loki.read.replicas | int | `0` |  |
| loki.resultsCache.defaultValidity | string | `"6h"` |  |
| loki.resultsCache.enabled | bool | `true` |  |
| loki.sidecar.image.pullPolicy | string | `"IfNotPresent"` |  |
| loki.sidecar.image.tag | string | `"1.30.10"` |  |
| loki.test.enabled | bool | `false` |  |
| loki.write.replicas | int | `0` |  |
| opentelemetry-collector | object | `{"command":{"name":"otelcol-contrib"},"config":{"exporters":{"otlphttp/loki":{"endpoint":"http://${env:RELEASE_NAME}-loki-gateway/otlp","headers":{"X-Scope-OrgID":"1"}},"prometheusremotewrite":{"endpoint":"http://${env:RELEASE_NAME}-kube-prometheus-prometheus:9090/api/v1/write","tls":{"insecure":true}}},"extensions":{"bearertokenauth":{"token":"${env:OTEL_HTTP_AUTH_TOKEN}"},"health_check":{"endpoint":"0.0.0.0:13133"}},"processors":{"batch":{"send_batch_size":1000,"timeout":"5s"},"memory_limiter":{"check_interval":"1s","limit_percentage":80,"spike_limit_percentage":25}},"receivers":{"otlp":{"protocols":{"grpc":{"endpoint":"0.0.0.0:4317"},"http":{"auth":{"authenticator":"bearertokenauth"},"endpoint":"0.0.0.0:4318"}}}},"service":{"extensions":["health_check","bearertokenauth"],"pipelines":{"logs":{"exporters":["otlphttp/loki"],"processors":["memory_limiter","batch"],"receivers":["otlp"]},"metrics":{"exporters":["prometheusremotewrite"],"processors":["memory_limiter","batch"],"receivers":["otlp"]}},"telemetry":{"metrics":{"address":"0.0.0.0:8888"}}}},"enabled":true,"extraEnvs":[{"name":"RELEASE_NAME","valueFrom":{"fieldRef":{"fieldPath":"metadata.labels['app.kubernetes.io/instance']"}}},{"name":"OTEL_HTTP_AUTH_TOKEN","value":"REP_OTEL_HTTP_AUTH_TOKEN_REP"}],"image":{"pullPolicy":"IfNotPresent","repository":"ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-contrib"},"mode":"deployment","podAnnotations":{"prometheus.io/path":"/metrics","prometheus.io/port":"8888","prometheus.io/scrape":"true"},"ports":{"metrics":{"containerPort":8888,"enabled":true,"protocol":"TCP","servicePort":8888},"otlp":{"containerPort":4317,"enabled":true,"protocol":"TCP","servicePort":4317},"otlp-http":{"containerPort":4318,"enabled":true,"protocol":"TCP","servicePort":4318}},"resources":{"limits":{"cpu":"500m","memory":"512Mi"},"requests":{"cpu":"100m","memory":"128Mi"}}}` | OpenTelemetry Collector: gateway deployment receiving OTLP from applications. Exports: logs → Loki, metrics → Prometheus, traces → Tempo (when enabled). Applications should send OTLP to <release-name>-opentelemetry-collector:4317 (gRPC) or <release-name>-opentelemetry-collector:4318 (HTTP). See otel.md for per-service instrumentation config. #OTel instrumentation |
| opentelemetry-collector.config.exporters.otlphttp/loki | object | `{"endpoint":"http://${env:RELEASE_NAME}-loki-gateway/otlp","headers":{"X-Scope-OrgID":"1"}}` | Logs → Loki via OTLP (Loki 3.x native OTLP endpoint) |
| opentelemetry-collector.config.exporters.prometheusremotewrite | object | `{"endpoint":"http://${env:RELEASE_NAME}-kube-prometheus-prometheus:9090/api/v1/write","tls":{"insecure":true}}` | Metrics → Prometheus remote write receiver |
| opentelemetry-collector.config.extensions.bearertokenauth | object | `{"token":"${env:OTEL_HTTP_AUTH_TOKEN}"}` | Bearer token auth for the OTLP HTTP receiver (port 4318). Token is injected via the OTEL_HTTP_AUTH_TOKEN environment variable. |
| opentelemetry-collector.extraEnvs | list | `[{"name":"RELEASE_NAME","valueFrom":{"fieldRef":{"fieldPath":"metadata.labels['app.kubernetes.io/instance']"}}},{"name":"OTEL_HTTP_AUTH_TOKEN","value":"REP_OTEL_HTTP_AUTH_TOKEN_REP"}]` | Inject release name so config can reference sibling chart services |
| opentelemetry-collector.extraEnvs[1] | object | `{"name":"OTEL_HTTP_AUTH_TOKEN","value":"REP_OTEL_HTTP_AUTH_TOKEN_REP"}` | Bearer token for the OTLP HTTP endpoint (port 4318). Replace REP_OTEL_HTTP_AUTH_TOKEN_REP with the actual token value or override this in your environment values file. |
| opentelemetry-collector.ports | object | `{"metrics":{"containerPort":8888,"enabled":true,"protocol":"TCP","servicePort":8888},"otlp":{"containerPort":4317,"enabled":true,"protocol":"TCP","servicePort":4317},"otlp-http":{"containerPort":4318,"enabled":true,"protocol":"TCP","servicePort":4318}}` | Expose OTLP gRPC, HTTP and self-metrics ports |
| otelCollectorMonitor | object | `{"enabled":true,"scrapeInterval":"30s"}` | ServiceMonitor for the OpenTelemetry Collector internal metrics endpoint (port 8888). Allows Prometheus to scrape otelcol_* health/pipeline metrics. |
| otelCollectorMonitor.scrapeInterval | string | `"30s"` | Prometheus scrape interval. |
| otelIngress | object | `{"clusterIssuer":"letsencrypt-prod","enabled":false,"hostname":"","middleware":"{{ .Release.Namespace }}-otel-ip-allowlist@kubernetescrd","tlsSecretName":"otel-tls"}` | Ingress for the OTLP HTTP endpoint (port 4318). Exposes the collector externally via Traefik with an ip-allowlist middleware. Requires cert-manager for TLS. Disabled by default — set hostname to enable. The middleware must be pre-created in the same namespace (e.g. a Traefik Middleware CRD). |
| otelIngress.hostname | string | `""` | External hostname, e.g. otel.example.nl |
| otelIngress.middleware | string | `"{{ .Release.Namespace }}-otel-ip-allowlist@kubernetescrd"` | Traefik middleware reference (namespace/name@kubernetescrd). Set to "" to disable. |
| prometheus-pushgateway | object | `{"enabled":true,"image":{"pullPolicy":"IfNotPresent","repository":"quay.io/prometheus/pushgateway","tag":"v1.11.1"},"resources":{"limits":{"cpu":"100m","memory":"64Mi"},"requests":{"cpu":"10m","memory":"32Mi"}}}` | Pushgateway: separate dependency (not bundled in kube-prometheus-stack). quay.io/prometheus/pushgateway:v1.11.1 |
| tempo | object | `{"enabled":false,"persistence":{"enabled":true,"size":"10Gi","storageClassName":"managed-csi"},"tempo":{"image":{"pullPolicy":"IfNotPresent"},"receivers":{"otlp":{"protocols":{"grpc":{"endpoint":"0.0.0.0:4317"},"http":{"endpoint":"0.0.0.0:4318"}}}},"storage":{"trace":{"backend":"local","local":{"path":"/var/tempo/traces"},"wal":{"path":"/var/tempo/wal"}}}}}` | Grafana Tempo: distributed tracing backend. Disabled by default. Enable with: tempo.enabled=true Requires opentelemetry-collector.enabled=true to receive traces via OTLP. |
| tempo.tempo.image | object | `{"pullPolicy":"IfNotPresent"}` | tempo image settings docker.io/grafana/tempo:2.9.0 |
| traefikMonitor | object | `{"enabled":true,"namespace":"","scrapeInterval":"30s"}` | metrics.prometheus=true (default in the standard Traefik Helm chart). |
| traefikMonitor.namespace | string | `""` | Namespace where Traefik pods run. Leave empty to search all namespaces. |
| traefikMonitor.scrapeInterval | string | `"30s"` | Prometheus scrape interval. |
