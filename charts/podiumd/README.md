# PodiumD

## Add Used chart repositories:

    helm repo add bitnami https://charts.bitnami.com/bitnami
    helm repo add dimpact https://Dimpact-Samenwerking.github.io/helm-charts/
    helm repo add maykinmedia https://maykinmedia.github.io/charts
    helm repo add wiremind https://wiremind.github.io/wiremind-helm-charts

## Parameters

### Tags

Tags define which PodiumD component will be installed.

| Name           | Description                            | Value   |
|----------------|----------------------------------------|---------|
| tags.formulier | Whether PodiumD Formulier is installed | `true`  |
| tags.portaal   | Whether PodiumD Portaal is installed   | `false` |
| tags.contact   | Whether PodiumD Contact is installed   | `false` |
| tags.zaak      | Whether PodiumD ZAAK is installed      | `false` |


### Global

The following components can be partially configured:
- Open Zaak
- Open Notificaties

Kanalen will only be added to Open Notificaties during Helm install, not on Helm upgrade.

| Name                                              | Description                                                                | Value                                              |
|---------------------------------------------------|----------------------------------------------------------------------------|----------------------------------------------------|
| global.configuration.enabled                      | Whether component configuration is enabled | `true`                                             |
| global.configuration.organization                 | Organization name                                                          | `Example gemeente`                                 |
| global.configuration.openzaakAutorisatiesApi      | Autorisaties API                                                           | `https://openzaak.example.nl/autorisaties/api/v1/` |
| global.configuration.notificatiesApi              | Notificaties API                                                           | `https://opennotificaties.example.nl/api/v1/`      |
| global.configuration.notificatiesOpenzaakClientId | ClientId used by Open Notificaties to access autorisaties API              | `notificaties`                                     |
| global.configuration.notificatiesOpenzaakSecret   | Secret used by Open Notificaties to access autorisaties API                | `notificaties-secret`                              |
| global.configuration.openzaakNotificatiesClientId | ClientId used by Open Zaak to send notifications                           | `openzaak`                                         |
| global.configuration.openzaakNotificatiesSecret   | Secret used by Open Zaak to send notifications                             | `openzaak-secret`                                  |
| global.imageRegistry                              | Image registry used by Keycloak, Redis, RabitMQ and Elastic                         | `""`                                               | 

### keycloak

| Name                                        | Description                                                                 | Value                                                   |
|---------------------------------------------|-----------------------------------------------------------------------------|---------------------------------------------------------|
| keycloak.enabled                            | Boolean to override the installation of Keycloak                            |                                                         |
| keycloak.config.realmDisplayName            | Name displayed in Keycloak when logging into the podiumd realm              | `PodiumD`                                               |
| keycloak.config.realmFrontendUrl            | URL of keycloak for logging in to podiumd applications (podiumd realm)      | `https://keycloak.example.nl`                           |
| keycloak.config.adminFrontendUrl            | URL of keycloak for logging in to admin console (master realm)              | `https://keycloak-admin.example.nl`                     |
| keycloak.auth.adminUser                     | Keycloak administrator user                                                 | `admin`                                                 |
| keycloak.auth.adminPassword                 | Keycloak administrator password                                             | `ChangeMeNow`                                           |
| keycloak.externalDatabase.host              | Database host                                                               | `""`                                                    |
| keycloak.externalDatabase.database          | Database name                                                               | `""`                                                    |
| keycloak.externalDatabase.user              | Database username                                                           | `""`                                                    |
| keycloak.externalDatabase.password          | Database user password                                                      | `""`                                                    |
| keycloak.image.repository                   | Keycloak image repository                                                   | `bitnami/keycloak`                                      |
| keycloak.image.tag                          | Keycloak image tag                                                          | `24.0.5-debian-12-r0`                                   |
| keycloak.image.pullPolicy                   | Keycloak image pull policy                                                  | `IfNotPresent`                                          |
| keycloak.nodeSelector                       | Node labels for Keycloak pod assignment. Evaluated as a template            | `{}`                                                    |
| keycloak.resources                          | Container requests and limits                                               | `requests: cpu:10m, memory:512Mi limits: memory:1024Mi` |
| keycloak.keycloakConfigCli.enabled          | Whether Keycloak configuration is enabled                                   | `true`                                                  |
| keycloak.keycloakConfigCli.image.repository | Keycloak config cli image repository                                        | `bitnami/keycloak-config-cli`                           |
| keycloak.keycloakConfigCli.image.tag        | Keycloak config cli image tag                                               | `5.12.0-debian-12-r5`                                   |
| keycloak.keycloakConfigCli.image.pullPolicy | Keycloak config cli image pull policy                                       | `IfNotPresent`                                          |
| keycloak.keycloakConfigCli.nodeSelector     | Node labels for Keycloak config cli pod assignment. Evaluated as a template | `{}`                                                    |
 
