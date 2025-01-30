# PodiumD

## PodiumD versions

### [2.2.0](https://github.com/Dimpact-Samenwerking/helm-charts/releases/tag/podiumd-2.2.0)

**PodiumD Helm chart version: 2.2.0**

Patch release for Open Inwoner bug fix.

| Component         | Version | Change  |
|-------------------|---------|---------|
| ClamAV            | 1.4.1   |         |
| Keycloak          | 24.0.5  |         |
| Objecten          | 2.4.4   |         |
| Objecttypen       | 2.2.2   |         |
| Open Formulieren  | 2.7.11  | Security patch |
| Open Inwoner      | 1.25.0  | Minor update |
| Open Klant        | 2.3.0   |         |
| Open Notificaties | 1.7.1   |         |
| Open Zaak         | 1.15.0  |         |


### [3.2.0](https://github.com/Dimpact-Samenwerking/helm-charts/releases/tag/podiumd-3.2.0)

**PodiumD Helm chart version: 3.2.0**


| Component         | Version | Change  |
|-------------------|---------|---------|
| ClamAV            | 1.4.1   |         |
| Keycloak          | 24.0.5  |         |
| Objecten          | 2.4.4   |         |
| Objecttypen       | 2.2.2   |         |
| Open Formulieren  | 2.7.11  | Security patch |
| Open Inwoner      | 1.25.0  | Minor update |
| Open Klant        | 2.3.0   |         |
| Open Notificaties | 1.7.1   |         |
| Open Zaak         | 1.15.0  |         |
| Kiss              | 0.5.1   | Patch update |

**PodiumD Helm chart version: 4.0.0**


| Component         | Version | Change          |
|-------------------|---------|-----------------|
| ClamAV            | 1.4.1   |                 |
| Keycloak          | 25.0.6  | Major update    |
| Objecten          | 3.0.0   | Major update    |
| Objecttypen       | 3.0.0   | Major update    |
| Open Formulieren  | 3.0.0   | Major update    |
| Open Inwoner      | 1.26.0  | Minor update    |
| Open Klant        | 2.4.0   | Minor update    |
| Open Notificaties | 1.8.0   | Minor update    |
| Open Zaak         | 1.17.0  | Minor update    |
| Kiss              | 0.6.0   | Minor update    |
| Zac               | 2.0.0   | Nieuw component |


## Add Used chart repositories:

    helm repo add bitnami https://charts.bitnami.com/bitnami
    helm repo add dimpact https://Dimpact-Samenwerking.github.io/helm-charts/
    helm repo add kiss-frontend https://raw.githubusercontent.com/Klantinteractie-Servicesysteem/KISS-frontend/main/helm
    helm repo add kiss-adapter https://raw.githubusercontent.com/ICATT-Menselijk-Digitaal/podiumd-adapter/main/helm
    helm repo add kiss-elastic https://raw.githubusercontent.com/Klantinteractie-Servicesysteem/.github/main/docs/scripts/elastic
    helm repo add maykinmedia https://maykinmedia.github.io/charts
    helm repo add wiremind https://wiremind.github.io/wiremind-helm-charts
    helm repo add openshift https://charts.openshift.io
    helm repo add solr https://solr.apache.org/charts
    helm repo add opentelemetry https://open-telemetry.github.io/opentelemetry-helm-charts
    helm repo add zac https://dimpact-zaakafhandelcomponent.github.io/charts

## PersistentVolume and PersistVolumeClaim resources

PersistentVolume and PersistentVolumeClaim resources are:
- created during a Helm install or upgrade if the PersistentVolumeClaim referenced by the `persistence.existingClaim` parameter does not yet exist
- never deleted during a Helm uninstall
                     
In order to determine whether the combination of PersistentVolume and PersistentVolumeClaim should be created,
the existence of the PersistentVolumeClaim referenced by the `persistence.existingClaim` parameter of the subchart, is checked.
If the referenced PersistentVolumeClaim does not exist both the PersistentVolume and PersistentVolumeClaim are created during Helm install.

As the PersistentVolume and PersistentVolumeClaim are never deleted during a Helm uninstall, they can be reused by the next Helm install.
PersistentVolume and PersistentVolumeClaim resources can only be manually deleted or updated after a Helm uninstall.
If they are deleted they will be recreated during the next Helm install.
If they are updated they will be reused by the next Helm install.
The following parameters impact the creation of PersistentVolume reources    

| Name                                          | Description                                                                                                                                          | Value |
|-----------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|-------|
| persistentVolume.volumeAttributeShareName     | Value of created PersistentVolume paramer `spec.csi.volumeAttributes.shareName`.<br/>Overrides the `volumeAttributeShareName` parameter per subchart | `""`  |
| persistentVolume.volumeAttributeResourceGroup | Value of created PersistentVolume paramer `spec.csi.volumeAttributes.resourceGroup`                                                                  | `""`  |
| persistentVolume.nodeStageSecretRefName       | Value of created PersistentVolume paramer `spec.csi.nodeStageSecretRef.name`                                                                         | `""`  |
| persistentVolume.nodeStageSecretRefNamespace  | Value of created PersistentVolume paramer `spec.csi.nodeStageSecretRef.namespace`                                                                    | `""`  |

## Parameters

### Global

The following components can be partially configured:
- Open Zaak
- Open Notificaties

Kanalen will only be added to Open Notificaties during Helm install, not on Helm upgrade.

| Name                                              | Description                                                                 | Value                                                           |
|---------------------------------------------------|-----------------------------------------------------------------------------|-----------------------------------------------------------------|
| global.configuration.enabled                      | Whether component configuration is enabled                                  | `true`                                                          |
| global.configuration.overwrite                    | Whether existing component configuration is overwritten                     | `true`                                                          |
| global.configuration.organization                 | Organization name                                                           | `Example gemeente`                                              |
| global.configuration.openzaakAutorisatiesApi      | Autorisaties API                                                            | `http//openzaak.podiumd.svc.cluster.local/autorisaties/api/v1/` |
| global.configuration.notificatiesApi              | Notificaties API                                                            | `http://opennotificaties.podiumd.svc.cluster.local/api/v1/`     |
| global.configuration.notificatiesOpenzaakClientId | ClientId used by Open Notificaties to access autorisaties API               | `notificaties`                                                  |
| global.configuration.notificatiesOpenzaakSecret   | Secret used by Open Notificaties to access autorisaties API                 | `notificaties-secret`                                           |
| global.configuration.openzaakNotificatiesClientId | ClientId used by Open Zaak to send notifications                            | `openzaak`                                                      |
| global.configuration.openzaakNotificatiesSecret   | Secret used by Open Zaak to send notifications                              | `openzaak-secret`                                               |
| global.imageRegistry                              | Image registry used by Keycloak, Redis, RabitMQ and Elastic                 | `""`                                                            | 
| global.settings.databaseHost                      | Database host used bij objecten, objecttypen, openinwoner, opennotificaties | `""`                                                            | 

