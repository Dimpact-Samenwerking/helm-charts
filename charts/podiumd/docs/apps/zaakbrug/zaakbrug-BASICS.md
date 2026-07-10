# ZaakBrug — Basics

## Management summary

ZaakBrug is a translation bridge: it lets older municipal applications that
still speak the legacy ZDS standard (SOAP/StUF Zaak- en Documentservices, the
eSuite era) keep working while the case data itself lives in the modern ZGW
APIs (Open Zaak). Instead of rebuilding every old koppeling at once, a
municipality points those legacy applications at ZaakBrug, which converts
their requests to ZGW calls on the fly. It is an optional component of
PodiumD, disabled by default, and enabled per gemeente that still has ZDS
clients. To run it needs a small PostgreSQL database, a Keycloak client for
its admin console, and a JWT registration in Open Zaak. It is the heaviest
single pod in the stack by memory: a Java application with a fixed 4G heap,
using about 3.4Gi in practice.

## What it is

- Upstream: [Sudwest-Fryslan/ZaakBrug](https://github.com/Sudwest-Fryslan/ZaakBrug)
  (Gemeente Súdwest-Fryslân, maintained with WeAreFrank!), built on the
  [Frank!Framework](https://frank-framework.org/) integration engine.
- Sub-chart: `wearefrank/zaakbrug` `2.3.27` from
  `https://wearefrank.github.io/charts` (wraps the Frank!Framework `ff-common`
  library chart). Condition `zaakbrug.enabled`, tag `zaak`. **Disabled by
  default.**
- Image: `wearefrank/zaakbrug:1.26.14` (mirror to `acrprodmgmt.azurecr.io` for
  production).
- Role in PodiumD: translates inbound ZDS (SOAP/StUF) traffic from legacy
  applications into ZGW API calls against Open Zaak, so legacy koppelingen
  keep working during the migration to zaakgericht werken.
- Runtime components:
  - Deployment `podiumd-zaakbrug` — single Frank!Framework JVM container
    (Xms=Xmx=4G via `zaakbrug.frank.memory.{minimum,maximum}`), Service
    `podiumd-zaakbrug:80` → container port `8080`. Slow starter (~2 min).
  - Secret `zaakbrug-secrets` — rendered by the umbrella chart
    (`templates/zaakbrug-secrets.yaml`): `credentials.properties` with the
    Zaken-API JWT username/password, mounted via `frank.credentials.secret`.
  - ConfigMap `zaakbrug-oauth-role-mapping` — rendered by the umbrella chart
    (`templates/zaakbrug-oauth-role-mapping-configmap.yaml`): the files
    `oauth-role-mapping.properties` (Frank console role → Keycloak client
    role, from `zaakbrug.oauthRoleMapping`) and `RoutingProfiles.json`
    (zero-byte placeholder). Because the upstream chart has no
    `extraVolumes`/`extraVolumeMounts` support, this ConfigMap is mounted at
    `/opt/frank/resources/` by a post-deploy `kubectl patch` in the
    ExternalsPodiumD Applications pipeline — a temporary workaround.
  - `zaakbrug.staging.enabled: false` keeps the sub-chart's bundled
    bitnami/redis transitive dependency off (never use Bitnami).

## Required resources

### Database

- PostgreSQL: **yes** — database `zaakbrug`, owner role `zaakbrug`, TLS
  enforced (`ssl: true`). Provision at the minimum tier: it stores only
  Frank!Framework metadata and transient message-processing state, no
  high-volume tables. It is not an MI-export target.
- **Exception to the standard convention**: zaakbrug does *not* use the usual
  `<component>` Secret (`DB_PASSWORD`) + ConfigMap (`DB_HOST`/`DB_NAME`/
  `DB_USER`) contract. The JDBC connection is declared inline in the
  environment values under `zaakbrug.connections.jdbc[]` — JNDI name must be
  `jdbc/podiumd` (Narayana looks it up by that default) — with the password
  substituted at deploy time from the Key Vault secret `zaakbrug`
  (`REP_ZAAKBRUG_DATABASE_PASSWORD_REP`).
- `ssl` must be an unquoted YAML boolean; `ssl: "true"` fails the helm render
  (`wrong type for value; expected bool; got string`).

### Storage

None. No PVC — there is no `zaakbrug-storage.yaml` template; state lives in
the PostgreSQL database.

### Routing / exposure (NGINX Gateway Fabric)

Public console hostname `<env>-zaakbrug.dimpact.nl` (e.g.
`ontw-zaakbrug.dimpact.nl`). Two HTTPRoutes are observed on the
`public-gateway` Gateway in `ingress-basic` (`hr-zaakbrug` and
`hr-zaakbrug-nginx`), targeting the ClusterIP service `podiumd-zaakbrug`.
HTTPRoutes and the DNS CNAME (to the Application Gateway load balancer) are
created by the per-gemeente environment deployment (ADO ExternalsPodiumD),
not by this chart. Without the DNS record, Keycloak OAuth2 callbacks to the
console fail. Legacy ZDS clients call the same host/service for the SOAP
endpoints.

### Other dependencies

- **Keycloak** — client `zaakbrug` in the `podiumd` realm (confidential OIDC
  client for console SSO; seeded automatically into the realm import when
  `zaakbrug.enabled=true`). Client secret: Key Vault `zaakbrug-oauth-client-secret`,
  identical on the Keycloak side and in
  `frank.environmentVariables` (`application.security.console.authentication.*`).
  Console access is gated by Keycloak client roles mapped to Frank console
  roles via `zaakbrug.oauthRoleMapping` (defaults: `IbisAdmin=administrators`,
  `IbisTester=zaakbrug_admin`, `IbisDataAdmin=dataadmin`). No local console
  account exists.
- **Open Zaak (Zaken API)** — ZaakBrug authenticates outbound with the
  `zaakbrug` JWT client (`zaakbrug.frank.zakenApi.jwt.username`/`password`,
  password required when enabled, from Key Vault
  `zaakbrug-zaken-api-jwt-password`). Register the same client id + secret in
  Open Zaak's autorisaties seed (`vng_api_common_credentials` +
  `vng_api_common_applicaties`).
- No Redis, ClamAV, Elasticsearch, RabbitMQ or SMTP dependencies.

## CPU and memory

Chart defaults (`zaakbrug.resources` in `values.yaml`; there is no zaakbrug
section in `docs/misc/resource-overview.md`):

| Container | CPU request | CPU limit | Memory request | Memory limit |
|---|---|---|---|---|
| zaakbrug (Frank!Framework JVM) | 250m | 2 | 5Gi | 6Gi |

The limits are sized for the fixed JVM heap (Xms=Xmx=4G) plus roughly 1Gi
headroom for non-heap memory (metaspace, code cache, direct buffers, threads).

Observed usage (2026-07-10): on ontw, `podiumd-zaakbrug` uses 10m CPU /
3388Mi memory at idle — the largest single pod in the namespace, and the
memory is effectively constant because the heap is pre-allocated. Not
deployed on accp at capture time. Sizing recommendation: keep the chart
defaults; do not lower the memory request below the heap+overhead or the pod
risks eviction/OOM. Tuning the footprint means changing
`zaakbrug.frank.memory.{minimum,maximum}` and the K8s resources together.

## Integrating ZaakBrug as a new app

Condensed from `zaakbrug-deploy.md` (read that for full detail and
troubleshooting):

1. **Database** — create the `zaakbrug` PostgreSQL database and `zaakbrug`
   owner role on the shared server, minimum tier, TLS enforced.
2. **Key Vault secrets** — add `zaakbrug` (DB password),
   `zaakbrug-oauth-client-secret` (Keycloak client secret) and
   `zaakbrug-zaken-api-jwt-password` (outbound Zaken-API JWT); bind them in
   the pipeline as `ZAAKBRUG_DATABASE_PASSWORD`,
   `ZAAKBRUG_OAUTH_CLIENT_SECRET`, `ZAAKBRUG_ZAKEN_API_JWT_PASSWORD`.
3. **Environment values** — set `zaakbrug.enabled: true`,
   `zaakbrug.staging.enabled: false`, pin `zaakbrug.image.tag` (`1.26.14`),
   supply `zaakbrug.frank.zakenApi.jwt.password`
   (`REP_ZAAKBRUG_ZAKEN_API_JWT_PASSWORD_REP`), the
   `frank.environmentVariables`
   `application.security.console.authentication.*` block (required — without
   it the console serves openly with no Keycloak redirect), and the
   `connections.jdbc[]` entry named `jdbc/podiumd` with `ssl: true`
   (unquoted boolean).
4. **Keycloak client** — add the `zaakbrug` client under
   `keycloak.config.clients` with `secret:
   "REP_ZAAKBRUG_OAUTH_CLIENT_SECRET_REP"` and `oidcUrl` set to the console
   host; the realm import seeds the client, its roles and the roles-claim
   protocol mapper automatically.
5. **Open Zaak registration** — add the `zaakbrug` client to
   `openzaak.configuration.data` (`vng_api_common_credentials` with the JWT
   password, plus a `vng_api_common_applicaties` entry with
   `client_ids: [zaakbrug]`); re-run the Open Zaak configuration job.
6. **Pipeline** — register the wearefrank helm repo
   (`helm repo add wearefrank https://wearefrank.github.io/charts`) before
   dependency build, and add the post-deploy `kubectl patch` that mounts
   ConfigMap `zaakbrug-oauth-role-mapping` at `/opt/frank/resources/`
   (temporary workaround; deploy **without** `--wait`/`--atomic` while it is
   needed, then gate on `kubectl rollout status`).
7. **DNS + HTTPRoute** — CNAME `<env>-zaakbrug.<gemeente-domain>` to the
   Application Gateway LB; the environment deployment creates the HTTPRoutes
   to service `podiumd-zaakbrug`; cert-manager issues TLS once DNS resolves.
8. **Verify** — pod `podiumd-zaakbrug` `1/1 Running` (~2 min JVM start);
   `http://localhost:8080/iaf/gui` inside the pod returns `302` to
   `/iaf/gui/oauth2/authorization/custom` and on to Keycloak; grant users a
   `zaakbrug` client role in Keycloak; repoint legacy ZDS clients' endpoints
   at ZaakBrug.

## Related documents

- [`zaakbrug-deploy.md`](zaakbrug-deploy.md) — full end-to-end deploy guide:
  database, Key Vault secrets, values blocks, Open Zaak registration,
  pipeline changes (including the ConfigMap mount patch), console SSO/role
  model, and troubleshooting.
