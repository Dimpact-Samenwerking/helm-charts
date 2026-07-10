# Objecttypen — Basics

## Management summary

Objecttypen is the catalogue of "object type" definitions used by the PodiumD
platform. It stores the blueprints (schemas) that describe what records in the
Objecten registry look like — for example an employee, a department, an
internal task, a knowledge article or a product request. Other PodiumD parts
(Objecten, Open Formulieren, KISS/contact, Open Beheer, ITA) read these
definitions so that everyone stores and validates data the same way. It needs
only a PostgreSQL database, the shared Redis cache and a Keycloak login for
administrators. The footprint is small: two lightweight web pods and two
short-lived setup jobs that run at install/upgrade time.

## What it is

- Upstream: [maykinmedia/objecttypes-api](https://github.com/maykinmedia/objecttypes-api)
  — a Django implementation of the VNG Objecttypen API standard.
- Image (pinned in `charts/podiumd/values.yaml`):
  `maykinmedia/objecttypes-api:3.4.2@sha256:d366e6ede1bb924ea351495f4e88ceba53bb0df02fa5302929daef379131fda1`.
- Deployed as the vendored subchart `objecttypen` 1.6.1 (repository
  `@maykinmedia`, condition `objecttypen.enabled`), with
  `fullnameOverride: objecttypen`.
- Role in the stack: schema registry for the Objecten API. Objecten records
  reference an objecttype URL here; consumers authenticate with API tokens.
- Runtime components:
  - **web** — 2 replicas (subchart `replicaCount: 2`), uWSGI (2 processes ×
    2 threads, `objecttypen.settings.uwsgi`). No worker, no beat, no nginx
    sidecar — live clusters confirm only `objecttypen x2` pods.
  - **objecttypen-config Job** — django-setup-configuration
    (`objecttypen.configuration.job`, backoffLimit 6,
    ttlSecondsAfterFinished 600): loads token-auth items and the OIDC admin
    login config from `objecttypen.configuration.data`.
  - **create-required-objecttypen-job** — PodiumD-specific seeding Job
    (umbrella template `charts/podiumd/templates/create-required-objecttypen.yaml`,
    gated by `objecttypen.create_required_objecttypen_job.enabled`). Runs a
    Python script against `<configuration.oidcUrl>/api/v2` using the admin API
    token `objecttypen.configuration.token` and creates the eight object types
    PodiumD requires — Medewerker, Afdeling, Groep, InterneTaak,
    Kennisartikel, VAC, Productaanvraag-Dimpact and Activiteitenlog — each
    with a published version fetched from the open-objecten community schemas
    (Activiteitenlog from the ITA repo). Idempotent: existing types (matched
    by name) are left alone. backoffLimit 10, activeDeadlineSeconds 900.

## Required resources

### Database

PostgreSQL, yes. Unlike most PodiumD apps, this subchart renders its own DB
wiring instead of expecting a pre-created ConfigMap/Secret:

- ConfigMap `objecttypen` (rendered by the subchart) gets `DB_HOST`
  (`global.settings.databaseHost`, falling back to
  `objecttypen.settings.database.host`), `DB_NAME`, `DB_USER`, `DB_PORT`
  from `objecttypen.settings.database.*`.
- Secret `objecttypen` (rendered by the subchart) gets `DB_PASSWORD`
  (`settings.database.password`) and `SECRET_KEY` (`settings.secretKey`).
  Alternatively set `objecttypen.existingSecret` to a pre-provisioned Secret
  containing `DB_PASSWORD` and `SECRET_KEY`; the subchart then renders no
  Secret of its own.

DB name/user/password are per-environment values (not set in the chart
defaults). Connection pooling is configurable via
`settings.database.db_pool_*` (default 3 pool workers).

### Storage

None. No PVC and no `objecttypen-storage.yaml` template — the app is
stateless apart from its database. (The subchart bundles an optional Redis
with persistence, but PodiumD disables it via `objecttypen.tags.redis: false`
and uses the shared redis-ha instead.)

### Routing / exposure (NGINX Gateway Fabric)

Public. HTTPRoute `hr-objecttypen-nginx` with hostname
`<env>-objecttypen.dimpact.nl` (e.g. `ontw-objecttypen.dimpact.nl`) on
Gateway `public-gateway` in namespace `ingress-basic`, created by the
per-gemeente environment deployment (ADO `ExternalsPodiumD`) — not by this
chart. Backend is the app's ClusterIP service `objecttypen` on port 80 (the
subchart has no nginx service; the route name just follows the environment
naming convention). `objecttypen.settings.allowedHosts` must include the
public hostname (chart default only lists
`objecttypen.podiumd.svc.cluster.local`).

### Other dependencies

- **Redis**: shared `redis-ha` at
  `redis-ha-master.podiumd.svc.cluster.local:6379`, **DB 0** for both the
  default and axes caches (`objecttypen.settings.cache.default/axes`; see
  `docs/apps/redis/redis-ha-databases.md`).
