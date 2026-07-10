# Open Zaak — Basics

## Management summary

Open Zaak is the central case registry of PodiumD. It stores every case
("zaak"), the documents that belong to it, the decisions taken on it, and the
catalogue of case types a municipality works with. Almost every other PodiumD
application (ZAC, Open Formulieren, Open Inwoner, Open Notificaties, Open
Beheer) reads from or writes to Open Zaak, which makes it the backbone of the
stack. To run it needs a PostgreSQL database, a small Azure Files share for
document storage, the shared Redis, and a Keycloak client for admin login. Its
footprint is moderate: two web pods of roughly 0.5–0.6 GiB each plus a
background worker that peaks around 0.8 GiB.

## What it is

Upstream: [maykinmedia/open-zaak](https://github.com/open-zaak/open-zaak) — the
reference implementation of the VNG "API's voor Zaakgericht Werken" standards.
It serves five ZGW APIs: **Zaken**, **Documenten**, **Catalogi**, **Besluiten**
and **Autorisaties**. Image: `openzaak/open-zaak`, chart-pinned tag
`1.27.3@sha256:b27327...` (`openzaak.image.tag` in
`charts/podiumd/values.yaml`, lines 501–718). Deployed via the vendored Maykin
`openzaak` subchart with `nameOverride`/`fullnameOverride: openzaak`.

Runtime components:

- **openzaak web** — Django/uWSGI, 2 replicas (uwsgi: 2 processes × 4 threads,
  `maxRequests: 1000`)
- **openzaak-worker** — Celery worker, 1 replica, liveness probe enabled
  (`maxWorkerLivenessDelta: 300`)
- **openzaak-beat** — Celery beat scheduler, 1 replica
- **nginx** — sidecar/front deployment serving static files and proxying uwsgi
  (nginxinc/nginx-unprivileged `1.31.1@sha256:a863b9...`); the ClusterIP
  service is `openzaak-nginx`
- **django-config configuration job** (`openzaak.configuration.job`) — runs
  `setup_configuration` from `openzaak.configuration.data` (services, notification
  config, selectielijst, `vng_api_common` applications/credentials, admin OIDC)
- **create_required_catalogi_job** — post-install/upgrade job that loads the
  required PodiumD catalogi into Open Zaak using
  `openzaak.create_required_catalogi_job.client_id`/`secret`; optionally creates
  and publishes the e2e-test zaaktype (`e2eTestZaaktype.create: true`)
- Flower is disabled by default (`openzaak.flower.enabled: false`); OTel export
  disabled by default (`openzaak.otel.disabled: true`, see
  `values-enable-observability.yaml`)

## Required resources

### Database

PostgreSQL — yes (Azure Database for PostgreSQL Flexible Server in Dimpact
environments). Credentials follow the standard per-app contract, created by the
per-gemeente environment deployment (not by this chart):

- Secret `openzaak` — must contain `DB_PASSWORD`
- ConfigMap `openzaak` — must contain `DB_HOST`, `DB_NAME`, `DB_USER`
  (`DB_PORT` optional)

See `openzaak-db-connection-pooling.md` in this folder before enabling the
experimental psycopg pool.

### Storage

Yes. `charts/podiumd/templates/openzaak-storage.yaml` renders a PV + PVC
(guarded by `lookup`, `helm.sh/resource-policy: keep`):

- PVC name: `openzaak` (`openzaak.persistence.existingClaim`)
- Size: **10Gi** (`openzaak.persistence.size`), access mode ReadWriteMany
- Storage class: `podiumd-standard` (Azure Files CSI)
- Azure Files share: `openzaak`
  (`openzaak.persistentVolume.volumeAttributeShareName`)

The share holds uploaded documents for the Documenten API when
`openzaak.settings.documentApiBackend: filesystem` (the default). The
alternative backend is `azure_blob_storage`, configured via
`openzaak.settings.azureBlobStorage` (accountName/clientId/clientSecret/
tenantId/container) — with blob storage the PVC is not used for documents.

### Routing / exposure (NGINX Gateway Fabric)

Public. Hostname pattern `<env>-openzaak.dimpact.nl` (e.g.
`ontw-openzaak.dimpact.nl`). The HTTPRoute (`hr-openzaak-nginx`, Gateway
`public-gateway` in namespace `ingress-basic`, gatewayClass `nginx`) is created
by the per-gemeente environment deployment (ADO `ExternalsPodiumD`), not by
this chart. Backend: service `openzaak-nginx`. Keep
`openzaak.settings.allowedHosts` in sync with the public hostname (chart
default is only the in-cluster name `openzaak-nginx.podiumd.svc.cluster.local`).

### Other dependencies

- **Redis** — shared `redis-ha` (`redis-ha-master.podiumd.svc.cluster.local:6379`):
  DB **4** for Django cache and axes (`settings.cache.default` / `cache.axes`),
  DB **5** for the Celery broker and result backend (`settings.celery.brokerUrl`
  / `resultBackendl`). Allocation table: `docs/apps/redis/redis-ha-databases.md`.
- **Keycloak** — OIDC client in the `podiumd` realm for Django admin login,
  configured through `configuration.data` (`oidc_db_config_*`) with the secret
  in `openzaak.configuration.secrets.keycloak_client_secret`;
  `openzaak.configuration.oidcUrl` is the public Open Zaak URL. PKCE via
  `openzaak.configuration.pkceEnabled` (requires `oidc_use_pkce: true` in the
  config data and PKCE on the Keycloak client).
- **Open Notificaties** — Open Zaak publishes notifications
  (`configuration.notificaties.enabled: true`) using
  `openzaak_opennotificaties_secret`, and authorizes Open Notificaties against
  its Autorisaties API (`configuration.notificatiesAuthorization.enabled: true`,
  `opennotificaties_autorisatie_api_secret`).
- **Consumer applications** — every app that calls the ZGW APIs (Open
  Formulieren, Open Inwoner, Open Beheer, ZAC, ...) needs an application +
  credential pair in `configuration.data`
  (`vng_api_common_applicaties` / `vng_api_common_credentials`) with the
  secrets in `openzaak.configuration.secrets` (e.g.
  `openzaak_openforms_secret`, `openzaak_openinwoner_secret`,
  `openzaak_openbeheer_secret`).
- **Selectielijst API** — external, `https://selectielijst.openzaak.nl/api/v1/`
  (no auth), configured via `zgw_consumers` + `openzaak_selectielijst_config`.
- **SMTP** — `openzaak.settings.email` (port 587, TLS) for admin e-mail.

## CPU and memory

Chart defaults (requests only — no limits set, burstable):

| Container | CPU request | Mem request | CPU limit | Mem limit |
|-----------|-------------|-------------|-----------|-----------|
| openzaak (web, x2) | 250m | 512Mi | not set (burstable) | not set (burstable) |
| openzaak-worker | 200m | 1Gi | not set (burstable) | not set (burstable) |
| openzaak-beat | 10m | 160Mi | not set (burstable) | not set (burstable) |
| nginx | 10m | 16Mi | not set (burstable) | not set (burstable) |
| create_required_catalogi_job | 50m | 64Mi | 200m | 128Mi |
| configuration job | not set | not set | not set | not set |

Observed usage (kubectl top, 2026-07-10): on **ontw** the two web pods sit at
8–10m CPU / 560–604Mi, worker 58m / 765Mi, beat 1m / 198Mi, nginx 1m / 6Mi. On
**accp**: web 7–8m / 540–544Mi, worker 112m / 755Mi, beat 1m / 193Mi, nginx
1m / 5Mi. Web memory runs slightly above the 512Mi request even at idle, and
worker memory (~765Mi) fits inside its 1Gi request; CPU numbers are
idle-baseline, not peak.

`resource-overview.md` flags Open Zaak **"Increase for production"**: the web
pod holds Django in-memory state and production zaak volumes can be large
(suggested web 250m/512Mi as a floor); the worker peaks during bulk document
processing (keep 200m/1Gi). A PDB with `minAvailable: 1` is recommended for
the web deployment.

## Integrating Open Zaak as a new app

1. **Provision the database and credentials.** Create the `openzaak` database
   on the PostgreSQL flexible server, then the Secret `openzaak`
   (`DB_PASSWORD`) and ConfigMap `openzaak` (`DB_HOST`, `DB_NAME`, `DB_USER`)
   in the `podiumd` namespace via the environment deployment.
2. **Storage.** Ensure the Azure Files share `openzaak` exists in the
   environment's storage account; the chart renders the PV/PVC (10Gi,
   `podiumd-standard`) on first install and keeps them on delete.