### keycloak

| Name                                        | Description                                                                 | Value                               |
|---------------------------------------------|-----------------------------------------------------------------------------|-------------------------------------|
| keycloak.enabled                            | Boolean to override the installation of Keycloak                            |                                     |
| keycloak.config.realmDisplayName            | Name displayed in Keycloak when logging into the podiumd realm              | `PodiumD`                           |
| keycloak.config.realmFrontendUrl            | URL of keycloak for logging in to podiumd applications (podiumd realm)      | `https://keycloak.example.nl`       |
| keycloak.config.adminFrontendUrl            | URL of keycloak for logging in to admin console (master realm)              | `https://keycloak-admin.example.nl` |
| keycloak.auth.adminUser                     | Keycloak administrator user                                                 | `admin`                             |
| keycloak.auth.adminPassword                 | Keycloak administrator password                                             | `ChangeMeNow`                       |
| keycloak.externalDatabase.host              | Database host                                                               | `""`                                |
| keycloak.externalDatabase.database          | Database name                                                               | `""`                                |
| keycloak.externalDatabase.user              | Database username                                                           | `""`                                |
| keycloak.externalDatabase.password          | Database user password                                                      | `""`                                |
| keycloak.image.repository                   | Keycloak image repository                                                   | `bitnami/keycloak`                  |
| keycloak.image.tag                          | Keycloak image tag                                                          | `24.0.5-debian-12-r0`               |
| keycloak.image.pullPolicy                   | Keycloak image pull policy                                                  | `IfNotPresent`                      |
| keycloak.nodeSelector                       | Node labels for Keycloak pod assignment. Evaluated as a template            | `{}`                                |
| keycloak.resources                          | Container requests and limits                                               | See values.yaml                     |
| keycloak.keycloakConfigCli.enabled          | Whether Keycloak configuration is enabled                                   | `true`                              |
| keycloak.keycloakConfigCli.image.repository | Keycloak config cli image repository                                        | `bitnami/keycloak-config-cli`       |
| keycloak.keycloakConfigCli.image.tag        | Keycloak config cli image tag                                               | `5.12.0-debian-12-r5`               |
| keycloak.keycloakConfigCli.image.pullPolicy | Keycloak config cli image pull policy                                       | `IfNotPresent`                      |
| keycloak.keycloakConfigCli.nodeSelector     | Node labels for Keycloak config cli pod assignment. Evaluated as a template | `{}`                                |
 
### Open LDAP

| Name                                               | Description                                                                                                                                           | Value                 |
|----------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------|
| openldap.enabled                                   | Boolean to override the installation of OpenLDAP                                                                                                      |                       |
| openldap.adminUsername                             | LDAP administrator username                                                                                                                           | `"admin"`             |
| openldap.adminPassword                             | LDAP administrator password                                                                                                                           | `"admin"`             |
| openldap.root                                      | Root of LDAP tree                                                                                                                                     | `"dc=dimpact,dc=org"` |
| openldap.persistence.existingClaim                 | Manually managed Persistent Volume and Claim                                                                                                          | `openldap`            |
| openldap.persistence.subpath                       | Path within the volume                                                                                                                                | `openldap`            |
| openldap.persistence.size                          | Size of created PersistentVolume                                                                                                                      | `1Gi`                 |
| openldap.persistentVolume.volumeAttributeShareName | Value of created PersistentVolume paramer `spec.csi.volumeAttributes.shareName`.<br/>Overriden by `.Values.persistentVolume.volumeAttributeShareName` | `openldap`            |
| openldap.image.repository                          | Image repository                                                                                                                                      | `bitnami/openldap`    |
| openldap.image.tag                                 | Image tag                                                                                                                                             | `2.6.8`               |
| openldap.image.pullPolicy                          | Image pull policy                                                                                                                                     | `IfNotPresent`        |
| openldap.nodeSelector                              | Node labels for pod assignment. Evaluated as a template                                                                                               | `{}`                  |
| openldap.resources                                 | Container requests and limits                                                                                                                         | See values.yaml       |

### ClamAV

