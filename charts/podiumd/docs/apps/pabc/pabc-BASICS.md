# PABC — Basics

## Management summary

PABC (Platform Autorisatie Beheer Component) is the central authorisation
component of PodiumD. It records which groups of municipal staff are allowed
to do what — for example, which team may handle which types of cases — and
the ZAC case-handling application asks PABC for these permissions on every
authorisation decision. A functional administrator maintains the mappings
(functional role → application role, per domain/zaaktype) in a small web UI.
Since PodiumD 4.8.0 (ZAC 5.0.1) it is a required part of the stack, enabled
by default. It needs a PostgreSQL database, two Keycloak clients and a public
hostname for the management UI. Footprint is tiny: a single small pod.

## What it is

- Upstream project: Platform Autorisatie Beheer Component
  ([github.com/Platform-Autorisatie-Beheer-Component](https://github.com/Platform-Autorisatie-Beheer-Component)),
  developed under Dimpact/ICTU governance alongside ZAC. The subchart is
  pulled from `oci://ghcr.io/platform-autorisatie-beheer-component`
  (chart `pabc`, version `1.1.1`; container image tags are `1.1.0`, one minor
  version behind the chart).
- Images — pinned to the ACR mirror because the pabc 1.1.1 subchart templates
  image references literally (no `global.imageRegistry` support) and AKS
  Gatekeeper only allows `acrprodmgmt.azurecr.io/*`
  (see `docs/images/images-4.8.0.yaml`):
  - `acrprodmgmt.azurecr.io/platform-autorisatie-beheer-component/pabc-api:1.1.0`
  - `acrprodmgmt.azurecr.io/platform-autorisatie-beheer-component/pabc-migrations:1.1.0`
  - `acrprodmgmt.azurecr.io/groundnuty/k8s-wait-for:v2.0` (init containers)
- Role in PodiumD: single source of authorisation data for ZAC. ZAC queries
  the PABC API (`X-API-KEY` header) to resolve which Keycloak groups hold
  which ZAC application roles per zaaktype/domain. As of ZAC 5.0.1 the old
  `zac.featureFlags.pabcIntegration` flag no longer exists — the integration
  is always on, hence `pabc.enabled: true` is the chart default in 4.8.0.
- Runtime components (`fullnameOverride: "pabc"`):
  - `pabc` deployment — 1 replica (.NET API + management UI, port 8080),
    with a `pabc-wait-for-migrations` init container (k8s-wait-for) that
    blocks start-up until the migrations Job of the same release completes
  - `pabc-migrations-<revision>` Job — runs the schema migrations on every
    install/upgrade (own `wait-for-postgresql` init container)
  - Service `pabc` (ClusterIP), plus a Role/RoleBinding that lets the pod's
    ServiceAccount read Job status for the wait-for gate
  - Subchart extras left off: its own ingress (`enabled: false`), HPA, and
    the bundled Bitnami PostgreSQL (`pabc.postgresql.enabled: false` — an
    external PostgreSQL server is always used)

## Required resources

### Database

- PostgreSQL: **yes** (Azure Database for PostgreSQL Flexible Server in
  Dimpact environments). Database `pabc`, user `pabc`.
- Unlike most PodiumD components, the app does **not** use the shared
  Secret/ConfigMap contract — credentials are chart values under
  `pabc.settings.database.*` (`host`, `name`, `username`, `password`; the
  subchart renders them into its own Secret/ConfigMap). The password is
  injected at deploy time from Key Vault (convention `pabc-db-admin-<env>`,
  via a `--set pabc.settings.database.password=...` in the deploy script).
- The schema is created automatically by the `pabc-migrations` Job.
- `pabc` **is** in the default `mi.targets` list, so when MI exports are
  enabled (`mi.enabled: true`) the export CronJob does expect the standard
  contract: Secret `pabc` (`DB_PASSWORD`) + ConfigMap `pabc`
  (`DB_HOST`, `DB_NAME`, `DB_USER`), created by the per-gemeente environment
  deployment.

### Storage

- None. No PVC and no `pabc-storage.yaml` template — the app is stateless;
  all state lives in PostgreSQL.

### Routing / exposure (NGINX Gateway Fabric)

- Public hostname pattern: `<env>-pabc.dimpact.nl`
  (e.g. `ontw-pabc.dimpact.nl`) — the management UI for functional
  administrators.
- HTTPRoute `hr-pabc` on Gateway `public-gateway` (namespace `ingress-basic`,
  gatewayClass `nginx`), created by the per-gemeente environment deployment
  (ADO `ExternalsPodiumD`) — not by this chart. The route backend is the
  `pabc` ClusterIP service directly (no nginx sidecar).
- The subchart's own Kubernetes Ingress stays disabled on NGF clusters
  (`enabling-pabc.md` shows a traefik Ingress example for non-NGF
  environments).

### Other dependencies

- **Keycloak** (`podiumd` realm) — two clients, both provisioned
  automatically by the realm config job (keycloak-config-cli) when
  `global.configuration.enabled: true`:
  - `pabc` (`pabc.settings.oidc.clientId`) — OIDC confidential client for
    user login to the management UI. Redirect URIs derive from
    `pabc.settings.oidc.oidcUrl` (must exactly match the public URL). The
    client role `administrator` (`pabc.settings.oidc.functioneelBeheerderRole`)
    grants UI access and is auto-assigned to the `administrators` group;
    claim mapping via `roleClaimType: roles`, `nameClaimType`,
    `emailClaimType`. `pkceEnabled: false` by default.
  - `pabc-keycloak-admin` (`pabc.settings.keycloakAdmin.clientId`) — service
    account with realm-management roles `view-users`, `view-realm`,
    `view-groups`; PABC uses it to read users/groups via the Keycloak Admin
    REST API.
  - Both client secrets must be set in values **before** the first deploy or
    the clients are created with blank secrets.
- **ZAC**: calls the PABC API with an `X-API-KEY` header. The key in
  `pabc.settings.apiKeys` (a list) must match `zac.pabcApi.apiKey`, and
  `zac.pabcApi.url` points at the internal service: `http://pabc/api`.
- **Post-deploy seeding**: the PABC database must be seeded once (application
  rename `zac` → `zaakafhandelcomponent`, ZAC application roles, functional
  roles per Keycloak group, domain + mappings) via the idempotent
  `post-deployment-pabc-init` Job from `podiumd-infra` — see
  `enabling-pabc.md`. Without it, all ZAC authorisation calls return empty
  results.
- No Redis, ClamAV, Elasticsearch, RabbitMQ, SMTP, or Open Zaak /
  Open Notificaties registration.

## CPU and memory

Chart defaults (`charts/podiumd/values.yaml` + `docs/misc/resource-overview.md`):

| Container | Replicas | CPU request | Mem request | CPU limit | Mem limit |
|-----------|----------|-------------|-------------|-----------|-----------|
| pabc | 1 | 10m | 384Mi | 200m | 768Mi |
| pabc-migrations (Job) | per release | not set (burstable) | not set (burstable) | not set (burstable) | not set (burstable) |

**Observed usage** (kubectl top, 2026-07-10): on `aks-blue-ontw-dimp` the
single pabc pod used 2m CPU / 199Mi — about half the memory request and far
below the limits. PABC was not deployed on `aks-blue-accp-dimp` at capture
time. The chart defaults are comfortably sized for production; no
"increase for production" note applies in `resource-overview.md`. Note it is
a single replica, so expect a brief API blip during node drains — ZAC calls
will fail until the pod reschedules. (`resource-overview.md` still says
"Disabled by default" for PABC; that predates the 4.8.0 default of
`enabled: true`.)

## Integrating PABC as a new app

1. **Provision the database**: create database `pabc` and user `pabc` on the
   environment's PostgreSQL Flexible Server; store the password in Key Vault
   (`pabc-db-admin-<env>`) and have the deploy script inject it as
   `pabc.settings.database.password`. Set `pabc.settings.database.host` (and
   `name`/`username` if they deviate from the defaults). If MI exports are
   enabled, also create Secret/ConfigMap `pabc` per the standard contract.
2. **Generate secrets** (e.g. `openssl rand -base64 32`): OIDC client secret,
   Keycloak-admin client secret, and the ZAC API key.
3. **Set chart values** in the per-gemeente values file (`pabc.enabled: true`
   is the 4.8.0 default):
   - `pabc.settings.oidc.authority: https://<keycloak-host>/realms/podiumd`
   - `pabc.settings.oidc.oidcUrl: https://<env>-pabc.dimpact.nl` — must
     exactly match the public URL (no trailing slash)
   - `pabc.settings.oidc.clientSecret` and
     `pabc.settings.keycloakAdmin.clientSecret`
   - `pabc.settings.apiKeys: ["<key>"]`
   - `pabc.nodeSelector: {kubernetes.azure.com/mode: user}` on aks-blue
     clusters; image repositories are already pinned to the
     `acrprodmgmt.azurecr.io` mirror — mirror the three images first if the
     ACR does not have them yet.
4. **Keycloak clients**: automatic — the realm config job creates `pabc` and
   `pabc-keycloak-admin` when `global.configuration.enabled: true`. To
   re-provision after changing `oidcUrl` or rotating secrets, set
   `global.configuration.overwrite: true` for one deploy.
5. **Wire up ZAC**: set `zac.pabcApi.url: http://pabc/api` and
   `zac.pabcApi.apiKey` to the same value as `pabc.settings.apiKeys[0]`.
6. **DNS + HTTPRoute**: add the `<env>-pabc.dimpact.nl` DNS record and have
   the environment deployment create HTTPRoute `hr-pabc` on `public-gateway`
   pointing at service `pabc`.
7. **Deploy and verify**: `pabc-migrations-<revision>` Job is `Complete`, the
   `pabc` pod is `1/1 Running`, and both Keycloak clients exist in the
   `podiumd` realm.
8. **Seed role mappings**: run the `post-deployment-pabc-init` Job, then
   verify `http://pabc/api/v1/groups?application-name=zaakafhandelcomponent&...`
   returns groups and that behandelaar assignment works in ZAC (see
   `enabling-pabc.md` for the exact commands and mapping table).

## Related documents

- [enabling-pabc.md](enabling-pabc.md) — full step-by-step enablement guide:
  secrets, values, Keycloak realm config details, deploy-script changes, the
  seeding job, and a troubleshooting table. Written against pre-4.8.0
  environments, so its `enabled: false` default, traefik Ingress example and
  `zac.featureFlags.pabcIntegration` flag (removed in ZAC 5.0.1) no longer
  apply on 4.8.0 NGF clusters — everything else still holds.