3. **Set values.** In the gemeente values file: keep the pinned
   `openzaak.image.tag`; add the public hostname to
   `openzaak.settings.allowedHosts`; set `openzaak.configuration.oidcUrl` to
   `https://<env>-openzaak.dimpact.nl`; fill `openzaak.configuration.data`
   (sites, `zgw_consumers` services for Notificaties + Selectielijst,
   `notifications_config`, `vng_api_common_applicaties`/`credentials`,
   `oidc_db_config_*`) and the matching `openzaak.configuration.secrets`.
   Choose the Documenten backend via `openzaak.settings.documentApiBackend`
   (`filesystem` default, or `azure_blob_storage` + `azureBlobStorage` block).
4. **Keycloak client.** Create the Open Zaak client in the `podiumd` realm and
   put its secret in `openzaak.configuration.secrets.keycloak_client_secret`
   (enable PKCE on both sides if using `pkceEnabled: true`).
5. **Wire up notifications.** Generate the
   `openzaak_opennotificaties_secret` and
   `opennotificaties_autorisatie_api_secret` pairs and configure the same
   values on the Open Notificaties side.
6. **Catalogi job.** Set `openzaak.create_required_catalogi_job.client_id` and
   `secret` (a ZGW client with catalogi write access); leave
   `e2eTestZaaktype.create: true` unless the environment must not get the
   e2e-test zaaktype.
7. **DNS + HTTPRoute.** Point `<env>-openzaak.dimpact.nl` at the NGF public
   gateway and have the environment deployment create HTTPRoute
   `hr-openzaak-nginx` → service `openzaak-nginx`.
8. **Verify.** Check that the configuration job and
   `create_required_catalogi_job` complete (`kubectl -n podiumd get jobs`),
   that `https://<env>-openzaak.dimpact.nl/` serves the API index and
   `/admin/` logs in via Keycloak, and that a test notification reaches Open
   Notificaties. Watch pod logs for startup traps listed in
   `openzaak-known-issues.md`.

## Related documents

- [openzaak-db-connection-pooling.md](openzaak-db-connection-pooling.md) —
  uWSGI tuning (safe) and experimental psycopg DB connection pooling
  (`dbPool.enabled`) with proposed values and caveats.
- [openzaak-known-issues.md](openzaak-known-issues.md) — known issues and
  configuration traps, including the 4.7.0 chart-pin decision (chart 1.13.1 /
  app 1.27.x) and startup failure modes.
