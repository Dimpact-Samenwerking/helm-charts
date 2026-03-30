# PodiumD Resource Overview

Resource requests and limits for all chart components. Values reflect the chart defaults (podiumd `values.yaml` combined with sub-chart defaults). Limits marked `-` are not set — the container is burstable.

## Legend

| Symbol | Meaning |
|--------|---------|
| — | Not set (burstable / best-effort) |
| *needs settings* | No defaults exist; must be configured per environment |
| ⚠️ **Increase for production** | Default is sufficient for dev/test but expected to be insufficient under production load |
| `(op)` | Managed by an operator via CRD — not a plain Helm `resources:` field. See section notes for how to configure. |

## PodDisruptionBudget (PDB)

PDBs prevent all pods of a workload from being evicted simultaneously during node maintenance. They are only meaningful for components running **2 or more replicas**.

**PDBs managed automatically by operators** (no manual configuration needed):
- `zac-solr-solrcloud` — `maxUnavailable: 2` (Solr Operator)
- `zac-solr-solrcloud-zookeeper` — `maxUnavailable: 1` (Solr Operator)
- `kiss-es-default` — `minAvailable: 1` (ECK Operator)
- `openinwoner-elasticsearch-es-default` — `minAvailable: 0` (ECK Operator; should be raised to 1 for ≥2 ES nodes on production)

**PDBs to add manually for production** (components with ≥2 replicas where no PDB exists):

| Component | Recommended PDB |
|-----------|-----------------|
| openzaak | `minAvailable: 1` |
| openklant | `minAvailable: 1` |
| openformulieren | `minAvailable: 1` |
| openinwoner | `minAvailable: 1` |
| opennotificaties | `minAvailable: 1` |
| objecten | `minAvailable: 1` |
| objecttypen | `minAvailable: 1` |
| keycloak | `minAvailable: 1` |
| contact-web (KISS) | `minAvailable: 1` |

> Components with a single replica (ClamAV, ZAC, workers, beats, nginx sidecars, operators) should **not** have a PDB — it would block node drains entirely.

---

## Keycloak

Default replicas: **2**

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit | Notes |
|-----------|-------------|-------------|-----------|-----------|-------|
| keycloak-builder (init) `(op)` | 250m | 512Mi | 1000m | 1Gi | Set by keycloak-operator |
| keycloak `(op)` | 500m | 1700Mi | 1000m | 2Gi | Set via `keycloak.resources` → `spec.resources` in Keycloak CR |

Resources for the main Keycloak container are set via `spec.resources` in the Keycloak CR — this is the supported field provided by the operator. The operator's built-in defaults (when nothing is set) are `1700Mi` request and `2Gi` limit (memory only, no CPU). The chart now explicitly sets these via `keycloak.resources` to also add a CPU request of `500m`.

> ⚠️ **Increase for production**: Suggested memory request `2Gi`, limit `3Gi` for environments with many realms or high SSO load. CPU limit intentionally not set (burstable).

**PDB**: Add `minAvailable: 1` (see table above).

### Keycloak Operator

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| keycloak-operator | 100m | 128Mi | 500m | 256Mi |
| job: ensurePodiumdAdminUser | 50m | 64Mi | 200m | 128Mi |
| job: ensureOperatorSa | 50m | 64Mi | 200m | 128Mi |
| job: importPodiumdRealm (kc-config-cli) | 50m | 256Mi | 200m | 512Mi |
| job: importMasterRealm (kc-config-cli) | 50m | 256Mi | 200m | 512Mi |

Values keys: `keycloak-operator.operator.resources` (operator pod), `keycloak-operator.jobs.resources` (curl/python/psql job containers), `keycloak-operator.jobs.configCliResources` (kc-config-cli — Spring Boot JVM, needs more memory).

---

## Redis Operator

Redis HA runs **3 replicas** by default (StatefulSet).

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit | Notes |
|-----------|-------------|-------------|-----------|-----------|-------|
| redis-operator | 100m | 128Mi | 500m | 256Mi | |
| redis-ha `(op)` | 100m | 256Mi | 500m | 512Mi | Set via `redis-operator.redis-ha.resources` → RedisReplication CRD |
| redis-ha exporter `(op)` | 100m | 128Mi | 500m | 256Mi | Set via `redis-operator.redis-ha.resources` → RedisReplication CRD |
| redis-ha init busybox `(op)` | 10m | 16Mi | 50m | 32Mi | Set via `redis-operator.redis-ha.initContainerResources` → RedisReplication CRD |

> ⚠️ **Increase for production**: Redis holds all Celery task queues and Django caches. Under production load 128Mi per pod may be tight if many tasks are queued simultaneously. Suggested: memory request `256Mi`, limit `512Mi`.

*Redis HA StatefulSet has built-in quorum (3 replicas). A PDB is not required but may be added with `minAvailable: 2` to protect quorum.*

---

## Open Zaak

