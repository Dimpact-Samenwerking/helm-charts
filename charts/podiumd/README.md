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
| global.imageRegistry                              | Image registry used by Keycloak, Redis and Elastic                         | `""`                                               | 

### keycloak

| Name                                        | Description                                                                 | Value                             |
|---------------------------------------------|-----------------------------------------------------------------------------|-----------------------------------|
| keycloak.enabled                            | Boolean to override the installation of Keycloak                            |                                   |
| keycloak.config.realmDisplayName            | Name displayed in Keycloak when logging into the podiumd realm              | `PodiumD`                         |
| keycloak.config.realmFrontendUrl            | URL of keycloak                                                             | `https://keycloak.example.nl`     |
| keycloak.auth.adminUser                     | Keycloak administrator user                                                 | `admin`                           |
| keycloak.auth.adminPassword                 | Keycloak administrator password                                             | `ChangeMeNow`                     |
| keycloak.externalDatabase.host              | Database host                                                               | `""`                              |
| keycloak.externalDatabase.database          | Database name                                                               | `""`                              |
| keycloak.externalDatabase.user              | Database username                                                           | `""`                              |
| keycloak.externalDatabase.password          | Database user password                                                      | `""`                              |
| keycloak.image.repository                   | Keycloak image repository                                                   | `bitnami/keycloak`                |
| keycloak.image.tag                          | Keycloak image tag                                                          | `24.0.5-debian-12-r0`             |
| keycloak.nodeSelector                       | Node labels for Keycloak pod assignment. Evaluated as a template            | `{}`                              |
| keycloak.keycloakConfigCli.enabled          | Whether Keycloak configuration is enabled                                   | `true`                            |
| keycloak.keycloakConfigCli.image.repository | Keycloak config cli image repository                                        | `bitnami/keycloak-config-cli`     |
| keycloak.keycloakConfigCli.image.tag        | Keycloak config cli image tag                                               | `5.12.0-debian-12-r5`             |
| keycloak.keycloakConfigCli.nodeSelector     | Node labels for Keycloak config cli pod assignment. Evaluated as a template | `{}`                              |
| keycloak.resources                          | Container requests and limits                                               | `requests: cpu:10m, memory:512Mi` |





| Name             | Description                                             | Value                                  |
|------------------|---------------------------------------------------------|----------------------------------------|
| nameOveride      | String to override name template                        | `""`                                   |
