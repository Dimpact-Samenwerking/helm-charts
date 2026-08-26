# podiumd

![Version: 4.9.0](https://img.shields.io/badge/Version-4.9.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 4.9.0](https://img.shields.io/badge/AppVersion-4.9.0-informational?style=flat-square)

PodiumD Helm chart

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| @adfinis | keycloak-operator | 1.12.1 |
| @dimpact | brppersonenmock(brp-personen-mock) | 1.2.9 |
| @maykinmedia | objecten | 2.12.1 |
| @maykinmedia | objecttypen | 1.6.1 |
| @maykinmedia | openarchiefbeheer | 2.0.0 |
| @maykinmedia | openbeheer | 0.1.3 |
| @maykinmedia | openformulieren(openforms) | 1.12.0 |
| @maykinmedia | openinwoner | 2.4.0 |
| @maykinmedia | openklant | 1.11.0 |
| @maykinmedia | opennotificaties | 2.0.0 |
| @maykinmedia | openzaak | 1.14.2 |
| @maykinmedia | referentielijsten(referentielijsten) | 0.1.1 |
| @opstree | redis-operator | 0.26.1 |
| @wiremind | clamav | 3.7.2 |
| @worth-nl | omc(notifynl-omc-nodep) | 0.14.1 |
| @zac | zac(zaakafhandelcomponent) | 1.0.297 |
| @zgw-office-addin | zgw-office-addin | 0.0.89 |
| file://../mi-data | mi(mi-data) | 1.0.0 |
| https://helm.elastic.co | eck-operator | 3.5.0 |
| https://helm.elastic.co | kiss-eck(eck-stack) | 0.20.0 |
| https://openbao.github.io/openbao-helm | openbao | 0.28.4 |
| https://wearefrank.github.io/charts | zaakbrug | 2.3.28 |
| oci://ghcr.io/interne-taak-afhandeling | ita(internetaakafhandeling) | 3.3.0 |
| oci://ghcr.io/klantinteractie-servicesysteem | kiss(kiss-chart) | 3.0.0 |
| oci://ghcr.io/platform-autorisatie-beheer-component | pabc(pabc) | 1.1.1 |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| apiproxy.affinity | object | `{}` |  |
| apiproxy.enabled | bool | `false` |  |
| apiproxy.errorLogLevel | string | `"notice"` | nginx error_log level (debug|info|notice|warn|error|crit|alert|emerg). "debug" logs full request/response headers (incl. injected API keys/toepassing headers) and is very high-volume — use only for short-lived troubleshooting, never leave enabled given the BRP/citizen-data traffic this proxy carries. |
| apiproxy.image.pullPolicy | string | `"IfNotPresent"` |  |
| apiproxy.image.repository | string | `"nginxinc/nginx-unprivileged"` |  |
| apiproxy.image.tag | string | `"1.31.4@sha256:197f252f060ed357f2ab98d4256762d7d107c76f18ad8f0b9d5178854611566d"` |  |
| apiproxy.imagePullSecrets | list | `[]` |  |
| apiproxy.livenessProbe.initialDelaySeconds | int | `5` |  |
| apiproxy.livenessProbe.periodSeconds | int | `10` |  |
| apiproxy.locations.bag.<<.hostHeader | string | `"lab.api.mijniconnect.nl"` |  |
| apiproxy.locations.bag.<<.sslVerify | string | `""` |  |
| apiproxy.locations.bag.path | string | `"/lvbag/individuelebevragingen/v2/"` |  |
| apiproxy.locations.bag.targetUrl | string | `"https://lab.api.mijniconnect.nl/iconnect/apibagib/v2/"` |  |
| apiproxy.locations.bag.urlRewrite.enabled | bool | `false` |  |
| apiproxy.locations.bag.urlRewrite.internalUrl | string | `"http://api-proxy/lvbag/individuelebevragingen/v2/"` |  |
| apiproxy.locations.brp.<<.hostHeader | string | `"lab.api.mijniconnect.nl"` |  |
| apiproxy.locations.brp.<<.sslVerify | string | `""` |  |
| apiproxy.locations.brp.path | string | `"/haalcentraal/api/brp/"` |  |
| apiproxy.locations.brp.targetUrl | string | `"https://lab.api.mijniconnect.nl/iconnect/apihcbrp/actueel/prtcl/v2/"` |  |
| apiproxy.locations.brp.toepassingDefaultValue | string | `""` |  |
| apiproxy.locations.brp.toepassingHeaderName | string | `""` |  |
| apiproxy.locations.commonSettings.hostHeader | string | `"lab.api.mijniconnect.nl"` |  |
| apiproxy.locations.commonSettings.sslVerify | string | `""` |  |
| apiproxy.locations.kvkBasic.<<.hostHeader | string | `"lab.api.mijniconnect.nl"` |  |
| apiproxy.locations.kvkBasic.<<.sslVerify | string | `""` |  |
| apiproxy.locations.kvkBasic.targetUrl | string | `"https://lab.api.mijniconnect.nl/iconnect/apikvk/basprof/v1/v1/basisprofielen"` |  |
| apiproxy.locations.kvkBranch.<<.hostHeader | string | `"lab.api.mijniconnect.nl"` |  |
| apiproxy.locations.kvkBranch.<<.sslVerify | string | `""` |  |
| apiproxy.locations.kvkBranch.targetUrl | string | `"https://lab.api.mijniconnect.nl/iconnect/apikvk/vesprof/v1/v1/vestigingsprofielen"` |  |
| apiproxy.locations.kvkSearch.<<.hostHeader | string | `"lab.api.mijniconnect.nl"` |  |
| apiproxy.locations.kvkSearch.<<.sslVerify | string | `""` |  |
| apiproxy.locations.kvkSearch.targetUrl | string | `"https://lab.api.mijniconnect.nl/iconnect/apikvk/zoeken/v2/zoeken"` |  |
| apiproxy.nginxCertsSecret | string | `""` | Secret containing client certificate (`client.crt`/`client.key`) and CA bundle (`ca.crt`) for upstream mTLS. Leave empty to disable mTLS and skip the cert volume mount. When set, `sslVerify` auto-derives to "on"; when empty it auto-derives to "off". |
| apiproxy.nodeSelector | object | `{}` |  |
| apiproxy.readinessProbe.initialDelaySeconds | int | `5` |  |
| apiproxy.readinessProbe.periodSeconds | int | `10` |  |
| apiproxy.replicaCount | int | `1` |  |
| apiproxy.resolverIp | string | `"10.0.0.10"` |  |
| apiproxy.resources.limits.cpu | string | `"0.5"` |  |
| apiproxy.resources.limits.memory | string | `"256Mi"` |  |
| apiproxy.resources.requests.cpu | string | `"0.1"` |  |
| apiproxy.resources.requests.memory | string | `"128Mi"` |  |
| apiproxy.service.containerPort | int | `8080` |  |
| apiproxy.service.port | int | `80` |  |
| apiproxy.sslVerifyDepth | int | `6` | Maximum length of the upstream server certificate chain validated by nginx (`proxy_ssl_verify_depth`). Government API gateways occasionally chain through cross-signed intermediates; the nginx default of 1 is too shallow. Per-location overrides: set `apiproxy.locations.<loc>.sslVerifyDepth` to override this global value for a single upstream (e.g. bag, brp, kvkSearch). |
| apiproxy.tolerations | list | `[]` |  |
| clamav.clamdConfig | string | `"###############\n# General\n###############\n\nDatabaseDirectory /var/lib/clamav\nTemporaryDirectory /tmp\nLogTime yes\n# CUSTOM: Use pid file in tmp\nPidFile /tmp/clamd.pid\nLocalSocket /tmp/clamd.sock\nTCPSocket 3310\nForeground yes\n# Reload database sequentially to avoid double memory usage (~1.2 GiB vs ~2.4 GiB)\n# Scans are briefly blocked during reload, which is acceptable\nConcurrentDatabaseReload no\nMaxThreads 10\n\n###############\n# Results\n###############\n\nDetectPUA yes\nExcludePUA NetTool\nExcludePUA PWTool\nHeuristicAlerts yes\nBytecode yes\n\n###############\n# Scan\n###############\n\nScanPE yes\nDisableCertCheck yes\nScanELF yes\nAlertBrokenExecutables yes\nScanOLE2 yes\nScanPDF yes\nScanSWF yes\nScanMail yes\nPhishingSignatures yes\nPhishingScanURLs yes\nScanHTML yes\nScanArchive yes\n\n###############\n# Limits\n###############\n\nMaxScanSize 150M\nMaxFileSize 100M\n# Match MaxFileSize so stream scans have the same ceiling as file scans\nStreamMaxLength 100M\nMaxRecursion 10\nMaxFiles 15000\nMaxEmbeddedPE 10M\nMaxHTMLNormalize 10M\nMaxHTMLNoTags 2M\nMaxScriptNormalize 5M\nMaxZipTypeRcg 1M\nMaxPartitions 128\nMaxIconsPE 200\nPCREMatchLimit 10000\nPCRERecMatchLimit 10000\n"` |  |
| clamav.extraVolumeMounts[0].mountPath | string | `"/var/lib/clamav"` |  |
| clamav.extraVolumeMounts[0].name | string | `"clamav-data"` |  |
| clamav.freshclamConfig | string | `"###############\n# General\n###############\n\nDatabaseDirectory /var/lib/clamav\nPidFile /tmp/freshclam.pid\n# CUSTOM: Set defined user\nDatabaseOwner 2000\n\n###############\n# Updates\n###############\n\nDatabaseMirror database.clamav.net\nScriptedUpdates yes\nNotifyClamd /etc/clamav/clamd.conf\nBytecode yes\n"` |  |
| clamav.fullnameOverride | string | `"clamav"` |  |
| clamav.image.repository | string | `"clamav/clamav"` |  |
| clamav.image.tag | string | `"1.5.4@sha256:0e85467cb0d6e7d860a45035707741cd5ffc032ffefc6002a3510c75b6d07027"` |  |
| clamav.metrics.enabled | bool | `false` |  |
| clamav.metrics.image.repository | string | `"docker.io/sergeymakinen/clamav_exporter"` |  |
| clamav.metrics.image.tag | string | `"v2.1.8@sha256:ac0e23e6b718f265f67de68d9fccbb8e9baccedeba19658fd78dd8a606508e24"` |  |
| clamav.metrics.serviceMonitor.enabled | bool | `false` |  |
| clamav.nameOverride | string | `"clamav"` |  |
| clamav.persistentVolume.enabled | bool | `true` |  |
| clamav.persistentVolume.size | string | `"2Gi"` |  |
| clamav.persistentVolume.storageClass | string | `"managed-csi"` |  |
| clamav.resources.limits.cpu | string | `"1000m"` |  |
| clamav.resources.limits.memory | string | `"3Gi"` |  |
| clamav.resources.requests.cpu | string | `"250m"` |  |
| clamav.resources.requests.memory | string | `"2Gi"` |  |
| clamav.startupProbe.failureThreshold | int | `9` |  |
| clamav.startupProbe.initialDelaySeconds | int | `60` |  |
| clamav.startupProbe.periodSeconds | int | `30` |  |
| clamav.startupProbe.timeoutSeconds | int | `5` |  |
| eck-operator.config.validateStorageClass | bool | `false` |  |
| eck-operator.createClusterScopedResources | bool | `false` |  |
| eck-operator.enabled | bool | `true` |  |
| eck-operator.installCRDs | bool | `true` | the chart installs and upgrades the 12 *.k8s.elastic.co CRDs, in lock-step with the operator version. The CRDs carry helm.sh/resource-policy: keep, so `helm uninstall` never removes them (the Elastic CRs and their data survive). Requires cluster-scope RBAC on the deploying identity. Clusters whose CRDs predate helm ownership (kisselastic era / manual apply) need a one-time adoption: deploy with `--take-ownership` (helm >= 3.17) or annotate the CRDs once — see docs/apps/elastic/migrating-to-eck-stack.md section 4b. Installers without cluster-scope RBAC: set false and apply the CRDs manually (same doc). override: values-enable-observability.yaml sets config.metricsPort and enables podMonitor |
| eck-operator.managedNamespaces[0] | string | `"podiumd"` |  |
| eck-operator.podMonitor.enabled | bool | `false` |  |
| eck-operator.webhook.enabled | bool | `false` |  |
| frankgateway.admin.adminKey | string | `""` |  |
| frankgateway.admin.viewerKey | string | `""` |  |
| frankgateway.apiKeys.envNames[0] | string | `"BAG_API_KEY"` |  |
| frankgateway.apiKeys.envNames[1] | string | `"KVK_API_KEY"` |  |
| frankgateway.apiKeys.existingSecret | string | `"frankgateway-api-keys"` |  |
| frankgateway.dashboard.adminPassword | string | `""` |  |
| frankgateway.dashboard.auth.dnsResolver | string | `"10.0.0.10"` |  |
| frankgateway.dashboard.auth.enabled | bool | `true` |  |
| frankgateway.dashboard.auth.hostname | string | `""` |  |
| frankgateway.dashboard.auth.oauth2Proxy.image.repository | string | `"quay.io/oauth2-proxy/oauth2-proxy"` |  |
| frankgateway.dashboard.auth.oauth2Proxy.image.tag | string | `"v7.7.1@sha256:f6a4aa83a27e316114bf79664302b1ffb2cc8ce697fb479273af4feb3fb16fe3"` |  |
| frankgateway.dashboard.auth.oauth2Proxy.nodeSelector | object | `{}` |  |
| frankgateway.dashboard.auth.oauth2Proxy.resources.limits.cpu | string | `"250m"` |  |
| frankgateway.dashboard.auth.oauth2Proxy.resources.limits.memory | string | `"256Mi"` |  |
| frankgateway.dashboard.auth.oauth2Proxy.resources.requests.cpu | string | `"25m"` |  |
| frankgateway.dashboard.auth.oauth2Proxy.resources.requests.memory | string | `"64Mi"` |  |
| frankgateway.dashboard.auth.sessionRedisUrl | string | `""` |  |
| frankgateway.dashboard.auth.shim.image.pullPolicy | string | `"IfNotPresent"` |  |
| frankgateway.dashboard.auth.shim.image.repository | string | `"nginxinc/nginx-unprivileged"` |  |
| frankgateway.dashboard.auth.shim.image.tag | string | `"1.31.4@sha256:197f252f060ed357f2ab98d4256762d7d107c76f18ad8f0b9d5178854611566d"` |  |
| frankgateway.dashboard.auth.shim.nodeSelector | object | `{}` |  |
| frankgateway.dashboard.auth.shim.resources.limits.cpu | string | `"250m"` |  |
| frankgateway.dashboard.auth.shim.resources.limits.memory | string | `"128Mi"` |  |
| frankgateway.dashboard.auth.shim.resources.requests.cpu | string | `"25m"` |  |
| frankgateway.dashboard.auth.shim.resources.requests.memory | string | `"32Mi"` |  |
| frankgateway.dashboard.enabled | bool | `true` |  |
| frankgateway.dashboard.image.repository | string | `"apache/apisix-dashboard"` |  |
| frankgateway.dashboard.image.tag | string | `"3.0.1-alpine@sha256:b5fafc11b76f998269375192ac33efc992d72aa69bfd7f3eb2ca377906cdbb6d"` |  |
| frankgateway.dashboard.ingress.clusterIssuer | string | `"letsencrypt-prod"` |  |
| frankgateway.dashboard.ingress.enabled | bool | `false` |  |
| frankgateway.dashboard.nodeSelector | object | `{}` |  |
| frankgateway.dashboard.resources.limits.cpu | string | `"500m"` |  |
| frankgateway.dashboard.resources.limits.memory | string | `"512Mi"` |  |
| frankgateway.dashboard.resources.requests.cpu | string | `"50m"` |  |
| frankgateway.dashboard.resources.requests.memory | string | `"128Mi"` |  |
| frankgateway.enabled | bool | `false` |  |
| frankgateway.etcd.image.repository | string | `"quay.io/coreos/etcd"` |  |
| frankgateway.etcd.image.tag | string | `"v3.5.16@sha256:d967d98a12dc220a1a290794711dba7eba04b8ce465e12b02383d1bfbb33e159"` |  |
| frankgateway.etcd.nodeSelector | object | `{}` |  |
| frankgateway.etcd.resources.limits.cpu | string | `"500m"` |  |
| frankgateway.etcd.resources.limits.memory | string | `"512Mi"` |  |
| frankgateway.etcd.resources.requests.cpu | string | `"50m"` |  |
| frankgateway.etcd.resources.requests.memory | string | `"128Mi"` |  |
| frankgateway.etcd.storage | string | `"2Gi"` |  |
| frankgateway.etcd.storageClassName | string | `""` |  |
| frankgateway.image.repository | string | `"ghcr.io/wearefrank/frank-gateway"` |  |
| frankgateway.image.tag | string | `"104@sha256:a830b90f8820f5cdb0c382ecef02a302c50d129edc9de81d7daa7af1cf267d98"` |  |
| frankgateway.metrics.enabled | bool | `false` |  |
| frankgateway.metrics.serviceMonitor.enabled | bool | `false` |  |
| frankgateway.metrics.serviceMonitor.interval | string | `"30s"` |  |
| frankgateway.nodeSelector | object | `{}` |  |
| frankgateway.replicas | int | `1` |  |
| frankgateway.resources.limits.cpu | string | `"1"` |  |
| frankgateway.resources.limits.memory | string | `"1Gi"` |  |
| frankgateway.resources.requests.cpu | string | `"100m"` |  |
| frankgateway.resources.requests.memory | string | `"256Mi"` |  |
| frankgateway.routes.job.backoffLimit | int | `3` |  |
| frankgateway.routes.job.image.pullPolicy | string | `"IfNotPresent"` |  |
| frankgateway.routes.job.image.repository | string | `"curlimages/curl"` |  |
| frankgateway.routes.job.image.tag | string | `"8.21.0@sha256:7c12af72ceb38b7432ab85e1a265cff6ae58e06f95539d539b654f2cfa64bb13"` |  |
| frankgateway.routes.job.nodeSelector | object | `{}` |  |
| frankgateway.routes.job.ttlSecondsAfterFinished | int | `600` |  |
| frankgateway.routes.seed | bool | `true` |  |
| frankgateway.tls.enabled | bool | `false` |  |
| frankgateway.tls.port | int | `9443` |  |
| global.configuration.enabled | bool | `true` |  |
| global.configuration.organization | string | `"Example gemeente"` |  |
| global.configuration.overwrite | bool | `true` |  |
| global.imageRegistry | string | `""` |  |
| global.images.busybox.pullPolicy | string | `"IfNotPresent"` |  |
| global.images.busybox.repository | string | `"library/busybox"` |  |
| global.images.busybox.tag | string | `"1.38.0-glibc@sha256:3ba030337caebbfc2232b22b1e435eb213b28e5844a34942c74555bf904a265a"` |  |
| global.images.curl.pullPolicy | string | `"IfNotPresent"` |  |
| global.images.curl.repository | string | `"curlimages/curl"` |  |
| global.images.curl.tag | string | `"8.21.0@sha256:7c12af72ceb38b7432ab85e1a265cff6ae58e06f95539d539b654f2cfa64bb13"` |  |
| global.images.nginx.pullPolicy | string | `"IfNotPresent"` |  |
| global.images.nginx.repository | string | `"nginxinc/nginx-unprivileged"` |  |
| global.images.nginx.tag | string | `"1.31.4@sha256:197f252f060ed357f2ab98d4256762d7d107c76f18ad8f0b9d5178854611566d"` |  |
| global.settings.databaseHost | string | `""` |  |
| ita.afdeling.type | string | `"https://ontw-objecttypen.example.nl/api/v2/objecttypes/REP_CONTACT_AFDELING_UUID_REP"` |  |
| ita.afdeling.typeVersion | int | `1` |  |
| ita.afdeling.uuid | string | `"REP_CONTACT_AFDELING_UUID_REP"` |  |
| ita.affinity | object | `{}` |  |
| ita.apiConnections.object.apiKey | string | `"REP_OBJECTEN_CREDENTIALS_ITA_TOKEN_REP"` |  |
| ita.apiConnections.object.baseUrl | string | `"https://objecten.example.nl/api/v2/"` |  |
| ita.apiConnections.openKlant.apiKey | string | `"REP_OPENKLANT_CREDENTIALS_ITA_TOKEN_REP"` |  |
| ita.apiConnections.openKlant.baseUrl | string | `"https://openklant.example.nl/klantinteracties/api/v1/"` |  |
| ita.apiConnections.zaakSysteem.baseUrl | string | `"https://openzaak.example.nl"` |  |
| ita.apiConnections.zaakSysteem.clientId | string | `"ita"` |  |
| ita.apiConnections.zaakSysteem.key | string | `"REP_OPENZAAK_CREDENTIALS_ITA_SECRET_REP"` |  |
| ita.database.host | string | `"REP_ITA_DATABASE_HOST_REP"` |  |
| ita.database.name | string | `"ita"` |  |
| ita.database.password | string | `"REP_ITA_DATABASE_PASSWORD_REP"` |  |
| ita.database.port | string | `"5432"` |  |
| ita.database.username | string | `"ita"` |  |
| ita.enabled | bool | `true` |  |
| ita.fullnameOverride | string | `"ita"` |  |
| ita.groep.type | string | `"https://ontw-objecttypen.example.nl/api/v2/objecttypes/REP_CONTACT_GROEP_UUID_REP"` |  |
| ita.groep.typeVersion | int | `1` |  |
| ita.groep.uuid | string | `"REP_CONTACT_GROEP_UUID_REP"` |  |
| ita.imagePullSecrets | list | `[]` |  |
| ita.ingress.enabled | bool | `false` |  |
| ita.ita.baseUrl | string | `"https://ita.example.nl"` |  |
| ita.logboek.type | string | `"https://ontw-objecttypen.example.nl/api/v2/objecttypes/REP_ITA_ACTIVITEITENLOG_UUID_REP"` |  |
| ita.logboek.typeVersion | int | `1` |  |
| ita.medewerker.type | string | `"https://ontw-objecttypen.example.nl/api/v2/objecttypes/REP_CONTACT_MEDEWERKER_UUID_REP"` |  |
| ita.medewerker.typeVersion | int | `1` |  |
| ita.medewerker.uuid | string | `"REP_CONTACT_MEDEWERKER_UUID_REP"` |  |
| ita.nameOverride | string | `""` |  |
| ita.nieuweInternetaakNotificatie | object | `{"notification":{"pollerMessage":"Poller uitgevoerd om:"},"schedule":"*/15 * * * *"}` | CronJob die behandelaars waarschuwt bij een nieuwe internetaak. Was tot 3.2.0 de enige poller; schedule en notification stonden toen onder ita.poller. Omgevingen die die sleutels overschrijven moeten ze hierheen verplaatsen, anders vallen ze stil terug op de chart-defaults. poller.notification.hourThreshold is niet meer aanwezig in subchart, dus verwijderd. |
| ita.nodeSelector | object | `{}` |  |
| ita.poller | object | `{"image":{"pullPolicy":"IfNotPresent","repository":"ghcr.io/interne-taak-afhandeling/internetaakafhandeling.poller","tag":"3.3.0@sha256:7690650687047c43f08c4f8320b77d821d3551d18478de9a600a2f828600c865"},"resources":{"limits":{"cpu":"100m","memory":"256Mi"},"requests":{"cpu":"50m","memory":"128Mi"}}}` | ITA 3.3.0 splitste de poller in twee CronJobs, elk met een eigen POLLER_MODE. Dit blok levert alleen nog het image en de resources die ze allebei gebruiken; schedule en notification zijn verhuisd naar nieuweInternetaakNotificatie hieronder. |
| ita.postgresql.enabled | bool | `false` |  |
| ita.replicaCount | int | `1` |  |
| ita.smtp.enableSsl | string | `"true"` |  |
| ita.smtp.fromEmail | string | `""` |  |
| ita.smtp.host | string | `"mail.example.nl"` |  |
| ita.smtp.password | string | `""` |  |
| ita.smtp.port | string | `"587"` |  |
| ita.smtp.username | string | `""` |  |
| ita.tolerations | list | `[]` |  |
| ita.verlopenContactverzoekHerinneringNotificatie | object | `{"enabled":true,"schedule":"0 7 * * 1-5"}` | Nieuw in ITA 3.3.0: dagelijkse herinnering voor verlopen contactverzoeken, op werkdagen om 07:00. |
| ita.web.image.pullPolicy | string | `"IfNotPresent"` |  |
| ita.web.image.tag | string | `"3.3.0@sha256:cb56b4809e0c840cbc72814f8a72495fd18860cb08dfb092c12ba3c2cea785df"` |  |
| ita.web.oidc.authority | string | `"REP_ITA_OIDC_AUTHORITY_REP"` |  |
| ita.web.oidc.clientId | string | `"ita"` |  |
| ita.web.oidc.clientSecret | string | `"REP_ITA_OIDC_CLIENT_SECRET_REP"` |  |
| ita.web.oidc.emailClaimType | string | `"email"` |  |
| ita.web.oidc.frontendUrl | string | `"REP_ITA_OIDC_FRONTEND_URL_REP"` |  |
| ita.web.oidc.functioneelBeheerderRole | string | `"ITA_Functioneel_Beheerder"` |  |
| ita.web.oidc.itaSystemAccessRole | string | `"ITA_Gebruiker"` |  |
| ita.web.oidc.nameClaimType | string | `"name"` |  |
| ita.web.oidc.objectregisterMedewerkerIdClaimType | string | `"samaccountname"` |  |
| ita.web.oidc.pkceEnabled | bool | `false` | Enable PKCE (S256) on the Keycloak client for ITA. ITA is a JS frontend; the upstream chart has no app-side PKCE toggle. PKCE support depends on the OIDC client library used by the application. |
| ita.web.oidc.roleClaimType | string | `"roles"` |  |
| ita.web.resources.limits.cpu | string | `"200m"` |  |
| ita.web.resources.limits.memory | string | `"256Mi"` |  |
| ita.web.resources.requests.cpu | string | `"100m"` |  |
| ita.web.resources.requests.memory | string | `"128Mi"` |  |
| ita.web.service.port | int | `80` |  |
| ita.web.service.type | string | `"ClusterIP"` |  |
| keycloak-operator.enableServiceMonitor | bool | `false` |  |
| keycloak-operator.enabled | bool | `true` |  |
| keycloak-operator.fullnameOverride | string | `"keycloak"` |  |
| keycloak-operator.jobs.configCliResources | object | `{"limits":{"cpu":"200m","memory":"512Mi"},"requests":{"cpu":"50m","memory":"256Mi"}}` | Resources for the kc-config-cli containers (Spring Boot JVM app) in import-podiumd-realm and import-master-realm jobs. |
| keycloak-operator.jobs.ensureOperatorSa.clientSecret | string | `""` |  |
| keycloak-operator.jobs.ensureOperatorSa.enabled | bool | `true` |  |
| keycloak-operator.jobs.ensureOperatorSa.image.pullPolicy | string | `"IfNotPresent"` |  |
| keycloak-operator.jobs.ensureOperatorSa.image.repository | string | `"curlimages/curl"` |  |
| keycloak-operator.jobs.ensureOperatorSa.image.tag | string | `"8.21.0@sha256:7c12af72ceb38b7432ab85e1a265cff6ae58e06f95539d539b654f2cfa64bb13"` |  |
| keycloak-operator.jobs.ensurePodiumdAdminUser.enabled | bool | `true` |  |
| keycloak-operator.jobs.ensurePodiumdAdminUser.image.registry | string | `""` |  |
| keycloak-operator.jobs.ensurePodiumdAdminUser.image.repository | string | `"postgres"` |  |
| keycloak-operator.jobs.ensurePodiumdAdminUser.image.tag | string | `"16@sha256:c1b3783309b6499c795eed7c20135a1a4d25cae1b575c3d52c6f536129a1b109"` |  |
| keycloak-operator.jobs.ensurePodiumdAdminUser.initImage.registry | string | `""` |  |
| keycloak-operator.jobs.ensurePodiumdAdminUser.initImage.repository | string | `"python"` |  |
| keycloak-operator.jobs.ensurePodiumdAdminUser.initImage.tag | string | `"3.14.7-slim@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83"` |  |
| keycloak-operator.jobs.importMasterRealm.enabled | bool | `true` |  |
| keycloak-operator.jobs.importPodiumdRealm.enabled | bool | `true` |  |
| keycloak-operator.jobs.keycloakUrl | string | `""` | Keycloak URL used by the realm-import jobs (keycloak-config-cli). Empty = in-cluster service (http://keycloak-service:8080). Set only when the jobs must reach Keycloak via another URL; note the public admin host can sit behind a gateway IP-allowlist that blocks cluster egress (403). |
| keycloak-operator.jobs.resources | object | `{"limits":{"cpu":"200m","memory":"128Mi"},"requests":{"cpu":"50m","memory":"64Mi"}}` | Resources applied to lightweight keycloak job containers (curl, python, psql): ensure-operator-sa, ensure-podiumd-admin-user. |
| keycloak-operator.operator.config.keycloakImage.repository | string | `"quay.io/keycloak/keycloak"` |  |
| keycloak-operator.operator.config.keycloakImage.sha | string | `"831330513f55695572286e521f94fcd3c7e285250ed5b848090265a33192f669"` |  |
| keycloak-operator.operator.config.keycloakImage.tag | string | `"26.7.2"` |  |
| keycloak-operator.operator.image.repository | string | `"quay.io/keycloak/keycloak-operator"` |  |
| keycloak-operator.operator.image.tag | string | `"26.6.4"` |  |
| keycloak-operator.operator.resources.limits.cpu | string | `"500m"` |  |
| keycloak-operator.operator.resources.limits.memory | string | `"768Mi"` |  |
| keycloak-operator.operator.resources.requests.cpu | string | `"100m"` |  |
| keycloak-operator.operator.resources.requests.memory | string | `"128Mi"` |  |
| keycloak-operator.serviceAccount.create | bool | `false` |  |
| keycloak.additionalOptions[0].name | string | `"health-enabled"` |  |
| keycloak.additionalOptions[0].value | string | `"true"` |  |
| keycloak.additionalOptions[1].name | string | `"metrics-enabled"` |  |
| keycloak.additionalOptions[1].value | string | `"true"` |  |
| keycloak.additionalOptions[2].name | string | `"cache"` |  |
| keycloak.additionalOptions[2].value | string | `"ispn"` |  |
| keycloak.additionalOptions[3].name | string | `"cache-stack"` |  |
| keycloak.additionalOptions[3].value | string | `""` |  |
| keycloak.auth.adminPassword | string | `""` |  |
| keycloak.auth.adminUser | string | `"admin"` |  |
| keycloak.config.accessTokenLifespan | int | `60` |  |
| keycloak.config.adminFrontendUrl | string | `"https://keycloak-admin.example.nl"` |  |
| keycloak.config.clients.datamigratie.enabled | bool | `true` |  |
| keycloak.config.clients.datamigratie.name | string | `"Datamigratie"` |  |
| keycloak.config.clients.datamigratie.oidcUrl | string | `"https://datamigratie.example.nl"` |  |
| keycloak.config.clients.datamigratie.secret | string | `""` |  |
| keycloak.config.clients.monitoring.enabled | bool | `true` |  |
| keycloak.config.clients.monitoring.name | string | `"Monitoring (Grafana)"` |  |
| keycloak.config.clients.monitoring.oidcUrl | string | `"https://monitoring.example.nl"` |  |
| keycloak.config.clients.monitoring.secret | string | `""` |  |
| keycloak.config.clients.zaakbrug.enabled | bool | `true` |  |
| keycloak.config.clients.zaakbrug.name | string | `"Zaakbrug Frank!Framework console"` |  |
| keycloak.config.clients.zaakbrug.oidcUrl | string | `"https://zaakbrug.example.nl"` |  |
| keycloak.config.clients.zaakbrug.secret | string | `""` |  |
| keycloak.config.realm | string | `"podiumd"` | identity provider mapper for the admin realm adminIdentityProviderMappers: {} |
| keycloak.config.realmDisplayName | string | `"PodiumD"` |  |
| keycloak.config.realmFrontendUrl | string | `"https://keycloak.example.nl"` |  |
| keycloak.config.skipGroups | bool | `true` |  |
| keycloak.config.skipRoles | bool | `true` |  |
| keycloak.config.smtp.from | string | `"noreply@example.nl"` |  |
| keycloak.config.smtp.fromDisplayName | string | `"Example Gemeente"` |  |
| keycloak.config.smtp.port | string | `"587"` |  |
| keycloak.config.smtp.server | string | `"mail.example.nl"` |  |
| keycloak.config.smtp.ssl | string | `"false"` |  |
| keycloak.config.smtp.starttls | string | `"true"` |  |
| keycloak.db | object | `{"database":"","host":"","passwordSecret":{"key":"","name":""},"port":"","usernameSecret":{"key":"","name":""},"vendor":""}` | db uses the new keycloak-operator CRD structure (falls back to externalDatabase.*) |
| keycloak.externalDatabase.database | string | `""` |  |
| keycloak.externalDatabase.host | string | `"postgres"` |  |
| keycloak.externalDatabase.password | string | `""` |  |
| keycloak.externalDatabase.port | int | `5432` |  |
| keycloak.externalDatabase.user | string | `""` |  |
| keycloak.externalDatabase.vendor | string | `"postgres"` |  |
| keycloak.features.enabled | list | `[]` |  |
| keycloak.hostname | object | `{"admin":"","hostname":""}` | new hostname configuration for keycloak-operator, falls back to config.adminFrontendUrl if not defined |
| keycloak.http.httpEnabled | bool | `true` |  |
| keycloak.image.registry | string | `""` |  |
| keycloak.image.repository | string | `"quay.io/keycloak/keycloak"` |  |
| keycloak.image.tag | string | `"26.7.2@sha256:831330513f55695572286e521f94fcd3c7e285250ed5b848090265a33192f669"` |  |
| keycloak.ingress.enabled | bool | `false` |  |
| keycloak.instances | string | `"2"` | instances is the new operator-style replica count (falls back to replicaCount) |
| keycloak.keycloakConfigCli.image.registry | string | `""` |  |
| keycloak.keycloakConfigCli.image.repository | string | `"adorsys/keycloak-config-cli"` |  |
| keycloak.keycloakConfigCli.image.tag | string | `"6.5.1-26@sha256:1b22dfaa9ae0c71f74b0342f9221a6510f272da5def683dbba26a98e6b1b1411"` |  |
| keycloak.name | string | `"keycloak"` |  |
| keycloak.podTemplate.metadata.labels.app | string | `"keycloak"` |  |
| keycloak.podTemplate.metadata.labels.version | string | `"26.6.4"` |  |
| keycloak.podTemplate.spec.affinity.podAntiAffinity.preferredDuringSchedulingIgnoredDuringExecution[0].podAffinityTerm.labelSelector.matchExpressions[0].key | string | `"app"` |  |
| keycloak.podTemplate.spec.affinity.podAntiAffinity.preferredDuringSchedulingIgnoredDuringExecution[0].podAffinityTerm.labelSelector.matchExpressions[0].operator | string | `"In"` |  |
| keycloak.podTemplate.spec.affinity.podAntiAffinity.preferredDuringSchedulingIgnoredDuringExecution[0].podAffinityTerm.labelSelector.matchExpressions[0].values[0] | string | `"keycloak"` |  |
| keycloak.podTemplate.spec.affinity.podAntiAffinity.preferredDuringSchedulingIgnoredDuringExecution[0].podAffinityTerm.topologyKey | string | `"kubernetes.io/hostname"` |  |
| keycloak.podTemplate.spec.affinity.podAntiAffinity.preferredDuringSchedulingIgnoredDuringExecution[0].weight | int | `100` |  |
| keycloak.podTemplate.spec.containers[0].livenessProbe.failureThreshold | int | `5` |  |
| keycloak.podTemplate.spec.containers[0].livenessProbe.httpGet.path | string | `"/health/live"` |  |
| keycloak.podTemplate.spec.containers[0].livenessProbe.httpGet.port | int | `9000` |  |
| keycloak.podTemplate.spec.containers[0].livenessProbe.httpGet.scheme | string | `"HTTP"` |  |
| keycloak.podTemplate.spec.containers[0].livenessProbe.initialDelaySeconds | int | `120` |  |
| keycloak.podTemplate.spec.containers[0].livenessProbe.periodSeconds | int | `30` |  |
| keycloak.podTemplate.spec.containers[0].livenessProbe.timeoutSeconds | int | `5` |  |
| keycloak.podTemplate.spec.containers[0].name | string | `"keycloak"` |  |
| keycloak.podTemplate.spec.containers[0].readinessProbe.failureThreshold | int | `3` |  |
| keycloak.podTemplate.spec.containers[0].readinessProbe.httpGet.path | string | `"/health/ready"` |  |
| keycloak.podTemplate.spec.containers[0].readinessProbe.httpGet.port | int | `9000` |  |
| keycloak.podTemplate.spec.containers[0].readinessProbe.httpGet.scheme | string | `"HTTP"` |  |
| keycloak.podTemplate.spec.containers[0].readinessProbe.initialDelaySeconds | int | `60` |  |
| keycloak.podTemplate.spec.containers[0].readinessProbe.periodSeconds | int | `10` |  |
| keycloak.podTemplate.spec.containers[0].readinessProbe.timeoutSeconds | int | `5` |  |
| keycloak.podTemplate.spec.containers[0].resources.limits.cpu | string | `"1000m"` |  |
| keycloak.podTemplate.spec.containers[0].resources.limits.memory | string | `"1Gi"` |  |
| keycloak.podTemplate.spec.containers[0].resources.requests.cpu | string | `"250m"` |  |
| keycloak.podTemplate.spec.containers[0].resources.requests.memory | string | `"512Mi"` |  |
| keycloak.podTemplate.spec.containers[0].securityContext.allowPrivilegeEscalation | bool | `false` |  |
| keycloak.podTemplate.spec.containers[0].securityContext.capabilities.drop[0] | string | `"ALL"` |  |
| keycloak.podTemplate.spec.containers[0].securityContext.runAsNonRoot | bool | `true` |  |
| keycloak.podTemplate.spec.containers[0].securityContext.runAsUser | int | `1000` |  |
| keycloak.podTemplate.spec.containers[0].securityContext.seccompProfile.type | string | `"RuntimeDefault"` |  |
| keycloak.podTemplate.spec.containers[0].startupProbe.failureThreshold | int | `30` |  |
| keycloak.podTemplate.spec.containers[0].startupProbe.httpGet.path | string | `"/health/started"` |  |
| keycloak.podTemplate.spec.containers[0].startupProbe.httpGet.port | int | `9000` |  |
| keycloak.podTemplate.spec.containers[0].startupProbe.httpGet.scheme | string | `"HTTP"` |  |
| keycloak.podTemplate.spec.containers[0].startupProbe.initialDelaySeconds | int | `30` |  |
| keycloak.podTemplate.spec.containers[0].startupProbe.periodSeconds | int | `10` |  |
| keycloak.podTemplate.spec.containers[0].startupProbe.timeoutSeconds | int | `5` |  |
| keycloak.podTemplate.spec.containers[0].volumeMounts[0].mountPath | string | `"/opt/keycloak/lib/quarkus"` |  |
| keycloak.podTemplate.spec.containers[0].volumeMounts[0].name | string | `"keycloak-build-data"` |  |
| keycloak.podTemplate.spec.containers[0].volumeMounts[0].subPath | string | `"quarkus"` |  |
| keycloak.podTemplate.spec.containers[0].volumeMounts[1].mountPath | string | `"/opt/keycloak/providers"` |  |
| keycloak.podTemplate.spec.containers[0].volumeMounts[1].name | string | `"keycloak-build-data"` |  |
| keycloak.podTemplate.spec.containers[0].volumeMounts[1].subPath | string | `"providers"` |  |
| keycloak.podTemplate.spec.initContainers[0].command[0] | string | `"/bin/bash"` |  |
| keycloak.podTemplate.spec.initContainers[0].command[1] | string | `"-c"` |  |
| keycloak.podTemplate.spec.initContainers[0].command[2] | string | `"set -e\nexport KC_DB=postgres\nexport KC_PROXY_HEADERS=xforwarded\nexport KC_CACHE=ispn\nexport KC_METRICS_ENABLED=true\nexport KC_HEALTH_ENABLED=true\n/opt/keycloak/bin/kc.sh build\nrm -rf /opt/keycloak/build/quarkus /opt/keycloak/build/providers\nmkdir -p /opt/keycloak/build/quarkus /opt/keycloak/build/providers\ncp -a /opt/keycloak/lib/quarkus/. /opt/keycloak/build/quarkus/\ncp -a /opt/keycloak/providers/. /opt/keycloak/build/providers/ 2>/dev/null || true\n"` |  |
| keycloak.podTemplate.spec.initContainers[0].name | string | `"keycloak-builder"` |  |
| keycloak.podTemplate.spec.initContainers[0].resources.limits.cpu | string | `"1000m"` |  |
| keycloak.podTemplate.spec.initContainers[0].resources.limits.memory | string | `"1Gi"` |  |
| keycloak.podTemplate.spec.initContainers[0].resources.requests.cpu | string | `"250m"` |  |
| keycloak.podTemplate.spec.initContainers[0].resources.requests.memory | string | `"512Mi"` |  |
| keycloak.podTemplate.spec.initContainers[0].securityContext.allowPrivilegeEscalation | bool | `false` |  |
| keycloak.podTemplate.spec.initContainers[0].securityContext.capabilities.drop[0] | string | `"ALL"` |  |
| keycloak.podTemplate.spec.initContainers[0].securityContext.runAsNonRoot | bool | `true` |  |
| keycloak.podTemplate.spec.initContainers[0].securityContext.runAsUser | int | `1000` |  |
| keycloak.podTemplate.spec.initContainers[0].securityContext.seccompProfile.type | string | `"RuntimeDefault"` |  |
| keycloak.podTemplate.spec.initContainers[0].volumeMounts[0].mountPath | string | `"/opt/keycloak/build"` |  |
| keycloak.podTemplate.spec.initContainers[0].volumeMounts[0].name | string | `"keycloak-build-data"` |  |
| keycloak.podTemplate.spec.initContainers[0].volumeMounts[0].subPath | string | `""` |  |
| keycloak.podTemplate.spec.securityContext.fsGroup | int | `1000` |  |
| keycloak.podTemplate.spec.securityContext.runAsNonRoot | bool | `true` |  |
| keycloak.podTemplate.spec.securityContext.runAsUser | int | `1000` |  |
| keycloak.podTemplate.spec.securityContext.seccompProfile.type | string | `"RuntimeDefault"` |  |
| keycloak.podTemplate.spec.volumes[0].emptyDir | object | `{}` |  |
| keycloak.podTemplate.spec.volumes[0].name | string | `"keycloak-build-data"` |  |
| keycloak.proxy | object | `{"headers":"xforwarded"}` | new keycloak entrypoint configuration, falls back to proxyHeaders if headers is not set |
| keycloak.resources.limits.cpu | string | `"1000m"` |  |
| keycloak.resources.limits.memory | string | `"2Gi"` |  |
| keycloak.resources.requests.cpu | string | `"500m"` |  |
| keycloak.resources.requests.memory | string | `"1700Mi"` |  |
| keycloak.secretsName | string | `"keycloak-secrets"` |  |
| kiss-eck.eck-elasticsearch.enabled | bool | `true` |  |
| kiss-eck.eck-elasticsearch.fullnameOverride | string | `"kiss"` |  |
| kiss-eck.eck-elasticsearch.nodeSets | list | `[{"config":{"node.roles":["data","ingest","master"],"node.store.allow_mmap":false},"count":3,"name":"default","podTemplate":{"spec":{"nodeSelector":{}}}}]` | default sizing, kept equal to the previous release (kiss-elastic used elasticsearchCount: 3). Environments can override nodeSets (e.g. nodeSelector, count, storage), the same way openinwoner.eck-elasticsearch.nodeSets is set. Note: volumeClaimTemplates is immutable — during a migration keep it equal to the existing PVCs; changing the size needs a manual recreate (see docs/apps/elastic/migrating-to-eck-stack.md). |
| kiss-eck.eck-elasticsearch.version | string | `"8.19.19"` |  |
| kiss-eck.eck-enterprise-search | object | `{"config":{"app_search.engine.total_fields.limit":1000,"connector.crawler.crawl.threads.limit":1,"connector.crawler.http.user_agent":"PodiumD-Contact-Elastic-Crawler","connector.crawler.workers.pool_size.limit":1,"kibana.host":"https://kiss-kb-http.podiumd.svc.cluster.local:5601"},"count":1,"elasticsearchRef":{"name":"kiss"},"enabled":false,"fullnameOverride":"kiss","podTemplate":{"spec":{"nodeSelector":{}}},"version":"8.19.19"}` | Uit sinds KISS 3.0.0. KISS bevraagt de Elasticsearch-indices rechtstreeks en crawlt met de Elastic Open Crawler, dus Enterprise Search wordt nergens meer voor gebruikt. De connector.crawler-instellingen hieronder waren voor de oude crawler; die zitten nu per site onder kiss.settings.syncJobs.website. Relevance- en precision-tuning gebeurde in Kibana en werd in Enterprise Search opgeslagen; dat had al geen effect meer, KISS 3.0.0 gebruikt vast precision 6. Aanzetten kan nog, maar levert alleen een ongebruikte pod op. |
| kiss-eck.eck-kibana.config."server.publicBaseUrl" | string | `"https://kiss-kb-http.podiumd.svc.cluster.local:5601"` |  |
| kiss-eck.eck-kibana.elasticsearchRef.name | string | `"kiss"` |  |
| kiss-eck.eck-kibana.enabled | bool | `true` |  |
| kiss-eck.eck-kibana.fullnameOverride | string | `"kiss"` |  |
| kiss-eck.eck-kibana.podTemplate.spec.nodeSelector | object | `{}` |  |
| kiss-eck.eck-kibana.version | string | `"8.19.19"` |  |
| kiss-eck.enabled | bool | `true` |  |
| kiss.adapter.baseUrl | string | `""` |  |
| kiss.adapter.clientId | string | `"kiss_intern"` |  |
| kiss.adapter.esuite.baseUrl | string | `""` |  |
| kiss.adapter.esuite.clientId | string | `"<kiss>"` |  |
| kiss.adapter.esuite.contactverzoektypen | list | `[]` |  |
| kiss.adapter.esuite.isDefault | bool | `true` |  |
| kiss.adapter.esuite.secret | string | `""` |  |
| kiss.adapter.extraEnvVars | list | `[]` | Optionally specify extra list of additional environment variables. |
| kiss.adapter.extraVolumeMounts | list | `[]` | Optionally specify extra list of additional volumeMounts, for example to trust extra ca certificates. |
| kiss.adapter.extraVolumes | list | `[]` | Optionally specify extra list of additional volumes, for example to trust extra ca certificates. |
| kiss.adapter.image.pullPolicy | string | `"IfNotPresent"` |  |
| kiss.adapter.image.tag | string | `"0.6.7@sha256:089d07a6efdfcab07b61b1a75b4d26c14099cc9b206a56419e36ef6f28a26a68"` |  |
| kiss.adapter.objecten.baseUrl | string | `""` |  |
| kiss.adapter.objecten.token | string | `""` |  |
| kiss.adapter.objecttypen.afdelingUUID | string | `""` |  |
| kiss.adapter.objecttypen.baseUrlExtern | string | `""` |  |
| kiss.adapter.objecttypen.baseUrlIntern | string | `""` |  |
| kiss.adapter.objecttypen.groepUUID | string | `""` |  |
| kiss.adapter.objecttypen.interneTaakUUID | string | `""` |  |
| kiss.adapter.objecttypen.kennisartikelUUID | string | `""` |  |
| kiss.adapter.objecttypen.medewerkerUUID | string | `""` |  |
| kiss.adapter.objecttypen.token | string | `""` |  |
| kiss.adapter.objecttypen.vacUUID | string | `""` |  |
| kiss.adapter.resources.limits.cpu | string | `"200m"` |  |
| kiss.adapter.resources.limits.memory | string | `"256Mi"` |  |
| kiss.adapter.resources.requests.cpu | string | `"10m"` |  |
| kiss.adapter.resources.requests.memory | string | `"100Mi"` |  |
| kiss.adapter.secret | string | `""` |  |
| kiss.configuration.oidcSecret | string | `"<kiss>"` |  |
| kiss.configuration.oidcUrl | string | `"https://kiss.example.nl"` |  |
| kiss.enabled | bool | `true` |  |
| kiss.extraEnvVars | list | `[]` | Optionally specify extra list of additional environment variables. Not necesarry for KvK / BRP headers, use the settings for these |
| kiss.extraVolumeMounts | list | `[]` | Optionally specify extra list of additional volumeMounts, for example to trust extra ca certificates. |
| kiss.extraVolumes | list | `[]` | Optionally specify extra list of additional volumes, for example to trust extra ca certificates. |
| kiss.fullnameOverride | string | `"contact"` |  |
| kiss.image.pullPolicy | string | `"IfNotPresent"` |  |
| kiss.image.tag | string | `"3.0.0@sha256:56a9c225d9fb19184ee9ad6c84877e7b5853c280cbb5e0d59edb340c7bb8599c"` |  |
| kiss.imagePullSecrets | list | `[]` |  |
| kiss.nameOverride | string | `"contact"` |  |
| kiss.nodeSelector | object | `{}` |  |
| kiss.resources.requests.cpu | string | `"100m"` |  |
| kiss.resources.requests.memory | string | `"256Mi"` |  |
| kiss.settings.afdelingen.baseUrl | string | `""` |  |
| kiss.settings.afdelingen.objectTypeUrl | string | `""` |  |
| kiss.settings.afdelingen.token | string | `""` |  |
| kiss.settings.database.host | string | `""` |  |
| kiss.settings.database.name | string | `""` |  |
| kiss.settings.database.password | string | `""` |  |
| kiss.settings.database.port | int | `5432` |  |
| kiss.settings.database.username | string | `""` |  |
| kiss.settings.elastic.baseUrl | string | `""` |  |
| kiss.settings.elastic.excludedFieldsKennisbank | list | `[]` |  |
| kiss.settings.elastic.password | string | `""` |  |
| kiss.settings.elastic.username | string | `"elastic"` |  |
| kiss.settings.email.enableSsl | bool | `true` |  |
| kiss.settings.email.host | string | `""` |  |
| kiss.settings.email.password | string | `""` |  |
| kiss.settings.email.port | int | `587` |  |
| kiss.settings.email.username | string | `""` |  |
| kiss.settings.feedback.emailFrom | string | `""` |  |
| kiss.settings.feedback.emailTo | string | `""` |  |
| kiss.settings.groepen.baseUrl | string | `""` |  |
| kiss.settings.groepen.objectTypeUrl | string | `""` |  |
| kiss.settings.groepen.token | string | `""` |  |
| kiss.settings.haalCentraal.apiKey | string | `""` |  |
| kiss.settings.haalCentraal.baseUrl | string | `""` |  |
| kiss.settings.kvk.apiKey | string | `""` |  |
| kiss.settings.kvk.baseUrl | string | `""` |  |
| kiss.settings.logboek.baseUrl | string | `""` |  |
| kiss.settings.logboek.objectTypeUrl | string | `""` |  |
| kiss.settings.logboek.objectTypeVersion | int | `1` |  |
| kiss.settings.logboek.token | string | `""` |  |
| kiss.settings.managementInformatie.apiKey | string | `""` |  |
| kiss.settings.oidc.authority | string | `""` |  |
| kiss.settings.oidc.beheerderRole | string | `"Beheerder"` |  |
| kiss.settings.oidc.clientId | string | `"kiss"` |  |
| kiss.settings.oidc.clientSecret | string | `"<kiss>"` |  |
| kiss.settings.oidc.kennisbankRole | string | `"Kennisbank"` |  |
| kiss.settings.oidc.klantcontactmedewerkerRole | string | `"Klantcontactmedewerker"` | Rolnamen zoals ze in de podiumd-realm staan (client kiss). KISS 3.0.0 splitst de redacteursrol in REDACTEUR en BEHEERDER; de realm-config in templates/keycloak-podiumd-realm-config.yaml levert beide rollen. |
| kiss.settings.oidc.medewerkerIdentificatie.claim | string | `"samaccountname"` |  |
| kiss.settings.oidc.medewerkerIdentificatie.truncate | string | `nil` |  |
| kiss.settings.oidc.pkceEnabled | bool | `false` | Enable PKCE (S256) on the Keycloak client for KISS. KISS is a React frontend; the OIDC client library must support PKCE. |
| kiss.settings.oidc.redacteurRole | string | `"Redacteur"` |  |
| kiss.settings.organisatieIds | list | `[]` |  |
| kiss.settings.registers | list | `[]` |  |
| kiss.settings.syncJobs.crawlerImage | object | `{"pullPolicy":"IfNotPresent","repository":"docker.elastic.co/integrations/crawler","tag":"1.0.0@sha256:6f3c02f6c783711b8d9e133cf10934b137d6547dc1eb10a0d2ccf99ffe2e2d07"}` | Elastic Open Crawler, vervangt de Enterprise Search web crawler. Draait als CronJob per site uit syncJobs.website en schrijft rechtstreeks naar Elasticsearch. |
| kiss.settings.syncJobs.image.pullPolicy | string | `"IfNotPresent"` |  |
| kiss.settings.syncJobs.image.tag | string | `"3.0.0@sha256:64d56ff3039b71806d7d03ecfcd37cede2d31c4146fe4e06d9de6f526415fffb"` |  |
| kiss.settings.syncJobs.indexTemplateImage | object | `{"pullPolicy":"IfNotPresent","repository":"curlimages/curl","tag":"8.21.0@sha256:7c12af72ceb38b7432ab85e1a265cff6ae58e06f95539d539b654f2cfa64bb13"}` | pre-install/pre-upgrade hook die het search-website* index-template in Elasticsearch registreert. Heeft alleen curl nodig. |
| kiss.settings.syncJobs.kennisbank.baseUrl | string | `""` |  |
| kiss.settings.syncJobs.kennisbank.historyLimit | int | `1` |  |
| kiss.settings.syncJobs.kennisbank.objectTypeUrl | string | `""` |  |
| kiss.settings.syncJobs.kennisbank.resources.requests.cpu | string | `"50m"` |  |
| kiss.settings.syncJobs.kennisbank.resources.requests.memory | string | `"128Mi"` |  |
| kiss.settings.syncJobs.kennisbank.schedule | string | `"*/59 * * * *"` |  |
| kiss.settings.syncJobs.kennisbank.token | string | `""` |  |
| kiss.settings.syncJobs.medewerkers.baseUrl | string | `""` |  |
| kiss.settings.syncJobs.medewerkers.clientId | string | `""` |  |
| kiss.settings.syncJobs.medewerkers.clientSecret | string | `""` |  |
| kiss.settings.syncJobs.medewerkers.historyLimit | int | `1` |  |
| kiss.settings.syncJobs.medewerkers.objectTypeUrl | string | `""` |  |
| kiss.settings.syncJobs.medewerkers.resources.requests.cpu | string | `"50m"` |  |
| kiss.settings.syncJobs.medewerkers.resources.requests.memory | string | `"128Mi"` |  |
| kiss.settings.syncJobs.medewerkers.schedule | string | `"*/59 * * * *"` |  |
| kiss.settings.syncJobs.sharepoint | list | `[]` |  |
| kiss.settings.syncJobs.vac.baseUrl | string | `""` |  |
| kiss.settings.syncJobs.vac.historyLimit | int | `1` |  |
| kiss.settings.syncJobs.vac.manageFromKiss | bool | `false` |  |
| kiss.settings.syncJobs.vac.objectTypeUrl | string | `""` |  |
| kiss.settings.syncJobs.vac.objectTypeVersion | int | `1` |  |
| kiss.settings.syncJobs.vac.resources.requests.cpu | string | `"50m"` |  |
| kiss.settings.syncJobs.vac.resources.requests.memory | string | `"128Mi"` |  |
| kiss.settings.syncJobs.vac.schedule | string | `"*/59 * * * *"` |  |
| kiss.settings.syncJobs.vac.token | string | `""` |  |
| kiss.settings.syncJobs.website | list | `[]` |  |
| mi.enabled | bool | `false` |  |
| objecten.configuration.data | string | `""` |  |
| objecten.configuration.demo.enabled | bool | `false` |  |
| objecten.configuration.enabled | bool | `true` |  |
| objecten.configuration.initContainer.enabled | bool | `false` |  |
| objecten.configuration.job.backoffLimit | int | `6` |  |
| objecten.configuration.job.enabled | bool | `true` |  |
| objecten.configuration.job.resources | object | `{}` |  |
| objecten.configuration.job.restartPolicy | string | `"OnFailure"` |  |
| objecten.configuration.job.ttlSecondsAfterFinished | int | `600` |  |
| objecten.configuration.oidcUrl | string | `"https://objecten.example.nl"` |  |
| objecten.configuration.pkceEnabled | bool | `false` | Enable PKCE (S256) on the Keycloak client. Requires mozilla_django_oidc >= 4.0.0 and oidc_use_pkce: true in configuration.data. |
| objecten.configuration.secrets.keycloak_client_secret | string | `""` |  |
| objecten.flower.enabled | bool | `false` |  |
| objecten.fullnameOverride | string | `"objecten"` |  |
| objecten.image.repository | string | `"maykinmedia/objects-api"` |  |
| objecten.image.tag | string | `"3.6.2@sha256:6a3a40081016e5072c5355622c0ca3e1ded89228edce7336fc4d8600217344f8"` |  |
| objecten.nameOverride | string | `"objecten"` |  |
| objecten.otel.disabled | bool | `true` |  |
| objecten.persistence.existingClaim | string | `"objecten"` |  |
| objecten.persistence.size | string | `"10Gi"` |  |
| objecten.persistence.storageClassName | string | `"podiumd-standard"` |  |
| objecten.persistentVolume.storageClassName | string | `"podiumd-standard"` |  |
| objecten.persistentVolume.volumeAttributeShareName | string | `"objecten"` |  |
| objecten.resources.requests.cpu | string | `"100m"` |  |
| objecten.resources.requests.memory | string | `"256Mi"` |  |
| objecten.settings.allowedHosts | string | `"objecten.podiumd.svc.cluster.local"` |  |
| objecten.settings.cache.axes | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/1"` |  |
| objecten.settings.cache.default | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/1"` |  |
| objecten.settings.cache.oidc | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/1"` |  |
| objecten.settings.celery.brokerUrl | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/2"` |  |
| objecten.settings.celery.logLevel | string | `"warning"` | Set to debug for test/acceptance environments |
| objecten.settings.celery.resultBackend | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/2"` |  |
| objecten.settings.disable2fa | bool | `false` |  |
| objecten.settings.email.port | int | `587` |  |
| objecten.settings.email.useTLS | bool | `true` |  |
| objecten.tags.redis | bool | `false` |  |
| objecten.worker.livenessProbe.enabled | bool | `true` |  |
| objecten.worker.maxWorkerLivenessDelta | string | `"300"` |  |
| objecten.worker.replicaCount | int | `1` |  |
| objecten.worker.resources.requests.cpu | string | `"50m"` |  |
| objecten.worker.resources.requests.memory | string | `"192Mi"` |  |
| objecttypen.configuration.data | string | `""` |  |
| objecttypen.configuration.enabled | bool | `true` |  |
| objecttypen.configuration.initContainer.enabled | bool | `false` |  |
| objecttypen.configuration.job.backoffLimit | int | `6` |  |
| objecttypen.configuration.job.enabled | bool | `true` |  |
| objecttypen.configuration.job.resources | object | `{}` |  |
| objecttypen.configuration.job.restartPolicy | string | `"OnFailure"` |  |
| objecttypen.configuration.job.ttlSecondsAfterFinished | int | `600` |  |
| objecttypen.configuration.oidcUrl | string | `"https://objecttypen.example.nl"` |  |
| objecttypen.configuration.pkceEnabled | bool | `false` | Enable PKCE (S256) on the Keycloak client. Requires mozilla_django_oidc >= 4.0.0 and oidc_use_pkce: true in configuration.data. |
| objecttypen.configuration.secrets.keycloak_client_secret | string | `""` |  |
| objecttypen.configuration.token | string | `"<token>"` |  |
| objecttypen.create_required_objecttypen_job.activeDeadlineSeconds | int | `900` |  |
| objecttypen.create_required_objecttypen_job.backoffLimit | int | `10` |  |
| objecttypen.create_required_objecttypen_job.enabled | bool | `true` |  |
| objecttypen.create_required_objecttypen_job.resources.limits.cpu | string | `"200m"` |  |
| objecttypen.create_required_objecttypen_job.resources.limits.memory | string | `"128Mi"` |  |
| objecttypen.create_required_objecttypen_job.resources.requests.cpu | string | `"50m"` |  |
| objecttypen.create_required_objecttypen_job.resources.requests.memory | string | `"64Mi"` |  |
| objecttypen.fullnameOverride | string | `"objecttypen"` |  |
| objecttypen.image.repository | string | `"maykinmedia/objecttypes-api"` |  |
| objecttypen.image.tag | string | `"3.4.2@sha256:d366e6ede1bb924ea351495f4e88ceba53bb0df02fa5302929daef379131fda1"` |  |
| objecttypen.nameOverride | string | `"objecttypen"` |  |
| objecttypen.otel.disabled | bool | `true` |  |
| objecttypen.resources.requests.cpu | string | `"10m"` |  |
| objecttypen.resources.requests.memory | string | `"160Mi"` |  |
| objecttypen.settings.allowedHosts | string | `"objecttypen.podiumd.svc.cluster.local"` |  |
| objecttypen.settings.cache.axes | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/0"` |  |
| objecttypen.settings.cache.default | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/0"` |  |
| objecttypen.settings.disable2fa | bool | `false` |  |
| objecttypen.settings.email.port | int | `587` |  |
| objecttypen.settings.email.useTLS | bool | `true` |  |
| objecttypen.settings.uwsgi.maxRequests | string | `"1000"` |  |
| objecttypen.settings.uwsgi.processes | string | `"2"` |  |
| objecttypen.settings.uwsgi.threads | string | `"2"` |  |
| objecttypen.tags.redis | bool | `false` |  |
| omc.enabled | bool | `false` |  |
| omc.fullnameOverride | string | `"omc"` |  |
| omc.image.tag | string | `"1.17.19"` |  |
| omc.settings.notify.api.baseUrl | string | `"https://api.notifynl.nl"` |  |
| omc.settings.omc.auth.jwt.audience | string | `"omc"` |  |
| omc.settings.omc.auth.jwt.issuer | string | `"omc"` |  |
| omc.settings.omc.auth.jwt.secret | string | `""` |  |
| omc.settings.omc.auth.jwt.userId | string | `"OMC (PodiumD)"` |  |
| omc.settings.omc.auth.jwt.userName | string | `"OMC (PodiumD)"` |  |
| omc.settings.omc.feature.workflow.version | int | `2` |  |
| omc.settings.zgw.auth.jwt.issuer | string | `""` |  |
| omc.settings.zgw.auth.jwt.secret | string | `""` |  |
| omc.settings.zgw.auth.jwt.userId | string | `"OMC (PodiumD)"` |  |
| omc.settings.zgw.auth.jwt.userName | string | `"OMC (PodiumD)"` |  |
| omc.settings.zgw.variable.objectType.decisionInfoObjectType.uuids | string | `"00000000-0000-1000-b000-000000000000"` |  |
| omc.settings.zgw.variable.objectType.ktoObjectType.uuid | string | `"00000000-0000-1000-b000-000000000000"` |  |
| omc.settings.zgw.variable.objectType.messageObjectType.uuid | string | `"00000000-0000-1000-b000-000000000000"` |  |
| omc.settings.zgw.variable.objectType.messageObjectType.version | int | `1` |  |
| omc.settings.zgw.variable.objectType.taskObjectType.uuid | string | `"00000000-0000-1000-b000-000000000000"` |  |
| openarchiefbeheer.beat.resources.requests.cpu | string | `"50m"` |  |
| openarchiefbeheer.beat.resources.requests.memory | string | `"128Mi"` |  |
| openarchiefbeheer.configuration.data | string | `""` |  |
| openarchiefbeheer.configuration.enabled | bool | `true` |  |
| openarchiefbeheer.configuration.job.backoffLimit | int | `6` |  |
| openarchiefbeheer.configuration.job.enabled | bool | `true` |  |
| openarchiefbeheer.configuration.job.restartPolicy | string | `"OnFailure"` |  |
| openarchiefbeheer.configuration.job.ttlSecondsAfterFinished | int | `600` |  |
| openarchiefbeheer.configuration.oidcUrl | string | `"https://abc.example.nl"` |  |
| openarchiefbeheer.configuration.pkceEnabled | bool | `false` | Enable PKCE (S256) on the Keycloak client. |
| openarchiefbeheer.configuration.secrets.keycloak_client_secret | string | `""` |  |
| openarchiefbeheer.enabled | bool | `false` |  |
| openarchiefbeheer.fullnameOverride | string | `"openarchiefbeheer"` |  |
| openarchiefbeheer.image.tag | string | `"2.0.0@sha256:e5217d748869c62d26393311c3cfdcaacf69d8dde80ca3bc172ff41f3885f0ff"` |  |
| openarchiefbeheer.nameOverride | string | `"openarchiefbeheer"` |  |
| openarchiefbeheer.nginx.image.pullPolicy | string | `"IfNotPresent"` |  |
| openarchiefbeheer.nginx.image.repository | string | `"nginxinc/nginx-unprivileged"` |  |
| openarchiefbeheer.nginx.image.tag | string | `"1.31.4@sha256:197f252f060ed357f2ab98d4256762d7d107c76f18ad8f0b9d5178854611566d"` |  |
| openarchiefbeheer.nginx.resources.requests.cpu | string | `"10m"` |  |
| openarchiefbeheer.nginx.resources.requests.memory | string | `"16Mi"` |  |
| openarchiefbeheer.otel.disabled | bool | `true` |  |
| openarchiefbeheer.persistence.existingClaim | string | `"openarchiefbeheer"` |  |
| openarchiefbeheer.persistence.size | string | `"10Gi"` |  |
| openarchiefbeheer.persistence.storageClassName | string | `"podiumd-standard"` |  |
| openarchiefbeheer.persistentVolume.storageClassName | string | `"podiumd-standard"` |  |
| openarchiefbeheer.persistentVolume.volumeAttributeShareName | string | `"openarchiefbeheer"` |  |
| openarchiefbeheer.replicaCount | int | `1` |  |
| openarchiefbeheer.resources.limits | object | `{}` |  |
| openarchiefbeheer.resources.requests.cpu | string | `"250m"` |  |
| openarchiefbeheer.resources.requests.memory | string | `"256Mi"` |  |
| openarchiefbeheer.settings.allowedHosts | string | `"openarchiefbeheer.podiumd.svc.cluster.local"` |  |
| openarchiefbeheer.settings.cache.axes | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/13"` |  |
| openarchiefbeheer.settings.cache.choices | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/14"` |  |
| openarchiefbeheer.settings.cache.default | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/13"` |  |
| openarchiefbeheer.settings.celery.brokerUrl | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/14"` |  |
| openarchiefbeheer.settings.celery.logLevel | string | `"warning"` | Set to debug for test/acceptance environments |
| openarchiefbeheer.settings.celery.resultBackendl | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/14"` |  |
| openarchiefbeheer.settings.environment | string | `""` | Name of the environment (used for displaying purposes) |
| openarchiefbeheer.settings.frontend | object | `{"apiPath":"/api/v1","apiUrl":"","zaakUrlTemplate":""}` | Controls the log levels of project code and of the OIDC library. Possible values: NOTSET, DEBUG, INFO, WARNING, ERROR, CRITICAL.   level: INFO |
| openarchiefbeheer.settings.frontendUrl | string | `""` |  |
| openarchiefbeheer.settings.oidcRenewIdTokenExpirySeconds | int | `1800` |  |
| openarchiefbeheer.settings.postDestructionVisibilityPeriod | int | `7` | Number of days for which destruction lists will be visible after successful destruction. Defaults to 7. |
| openarchiefbeheer.settings.relatedCountDisabled | bool | `false` | If true, the inline presentation of related objects is disabled, reducing load on external registers. |
| openarchiefbeheer.settings.requestsReadTimeout | string | `"5000"` |  |
| openarchiefbeheer.settings.retry.backoffFactor | string | `""` |  |
| openarchiefbeheer.settings.retry.statusForcelist | string | `""` |  |
| openarchiefbeheer.settings.retry.total | string | `""` |  |
| openarchiefbeheer.settings.sessionCookieAge | int | `1800` |  |
| openarchiefbeheer.settings.waitingPeriod | int | `7` | Number of days to wait before destroying a list. Defaults to 7 in the application. |
| openarchiefbeheer.tags.redis | bool | `false` |  |
| openarchiefbeheer.worker.livenessProbe.enabled | bool | `true` |  |
| openarchiefbeheer.worker.resources.requests.cpu | string | `"100m"` |  |
| openarchiefbeheer.worker.resources.requests.memory | string | `"256Mi"` |  |
| openbao.configuration.bootstrapTokenSecret | string | `"openbao-bootstrap-token"` |  |
| openbao.configuration.enabled | bool | `true` |  |
| openbao.configuration.job.backoffLimit | int | `6` |  |
| openbao.configuration.job.image.repository | string | `"quay.io/openbao/openbao"` |  |
| openbao.configuration.job.image.tag | string | `"2.5.5@sha256:6150c4a6b62067db6141c8da7a6a6b5763f4f47c315343d0c848b40fecdfd452"` |  |
| openbao.configuration.job.nodeSelector | object | `{}` |  |
| openbao.configuration.job.resources.limits.cpu | string | `"250m"` |  |
| openbao.configuration.job.resources.limits.memory | string | `"128Mi"` |  |
| openbao.configuration.job.resources.requests.cpu | string | `"50m"` |  |
| openbao.configuration.job.resources.requests.memory | string | `"64Mi"` |  |
| openbao.configuration.job.restartPolicy | string | `"Never"` |  |
| openbao.configuration.job.ttlSecondsAfterFinished | int | `600` |  |
| openbao.configuration.keycloak.realm | string | `"podiumd"` |  |
| openbao.configuration.keycloak.url | string | `"https://keycloak.example.nl"` |  |
| openbao.configuration.kvPath | string | `"secret"` |  |
| openbao.configuration.oidcUrl | string | `"https://openbao.example.nl"` |  |
| openbao.configuration.secrets.keycloak_client_secret | string | `""` |  |
| openbao.configuration.uploadersGroup | string | `"vault-uploaders"` |  |
| openbao.configuration.uploadersRole | string | `"uploaders"` |  |
| openbao.database.host | string | `""` |  |
| openbao.database.name | string | `"openbao"` |  |
| openbao.database.password | string | `""` |  |
| openbao.database.port | int | `5432` |  |
| openbao.database.schemaJob.backoffLimit | int | `6` |  |
| openbao.database.schemaJob.image.repository | string | `"docker.io/library/postgres"` |  |
| openbao.database.schemaJob.image.tag | string | `"16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685"` |  |
| openbao.database.schemaJob.nodeSelector | object | `{}` |  |
| openbao.database.schemaJob.resources.limits.cpu | string | `"250m"` |  |
| openbao.database.schemaJob.resources.limits.memory | string | `"128Mi"` |  |
| openbao.database.schemaJob.resources.requests.cpu | string | `"50m"` |  |
| openbao.database.schemaJob.resources.requests.memory | string | `"64Mi"` |  |
| openbao.database.schemaJob.ttlSecondsAfterFinished | int | `600` |  |
| openbao.database.secretName | string | `"openbao-db"` |  |
| openbao.database.sslmode | string | `"require"` |  |
| openbao.database.username | string | `"openbao-admin"` |  |
| openbao.enabled | bool | `false` |  |
| openbao.injector.enabled | bool | `false` |  |
| openbao.server.dataStorage.enabled | bool | `false` |  |
| openbao.server.extraLabels."azure.workload.identity/use" | string | `"true"` |  |
| openbao.server.extraSecretEnvironmentVars[0].envName | string | `"BAO_PG_CONNECTION_URL"` |  |
| openbao.server.extraSecretEnvironmentVars[0].secretKey | string | `"connection-url"` |  |
| openbao.server.extraSecretEnvironmentVars[0].secretName | string | `"openbao-db"` |  |
| openbao.server.ha.config | string | `"ui = true\n\nlistener \"tcp\" {\n  tls_disable     = 1\n  address         = \"[::]:8200\"\n  cluster_address = \"[::]:8201\"\n}\n\nstorage \"postgresql\" {\n  table      = \"openbao_kv_store\"\n  ha_enabled = \"true\"\n  ha_table   = \"openbao_ha_locks\"\n}\n\nservice_registration \"kubernetes\" {}\n"` |  |
| openbao.server.ha.enabled | bool | `true` |  |
| openbao.server.ha.raft.enabled | bool | `false` |  |
| openbao.server.ha.replicas | int | `3` |  |
| openbao.server.image.registry | string | `"quay.io"` |  |
| openbao.server.image.repository | string | `"openbao/openbao"` |  |
| openbao.server.image.tag | string | `""` |  |
| openbao.server.ingress.enabled | bool | `false` |  |
| openbao.server.readinessProbe.enabled | bool | `true` |  |
| openbao.server.readinessProbe.path | string | `"/v1/sys/health?standbyok=true&perfstandbyok=true&uninitcode=200&sealedcode=200"` |  |
| openbao.server.resources.limits.cpu | string | `"500m"` |  |
| openbao.server.resources.limits.memory | string | `"512Mi"` |  |
| openbao.server.resources.requests.cpu | string | `"100m"` |  |
| openbao.server.resources.requests.memory | string | `"256Mi"` |  |
| openbao.server.serviceAccount.annotations."azure.workload.identity/client-id" | string | `""` |  |
| openbao.server.serviceAccount.create | bool | `true` |  |
| openbao.server.serviceAccount.name | string | `"openbao"` |  |
| openbao.server.updateStrategyType | string | `"RollingUpdate"` |  |
| openbeheer.configuration.data | string | `""` |  |
| openbeheer.configuration.enabled | bool | `true` |  |
| openbeheer.configuration.job.backoffLimit | int | `6` |  |
| openbeheer.configuration.job.enabled | bool | `true` |  |
| openbeheer.configuration.job.resources | object | `{}` |  |
| openbeheer.configuration.job.restartPolicy | string | `"Never"` |  |
| openbeheer.configuration.job.ttlSecondsAfterFinished | int | `600` |  |
| openbeheer.configuration.oidcUrl | string | `"https://openbeheer.example.nl"` |  |
| openbeheer.configuration.overwrite | bool | `false` |  |
| openbeheer.configuration.pkceEnabled | bool | `false` | Enable PKCE (S256) on the Keycloak client. Requires mozilla_django_oidc >= 4.0.0 and oidc_use_pkce: true in configuration.data. |
| openbeheer.configuration.secrets.keycloak_client_secret | string | `""` |  |
| openbeheer.configuration.secrets.objecttypen_openbeheer_token | string | `""` |  |
| openbeheer.configuration.secrets.openzaak_openbeheer_secret | string | `""` |  |
| openbeheer.enabled | bool | `false` |  |
| openbeheer.fullnameOverride | string | `"openbeheer"` |  |
| openbeheer.image.pullPolicy | string | `"IfNotPresent"` |  |
| openbeheer.image.repository | string | `"maykinmedia/open-beheer"` |  |
| openbeheer.image.tag | string | `"0.9.1@sha256:7c1dfaff1d069afe5d45e421f813078d8112b13c3cf65b5f547e866f6aad4e31"` |  |
| openbeheer.nameOverride | string | `"openbeheer"` |  |
| openbeheer.nginx.image.pullPolicy | string | `"IfNotPresent"` |  |
| openbeheer.nginx.image.repository | string | `"nginxinc/nginx-unprivileged"` |  |
| openbeheer.nginx.image.tag | string | `"1.31.4@sha256:197f252f060ed357f2ab98d4256762d7d107c76f18ad8f0b9d5178854611566d"` |  |
| openbeheer.nginx.resources.requests.cpu | string | `"10m"` |  |
| openbeheer.nginx.resources.requests.memory | string | `"16Mi"` |  |
| openbeheer.persistence.enabled | bool | `true` |  |
| openbeheer.persistence.existingClaim | string | `"openbeheer"` |  |
| openbeheer.persistence.mediaMountSubpath | string | `"openbeheer/media"` |  |
| openbeheer.persistence.size | string | `"1Gi"` |  |
| openbeheer.persistence.storageClassName | string | `"podiumd-standard"` |  |
| openbeheer.persistentVolume.storageClassName | string | `"podiumd-standard"` |  |
| openbeheer.persistentVolume.volumeAttributeShareName | string | `"openbeheer"` |  |
| openbeheer.replicaCount | int | `2` |  |
| openbeheer.resources | object | `{}` |  |
| openbeheer.securityContext.capabilities.drop[0] | string | `"ALL"` |  |
| openbeheer.securityContext.readOnlyRootFilesystem | bool | `false` |  |
| openbeheer.securityContext.runAsNonRoot | bool | `true` |  |
| openbeheer.securityContext.runAsUser | int | `1000` |  |
| openbeheer.settings.allowedHosts | string | `"openbeheer-nginx.podiumd.svc.cluster.local"` |  |
| openbeheer.settings.apiDomain | string | `""` |  |
| openbeheer.settings.apiPath | string | `"/api/v1"` |  |
| openbeheer.settings.cache.axes | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/17"` |  |
| openbeheer.settings.cache.default | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/17"` |  |
| openbeheer.settings.database.host | string | `""` |  |
| openbeheer.settings.database.name | string | `""` |  |
| openbeheer.settings.database.password | string | `""` |  |
| openbeheer.settings.database.port | int | `5432` |  |
| openbeheer.settings.database.sslmode | string | `"prefer"` |  |
| openbeheer.settings.database.username | string | `""` |  |
| openbeheer.settings.debug | bool | `false` |  |
| openbeheer.settings.djangoSettingsModule | string | `"openbeheer.conf.docker"` |  |
| openbeheer.settings.elasticapm.serviceName | string | `""` |  |
| openbeheer.settings.elasticapm.token | string | `""` |  |
| openbeheer.settings.elasticapm.url | string | `""` |  |
| openbeheer.settings.email.defaultFrom | string | `""` |  |
| openbeheer.settings.email.host | string | `"localhost"` |  |
| openbeheer.settings.email.password | string | `""` |  |
| openbeheer.settings.email.port | int | `25` |  |
| openbeheer.settings.email.useTLS | bool | `false` |  |
| openbeheer.settings.email.username | string | `""` |  |
| openbeheer.settings.environment | string | `""` |  |
| openbeheer.settings.isHttps | bool | `true` |  |
| openbeheer.settings.secretKey | string | `""` |  |
| openbeheer.settings.sentry.dsn | string | `""` |  |
| openbeheer.settings.sessionCookieAge | int | `900` |  |
| openbeheer.settings.throttling.enable | bool | `true` |  |
| openbeheer.settings.throttling.rateAnonymous | string | `"2500/hour"` |  |
| openbeheer.settings.throttling.rateUser | string | `"15000/hour"` |  |
| openbeheer.settings.useXForwardedHost | bool | `false` |  |
| openbeheer.settings.uwsgi.master | string | `"1"` |  |
| openbeheer.settings.uwsgi.maxRequests | string | `"1000"` |  |
| openbeheer.settings.uwsgi.processes | string | `"2"` |  |
| openbeheer.settings.uwsgi.threads | string | `"2"` |  |
| openbeheer.tags.redis | bool | `false` |  |
| openformulieren.beat.resources.requests.cpu | string | `"10m"` |  |
| openformulieren.beat.resources.requests.memory | string | `"160Mi"` |  |
| openformulieren.clamavConfigJob | object | `{"activeDeadlineSeconds":1200,"backoffLimit":15,"clamavHost":"clamav.podiumd.svc.cluster.local","clamavPort":3310,"clamavTimeout":30,"enabled":false,"resources":{"limits":{"cpu":"200m","memory":"256Mi"},"requests":{"cpu":"50m","memory":"128Mi"}},"ttlSecondsAfterFinished":600}` | Seeds Open Forms' GlobalConfiguration singleton (enable_virus_scan, clamav_host/port/timeout) via `manage.py shell`. Open Forms has no declarative setup-configuration step for this — upstream only exposes it through the admin UI (docs/configuration/general/virus_scan.rst) — so this Job writes the same fields directly, verifying the ClamAV connection first the same way GlobalConfiguration.clean() does. Off by default: opt-in per gemeente. See templates/openformulieren-configure-clamav.yaml and docs/apps/openforms/openforms-BASICS.md. |
| openformulieren.clamavConfigJob.backoffLimit | int | `15` | Retries generously: on first deploy this Job can race both the openformulieren DB migration (image entrypoint) and ClamAV's own cold-start (up to ~5 minutes to load its signature database, see docs/apps/clamav/clamav-BASICS.md) — it fails fast and lets Kubernetes' Job backoff retry until both are ready, rather than needing a wait container or Helm hook ordering. |
| openformulieren.configuration.data | string | `""` |  |
| openformulieren.configuration.enabled | bool | `true` |  |
| openformulieren.configuration.job.backoffLimit | int | `6` |  |
| openformulieren.configuration.job.enabled | bool | `true` |  |
| openformulieren.configuration.job.restartPolicy | string | `"OnFailure"` |  |
| openformulieren.configuration.job.ttlSecondsAfterFinished | int | `600` |  |
| openformulieren.configuration.oidcUrl | string | `"https://openformulieren.example.nl"` |  |
| openformulieren.configuration.pkceEnabled | bool | `false` | Enable PKCE (S256) on the Keycloak client. Requires mozilla_django_oidc >= 4.0.0 and oidc_use_pkce: true in configuration.data. |
| openformulieren.configuration.secrets.keycloak_client_secret | string | `""` |  |
| openformulieren.flower.enabled | bool | `false` |  |
| openformulieren.fullnameOverride | string | `"openformulieren"` |  |
| openformulieren.image.tag | string | `"3.5.6@sha256:f5a5d51a44f39edcfb2143ae5d2ed9525b22ea377faa35fd2cce26b678f7fe83"` |  |
| openformulieren.nameOverride | string | `"openformulieren"` |  |
| openformulieren.nginx.config.clientMaxBodySize | string | `"100M"` |  |
| openformulieren.nginx.image.pullPolicy | string | `"IfNotPresent"` |  |
| openformulieren.nginx.image.repository | string | `"nginxinc/nginx-unprivileged"` |  |
| openformulieren.nginx.image.tag | string | `"1.31.4@sha256:197f252f060ed357f2ab98d4256762d7d107c76f18ad8f0b9d5178854611566d"` |  |
| openformulieren.nginx.resources.requests.cpu | string | `"10m"` |  |
| openformulieren.nginx.resources.requests.memory | string | `"16Mi"` |  |
| openformulieren.persistence.existingClaim | string | `"openformulieren"` |  |
| openformulieren.persistence.mediaMountSubpath | string | `"openformulieren/media"` |  |
| openformulieren.persistence.privateMediaMountSubpath | string | `"openformulieren/private_media"` |  |
| openformulieren.persistence.size | string | `"10Gi"` |  |
| openformulieren.persistence.storageClassName | string | `"podiumd-standard"` |  |
| openformulieren.persistentVolume.storageClassName | string | `"podiumd-standard"` |  |
| openformulieren.persistentVolume.volumeAttributeShareName | string | `"openformulieren"` |  |
| openformulieren.resources.requests.cpu | string | `"250m"` |  |
| openformulieren.resources.requests.memory | string | `"1Gi"` |  |
| openformulieren.settings.allowedHosts | string | `"openformulieren-nginx.podiumd.svc.cluster.local"` |  |
| openformulieren.settings.cache.axes | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/9"` |  |
| openformulieren.settings.cache.default | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/9"` |  |
| openformulieren.settings.celery.brokerUrl | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/10"` |  |
| openformulieren.settings.celery.logLevel | string | `"warning"` | Set to debug for test/acceptance environments |
| openformulieren.settings.celery.resultBackendl | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/10"` |  |
| openformulieren.settings.email.port | int | `587` |  |
| openformulieren.settings.email.useTLS | bool | `true` |  |
| openformulieren.tags.redis | bool | `false` |  |
| openformulieren.worker.livenessProbe.enabled | bool | `true` |  |
| openformulieren.worker.maxWorkerLivenessDelta | string | `"300"` |  |
| openformulieren.worker.replicaCount | int | `1` |  |
| openformulieren.worker.resources.requests.cpu | string | `"200m"` |  |
| openformulieren.worker.resources.requests.memory | string | `"1Gi"` |  |
| openinwoner.beat.resources.requests.cpu | string | `"50m"` |  |
| openinwoner.beat.resources.requests.memory | string | `"128Mi"` |  |
| openinwoner.celeryMonitor.resources.requests.cpu | string | `"50m"` |  |
| openinwoner.celeryMonitor.resources.requests.memory | string | `"64Mi"` |  |
| openinwoner.clamavConfigJob | object | `{"activeDeadlineSeconds":1200,"backoffLimit":15,"clamavHost":"clamav.podiumd.svc.cluster.local","clamavPort":3310,"clamavTimeout":30,"enabled":false,"resources":{"limits":{"cpu":"200m","memory":"256Mi"},"requests":{"cpu":"50m","memory":"128Mi"}},"ttlSecondsAfterFinished":600}` | Seeds Open Inwoner's SiteConfiguration singleton (enable_virus_scan, clamav_host/port/timeout) via `manage.py shell`. Unlike most SiteConfiguration fields, these four are NOT managed by the site_config_enable/site_config: setup-configuration step — upstream's SiteConfigurationStep omits them from both its required_settings and optional_settings, so setting them under configuration.data is silently ignored. This Job writes them directly and pings clamd itself first (SiteConfiguration.clean() only checks clamav_host is non-empty, it doesn't test connectivity). Off by default: opt-in per gemeente. See templates/openinwoner-configure-clamav.yaml and docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-gemeente-specific.md. |
| openinwoner.clamavConfigJob.backoffLimit | int | `15` | Retries generously: on first deploy this Job can race both the openinwoner DB migration (image entrypoint) and ClamAV's own cold-start (up to ~5 minutes to load its signature database, see docs/apps/clamav/clamav-BASICS.md) — it fails fast and lets Kubernetes' Job backoff retry until both are ready, rather than needing a wait container or Helm hook ordering. |
| openinwoner.configuration.data | string | `""` |  |
| openinwoner.configuration.enabled | bool | `true` |  |
| openinwoner.configuration.initContainer.enabled | bool | `false` |  |
| openinwoner.configuration.job.backoffLimit | int | `6` |  |
| openinwoner.configuration.job.enabled | bool | `true` |  |
| openinwoner.configuration.job.resources | object | `{}` |  |
| openinwoner.configuration.job.restartPolicy | string | `"OnFailure"` |  |
| openinwoner.configuration.job.ttlSecondsAfterFinished | int | `600` |  |
| openinwoner.configuration.oidcUrl | string | `"https://openinwoner.example.nl"` |  |
| openinwoner.configuration.pkceEnabled | bool | `false` | Enable PKCE (S256) on the Keycloak client. Requires mozilla_django_oidc >= 4.0.0 and oidc_use_pkce: true in configuration.data. |
| openinwoner.configuration.secrets.keycloak_client_secret | string | `""` |  |
| openinwoner.eck-elasticsearch.enabled | bool | `true` |  |
| openinwoner.eck-elasticsearch.http | object | `{"tls":{"selfSignedCertificate":{"disabled":true}}}` | image: overrides the Elasticsearch image. ECK does NOT append :version when spec.image is set — include the full tag. For ACR: image: acrprodmgmt.azurecr.io/elasticsearch/elasticsearch:9.2.0 |
| openinwoner.eck-elasticsearch.version | string | `"9.2.0"` |  |
| openinwoner.eck-operator.enabled | bool | `false` |  |
| openinwoner.fullnameOverride | string | `"openinwoner"` |  |
| openinwoner.image.tag | string | `"2.4.3@sha256:c2ff751143c260874a1ebcdcc7e07dc213cffee70c3ea5a9589948e3f5da43e4"` |  |
| openinwoner.lowLatencyWorker | object | `{"replicaCount":1,"resources":{"requests":{"cpu":"100m","memory":"256Mi"}}}` | New in openinwoner 2.3.0 (chart 2.2.0): dedicated low-latency Celery worker for cache-seeding/warmup tasks. The chart creates this deployment by default (replicaCount 1) on upgrade; resources pinned here to match podiumd conventions. |
| openinwoner.nameOverride | string | `"openinwoner"` |  |
| openinwoner.nginx.config.basicAuth.enabled | bool | `false` |  |
| openinwoner.nginx.config.basicAuth.users | string | `"dimpact:$apr1$E03dZmYK$npjTaXfI05tMJ63gB8dxm."` |  |
| openinwoner.nginx.config.clientMaxBodySize | string | `"100M"` |  |
| openinwoner.nginx.image.pullPolicy | string | `"IfNotPresent"` |  |
| openinwoner.nginx.image.repository | string | `"nginxinc/nginx-unprivileged"` |  |
| openinwoner.nginx.image.tag | string | `"1.31.4@sha256:197f252f060ed357f2ab98d4256762d7d107c76f18ad8f0b9d5178854611566d"` |  |
| openinwoner.nginx.resources.requests.cpu | string | `"30m"` |  |
| openinwoner.nginx.resources.requests.memory | string | `"8Mi"` |  |
| openinwoner.persistence.existingClaim | string | `"openinwoner"` |  |
| openinwoner.persistence.size | string | `"10Gi"` |  |
| openinwoner.persistence.storageClassName | string | `"podiumd-standard"` |  |
| openinwoner.persistentVolume.storageClassName | string | `"podiumd-standard"` |  |
| openinwoner.persistentVolume.volumeAttributeShareName | string | `"openinwoner"` |  |
| openinwoner.resources.requests.cpu | string | `"200m"` |  |
| openinwoner.resources.requests.memory | string | `"1Gi"` |  |
| openinwoner.settings.allowedHosts | string | `"openinwoner-nginx.podiumd.svc.cluster.local"` |  |
| openinwoner.settings.brpVersion | string | `""` |  |
| openinwoner.settings.cache.axes | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/11"` |  |
| openinwoner.settings.cache.default | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/11"` |  |
| openinwoner.settings.cacheSeedingQueue | string | `""` | New in openinwoner 2.3.0: Celery queue for cache-seeding tasks. Empty defaults to the low-latency worker queue (see lowLatencyWorker below). |
| openinwoner.settings.cacheZgwZakenTimeout | string | `""` | New in openinwoner 2.3.0: per-request timeout (seconds) for cached ZGW zaken. Empty uses the application default (300s, raised from 60s upstream). |
| openinwoner.settings.celery.brokerUrl | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/12"` |  |
| openinwoner.settings.celery.logLevel | string | `"warning"` | Set to debug for test/acceptance environments |
| openinwoner.settings.celery.resultBackendl | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/12"` |  |
| openinwoner.settings.cms4MigrationInitContainer | bool | `true` | New in openinwoner 2.3.0 (chart 2.2.0): runs an init container executing `manage.py cms4_migration` for the Django CMS v3 → v4 migration. Keep true for the first rollout to 2.3.0 so the one-time migration runs; flip to false in a follow-up release once every environment has completed it. Re-running is a no-op. |
| openinwoner.settings.digidMock | string | `""` |  |
| openinwoner.settings.eherkenningMock | string | `""` |  |
| openinwoner.settings.email.port | int | `587` |  |
| openinwoner.settings.email.useTLS | bool | `true` |  |
| openinwoner.settings.oidcFrontendLogoutWithHints | bool | `true` |  |
| openinwoner.settings.otel.disabled | bool | `true` |  |
| openinwoner.settings.searchIndexInitContainer | bool | `true` |  |
| openinwoner.tags.redis | bool | `false` |  |
| openinwoner.worker.livenessProbe.enabled | bool | `true` |  |
| openinwoner.worker.maxWorkerLivenessDelta | string | `"300"` |  |
| openinwoner.worker.replicaCount | int | `1` |  |
| openinwoner.worker.resources.requests.cpu | string | `"200m"` |  |
| openinwoner.worker.resources.requests.memory | string | `"640Mi"` |  |
| openklant.configuration.data | string | `""` |  |
| openklant.configuration.enabled | bool | `true` |  |
| openklant.configuration.initContainer.enabled | bool | `false` |  |
| openklant.configuration.job.backoffLimit | int | `6` |  |
| openklant.configuration.job.enabled | bool | `true` |  |
| openklant.configuration.job.resources | object | `{}` |  |
| openklant.configuration.job.restartPolicy | string | `"OnFailure"` |  |
| openklant.configuration.job.ttlSecondsAfterFinished | int | `600` |  |
| openklant.configuration.oidcUrl | string | `"https://openklant.example.nl"` |  |
| openklant.configuration.pkceEnabled | bool | `false` | Enable PKCE (S256) on the Keycloak client. Requires mozilla_django_oidc >= 4.0.0 and oidc_use_pkce: true in configuration.data. |
| openklant.configuration.secrets.keycloak_client_secret | string | `""` |  |
| openklant.fullnameOverride | string | `"openklant"` |  |
| openklant.image.repository | string | `"maykinmedia/open-klant"` |  |
| openklant.image.tag | string | `"2.15.0@sha256:ce59a2c60dab1c14e62fe34a99511839390dd2d482983c27334241e0d60c693d"` |  |
| openklant.nameOverride | string | `"openklant"` |  |
| openklant.nginx.image.pullPolicy | string | `"IfNotPresent"` |  |
| openklant.nginx.image.repository | string | `"nginxinc/nginx-unprivileged"` |  |
| openklant.nginx.image.tag | string | `"1.31.4@sha256:197f252f060ed357f2ab98d4256762d7d107c76f18ad8f0b9d5178854611566d"` |  |
| openklant.nginx.resources.requests.cpu | string | `"10m"` |  |
| openklant.nginx.resources.requests.memory | string | `"16Mi"` |  |
| openklant.otel.disabled | bool | `true` |  |
| openklant.persistence.existingClaim | string | `"openklant"` |  |
| openklant.persistence.size | string | `"10Gi"` |  |
| openklant.persistence.storageClassName | string | `"podiumd-standard"` |  |
| openklant.persistentVolume.storageClassName | string | `"podiumd-standard"` |  |
| openklant.persistentVolume.volumeAttributeShareName | string | `"openklant"` |  |
| openklant.resources.requests.cpu | string | `"100m"` |  |
| openklant.resources.requests.memory | string | `"300Mi"` |  |
| openklant.settings.allowedHosts | string | `"openklant.podiumd.svc.cluster.local"` |  |
| openklant.settings.cache.axes | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/7"` |  |
| openklant.settings.cache.default | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/7"` |  |
| openklant.settings.celery.brokerUrl | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/8"` |  |
| openklant.settings.celery.logLevel | string | `"warning"` | Set to debug for test/acceptance environments |
| openklant.settings.celery.resultBackendl | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/8"` |  |
| openklant.settings.disable2fa | bool | `false` |  |
| openklant.settings.email.port | int | `587` |  |
| openklant.settings.email.useTLS | bool | `true` |  |
| openklant.settings.uwsgi.maxRequests | string | `"1000"` |  |
| openklant.settings.uwsgi.processes | string | `"2"` |  |
| openklant.settings.uwsgi.threads | string | `"4"` |  |
| openklant.tags.redis | bool | `false` |  |
| openklant.worker.livenessProbe.enabled | bool | `true` |  |
| openklant.worker.replicaCount | int | `1` |  |
| openklant.worker.resources.requests.cpu | string | `"50m"` |  |
| openklant.worker.resources.requests.memory | string | `"200Mi"` |  |
| opennotificaties.beat.resources.requests.cpu | string | `"50m"` |  |
| opennotificaties.beat.resources.requests.memory | string | `"128Mi"` |  |
| opennotificaties.configuration.data | string | `""` |  |
| opennotificaties.configuration.http_request_job.enabled | bool | `false` |  |
| opennotificaties.configuration.initContainer.enabled | bool | `false` |  |
| opennotificaties.configuration.job.backoffLimit | int | `6` |  |
| opennotificaties.configuration.job.enabled | bool | `true` |  |
| opennotificaties.configuration.job.resources | object | `{}` |  |
| opennotificaties.configuration.job.restartPolicy | string | `"OnFailure"` |  |
| opennotificaties.configuration.job.ttlSecondsAfterFinished | int | `600` |  |
| opennotificaties.configuration.oidcUrl | string | `"https://opennotificaties.example.nl"` |  |
| opennotificaties.configuration.pkceEnabled | bool | `false` | Enable PKCE (S256) on the Keycloak client. Requires mozilla_django_oidc >= 4.0.0 and oidc_use_pkce: true in configuration.data. |
| opennotificaties.configuration.secrets.keycloak_client_secret | string | `""` |  |
| opennotificaties.flower.enabled | bool | `false` |  |
| opennotificaties.fullnameOverride | string | `"opennotificaties"` |  |
| opennotificaties.image.tag | string | `"1.16.2@sha256:2988d538b30db30487ed89873877e1d22e12f80dfa42d80ec1a5c97265c7e4cd"` |  |
| opennotificaties.nameOverride | string | `"opennotificaties"` |  |
| opennotificaties.otel.disabled | bool | `true` |  |
| opennotificaties.persistence.existingClaim | string | `"opennotificaties"` |  |
| opennotificaties.persistence.size | string | `"10Gi"` |  |
| opennotificaties.persistence.storageClassName | string | `"podiumd-standard"` |  |
| opennotificaties.persistentVolume.storageClassName | string | `"podiumd-standard"` |  |
| opennotificaties.persistentVolume.volumeAttributeShareName | string | `"opennotificaties"` |  |
| opennotificaties.resources.requests.cpu | string | `"100m"` |  |
| opennotificaties.resources.requests.memory | string | `"256Mi"` |  |
| opennotificaties.settings.allowedHosts | string | `"opennotificaties.podiumd.svc.cluster.local"` |  |
| opennotificaties.settings.cache.axes | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/3"` |  |
| opennotificaties.settings.cache.default | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/3"` |  |
| opennotificaties.settings.celery.brokerUrl | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/6"` |  |
| opennotificaties.settings.celery.logLevel | string | `"warning"` | Set to debug for test/acceptance environments |
| opennotificaties.settings.celery.publishBrokerUrl | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/6"` |  |
| opennotificaties.settings.celery.resultBackend | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/6"` |  |
| opennotificaties.settings.disable2fa | bool | `false` |  |
| opennotificaties.settings.email.port | int | `587` |  |
| opennotificaties.settings.email.useTLS | bool | `true` |  |
| opennotificaties.settings.maxRetries | int | `5` |  |
| opennotificaties.settings.messageBroker.celeryResultBackend | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/6"` |  |
| opennotificaties.settings.notificationSecInterval | int | `5` | Seconds between execute_notifications runs (chart default 20, minimum 5). Lowered to the minimum so notifications go out with less delay. |
| opennotificaties.settings.requestsTimeout | int | `60` |  |
| opennotificaties.settings.retryBackoff | int | `3` |  |
| opennotificaties.settings.retryBackoffMax | int | `48` |  |
| opennotificaties.tags.redis | bool | `false` |  |
| opennotificaties.worker.livenessProbe.enabled | bool | `true` |  |
| opennotificaties.worker.maxWorkerLivenessDelta | string | `"300"` |  |
| opennotificaties.worker.replicaCount | int | `1` |  |
| opennotificaties.worker.resources.requests.cpu | string | `"50m"` |  |
| opennotificaties.worker.resources.requests.memory | string | `"386Mi"` |  |
| openzaak.beat.resources.requests.cpu | string | `"10m"` |  |
| openzaak.beat.resources.requests.memory | string | `"160Mi"` |  |
| openzaak.configuration.data | string | `""` |  |
| openzaak.configuration.enabled | bool | `true` |  |
| openzaak.configuration.initContainer.enabled | bool | `false` |  |
| openzaak.configuration.job.backoffLimit | int | `6` |  |
| openzaak.configuration.job.enabled | bool | `true` |  |
| openzaak.configuration.job.resources | object | `{}` |  |
| openzaak.configuration.job.restartPolicy | string | `"Never"` |  |
| openzaak.configuration.job.ttlSecondsAfterFinished | int | `600` |  |
| openzaak.configuration.notificaties.enabled | bool | `true` |  |
| openzaak.configuration.notificatiesAuthorization.enabled | bool | `true` |  |
| openzaak.configuration.oidcUrl | string | `"https://openzaak.example.nl"` |  |
| openzaak.configuration.pkceEnabled | bool | `false` | Enable PKCE (S256) on the Keycloak client. Requires mozilla_django_oidc >= 4.0.0 and oidc_use_pkce: true in configuration.data. |
| openzaak.configuration.secrets.keycloak_client_secret | string | `""` |  |
| openzaak.create_required_catalogi_job.activeDeadlineSeconds | int | `900` |  |
| openzaak.create_required_catalogi_job.backoffLimit | int | `10` |  |
| openzaak.create_required_catalogi_job.client_id | string | `"<openzaak_client_id>"` |  |
| openzaak.create_required_catalogi_job.e2eTestZaaktype.create | bool | `true` |  |
| openzaak.create_required_catalogi_job.enabled | bool | `true` |  |
| openzaak.create_required_catalogi_job.resources.limits.cpu | string | `"200m"` |  |
| openzaak.create_required_catalogi_job.resources.limits.memory | string | `"128Mi"` |  |
| openzaak.create_required_catalogi_job.resources.requests.cpu | string | `"50m"` |  |
| openzaak.create_required_catalogi_job.resources.requests.memory | string | `"64Mi"` |  |
| openzaak.create_required_catalogi_job.secret | string | `"<openzaak_secret>"` |  |
| openzaak.extraEnvVars | list | `[{"name":"OPENZAAK_PORT","value":"8000"}]` | Override OPENZAAK_PORT to prevent Kubernetes service-discovery injection (tcp://<ip>:80) from being passed to uwsgi as the port number. Since Open Zaak 1.27.3 the app reads OPENZAAK_PORT for uwsgi_port; K8s auto-injects OPENZAAK_PORT=tcp://<svc-ip>:80 for the openzaak Service, which uwsgi cannot parse. See https://github.com/open-zaak/open-zaak/issues/2415 |
| openzaak.flower.enabled | bool | `false` |  |
| openzaak.fullnameOverride | string | `"openzaak"` |  |
| openzaak.image.tag | string | `"1.29.3@sha256:7ac22da287ac190a0e1c14849a370c433d3511678dcc8f3897007fd6de6dd4ac"` |  |
| openzaak.nameOverride | string | `"openzaak"` |  |
| openzaak.nginx.image.pullPolicy | string | `"IfNotPresent"` |  |
| openzaak.nginx.image.repository | string | `"nginxinc/nginx-unprivileged"` |  |
| openzaak.nginx.image.tag | string | `"1.31.4@sha256:197f252f060ed357f2ab98d4256762d7d107c76f18ad8f0b9d5178854611566d"` |  |
| openzaak.nginx.resources.requests.cpu | string | `"10m"` |  |
| openzaak.nginx.resources.requests.memory | string | `"16Mi"` |  |
| openzaak.otel.disabled | bool | `true` |  |
| openzaak.persistence.existingClaim | string | `"openzaak"` |  |
| openzaak.persistence.size | string | `"10Gi"` |  |
| openzaak.persistence.storageClassName | string | `"podiumd-standard"` |  |
| openzaak.persistentVolume.storageClassName | string | `"podiumd-standard"` |  |
| openzaak.persistentVolume.volumeAttributeShareName | string | `"openzaak"` |  |
| openzaak.resources.requests.cpu | string | `"250m"` |  |
| openzaak.resources.requests.memory | string | `"512Mi"` |  |
| openzaak.settings.allowedHosts | string | `"openzaak-nginx.podiumd.svc.cluster.local"` |  |
| openzaak.settings.cache.axes | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/4"` |  |
| openzaak.settings.cache.default | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/4"` |  |
| openzaak.settings.celery.brokerUrl | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/5"` |  |
| openzaak.settings.celery.logLevel | string | `"warning"` | Set to debug for test/acceptance environments |
| openzaak.settings.celery.resultBackendl | string | `"redis://redis-ha-master.podiumd.svc.cluster.local:6379/5"` |  |
| openzaak.settings.disable2fa | bool | `false` |  |
| openzaak.settings.documentApiBackend | string | `"filesystem"` | Backend for the Documenten API. Supported values: filesystem | azure_blob_storage |
| openzaak.settings.email.port | int | `587` |  |
| openzaak.settings.email.useTLS | bool | `true` |  |
| openzaak.settings.uwsgi.maxRequests | string | `"1000"` |  |
| openzaak.settings.uwsgi.processes | string | `"2"` |  |
| openzaak.settings.uwsgi.threads | string | `"4"` |  |
| openzaak.tags.redis | bool | `false` |  |
| openzaak.worker.livenessProbe.enabled | bool | `true` |  |
| openzaak.worker.maxWorkerLivenessDelta | string | `"300"` |  |
| openzaak.worker.replicaCount | int | `1` |  |
| openzaak.worker.resources.requests.cpu | string | `"200m"` |  |
| openzaak.worker.resources.requests.memory | string | `"1Gi"` |  |
| pabc.enabled | bool | `true` |  |
| pabc.fullnameOverride | string | `"pabc"` |  |
| pabc.image.repository | string | `"ghcr.io/platform-autorisatie-beheer-component/pabc-api"` |  |
| pabc.image.tag | string | `"1.1.1@sha256:09a902e43f6cdb214afc369d04005c7b6108fd24b15709f1debbcfb1b446ef42"` |  |
| pabc.initContainers.waitFor.image.pullPolicy | string | `"IfNotPresent"` |  |
| pabc.initContainers.waitFor.image.repository | string | `"ghcr.io/groundnuty/k8s-wait-for"` |  |
| pabc.initContainers.waitFor.image.tag | string | `"v2.0@sha256:c14d7271e4013b24b34ef0d7144c4610577d0e9110ccc26b163fa28089fa1f4e"` |  |
| pabc.migrations.image.repository | string | `"ghcr.io/platform-autorisatie-beheer-component/pabc-migrations"` |  |
| pabc.migrations.image.tag | string | `"1.1.1@sha256:a3841a2eb78cddd34ebb0de1bfede1db1ae9713921c0d77e4366baceffa86e05"` |  |
| pabc.migrations.nodeSelector | object | `{}` |  |
| pabc.nodeSelector | object | `{}` |  |
| pabc.postgresql.enabled | bool | `false` |  |
| pabc.resources.limits.cpu | string | `"200m"` |  |
| pabc.resources.limits.memory | string | `"768Mi"` |  |
| pabc.resources.requests.cpu | string | `"10m"` |  |
| pabc.resources.requests.memory | string | `"384Mi"` |  |
| pabc.settings.apiKeys[0] | string | `""` |  |
| pabc.settings.database.host | string | `""` |  |
| pabc.settings.database.name | string | `"pabc"` |  |
| pabc.settings.database.password | string | `""` |  |
| pabc.settings.database.username | string | `"pabc"` |  |
| pabc.settings.keycloakAdmin.clientId | string | `"pabc-keycloak-admin"` |  |
| pabc.settings.keycloakAdmin.clientSecret | string | `""` |  |
| pabc.settings.oidc.authority | string | `""` |  |
| pabc.settings.oidc.clientId | string | `"pabc"` |  |
| pabc.settings.oidc.clientSecret | string | `""` |  |
| pabc.settings.oidc.emailClaimType | string | `"email"` |  |
| pabc.settings.oidc.functioneelBeheerderRole | string | `"administrator"` |  |
| pabc.settings.oidc.nameClaimType | string | `"name"` |  |
| pabc.settings.oidc.oidcUrl | string | `"https://pabc.example.nl"` |  |
| pabc.settings.oidc.pkceEnabled | bool | `false` | Enable PKCE (S256) on the Keycloak client. PABC is a .NET app; enable when OpenIdConnect PKCE is configured in the application. |
| pabc.settings.oidc.roleClaimType | string | `"roles"` |  |
| persistentVolume.nodeStageSecretRefName | string | `""` |  |
| persistentVolume.nodeStageSecretRefNamespace | string | `""` |  |
| persistentVolume.volumeAttributeResourceGroup | string | `""` |  |
| persistentVolume.volumeAttributeShareName | string | `""` |  |
| redis-operator.enabled | bool | `true` |  |
| redis-operator.featureGates.GenerateConfigInInitContainer | bool | `true` |  |
| redis-operator.redis-ha | object | `{"databases":32,"enabled":true,"image":{"repository":"quay.io/opstree/redis","tag":"v8.6.6@sha256:12724412997e6acc32783f8c3c1ce8a7657029e06f563ffc8cbd81e2e9de7628"},"initContainerImage":{"pullPolicy":"IfNotPresent","repository":"library/busybox","tag":"1.38.0-glibc@sha256:3ba030337caebbfc2232b22b1e435eb213b28e5844a34942c74555bf904a265a"},"initContainerResources":{"limits":{"cpu":"50m","memory":"32Mi"},"requests":{"cpu":"10m","memory":"16Mi"}},"labelMasterCronJob":{"enabled":true,"image":{"repository":"docker.io/alpine/k8s","tag":"1.36.2@sha256:44ef4942e171939b9c665a4a84beb80e2dcdb9a24330d4651cfdfd2e9deecc47"},"nodeSelector":{},"resources":{"limits":{"cpu":"100m","memory":"64Mi"},"requests":{"cpu":"10m","memory":"32Mi"}},"schedule":"*/2 * * * *"},"podSecurityContext":{"fsGroup":1000},"preDeleteJob":{"image":{"repository":"docker.io/alpine/k8s","tag":"1.36.2@sha256:44ef4942e171939b9c665a4a84beb80e2dcdb9a24330d4651cfdfd2e9deecc47"},"nodeSelector":{}},"redisConfig":{"additionalRedisConfig":""},"redisExporter":{"enabled":false,"image":{"repository":"quay.io/opstree/redis-exporter","tag":"v1.89.0@sha256:00a3628bdd3bb3423a15c5daefa328c471ee609798eed1744fe578c906d20cab"},"podMonitor":{"enabled":false,"interval":"30s","scrapeTimeout":"10s"}},"replicaCount":3,"resources":{"limits":{"cpu":"500m","memory":"512Mi"},"requests":{"cpu":"100m","memory":"256Mi"}},"serviceName":"redis-ha","storage":{"volumeClaimTemplate":{"spec":{"accessModes":["ReadWriteOnce"],"resources":{"requests":{"storage":"2Gi"}},"storageClassName":"managed-csi-premiumv2"}}}}` | Shared Redis HA cluster using the RedisReplication CRD from the OT Redis Operator. When redis-operator.redis-ha.enabled is true, individual Redis subcharts per service should be disabled:   servicename:     tags:       redis: false   # disables template references to .Subcharts.redis     redis:       enabled: false # prevents subchart installation  Database allocation:   objecttypen        : db 0  (cache)   objecten           : db 1  (cache), db 2  (celery)   opennotificaties   : db 3  (cache), db 6  (celery result backend; broker nu ook Redis i.p.v. RabbitMQ vanaf chart 2.0.0)   openzaak           : db 4  (cache), db 5  (celery)   openklant          : db 7  (cache), db 8  (celery)   openformulieren    : db 9  (cache), db 10 (celery)   openinwoner        : db 11 (cache), db 12 (celery)   openarchiefbeheer  : db 13 (cache+axes), db 14 (choices + celery)   referentielijsten  : db 15 (cache), db 16 (reserved — celery not yet used)   openbeheer         : db 17 (cache), db 18 (reserved — celery not yet used)   <future component> : db 19 (cache), db 20 (celery)   db 21–31           : unallocated See docs/apps/redis/redis-ha-databases.md for the full allocation table and guidance. |
| redis-operator.redis-ha.databases | int | `32` | Number of Redis databases to configure. Applied via an initContainer because `databases` is a startup-only parameter and the OT redis-operator does not include the additionalRedisConfig ConfigMap in the main redis.conf (operator limitation in v0.24.0). |
| redis-operator.redis-ha.initContainerImage | object | `{"pullPolicy":"IfNotPresent","repository":"library/busybox","tag":"1.38.0-glibc@sha256:3ba030337caebbfc2232b22b1e435eb213b28e5844a34942c74555bf904a265a"}` | Image used by the initContainer that appends `databases N` to redis.conf. Override this in environments that restrict public Docker Hub pulls (e.g. point to an ACR mirror). |
| redis-operator.redis-ha.initContainerResources | object | `{"limits":{"cpu":"50m","memory":"32Mi"},"requests":{"cpu":"10m","memory":"16Mi"}}` | Resources for the initContainer that configures redis.conf. |
| redis-operator.redis-ha.labelMasterCronJob | object | `{"enabled":true,"image":{"repository":"docker.io/alpine/k8s","tag":"1.36.2@sha256:44ef4942e171939b9c665a4a84beb80e2dcdb9a24330d4651cfdfd2e9deecc47"},"nodeSelector":{},"resources":{"limits":{"cpu":"100m","memory":"64Mi"},"requests":{"cpu":"10m","memory":"32Mi"}},"schedule":"*/2 * * * *"}` | CronJob that periodically reconciles redis-role labels on redis-ha pods. Workaround for a known OT Redis Operator 0.24.0 bug (PR #1720) where the operator fails to apply redis-role labels after a simultaneous pod restart, leaving the redis-ha-master Service with no endpoints. Runs every 2 minutes and always reconciles from RedisReplication.status.masterNode — no early-exit if a label already exists. NOTE: PR #1720 has been included since redis-operator 0.25.0 (confirmed present in 0.26.1, the version currently pinned above). This workaround is a candidate for removal — verify the operator self-heals correctly on a simultaneous pod restart in a test environment before setting labelMasterCronJob.enabled: false. See docs/apps/redis/redis-ha.md. |
| redis-operator.redis-ha.podSecurityContext | object | `{"fsGroup":1000}` | Pod security context for Redis pods. fsGroup must match the redis container's GID (1000) so that mounted PVC data directories are writable by the redis process. |
| redis-operator.redis-ha.preDeleteJob | object | `{"image":{"repository":"docker.io/alpine/k8s","tag":"1.36.2@sha256:44ef4942e171939b9c665a4a84beb80e2dcdb9a24330d4651cfdfd2e9deecc47"},"nodeSelector":{}}` | pre-delete hook Job (templates/redis-ha-pre-delete.yaml) that drains the RedisReplication CR before the redis-operator's Deployment is torn down. |
| redis-operator.redis-ha.redisConfig.additionalRedisConfig | string | `""` | Optional extra redis.conf directives for runtime-configurable parameters. Note: startup-only parameters (e.g. databases) will NOT take effect here due to an operator limitation; use the databases field above instead. |
| redis-operator.redis-ha.redisExporter.podMonitor | object | `{"enabled":false,"interval":"30s","scrapeTimeout":"10s"}` | PodMonitor for the redis_exporter sidecar (port 9121). Requires Prometheus Operator CRDs (monitoring.coreos.com/v1). Enable via values-enable-observability.yaml. |
| redis-operator.redis-ha.serviceName | string | `"redis-ha"` | Grafana/Loki `app` + `service_name` label for the redis-ha pods (IN-2060). Without an explicit value the pods inherit `app.kubernetes.io/name: podiumd` from the shared chart labels and show up in Grafana as "podiumd" instead of "redis-ha". Set to "" to omit the override. |
| redis-operator.redis-ha.storage.volumeClaimTemplate.spec.resources.requests.storage | string | `"2Gi"` | Default storage per Redis replica. To increase, override in your environment values file. Note: managed-csi-premiumv2 supports online volume expansion — patch the PVC directly after resizing:   kubectl patch pvc <pvc-name> -n <namespace> -p '{"spec":{"resources":{"requests":{"storage":"8Gi"}}}}' |
| redis-operator.redisOperator.imageName | string | `"quay.io/opstree/redis-operator"` |  |
| redis-operator.redisOperator.imageTag | string | `"v0.26.0@sha256:1c6818e5e50553f9f3c1b91a8824ae5c1999a0c9416c794ca51431b7f0cb48c3"` |  |
| redis-operator.redisOperator.initContainerImageTag | string | `"v0.26.0@sha256:1c6818e5e50553f9f3c1b91a8824ae5c1999a0c9416c794ca51431b7f0cb48c3"` | Chart default for initContainerImageTag is a plain (non-digest-pinned) "v0.26.0"; override explicitly so the init container is digest-pinned like every other image here. |
| redis-operator.resources.limits.cpu | string | `"500m"` |  |
| redis-operator.resources.limits.memory | string | `"256Mi"` |  |
| redis-operator.resources.requests.cpu | string | `"100m"` |  |
| redis-operator.resources.requests.memory | string | `"128Mi"` |  |
| referentielijsten.configuration.data | string | `""` |  |
| referentielijsten.configuration.enabled | bool | `true` |  |
| referentielijsten.configuration.initContainer.enabled | bool | `false` |  |
| referentielijsten.configuration.job.backoffLimit | int | `6` |  |
| referentielijsten.configuration.job.enabled | bool | `true` |  |
| referentielijsten.configuration.job.resources | object | `{}` |  |
| referentielijsten.configuration.job.restartPolicy | string | `"OnFailure"` |  |
| referentielijsten.configuration.job.ttlSecondsAfterFinished | int | `600` |  |
| referentielijsten.configuration.oidcUrl | string | `"https://referentielijsten.example.nl"` |  |
| referentielijsten.configuration.pkceEnabled | bool | `false` | Enable PKCE (S256) on the Keycloak client. Requires mozilla_django_oidc >= 4.0.0 and oidc_use_pkce: true in configuration.data. |
| referentielijsten.configuration.secrets.keycloak_client_secret | string | `""` |  |
| referentielijsten.enabled | bool | `false` |  |
| referentielijsten.fullnameOverride | string | `"referentielijsten"` |  |
| referentielijsten.image.pullPolicy | string | `"IfNotPresent"` |  |
| referentielijsten.image.repository | string | `"maykinmedia/referentielijsten-api"` |  |
| referentielijsten.image.tag | string | `"0.7.4@sha256:5501b48fe9b988a72adba14308748e6b5928f851ec66d108bab2fe625eb831a3"` |  |
| referentielijsten.persistence.enabled | bool | `true` |  |
| referentielijsten.persistence.existingClaim | string | `"referentielijsten"` |  |
| referentielijsten.persistence.size | string | `"10Gi"` |  |
| referentielijsten.persistence.storageClassName | string | `"podiumd-standard"` |  |
| referentielijsten.persistentVolume.storageClassName | string | `"podiumd-standard"` |  |
| referentielijsten.persistentVolume.volumeAttributeShareName | string | `"referentielijsten"` |  |
| referentielijsten.replicaCount | int | `1` |  |
| referentielijsten.settings.allowedHosts | string | `"referentielijsten-nginx.podiumd.svc.cluster.local"` |  |
| referentielijsten.settings.cache.axes | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/15"` |  |
| referentielijsten.settings.cache.default | string | `"redis-ha-master.podiumd.svc.cluster.local:6379/15"` |  |
| referentielijsten.settings.debug | bool | `false` |  |
| referentielijsten.settings.disable2fa | bool | `false` |  |
| referentielijsten.settings.djangoSettingsModule | string | `"referentielijsten.conf.docker"` |  |
| referentielijsten.settings.email.port | int | `587` |  |
| referentielijsten.settings.email.useTLS | bool | `true` |  |
| referentielijsten.settings.environment | string | `""` |  |
| referentielijsten.settings.isHttps | bool | `true` |  |
| referentielijsten.settings.secretKey | string | `""` |  |
| referentielijsten.settings.useXForwardedHost | bool | `false` |  |
| referentielijsten.settings.uwsgi.maxRequests | string | `"1000"` |  |
| referentielijsten.settings.uwsgi.processes | string | `"2"` |  |
| referentielijsten.settings.uwsgi.threads | string | `"2"` |  |
| referentielijsten.tags.redis | bool | `false` |  |
| serviceAccount.annotations | object | `{}` |  |
| serviceAccount.automount | bool | `false` |  |
| serviceAccount.create | bool | `true` |  |
| serviceAccount.name | string | `""` |  |
| tags."eck-operator.enabled" | bool | `false` |  |
| tags.redis | bool | `false` |  |
| zaakbrug | object | `{"enabled":false,"frank":{"zakenApi":{"jwt":{"password":"","username":"zaakbrug"}}},"image":{"registry":"wearefrank","repository":"zaakbrug","tag":"1.26.15@sha256:101d1319ea5706289ce8f22c7f012a12b8378770bb2a5ebf761d72fa46c5ca97"},"oauthRoleMapping":{"IbisAdmin":"administrators","IbisDataAdmin":"dataadmin","IbisTester":"zaakbrug_admin"},"resources":{"limits":{"cpu":"2","memory":"6Gi"},"requests":{"cpu":"250m","memory":"5Gi"}},"staging":{"enabled":false}}` | --------------------------------------------------------------------------- |
| zaakbrug.frank | object | `{"zakenApi":{"jwt":{"password":"","username":"zaakbrug"}}}` | ------------------------------------------------------------------------- |
| zaakbrug.oauthRoleMapping | object | `{"IbisAdmin":"administrators","IbisDataAdmin":"dataadmin","IbisTester":"zaakbrug_admin"}` | ------------------------------------------------------------------------- |
| zac.auth.clientId | string | `"zac"` |  |
| zac.auth.pkceEnabled | bool | `false` | Enable PKCE (S256) on the Keycloak client. NOTE: ZAC does not currently support PKCE; this switch is reserved for when PKCE support is added to the ZAC OIDC client. |
| zac.auth.realm | string | `"podiumd"` |  |
| zac.auth.secret | string | `"changeme"` |  |
| zac.auth.server | string | `"http://keycloak.example.nl"` |  |
| zac.bagApi.apiKey | string | `"dummy"` |  |
| zac.bagApi.url | string | `"http://bag.example.nl"` |  |
| zac.brpApi.apiKey.header | string | `"x-api-key"` |  |
| zac.brpApi.apiKey.value | string | `"dummy"` |  |
| zac.brpApi.logLevel | string | `"OFF"` |  |
| zac.brpApi.protocollering.doelbinding.header | string | `""` |  |
| zac.brpApi.protocollering.doelbinding.perZaaktype | bool | `false` |  |
| zac.brpApi.protocollering.doelbinding.raadpleegmet | string | `"BRPACT-ZacPersoonBasis"` |  |
| zac.brpApi.protocollering.doelbinding.zoekmet | string | `"BRPACT-ZoekenAlgemeen"` |  |
| zac.brpApi.protocollering.enabled | bool | `false` |  |
| zac.brpApi.protocollering.gebruiker.header | string | `""` |  |
| zac.brpApi.protocollering.originOin.header | string | `""` |  |
| zac.brpApi.protocollering.originOin.oin | string | `""` |  |
| zac.brpApi.protocollering.toepassing.header | string | `""` |  |
| zac.brpApi.protocollering.toepassing.value | string | `""` |  |
| zac.brpApi.protocollering.verwerking.extendWithZaaktype | bool | `false` | New in chart 1.0.297+: whether to extend the verwerking register with the zaaktype, i.e. "<register>@<zaaktype>" instead of "<register>" on its own. Must be true for iConnect; leave false for eServices/2Secure. |
| zac.brpApi.protocollering.verwerking.header | string | `""` |  |
| zac.brpApi.protocollering.verwerking.register | string | `""` |  |
| zac.brpApi.url | string | `"http://brp.example.nl"` |  |
| zac.catalogusDomein | string | `"ALG"` |  |
| zac.contextUrl | string | `"http://zac.example.nl"` |  |
| zac.db.host | string | `"postgres"` |  |
| zac.db.name | string | `"zac"` |  |
| zac.db.password | string | `"changeme"` |  |
| zac.db.user | string | `"zac"` |  |
| zac.enabled | bool | `true` |  |
| zac.fullnameOverride | string | `"zac"` |  |
| zac.gemeente.code | string | `"007"` |  |
| zac.gemeente.mail | string | `"noreply@example.nl"` |  |
| zac.gemeente.naam | string | `"Example Gemeente"` |  |
| zac.global.curlImage.pullPolicy | string | `"IfNotPresent"` |  |
| zac.global.curlImage.repository | string | `"curlimages/curl"` |  |
| zac.global.curlImage.tag | string | `"8.21.0@sha256:7c12af72ceb38b7432ab85e1a265cff6ae58e06f95539d539b654f2cfa64bb13"` |  |
| zac.image.pullPolicy | string | `"IfNotPresent"` |  |
| zac.image.tag | string | `"5.4.4@sha256:2809ee2d2dc1ca166b88878a50d2850c7e972651f3ee5c35f44e92127c67773a"` |  |
| zac.initContainer.enabled | bool | `true` |  |
| zac.initContainer.resources.requests.cpu | string | `"50m"` |  |
| zac.initContainer.resources.requests.memory | string | `"256Mi"` |  |
| zac.keycloak.adminClient.id | string | `"zac-admin-client"` |  |
| zac.keycloak.adminClient.secret | string | `"changeme"` |  |
| zac.klantinteractiesApi.token | string | `"openklanttoken"` |  |
| zac.klantinteractiesApi.url | string | `"http://open-klant.example.nl"` |  |
| zac.kvkApi.apiKey | string | `"dummy"` |  |
| zac.kvkApi.url | string | `"http://kvk.example.nl"` |  |
| zac.livenessProbe.failureThreshold | int | `16` |  |
| zac.livenessProbe.path | string | `"/health/ready"` |  |
| zac.livenessProbe.periodSeconds | int | `30` |  |
| zac.livenessProbe.timeoutSeconds | int | `1` |  |
| zac.mail.smtp.password | string | `"dummy"` |  |
| zac.mail.smtp.port | string | `"587"` |  |
| zac.mail.smtp.server | string | `"mail.example.nl"` |  |
| zac.mail.smtp.username | string | `"dummy"` |  |
| zac.maxFileSizeMB | int | `150` |  |
| zac.nameOverride | string | `"zac"` |  |
| zac.nginx.client_max_body_size | string | `"150M"` |  |
| zac.nginx.enabled | bool | `true` |  |
| zac.nginx.image.pullPolicy | string | `"IfNotPresent"` |  |
| zac.nginx.image.repository | string | `"nginxinc/nginx-unprivileged"` |  |
| zac.nginx.image.tag | string | `"1.31.4@sha256:197f252f060ed357f2ab98d4256762d7d107c76f18ad8f0b9d5178854611566d"` |  |
| zac.nginx.resources.requests.cpu | string | `"50m"` |  |
| zac.nginx.resources.requests.memory | string | `"64Mi"` |  |
| zac.notificationsSecretKey | string | `"changeme"` |  |
| zac.objectenApi.token | string | `"objectentoken"` |  |
| zac.objectenApi.url | string | `"http://objecten.example.nl"` |  |
| zac.objecttypenApi.token | string | `"objecttypentoken"` |  |
| zac.objecttypenApi.url | string | `"http://objecttypen.example.nl"` |  |
| zac.office_converter.image.tag | string | `"8.36.0@sha256:87c16b9f364279d321bc9772d31fa58aa6abe036423c270698bd636c3a8e9466"` |  |
| zac.opa.image.tag | string | `"1.19.1-static@sha256:32bf41d914b1505fea13303f60587cc57bdd2902262177585fb208f5dde76d32"` |  |
| zac.opa.resources.requests.cpu | string | `"10m"` |  |
| zac.opa.resources.requests.memory | string | `"20Mi"` |  |
| zac.opa.sidecar | bool | `true` |  |
| zac.openForms.url | string | `"http://open-forms.example.nl"` |  |
| zac.organizations.bron.rsin | string | `"000000000"` |  |
| zac.organizations.verantwoordelijke.rsin | string | `"000000000"` |  |
| zac.pabcApi.apiKey | string | `""` |  |
| zac.pabcApi.url | string | `""` |  |
| zac.smartDocuments.authentication | string | `""` |  |
| zac.smartDocuments.enabled | bool | `false` |  |
| zac.smartDocuments.fixedUserName | string | `""` |  |
| zac.smartDocuments.url | string | `""` |  |
| zac.solr-operator.enabled | bool | `true` | turn functionality on/off |
| zac.solr-operator.image.tag | string | `"v0.9.1@sha256:38dd9719f0f6e799d04bb8c22fb5eaca3a9fe7ffaf313c296327c6cca02f3c1d"` |  |
| zac.solr-operator.nodeSelector | object | `{}` |  |
| zac.solr-operator.resources.limits.cpu | string | `"500m"` |  |
| zac.solr-operator.resources.limits.memory | string | `"256Mi"` |  |
| zac.solr-operator.resources.requests.cpu | string | `"100m"` |  |
| zac.solr-operator.resources.requests.memory | string | `"128Mi"` |  |
| zac.solr-operator.solr.busyBoxImage.pullPolicy | string | `"IfNotPresent"` |  |
| zac.solr-operator.solr.busyBoxImage.repository | string | `"library/busybox"` |  |
| zac.solr-operator.solr.busyBoxImage.tag | string | `"1.38.0-glibc@sha256:3ba030337caebbfc2232b22b1e435eb213b28e5844a34942c74555bf904a265a"` |  |
| zac.solr-operator.solr.dataStorage.persistent.reclaimPolicy | string | `"Retain"` | Retain PVCs when the operator scales down Solr (e.g. during node rotation). The default "Delete" causes the operator to destroy PVC data on scale-down, which requires a full index resync from another replica. |
| zac.solr-operator.solr.enabled | bool | `true` | set enabled to provision solrcloud as well |
| zac.solr-operator.solr.image.tag | string | `"9.10.1-slim@sha256:389b4a54b6a0b37a028a3f157e4d3b7031cf76def1b14bcaa225ea1e27f79ffb"` |  |
| zac.solr-operator.solr.javaMem | string | `"-Xms512m -Xmx768m"` | define memory settings for solr in the solrcloud |
| zac.solr-operator.solr.jobs.createZacCore | bool | `true` |  |
| zac.solr-operator.solr.resources.limits.cpu | string | `"2000m"` |  |
| zac.solr-operator.solr.resources.limits.memory | string | `"2Gi"` |  |
| zac.solr-operator.solr.resources.requests.cpu | string | `"500m"` |  |
| zac.solr-operator.solr.resources.requests.memory | string | `"1Gi"` |  |
| zac.solr-operator.watchNamespaces | string | `"podiumd"` | namespaces to watch for solr-operator |
| zac.solr-operator.zookeeper-operator | object | `{"crd":{"create":false},"hooks":{"image":{"tag":"v1.25.4@sha256:af5cea3f2e40138df90660c0c073d8b1506fb76c8602a9f48aceb5f4fb052ddc"}},"image":{"tag":"0.2.15@sha256:b2bc4042fdd8fea6613b04f2f602ba4aff1201e79ba35cd0e2df9f3327111b0e"},"resources":{"limits":{"cpu":"200m","memory":"128Mi"},"requests":{"cpu":"50m","memory":"64Mi"}},"watchNamespace":"podiumd","zookeeper":{"image":{"tag":"0.2.15@sha256:c498ebfb76a66f038075e2fa6148528d74d31ca1664f3257fdf82ee779eec9c8"},"resources":{"limits":{"cpu":"500m","memory":"512Mi"},"requests":{"cpu":"100m","memory":"256Mi"}},"storage":{"reclaimPolicy":"Retain"}}}` | install crds using https://github.com/pravega/zookeeper-operator/blob/master/charts/zookeeper-operator/templates/zookeeper.pravega.io_zookeeperclusters_crd.yaml |
| zac.solr-operator.zookeeper-operator.watchNamespace | string | `"podiumd"` | namespaces to watch for zookeeper-operator |
| zac.solr-operator.zookeeper-operator.zookeeper.storage.reclaimPolicy | string | `"Retain"` | Retain PVCs when the operator scales down ZooKeeper (e.g. during node rotation). The default "Delete" causes the operator to destroy PVC data on scale-down, which prevents the cluster from recovering quorum after a node replacement event. |
| zac.zacInternalEndpointsApiKey | string | `"dummy"` |  |
| zac.zgwApis.clientId | string | `"zac"` |  |
| zac.zgwApis.secret | string | `"changeme"` |  |
| zac.zgwApis.url | string | `"http://open-zaak.internal"` |  |
| zac.zgwApis.urlExtern | string | `"http://open-zaak.example.nl"` |  |
| zgw-office-addin.backend.image.tag | string | `"0.11.0@sha256:5b188e853531986e31709ed6cae130a891e0014cb267c43ac338b792c84a29ab"` |  |
| zgw-office-addin.backend.msalSecret | string | `""` |  |
| zgw-office-addin.backend.resources.requests.cpu | string | `"100m"` |  |
| zgw-office-addin.backend.resources.requests.memory | string | `"256Mi"` |  |
| zgw-office-addin.backend.zgwApis | object | `{"secret":"","url":"http://open-zaak.example.nl"}` | ZGW API configuration for integration with the ZGW APIs provider (OpenZaak) |
| zgw-office-addin.common.appEnv | string | `"production"` | Name of the environment (used for display purposes). Default "production" means that no indicator is appended to the DiscplayName in the manifests. |
| zgw-office-addin.common.frontendUrl | string | `"https://zgw-office-addin.example.nl"` | The frontend public URL where the manifest files and static js file are served |
| zgw-office-addin.common.msalClientId | string | `""` | MS Azure Client ID assigned to the Office Add-in application |
| zgw-office-addin.common.msalTenantId | string | `""` | MS Azure Tenant ID of the Office Add-in application |
| zgw-office-addin.common.podLabels | object | `{"app":"office-addin","service_name":"office-addin"}` | IN-2060: Grafana/Loki app + service_name labels on the office-addin pods. Without these the pods are attributed to the Helm release name ("podiumd"). Requires zgw-office-addin chart >= 0.0.89 (adds podLabels support). |
| zgw-office-addin.enabled | bool | `true` |  |
| zgw-office-addin.frontend.image.tag | string | `"0.11.0@sha256:9a6b3e9023b8cfba152a84dd7477e079490fc7d35562d32e0dc094be81a7f7a2"` |  |
| zgw-office-addin.frontend.resources.requests.cpu | string | `"50m"` |  |
| zgw-office-addin.frontend.resources.requests.memory | string | `"64Mi"` |  |
| zgw-office-addin.fullnameOverride | string | `"zgw-office-addin"` |  |
