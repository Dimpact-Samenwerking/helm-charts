# Open Inwoner — Basics

## Management summary

Open Inwoner ("Mijn omgeving") is the citizen self-service portal of PodiumD. Residents log in with DigiD and see the status of their cases (zaken), read messages from the municipality, and manage their profile and contact details. It is part of PodiumD so that citizens have one place to follow everything they have running with the municipality, fed by the same case data the back office works with. To run it needs a PostgreSQL database, the shared Redis, a file share, its own small Elasticsearch cluster for search, and connections to Keycloak, Open Zaak and Open Klant. Footprint is moderate: two web pods of about 1 GB each, three background workers, and one or more Elasticsearch nodes of about 1.5 GB each.

## What it is

- Upstream project: [Open Inwoner Platform (OIP)](https://github.com/maykinmedia/open-inwoner) by Maykin Media (Django application).
- Image: `maykinmedia/open-inwoner`, chart default tag `2.3.1` (`openinwoner.image.tag`).
- Role in PodiumD: public-facing citizen portal ("Mijn omgeving") — shows zaken from Open Zaak, messages/contactmomenten via Open Klant, personal data via BRP (haal-centraal), and company data via KvK.
- Runtime components:
  - `openinwoner` web deployment (2 replicas) with an `nginx` sidecar container
  - `openinwoner-worker` — Celery worker (background tasks)
  - `openinwoner-low-latency-worker` — dedicated Celery worker for cache-seeding/warmup tasks (new in OIP 2.3.0; queue configurable via `openinwoner.settings.cacheSeedingQueue`)
  - `openinwoner-beat` — Celery beat scheduler
  - `openinwoner-celery-monitor` — Celery monitoring container
  - `openinwoner-elasticsearch` — dedicated Elasticsearch cluster (ECK-managed `Elasticsearch` CR, pods `openinwoner-elasticsearch-es-default-*`), reconciled by the **central** `eck-operator`; the subchart-bundled `openinwoner.eck-operator` must stay `enabled: false`
  - Init containers: `openinwoner-search-index` (`settings.searchIndexInitContainer: true`) and a one-time `cms4_migration` init container for the Django CMS v3→v4 migration (`settings.cms4MigrationInitContainer`, OIP 2.3.0)
  - A setup-configuration Job (`openinwoner.configuration.job`) that loads `configuration.data` (OIDC, zgw-consumers, sites) on install/upgrade

## Required resources

### Database

- PostgreSQL: **yes** (external — Azure Database for PostgreSQL Flexible Server in Dimpact environments).
- Standard PodiumD credential contract, created by the per-gemeente environment deployment (not by this chart):
  - Secret `openinwoner` — must contain `DB_PASSWORD`
  - ConfigMap `openinwoner` — must contain `DB_HOST`, `DB_NAME`, `DB_USER` (`DB_PORT` optional)

### Storage

- PVC: **yes** — `openinwoner`, 10Gi (`openinwoner.persistence.size`), storage class `podiumd-standard`, `ReadWriteMany`.
- Rendered by `charts/podiumd/templates/openinwoner-storage.yaml`: Azure Files CSI PV named `<namespace>-openinwoner`, share name from `openinwoner.persistentVolume.volumeAttributeShareName` (default `openinwoner`; a global `persistentVolume.volumeAttributeShareName` overrides it). PV/PVC carry `helm.sh/resource-policy: keep` and are skipped if they already exist (`lookup`).
- Elasticsearch data: separate `ReadWriteOnce` volumes via the ECK nodeSet `volumeClaimTemplates` (example: 8Gi on `managed-csi`); **immutable** — changing it requires manually deleting the StatefulSet and PVCs.

### Routing / exposure (NGINX Gateway Fabric)

- Public hostname: `<env>-mijn.dimpact.nl` (e.g. `ontw-mijn.dimpact.nl`).
- HTTPRoute `hr-openinwoner-nginx` on Gateway `public-gateway` (namespace `ingress-basic`, gatewayClass `nginx`), backend service `openinwoner-nginx`. The HTTPRoute is created by the per-gemeente environment deployment (ADO `ExternalsPodiumD`), not by this chart.
- `openinwoner.settings.allowedHosts` defaults to `openinwoner-nginx.podiumd.svc.cluster.local`; add the public hostname per environment.
- When `settings.digidMock: "true"` (test environments), enable nginx basic auth (`openinwoner.nginx.config.basicAuth`) to shield the mock login.

### Other dependencies

- **Redis** (shared `redis-ha-master.podiumd.svc.cluster.local:6379`): DB **11** for cache (`default` + `axes`), DB **12** for Celery broker and result backend. See `docs/apps/redis/redis-ha-databases.md`.
- **Elasticsearch**: own dedicated cluster (`openinwoner.eck-elasticsearch`, version 9.2.0, TLS disabled), `nodeSets` configured per environment — 1 node on ontw, 2 on accp, 3 recommended for production.
- **Keycloak**: OIDC client in the `podiumd` realm for admin/DigiD login; client secret via `configuration.secrets.keycloak_client_secret`, discovery endpoint in `configuration.data` (`oidc_db_config_admin_auth`). PKCE via `configuration.pkceEnabled` plus `oidc_use_pkce: true` in the data blob.
- **Open Zaak**: consumes Zaken/Documenten/Catalogi/Besluiten APIs — ZGW client `openinwoner` with secret `openzaak_openinwoner_secret` (registered in Open Zaak's Autorisaties API), configured under `zgw_consumers` and `openzaak_config` in `configuration.data`.
- **Open Klant**: Klanten API access via token `openklant_openinwoner_token`.
- **BRP (haal-centraal)**: `settings.brpVersion` (personal data; `brp-personen-mock` in test environments).
- **KvK**: company data lookup for eHerkenning users (configured in the app/admin).
- **SMTP**: outgoing mail, `settings.email` (port 587, TLS).
- **OTel**: disabled by default (`settings.otel.disabled: true`); the `values-enable-observability.yaml` overlay enables it.

## CPU and memory

Chart defaults (from `values.yaml` and `docs/resource-overview.md`; web replicas: 2, all others 1):

| Container | CPU request | Mem request | CPU limit | Mem limit |
|-----------|-------------|-------------|-----------|-----------|
| openinwoner (web) | 200m | 1Gi | not set (burstable) | not set (burstable) |
| openinwoner-worker | 200m | 640Mi | not set (burstable) | not set (burstable) |
| openinwoner-low-latency-worker | 100m | 256Mi | not set (burstable) | not set (burstable) |
| openinwoner-beat | 50m | 128Mi | not set (burstable) | not set (burstable) |
| openinwoner-celery-monitor | 50m | 64Mi | not set (burstable) | not set (burstable) |
| nginx (sidecar) | 30m | 8Mi | not set (burstable) | not set (burstable) |
| openinwoner-search-index (init) | — | — | — | — |

Elasticsearch (per environment, via ECK nodeSet `podTemplate`): ontw-dim1 runs 1 node at 200m/1536Mi request, 1000m/1536Mi limit; production recommendation is **3 nodes** at 500m/4Gi request, 2000m/4Gi limit (memory request = limit; JVM heap = half the limit).

Observed usage (2026-07-10): on **ontw** — web x2 at 16–18m / 980–991Mi, worker 48m / 915Mi, low-latency-worker 6m / **1518Mi**, beat 2m / 253Mi, celery-monitor 3m / 218Mi, ES (1 node) 14m / 1509Mi, nginx 1m / 16Mi. On **accp** — web x2 at 25–48m / 939–974Mi, worker 58m / 818Mi, beat 2m / 234Mi, celery-monitor 2m / 212Mi, ES x2 at 12–14m / 1563–1594Mi, nginx 1m / 5Mi. Web pods sit right at their 1Gi request, and the worker (818–915Mi) and especially the low-latency-worker (1.5Gi observed vs 256Mi request) run well above their requests — size worker memory requests up for production. CPU numbers are idle baselines, not peaks.

Flags from `resource-overview.md`:

- The `openinwoner-search-index` init container has **no resource settings** — needs settings.
- **Increase for production**: a single ES node is a SPOF for search; 3 nodes recommended (minimum for a proper quorum).
- PDB: `minAvailable: 1` for the web deployment. The ECK-managed ES PDB defaults to `minAvailable: 0` — raise to 1 when running 2+ ES nodes.

## Integrating Open Inwoner as a new app

1. **Provision the database**: create the PostgreSQL database and role, then create Secret `openinwoner` (`DB_PASSWORD`) and ConfigMap `openinwoner` (`DB_HOST`, `DB_NAME`, `DB_USER`) in the target namespace (done by the per-gemeente environment deployment).
2. **Storage**: ensure the Azure Files share `openinwoner` exists (or set `openinwoner.persistentVolume.volumeAttributeShareName`); the chart renders the PV/PVC (`podiumd-standard`, 10Gi) on first install.
3. **Keycloak client**: create an OIDC client for Open Inwoner in the `podiumd` realm; put its secret in `openinwoner.configuration.secrets.keycloak_client_secret` and configure `oidc_db_config_admin_auth` (discovery endpoint, claims) in `openinwoner.configuration.data`. Set `configuration.oidcUrl` to the public URL. For PKCE set `configuration.pkceEnabled: true` **and** `oidc_use_pkce: true` in the data blob.
4. **Register with Open Zaak / Open Klant**: add an Autorisaties API application in Open Zaak for client id `openinwoner` (secret → `configuration.secrets` as `openzaak_openinwoner_secret`) and issue an Open Klant token (`openklant_openinwoner_token`); wire both into `zgw_consumers.services` and `openzaak_config.api_groups` in `configuration.data`.
5. **Set environment values**: `openinwoner.image.tag`, `settings.allowedHosts` (add `<env>-mijn.dimpact.nl`), `settings.brpVersion`, `settings.email`, `sites_config` (public domain), and the per-environment `eck-elasticsearch.nodeSets` block (count, resources, ES_JAVA_OPTS, volumeClaimTemplates). Keep `openinwoner.eck-operator.enabled: false` — the central operator reconciles the ES CR.
6. **DNS + HTTPRoute**: point `<env>-mijn.dimpact.nl` at the NGF public gateway and have the environment deployment create HTTPRoute `hr-openinwoner-nginx` → service `openinwoner-nginx`.
7. **Verify**: setup-configuration Job completes; ES cluster goes green (`kubectl get elasticsearch openinwoner-elasticsearch -n podiumd`); the search-index init container finishes; DigiD/OIDC login works on the public URL; zaken from Open Zaak and messages from Open Klant appear; Celery workers/beat show no errors in logs.

## Related documents

- [openinwoner-outgoing-request-logging.md](openinwoner-outgoing-request-logging.md) — how to stop Open Inwoner logging outgoing HTTP requests (no master switch in OIP; per-handler workaround).