### Open LDAP

| Name                               | Description                                             | Value                             |
|------------------------------------|---------------------------------------------------------|-----------------------------------|
| openldap.enabled                   | Boolean to override the installation of OpenLDAP        |                                   |
| openldap.adminUsername             | LDAP administrator username                             | `"admin"`                         |
| openldap.adminPassword             | LDAP administrator password                             | `"admin"`                         |
| openldap.root                      | Root of LDAP tree                                       | `"dc=dimpact,dc=org"`             |
| openldap.persistence.existingClaim | Manually managed Persistent Volume and Claim            | `""`                              |
| openldap.persistence.subpath       | Path within the volume                                  | `openldap`                        |
| openldap.image.repository          | Image repository                                        | `bitnami/openldap`                |
| openldap.image.tag                 | Image tag                                               | `2.6.8`                           |
| openldap.image.pullPolicy          | Image pull policy                                       | `IfNotPresent`                    |
| openldap.nodeSelector              | Node labels for pod assignment. Evaluated as a template | `{}`                              |
| openldap.resources                 | Container requests and limits                           | `requests: cpu:10m, memory:150Mi` |

### ClamAV

| Name                    | Description                                                                    | Value                                                         |
|-------------------------|--------------------------------------------------------------------------------|---------------------------------------------------------------|
| clamav.enabled          | Boolean to override the installation of ClamAV                                 |                                                               |
| clamav.clamdConfig      | Override default clamd.conf file. (https://linux.die.net/man/5/clamd.conf)     | see Chart.yaml                                                |
| clamav.freshclamConfig  | Override default clamd.conf file. (https://linux.die.net/man/5/freshclam.conf) | see Chart.yaml                                                |
| clamav.image.repository | Image repository                                                               | `clamav/clamav`                                               |
| clamav.image.tag        | Image tag                                                                      | `1.3.1`                                                       |
| clamav.image.pullPolicy | Image pull policy                                                              | `IfNotPresent`                                                |
| clamav.nodeSelector     | Node labels for pod assignment. Evaluated as a template                        | `{}`                                                          |
| clamav.resources        | Container requests and limits                                                  | `requests: cpu:100m, memory:2GI limits: cpu:100m, memory:2GI` |


### BRP Mock

| Name                              | Description                                             | Value                                                 |
|-----------------------------------|---------------------------------------------------------|-------------------------------------------------------|
| brpmock.enabled                   | Boolean to override the installation of BRP Mock        | `false`                                               |
| brpmock.nodeSelector              | Node labels for pod assignment. Evaluated as a template | `{}`                                                  |
| brpmock.brpproxy.image.repository | Proxy image repository                                  | `iswish/haal-centraal-brp-bevragen-proxy`             |
| brpmock.brpproxy.image.tag        | Proxy image tag                                         | `2.0.20`                                              |
| brpmock.brpproxy.image.pullPolicy | Proxy image pull policy                                 | `IfNotPresent`                                        |
| brpmock.brpproxy.resources        | Proxy container requests and limits                     | `requests: cpu:10m, memory:150Mi`                     |
| brpmock.gbamock.image.repository  | Mock image repository                                   | `ghcr.io/brp-api/haal-centraal-brp-bevragen-gba-mock` |
| brpmock.gbamock.image.tag         | Mock image tag                                          | `2.0.8`                                               |
| brpmock.gbamock.image.pullPolicy  | Mock image pull policy                                  | `IfNotPresent`                                        |
| brpmock.gbamock.resources         | Mock container requests and limits                      | `requests: cpu:10m, memory:150Mi`                     |


### Open Zaak

| Name                                              | Description                                                                                     | Value                                                          |
|---------------------------------------------------|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------|
| openzaak.enabled                                  | Boolean to override the installation of Open Zaak                                               |                                                                |
| openzaak.configuration.oidcUrl                    | OpenID Connect client url                                                                       | `https://openzaak.example.nl`                                  |
| openzaak.configuration.oidcSecret                 | OpenID Connect client secret                                                                    | `<openzaak>`                                                   |
| openzaak.configuration.sites.openzaakDomain       | Domein (i.e. openzaak.example.nl)                                                               | `""`                                                           |
| openzaak.configuration.superuser.username         | Superuser username                                                                              | `""`                                                           |
| openzaak.configuration.superuser.password         | Superuser password                                                                              | `""`                                                           |
| openzaak.configuration.superuser.email            | Superuser email                                                                                 | `""`                                                           |
| openzaak.configuration.selectieLijst.enabled      | Configure selectie lijsten                                                                      | `false`                                                        |
| openzaak.configuration.selectieLijst.ApiRoot      | Selectie lijsten API root                                                                       | `https://selectielijst.openzaak.nl/api/v1/`                    |
| openzaak.configuration.selectieLijst.ApiOas       | Selectie lijsten OAS                                                                            | `https://selectielijst.openzaak.nl/api/v1/schema/openapi.yaml` |
| openzaak.configuration.selectieLijst.AllowedYears | Selectie lijsten allowed years                                                                  | `[2017, 2020]`                                                 |
| openzaak.configuration.selectieLijst.DefaultYear  | Selectie lijsten default year                                                                   | `2020`                                                         |
| openzaak.settings.allowedHosts                    | List if allowed hostnames (i.e. "openzaak.example.nl,openzaak-nginx.podiumd.svc.cluster.local") | `openzaak-nginx.podiumd.svc.cluster.local`                     |
| openzaak.settings.database.host                   | Database host                                                                                   | `""`                                                           |
| openzaak.settings.database.name                   | Database name                                                                                   | `""`                                                           |
| openzaak.settings.database.username               | Database username                                                                               | `""`                                                           |
| openzaak.settings.database.password               | Database user password                                                                          | `""`                                                           |
| openzaak.settings.secretKey                       | Django secret key. Generate secret key at https://djecrety.ir/                                  | `""`                                                           |
| openzaak.persistence.existingClaim                | Manually managed Persistent Volume and Claim                                                    | `""`                                                           |
| openzaak.persistence.mediaMountSubpath            | Media mount subpath                                                                             | `openzaak/media`                                               |
| openzaak.persistence.privateMediaMountSubpath     | Private media mount subpath                                                                     | `openzaak/private_media`                                       |
| openzaak.image.repository                         | Image repository                                                                                | `openzaak/open-zaak`                                           |
| openzaak.image.tag                                | Image tag                                                                                       | `1.12.3`                                                       |
| openzaak.image.pullPolicy                         | Image pull policy                                                                               | `IfNotPresent`                                                 |
| openzaak.nodeSelector                             | Node labels for pod assignment. Evaluated as a template                                         | `{}`                                                           |
| openzaak.resources                                | Container requests and limits                                                                   | `requests: cpu:10m, memory:400Mi`                              |
| openzaak.worker.resources                         | Worker container requests and limits                                                            | `requests: cpu:10m, memory:400Mi`                              |
| openzaak.nginx.image.repository                   | Nginx image repository                                                                          | `nginxinc/nginx-unprivileged`                                  |
| openzaak.nginx.image.tag                          | Mginx image tag                                                                                 | `stable`                                                       |
| openzaak.nginx.image.pullPolicy                   | Nginx image pull policy                                                                         | `IfNotPresent`                                                 |
| openzaak.nginx.resources                          | Nginx container requests and limits                                                             | `requests: cpu:1m, memory:10Mi`                                |
| openzaak.redis.image.repository                   | Redis image repository                                                                          | `bitnami/redis`                                                |
| openzaak.redis.image.tag                          | Redis image tag                                                                                 | `7.0.5-debian-11-r25`                                          |
| openzaak.redis.image.pullPolicy                   | Redis image pul policy                                                                          | `IfNotPresent`                                                 |
| openzaak.redis.master.nodeSelector                | Redis node labels for pod assignment. Evaluated as a template                                   | `{}`                                                           |
| openzaak.redis.master.resources.requests          | Redis container requests                                                                        | `cpu:10m, memory:20Mi`                                         |

### Open Notificaties

| Name                                                                 | Description                                                                                                              | Value                                        |
|----------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|----------------------------------------------|
| opennotificaties.enabled                                             | Boolean to override the installation of Open Notificatues                                                                |                                              |
| opennotificaties.configuration.oidcUrl                               | OpenID Connect client url                                                                                                | `https://opennotificaties.example.nl`        |
| opennotificaties.configuration.oidcSecret                            | OpenID Connect client secret                                                                                             | `<opennotificaties>`                         |
| opennotificaties.configuration.sites.notificatiesDomain              | Domein (i.e. opennotificaties.example.nl)                                                                                | `""`                                         |
| opennotificaties.configuration.superuser.username                    | Superuser username                                                                                                       | `""`                                         |
| opennotificaties.configuration.superuser.password                    | Superuser password                                                                                                       | `""`                                         |
| opennotificaties.configuration.superuser.email                       | Superuser email                                                                                                          | `""`                                         |
| opennotificaties.settings.allowedHosts                               | List if allowed hostnames (i.e. "openzaak.example.nl,openzaak-nginx.podiumd.svc.cluster.local")                          | `opennotificaties.podiumd.svc.cluster.local` |
| opennotificaties.settings.database.host                              | Database host                                                                                                            | `""`                                         |
| opennotificaties.settings.database.name                              | Database name                                                                                                            | `""`                                         |
| opennotificaties.settings.database.username                          | Database username                                                                                                        | `""`                                         |
| opennotificaties.settings.database.password                          | Database user password                                                                                                   | `""`                                         |
| opennotificaties.settings.secretKey                                  | Django secret key. Generate secret key at https://djecrety.ir/                                                           | `""`                                         |
| opennotificaties.settings.cleanOldNotifications.enabled              | Enable leaning of logged notifications                                                                                   | `true`                                       |
| opennotificaties.settings.cleanOldNotifications.daysRetained         | Number of days to retain logged notifications                                                                            | `30`                                         |
| opennotificaties.settings.cleanOldNotifications.cronjob.schedule     | Schedule to run the clean logged notifications cronjob                                                                   | `"0 0 * * *"`                                |
| opennotificaties.settings.cleanOldNotifications.cronjob.historyLimit | Number of succesful and failed jobs to keep                                                                              | `1`                                          |
| opennotificaties.settings.maxRetries                                 | Maximum number of automatic retries. After this amount of retries, Open Notificaties stops trying to deliver the message | `5`                                          |
| opennotificaties.settings.retryBackoff                               | A factor applied to the exponential backoff. This allows you to tune how quickly automatic retries are performed         | `3`                                          |
| opennotificaties.settings.retryBackoffMax                            | Upper limit to the exponential backoff time                                                                              | `48`                                         |
| opennotificaties.persistence.existingClaim                           | Manually managed Persistent Volume and Claim                                                                             | `""`                                         |
| opennotificaties.persistence.mediaMountSubpath                       | Media mount subpath                                                                                                      | `pennotificaties/media`                      |
| opennotificaties.image.repository                                    | Image repository                                                                                                         | `openzaak/open-notificaties`                 |
| opennotificaties.image.tag                                           | Image tag                                                                                                                | `1.6.0`                                      |
| opennotificaties.image.pullPolicy                                    | Image pull policy                                                                                                        | `IfNotPresent`                               |
| opennotificaties.nodeSelector                                        | Node labels for pod assignment. Evaluated as a template                                                                  | `{}`                                         |
| opennotificaties.resources                                           | Container requests and limits                                                                                            | `requests: cpu:10m, memory:200Mi`            |
| opennotificaties.worker.resources                                    | Worker container requests and limits                                                                                     | `requests: cpu:10m, memory:400Mi`            |
| opennotificaties.rabbitmq.image.repository                           | RabitMQ image repository                                                                                                 | `bitnami/rabbitmq`                           |
| opennotificaties.rabbitmq.image.tag                                  | RabitMQ image tag                                                                                                        | `3.11.8-debian-11-r0`                        |
| opennotificaties.rabbitmq.image.pullPolicy                           | RabitMQ image pul policy                                                                                                 | `IfNotPresent`                               |
| opennotificaties.rabbitmq.nodeSelector                               | RabitMQ node labels for pod assignment. Evaluated as a template                                                          | `{}`                                         |
| opennotificaties.rabbitmq.resources                                  | RabitMQ container requests and limits                                                                                    | `cpu:100m, memory:200Mi`                     |
| opennotificaties.redis.image.repository                              | Redis image repository                                                                                                   | `bitnami/redis`                              |
| opennotificaties.redis.image.tag                                     | Redis image tag                                                                                                          | `7.0.5-debian-11-r25`                        |
| opennotificaties.redis.image.pullPolicy                              | Redis image pul policy                                                                                                   | `IfNotPresent`                               |
| opennotificaties.redis.master.nodeSelector                           | Redis node labels for pod assignment. Evaluated as a template                                                            | `{}`                                         |
| opennotificaties.redis.master.resources.requests                     | Redis container requests                                                                                                 | `cpu:10m, memory:20Mi`                       |

### Objecten

| Name                                     | Description                                                                               | Value                                |
|------------------------------------------|-------------------------------------------------------------------------------------------|--------------------------------------|
| objecten.enabled                         | Boolean to override the installation of Objecten                                          |                                      |
| objecten.configuration.oidcUrl           | OpenID Connect client url                                                                 | `https://objecten.example.nl`        |
| objecten.configuration.oidcSecret        | OpenID Connect client secret                                                              | `<objecten>`                         |
| objecten.settings.allowedHosts           | List if allowed hostnames (i.e. "objecten.example.nl,objecten.podiumd.svc.cluster.local") | `objecten.podiumd.svc.cluster.local` |
| objecten.settings.database.host          | Database host                                                                             | `""`                                 |
| objecten.settings.database.name          | Database name                                                                             | `""`                                 |
| objecten.settings.database.username      | Database username                                                                         | `""`                                 |
| objecten.settings.database.password      | Database user password                                                                    | `""`                                 |
| objecten.settings.secretKey              | Django secret key. Generate secret key at https://djecrety.ir/                            | `""`                                 |
| objecten.persistence.existingClaim       | Manually managed Persistent Volume and Claim                                              | `""`                                 |
| objecten.persistence.mediaMountSubpath   | Media mount subpath                                                                       | `objecten/media`                     |
| objecten.image.repository                | Image repository                                                                          | `maykinmedia/objects-api`            |
| objecten.image.tag                       | Image tag                                                                                 | `2.3.1`                              |
| objecten.image.pullPolicy                | Image pull policy                                                                         | `IfNotPresent`                       |
| objecten.nodeSelector                    | Node labels for pod assignment. Evaluated as a template                                   | `{}`                                 |
| objecten.resources                       | Container requests and limits                                                             | `requests: cpu:10m, memory:250Mi`    |
| objecten.worker.resources                | Worker container requests and limits                                                      | `requests: cpu:10m, memory:200Mi`    |
| objecten.redis.image.repository          | Redis image repository                                                                    | `bitnami/redis`                      |
| objecten.redis.image.tag                 | Redis image tag                                                                           | `7.0.5-debian-11-r25`                |
| objecten.redis.image.pullPolicy          | Redis image pul policy                                                                    | `IfNotPresent`                       |
| objecten.redis.master.nodeSelector       | Redis node labels for pod assignment. Evaluated as a template                             | `{}`                                 |
| objecten.redis.master.resources.requests | Redis container requests                                                                  | `cpu:10m, memory:20Mi`               |

### Objecttypen

| Name                                   | Description                                                                                     | Value                                   |
|----------------------------------------|-------------------------------------------------------------------------------------------------|-----------------------------------------|
| objecttypen.enabled                    | Boolean to override the installation of objecttypen                                             |                                         |
| objecttypen.configuration.oidcUrl      | OpenID Connect client url                                                                       | `https://objecttypen.example.nl`        |
| objecttypen.configuration.oidcSecret   | OpenID Connect client secret                                                                    | `<objecttypen>`                         |
| objecttypen.settings.allowedHosts      | List if allowed hostnames (i.e. "objecttypen.example.nl,objecttypen.podiumd.svc.cluster.local") | `objecttypen.podiumd.svc.cluster.local` |
| objecttypen.settings.database.host     | Database host                                                                                   | `""`                                    |
| objecttypen.settings.database.name     | Database name                                                                                   | `""`                                    |
| objecttypen.settings.database.username | Database username                                                                               | `""`                                    |
| objecttypen.settings.database.password | Database user password                                                                          | `""`                                    |
| objecttypen.settings.secretKey         | Django secret key. Generate secret key at https://djecrety.ir/                                  | `""`                                    |
| objecttypen.image.repository           | Image repository                                                                                | `maykinmedia/objecttypes-api`           |
| objecttypen.image.tag                  | Image tag                                                                                       | `2.1.2`                                 |
| objecttypen.image.pullPolicy           | Image pull policy                                                                               | `IfNotPresent`                          |
| objecttypen.nodeSelector               | Node labels for pod assignment. Evaluated as a template                                         | `{}`                                    |
| objecttypen.resources                  | Container requests and limits                                                                   | `requests: cpu:10m, memory:250Mi`       |

### Open Klant versie 1

| Name                                        | Description                                                                                     | Value                                   |
|---------------------------------------------|-------------------------------------------------------------------------------------------------|-----------------------------------------|
| openklantv1.enabled                         | Boolean to override the installation of Open Klant versie 1                                     |                                         |
| openklantv1.configuration.oidcUrl           | OpenID Connect client url                                                                       | `https://openklantv1.example.nl`        |
| openklantv1.configuration.oidcSecret        | OpenID Connect client secret                                                                    | `<openklantv1>`                         |
| openklantv1.settings.allowedHosts           | List if allowed hostnames (i.e. "openklantv1.example.nl,openklantv1.podiumd.svc.cluster.local") | `openklantv1.podiumd.svc.cluster.local` |
| openklantv1.settings.database.host          | Database host                                                                                   | `""`                                    |
| openklantv1.settings.database.name          | Database name                                                                                   | `""`                                    |
| openklantv1.settings.database.username      | Database username                                                                               | `""`                                    |
| openklantv1.settings.database.password      | Database user password                                                                          | `""`                                    |
| openklantv1.settings.secretKey              | Django secret key. Generate secret key at https://djecrety.ir/                                  | `""`                                    |
| openklantv1.image.repository                | Image repository                                                                                | `maykinmedia/objects-api`               |
| openklantv1.image.tag                       | Image tag                                                                                       | `1.0.0`                                 |
| openklantv1.image.pullPolicy                | Image pull policy                                                                               | `IfNotPresent`                          |
| openklantv1.nodeSelector                    | Node labels for pod assignment. Evaluated as a template                                         | `{}`                                    |
| openklantv1.resources                       | Container requests and limits                                                                   | `requests: cpu:10m, memory:300Mi`       |
| openklantv1.worker.resources                | Worker container requests and limits                                                            | `requests: cpu:10m, memory:200Mi`       |
| openklantv1.redis.image.repository          | Redis image repository                                                                          | `bitnami/redis`                         |
| openklantv1.redis.image.tag                 | Redis image tag                                                                                 | `7.0.5-debian-11-r25`                   |
| openklantv1.redis.image.pullPolicy          | Redis image pul policy                                                                          | `IfNotPresent`                          |
| openklantv1.redis.master.nodeSelector       | Redis node labels for pod assignment. Evaluated as a template                                   | `{}`                                    |
| openklantv1.redis.master.resources.requests | Redis container requests                                                                        | `cpu:10m, memory:20Mi`                  |

### Open Klant versie 2

| Name                                        | Description                                                                                     | Value                                   |
|---------------------------------------------|-------------------------------------------------------------------------------------------------|-----------------------------------------|
| openklantv2.enabled                         | Boolean to override the installation of Open Klant versie 2                                     | `false`                                 |
| openklantv2.configuration.oidcUrl           | OpenID Connect client url                                                                       | `https://openklantv2.example.nl`        |
| openklantv2.configuration.oidcSecret        | OpenID Connect client secret                                                                    | `<openklantv2>`                         |
| openklantv2.settings.allowedHosts           | List if allowed hostnames (i.e. "openklantv2.example.nl,openklantv2.podiumd.svc.cluster.local") | `openklantv2.podiumd.svc.cluster.local` |
| openklantv2.settings.database.host          | Database host                                                                                   | `""`                                    |
| openklantv2.settings.database.name          | Database name                                                                                   | `""`                                    |
| openklantv2.settings.database.username      | Database username                                                                               | `""`                                    |
| openklantv2.settings.database.password      | Database user password                                                                          | `""`                                    |
| openklantv2.settings.secretKey              | Django secret key. Generate secret key at https://djecrety.ir/                                  | `""`                                    |
| openklantv2.image.repository                | Image repository                                                                                | `maykinmedia/objects-api`               |
| openklantv2.image.tag                       | Image tag                                                                                       | `2.0.0`                                 |
| openklantv2.image.pullPolicy                | Image pull policy                                                                               | `IfNotPresent`                          |
| openklantv2.nodeSelector                    | Node labels for pod assignment. Evaluated as a template                                         | `{}`                                    |
| openklantv2.resources                       | Container requests and limits                                                                   | `requests: cpu:10m, memory:300Mi`       |
| openklantv2.worker.resources                | Worker container requests and limits                                                            | `requests: cpu:10m, memory:200Mi`       |
| openklantv2.redis.image.repository          | Redis image repository                                                                          | `bitnami/redis`                         |
| openklantv2.redis.image.tag                 | Redis image tag                                                                                 | `7.0.5-debian-11-r25`                   |
| openklantv2.redis.image.pullPolicy          | Redis image pul policy                                                                          | `IfNotPresent`                          |
| openklantv2.redis.master.nodeSelector       | Redis node labels for pod assignment. Evaluated as a template                                   | `{}`                                    |
| openklantv2.redis.master.resources.requests | Redis container requests                                                                        | `cpu:10m, memory:20Mi`                  |

### Open Formulieren

| Name                                                 | Description                                                                                                   | Value                                             |
|------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|---------------------------------------------------|
| openformulieren.enabled                              | Boolean to override the installation of Open Formulieren                                                      |                                                   |
| openformulieren.configuration.oidcUrl                | OpenID Connect client url                                                                                     | `https://openformulieren.example.nl`              |
| openformulieren.configuration.oidcSecret             | OpenID Connect client secret                                                                                  | `<openformulieren>`                               |
| openformulieren.settings.allowedHosts                | List if allowed hostnames (i.e. "openformulieren.example.nl,openformulieren-nginx.podiumd.svc.cluster.local") | `openformulieren-nginx.podiumd.svc.cluster.local` |
| openformulieren.settings.database.host               | Database host                                                                                                 | `""`                                              |
| openformulieren.settings.database.name               | Database name                                                                                                 | `""`                                              |
| openformulieren.settings.database.username           | Database username                                                                                             | `""`                                              |
| openformulieren.settings.database.password           | Database user password                                                                                        | `""`                                              |
| openformulieren.settings.secretKey                   | Django secret key. Generate secret key at https://djecrety.ir/                                                | `""`                                              |
| openformulieren.persistence.existingClaim            | Manually managed Persistent Volume and Claim                                                                  | `""`                                              |
| openformulieren.persistence.mediaMountSubpath        | Media mount subpath                                                                                           | `openformulieren/media`                           |
| openformulieren.persistence.privateMediaMountSubpath | Private media mount subpath                                                                                   | `openformulieren/private_media`                   |
| openformulieren.image.repository                     | Image repository                                                                                              | `openformulieren/open-forms`                      |
| openformulieren.image.tag                            | Image tag                                                                                                     | `2.6.7`                                           |
| openformulieren.image.pullPolicy                     | Image pull policy                                                                                             | `IfNotPresent`                                    |
| openformulieren.nodeSelector                         | Node labels for pod assignment. Evaluated as a template                                                       | `{}`                                              |
| openformulieren.resources                            | Container requests and limits                                                                                 | `requests: cpu:10m, memory:600Mi`                 |
| openformulieren.worker.resources                     | Worker container requests and limits                                                                          | `requests: cpu:10m, memory:500Mi`                 |
| openformulieren.beat.resources                       | Beat container requests and limits                                                                            | `requests: cpu:1m, memory:150Mi`                  |
| openformulieren.nginx.image.repository               | Nginx image repository                                                                                        | `nginxinc/nginx-unprivileged`                     |
| openformulieren.nginx.image.tag                      | Mginx image tag                                                                                               | `stable`                                          |
| openformulieren.nginx.image.pullPolicy               | Nginx image pull policy                                                                                       | `IfNotPresent`                                    |
| openformulieren.nginx.resources                      | Nginx container requests and limits                                                                           | `requests: cpu:1m, memory:10Mi`                   |
| openformulieren.redis.image.repository               | Redis image repository                                                                                        | `bitnami/redis`                                   |
| openformulieren.redis.image.tag                      | Redis image tag                                                                                               | `7.0.5-debian-11-r25`                             |
| openformulieren.redis.image.pullPolicy               | Redis image pul policy                                                                                        | `IfNotPresent`                                    |
| openformulieren.redis.master.nodeSelector            | Redis node labels for pod assignment. Evaluated as a template                                                 | `{}`                                              |
| openformulieren.redis.master.resources.requests      | Redis container requests                                                                                      | `cpu:10m, memory:20Mi`                            |

### Open Inwoner

| Name                                                | Description                                                                                           | Value                                         |
|-----------------------------------------------------|-------------------------------------------------------------------------------------------------------|-----------------------------------------------|
| openinwoner.enabled                                 | Boolean to override the installation of Open Inwoner                                                  |                                               |
| openinwoner.configuration.oidcUrl                   | OpenID Connect client url                                                                             | `https://openinwoner.example.nl`              |
| openinwoner.configuration.oidcSecret                | OpenID Connect client secret                                                                          | `<openinwoner>`                               |
| openinwoner.settings.allowedHosts                   | List if allowed hostnames (i.e. "openinwoner.example.nl,openinwoner-nginx.podiumd.svc.cluster.local") | `openinwoner-nginx.podiumd.svc.cluster.local` |
| openinwoner.settings.database.host                  | Database host                                                                                         | `""`                                          |
| openinwoner.settings.database.name                  | Database name                                                                                         | `""`                                          |
| openinwoner.settings.database.username              | Database username                                                                                     | `""`                                          |
| openinwoner.settings.database.password              | Database user password                                                                                | `""`                                          |
| openinwoner.settings.secretKey                      | Django secret key. Generate secret key at https://djecrety.ir/                                        | `""`                                          |
| openinwoner.settings.digidMock                      | Enable the DigiD mock                                                                                 | `""`                                          |
| openinwoner.persistence.existingClaim               | Manually managed Persistent Volume and Claim                                                          | `""`                                          |
| openinwoner.persistence.mediaMountSubpath           | Media mount subpath                                                                                   | `openinwoner/media`                           |
| openinwoner.persistence.privateMediaMountSubpath    | Private media mount subpath                                                                           | `openinwoner/private_media`                   |
| openinwoner.image.repository                        | Image repository                                                                                      | `openinwoner/open-forms`                      |
| openinwoner.image.tag                               | Image tag                                                                                             | `2.6.7`                                       |
| openinwoner.image.pullPolicy                        | Image pull policy                                                                                     | `IfNotPresent`                                |
| openinwoner.nodeSelector                            | Node labels for pod assignment. Evaluated as a template                                               | `{}`                                          |
| openinwoner.resources                               | Container requests and limits                                                                         | `requests: cpu:10m, memory:600Mi`             |
| openinwoner.worker.resources                        | Worker container requests and limits                                                                  | `requests: cpu:10m, memory:400Mi`             |
| openinwoner.nginx.image.repository                  | Nginx image repository                                                                                | `nginxinc/nginx-unprivileged`                 |
| openinwoner.nginx.image.tag                         | Mginx image tag                                                                                       | `stable`                                      |
| openinwoner.nginx.image.pullPolicy                  | Nginx image pull policy                                                                               | `IfNotPresent`                                |
| openinwoner.nginx.resources                         | Nginx container requests and limits                                                                   | `requests: cpu:1m, memory:10Mi`               |
| openinwoner.redis.image.repository                  | Redis image repository                                                                                | `bitnami/redis`                               |
| openinwoner.redis.image.tag                         | Redis image tag                                                                                       | `7.0.5-debian-11-r25`                         |
| openinwoner.redis.image.pullPolicy                  | Redis image pul policy                                                                                | `IfNotPresent`                                |
| openinwoner.redis.master.nodeSelector               | Redis node labels for pod assignment. Evaluated as a template                                         | `{}`                                          |
| openinwoner.redis.master.resources.requests         | Redis container requests                                                                              | `cpu:10m, memory:20Mi`                        |
| openinwoner.elasticsearch.image.repository          | Elastic search image repository                                                                       | `bitnami/elasticsearch`                       |
| openinwoner.elasticsearch.image.tag                 | Elastic search image tag                                                                              | `8.6.2-debian-11-r0`                          |
| openinwoner.elasticsearch.image.pullPolicy          | Elastic search image pul policy                                                                       | `IfNotPresent`                                |
| openinwoner.elasticsearch.master.nodeSelector       | Elastic search node labels for pod assignment. Evaluated as a template                                | `{}`                                          |
| openinwoner.elasticsearch.master.resources.requests | Elastic search container requests                                                                     | `cpu:25m, memory:256Mi`                       |
