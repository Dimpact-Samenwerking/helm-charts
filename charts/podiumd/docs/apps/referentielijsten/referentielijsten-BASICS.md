# Referentielijsten — Basics

## Management summary

Referentielijsten is a small service that publishes shared reference lists — standard
value tables such as communication channels or country codes — through one central API.
Instead of every application keeping its own copy of these tables, all PodiumD components
can read the same, consistently maintained values from this single source, which prevents
typos and mismatches in case data. It is part of PodiumD as the reference-data backbone
behind the "zaakgericht werken" applications. To run it needs a PostgreSQL database, a
small Azure file share, Redis and a Keycloak client. Its footprint is tiny: one web pod
using roughly 280 MiB memory and near-idle CPU.

## What it is

- Upstream: Maykin Media [`referentielijsten`](https://github.com/maykinmedia/referentielijsten),
  a Django application implementing the VNG Referentielijsten API standard (serving
  "landelijke tabellen" / reference lists). Added to PodiumD in chart release 4.6.1,
  **disabled by default** (`referentielijsten.enabled: false`).
- Image: `maykinmedia/referentielijsten-api:0.7.3` (digest-pinned in
  `charts/podiumd/values.yaml`).
- Delivered as a vendored sub-chart dependency (`referentielijsten` v0.1.1, repository
  `@maykinmedia`), aliased `referentielijsten` with `fullnameOverride: referentielijsten`.
- Role: central provider of reference lists/tables that other PodiumD components consume
  over its REST API; administrators maintain the lists via the Django admin (Keycloak
  OIDC login).
- Runtime components:
  - web Deployment, `replicaCount: 1` (uWSGI, `2` processes × `2` threads,
    `maxRequests: 1000`; serves HTTP directly on port 8000 — **no nginx sidecar** in the
    sub-chart, unlike most other PodiumD apps)
  - `django-setup-configuration` Job on install/upgrade
    (`referentielijsten.configuration.job.enabled: true`, `backoffLimit: 6`,
    `ttlSecondsAfterFinished: 600`)
  - the sub-chart's bundled Redis is disabled (`referentielijsten.tags.redis: false`) —
    the shared `redis-ha` is used instead.

## Required resources

### Database

PostgreSQL, yes — by convention database `referentielijsten`, user `referentielijsten` on
the shared Azure Database for PostgreSQL Flexible Server. Like Open Beheer (and unlike
apps using the external `<component>` Secret/ConfigMap contract), it is wired directly
through chart values:
`referentielijsten.settings.database.{host,port,username,password,name,sslmode}`
(`sslmode` defaults to `prefer`, port `5432`; `DB_HOST` falls back to
`global.settings.databaseHost` when set). The sub-chart renders its own `referentielijsten`
Secret (`DB_PASSWORD`, `SECRET_KEY`) and ConfigMap (`DB_HOST`/`DB_NAME`/`DB_USER`/`DB_PORT`);
an `existingSecret` value can substitute the Secret. Database and user are provisioned by
the per-gemeente environment deployment, not by this chart.

### Storage

Yes — a 10 GiB `ReadWriteMany` Azure Files PVC, rendered by
`charts/podiumd/templates/referentielijsten-storage.yaml`:

- Static PV `<namespace>-referentielijsten` (`file.csi.azure.com`), reclaim policy
  **Retain**, `helm.sh/resource-policy: keep` — PV, PVC and share survive
  `helm uninstall`. No dynamic provisioning: the Azure file share must pre-exist.
- Share name from `referentielijsten.persistentVolume.volumeAttributeShareName:
  referentielijsten`; storage class `podiumd-standard`; PVC name `referentielijsten`
  (`referentielijsten.persistence.existingClaim`); size
  `referentielijsten.persistence.size: 10Gi`.
- Mounted at `/app/media` and `/app/private_media` (subpaths `referentielijsten/media`
  and `referentielijsten/private_media`); mount options `uid=1000`/`gid=1000` match the
  container user.

### Routing / exposure (NGINX Gateway Fabric)

Public. In Dimpact environments an HTTPRoute `hr-referentielijsten-nginx` on Gateway
`public-gateway` (namespace `ingress-basic`, gatewayClass `nginx`) routes
`<env>-referentielijsten.dimpact.nl` (e.g. `ontw-referentielijsten.dimpact.nl`). The
HTTPRoute, the fronting `referentielijsten-nginx` service and the DNS record are created
by the per-gemeente environment deployment (ADO `ExternalsPodiumD`), not by this chart —
the chart itself only creates the ClusterIP service `referentielijsten` (port 80 →
container port 8000). `referentielijsten.settings.allowedHosts` defaults to
`referentielijsten-nginx.podiumd.svc.cluster.local` accordingly. The public hostname must
match the host in `referentielijsten.configuration.oidcUrl` — the realm-config job derives
the Keycloak redirect URIs (`{oidcUrl}/*`) from it. For non-NGF environments the sub-chart
also ships an optional classic Ingress template (`referentielijsten.ingress.*`, disabled
by default).

### Other dependencies

- **Redis**: shared `redis-ha` at `redis-ha-master.podiumd.svc.cluster.local:6379`,
  **db 15** for both `default` and `axes` caches
  (`referentielijsten.settings.cache.*`); db 16 is reserved but unused — Referentielijsten
  runs no Celery worker. Allocation table: `docs/apps/redis/redis-ha-databases.md`.
- **Keycloak**: OIDC client `referentielijsten` on realm `podiumd`, created automatically
  by the realm-config job; secret from
  `referentielijsten.configuration.secrets.keycloak_client_secret` (values.yaml marks it
  **required in all environments** — it is also imported into the realm as
  `referentielijsten-oidc-secret`). Optional PKCE via
  `referentielijsten.configuration.pkceEnabled` (requires `oidc_use_pkce: true` in
  `configuration.data`). Admin OIDC login itself is configured declaratively via the
  commented `configuration.data` example in values.yaml (django-setup-configuration).
- **SMTP**: optional, `referentielijsten.settings.email.*` (umbrella defaults: port 587,
  TLS on; host per environment).
- Django `SECRET_KEY` via `referentielijsten.settings.secretKey` (pipeline-injected).
- No Open Zaak / Open Notificaties registration — Referentielijsten neither publishes nor
  subscribes to notificaties; it is a standalone data provider consumed by other apps.

## CPU and memory

Chart defaults (`charts/podiumd/values.yaml` and sub-chart defaults; Referentielijsten has
**no** section in `docs/resource-overview.md`):

| Container | CPU request | CPU limit | Memory request | Memory limit |
|---|---|---|---|---|
| web (x1) | not set (burstable) | not set | not set (burstable) | not set |
| configuration job | not set (burstable) | not set | not set (burstable) | not set |

Observed usage (2026-07-10, `kubectl top pods -n podiumd`): on aks-blue-ontw-dimp the
single web pod uses ~3m CPU and 278 MiB memory. Not deployed on accp at capture time. CPU
is essentially idle at dev load; memory is steady just under 300 MiB. Sizing
recommendation: for production set explicit requests of roughly 50m CPU / 384 Mi memory
(limit ~512 Mi) on the web pod; one replica is adequate for a read-mostly reference-data
service, but raise `replicaCount` to 2 if the environment requires zero-downtime rollouts.

## Integrating Referentielijsten as a new app

1. **Provision the database**: create database `referentielijsten` and user
   `referentielijsten` on the shared PostgreSQL Flexible Server; store the password in
   Key Vault following the environment's `<component>-db-admin-<env>` convention.
2. **Create the Azure file share**: share `referentielijsten` (10 GiB) in the storage
   account the cluster-wide CSI credential (`persistentVolume.nodeStageSecretRefName` /
   `...Namespace`) authenticates against — the PV is static, the share must pre-exist.
3. **Provision Key Vault secrets**: Django `SECRET_KEY` (`openssl rand -base64 50`) and
   the Keycloak client secret (`openssl rand -hex 32`).
4. **Enable and configure** in the environment values file:
   ```yaml
   referentielijsten:
     enabled: true
     configuration:
       oidcUrl: https://<env>-referentielijsten.dimpact.nl
       secrets:
         keycloak_client_secret: "REP_REFERENTIELIJSTEN_KEYCLOAK_CLIENT_SECRET_REP"
       data: |-
         # OIDC provider for admin login — use the commented example in
         # values.yaml (referentielijsten.configuration.data)
     settings:
       secretKey: "REP_REFERENTIELIJSTEN_SECRET_KEY_REP"
       database:
         host: <pg-host>          # or rely on global.settings.databaseHost
         name: referentielijsten
         username: referentielijsten
         password: "REP_REFERENTIELIJSTEN_DB_PASSWORD_REP"
   ```
   For ACR-based environments also override `referentielijsten.image.repository` to
   `<acr>/referentielijsten-api` (keep the chart's pinned tag).
5. **Keycloak client**: created automatically by the realm-config job from
   `configuration.oidcUrl`; populate the client secret **before** the first deploy so the
   realm import and the app configuration agree.
6. **DNS + HTTPRoute**: have the environment deployment create the
   `<env>-referentielijsten.dimpact.nl` DNS record, the `referentielijsten-nginx` front
   service and the HTTPRoute on `public-gateway`; the hostname must match
   `configuration.oidcUrl`.
7. **Verify**: configuration Job completes (`kubectl -n podiumd get jobs -l
   app.kubernetes.io/name=referentielijsten` → 1/1); pod Ready with 0 restarts; browse to
   `https://<env>-referentielijsten.dimpact.nl/admin/` and confirm the Keycloak redirect
   works; confirm the API serves the reference tables and that consuming applications can
   read them.
