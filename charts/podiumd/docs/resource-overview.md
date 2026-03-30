# PodiumD Resource Overview

Resource requests and limits for all chart components. Values reflect the chart defaults (podiumd `values.yaml` combined with sub-chart defaults). Limits marked `-` are not set — the container is burstable.

> **Note:** Components marked *needs settings* have no resource configuration in the chart or sub-chart defaults and should be configured per environment.

---

## Keycloak

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| keycloak-builder (init) | 250m | 512Mi | 1000m | 1Gi |
| keycloak | — | 1700Mi | — | 2Gi |

## Keycloak Operator

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| keycloak-operator | — | — | — | — |
| job: ensurePodiumdAdminUser | — | — | — | — |
| job: ensureOperatorSa | — | — | — | — |

*The operator and its jobs have no resource settings — needs settings.*

---

## Redis Operator

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| redis-operator | 100m | 128Mi | 500m | 256Mi |
| redis-ha | 100m | 128Mi | 500m | 256Mi |
| redis-ha exporter (init-config) | 100m | 128Mi | 500m | 256Mi |
| redis-ha init (busybox) | — | — | — | — |

---

## Open Zaak

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| openzaak | 100m | 256Mi | — | — |
| openzaak-worker | 10m | 480Mi | — | — |
| openzaak-beat | 10m | 160Mi | — | — |
| nginx | 10m | 16Mi | — | — |

---

## Open Notificaties

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| opennotificaties | 100m | 256Mi | — | — |
| opennotificaties-worker | 50m | 386Mi | — | — |
| opennotificaties-beat | — | — | — | — |
| rabbitmq | 300m | 256Mi | — | — |

*opennotificaties-beat has no resource settings — needs settings.*

---

## Objecten

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| objecten | 100m | 256Mi | — | — |
| objecten-worker | 50m | 192Mi | — | — |

---

## Objecttypen

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| objecttypen | 10m | 160Mi | — | — |

---

## Open Archiefbeheer

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| openarchiefbeheer | 250m | 256Mi | — | — |
| openarchiefbeheer-worker | — | — | — | — |
| openarchiefbeheer-beat | — | — | — | — |
| openarchiefbeheer-nginx | — | — | — | — |

*worker, beat and nginx have no resource settings — needs settings.*

---

## Open Klant

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| openklant | 100m | 300Mi | — | — |
| openklant-worker | 50m | 200Mi | — | — |
| openklant-nginx | 10m | 16Mi | — | — |

---

## Open Formulieren

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| openformulieren | 100m | 650Mi | — | — |
| openformulieren-worker | 50m | 512Mi | — | — |
| openformulieren-beat | 10m | 160Mi | — | — |
| nginx | 10m | 16Mi | — | — |

---

## Open Inwoner

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| openinwoner | 200m | 1Gi | — | — |
| openinwoner-worker | 200m | 640Mi | — | — |
| openinwoner-beat | — | — | — | — |
| openinwoner-celery-monitor | — | — | — | — |
| nginx | 30m | 8Mi | — | — |
| openinwoner-search-index (init) | — | — | — | — |

*beat, celery-monitor and search-index init have no resource settings — needs settings.*

### Open Inwoner — Elasticsearch (ECK, per environment)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| elasticsearch | 200m | 1536Mi | 1000m | 1536Mi |
| elastic-internal-init-filesystem (init) | 100m | 50Mi | 100m | 50Mi |

*Configured per environment via `openinwoner.eck-elasticsearch.nodeSets`. The values above reflect the ontw-dim1 environment.*

---

## KISS Elastic (ECK Operator)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| elastic-operator (manager) | 100m | 150Mi | 1000m | 1Gi |
| elasticsearch | — | 2Gi | — | 2Gi |
| kibana | — | 1Gi | — | 1Gi |
| enterprise-search | — | 4Gi | — | 4Gi |
| elastic-internal-init-filesystem (init) | 100m | 50Mi | 100m | 50Mi |

*Elasticsearch, Kibana and Enterprise Search requests not set — needs settings.*

---

## KISS

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| kiss (frontend) | — | — | — | — |
| adapter (podiumd-adapter) | 10m | 100Mi | — | — |
| syncJobs (kennisbank, medewerkers, vac) | — | — | — | — |

*KISS frontend and syncJobs have no resource settings — needs settings.*

---

## ZAC

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| zac | 100m | 1Gi | — | — |
| opa (sidecar) | — | — | — | — |
| init-solr-zac-core (init) | — | — | — | — |
| nginx | — | — | — | — |
| office-converter | 100m | 512Mi | — | — |
| signaleren (CronJob) | — | — | — | — |

*opa, nginx and signaleren have no resource settings — needs settings.*

### ZAC — Solr (Operator managed)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| solr-operator | — | — | — | — |
| solrcloud-node | — | — | — | — |
| zookeeper-operator | — | — | — | — |
| zookeeper | — | — | — | — |

*All Solr/Zookeeper components have no resource settings. JVM heap is configured via `javaMem: -Xms512m -Xmx768m`. Operator-level resources should be set per environment — needs settings.*

---

## ZGW Office Addin

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| frontend | — | — | — | — |
| backend | — | — | — | — |

*No resource settings — needs settings.*

---

## ITA

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| internetaakafhandeling-web | — | — | — | — |
| ita-poller (CronJob) | — | — | — | — |

*No resource settings — needs settings.*

---

## ClamAV

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| clamav | 250m | 2Gi | 1000m | 3Gi |

---

## API Proxy

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| nginx | 100m | 128Mi | 500m | 256Mi |

---

## BRP Personen Mock

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| brp-personen-mock | 10m | 150Mi | — | — |

*Test environments only.*

---

## PABC

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| pabc | 10m | 384Mi | 200m | 768Mi |

*Disabled by default (`enabled: false`).*

---

## OMC (NotifyNL)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| omc | 250m | 128Mi | 500m | 512Mi |

*Disabled by default (`enabled: false`). Values reflect sub-chart defaults.*