Default replicas: **2** (web), **1** (worker, beat, nginx)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| openzaak | 250m | 512Mi | — | — |
| openzaak-worker | 200m | 1Gi | — | — |
| openzaak-beat | 10m | 160Mi | — | — |
| nginx | 10m | 16Mi | — | — |

> ⚠️ **Increase for production**: The web pod holds Django in-memory state; production zaak volumes can be large. Suggested: CPU request `250m`, memory request `512Mi`. Worker can reach peak usage during bulk document processing — consider `200m / 1Gi`.

**PDB**: Add `minAvailable: 1` for the web deployment.

---

## Open Notificaties

Default replicas: **2** (web), **1** (worker, beat), **1** (RabbitMQ)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| opennotificaties | 100m | 256Mi | — | — |
| opennotificaties-worker | 50m | 386Mi | — | — |
| opennotificaties-beat | 50m | 128Mi | — | — |
| rabbitmq | 300m | 256Mi | — | — |

> ⚠️ **Increase for production**: RabbitMQ memory of 256Mi is low; under high notification throughput it will hit the memory high-watermark and throttle publishers. Suggested: `300m / 512Mi` request, `500m / 1Gi` limit. Worker may also need `100m / 512Mi` under load.

**PDB**: Add `minAvailable: 1` for the web deployment.

---

## Objecten

Default replicas: **2** (web), **1** (worker)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| objecten | 100m | 256Mi | — | — |
| objecten-worker | 50m | 192Mi | — | — |

**PDB**: Add `minAvailable: 1` for the web deployment.

---

## Objecttypen

Default replicas: **2**

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| objecttypen | 10m | 160Mi | — | — |

**PDB**: Add `minAvailable: 1`.

---

## Open Archiefbeheer

Default replicas: **1** (all components)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| openarchiefbeheer | 250m | 256Mi | — | — |
| openarchiefbeheer-worker | 100m | 256Mi | — | — |
| openarchiefbeheer-beat | 50m | 128Mi | — | — |
| openarchiefbeheer-nginx | 10m | 16Mi | — | — |Suggested: worker `100m / 256Mi`, beat `50m / 128Mi`, nginx `10m / 16Mi`.

---

## Open Klant

Default replicas: **2** (web), **1** (worker, nginx)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| openklant | 100m | 300Mi | — | — |
| openklant-worker | 50m | 200Mi | — | — |
| openklant-nginx | 10m | 16Mi | — | — |

**PDB**: Add `minAvailable: 1` for the web deployment.

---

## Open Formulieren

Default replicas: **2** (web), **1** (worker, beat, nginx)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| openformulieren | 250m | 1Gi | — | — |
| openformulieren-worker | 200m | 1Gi | — | — |
| openformulieren-beat | 10m | 160Mi | — | — |
| nginx | 10m | 16Mi | — | — |

> ⚠️ **Increase for production**: Form submissions can involve PDF generation and file uploads. Suggested: web `250m / 1Gi`, worker `200m / 1Gi`.

**PDB**: Add `minAvailable: 1` for the web deployment.

---

## Open Inwoner

Default replicas: **2** (web), **1** (worker, beat, celery-monitor, nginx)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| openinwoner | 200m | 1Gi | — | — |
| openinwoner-worker | 200m | 640Mi | — | — |
| openinwoner-beat | 50m | 128Mi | — | — |
| openinwoner-celery-monitor | 50m | 64Mi | — | — |
| nginx | 30m | 8Mi | — | — |
| openinwoner-search-index (init) | — | — | — | — |

*openinwoner-search-index init container has no resource settings — needs settings.*

**PDB**: Add `minAvailable: 1` for the web deployment.

### Open Inwoner — Elasticsearch (ECK, per environment)

Configured per environment via `openinwoner.eck-elasticsearch.nodeSets`.

| Environment | Replicas | CPU Request | Mem Request | CPU Limit | Mem Limit | Notes |
|-------------|----------|-------------|-------------|-----------|-----------|-------|
| ontw-dim1 | 1 | 200m | 1536Mi | 1000m | 1536Mi | `(op)` — set by ECK via nodeSet podTemplate |
| **production (recommended)** | **3** | **500m** | **4Gi** | **2000m** | **4Gi** | `(op)` — set by ECK via nodeSet podTemplate |

> ⚠️ **Increase for production**: A single ES node is a SPOF for search. 3 nodes recommended for production (minimum for a proper quorum). ES JVM heap is automatically set to half of the memory limit, so `4Gi` limit → `2Gi` heap — the standard recommendation for general workloads. Memory request and limit should match to avoid OOM eviction.

**PDB**: ECK manages the PDB automatically. Raise `minAvailable` from `0` to `1` in the ECK `pdb` spec when using 2+ nodes.

---

