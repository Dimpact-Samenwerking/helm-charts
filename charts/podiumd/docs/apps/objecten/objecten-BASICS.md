# Objecten — Basics

## Management summary

Objecten (Objects API) is the central registry in PodiumD where applications store and
retrieve structured data records — for example contact requests, internal tasks,
employees, departments and knowledge articles. Every record must conform to a
definition (an "object type"); as of Open Object 4.0, Objecten manages those
definitions itself rather than delegating to a separate Objecttypen
application, so all applications still read and write the same well-defined
data, just from one app instead of two. Frontends such as Open Formulieren, KISS, OMC
and ZAC rely on it to hand work items and contact data to each other. It needs a
PostgreSQL database, the shared Redis, a small file share and a public hostname. Its
footprint is modest: two web pods and one background worker, roughly 1.5 GiB of memory
in total under normal load.

## What it is

- Upstream: [Open Object (maykinmedia/open-object)](https://github.com/maykinmedia/open-object),
  the successor to the separate `objects-api`/`objecttypes-api` projects
  (Django/uwsgi + Celery).
- **As of Open Object 4.0, the Objecttypen API (object-type schemas) is part
  of Objecten** — merged into one application. The former separate
  `objecttypen` subchart, values block, Keycloak client, Redis database and
  public hostname are all retired; see `openobject-migration.md` (this
  directory) for the full migration record.
- Deployed via the `openobject` subchart (version `1.1.1`, repo
  `@maykinmedia`), **aliased to `objecten`** in `Chart.yaml` (`alias:
  objecten`, condition `objecten.enabled`) so every values key, rendered
  object name, and DNS name still say `objecten`.
- Image: `maykinmedia/open-object`, tag `4.1.0` (`objecten.image.tag`) — was
  `maykinmedia/objects-api` before the merge.
- Runtime components:
  - `objecten` — web Deployment, 2 replicas (chart default).
  - `objecten-worker` — Celery worker Deployment, 1 replica
    (`objecten.worker.replicaCount`), liveness probe enabled.
  - `django-config` Job (`objecten.configuration.job`) — one-shot
    django-setup-configuration run that loads `objecten.configuration.data`
    (zgw-consumers services, notifications config, token auth, objecttypes
    registrations, sites, admin OIDC) at install/upgrade.
  - No beat scheduler and no Flower (`objecten.flower.enabled: false`).

Role in the stack: stores objects (contactmomenten, InterneTaak, Medewerker,
Afdeling/Groep, Kennisartikel, VAC, Productaanvraag-Dimpact, Activiteitenlog, ...)
whose schemas are now defined locally in Objecten itself, rather than in a
separate Objecttypen API. Consumers include Open Formulieren
(productaanvragen), KISS, OMC and ZAC. The umbrella template
`templates/create-required-objecttypen.yaml` creates those required object
types — it is now gated on `objecten.*` values and talks to Objecten
directly (it used to talk to the separate Objecttypen app).

## Required resources

### Database

PostgreSQL (Azure Database for PostgreSQL Flexible Server in Dimpact environments).
Per-app credential convention, provisioned by the per-gemeente environment deployment
(not by this chart):

- Secret `objecten` — must contain `DB_PASSWORD`.
- ConfigMap `objecten` — must contain `DB_HOST`, `DB_NAME`, `DB_USER`
  (`DB_PORT` optional).

### Storage

Yes — `templates/objecten-storage.yaml` renders a PersistentVolume + PVC (both
`lookup`-guarded, so they are only created when absent, and annotated
`helm.sh/resource-policy: keep`):

- PVC name: `objecten` (`objecten.persistence.existingClaim`), size **10Gi**
  (`objecten.persistence.size`), access mode ReadWriteMany.
- Azure Files CSI (`file.csi.azure.com`), storage class `podiumd-standard`,
  share name `objecten` (`objecten.persistentVolume.volumeAttributeShareName`),
  mounted uid/gid 1000.

### Routing / exposure (NGINX Gateway Fabric)

Public at `<env>-objecten.dimpact.nl` (e.g. `ontw-objecten.dimpact.nl`) via HTTPRoute
`hr-objecten-nginx` on Gateway `public-gateway` (namespace `ingress-basic`,
gatewayClass `nginx`). The HTTPRoute is created by the per-gemeente environment
deployment (ADO `ExternalsPodiumD`), not by this chart, and points at the Objecten
ClusterIP service. In-cluster the app answers on
`objecten.podiumd.svc.cluster.local` (`objecten.settings.allowedHosts`).

### Other dependencies

- **Redis** (shared `redis-ha-master.podiumd.svc.cluster.local:6379`):
  - DB **1** — cache (`default`, `axes`, `oidc`) via `objecten.settings.cache.*`.
  - DB **2** — Celery broker + result backend via `objecten.settings.celery.*`.
- **Objecttypes** — every object references an object type; since the merge
  these are **local data** inside Objecten, not a call to a separate
  Objecttypen API/service (the old `objecttypes-api` zgw-consumers service
  and its `object_objecttypes_token` no longer apply).
- **Open Notificaties** — Objecten publishes notifications; zgw-consumers service
  `notifications-api` with token `object_notificaties_token`.
- **Keycloak** — admin OIDC login: client in the `podiumd` realm, secret in
  `objecten.configuration.secrets.keycloak_client_secret`, provider settings in the
  `oidc_db_config_*` block of `objecten.configuration.data`;
  `objecten.configuration.pkceEnabled: true` enables PKCE (requires `pkceEnabled:
  true` on the Keycloak client and `oidc_use_pkce: true` in the config data).
- **API consumers** — token-auth items in `objecten.configuration.data`
  (`tokenauth_config_enable`), e.g. `openformulieren_objecten_token` for Open
  Formulieren and a token for Open Archiefbeheer; add one item per consuming app
  (KISS, OMC, ZAC, ...).
- **SMTP** — `objecten.settings.email` (port 587, TLS).
- **OpenTelemetry** — disabled by default (`objecten.otel.disabled: true`);
  the `values-enable-observability.yaml` override enables it.

## CPU and memory

Chart defaults (from `values.yaml` / `docs/misc/resource-overview.md`); replicas: 2 web, 1
worker:

| Container | CPU request | Mem request | CPU limit | Mem limit |
|-----------|-------------|-------------|-----------|-----------|
| objecten (web) | 100m | 256Mi | not set (burstable) | not set (burstable) |
| objecten-worker | 50m | 192Mi | not set (burstable) | not set (burstable) |
| django-config job | not set (`configuration.job.resources: {}`) | not set | not set | not set |

Observed usage (2026-07-10): on ontw, web pods 4–5m CPU / 504–608Mi each and the
worker 70m / 277Mi; on accp, web pods 3m / 524–599Mi each and the worker 66m / 259Mi.
Web memory sits at roughly twice the 256Mi request on both clusters, so plan node
capacity for ~600Mi per web pod and consider raising the memory request accordingly;
worker requests are close to reality. CPU is idle-baseline on these clusters — treat
it as a floor, not a peak. `resource-overview.md` recommends a PodDisruptionBudget
`minAvailable: 1` for the web deployment (no PDB on the single-replica worker).

## Integrating Objecten as a new app

1. **Provision the database and credentials.** Create the `objecten` database on the
   environment's PostgreSQL server, then (via the environment deployment) the Secret
   `objecten` (`DB_PASSWORD`) and ConfigMap `objecten` (`DB_HOST`, `DB_NAME`,
   `DB_USER`) in the `podiumd` namespace.
2. **Set chart values.** Leave `objecten.enabled` unset (or set `true`); pin
   `objecten.image.tag`; set `objecten.configuration.oidcUrl` and the
   `sites_config` domain to the public hostname; keep the Redis DB 1/2 URLs from the
   defaults (see `docs/apps/redis/redis-ha-databases.md` before changing indexes).
3. **Storage.** Ensure the Azure Files share `objecten` exists (or override
   `objecten.persistentVolume.volumeAttributeShareName`); the chart renders the
   10Gi PV/PVC on first install.
4. **Keycloak client.** Create an OIDC client for Objecten in the `podiumd` realm and
   put its secret in `objecten.configuration.secrets.keycloak_client_secret`; fill the
   `oidc_db_config_*` section of `objecten.configuration.data` (discovery endpoint,
   client id, claim mappings). Enable PKCE on both sides if required.
5. **Wire the ZGW services.** In `objecten.configuration.data`, define the
   zgw-consumers service for Open Notificaties (`object_notificaties_token`),
   enable `notifications_config_enable`, and add `tokenauth` items for each
   consumer (Open Formulieren, Open Archiefbeheer, KISS/OMC/ZAC as
   applicable). Put the token values in `objecten.configuration.secrets`.
6. **Object types.** Object types are local data now — make sure the
   required set exists via `objecttypes_config_enable`/`objecttypes` in
   `objecten.configuration.data` (the `create-required-objecttypen-job`,
   configured under `objecten.*`, seeds the standard Dimpact set) and
   register the UUIDs the consumers need.
7. **DNS + HTTPRoute.** Add DNS for `<env>-objecten.dimpact.nl` and have the
   environment deployment create HTTPRoute `hr-objecten-nginx` on
   `public-gateway`/`ingress-basic` pointing at the Objecten service.
8. **Verify.** `helm upgrade` with `--atomic`; check the `django-config` job completes
   (`kubectl -n podiumd get jobs`, logs), both web pods and the worker go Ready
   (`kubectl -n podiumd rollout status deploy/objecten`), the admin UI is reachable at
   `https://<env>-objecten.dimpact.nl/admin/` with Keycloak login, and
   `/api/v2/objects` answers with a valid consumer token.

## Related documents

- [`openobject-migration.md`](openobject-migration.md) (this directory) — the
  full record of the objecten/objecttypen merge: data-migration mechanics,
  values old-key → new-key mapping, template diff, and design decisions.
