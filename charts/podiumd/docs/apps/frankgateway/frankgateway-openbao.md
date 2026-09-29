# Frank!Gateway — OpenBao (secrets vault)

> **This is the single OpenBao document.** OpenBao ships in PodiumD as the
> secrets store behind Frank!Gateway, so it is documented here, next to the
> gateway that depends on it. The files under [`../openbao/`](../openbao/)
> are placeholders pointing to this page.
>
> Section numbers are stable: the chart itself refers to them
> (`scripts/openbao-mint-config-token.sh`, `templates/openbao-config-job.yaml`,
> `values.yaml` → `openbao.configuration.bootstrapTokenSecret`). Keep §5 (bootstrap
> runbook) and §7 (security notes) where they are.

## Management summary

OpenBao is the secrets vault of PodiumD: a safe place inside the cluster where
municipal staff and applications store and retrieve sensitive material (API
keys, certificates, upload credentials) instead of passing it around by mail or
keeping it in configuration files. Its first and main consumer is
**Frank!Gateway**, which reads the keys for the external services it calls
(BAG, KVK, …) from OpenBao at the moment it makes the call, so those keys never
sit in configuration files. Users log in with their normal PodiumD account
(Keycloak); who may upload secrets is controlled by group membership.

It is the community-governed open-source fork of HashiCorp Vault. New in
PodiumD **4.8.2** and optional in itself, but **required as soon as
Frank!Gateway is enabled**. To run, it needs a small PostgreSQL database on the
shared server and a public hostname; it needs no disk of its own. Footprint:
three small pods plus two one-shot setup jobs.

Once per fresh cluster, an operator must initialise the vault by hand. After
that, and after **every restart or upgrade**, it must also be unsealed by hand
(a deliberate safety step). The unseal key and the root token that come out of
initialisation are kept in the environment's Azure Key Vault, as
`openbao-unseal-key` and `openbao-root-token`.

---

## DevOps TL;DR

> First deploy: read the full doc below. Subsequent deploys: this section is all
> you need.

Infra to provision per environment (one line each):

| Piece | What DevOps must provide |
|---|---|
| **Database** | Azure PostgreSQL db `openbao` + role `openbao-admin`; password in Key Vault (`REP_OPENBAO_DB_PASSWORD_REP`). Tables auto-created by the schema Job. |
| **Key Vault items** | `openbao-unseal-key` and `openbao-root-token` in the environment Key Vault. ADO `ExternalsPodiumD` creates both (Terraform `keyvault` block, `passwords` list) with a **placeholder**; the real values are written after `bao operator init` (§5 step 4). |
| **Ingress / route** | Gateway/Ingress (`infra.yml`) → service `<release>-openbao-active:8200` over **HTTP** (TLS terminated at gateway), host per environment from `openbao.configuration.oidcUrl` (convention `<env>-openbao-admin.<gemeente>.nl`). |
| **TLS cert** | Gateway cert **SAN must cover the OpenBao host** (`<env>-openbao-admin.<gemeente>.nl`); pods run no TLS (`tls_disable=1`), so no server cert needed. |
| **Storage** | **None** — no PVC (PostgreSQL storage backend, `dataStorage.enabled=false`). |
| **Secrets (cluster)** | `openbao-db` (chart-rendered) · `openbao-bootstrap-token` key `token` (**seeded by `scripts/openbao-mint-config-token.sh`** — a scoped periodic token, NOT the root token) · `openbao-oidc-secret` (auto-generated, kept stable). |
| **Identity** | User-assigned MI + federated credential for SA `openbao`; set client-id in `server.serviceAccount.annotations`. (The Azure KV *crypto key* for auto-unseal is provisioned but unused — Shamir, §3.6.) |
| **Images / egress** | Allow `quay.io/openbao/openbao:2.5.5` + `docker.io/library/postgres:16-alpine` (or mirror to ACR + override). |
| **One-time bootstrap** | `bao operator init -key-shares=1 -key-threshold=1`; store the key and root token in Key Vault; unseal all 3 pods; mint + seed the scoped config token (`scripts/openbao-mint-config-token.sh`), then revoke the root token; re-run deploy; check `kubectl logs job/openbao-config`. |
| **Every restart / upgrade** | Unseal all 3 pods with `openbao-unseal-key` from Key Vault (§5.1). |

Values to set: `openbao.enabled=true`, `openbao.database.host`,
`openbao.configuration.oidcUrl`, `openbao.configuration.keycloak.url`,
`server.serviceAccount.annotations` client-id. Full runbook in §5.

---

## 1. Architecture at a glance

