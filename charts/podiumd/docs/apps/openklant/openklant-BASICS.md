# Open Klant — Basics

## Management summary

Open Klant is the customer-data registry of PodiumD. It stores who a citizen or
company is (contact details, digital addresses) and every contact moment the
municipality has with them — phone calls, questions, internal follow-up tasks.
Other PodiumD applications (the KISS contact centre, Open Inwoner citizen
portal, ZAC case handling, OMC notifications) read and write this data through
its API, so residents get consistent answers no matter which channel they use.
It needs a PostgreSQL database, a small file share, the shared Redis cluster
and a public hostname. Footprint is modest: two small web pods, one background
worker and an nginx sidecar.

## What it is

- Upstream project: [maykinmedia/open-klant](https://github.com/maykinmedia/open-klant)
  — provides the **Klantinteracties API** (klanten/partijen, digitale adressen,
  contactmomenten, interne taken) of the ZGW landscape.
- Image: `maykinmedia/open-klant`, chart-default tag `2.15.0`
  (`openklant.image.tag`); nginx sidecar `nginx:1.31.1@sha256:a863b95e…`.
- Role in PodiumD: single source of customer/contact data, consumed by KISS,
  OMC, Open Inwoner and ZAC.
- Runtime components:
  - `openklant` web deployment — 2 replicas (Django/uwsgi, `2` processes ×
    `4` threads per pod via `openklant.settings.uwsgi`)
  - `openklant-worker` — 1 replica (Celery worker)
  - `openklant-nginx` — nginx serving static files in front of the web pods
  - `openklant` configuration Job — runs `setup_configuration` on
    install/upgrade (`openklant.configuration.job.enabled: true`)

## Required resources

### Database

- PostgreSQL: **yes** (Azure Database for PostgreSQL Flexible Server in
  Dimpact environments).
- Credential contract (created by the per-gemeente environment deployment,
  not by this chart):
  - Secret `openklant` — must contain `DB_PASSWORD`
  - ConfigMap `openklant` — must contain `DB_HOST`, `DB_NAME`, `DB_USER`
    (`DB_PORT` optional)

### Storage

- PVC: **yes** — 10Gi (`openklant.persistence.size`), storage class
  `podiumd-standard`, access mode ReadWriteMany.
- Rendered by `charts/podiumd/templates/openklant-storage.yaml`: an Azure
  Files CSI PersistentVolume (`<namespace>-openklant`, reclaim policy Retain,
  `helm.sh/resource-policy: keep`) bound to PVC `openklant`
  (`openklant.persistence.existingClaim`). The Azure Files share name comes
  from `openklant.persistentVolume.volumeAttributeShareName` (default
  `openklant`). Both objects are `lookup`-guarded, so pre-existing PV/PVCs
  are left untouched.

### Routing / exposure (NGINX Gateway Fabric)

- Public hostname pattern: `<env>-openklant.dimpact.nl`
  (e.g. `ontw-openklant.dimpact.nl`).
- HTTPRoute `hr-openklant-nginx` on Gateway `public-gateway` (namespace
  `ingress-basic`, gatewayClass `nginx`), created by the per-gemeente
  environment deployment (ADO `ExternalsPodiumD`) — not by this chart. The
  route backend is the `openklant-nginx` ClusterIP service.

### Other dependencies

- **Redis** (shared `redis-ha`, `redis-ha-master.podiumd.svc.cluster.local:6379`):
  - DB `7` — Django cache + axes (`openklant.settings.cache`)
  - DB `8` — Celery broker and result backend (`openklant.settings.celery`)
  - Allocation table: `docs/apps/redis/redis-ha-databases.md`.
- **Keycloak**: OIDC client in the `podiumd` realm for admin login
  (`openklant.configuration.secrets.keycloak_client_secret`,
  `openklant.configuration.oidcUrl`; set `openklant.configuration.pkceEnabled:
  true` plus `oidc_use_pkce: true` in `configuration.data` for PKCE).
- **API tokens for consumers**: token-auth entries in
  `openklant.configuration.data` (`tokenauth` items) give KISS, OMC,
  Open Inwoner (`openklant_openinwoner_token`), Open Archiefbeheer and ZAC
  access to the Klantinteracties API.
- **SMTP**: outbound mail on port 587 with TLS
  (`openklant.settings.email`).
- No ClamAV, Elasticsearch, RabbitMQ or Open Zaak/Open Notificaties
  registration required.

## CPU and memory

Chart defaults (`charts/podiumd/values.yaml` + `docs/misc/resource-overview.md`);
no limits are set (burstable):

| Container | Replicas | CPU request | Mem request | CPU limit | Mem limit |
|-----------|----------|-------------|-------------|-----------|-----------|
| openklant (web) | 2 | 100m | 300Mi | not set (burstable) | not set (burstable) |
| openklant-worker | 1 | 50m | 200Mi | not set (burstable) | not set (burstable) |
| openklant-nginx | 1 | 10m | 16Mi | not set (burstable) | not set (burstable) |

**Observed usage** (kubectl top, 2026-07-10): on `aks-blue-ontw-dimp` the two
web pods used 3–4m CPU / 239–278Mi, the worker 44m / 235Mi and nginx
1m / 16Mi; on `aks-blue-accp-dimp` web 3m / 311–363Mi, worker 38m / 232Mi,
nginx 1m / 5Mi. Web memory sits at or slightly above the 300Mi request under
light load, so the defaults are adequate but tight — consider raising the web
memory request to ~400Mi for production. CPU numbers are idle-ish baselines,
not peaks. `resource-overview.md` also recommends a PodDisruptionBudget with
`minAvailable: 1` for the web deployment.

## Integrating Open Klant as a new app

1. **Provision the database**: create a PostgreSQL database and user for
   Open Klant on the environment's Flexible Server, then create the Secret
   `openklant` (`DB_PASSWORD`) and ConfigMap `openklant` (`DB_HOST`,
   `DB_NAME`, `DB_USER`) in the `podiumd` namespace via the environment
   deployment.
2. **Set chart values** in the per-gemeente values file:
   - `openklant.image.tag` — pin the release (chart default `2.15.0`).
   - `openklant.settings.allowedHosts` — add the public hostname next to the
     cluster-internal default `openklant.podiumd.svc.cluster.local`.
   - `openklant.persistentVolume.volumeAttributeShareName` — Azure Files
     share (default `openklant`); create the share up front.
   - Leave `openklant.settings.cache` / `openklant.settings.celery` on Redis
     DBs 7/8 unless the allocation table says otherwise.
3. **Keycloak client**: create an OIDC client in the `podiumd` realm, put its
   secret in `openklant.configuration.secrets.keycloak_client_secret`, set
   `openklant.configuration.oidcUrl` to the public URL, and enable the
   `oidc_db_config_*` block in `openklant.configuration.data` (see the
   commented example in values.yaml).
4. **Issue consumer tokens**: add `tokenauth` items in
   `openklant.configuration.data` for each consumer (Open Inwoner via
   `openklant_openinwoner_token`, KISS, OMC, Open Archiefbeheer, ZAC) and
   configure the matching token on the consumer side.
5. **DNS + HTTPRoute**: add the `<env>-openklant.dimpact.nl` DNS record and
   have the environment deployment create HTTPRoute `hr-openklant-nginx` on
   `public-gateway` pointing at service `openklant-nginx`.
6. **Verify**: `helm upgrade` renders the PV/PVC and runs the configuration
   Job to completion (`kubectl get jobs -n podiumd`,
   `kubectl logs -n podiumd job/<openklant-config-job>`); the admin UI at
   `https://<env>-openklant.dimpact.nl/admin/` logs in via Keycloak; the
   Klantinteracties API answers at `/klantinteracties/api/v1/`; worker pod
   log shows Celery connected to Redis DB 8.

## Related documents

None — this folder has only the BASICS file; no deep-dive documents exist yet
for this component.
