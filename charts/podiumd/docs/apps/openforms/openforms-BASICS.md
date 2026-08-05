# Open Formulieren — Basics

## Management summary

Open Formulieren (Open Forms) is the smart form builder of PodiumD. Municipal
staff design web forms in an admin interface; citizens and businesses fill them
in online, logging in with DigiD or eHerkenning where needed. Submitted forms
are automatically turned into cases and documents in Open Zaak or into records
in the Objecten API, so requests land directly in the case handling process
without manual re-entry. To run it needs a PostgreSQL database, the shared
Redis, a file share for uploads, an SMTP relay, and a Keycloak client. Its
footprint is moderate: two web pods of about 1 GiB each plus a background
worker of about 1 GiB.

## What it is

- Upstream project: [Open Forms](https://github.com/maykinmedia/open-forms)
  (Maykin Media), image `openformulieren/open-forms`, tag pinned in
  `values.yaml` (`3.4.9@sha256:55dc…`).
- Deployed as the `openforms` subchart (v1.12.0, repo `@maykinmedia`), aliased
  to values key **`openformulieren`** — note the docs folder is `openforms`
  but every values path below starts with `openformulieren.`.
- Role in the stack: form design (admin) + form rendering (public), with
  registration backends that create zaken/documenten in Open Zaak and objects
  in the Objecten API.
- Runtime components:
  - `openformulieren` web Deployment — 2 replicas (Django/uwsgi)
  - `openformulieren-worker` — 1 replica (Celery worker, liveness probe
    enabled, `maxWorkerLivenessDelta: "300"`)
  - `openformulieren-beat` — 1 replica (Celery beat scheduler)
  - `openformulieren-nginx` — nginx front (image `nginxinc/nginx-unprivileged`
    tag `1.31.1@sha256:a863…`, `clientMaxBodySize: 100M`)
  - `django-setup-configuration` Job (`configuration.job`, `backoffLimit: 6`,
    `ttlSecondsAfterFinished: 600`) — applies declarative config on install/upgrade
  - Flower is available but disabled (`flower.enabled: false`)

## Required resources

### Database

PostgreSQL — yes (external; Azure Database for PostgreSQL Flexible Server in
Dimpact environments).

Unlike most sibling apps, the `openforms` subchart renders its own Secret and
ConfigMap (both named `openformulieren`) from values:

- ConfigMap `openformulieren` — `DB_HOST` (from `global.settings.databaseHost`,
  falling back to `openformulieren.settings.database.host`), `DB_NAME`,
  `DB_USER`, `DB_PORT` (default `5432`)
- Secret `openformulieren` — `DB_PASSWORD` (from
  `openformulieren.settings.database.password`), or point
  `openformulieren.existingSecret` at an externally managed secret

The database name/user are set per environment (`settings.database.name` /
`settings.database.username`); the chart defaults are empty. The resulting
Secret/ConfigMap contract (`DB_PASSWORD` + `DB_HOST`/`DB_NAME`/`DB_USER`)
matches the repo-wide per-app convention used e.g. by the `mi:` export jobs.

### Storage

Yes — one ReadWriteMany PVC for form uploads and generated documents, rendered
by `charts/podiumd/templates/openformulieren-storage.yaml`
(guarded with `lookup` and kept via `helm.sh/resource-policy: keep`):

- PV `<namespace>-openformulieren`, Azure Files CSI (`file.csi.azure.com`),
  share name `openformulieren.persistentVolume.volumeAttributeShareName`
  (default `openformulieren`)
- PVC `openformulieren` (`persistence.existingClaim`), size
  `persistence.size: 10Gi`, storage class `podiumd-standard`
- Mounted with subpaths `openformulieren/media` and
  `openformulieren/private_media`

### Routing / exposure (NGINX Gateway Fabric)

Public. HTTPRoute `hr-openformulieren-nginx` on Gateway `public-gateway`
(namespace `ingress-basic`), hostname pattern `<env>-formulier.dimpact.nl`
(e.g. `ontw-formulier.dimpact.nl`), backend service `openformulieren-nginx`
(cf. `settings.allowedHosts: openformulieren-nginx.podiumd.svc.cluster.local`).
The HTTPRoute is created by the per-gemeente environment deployment (ADO
`ExternalsPodiumD`), not by this chart. No Kubernetes Ingress objects
(`ingress.enabled` stays false).

### Other dependencies

- **Redis** (shared `redis-ha`, bundled redis disabled via `tags.redis: false`):
  - DB **9** — cache, default + axes
    (`settings.cache.default/axes: redis-ha-master.podiumd.svc.cluster.local:6379/9`)
  - DB **10** — Celery broker + result backend
    (`settings.celery.brokerUrl` / `settings.celery.resultBackendl`:
    `redis://redis-ha-master.podiumd.svc.cluster.local:6379/10`)
  - Allocation table: `docs/apps/redis/redis-ha-databases.md`
- **Keycloak** — OIDC client in the `podiumd` realm for admin login, wired via
  django-setup-configuration (`configuration.data` →
  `oidc_db_config_admin_auth`, secret in
  `configuration.secrets.keycloak_client_secret`, redirect base
  `configuration.oidcUrl`). PKCE optional via `pkceEnabled` (requires
  `oidc_use_pkce: true` in `configuration.data`).
- **DigiD / eHerkenning** — citizen/business login as additional OIDC providers
  brokered through Keycloak (see the commented `oidc-digid` example in
  `configuration.data`: `bsn` scope, `loa_settings`, `bsn_claim_path`).
- **Open Zaak** — Zaken/Documenten/Catalogi API services (`zgw_consumers`,
  `auth_type: zgw`, client id `open-formulieren` + secret registered in Open
  Zaak's Autorisaties API) and a `zgw_api` registration-backend group.
- **Objecten / Objecttypen API** — token-authenticated services plus an
  `objects_api` registration-backend group (productaanvraag flow). Since the
  objecten/objecttypen merge (`docs/apps/objecten/openobject-migration.md`) both the
  `objecten-api` and `objecttypen-api` `zgw_consumers` identifiers in Open
  Formulieren's own config point at the same merged host — Open Formulieren's
  own schema still expects two distinct service identifiers even though
  there's only one app behind them now.
- **SMTP** — outbound mail for confirmation e-mails (`settings.email`, chart
  defaults `port: 587`, `useTLS: true`; host set per environment).
- **ClamAV** — the stack ships a `clamav` service (clamd on TCP 3310,
  `clamav.podiumd.svc.cluster.local:3310`). Virus scanning of file uploads is
  enabled at runtime in the Open Forms admin (general configuration); there
  are no ClamAV keys under `openformulieren:` in `values.yaml`.

## CPU and memory

Chart defaults (`values.yaml` + `docs/misc/resource-overview.md`) — requests only,
no limits set (burstable):

| Container | Replicas | CPU request | Mem request | CPU limit | Mem limit |
|-----------|----------|-------------|-------------|-----------|-----------|
| openformulieren (web) | 2 | 250m | 1Gi | — | — |
| openformulieren-worker | 1 | 200m | 1Gi | — | — |
| openformulieren-beat | 1 | 10m | 160Mi | — | — |
| nginx | 1 | 10m | 16Mi | — | — |

**PDB**: `minAvailable: 1` on the web deployment (see resource-overview.md).

**Observed usage** (kubectl top, 2026-07-10): on ontw, web x2
14–21m / 831–1072Mi, worker 79m / 1263Mi, beat 3m / 366Mi, nginx 1m / 5Mi; on
accp, web x2 10–11m / 859–1013Mi, worker 71m / 983Mi, beat 1m / 233Mi, nginx
2m / 6Mi. resource-overview.md flags this app **"Increase for production"**
(PDF generation and file uploads; suggested web 250m/1Gi, worker 200m/1Gi —
i.e. keep at least the chart defaults). Note the worker (up to ~1.26Gi) and
beat (~366Mi) already exceed their requests on ontw, so on busy environments
budget the worker at ~1.5Gi and the beat at ~384–512Mi. CPU numbers are idle
baseline (dev/accp), not peak.

## Integrating Open Formulieren as a new app

1. **Database**: create a PostgreSQL database + role on the environment's
   Flexible Server. Set `openformulieren.settings.database.name/username/password`
   (host comes from `global.settings.databaseHost`), or manage the secret
   externally and reference it via `openformulieren.existingSecret`.
2. **Storage**: create the Azure Files share `openformulieren` in the
   environment's storage account; the umbrella chart renders the PV/PVC
   (`templates/openformulieren-storage.yaml`, 10Gi,
   `podiumd-standard`). Adjust `openformulieren.persistence.size` /
   `persistentVolume.volumeAttributeShareName` if the environment deviates.
3. **Enable + core values**: set `openformulieren.enabled: true`
   (Chart.yaml condition), keep the pinned `image.tag`, and set
   `settings.allowedHosts` (add the public hostname), CORS/CSRF origins for
   any embedding sites, and `settings.email` (SMTP host/port/TLS/from).
4. **Keycloak client**: create an OIDC client in the `podiumd` realm for the
   public hostname; put its secret in
   `openformulieren.configuration.secrets.keycloak_client_secret`, set
   `configuration.oidcUrl` to the public URL, and fill
   `configuration.data` (`oidc_db_config_admin_auth`) following the commented
   example in `values.yaml`. Enable `pkceEnabled: true` plus
   `oidc_use_pkce: true` if the Keycloak client enforces PKCE. Add DigiD /
   eHerkenning OIDC providers the same way if citizen login is required.
5. **Register with Open Zaak / Objecten**: add an application `open-formulieren`
   (client id + secret) in Open Zaak's Autorisaties API; define the
   `zgw_consumers.services` (zaken/documenten/catalogi/objecten/objecttypen —
   the latter two point at the same merged host, see above)
   and the `objects_api` / `zgw_api` registration groups in
   `configuration.data`, including the informatieobjecttypen for the
   submission PDF/CSV/attachments and `organisatie_rsin`.
6. **DNS + HTTPRoute**: point `<env>-formulier.dimpact.nl` at the public
   gateway and have the environment deployment create HTTPRoute
   `hr-openformulieren-nginx` → service `openformulieren-nginx`.
7. **Verify**: the `django-setup-configuration` Job completes (it retries up
   to `backoffLimit: 6`); `/admin/` login via Keycloak works; submit a test
   form end-to-end and confirm the zaak/object appears in Open Zaak/Objecten;
   check worker and beat logs for Celery errors and Redis DBs 9/10 for
   activity; confirm the confirmation e-mail arrives.

## Related documents

None — this folder has only the BASICS file; no deep-dive documents exist yet
for this component.
