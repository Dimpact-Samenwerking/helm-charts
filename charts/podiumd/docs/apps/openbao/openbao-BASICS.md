# OpenBao — Basics

## Management summary

OpenBao is the secrets vault of PodiumD: a safe place inside the cluster where
municipal staff and applications store and retrieve sensitive material (API
keys, certificates, upload credentials) instead of passing it around by mail or
keeping it in configuration files. Users log in with their normal PodiumD
account (Keycloak); who may upload secrets is controlled by group membership.
It is the community-governed open-source fork of HashiCorp Vault. New in
PodiumD **4.8.2** and optional: the chart ships it disabled. To run it needs a
small PostgreSQL database on the shared server and a public hostname; it needs
no disk of its own. Footprint: three small pods plus two one-shot setup jobs.
One-time per fresh cluster, an operator must initialise and unseal the vault by
hand (a deliberate safety step).

## What it is

Upstream: [OpenBao](https://openbao.org/) — MPL-2.0 fork of HashiCorp Vault.
Image `openbao/openbao`, chart-pinned **2.5.5** (subchart `appVersion`;
override via `openbao.server.image`). Deployed via the upstream
`openbao` Helm subchart wired into `Chart.yaml`, plus this chart's own glue
templates. Optional; enabled with `openbao.enabled: true` (default `false`).
Delivered on PR [#384](https://github.com/Dimpact-Samenwerking/helm-charts/pull/384).

Runtime components when enabled:

- **openbao server** (StatefulSet, **3 replicas**, HA) — the vault itself,
  `:8200`, PostgreSQL storage backend (`ha_enabled = "true"`), Shamir seal,
  TLS disabled at the pod (`tls_disable=1`; the platform gateway terminates
  TLS). Active-node service: `<release>-openbao-active`.
- **openbao-db-schema Job** (`templates/openbao-db-schema-job.yaml`,
  `library/postgres:16-alpine`) — creates the vault tables in the `openbao`
  database on first install.
- **openbao-config Job** (`templates/openbao-config-job.yaml`,
  `openbao/openbao:2.5.5`) — post-install/upgrade hook configuring OIDC auth,
  policies and group aliases inside the vault. Authenticates with a scoped
  periodic token from `Secret/openbao-bootstrap-token`; **self-skips cleanly
  (exit 0) while that Secret does not exist yet**, so the hook never blocks a
  release before the one-time bootstrap.
- **openbao-db secret** (`templates/openbao-db-secret.yaml`) — chart-rendered
  DB credential wiring.
- **Agent injector** — kept **off** (see deep dive §2.1).

## Required resources

### Database

Yes. Database `openbao` + role `openbao-admin` on the shared Azure PostgreSQL
Flexible Server, created by the environment deployment; password fed from Key
Vault (`REP_OPENBAO_DB_PASSWORD_REP`). Tables are auto-created by the
`openbao-db-schema` Job. PostgreSQL is also the vault's **storage backend** —
all secret material (encrypted) lives in this database, so it inherits the
server's backup regime.

### Storage

None — no PVC (`dataStorage.enabled: false`); the PostgreSQL backend replaces
local raft/file storage.

### Routing / exposure (NGINX Gateway Fabric)

Public. The hostname is chosen per environment — the chart imposes no naming
scheme; the host comes solely from `openbao.configuration.oidcUrl`. PodiumD
convention: `<env>-openbao.<gemeente>.nl` (e.g.
`ontw-openbao.dim2.dimpact.nl`). The Gateway/Ingress route (created
deploy-side in ADO `ExternalsPodiumD` `infra.yml`, not by this chart) points at
service `<release>-openbao-active:8200` over **HTTP** — TLS terminates at the
gateway, and the gateway certificate **SAN must cover the OpenBao hostname**.
The `localhost:8250` redirect URI additionally enables `bao login -method=oidc`
from an operator workstation.

### Other dependencies

- **Keycloak** — rendered into the `podiumd` realm import: OIDC client
  `openbao` (secret `$(KC_SECRET_OPENBAO)`, auto-generated and kept stable),
  client role `openbao:uploaders` (`openbao.configuration.uploadersRole`) and
  group `vault-uploaders` (`openbao.configuration.uploadersGroup`) whose
  membership grants upload access via the token's `groups` claim.
  **Caveat:** realm `roles`/`groups` import is gated by
  `keycloak.config.skipRoles`/`skipGroups` (default `true`) — see deep dive
  §3.7 before first enable.
- **Azure Key Vault** — operational store for the Shamir unseal key shares
  and the (to-be-revoked) root token (`openbao-root-token-<env>`), and source
  of the DB password. Azure KV **auto-unseal is deliberately not used**
  (workload-identity incompatibility, deep dive §3.6) — seal is Shamir.
- **Bootstrap token** — `Secret/openbao-bootstrap-token` (key `token`), seeded
  once per cluster by `scripts/openbao-mint-config-token.sh` (repo root); a
  scoped orphan periodic token, **not** the root token.
- **Frank!Gateway** (optional consumer) — can fetch external API keys from
  OpenBao at request time
  ([`../frankgateway/frankgateway-BASICS.md`](../frankgateway/frankgateway-BASICS.md)).

## CPU and memory

Chart defaults:

| Container | CPU request | Mem request | CPU limit | Mem limit |
|-----------|-------------|-------------|-----------|-----------|
| openbao server (×3) | 100m | 256Mi | 500m | 512Mi |
| openbao-config Job | 50m | 64Mi | 250m | 128Mi |
| openbao-db-schema Job | 50m | 64Mi | 250m | 128Mi |

No observed-usage numbers yet — first production-like deployment pending.

## Integrating OpenBao as a new app

Condensed — the authoritative step-by-step is the
[bootstrap runbook](podiumd-component-openbao.md#5-bootstrap-runbook-first-install)
in the deep dive.

1. **Provision the database.** Create db `openbao` + role `openbao-admin` on
   the shared PostgreSQL server; put the password in the environment Key Vault
   (`REP_OPENBAO_DB_PASSWORD_REP`).
2. **Route + certificate.** Deploy-side Gateway/Ingress route for the chosen
   hostname (convention `<env>-openbao.<gemeente>.nl`) →
   `<release>-openbao-active:8200` (HTTP); extend the gateway certificate SAN
   with the hostname.
3. **Set values.** `openbao.enabled: true`, the OIDC/public URL values, and —
   for the first enable on a realm running defaults — the
   `skipRoles`/`skipGroups` handling from deep dive §3.7.
4. **Deploy.** The db-schema Job creates tables; the config Job self-skips
   (no bootstrap token yet). Pods report Ready even though the vault is
   sealed (readiness maps sealed/uninitialised to HTTP 200).
5. **Init + unseal (one-time).** `bao operator init`, unseal with the Shamir
   shares, store shares + root token in Key Vault
   (`openbao-root-token-<env>`).
6. **Mint the config token.** Run `scripts/openbao-mint-config-token.sh` →
   seeds `Secret/openbao-bootstrap-token`; re-run the config Job (or
   `helm upgrade`) so OIDC auth, policies and group aliases are configured;
   then revoke the root token (deep dive §7).
7. **Verify.** Web UI login via Keycloak; a `vault-uploaders` member can
   write a secret; `bao login -method=oidc` works from a workstation; config
   Job completed (not skipped) on the latest run.

## Related documents

- [podiumd-component-openbao.md](podiumd-component-openbao.md) — the full
  component deep dive: architecture, chart wiring, all requirements (images,
  DB, route, TLS, Azure workload identity, seal model, Keycloak), values
  reference, bootstrap runbook, verification, security notes, and open items.
  **Read it before the first deployment.**