```text
                 ┌──────────────── Keycloak (podiumd realm) ────────────────┐
                 │  OIDC client "openbao"  ·  group "vault-uploaders"        │
                 │  clientRole openbao:uploaders                             │
                 └───────────────▲───────────────────────▲──────────────────┘
   browser / bao CLI             │ OIDC login            │ discovery + client-secret
        │                        │                       │
        ▼   HTTPS (TLS at GW)    │                       │
┌────────────────┐   route   ┌──┴───────────────────────┴──┐        ┌──────────────────┐
│ Gateway/Ingress│──────────▶│  Service <release>-openbao   │        │  Azure Key Vault │
│  (infra.yml)   │  :8200    │  -active  (HA, 3 replicas)   │        │  openbao-unseal- │
│  cert w/ SAN   │  http     │  listener tls_disable=1      │        │  key, openbao-   │
└────────────────┘           │  storage = PostgreSQL        │        │  root-token      │
                             └──────▲───────┬───────────────┘        └──────────────────┘
         frankgateway-<class>       │       │ BAO_PG_CONNECTION_URL
         (scoped reader token,      │       ▼
          request-time key fetch) ──┘  ┌───────────────────────────────┐
                                       │ Azure PostgreSQL  db "openbao" │
                                       │ tables openbao_kv_store /      │
                                       │        openbao_ha_locks        │
                                       └───────────────────────────────┘
```

Two moving parts ship in this chart:

1. **The upstream `openbao` sub-chart** (server StatefulSet) — configured through
   `openbao.server.*` (upstream keys).
2. **PodiumD glue templates** — a DB Secret, a DB-schema Job, and a post-deploy
   config Job — configured through `openbao.configuration.*` and
   `openbao.database.*`, plus the Keycloak realm additions.

| Rendered resource | Kind | Source template | When |
|---|---|---|---|
| `openbao-db` | Secret | `openbao-db-secret.yaml` | `openbao.enabled` |
| `openbao-db-schema` | Job (`pre-install,pre-upgrade`, weight `-5`) | `openbao-db-schema-job.yaml` | `openbao.enabled` |
| `<release>-openbao` (StatefulSet + Services + SA + ConfigMap + PDB) | sub-chart | `charts/podiumd/charts/openbao-0.28.4.tgz` | `openbao.enabled` |
| `openbao-config` | Job (`post-install,post-upgrade`, weight `10`) | `openbao-config-job.yaml` | `openbao.enabled && openbao.configuration.enabled` |
| Keycloak `openbao` client, group, roles | realm import | `keycloak-podiumd-realm-config.yaml` | rendered into the podiumd realm |
| `openbao-oidc-secret` | Secret key | `keycloak-podiumd-realm-secrets.yaml` | auto-generated, kept stable |

### 1.1 How Frank!Gateway uses it

`frankgateway.enabled: true` with `openbao.enabled: false` **fails the render**:
OpenBao is the only source of Frank!Gateway's external-API credentials.

- Everything the gateway reads lives under `<mount>/frankgateway/`: the API
  keys at `frankgateway` (fields `bag_api_key`, `kvk_api_key`), outbound client
  certificates at `frankgateway/client-certs/<name>` (fields `cert`, `key`) and
  the inbound consumer list at `frankgateway/consumers`. Commands to write them:
  [`frankgateway-routes.md`](frankgateway-routes.md).
- The gateway authenticates with a **scoped reader token** from the Secret
  named by `frankgateway.openbao.tokenSecret`. It is supplied out-of-band
  (Key-Vault-fed) and never minted by the chart. Its policy must cover the
  whole subtree (`<mount>/data/frankgateway/*` on kv-v2).
- A route whose secret cannot be read answers **503**
  (`frankgateway.openbao.failMode: closed`). A **sealed** OpenBao therefore
  turns every key-bearing route into a 503 — unsealing after a restart (§5.1)
  is on the gateway's critical path, not only the vault's.
