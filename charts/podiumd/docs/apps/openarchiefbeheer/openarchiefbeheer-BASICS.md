# Open Archiefbeheer — Basics

## Management summary

Open Archiefbeheer (OAB, in PodiumD environments known as "ABC") is the
records-management tool of the PodiumD stack. Record managers use it to build,
review and execute destruction lists: closed zaken whose retention period (per
the selectielijst) has expired are selected, approved and then destroyed in the
case registers. This gives municipalities a controlled, auditable way to meet
their legal archiving obligations. It runs as a small Django application (web,
background worker, scheduler, nginx sidecar) and needs a PostgreSQL database,
the shared Redis, a small file share and API access to Open Zaak. Its footprint
is modest: roughly 0.4 CPU requested and under 1 GiB memory in total across the
four containers.

## What it is

- Upstream project: [maykinmedia/open-archiefbeheer](https://github.com/maykinmedia/open-archiefbeheer)
- Image: `maykinmedia/open-archiefbeheer:2.0.0` (digest-pinned in `openarchiefbeheer.image.tag`)
- Role in PodiumD: archiving/destruction of zaken according to the selectielijst,
  operating on the Open Zaak ZGW APIs and cleaning up related records in
  Objecten and Open Klant.
- Runtime components (1 replica each, `replicaCount: 1`):
  - `openarchiefbeheer` — Django web application
  - `openarchiefbeheer-worker` — Celery worker (executes destruction runs)
  - `openarchiefbeheer-beat` — Celery beat scheduler
  - `openarchiefbeheer-nginx` — nginx sidecar deployment (image `nginx:1.31.1`, digest-pinned)
  - `openarchiefbeheer-config` — one-shot django-setup-configuration Job
    (`configuration.job.enabled: true`, `backoffLimit: 6`, `ttlSecondsAfterFinished: 600`)

## Required resources

### Database

- PostgreSQL: **yes** (Azure Database for PostgreSQL Flexible Server in Dimpact
  environments; host via `global.settings.databaseHost`).
- Credential contract (created by the per-gemeente environment deployment, not
  by this chart):
  - Secret `openarchiefbeheer` — must contain `DB_PASSWORD`
  - ConfigMap `openarchiefbeheer` — must contain `DB_HOST`, `DB_NAME`, `DB_USER`
    (`DB_PORT` optional)
- The component is also a default target of the MI export CronJobs
  (`mi.targets` in `values.yaml`), which reuse the same Secret/ConfigMap.

### Storage

- PVC: **yes** — `charts/podiumd/templates/openarchiefbeheer-storage.yaml`
  renders a PV/PVC pair (lookup-guarded, `helm.sh/resource-policy: keep`):
  - PVC name: `openarchiefbeheer` (`openarchiefbeheer.persistence.existingClaim`)
  - Size: `10Gi` (`openarchiefbeheer.persistence.size`)
  - Storage class: `podiumd-standard`, access mode `ReadWriteMany`
  - Azure Files CSI share: `openarchiefbeheer`
    (`openarchiefbeheer.persistentVolume.volumeAttributeShareName`; the global
    `persistentVolume.volumeAttributeShareName` overrides it when set)
  - PV is named `<namespace>-openarchiefbeheer`.

### Routing / exposure (NGINX Gateway Fabric)

- Public hostname: `<env>-abc.dimpact.nl` (e.g. `ontw-abc.dimpact.nl`).
- HTTPRoute `hr-openarchiefbeheer-nginx` on Gateway `public-gateway`
  (namespace `ingress-basic`, gatewayClass `nginx`), backend service
  `openarchiefbeheer-nginx`. The HTTPRoute is created by the per-gemeente
  environment deployment (ADO `ExternalsPodiumD`), not by this chart.
- `settings.allowedHosts` defaults to the cluster-internal name
  (`openarchiefbeheer.podiumd.svc.cluster.local`); the public hostname is added
  per environment.

### Other dependencies

- **Redis** — shared `redis-ha` (`tags.redis: false`, no own Redis):
  - db **13**: default + axes cache (`settings.cache.default` / `settings.cache.axes`)
  - db **14**: choices cache **and** Celery broker + result backend
    (`settings.cache.choices`, `settings.celery.brokerUrl`,
    `settings.celery.resultBackendl` — note the trailing `l` typo in the key)
  - Allocation registered in `docs/apps/redis/redis-ha-databases.md`.
- **Keycloak** — OIDC admin login via a client `openarchiefbeheer` in the
  `podiumd` realm. Client secret in
  `openarchiefbeheer.configuration.secrets.keycloak_client_secret`; discovery
  endpoint and claim mappings in the `oidc_db_config_admin_auth` block of
  `configuration.data`. PKCE optional via `configuration.pkceEnabled` (chart
  default `false`; see the known-issues doc before enabling `oidc_use_pkce`).
- **Open Zaak** — OAB consumes the Zaken, Documenten, Catalogi and Besluiten
  APIs with ZGW auth (`auth_type: zgw`, `client_id: openarchiefbeheer`, secret
  via env `oab_openzaak_secret`). Open Zaak must have a matching Applicatie +
  credential for that client id (per-gemeente `openzaak`
  `vng_api_common_applicaties`/`vng_api_common_credentials` config).
- **Selectielijst API** — public `https://selectielijst.openzaak.nl/api/v1/`
  (`auth_type: no_auth`).
- **Objecten** — consumed via token auth; the same token must be registered on
  the Objecten side (`objecten` tokenauth item `identifier: openarchiefbeheer`,
  placeholder `REP_OBJECTEN_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP`).
- **Open Klant** — klantinteracties API via token auth (`openklant` tokenauth
  item `identifier: openarchiefbeheer`, placeholder
  `REP_OPENKLANT_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP`). The service
  identifier in OAB's `zgw_consumers` **must exactly match** the identifier in
  `external_registers.openklant.services_identifiers` (in most PodiumD
  environments: `openklant-api`, not `openklant-klantinteracties`).
- No ClamAV, Elasticsearch or RabbitMQ dependency.

## CPU and memory

Chart defaults (`values.yaml` + `docs/resource-overview.md`, 1 replica each):

| Container | CPU request | Mem request | CPU limit | Mem limit |
|-----------|-------------|-------------|-----------|-----------|
| openarchiefbeheer (web) | 250m | 256Mi | not set (burstable) | not set (burstable) |
| openarchiefbeheer-worker | 100m | 256Mi | not set (burstable) | not set (burstable) |
| openarchiefbeheer-beat | 50m | 128Mi | not set (burstable) | not set (burstable) |
| openarchiefbeheer-nginx | 10m | 16Mi | not set (burstable) | not set (burstable) |

**Observed usage** (kubectl top, 2026-07-10): on ontw — web 2m/329Mi, beat
0m/144Mi, nginx 1m/4Mi, worker 74m/284Mi; on accp — web 3m/397Mi, beat
1m/131Mi, nginx 1m/5Mi, worker 109m/249Mi. CPU is far below the requests
(idle-ish baseline), but web and worker memory sit **above** their 256Mi
requests on both clusters. For production, raise the memory request of web and
worker to ~512Mi; the other defaults are adequate. `resource-overview.md` has
no "Increase for production" flag for this component beyond the suggested
worker/beat/nginx requests, which are already the chart defaults.

## Integrating Open Archiefbeheer as a new app

1. **Database**: create the PostgreSQL database and role, then create the
   Secret `openarchiefbeheer` (`DB_PASSWORD`) and ConfigMap `openarchiefbeheer`
   (`DB_HOST`, `DB_NAME`, `DB_USER`) in the `podiumd` namespace (done by the
   per-gemeente environment deployment).
2. **Storage**: ensure the Azure Files share `openarchiefbeheer` exists (the
   chart renders the PV/PVC on first install; both carry
   `helm.sh/resource-policy: keep`).
3. **Enable and configure** in the environment values:
   - `openarchiefbeheer.enabled: true`
   - `openarchiefbeheer.settings.allowedHosts`: add `<env>-abc.dimpact.nl`
   - `openarchiefbeheer.settings.frontendUrl` and
     `settings.frontend.apiUrl` / `settings.frontend.zaakUrlTemplate`
   - `openarchiefbeheer.configuration.oidcUrl`: the public app URL
   - Keep `settings.oidcRenewIdTokenExpirySeconds` equal to
     `settings.sessionCookieAge` (both default 1800) to prevent timeout
     mismatches.
4. **Keycloak client**: create client `openarchiefbeheer` in the `podiumd`
   realm; put its secret in
   `openarchiefbeheer.configuration.secrets.keycloak_client_secret` (or supply
   via `existingConfigurationSecrets`). Map a `roles` claim with a `Superuser`
   group for admin access (see the `oidc_db_config_admin_auth` example in
   `values.yaml`).
5. **Register with Open Zaak**: add an Applicatie + credential for
   `client_id: openarchiefbeheer` on the Open Zaak side and set the same secret
   as env `oab_openzaak_secret` in OAB's `configuration.data`
   (`zgw_consumers.services` for zaken/documenten/catalogi/besluiten +
   the public selectielijst service).
6. **Register tokens on Objecten and Open Klant**: add tokenauth items
   `identifier: openarchiefbeheer` on both, and configure the matching
   `external_registers` block in OAB — service identifiers must match the
   `zgw_consumers` identifiers exactly (`objecten-api`, `openklant-api`).
7. **DNS + HTTPRoute**: create DNS `<env>-abc.dimpact.nl` and the HTTPRoute
   `hr-openarchiefbeheer-nginx` on `public-gateway` pointing at service
   `openarchiefbeheer-nginx` (environment deployment).
8. **Verify**: the `openarchiefbeheer-config` Job completes (watch for the
   TTL-vs-`--wait` race documented in the known-issues doc); log in via
   Keycloak at `https://<env>-abc.dimpact.nl`; check worker/beat logs; confirm
   the external registers (Open Zaak, Objecten, Open Klant) resolve in the UI.

## Related documents

- [openarchiefbeheer-known-issues.md](openarchiefbeheer-known-issues.md) —
  configuration traps: `oidc_use_pkce` rejected by setup_configuration in OAB
  2.0.0, the config-Job TTL vs `helm --wait` race, and the
  openklant service-identifier mismatch pitfall.
