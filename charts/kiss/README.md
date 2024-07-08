# KISS

## Parameters

| Name                                 | Description                                                                                   | Value                                                       |
|--------------------------------------|-----------------------------------------------------------------------------------------------|-------------------------------------------------------------|
| brp.baseUrl                          | Haal Centraal BRP Personen bevragen API base url                                              | `http://brpmock.podiumd.svc.cluster.local/haalcentraal/api` |
| brp.apiKey                           | Haal Centraal BRP Personen bevragen API key                                                   | `""`                                                        |
| elastic.baseUrl                      | ELastic search base URL                                                                       | `https://kiss-es-http.podiumd.svc.cluster.local:9200`       |
| elastic.username                     | Elastic search username                                                                       | `elastic`                                                   |
| elastic.password                     | Elastic search password                                                                       | `""`                                                        |
| enterpriseSearch.baseUrl             | Enterprise search base URL                                                                    | `https://kiss-ent-http.podiumd.svc.cluster.local:3002`      |
| enterpriseSearch.privateApikey       | Enterprise search private API key                                                             | `""`                                                        |
| enterpriseSearch.publicApikey        | Enterprise search public API key                                                              | `""`                                                        |
| esuite.baseUrl                       | e-Suite base URL                                                                              | `https://esuite.example.nl`                                 |
| esuite.clientId                      | e-Suite client ID                                                                             | `kiss`                                                      |
| esuite.secret                        | e-Suite secret (minimum length is 16 characters)                                              | `""`                                                        |
| esuite.contactverzoektypen           | List of e-Suite contactverzoektypen                                                           | `[]`                                                        |
| database.host                        | Database host                                                                                 | `""`                                                        |
| database.name                        | Database name                                                                                 | `""`                                                        |
| database.user                        | Database username                                                                             | `""`                                                        |
| database.password                    | Database password                                                                             | `""`                                                        |
| kvk.baseUrl                          | Kamer Van Koophandel API base URL                                                             | `https://api.kvk.nl/test/api`                               |
| kvk.apikey                           | Kamer Van Koophandel API key                                                                  | `""`                                                        |
| objecten.baseUrl                     | Objecten base URL                                                                             | `http://objecten.podiumd.svc.cluster.local`                 |
| objecten.token                       | Objecten authorization token                                                                  | `""`                                                        |
| objecttypen.baseUrlIntern            | Objecttypen base URL                                                                          | `http://objecttypen.podiumd.svc.cluster.local`              |
| objecttypen.baseUrlExtern            | Objecttypen base URL as accessed by e-Suite                                                   | `https://objecttypen.example.nl`                            |
| objecttypen.token                    | Objecttypen authorization token                                                               | `""`                                                        |
| objecttypen.afdelingUUID             | UUID of objecttype afdeling                                                                   | `""`                                                        |
| objecttypen.groepUUID                | UUID of objecttype groep                                                                      | `""`                                                        |
| objecttypen.interneTaakUUID          | UUID of objecttype interne taak                                                               | `""`                                                        |
| objecttypen.kennisartikelUUID        | UUID of objecttype kennisartikel                                                              | `""`                                                        |
| objecttypen.medewerkerUUID           | UUID of objecttype medewerker                                                                 | `""`                                                        |
| objecttypen.vacUUID                  | UUID of objecttype vac                                                                        | `""`                                                        |
| oidc.authority                       | OpenID Connect Identity Provider URL                                                          | `https://keycloak.example.nl/realms/podiumd/`               |
| oidc.clientId                        | OpenID Connect clientId                                                                       | `kiss`                                                      |
| oidc.secret                          | OpenID Connect secret                                                                         | `""`                                                        |
| oidc.medewerkerIdentificatieClaim    | OpenID Connect claim used to identify the user                                                | `preferred_username`                                                     |
| oidc.medewerkerIdentificatieTruncate | Number of characters to truncate the OpenID Connect claim used to identify the user           | `null`                                                      |
| organisatieIds                       | RSIN of the organization that registers the Contactmomenten                                   | `""`                                                        |
| email.host                           | KCM feedback email on kennisartikel host                                                      | `""`                                                        |
| email.port                           | KCM feedback email on kennisartikel port                                                      | `null`                                                      |
| email.username                       | KCM feedback email on kennisartikel username                                                  | `""`                                                        |
| email.password                       | KCM feedback email on kennisartikel password                                                  | `""`                                                        |
| email.enableSSL                      | Enable SSL on KCM feedback email on kennisartikel (true or false)                             | `null`                                                      |
| email.feedbackFrom                   | KCM feedback email on kennisartikel sender address                                            | `""`                                                        |
| email.feedbackTo                     | KCM feedback email on kennisartikel host receiver address                                     | `""`                                                        |
| nodeSelector                         | Node labels for pod assignment. Evaluated as a template                                       | `{}`                                                        |
| frontend.service.name                | Override the frontend service name                                                            | `""`                                                        |
| frontend.image.repository            | Frontend image repository                                                                     | `ghcr.io/klantinteractie-servicesysteem/kiss-frontend`      |
| frontend.image.tag                   | Frontend image tag                                                                            | `"latest"`                                                  |
| frontend.image.pullPolicy            | Frontend image pull policy                                                                    | `IfNotPresent`                                              |
| frontend.resources                   | Frontend container requests and limits                                                        | `requests: cpu:10m, memory:100Mi`                           |
| adapter.baseUrl                      | Adapter base URL                                                                              | `http://kiss-adapter.podiumd.svc.cluster.local`             |
| adapter.clientId                     | Adapter client ID                                                                             | `kiss_intern`                                               |
| adapter.secret                       | Adapter secret (minimum length is 16 characters)                                              | `""`                                                        |
| adapter.image.repository             | Adapter image repository                                                                      | `ghcr.io/icatt-menselijk-digitaal/podiumd-adapter`          |
| adapter.image.tag                    | Adapter image tag                                                                             | `"latest"`                                                  |
| adapter.image.pullPolicy             | Adapter image pull policy                                                                     | `IfNotPresent`                                              |
| adapter.resources                    | Adapter container requests and limits                                                         | `requests: cpu:10m, memory:100Mi`                           |
| sync.initialSync                     | Start an initial synchronization of kennisbank, smoelenboek and vac immediately after install | `true`                                                      |
| sync.schedule.kennisbank             | Schedule of the kennisbank synchronization cron job                                           | `"*/59 * * * *"`                                            |
| sync.schedule.smoelenboek            | Schedule of the smoelenboek synchronization cron job                                          | `"*/59 * * * *"`                                            |
| sync.schedule.vac                    | Schedule of the vac synchronization cron job                                                  | `"*/59 * * * *"`                                            |
| sync.successfulJobsHistoryLimit      | Successfull jobs history limit                                                                | `1`                                                         |
| sync.failedJobsHistoryLimit          | Failed jobs history limit                                                                     | `1`                                                         |
| sync.image.repository                | Synchronization image repository                                                              | `ghcr.io/klantinteractie-servicesysteem/kiss-elastic-sync`  |
| sync.image.tag:                      | Synchronization image tag                                                                     | `"latest"`                                                  |
| sync.image.pullPolicy                | Synchronization image pull policy                                                             | `IfNotPresent`                                              |
| alpine.image.repository              | Alpine image repository                                                                       | `alpine`                                                    |
| alpine.image.tag:                    | Alpine image tag                                                                              | `"3.20"`                                                    |
| alpine.image.pullPolicy              | Alpine image pull policy                                                                      | `IfNotPresent`                                              |


 