- **Keycloak**: client `objecttypen` in the `podiumd` realm is rendered by
  `charts/podiumd/templates/keycloak-podiumd-realm-config.yaml`; its secret
  comes from `objecttypen.configuration.secrets.keycloak_client_secret`.
  Admin UI login via OIDC is configured through the
  `oidc_db_config_admin_auth` block in `objecttypen.configuration.data`.
  Optional PKCE (S256) via `objecttypen.configuration.pkceEnabled` (needs
  `oidc_use_pkce: true` in the data block too).
- **API tokens** (token auth, configured as `tokenauth.items` in
  `configuration.data` with values from `configuration.secrets`):
  `object_objecttypes_token` (Objecten → Objecttypen),
  `openformulieren_objecten_token`, and `objecttypen_openbeheer_token` for
  Open Beheer. Per the IN-2345 note in values.yaml, the Open Beheer token
  MUST equal the `Token <...>` value in openbeheer's objecttypen-service
  header, and its tokenauth entry must only be enabled when openbeheer is
  enabled and the secret is provisioned — the config Job fails on an
  unsubstituted `REP_..._REP` placeholder.
- **SMTP**: `objecttypen.settings.email` (port 587, TLS) for Django email.
- **OpenTelemetry**: disabled by default (`objecttypen.otel.disabled: true`);
  `values-enable-observability.yaml` enables it.

## CPU and memory

Chart defaults (from `charts/podiumd/values.yaml` and
`docs/misc/resource-overview.md`; replicas: 2):

| Container | CPU request | Mem request | CPU limit | Mem limit |
|-----------|-------------|-------------|-----------|-----------|
| objecttypen (web) | 10m | 160Mi | not set (burstable) | not set (burstable) |
| create-required-objecttypen-job | 50m | 64Mi | 200m | 128Mi |
| objecttypen-config Job | not set (burstable) | not set (burstable) | not set (burstable) | not set (burstable) |

**Observed usage** (kubectl top, 2026-07-10): ontw `objecttypen x2` at
3–4m CPU / 275–356Mi memory; accp `objecttypen x2` at 3m / 352–360Mi. CPU is
negligible at idle, but steady memory (~275–360Mi per pod) sits well above
the 160Mi request — for production, raise the memory request towards the
observed ~350–400Mi to avoid node overcommit. `docs/misc/resource-overview.md`
flags no "increase for production" beyond this, but does prescribe a
PodDisruptionBudget with `minAvailable: 1` for the 2-replica web deployment
(the subchart supports it via `pdb.create: true`, default off).

## Integrating Objecttypen as a new app

1. **Database**: create a PostgreSQL database and user for objecttypen on the
   environment's Flexible Server. Set `objecttypen.settings.database.name`,
   `.username`, `.password` and `objecttypen.settings.secretKey` in the
   per-environment values (host is inherited from
   `global.settings.databaseHost`), or pre-create a Secret with
   `DB_PASSWORD` + `SECRET_KEY` and point `objecttypen.existingSecret` at it.
2. **Enable and configure**: set `objecttypen.enabled: true` (subchart
   condition). Keep the pinned `objecttypen.image` tag+digest. Set
   `objecttypen.settings.allowedHosts` to include
   `<env>-objecttypen.dimpact.nl` and
   `objecttypen.configuration.oidcUrl: https://<env>-objecttypen.dimpact.nl`.
3. **Keycloak client**: provide
   `objecttypen.configuration.secrets.keycloak_client_secret` and add the
   `oidc_db_config_enable` / `oidc_db_config_admin_auth` block to
   `objecttypen.configuration.data` (see the commented example in
   values.yaml). Optionally enable PKCE with
   `objecttypen.configuration.pkceEnabled: true`.
4. **API tokens**: set the consumer tokens in
   `objecttypen.configuration.secrets` (`object_objecttypes_token`,
   `objecttypen_openbeheer_token` when openbeheer is enabled) and matching
   `tokenauth.items` in `objecttypen.configuration.data`. Set
   `objecttypen.configuration.token` — the admin token the seeding job uses.
5. **Seeding**: leave `objecttypen.create_required_objecttypen_job.enabled:
   true` so the eight PodiumD-required object types are created on install.
   Note the job fetches JSON schemas from raw.githubusercontent.com, so it
   needs outbound internet access.
6. **DNS + HTTPRoute**: register `<env>-objecttypen.dimpact.nl` and have the
   environment deployment create the HTTPRoute on `public-gateway`
   (namespace `ingress-basic`) targeting service `objecttypen:80`.
7. **Verify**: both Jobs (`objecttypen-config`,
   `create-required-objecttypen-job`) complete (`kubectl get jobs -n
   podiumd`); admin login at `https://<env>-objecttypen.dimpact.nl/admin/`
   via Keycloak works; `GET /api/v2/objecttypes` with a `Token <...>` header
   returns the seeded object types.