- With `frankgateway.tls.certManager.issuer.create: true`, OpenBao is also the
  CA for the gateway's internal-hop certificate (PKI engine) — see
  [`frankgateway-BASICS.md` → OpenBao as the issuing CA](frankgateway-BASICS.md#openbao-as-the-issuing-ca).

---

## 2. Chart wiring (dependency)

`charts/podiumd/Chart.yaml`:

```yaml
dependencies:
  - name: openbao
    version: 0.28.4                     # OpenBao server v2.5.5
    repository: "https://openbao.github.io/openbao-helm"
    condition: openbao.enabled
```

- Repository URL is spelled out in `Chart.yaml` (no `@openbao` alias) so CI and
  fresh clones can resolve the dependency without a prior `helm repo add`;
  `scripts/add-helm-repos.sh` still registers the repo for interactive use.
- Pinned to exact chart version `0.28.4` in `Chart.yaml` (`Chart.lock` is
  git-ignored, so the `Chart.yaml` pin is the authoritative one).
- The vendored `charts/podiumd/charts/openbao-0.28.4.tgz` is **git-ignored**, so
  any build/CI environment MUST run `helm dep build charts/podiumd` (after
  `scripts/add-helm-repos.sh`) to materialise it before `helm template`/`upgrade`.

### 2.1 Agent injector — keep it OFF

The upstream sub-chart enables the **Vault Agent Sidecar Injector** by default
(`injector.enabled` follows `global.enabled` = on). PodiumD does **not** use
sidecar injection — uploaders authenticate via OIDC — so `values.yaml` sets:

```yaml
openbao:
  injector:
    enabled: false
```

Leaving it on ships an unused `hashicorp/vault-k8s` Deployment **and a
cluster-scoped `MutatingWebhookConfiguration`** that intercepts pod creation
cluster-wide; if the injector is unhealthy it can block scheduling across the
whole cluster. Keep it disabled unless a concrete sidecar-injection use case
appears.

---

## 3. Requirements

### 3.1 Container images

| Image | Where used | Tag | Notes |
|---|---|---|---|
| `quay.io/openbao/openbao` | server StatefulSet (sub-chart) | `""` → sub-chart appVersion **2.5.5** | HA server |
| `quay.io/openbao/openbao` | `openbao-config` Job (`bao` CLI) | **`2.5.5`** (pinned) | standalone Job can't resolve the sub-chart appVersion; keep in step with it |
| `docker.io/library/postgres` | `openbao-db-schema` Job (`psql`) | `16-alpine` | schema DDL only |

> The OpenBao and postgres images above are recorded (digest-pinned) in
> `docs/images/images-baseline.yaml`, the single authoritative strip-registry
> mirror manifest. For an ACR-mirrored production environment, override
> `server.image` / the Job images to the mirror (see §9).

### 3.2 PostgreSQL database (shared Azure PostgreSQL)

OpenBao uses the PostgreSQL storage backend — there is **no data PVC**
(`server.dataStorage.enabled: false`). It does **not** create its own tables.
All secret material (encrypted) lives in this database, so it inherits the
server's backup regime.

Prerequisites to provision per environment:

- A database (default name `openbao`) on the shared Azure PostgreSQL flexible
  server.
- A database role (default `openbao-admin`) owning that database.
- The password, injected by the deploy pipeline — `openbao-db-secret.yaml`
  renders `Secret/openbao-db` with `username`, `password` and a libpq
  `connection-url`; the pipeline substitutes `REP_OPENBAO_DB_PASSWORD_REP` from
  Azure Key Vault. **Never commit a real password.**
- `sslmode: require` (default).

The `openbao-db-schema` Job (a `pre-install`/`pre-upgrade` hook, weight `-5`, so
it runs before the StatefulSet) creates, idempotently (`IF NOT EXISTS`):

- `openbao_kv_store` (data)
- `openbao_ha_locks` (HA leader election)

The server receives the full libpq URL via `BAO_PG_CONNECTION_URL`
(`server.extraSecretEnvironmentVars`, sourced from `openbao-db`) so credentials
never land in the server config ConfigMap.

### 3.3 Network route into the app (Gateway/Ingress)

The sub-chart Ingress is **disabled** (`server.ingress.enabled: false`). OpenBao
is exposed by the **platform Gateway/Ingress defined out-of-band in the
environment's `infra.yml`** (ADO `ExternalsPodiumD`), not by this chart. The
route MUST satisfy:

- **Backend service:** `<release>-openbao-active` on **port 8200**
  (the HA sub-chart publishes `-active` = current leader, `-standby`,
  `-internal`, `-ui`). Target `-active` so writes and the OIDC login UI always
  hit the unsealed leader. (`<release>` is the Helm release name, e.g.
  `podiumd-openbao-active`.)
- **Protocol to backend:** plain **HTTP**. The server listener runs
  `tls_disable = 1` on `[::]:8200`; **TLS is terminated at the gateway** and
  re-originated as cleartext inside the cluster.
- **External host:** must equal the host in `openbao.configuration.oidcUrl` —
  the chart imposes no hostname scheme; each environment picks its own host
  (PodiumD convention `<env>-openbao-admin.<gemeente>.nl`, e.g.
  `ontw-openbao-admin.dim2.dimpact.nl` — the name gemeenten were asked to
  create in DNS). This host drives the Keycloak client `redirectUris` and the
  OIDC role `allowed_redirect_uris`; a mismatch breaks OIDC login
  (`redirect_uri` rejected).
- **UI:** the server sets `ui = true`; the OIDC callback path used is
  `<oidcUrl>/ui/vault/auth/oidc/oidc/callback`. The `localhost:8250` redirect
  URI additionally enables `bao login -method=oidc` from an operator
  workstation.

> The intra-cluster HA port `[::]:8201` (`cluster_address`) is used for
> leader-forwarding between replicas and is **not** routed externally.

### 3.4 TLS certificate — SAN requirements

Because TLS is terminated at the gateway, the **gateway/ingress certificate**
(managed in `infra.yml`, typically via cert-manager or a platform wildcard
cert) is what matters:

- The certificate presented for the OpenBao route **must include the external
  OpenBao host as a Subject Alternative Name (SAN)** — e.g.
  `<env>-openbao-admin.<gemeente>.nl`. A wildcard SAN (`*.<gemeente>.nl`) that
  already covers the chosen host is acceptable.
- The host, its SAN, and `openbao.configuration.oidcUrl` must all agree.
- The **in-cluster** listener uses no TLS (`tls_disable = 1`), so **no
  server-side certificate or SAN is required on the pods** and none is
  provisioned by this chart. If a future requirement mandates end-to-end TLS
  (cluster-internal), a server cert whose SAN covers `<release>-openbao*` service
  DNS names and the `8200`/`8201` listeners would need to be added — out of
  scope for 4.8.2.

### 3.5 Azure Key Vault + Workload Identity

The environment Key Vault plays two separate roles for OpenBao. Do not confuse
them:

| What | Kind | Used? |
|---|---|---|
| `openbao-unseal-key`, `openbao-root-token` | Key Vault **secrets** — operator storage for the output of `bao operator init` | **Yes** — read by an operator to unseal (§5.1) and for break-glass |
| Auto-unseal key + MI + federated credential | Key Vault **crypto key** + identity for the `azurekeyvault` seal | **No** — provisioned, kept for a later switch to auto-unseal (§3.6) |

**The two secrets.** Environments deployed from ADO `ExternalsPodiumD` get both
from Terraform: they are in the `passwords` list of
`platform/gemeenten/<gemeente>/<env>/keyvault.tfvars`, so the platform pipeline
(`keyvault` resource) creates them in `kv-<env>-<gemeente>`. Terraform can only
create the *items*: it fills them with a random placeholder, because the real
values do not exist until `bao operator init` runs. An operator overwrites them
once (§5 step 4); `ignore_changes = [value]` keeps later pipeline runs from
putting the placeholder back. An environment deployed any other way must create
both secrets by hand, with the same names.

**The auto-unseal identity** is provisioned **out-of-band (base-infra)** and
referenced by values:

- A **user-assigned Managed Identity** with a **federated credential** for the
  `openbao` ServiceAccount, and the **`Key Vault Crypto User`** role on the
  unseal crypto key. Its client-id is set per-env via
  `server.serviceAccount.annotations."azure.workload.identity/client-id"`.
- `server.extraLabels."azure.workload.identity/use": "true"` and
  `serviceAccount.create: true` / `name: openbao` are set by the chart.

> **Current status:** the MI + federated credential + crypto key remain
> provisioned but are **unused** for unsealing (see §3.6) — the deployment uses
> Shamir, not Azure Key Vault auto-unseal. They are kept so KV auto-unseal can
> be re-enabled later without infra changes.

### 3.6 Seal / init / unseal model (Shamir)

The server config uses **Shamir** seal (no `seal` stanza). Azure Key Vault
auto-unseal is intentionally **not** used: OpenBao 2.5.5's `azurekeyvault` seal
authenticates via IMDS Managed Identity and ignores the AKS workload-identity
federated token, so it cannot reach the vault under workload identity
([openbao-helm#56](https://github.com/openbao/openbao-helm/issues/56),
[hashicorp/vault#29717](https://github.com/hashicorp/vault/issues/29717)).

**One key share, not five.** PodiumD initialises with
`-key-shares=1 -key-threshold=1`. Shamir's value lies in handing shares to
different people so no single one of them can unseal. Here every share would
land in the same Key Vault item set, readable by the same people, so five
shares add four more secrets to copy and no protection. The Key Vault's access
policy is the real control over who can unseal. An environment that does want
split custody must use separate storage per holder; the single
`openbao-unseal-key` item then does not apply.

Consequences (one-time, per fresh cluster):

- After first rollout the vault is **uninitialised + sealed**. The readiness
  probe maps sealed/uninitialised to HTTP 200
  (`/v1/sys/health?...&uninitcode=200&sealedcode=200`) so pods report Ready and a
  `helm --wait` deploy does not block forever. **A green deploy is therefore no
  evidence that OpenBao is usable** — check `bao status` (§6).
- An operator runs `bao operator init` once, then **unseals** each pod with the
  key. **Store the unseal key in `openbao-unseal-key` and the root token in
  `openbao-root-token`** in the environment Key Vault, before doing anything
  else with them.
- Run `scripts/openbao-mint-config-token.sh`: it writes the scoped
  `podiumd-config-job` policy, mints an **orphan periodic token** carrying it,
  and seeds that into `Secret/openbao-bootstrap-token` (key `token`); the
  `openbao-config` Job reads it as `BAO_TOKEN` and renews it on every run. The
  root token is then no longer needed — revoke it (§7). Until that Secret
  exists the Job **self-skips cleanly** (exit 0) so the post-install hook never
  blocks a release; a present-but-invalid token (revoked/expired) **fails the
  Job loudly** instead. Re-run the deploy (or the Job) after the bootstrap to
  apply the config.
- `updateStrategyType: RollingUpdate` (not the sub-chart default `OnDelete`) so a
  `helm upgrade` recreates the server pods to pick up config changes — and
  every recreated pod comes back **sealed** (§5.1).

### 3.7 Keycloak / OIDC integration

All rendered into the **podiumd realm** import (`keycloak-podiumd-realm-config.yaml`):

- **OIDC client `openbao`** — `client-secret` auth, `redirectUris`
  `<oidcUrl>/*` **and** `http://localhost:8250/*` (for `bao login -method=oidc`
  CLI), `webOrigins` `<oidcUrl>/*`, secret injected as `$(KC_SECRET_OPENBAO)`.
  Protocol mappers: `preferred_username` and a **client-role → `groups` claim**
  mapper (client roles of the `openbao` client are emitted in the `groups`
  claim).
- **Client role** `openbao:uploaders` (name from
  `openbao.configuration.uploadersRole` — the single source of truth: it also
  names the OpenBao group-alias the config Job creates, so the claim value and
  the alias always match).
- **Group** `vault-uploaders` (`openbao.configuration.uploadersGroup`), mapped
  to the client role above. Membership is what grants upload access: the role
  lands in the token's `groups` claim, which OpenBao maps — via the group-alias
  — onto an external identity group carrying the `uploader` policy.
- **No users are seeded.** The chart renders no test or su-* users into the
  realm. For test environments, create per-app `su-<app>` users (including
  `su-openbao` with the `uploaders` role) with `scripts/create-su-users.sh`,
  run from your own machine against the Keycloak admin API.
- **Skip-flag caveat:** the realm import's `roles`/`groups` sections are gated
  by `keycloak.config.skipRoles`/`skipGroups` (both default `true`), so on a
  realm running the defaults the `openbao:uploaders` role and `vault-uploaders`
  group are **not** imported. `scripts/create-su-users.sh` creates the role if
  it is missing; set both flags to `false` to have the chart manage the role
  and group instead.
- **Secret** (`keycloak-podiumd-realm-secrets.yaml`, auto-generated and kept
  stable across upgrades, or set via values):
  - `openbao-oidc-secret` — the `openbao` client secret.
- The realm-import Job injects `KC_SECRET_OPENBAO`.

The `openbao-config` Job then makes the vault usable, idempotently:

1. enable the **kv-v2** engine at `configuration.kvPath` (default `secret`);
2. write the **`uploader` policy** (create/update/read on `<kvPath>/data/*`,
   list/read on `<kvPath>/metadata/*`);
3. enable + configure the **`oidc`** auth method against the realm
   (`oidc_discovery_url = <keycloak.url>/realms/<realm>`, client `openbao`,
   `KC_SECRET_OPENBAO`, `default_role = uploader`);
4. create the **`uploader` OIDC role** (`user_claim=sub`, `groups_claim=groups`,
   `allowed_redirect_uris` from `oidcUrl` + `localhost:8250`). Deliberately
   **no `token_policies`** — the policy comes via the group binding in step 5,
   so login alone grants nothing;
5. bind the Keycloak uploaders to the `uploader` policy via an external
   identity group + group-alias. The group mirrors `uploadersGroup`
   (`vault-uploaders`); the **alias** is named after the **client role**
   (`uploadersRole`, `uploaders`), because that is what the openbao client's
   role mapper emits in the `groups` claim. Idempotent: the group id is read
   back by name on re-runs, and an existing alias (including one created under
   the wrong name by earlier chart versions) is updated in place. A failed
   alias write **fails the Job** — no silent success.

> **Access model.** Everyone in the realm can *log in* to OpenBao, but only
> holders of the `openbao:uploaders` client role (normally via membership of
> the `vault-uploaders` group) receive the `uploader` policy; everyone else
> lands with the `default` policy and can do nothing. Earlier chart versions
> granted `token_policies=uploader` to every login — re-running the config Job
> clears that grant (the OIDC-role write is a full replace).

---

## 4. Values reference

Minimum per-environment override to enable OpenBao (illustrative — real hosts,
client-id and DB host come from the environment):

```yaml
openbao:
  enabled: true

  configuration:
    enabled: true
    oidcUrl: https://<env>-openbao-admin.<gemeente>.nl   # == external route host / cert SAN
    keycloak:
      url: https://<env>-keycloak.<gemeente>.nl
      realm: podiumd
    uploadersGroup: vault-uploaders
    kvPath: secret
    bootstrapTokenSecret: openbao-bootstrap-token
    # secrets.keycloak_client_secret: ""  # empty => auto-generated + kept stable

  database:
    secretName: openbao-db
    host: podiumd-<env>-pg.postgres.database.azure.com
    port: 5432
    name: openbao
    username: openbao-admin
    password: ""            # REP_OPENBAO_DB_PASSWORD_REP — pipeline-substituted
    sslmode: require

  server:
    serviceAccount:
      annotations:
        azure.workload.identity/client-id: "<uami-client-id>"   # per-env
```

Key value groups:

| Path | Purpose |
|---|---|
| `openbao.enabled` | master switch (default `false`); must be `true` when `frankgateway.enabled` is |
| `openbao.configuration.*` | consumed by the PodiumD `openbao-*` templates (OIDC/Keycloak wiring, config Job, kv path, bootstrap Secret name) |
| `openbao.database.*` | shared Azure PostgreSQL connection + schema Job |
| `openbao.server.*` | upstream sub-chart keys (image, SA/workload-identity, readiness, HA, storage, HCL `config`, resources) |

Defaults for hosts (`*.example.nl`), `client-id`, and `database.host`/`password`
are placeholders and **must** be overridden per environment.

The unseal key and root token are **not** chart values and never pass through
the Helm deploy: nothing in the chart reads them. They live only in Key Vault
and are used by an operator (§5).

---

## 5. Bootstrap runbook (first install)

Throughout: `<kv>` is the environment Key Vault (`kv-<env>-<gemeente>` for
`ExternalsPodiumD` environments), `<ctx>` the kube-context and `<ns>` the
namespace. Name them on every command.

1. **Infra (base-infra / `infra.yml` / Terraform), out-of-band:**
   - PostgreSQL: create db `openbao` + role `openbao-admin`; store its password
     in Azure Key Vault (pipeline reads `REP_OPENBAO_DB_PASSWORD_REP`).
   - Key Vault items `openbao-unseal-key` and `openbao-root-token` exist
     (`ExternalsPodiumD`: run the platform pipeline with the `keyvault`
     resource; otherwise create them by hand). They hold placeholders for now.
   - Managed Identity + federated credential for SA `openbao`, client-id noted.
   - Gateway/Ingress route → `<release>-openbao-active:8200` (HTTP), external
     host `<env>-openbao-admin.<gemeente>.nl`, TLS cert whose **SAN covers that
     host**.
2. **Chart values:** set the §4 overrides for the environment.
3. **Deploy** (`helm dep build` first if the `.tgz` is not vendored). The
   schema Job creates the tables; the server starts sealed/uninitialised; the
   `openbao-config` Job self-skips (no bootstrap token yet).
4. **Initialise, store, unseal (one-time, manual).** Capture the output
   straight into Key Vault; do not leave it in a terminal scrollback or a file:

   ```bash
   INIT=$(kubectl --context <ctx> -n <ns> exec <release>-openbao-0 -- \
     bao operator init -key-shares=1 -key-threshold=1 -format=json)

   az keyvault secret set --vault-name <kv> --name openbao-unseal-key \
     --value "$(jq -r '.unseal_keys_b64[0]' <<<"$INIT")" -o none
   az keyvault secret set --vault-name <kv> --name openbao-root-token \
     --value "$(jq -r '.root_token' <<<"$INIT")" -o none
   unset INIT
   ```

   Read both back (`az keyvault secret show … --query value`) and confirm
   neither is still the Terraform placeholder **before** unsealing. Then
   unseal every pod as in §5.1.
5. **Mint + seed the config token:**

   ```bash
   BAO_ROOT_TOKEN=$(az keyvault secret show --vault-name <kv> \
     --name openbao-root-token --query value -o tsv) \
   NAMESPACE=<ns> ./charts/podiumd/scripts/openbao-mint-config-token.sh
   ```

   The script uses the ambient kube-context: check it points at `<ctx>` first.
   It writes the scoped `podiumd-config-job` policy, mints an orphan periodic
   token (default period `768h` = 32 days; every config-Job run renews it), and
   seeds it into `Secret/openbao-bootstrap-token` (key `token`). Do **not**
   seed the root token.
6. **Re-run the deploy** (or just the `openbao-config` Job): it now enables
   kv-v2, writes the policy, configures OIDC, and binds the group.
7. **Frank!Gateway secrets.** Write the external-API keys, client certificates
   and consumer list under `<mount>/frankgateway/`, and create the scoped
   reader-token Secret (`frankgateway.openbao.tokenSecret`) — see
   [`frankgateway-routes.md`](frankgateway-routes.md). Until then every
   key-bearing route answers 503.
8. **Verify** (§6), then **revoke the root token**: re-run the script with
   `--revoke-root` (asks for confirmation). The `openbao-root-token` item then
   holds a dead token; that is expected — leave it, so the item keeps its
   history. If the config token ever expires (no deploy within its period),
   re-run step 5 — after root revocation that first needs a new root token from
   `bao operator generate-root` with the unseal key; write the new token over
   `openbao-root-token`, and revoke it again when done.

### 5.1 Unseal after every restart or upgrade

Shamir seal means **every** server pod comes back sealed whenever it restarts:
`helm upgrade` (RollingUpdate), node drain, eviction, OOMKill. A sealed pod
still reports Ready (§3.6), and while the active node is sealed Frank!Gateway
answers 503 on every key-bearing route (§1.1). After any deploy, check and
unseal:

```bash
KEY=$(az keyvault secret show --vault-name <kv> --name openbao-unseal-key \
  --query value -o tsv)
for i in 0 1 2; do
  kubectl --context <ctx> -n <ns> exec -i <release>-openbao-$i -- \
    sh -c 'read -r k; bao operator unseal "$k" >/dev/null' <<<"$KEY"
  printf '<release>-openbao-%s sealed=' "$i"
  kubectl --context <ctx> -n <ns> exec <release>-openbao-$i -- \
    bao status -format=json | jq -r .sealed
done
unset KEY
```

The key goes in over stdin rather than as an exec argument, so it is not
recorded in the Kubernetes audit log (which records exec arguments, not
streamed input). Every line must end `sealed=false`.

> This is the single biggest operational cost of Shamir, and the reason §9
> item 4 stays open: KV auto-unseal would remove it.

---

## 6. Verification

- **Sub-chart materialised:** `helm dep build charts/podiumd` succeeds and
  `charts/podiumd/charts/openbao-0.28.4.tgz` exists.
- **Render:** `helm template ... --set openbao.enabled=true` produces
  `openbao-db` Secret, `openbao-db-schema` Job, `openbao-config` Job, and the
  sub-chart StatefulSet/Services.
- **Key Vault:** `openbao-unseal-key` and `openbao-root-token` exist in the
  environment Key Vault and hold the `bao operator init` output, not the
  Terraform placeholder.
- **Sealed/unsealed:** `bao status` inside **each** server pod reports
  `Initialized true`, `Sealed false` — after step 4 and after every upgrade.
- **Config Job:** `kubectl logs job/openbao-config` says it configured, not
  skipped (§9 item 2).
- **Route + cert:** `curl -sSf https://<env>-openbao-admin.<gemeente>.nl/v1/sys/health`
  returns JSON over a valid TLS chain (SAN matches host).
- **OIDC login (UI):** browse to the host, choose OIDC, authenticate as a
  realm user with the `openbao:uploaders` role (e.g. `su-openbao` created by
  `scripts/create-su-users.sh`); you should land with the `uploader` policy —
  granted via the external group, so `bao token lookup` shows it under
  `identity_policies` (not `policies`). A user *without* the role gets only
  `default`.
- **OIDC login (CLI):** `bao login -method=oidc` completes via the
  `localhost:8250` callback.
- **Upload:** as an uploader, `bao kv put secret/<path> k=v` succeeds; a
  non-member is denied.
- **Frank!Gateway:** a test call through a key-bearing route (BAG or KVK on the
  outway) reaches its upstream instead of answering 503.

---

## 7. Security notes

- DB credentials reach the server only via `BAO_PG_CONNECTION_URL` (Secret env),
  never the config ConfigMap. The schema Job inlines `PGPASSWORD` from values
  (same plaintext the Secret carries) because a `pre-install` hook cannot depend
  on a normal-resource Secret.
- The OIDC client secret is auto-generated and kept stable in
  `keycloak-podiumd-realm-secrets`; secrets are never inlined into the realm
  ConfigMap (injected as `$(KC_...)` env at import time).
- Jobs run non-root, `readOnlyRootFilesystem`, `allowPrivilegeEscalation:
  false`, all capabilities dropped, `seccompProfile: RuntimeDefault`.
- The **unseal key** (`openbao-unseal-key`) decrypts everything in the
  `openbao` database. With one share, whoever can read that Key Vault item
  plus the database can read every secret in the vault. Keep the Key Vault
  access policy as narrow as the database's. It is never revoked; rotating it
  means `bao operator rekey`, after which the Key Vault item must be updated in
  the same sitting.
- The **root token** captured at `bao operator init` is needed exactly once: to
  mint the scoped config token (§5, `scripts/openbao-mint-config-token.sh`).
  Store it only in Azure Key Vault (`openbao-root-token`) and **revoke it**
  (`--revoke-root`) once a deploy has succeeded with the scoped token —
  revocation no longer breaks upgrades. Break-glass: the unseal key can mint a
  new root token via `bao operator generate-root`.
- The `openbao-config` Job authenticates with the **`podiumd-config-job`
  token**: orphan (survives root revocation), periodic (renewed by the Job on
  every run), and restricted to the exact paths the Job configures — an
  attacker reading the namespace Secret gets config-plumbing rights, not the
  vault's contents or root control.
- Frank!Gateway's reader token is likewise scoped (`<mount>/frankgateway/*`,
  read only), so a compromised gateway pod exposes the gateway's own keys and
  nothing else in the vault.

---

## 8. Sizing (defaults)

| Workload | CPU request | Mem request | CPU limit | Mem limit |
|---|---|---|---|---|
| server (each of 3 replicas) | 100m | 256Mi | 500m | 512Mi |
| `openbao-config` Job | 50m | 64Mi | 250m | 128Mi |
| `openbao-db-schema` Job | 50m | 64Mi | 250m | 128Mi |

No observed-usage numbers yet — first production-like deployment pending.

---

## 9. Known limitations & open items

1. **Images manifest.** `openbao/openbao:2.5.5` and `postgres:16-alpine` are
   recorded (digest-pinned) in `docs/images/images-baseline.yaml`. If the agent
   injector is ever re-enabled, add `hashicorp/vault-k8s:1.7.2` there too.
   Override `server.image` / the Job images to the ACR mirror before shipping
   to a digest-pinned production environment. Egress must reach `quay.io` and
   `docker.io` until then. Note the schema Job tag `16-alpine` is a floating
   minor tag (IN-2399): pin a specific 16.x when picking that up.
2. **Config-Job silent skip.** `openbao-bootstrap-token` is created out-of-band
   (§5); if it is **missing** the `openbao-config` Job exits 0 and the `helm
   upgrade` **succeeds while the vault stays unconfigured**. Check the Job log
   after deploy (`kubectl logs job/openbao-config`) — a green release is not
   proof the OIDC/policy config was applied. (A present-but-invalid token, by
   contrast, fails the Job loudly.) The Job is kept after success precisely so
   this log stays readable: `ttlSecondsAfterFinished: 600` garbage-collects it
   after ~10 minutes, and the next deploy replaces it (`before-hook-creation`).
3. **Release/upgrade docs.** OpenBao is not mentioned in `README.md` or the
   upgrade guides; it is opt-in, but release notes that enable Frank!Gateway
   should point operators here.
4. **No KV auto-unseal yet.** Shamir requires a manual `bao operator init` +
   unseal per fresh cluster and after every restart/upgrade (§5.1). Revisit
   Azure Key Vault auto-unseal once OpenBao honours the workload-identity
   federated token (openbao-helm#56 / vault#29717). The MI + crypto key are
   already provisioned. Once adopted, `openbao-unseal-key` is replaced by
   recovery keys and this runbook changes.
5. **Route lives in `infra.yml`.** The external Gateway/Ingress route and its TLS
   cert (with the required SAN) are defined outside this chart; they must be kept
   in sync with `openbao.configuration.oidcUrl`.
6. **History.** Originally developed against `feature/podiumd-4.8.0` (PR
   [#343](https://github.com/Dimpact-Samenwerking/helm-charts/pull/343));
   rebased onto `feature/podiumd-4.8.2` as `feature/podiumd-4.8.2-openbao`
   (PR [#384](https://github.com/Dimpact-Samenwerking/helm-charts/pull/384)),
   2026-07-17. Documented as a separate component until 2026-09; merged into
   the Frank!Gateway docs because Frank!Gateway is its reason to exist in
   PodiumD.

---

## References

- OpenBao docs: <https://openbao.org/docs/>
- PostgreSQL storage backend:
  <https://openbao.org/docs/configuration/storage/postgresql/>
- `bao operator init`:
  <https://openbao.org/docs/commands/operator/init/>
- OpenBao Helm chart: <https://github.com/openbao/openbao-helm>
- Workload-identity unseal limitation:
  [openbao-helm#56](https://github.com/openbao/openbao-helm/issues/56) ·
  [hashicorp/vault#29717](https://github.com/hashicorp/vault/issues/29717)
- PR [#343](https://github.com/Dimpact-Samenwerking/helm-charts/pull/343),
  PR [#384](https://github.com/Dimpact-Samenwerking/helm-charts/pull/384)