| Name                    | Description                                                                    | Value           |
|-------------------------|--------------------------------------------------------------------------------|-----------------|
| clamav.enabled          | Boolean to override the installation of ClamAV                                 |                 |
| clamav.clamdConfig      | Override default clamd.conf file. (https://linux.die.net/man/5/clamd.conf)     | see Chart.yaml  |
| clamav.freshclamConfig  | Override default clamd.conf file. (https://linux.die.net/man/5/freshclam.conf) | see Chart.yaml  |
| clamav.image.repository | Image repository                                                               | `clamav/clamav` |
| clamav.image.tag        | Image tag                                                                      | `1.3.1`         |
| clamav.image.pullPolicy | Image pull policy                                                              | `IfNotPresent`  |
| clamav.nodeSelector     | Node labels for pod assignment. Evaluated as a template                        | `{}`            |
| clamav.resources        | Container requests and limits                                                  | See values.yaml |


### BRP Mock

| Name                              | Description                                             | Value                                                 |
|-----------------------------------|---------------------------------------------------------|-------------------------------------------------------|
| brpmock.enabled                   | Boolean to override the installation of BRP Mock        | `false`                                               |
| brpmock.nodeSelector              | Node labels for pod assignment. Evaluated as a template | `{}`                                                  |
| brpmock.brpproxy.image.repository | Proxy image repository                                  | `iswish/haal-centraal-brp-bevragen-proxy`             |
| brpmock.brpproxy.image.tag        | Proxy image tag                                         | `2.0.20`                                              |
| brpmock.brpproxy.image.pullPolicy | Proxy image pull policy                                 | `IfNotPresent`                                        |
| brpmock.brpproxy.resources        | Proxy container requests and limits                     | See values.yaml                                       |
| brpmock.gbamock.image.repository  | Mock image repository                                   | `ghcr.io/brp-api/haal-centraal-brp-bevragen-gba-mock` |
| brpmock.gbamock.image.tag         | Mock image tag                                          | `2.0.8`                                               |
| brpmock.gbamock.image.pullPolicy  | Mock image pull policy                                  | `IfNotPresent`                                        |
| brpmock.gbamock.resources         | Mock container requests and limits                      | See values.yaml                                       |


### Open Zaak

| Name                                               | Description                                                                                                                                           | Value                                                          |
|----------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------|
| openzaak.enabled                                   | Boolean to override the installation of Open Zaak                                                                                                     |                                                                |
| openzaak.configuration.enabled                     | Boolean to override whether Open Zaak configuration is enabled                                                                                        | `true`                                                         |
| openzaak.configuration.overwrite                   | Boolean to override whether existing Open Zaak configuration is overwritten                                                                           | `true`                                                         |
| openzaak.configuration.oidcUrl                     | OpenID Connect client url                                                                                                                             | `https://openzaak.example.nl`                                  |
| openzaak.configuration.oidcSecret                  | OpenID Connect client secret                                                                                                                          | `<openzaak>`                                                   |
| openzaak.configuration.sites.openzaakDomain        | Domein (i.e. openzaak.example.nl)                                                                                                                     | `""`                                                           |
| openzaak.configuration.superuser.username          | Superuser username                                                                                                                                    | `""`                                                           |
| openzaak.configuration.superuser.password          | Superuser password                                                                                                                                    | `""`                                                           |
| openzaak.configuration.superuser.email             | Superuser email                                                                                                                                       | `""`                                                           |
| openzaak.configuration.selectieLijst.enabled       | Configure selectie lijsten                                                                                                                            | `false`                                                        |
| openzaak.configuration.selectieLijst.ApiRoot       | Selectie lijsten API root                                                                                                                             | `https://selectielijst.openzaak.nl/api/v1/`                    |
| openzaak.configuration.selectieLijst.ApiOas        | Selectie lijsten OAS                                                                                                                                  | `https://selectielijst.openzaak.nl/api/v1/schema/openapi.yaml` |
| openzaak.configuration.selectieLijst.AllowedYears  | Selectie lijsten allowed years                                                                                                                        | `[2017, 2020]`                                                 |
| openzaak.configuration.selectieLijst.DefaultYear   | Selectie lijsten default year                                                                                                                         | `2020`                                                         |
| openzaak.settings.allowedHosts                     | List if allowed hostnames<br/>(i.e. "openzaak.example.nl,openzaak-nginx.podiumd.svc.cluster.local")                                                   | `openzaak-nginx.podiumd.svc.cluster.local`                     |
| openzaak.settings.database.host                    | Database host                                                                                                                                         | `""`                                                           |
| openzaak.settings.database.name                    | Database name                                                                                                                                         | `""`                                                           |
| openzaak.settings.database.username                | Database username                                                                                                                                     | `""`                                                           |
| openzaak.settings.database.password                | Database user password                                                                                                                                | `""`                                                           |
| openzaak.settings.database.sslmode                 | Database SSL mode                                                                                                                                     | `prefer`                                                       |
| openzaak.settings.email.host                       | Email host                                                                                                                                            | `localhost`                                                    |
| openzaak.settings.email.port                       | Email port                                                                                                                                            | `587`                                                          |
| openzaak.settings.email.username                   | Email username                                                                                                                                        | `""`                                                           |
| openzaak.settings.email.password                   | Email user password                                                                                                                                   | `""`                                                           |
| openzaak.settings.email.useTLS                     | Email use TLS                                                                                                                                         | `true`                                                         |
| openzaak.settings.secretKey                        | Django secret key. Generate secret key at https://djecrety.ir/                                                                                        | `""`                                                           |
| openzaak.settings.environment                      | Sets the `ENVIRONMENT` variable                                                                                                                       | `""`                                                           |
| openzaak.settings.isHttps                          | Use HTTPS                                                                                                                                             | `true`                                                         |
| openzaak.settings.debug                            | Enable debug mode                                                                                                                                     | `false`                                                        |
| openzaak.settings.numProxies                       | Number of proxies                                                                                                                                     | `1`                                                            |
| openzaak.settings.sentry.dsn                       | Url to Sentry (i.e https://sentry.example.com/111)                                                                                                    | `""`                                                           |
| openzaak.persistence.existingClaim                 | Manually managed Persistent Volume and Claim                                                                                                          | `openzaak`                                                     |
| openzaak.persistence.mediaMountSubpath             | Media mount subpath                                                                                                                                   | `openzaak/media`                                               |
| openzaak.persistence.privateMediaMountSubpath      | Private media mount subpath                                                                                                                           | `openzaak/private_media`                                       |
| openzaak.persistence.size                          | Size of created PersistentVolume                                                                                                                      | `10Gi`                                                         |
| openzaak.persistentVolume.volumeAttributeShareName | Value of created PersistentVolume paramer `spec.csi.volumeAttributes.shareName`.<br/>Overriden by `.Values.persistentVolume.volumeAttributeShareName` | `openzaak`                                                     |
| openzaak.image.repository                          | Image repository                                                                                                                                      | `openzaak/open-zaak`                                           |
| openzaak.image.tag                                 | Image tag                                                                                                                                             | `1.15.0`                                                       |
| openzaak.image.pullPolicy                          | Image pull policy                                                                                                                                     | `IfNotPresent`                                                 |
| openzaak.nodeSelector                              | Node labels for pod assignment. Evaluated as a template                                                                                               | `{}`                                                           |
| openzaak.resources                                 | Container requests and limits                                                                                                                         | See values.yaml                                                |
| openzaak.worker.resources                          | Worker container requests and limits                                                                                                                  | See values.yaml                                                |
| openzaak.nginx.image.repository                    | Nginx image repository                                                                                                                                | `nginxinc/nginx-unprivileged`                                  |
| openzaak.nginx.image.tag                           | Mginx image tag                                                                                                                                       | `stable`                                                       |
| openzaak.nginx.image.pullPolicy                    | Nginx image pull policy                                                                                                                               | `IfNotPresent`                                                 |
| openzaak.nginx.resources                           | Nginx container requests and limits                                                                                                                   | See values.yaml                                                |
| openzaak.redis.image.registry                      | Redis image registry                                                                                                                                  | `docker.io`                                                    |
| openzaak.redis.image.repository                    | Redis image repository                                                                                                                                | `bitnami/redis`                                                |
| openzaak.redis.image.tag                           | Redis image tag                                                                                                                                       | `7.0.5-debian-11-r25`                                          |
| openzaak.redis.image.pullPolicy                    | Redis image pul policy                                                                                                                                | `IfNotPresent`                                                 |
| openzaak.redis.master.nodeSelector                 | Redis node labels for pod assignment. Evaluated as a template                                                                                         | `{}`                                                           |

### Open Notificaties

| Name                                                                 | Description                                                                                                                                           | Value                                        |
|----------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------|
| opennotificaties.enabled                                             | Boolean to override the installation of Open Notificatues                                                                                             | `true`                                       |
| opennotificaties.configuration.enabled                               | Boolean to override whether Open Notificaties configuration is enabled                                                                                | `true`                                       |
| opennotificaties.configuration.overwrite                             | Boolean to override whether existing Open Notificaties configuration is overwritten                                                                   | `true`                                       |
| opennotificaties.configuration.oidcUrl                               | OpenID Connect client url                                                                                                                             | `https://opennotificaties.example.nl`        |
| opennotificaties.configuration.oidcSecret                            | OpenID Connect client secret                                                                                                                          | `<opennotificaties>`                         |
| opennotificaties.configuration.sites.notificatiesDomain              | Domein (i.e. opennotificaties.example.nl)                                                                                                             | `""`                                         |
| opennotificaties.configuration.superuser.username                    | Superuser username                                                                                                                                    | `""`                                         |
| opennotificaties.configuration.superuser.password                    | Superuser password                                                                                                                                    | `""`                                         |
| opennotificaties.configuration.superuser.email                       | Superuser email                                                                                                                                       | `""`                                         |
| opennotificaties.settings.allowedHosts                               | List if allowed hostnames<br/>(i.e. "openzaak.example.nl,openzaak-nginx.podiumd.svc.cluster.local")                                                   | `opennotificaties.podiumd.svc.cluster.local` |
| opennotificaties.settings.database.host                              | Database host. Overides global.settings.databaseHost                                                                                                  | `""`                                         |
| opennotificaties.settings.database.port                              | Database port                                                                                                                                         | `5432`                                       |
| opennotificaties.settings.database.name                              | Database name                                                                                                                                         | `""`                                         |
| opennotificaties.settings.database.username                          | Database username                                                                                                                                     | `""`                                         |
| opennotificaties.settings.database.password                          | Database user password                                                                                                                                | `""`                                         |
| opennotificaties.settings.database.sslmode                           | Database SSL mode                                                                                                                                     | `prefer`                                     |
| opennotificaties.settings.email.host                                 | Email host                                                                                                                                            | `localhost`                                  |
| opennotificaties.settings.email.port                                 | Email port                                                                                                                                            | `587`                                        |
| opennotificaties.settings.email.username                             | Email username                                                                                                                                        | `""`                                         |
| opennotificaties.settings.email.password                             | Email user password                                                                                                                                   | `""`                                         |
| opennotificaties.settings.email.useTLS                               | Email use TLS                                                                                                                                         | `true`                                       |
| opennotificaties.settings.secretKey                                  | Django secret key. Generate secret key at https://djecrety.ir/                                                                                        | `""`                                         |
| opennotificaties.settings.environment                                | Sets the `ENVIRONMENT` variable                                                                                                                       | `""`                                         |
| opennotificaties.settings.isHttps                                    | Use HTTPS                                                                                                                                             | `true`                                       |
| opennotificaties.settings.debug                                      | Enable debug mode                                                                                                                                     | `false`                                      |
| opennotificaties.settings.cleanOldNotifications.enabled              | Enable leaning of logged notifications                                                                                                                | `true`                                       |
| opennotificaties.settings.cleanOldNotifications.daysRetained         | Number of days to retain logged notifications                                                                                                         | `30`                                         |
| opennotificaties.settings.cleanOldNotifications.cronjob.schedule     | Schedule to run the clean logged notifications cronjob                                                                                                | `"0 0 * * *"`                                |
| opennotificaties.settings.cleanOldNotifications.cronjob.historyLimit | Number of succesful and failed jobs to keep                                                                                                           | `1`                                          |
| opennotificaties.settings.maxRetries                                 | Maximum number of automatic retries. After this amount of retries,<br/>Open Notificaties stops trying to deliver the message                          | `5`                                          |
| opennotificaties.settings.retryBackoff                               | A factor applied to the exponential backoff.<br/>This allows you to tune how quickly automatic retries are performed                                  | `3`                                          |
| opennotificaties.settings.retryBackoffMax                            | Upper limit to the exponential backoff time                                                                                                           | `48`                                         |
| opennotificaties.settings.numProxies                                 | Number of proxies                                                                                                                                     | `1`                                          |
| opennotificaties.settings.sentry.dsn                                 | Url to Sentry (i.e https://sentry.example.com/111)                                                                                                    | `""`                                         |
| opennotificaties.persistence.existingClaim                           | Manually managed Persistent Volume and Claim                                                                                                          | `opennotificaties`                           |
| opennotificaties.persistence.mediaMountSubpath                       | Media mount subpath                                                                                                                                   | `opennotificaties/media`                     |
| opennotificaties.persistence.size                                    | Size of created PersistentVolume                                                                                                                      | `10Gi`                                       |
| opennotificaties.persistentVolume.volumeAttributeShareName           | Value of created PersistentVolume paramer `spec.csi.volumeAttributes.shareName`.<br/>Overriden by `.Values.persistentVolume.volumeAttributeShareName` | `opennotificaties`                           |
| opennotificaties.image.repository                                    | Image repository                                                                                                                                      | `openzaak/open-notificaties`                 |
| opennotificaties.image.tag                                           | Image tag                                                                                                                                             | `1.7.1`                                      |
| opennotificaties.image.pullPolicy                                    | Image pull policy                                                                                                                                     | `IfNotPresent`                               |
| opennotificaties.nodeSelector                                        | Node labels for pod assignment. Evaluated as a template                                                                                               | `{}`                                         |
| opennotificaties.resources                                           | Container requests and limits                                                                                                                         | See values.yaml                              |
| opennotificaties.worker.resources                                    | Worker container requests and limits                                                                                                                  | See values.yaml                              |
| opennotificaties.rabbitmq.auth.username                              | RabitMQ username                                                                                                                                      | `guest`                                      |
| opennotificaties.rabbitmq.auth.password                              | RabitMQ user password                                                                                                                                 | `guest`                                      |
| opennotificaties.rabbitmq.auth.erlangCookie                          | RabitMQ erlang cookie                                                                                                                                 | `SUPER-SECRET`                               |
| opennotificaties.rabbitmq.image.repository                           | RabitMQ image repository                                                                                                                              | `bitnami/rabbitmq`                           |
| opennotificaties.rabbitmq.image.tag                                  | RabitMQ image tag                                                                                                                                     | `3.11.8-debian-11-r0`                        |
| opennotificaties.rabbitmq.image.pullPolicy                           | RabitMQ image pul policy                                                                                                                              | `IfNotPresent`                               |
| opennotificaties.rabbitmq.nodeSelector                               | RabitMQ node labels for pod assignment. Evaluated as a template                                                                                       | `{}`                                         |
| opennotificaties.rabbitmq.resources                                  | RabitMQ container requests and limits                                                                                                                 | See values.yaml                              |
| opennotificaties.redis.image.registry                                | Redis image registry                                                                                                                                  | `docker.io`                                  |
| opennotificaties.redis.image.repository                              | Redis image repository                                                                                                                                | `bitnami/redis`                              |
| opennotificaties.redis.image.tag                                     | Redis image tag                                                                                                                                       | `7.0.5-debian-11-r25`                        |
| opennotificaties.redis.image.pullPolicy                              | Redis image pul policy                                                                                                                                | `IfNotPresent`                               |
| opennotificaties.redis.master.nodeSelector                           | Redis node labels for pod assignment. Evaluated as a template                                                                                         | `{}`                                         |

### Objecten

| Name                                               | Description                                                                                                                                           | Value                                |
|----------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------|
| objecten.enabled                                   | Boolean to override the installation of Objecten                                                                                                      |                                      |
| objecten.configuration.oidcUrl                     | OpenID Connect client url                                                                                                                             | `https://objecten.example.nl`        |
| objecten.configuration.oidcSecret                  | OpenID Connect client secret                                                                                                                          | `<objecten>`                         |
| objecten.settings.allowedHosts                     | List if allowed hostnames<br/>(i.e. "objecten.example.nl,objecten.podiumd.svc.cluster.local")                                                         | `objecten.podiumd.svc.cluster.local` |
| objecten.settings.database.host                    | Database host. Overides global.settings.databaseHost                                                                                                  | `""`                                 |
| objecten.settings.database.port                    | Database port                                                                                                                                         | `5432`                               |
| objecten.settings.database.name                    | Database name                                                                                                                                         | `""`                                 |
| objecten.settings.database.username                | Database username                                                                                                                                     | `""`                                 |
| objecten.settings.database.password                | Database user password                                                                                                                                | `""`                                 |
| objecten.settings.database.sslmode                 | Database SSL mode                                                                                                                                     | `prefer`                             |
| objecten.settings.email.host                       | Email host                                                                                                                                            | `localhost`                          |
| objecten.settings.email.port                       | Email port                                                                                                                                            | `587`                                |
| objecten.settings.email.username                   | Email username                                                                                                                                        | `""`                                 |
| objecten.settings.email.password                   | Email user password                                                                                                                                   | `""`                                 |
| objecten.settings.email.useTLS                     | Email use TLS                                                                                                                                         | `true`                               |
| objecten.settings.secretKey                        | Django secret key. Generate secret key at https://djecrety.ir/                                                                                        | `""`                                 |
| objecten.settings.environment                      | Sets the `ENVIRONMENT` variable                                                                                                                       | `""`                                 |
| objecten.settings.isHttps                          | Use HTTPS                                                                                                                                             | `true`                               |
| objecten.settings.debug                            | Enable debug mode                                                                                                                                     | `false`                              |
| objecten.settings.sentry.dsn                       | Url to Sentry (i.e https://sentry.example.com/111)                                                                                                    | `""`                                 |
| objecten.persistence.existingClaim                 | Manually managed Persistent Volume and Claim                                                                                                          | `objecten`                           |
| objecten.persistence.mediaMountSubpath             | Media mount subpath                                                                                                                                   | `objecten/media`                     |
| objecten.persistence.size                          | Size of created PersistentVolume                                                                                                                      | `10Gi`                               |
| objecten.persistentVolume.volumeAttributeShareName | Value of created PersistentVolume paramer `spec.csi.volumeAttributes.shareName`.<br/>Overriden by `.Values.persistentVolume.volumeAttributeShareName` | `objecten`                           |
| objecten.image.repository                          | Image repository                                                                                                                                      | `maykinmedia/objects-api`            |
| objecten.image.tag                                 | Image tag                                                                                                                                             | `2.4.4`                              |
| objecten.image.pullPolicy                          | Image pull policy                                                                                                                                     | `IfNotPresent`                       |
| objecten.nodeSelector                              | Node labels for pod assignment. Evaluated as a template                                                                                               | `{}`                                 |
| objecten.resources                                 | Container requests and limits                                                                                                                         | see values.yaml                      |
| objecten.worker.resources                          | Worker container requests and limits                                                                                                                  | see values.yaml                      |
| objecten.redis.image.registry                      | Redis image registry                                                                                                                                  | `docker.io`                          |
| objecten.redis.image.repository                    | Redis image repository                                                                                                                                | `bitnami/redis`                      |
| objecten.redis.image.tag                           | Redis image tag                                                                                                                                       | `7.0.5-debian-11-r25`                |
| objecten.redis.image.pullPolicy                    | Redis image pul policy                                                                                                                                | `IfNotPresent`                       |
| objecten.redis.master.persistence.enabled          | Redis master persistence enabled                                                                                                                      | `true`                               |
| objecten.redis.master.persistence.size             | Redis master persistence size                                                                                                                         | `"8Gi"`                              |
| objecten.redis.master.persistence.storageClass     | Redis master persistence storage class                                                                                                                | `""`                                 |
| objecten.redis.master.nodeSelector                 | Redis node labels for pod assignment. Evaluated as a template                                                                                         | `{}`                                 |

### Objecttypen

| Name                                              | Description                                                                                         | Value                                   |
|---------------------------------------------------|-----------------------------------------------------------------------------------------------------|-----------------------------------------|
| objecttypen.enabled                               | Boolean to override the installation of objecttypen                                                 |                                         |
| objecttypen.configuration.oidcUrl                 | OpenID Connect client url                                                                           | `https://objecttypen.example.nl`        |
| objecttypen.configuration.oidcSecret              | OpenID Connect client secret                                                                        | `<objecttypen>`                         |
| objecttypen.settings.allowedHosts                 | List if allowed hostnames<br/>(i.e. "objecttypen.example.nl,objecttypen.podiumd.svc.cluster.local") | `objecttypen.podiumd.svc.cluster.local` |
| objecttypen.settings.database.host                | Database host. Overides global.settings.databaseHost                                                | `""`                                    |
| objecttypen.settings.database.port                | Database port                                                                                       | `5432`                                  |
| objecttypen.settings.database.name                | Database name                                                                                       | `""`                                    |
| objecttypen.settings.database.username            | Database username                                                                                   | `""`                                    |
| objecttypen.settings.database.password            | Database user password                                                                              | `""`                                    |
| objecttypen.settings.database.sslmode             | Database SSL mode                                                                                   | `prefer`                                |
| objecttypen.settings.email.host                   | Email host                                                                                          | `localhost`                             |
| objecttypen.settings.email.port                   | Email port                                                                                          | `587`                                   |
| objecttypen.settings.email.username               | Email username                                                                                      | `""`                                    |
| objecttypen.settings.email.password               | Email user password                                                                                 | `""`                                    |
| objecttypen.settings.email.useTLS                 | Email use TLS                                                                                       | `true`                                  |
| objecttypen.settings.secretKey                    | Django secret key. Generate secret key at https://djecrety.ir/                                      | `""`                                    |
| objecttypen.settings.environment                  | Sets the `ENVIRONMENT` variable                                                                     | `""`                                    |
| objecttypen.settings.debug                        | Enable debug mode                                                                                   | `false`                                 |
| objecttypen.settings.sentry.dsn                   | Url to Sentry (i.e https://sentry.example.com/111)                                                  | `""`                                    |
| objecttypen.image.repository                      | Image repository                                                                                    | `maykinmedia/objecttypes-api`           |
| objecttypen.image.tag                             | Image tag                                                                                           | `2.2.2`                                 |
| objecttypen.image.pullPolicy                      | Image pull policy                                                                                   | `IfNotPresent`                          |
| objecttypen.nodeSelector                          | Node labels for pod assignment. Evaluated as a template                                             | `{}`                                    |
| objecttypen.resources                             | Container requests and limits                                                                       | See values.yaml                         |
| objecttypen.redis.image.registry                  | Redis image registry                                                                                | `docker.io`                             |
| objecttypen.redis.image.repository                | Redis image repository                                                                              | `bitnami/redis`                         |
| objecttypen.redis.image.tag                       | Redis image tag                                                                                     | `7.0.5-debian-11-r25`                   |
| objecttypen.redis.image.pullPolicy                | Redis image pul policy                                                                              | `IfNotPresent`                          |
| objecttypen.redis.master.persistence.enabled      | Redis master persistence enabled                                                                    | `true`                                  |
| objecttypen.redis.master.persistence.size         | Redis master persistence size                                                                       | `"8Gi"`                                 |
| objecttypen.redis.master.persistence.storageClass | Redis master persistence storage class                                                              | `""`                                    |
| objecttypen.redis.master.nodeSelector             | Redis node labels for pod assignment. Evaluated as a template                                       | `{}`                                    |

### Open Klant

| Name                                            | Description                                                                                     | Value                                 |
|-------------------------------------------------|-------------------------------------------------------------------------------------------------|---------------------------------------|
| openklant.configuration.oidcUrl                 | OpenID Connect client url                                                                       | `https://openklant.example.nl`        |
| openklant.configuration.oidcSecret              | OpenID Connect client secret                                                                    | `<openklant>`                         |
| openklant.settings.allowedHosts                 | List if allowed hostnames<br/>(i.e. "openklant.example.nl,openklant.podiumd.svc.cluster.local") | `openklant.podiumd.svc.cluster.local` |
| openklant.settings.database.host                | Database host                                                                                   | `""`                                  |
| openklant.settings.database.port                | Database port                                                                                   | `5432`                                |
| openklant.settings.database.name                | Database name                                                                                   | `""`                                  |
| openklant.settings.database.username            | Database username                                                                               | `""`                                  |
| openklant.settings.database.password            | Database user password                                                                          | `""`                                  |
| openklant.settings.database.sslmode             | Database SSL mode                                                                               | `prefer`                              |
| openklant.settings.email.host                   | Email host                                                                                      | `localhost`                           |
| openklant.settings.email.port                   | Email port                                                                                      | `587`                                 |
| openklant.settings.email.username               | Email username                                                                                  | `""`                                  |
| openklant.settings.email.password               | Email user password                                                                             | `""`                                  |
| openklant.settings.email.useTLS                 | Email use TLS                                                                                   | `true`                                |
| openklant.settings.secretKey                    | Django secret key. Generate secret key at https://djecrety.ir/                                  | `""`                                  |
| openklant.settings.environment                  | Sets the `ENVIRONMENT` variable                                                                 | `""`                                  |
| openklant.settings.isHttps                      | Use HTTPS                                                                                       | `true`                                |
| openklant.settings.debug                        | Enable debug mode                                                                               | `false`                               |
| openklant.settings.sentry.dsn                   | Url to Sentry (i.e https://sentry.example.com/111)                                              | `""`                                  |
| openklant.image.repository                      | Image repository                                                                                | `maykinmedia/objects-api`             |
| openklant.image.tag                             | Image tag                                                                                       | `2.3.0`                               |
| openklant.image.pullPolicy                      | Image pull policy                                                                               | `IfNotPresent`                        |
| openklant.nodeSelector                          | Node labels for pod assignment. Evaluated as a template                                         | `{}`                                  |
| openklant.resources                             | Container requests and limits                                                                   | See values.yaml                       |
| openklant.worker.resources                      | Worker container requests and limits                                                            | See values.yaml                       |
| openklant.redis.image.registry                  | Redis image registry                                                                            | `docker.io`                           |
| openklant.redis.image.repository                | Redis image repository                                                                          | `bitnami/redis`                       |
| openklant.redis.image.tag                       | Redis image tag                                                                                 | `7.0.5-debian-11-r25`                 |
| openklant.redis.image.pullPolicy                | Redis image pul policy                                                                          | `IfNotPresent`                        |
| openklant.redis.master.persistence.enabled      | Redis master persistence enabled                                                                | `true`                                |
| openklant.redis.master.persistence.size         | Redis master persistence size                                                                   | `"8Gi"`                               |
| openklant.redis.master.persistence.storageClass | Redis master persistence storage class                                                          | `""`                                  |
| openklant.redis.master.nodeSelector             | Redis node labels for pod assignment. Evaluated as a template                                   | `{}`                                  |

### Open Formulieren

| Name                                                      | Description                                                                                                                                           | Value                                             |
|-----------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------|
| openformulieren.enabled                                   | Boolean to override the installation of Open Formulieren                                                                                              |                                                   |
| openformulieren.configuration.oidcUrl                     | OpenID Connect client url                                                                                                                             | `https://openformulieren.example.nl`              |
| openformulieren.configuration.oidcSecret                  | OpenID Connect client secret                                                                                                                          | `<openformulieren>`                               |
| openformulieren.settings.allowedHosts                     | List of allowed hostnames<br/>(i.e. "openformulieren.example.nl,openformulieren-nginx.podiumd.svc.cluster.local")                                     | `openformulieren-nginx.podiumd.svc.cluster.local` |
| openformulieren.settings.baseUrl                          | Base URL (i.e. "https://openformulieren.example.nl")                                                                                                  | `""`                                              |
| openformulieren.settings.database.host                    | Database host                                                                                                                                         | `""`                                              |
| openformulieren.settings.database.port                    | Database port                                                                                                                                         | `5432`                                            |
| openformulieren.settings.database.name                    | Database name                                                                                                                                         | `""`                                              |
| openformulieren.settings.database.username                | Database username                                                                                                                                     | `""`                                              |
| openformulieren.settings.database.password                | Database user password                                                                                                                                | `""`                                              |
| openformulieren.settings.database.sslmode                 | Database SSL mode                                                                                                                                     | `prefer`                                          |
| openformulieren.settings.email.host                       | Email host                                                                                                                                            | `localhost`                                       |
| openformulieren.settings.email.port                       | Email port                                                                                                                                            | `587`                                             |
| openformulieren.settings.email.username                   | Email username                                                                                                                                        | `""`                                              |
| openformulieren.settings.email.password                   | Email user password                                                                                                                                   | `""`                                              |
| openformulieren.settings.email.useTLS                     | Email use TLS                                                                                                                                         | `true`                                            |
| openformulieren.settings.email.defaultFrom                | Email default `from` email address                                                                                                                    | `""`                                              |
| openformulieren.settings.secretKey                        | Django secret key. Generate secret key at https://djecrety.ir/                                                                                        | `""`                                              |
| openformulieren.settings.environment                      | Sets the `ENVIRONMENT` variable                                                                                                                       | `""`                                              |
| openformulieren.settings.isHttps                          | Use HTTPS                                                                                                                                             | `true`                                            |
| openformulieren.settings.debug                            | Enable debug mode                                                                                                                                     | `false`                                           |
| openformulieren.settings.sentry.dsn                       | Url to Sentry (i.e https://sentry.example.com/111)                                                                                                    | `""`                                              |
| openformulieren.settings.cors.allowedOrigins              | List of allowed origins                                                                                                                               | `[]`                                              |
| openformulieren.settings.csp.reportSave                   |                                                                                                                                                       | `false`                                           |
| openformulieren.settings.numProxies                       | Number of proxies                                                                                                                                     | `1`                                               |
| openformulieren.persistence.existingClaim                 | Manually managed Persistent Volume and Claim                                                                                                          | `openformulieren`                                 |
| openformulieren.persistence.mediaMountSubpath             | Media mount subpath                                                                                                                                   | `openformulieren/media`                           |
| openformulieren.persistence.privateMediaMountSubpath      | Private media mount subpath                                                                                                                           | `openformulieren/private_media`                   |
| openformulieren.persistence.size                          | Size of created PersistentVolume                                                                                                                      | `10Gi`                                            |
| openformulieren.persistentVolume.volumeAttributeShareName | Value of created PersistentVolume paramer `spec.csi.volumeAttributes.shareName`.<br/>Overriden by `.Values.persistentVolume.volumeAttributeShareName` | `openformulieren`                                 |
| openformulieren.image.repository                          | Image repository                                                                                                                                      | `openformulieren/open-forms`                      |
| openformulieren.image.tag                                 | Image tag                                                                                                                                             | `2.7.8`                                           |
| openformulieren.image.pullPolicy                          | Image pull policy                                                                                                                                     | `IfNotPresent`                                    |
| openformulieren.extraVolumes                              | Optionally specify extra list of additional volumes                                                                                                   | `[]`                                              |
| openformulieren.extraVolumeMounts                         | Optionally specify extra list of additional volumeMounts                                                                                              | `[]]`                                             |
| openformulieren.extraVerifyCerts                          | Path to extra certificates or CA (root) certificates, comma seperated                                                                                 | `""`                                              |
| openformulieren.nodeSelector                              | Node labels for pod assignment. Evaluated as a template                                                                                               | `{}`                                              |
| openformulieren.resources                                 | Container requests and limits                                                                                                                         | See values.yaml                                   |
| openformulieren.worker.resources                          | Worker container requests and limits                                                                                                                  | See values.yaml                                   |
| openformulieren.beat.resources                            | Beat container requests and limits                                                                                                                    | See values.yaml                                   |
| openformulieren.nginx.image.repository                    | Nginx image repository                                                                                                                                | `nginxinc/nginx-unprivileged`                     |
| openformulieren.nginx.image.tag                           | Mginx image tag                                                                                                                                       | `stable`                                          |
| openformulieren.nginx.image.pullPolicy                    | Nginx image pull policy                                                                                                                               | `IfNotPresent`                                    |
| openformulieren.nginx.resources                           | Nginx container requests and limits                                                                                                                   | See values.yaml                                   |
| openformulieren.nginx.config.clientMaxBodySize            | Nginx client max body size                                                                                                                            | `100M`                                            |
| openformulieren.redis.image.registry                      | Redis image registry                                                                                                                                  | `docker.io`                                       |
| openformulieren.redis.image.repository                    | Redis image repository                                                                                                                                | `bitnami/redis`                                   |
| openformulieren.redis.image.tag                           | Redis image tag                                                                                                                                       | `7.0.5-debian-11-r25`                             |
| openformulieren.redis.image.pullPolicy                    | Redis image pul policy                                                                                                                                | `IfNotPresent`                                    |
| openformulieren.redis.master.persistence.enabled          | Redis master persistence enabled                                                                                                                      | `true`                                            |
| openformulieren.redis.master.persistence.size             | Redis master persistence size                                                                                                                         | `"8Gi"`                                           |
| openformulieren.redis.master.persistence.storageClass     | Redis master persistence storage class                                                                                                                | `""`                                              |
| openformulieren.redis.master.nodeSelector                 | Redis node labels for pod assignment. Evaluated as a template                                                                                         | `{}`                                              |

### Open Inwoner

| Name                                                      | Description                                                                                                                                           | Value                                         |
|-----------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------|
| openinwoner.enabled                                       | Boolean to override the installation of Open Inwoner                                                                                                  |                                               |
| openinwoner.configuration.oidcUrl                         | OpenID Connect client url                                                                                                                             | `https://openinwoner.example.nl`              |
| openinwoner.configuration.oidcSecret                      | OpenID Connect client secret                                                                                                                          | `<openinwoner>`                               |
| openinwoner.settings.allowedHosts                         | List if allowed hostnames<br/>(i.e. "openinwoner.example.nl,openinwoner-nginx.podiumd.svc.cluster.local")                                             | `openinwoner-nginx.podiumd.svc.cluster.local` |
| openinwoner.settings.database.host                        | Database host. Overides global.settings.databaseHost                                                                                                  | `""`                                          |
| openinwoner.settings.database.port                        | Database port                                                                                                                                         | `5432`                                        |
| openinwoner.settings.database.name                        | Database name                                                                                                                                         | `""`                                          |
| openinwoner.settings.database.username                    | Database username                                                                                                                                     | `""`                                          |
| openinwoner.settings.database.password                    | Database user password                                                                                                                                | `""`                                          |
| openinwoner.settings.database.sslmode                     | Database SSL mode                                                                                                                                     | `prefer`                                      |
| openinwoner.settings.email.host                           | Email host                                                                                                                                            | `localhost`                                   |
| openinwoner.settings.email.port                           | Email port                                                                                                                                            | `587`                                         |
| openinwoner.settings.email.username                       | Email username                                                                                                                                        | `""`                                          |
| openinwoner.settings.email.password                       | Email user password                                                                                                                                   | `""`                                          |
| openinwoner.settings.email.useTLS                         | Email use TLS                                                                                                                                         | `true`                                        |
| openinwoner.settings.email.defaultFrom                    | Email default `from` email address                                                                                                                    | `""`                                          |
| openinwoner.settings.secretKey                            | Django secret key. Generate secret key at https://djecrety.ir/                                                                                        | `""`                                          |
| openinwoner.settings.environment                          | Sets the `ENVIRONMENT` variable                                                                                                                       | `""`                                          |
| openinwoner.settings.brpVersion                           |                                                                                                                                                       | `""`                                          |
| openinwoner.settings.digidMock                            | Enable the DigiD mock                                                                                                                                 | `""`                                          |
| openinwoner.settings.eherkenningMock                      | Enable the eHerkenning mock                                                                                                                           | `""`                                          |
| openinwoner.settings.isHttps                              | Use HTTPS                                                                                                                                             | `true`                                        |
| openinwoner.settings.debug                                | Enable debug mode                                                                                                                                     | `false`                                       |
| openinwoner.settings.numProxies                           | Number of proxies                                                                                                                                     | `1`                                           |
| openinwoner.settings.sentry.dsn                           | Url to Sentry (i.e https://sentry.example.com/111)                                                                                                    | `""`                                          |
| openinwoner.settings.smsgateway.apikey                    | SMS gateway api key                                                                                                                                   | `""`                                          |
| openinwoner.settings.smsgateway.backend                   | SMS gateway backend                                                                                                                                   | `""`                                          |
| openinwoner.persistence.existingClaim                     | Manually managed Persistent Volume and Claim                                                                                                          | `openinwoner`                                 |
| openinwoner.persistence.mediaMountSubpath                 | Media mount subpath                                                                                                                                   | `openinwoner/media`                           |
| openinwoner.persistence.privateMediaMountSubpath          | Private media mount subpath                                                                                                                           | `openinwoner/private_media`                   |
| openinwoner.persistence.size                              | Size of created PersistentVolume                                                                                                                      | `10Gi`                                        |
| openinwoner.persistentVolume.volumeAttributeShareName     | Value of created PersistentVolume paramer `spec.csi.volumeAttributes.shareName`.<br/>Overriden by `.Values.persistentVolume.volumeAttributeShareName` | `openinwoner`                                 |
| openinwoner.image.repository                              | Image repository                                                                                                                                      | `openinwoner/open-forms`                      |
| openinwoner.image.tag                                     | Image tag                                                                                                                                             | `1.21.2`                                      |
| openinwoner.image.pullPolicy                              | Image pull policy                                                                                                                                     | `IfNotPresent`                                |
| openinwoner.nodeSelector                                  | Node labels for pod assignment. Evaluated as a template                                                                                               | `{}`                                          |
| openinwoner.resources                                     | Container requests and limits                                                                                                                         | See values.yaml                               |
| openinwoner.worker.resources                              | Worker container requests and limits                                                                                                                  | See values.yaml                               |
| openinwoner.nginx.config.clientMaxBodySize                | Nginx client max body size                                                                                                                            | `100M`                                        |
| openinwoner.nginx.image.repository                        | Nginx image repository                                                                                                                                | `nginxinc/nginx-unprivileged`                 |
| openinwoner.nginx.image.tag                               | Mginx image tag                                                                                                                                       | `stable`                                      |
| openinwoner.nginx.image.pullPolicy                        | Nginx image pull policy                                                                                                                               | `IfNotPresent`                                |
| openinwoner.nginx.resources                               | Nginx container requests and limits                                                                                                                   | See values.yaml                               |
| openinwoner.redis.image.registry                          | Redis image registry                                                                                                                                  | `docker.io`                                   |
| openinwoner.redis.image.repository                        | Redis image repository                                                                                                                                | `bitnami/redis`                               |
| openinwoner.redis.image.tag                               | Redis image tag                                                                                                                                       | `7.0.5-debian-11-r25`                         |
| openinwoner.redis.image.pullPolicy                        | Redis image pul policy                                                                                                                                | `IfNotPresent`                                |
| openinwoner.redis.master.persistence.enabled              | Redis master persistence enabled                                                                                                                      | `true`                                        |
| openinwoner.redis.master.persistence.size                 | Redis master persistence size                                                                                                                         | `"8Gi"`                                       |
| openinwoner.redis.master.persistence.storageClass         | Redis master persistence storage class                                                                                                                | `""`                                          |
| openinwoner.redis.master.nodeSelector                     | Redis node labels for pod assignment. Evaluated as a template                                                                                         | `{}`                                          |
| openinwoner.elasticsearch.image.repository                | Elastic search image repository                                                                                                                       | `bitnami/elasticsearch`                       |
| openinwoner.elasticsearch.image.tag                       | Elastic search image tag                                                                                                                              | `8.6.2-debian-11-r0`                          |
| openinwoner.elasticsearch.image.pullPolicy                | Elastic search image pul policy                                                                                                                       | `IfNotPresent`                                |
| openinwoner.elasticsearch.master.persistence.enabled      | Elastic search master persistence enabled                                                                                                             | `true`                                        |
| openinwoner.elasticsearch.master.persistence.size         | Elastic search master persistence storage size                                                                                                        | `"8Gi"`                                       |
| openinwoner.elasticsearch.master.persistence.storageClass | Elastic search master persistence storage class                                                                                                       | `""`                                          |
| openinwoner.elasticsearch.master.nodeSelector             | Elastic search master node labels for pod assignment. Evaluated as a template                                                                         | `{}`                                          |
| openinwoner.elasticsearch.data.persistence.enabled        | Elastic search data persistence enabled                                                                                                               | `true`                                        |
| openinwoner.elasticsearch.data.persistence.size           | Elastic search data persistence storage size                                                                                                          | `"8Gi"`                                       |
| openinwoner.elasticsearch.data.persistence.storageClass   | Elastic search data persistence storage class                                                                                                         | `""`                                          |
| openinwoner.elasticsearch.data.nodeSelector               | Elastic search data node labels for pod assignment. Evaluated as a template                                                                           | `{}`                                          |
| openinwoner.elasticsearch.coordinating.nodeSelector       | Elastic search coordinating node labels for pod assignment. Evaluated as a template                                                                   | `{}`                                          |

### Tags

Tags to add additional unreleased PodiumD functionality.

| Name           | Description                          | Value   |
|----------------|--------------------------------------|---------|
| tags.portaal   | Whether PodiumD Portaal is installed | `false` |
| tags.contact   | Whether PodiumD Contact is installed | `false` |
| tags.zaak      | Whether PodiumD Zaak is installed    | `false` |
                
## Upgrading

If an Helm upgrade of a component fails because of a forbidden update to a statefullset spec the statefullset needs to be deleted prior to the Helm upgrade by the following command:
                                                                                                                                                                   
$ kubectl delete sts <component>-redis-master -n podiumd --cascade=orphan



