# Open Notificaties — Basics

## Management summary

Open Notificaties is the message hub of PodiumD. When something changes in a
case — for example Open Zaak registers a new zaak, document or besluit — Open
Notificaties passes that news on to every other application that asked to be
kept informed. Without it, applications such as ZAC, Open Inwoner and OMC would
not notice changes made elsewhere in the stack. It needs a PostgreSQL database,
the shared Redis cluster and a Keycloak client to run. Its footprint is modest:
four small pods using roughly 1.2 GiB of memory in total on the Dimpact
clusters.

## What it is

Upstream project: [Open Notificaties](https://github.com/open-zaak/open-notificaties)
by Maykin Media — the reference implementation of the VNG/ZGW **Notificaties
API** (publish/subscribe for zaakgericht werken events). Image:
`openzaak/open-notificaties`, pinned to tag `1.16.1` in the umbrella chart.
Deployed via the `opennotificaties` subchart (version 2.0.0, repo
`@maykinmedia`), gated on `opennotificaties.enabled`.

> **Naming quirk**: the subchart key is `opennotificaties` (and
> `nameOverride`/`fullnameOverride` are set to `opennotificaties`), but the
> per-environment DB credential Secret and ConfigMap are named **`notificaties`**
> (see the `mi.targets` comment in `values.yaml`). Keep this in mind when
> looking for its configuration on a cluster.

Runtime components:

- **web** — Django/API deployment, 2 replicas (subchart default), container port 8000, exposed by ClusterIP Service `opennotificaties` on port 80. No nginx sidecar in this subchart.
- **worker** — Celery worker that delivers notifications to subscribers, 1 replica (umbrella override; subchart default is 2), with exec liveness probe (`worker.livenessProbe.enabled: true`, `maxWorkerLivenessDelta: "300"`).
- **beat** — Celery beat scheduler, 1 replica.
- **setup-configuration Job** — `configuration.job.enabled: true`; applies kanalen, credentials, OIDC and subscription config from `configuration.data` on each deploy.
- **flower** — disabled (`flower.enabled: false`).

RabbitMQ was **removed in subchart 2.0.0 / app 1.16.0**: the Celery broker,
result backend and publish broker now all use the shared `redis-ha` cluster.
Environments still running an older release (e.g. accp at the time of the live
snapshot) show an `opennotificaties-rabbitmq-0` pod; that disappears after
upgrading to chart 2.0.0. `tags.redis` must stay `false` — the subchart's
bundled Redis dependency is not used, and enabling the tag breaks the render
(see the comment block in `values.yaml`).

## Required resources

### Database

PostgreSQL: **yes** (external; Azure Database for PostgreSQL Flexible Server in
Dimpact environments, host via `global.settings.databaseHost` / per-app config).
Credentials follow the per-app convention, **but with the `notificaties` name**:

- Secret `notificaties` — must contain `DB_PASSWORD` (other app secrets may live here too)
- ConfigMap `notificaties` — must contain `DB_HOST`, `DB_NAME`, `DB_USER` (`DB_PORT` optional)

Both are created by the per-gemeente environment deployment, not by this chart.

### Storage

PVC: **yes** — 10Gi (`opennotificaties.persistence.size`), storage class
`podiumd-standard`, Azure Files CSI share `opennotificaties` via
`opennotificaties.persistentVolume.volumeAttributeShareName`. The PV/PVC pair is
rendered by `charts/podiumd/templates/opennotificaties-storage.yaml` (PV name
`<namespace>-opennotificaties`, claim `opennotificaties`).

### Routing / exposure (NGINX Gateway Fabric)

Public hostname `<env>-notificaties.dimpact.nl` (observed:
`ontw-notificaties.dimpact.nl`). The HTTPRoute (`hr-opennotificaties-nginx` on
Gateway `public-gateway` in namespace `ingress-basic`) is created by the
per-gemeente environment deployment (ADO `ExternalsPodiumD`), not by this
chart. The route name contains `-nginx` for historical consistency, but the
subchart has no nginx component — the backend is the ClusterIP Service
`opennotificaties` on port 80. `settings.allowedHosts` must include the
hostnames used (chart default lists the in-cluster name
`opennotificaties.podiumd.svc.cluster.local`).

### Other dependencies

- **Redis (shared `redis-ha`)** — db **3** for cache (`settings.cache.default`/`axes`), db **6** for the Celery broker, result backend and publish broker (`settings.celery.brokerUrl`/`publishBrokerUrl` and `settings.messageBroker.celeryResultBackend` — the last one is required; missing it breaks the render). Allocation table: `docs/apps/redis/redis-ha-databases.md`.
- **Keycloak** — client `opennotificaties` in the `podiumd` realm (rendered by `templates/keycloak-podiumd-realm-config.yaml`); admin OIDC login configured via `configuration.data` (`oidc_db_config_*`) with `configuration.secrets.keycloak_client_secret`; `configuration.oidcUrl` must be the public URL; PKCE optional via `configuration.pkceEnabled` plus `oidc_use_pkce` in the data.
- **Open Zaak Autorisaties API** — Open Notificaties consumes Open Zaak's Autorisaties API (`zgw_consumers` service `autorisaties-api`, client id `open-notificaties`, secret `opennotificaties_autorisatie_api_secret`) and holds `vng_api_common_credentials` for both directions (`openzaak_opennotificaties_secret` for Open Zaak calling in, `opennotificaties_opennotificaties_secret` for its own autorisaties subscription). The same client id/secret pairs must be mirrored in the `openzaak` values block.
- **Kanalen / abonnementen** — notification channels (`zaken`, `documenten`, `besluiten`, `zaaktypen`, ...) and subscriptions are provisioned declaratively via `configuration.data` (`notifications_kanalen_config`, `notifications_abonnementen_config`) applied by the setup-configuration Job.
- **SMTP** — `settings.email` (port 587, TLS) for admin/error mail.

## CPU and memory

Chart defaults (umbrella `values.yaml`; limits not set — burstable):

| Container | CPU request | Mem request | CPU limit | Mem limit |
|-----------|-------------|-------------|-----------|-----------|
| opennotificaties (web, x2) | 100m | 256Mi | not set (burstable) | not set (burstable) |
| opennotificaties-worker | 50m | 386Mi | not set (burstable) | not set (burstable) |
| opennotificaties-beat | 50m | 128Mi | not set (burstable) | not set (burstable) |

`resource-overview.md` additionally lists `rabbitmq` at 300m/256Mi with an
"increase for production" warning — that row only applies to pre-2.0.0 releases
that still run RabbitMQ; from subchart 2.0.0 there is no RabbitMQ pod. The same
note warns the **worker may need 100m / 512Mi under load**, and recommends a
PodDisruptionBudget `minAvailable: 1` for the web deployment.

**Observed usage** (kubectl top, 2026-07-10): ontw — web x2 at 4–5m /
498–499Mi, beat 2m / 159Mi, worker 19m / 125Mi; accp — web x2 at 5m /
487–558Mi, beat 1m / 189Mi, worker 34m / 420Mi, plus `rabbitmq-0` 7m / 132Mi
(pre-2.0.0 release). Web pods consistently sit around 500Mi, double the 256Mi
request — consider raising the web memory request to ~512Mi so scheduling
reflects reality; worker usage on accp (420Mi) also brushes its 386Mi request.
CPU is negligible at dev/accp load; treat these as baseline, not peak.

## Integrating Open Notificaties as a new app

1. **Provision the database and credentials.** Create the PostgreSQL database
   on the environment's Flexible Server, then create Secret `notificaties`
   (with `DB_PASSWORD`) and ConfigMap `notificaties` (with `DB_HOST`,
   `DB_NAME`, `DB_USER`) in the `podiumd` namespace — note the `notificaties`
   name, not `opennotificaties`.
2. **Enable and configure the subchart.** Set `opennotificaties.enabled: true`;
   keep the pinned `opennotificaties.image.tag` (`1.16.1`); set
   `opennotificaties.configuration.oidcUrl: https://<env>-notificaties.dimpact.nl`
   and add the public hostname to `opennotificaties.settings.allowedHosts`.
   Leave `opennotificaties.tags.redis: false` and keep the
   `settings.cache.*` / `settings.celery.*` /
   `settings.messageBroker.celeryResultBackend` values pointing at
   `redis-ha-master.podiumd.svc.cluster.local` (db 3 / db 6).
3. **Keycloak client.** Provide
   `opennotificaties.configuration.secrets.keycloak_client_secret` and the
   `oidc_db_config_*` block in `opennotificaties.configuration.data`; the
   umbrella realm template creates the `opennotificaties` client in the
   `podiumd` realm. Enable PKCE with `configuration.pkceEnabled: true` plus
   `oidc_use_pkce: true` in the data if desired.
4. **Register with Open Zaak.** Set the shared secrets
   (`opennotificaties_autorisatie_api_secret`,
   `opennotificaties_opennotificaties_secret`,
   `openzaak_opennotificaties_secret`) in
   `opennotificaties.configuration.secrets` and configure `zgw_consumers`,
   `autorisaties_api`, `vng_api_common_credentials` and
   `notifications_kanalen_config` in `opennotificaties.configuration.data`;
   mirror the same client id/secret pairs in the `openzaak` block. The
   setup-configuration Job (`configuration.job.enabled: true`) applies all of
   this at deploy time.
5. **DNS + HTTPRoute.** Point `<env>-notificaties.dimpact.nl` at the public
   gateway and have the environment deployment (`ExternalsPodiumD`) create the
   HTTPRoute targeting Service `opennotificaties` port 80 on Gateway
   `public-gateway`/`ingress-basic`.
6. **Verify.** The setup-configuration Job completes; `https://<env>-notificaties.dimpact.nl/api/v1/`
   serves the Notificaties API and kanalen are listed (`/api/v1/kanaal`); admin
   login works via Keycloak; worker and beat logs are clean; a test change in
   Open Zaak (e.g. a new zaak) produces a delivered notification.

## Related documents

None — this folder has only the BASICS file; no deep-dive documents exist yet
for this component.