## KISS Elastic (ECK Operator)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit | Notes |
|-----------|-------------|-------------|-----------|-----------|-------|
| elastic-operator (manager) | 100m | 150Mi | 1000m | 1Gi | |
| elasticsearch `(op)` | — | 2Gi | — | 2Gi | Set by ECK operator; configure via `kiss-elastic` Elasticsearch CR |
| kibana `(op)` | — | 1Gi | — | 1Gi | Set by ECK operator; configure via Kibana CR |
| enterprise-search `(op)` | — | 4Gi | — | 4Gi | Set by ECK operator; configure via EnterpriseSearch CR |
| elastic-internal-init-filesystem (init) `(op)` | 100m | 50Mi | 100m | 50Mi | Set by ECK operator |

*Elasticsearch, Kibana and Enterprise Search CPU requests not set — needs settings.*

> ⚠️ **Increase for production**: KISS Elasticsearch defaults have only limits with no requests — this puts pods in the Burstable QoS class and makes them eviction candidates under node pressure. Suggested for production: ES `500m / 4Gi` (request = limit for Guaranteed QoS), Kibana `200m / 1Gi`, Enterprise Search `500m / 4Gi`.

**PDB**: ECK manages the PDB automatically (`minAvailable: 1` for the 3-node ES cluster).

---

## KISS

Default replicas: **2** (contact-web frontend), **1** (adapter, syncJobs)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| kiss (frontend) | 100m | 256Mi | — | — |
| adapter (podiumd-adapter) | 10m | 100Mi | — | — |
| syncJobs (kennisbank, medewerkers, vac) | — | — | — | — |

*syncJobs have no resource settings — needs settings.* Suggested: `100m / 256Mi`.

**PDB**: Add `minAvailable: 1` for the contact-web deployment.

---

## ZAC

Default replicas: **1** (all components)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| zac | 100m | 1Gi | — | — |
| opa (sidecar) | 10m | 20Mi | — | — |
| init-solr-zac-core (init) | 50m | 256Mi | — | — |
| nginx | 50m | 64Mi | — | — |
| office-converter | 100m | 512Mi | — | — |
| signaleren (CronJob) | — | — | — | — |

*signaleren (CronJob) has no resource settings — needs settings.* Suggested: `100m / 256Mi`.

> ⚠️ **Increase for production**: ZAC is a Quarkus JVM application. Under production load with many concurrent zaakafhandeling flows, 1Gi may be insufficient. Suggested: `500m / 2Gi` request, no CPU limit. Office converter is CPU-intensive for large DOCX/PDF; consider `500m / 1Gi` on production.

### ZAC — Solr (Operator managed)

Default replicas: **3** (SolrCloud), **1** (Zookeeper)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit | Notes |
|-----------|-------------|-------------|-----------|-----------|-------|
| solr-operator | 100m | 128Mi | 500m | 256Mi | `zac.solr-operator.resources` |
| solrcloud-node `(op)` | 500m | 1Gi | 2000m | 2Gi | `zac.solr-operator.solr.resources` → SolrCloud CRD |
| zookeeper-operator | 50m | 64Mi | 200m | 128Mi | `zac.solr-operator.zookeeper-operator.resources` |
| zookeeper `(op)` | 100m | 256Mi | 500m | 512Mi | `zac.solr-operator.zookeeper-operator.zookeeper.resources` → SolrCloud CRD |

> JVM heap is set via `javaMem` in the ZAC chart (default `Xms512m Xmx768m`). The `solr.resources` and `zookeeper.resources` fields (added in ZAC chart 1.0.204) map to the SolrCloud CRD.

> ⚠️ **Increase for production**: Default JVM heap of 512–768Mi is suitable for dev. Production with large ZAAK indices should use `Xms1g Xmx2g`. Container memory limit must be ~1.5× the heap to account for off-heap usage. Suggested: `1000m / 3Gi` per SolrCloud node. Zookeeper: `200m / 512Mi`.

**PDB**: Managed by the Solr Operator (`maxUnavailable: 2` for SolrCloud, `maxUnavailable: 1` for Zookeeper).

---

## ZGW Office Addin

Default replicas: **1** (all components)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| frontend | 50m | 64Mi | — | — |
| backend | 100m | 256Mi | — | — |

---

## ITA

Default replicas: **1** (all components)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| internetaakafhandeling-web | — | — | — | — |
| ita-poller (CronJob) | — | — | — | — |

> ⚠️ **Chart limitation — ITA resources cannot be set via values.yaml.** The ITA subchart (`internetaakafhandeling`) does not expose a Kubernetes `resources` field for its web deployment or poller. The `web.resources` key in the chart is repurposed for branding configuration (logoUrl, faviconUrl, designTokensUrl) and has no effect on pod resource requests/limits. Raised with ITA/interne-taak-afhandeling team.

---

## ClamAV

Default replicas: **1** (StatefulSet)

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| clamav | 250m | 2Gi | 1000m | 3Gi |

ClamAV loads its entire virus database into memory (~900Mi). The 2Gi request reflects this well. No PDB — single instance.

---

## API Proxy

Default replicas: **1**

| Container | CPU Request | Mem Request | CPU Limit | Mem Limit |
|-----------|-------------|-------------|-----------|-----------|
| nginx | 100m | 128Mi | 500m | 256Mi |

---

## BRP Personen Mock

Default replicas: **1**

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
