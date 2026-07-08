# PodiumD component: OpenBao (secrets vault)

> New component in PodiumD **4.8.0**, delivered on branch
> `feature/podiumd-4.8.0-openbao` (PR
> [#343](https://github.com/Dimpact-Samenwerking/helm-charts/pull/343)).
> **Disabled by default** (`openbao.enabled: false`); enable and supply the
> per-environment values described below.

[OpenBao](https://openbao.org/) is an open-source, community-governed fork of
HashiCorp Vault (MPL-2.0). It is wired into PodiumD as an in-cluster secrets
vault that end users log in to with their Keycloak identity (OIDC) to store and
retrieve secrets. It runs HA (3 replicas), is backed by the shared Azure
PostgreSQL server, and is fronted by the platform Gateway/Ingress.

This document describes **everything OpenBao needs** to become a working part of
the PodiumD chart: the chart wiring, the container images, the database, the
network route, the TLS certificate, the Azure/workload-identity prerequisites,
the seal/init/unseal model, and the Keycloak/OIDC integration — followed by a
values reference, a bootstrap runbook, verification steps, and the known open
items.

---

## DevOps TL;DR

> First deploy: read the full doc below. Subsequent deploys: this section is all
> you need.

Infra to provision per environment (one line each):

| Piece | What DevOps must provide |
|---|---|
| **Database** | Azure PostgreSQL db `openbao` + role `openbao-admin`; password in Key Vault (`REP_OPENBAO_DB_PASSWORD_REP`). Tables auto-created by the schema Job. |
| **Ingress / route** | Gateway/Ingress (`infra.yml`) → service `<release>-openbao-active:8200` over **HTTP** (TLS terminated at gateway), host = `openbao.<env>.example.nl`. |
| **TLS cert** | Gateway cert **SAN must cover the OpenBao host** (`openbao.<env>.example.nl`); pods run no TLS (`tls_disable=1`), so no server cert needed. |
| **Storage** | **None** — no PVC (PostgreSQL storage backend, `dataStorage.enabled=false`). |
| **Secrets** | `openbao-db` (chart-rendered) · `openbao-bootstrap-token` key `token` (**seeded by `scripts/openbao-mint-config-token.sh`** — a scoped periodic token, NOT the root token) · `openbao-oidc-secret` (auto-generated, kept stable). |
| **Identity** | User-assigned MI + federated credential for SA `openbao`; set client-id in `server.serviceAccount.annotations`. (KV unseal key provisioned but unused — Shamir.) |
| **Images / egress** | Allow `quay.io/openbao/openbao:2.5.5` + `docker.io/library/postgres:16-alpine` (or mirror to ACR + override). |
| **One-time bootstrap** | `bao operator init` + unseal (×3 pods, **Shamir → repeat after every restart/upgrade**); mint + seed the scoped config token (`scripts/openbao-mint-config-token.sh`), then revoke the root token; re-run deploy; check `kubectl logs job/openbao-config`. |

Values to set: `openbao.enabled=true`, `openbao.database.host`, `openbao.configuration.oidcUrl`, `openbao.configuration.keycloak.url`, `server.serviceAccount.annotations` client-id. Full runbook in §5.

---

## 1. Architecture at a glance

```
                 ┌──────────────── Keycloak (podiumd realm) ────────────────┐
                 │  OIDC client "openbao"  ·  group "vault-uploaders"        │
                 │  clientRole openbao:uploaders                             │
                 └───────────────▲───────────────────────▲──────────────────┘
   browser / bao CLI             │ OIDC login            │ discovery + client-secret
        │                        │                       │
        ▼   HTTPS (TLS at GW)    │                       │
┌────────────────┐   route   ┌──┴───────────────────────┴──┐        ┌───────────────┐
│ Gateway/Ingress│──────────▶│  Service <release>-openbao   │        │  Azure Key    │
│  (infra.yml)   │  :8200    │  -active  (HA, 3 replicas)   │        │  Vault        │
│  cert w/ SAN   │  http     │  listener tls_disable=1      │        │  (unseal keys │
└────────────────┘           │  storage = PostgreSQL        │        │   + root tok) │
                             └──────────────┬───────────────┘        └───────────────┘
                                            │ BAO_PG_CONNECTION_URL
                                            ▼
                            ┌───────────────────────────────┐
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

> **Open item (see §9):** `docs/images/images-4.8.0.yaml` currently lists **only**
> Open Inwoner. The three images above are **not** yet recorded there, and no ACR
> mirror name / digest pin has been captured for the OpenBao and postgres images.
> For an ACR-mirrored, digest-pinned production environment these must be added
> and the values overridden to the mirror.

### 3.2 PostgreSQL database (shared Azure PostgreSQL)

OpenBao uses the PostgreSQL storage backend — there is **no data PVC**
(`server.dataStorage.enabled: false`). It does **not** create its own tables.

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
environment's `infra.yml`**, not by this chart. The route MUST satisfy:

- **Backend service:** `<release>-openbao-active` on **port 8200**
  (the HA sub-chart publishes `-active` = current leader, `-standby`,
  `-internal`, `-ui`). Target `-active` so writes and the OIDC login UI always
  hit the unsealed leader. (`<release>` is the Helm release name, e.g.
  `podiumd-openbao-active`.)
- **Protocol to backend:** plain **HTTP**. The server listener runs
  `tls_disable = 1` on `[::]:8200`; **TLS is terminated at the gateway** and
  re-originated as cleartext inside the cluster.
- **External host:** must equal the host in `openbao.configuration.oidcUrl`
  (e.g. `https://openbao.<env>.example.nl`). This host drives the Keycloak
  client `redirectUris` and the OIDC role `allowed_redirect_uris`; a mismatch
  breaks OIDC login (`redirect_uri` rejected).
- **UI:** the server sets `ui = true`; the OIDC callback path used is
  `<oidcUrl>/ui/vault/auth/oidc/oidc/callback`.

> The intra-cluster HA port `[::]:8201` (`cluster_address`) is used for
> leader-forwarding between replicas and is **not** routed externally.

### 3.4 TLS certificate — SAN requirements

Because TLS is terminated at the gateway, the **gateway/ingress certificate**
(managed in `infra.yml`, typically via cert-manager or a platform wildcard
cert) is what matters:

- The certificate presented for the OpenBao route **must include the external
  OpenBao host as a Subject Alternative Name (SAN)** — e.g.
  `openbao.<env>.example.nl`. A wildcard SAN (`*.<env>.example.nl`) that already
  covers the chosen host is acceptable.
- The host, its SAN, and `openbao.configuration.oidcUrl` must all agree.
- The **in-cluster** listener uses no TLS (`tls_disable = 1`), so **no
  server-side certificate or SAN is required on the pods** and none is
  provisioned by this chart. If a future requirement mandates end-to-end TLS
  (cluster-internal), a server cert whose SAN covers `<release>-openbao*` service
  DNS names and the `8200`/`8201` listeners would need to be added — out of
  scope for 4.8.0.

### 3.5 Azure Key Vault + Workload Identity

Provisioned **out-of-band (base-infra)**, referenced by values:

- A **user-assigned Managed Identity** with a **federated credential** for the
  `openbao` ServiceAccount, and the **`Key Vault Crypto User`** role on the
  unseal key. Its client-id is set per-env via
  `server.serviceAccount.annotations."azure.workload.identity/client-id"`.
- `server.extraLabels."azure.workload.identity/use": "true"` and
  `serviceAccount.create: true` / `name: openbao` are set by the chart.

> **Current status:** the MI + federated credential + KV key remain provisioned
> but are **unused** for unsealing (see §3.6) — the deployment uses Shamir, not
> Azure Key Vault auto-unseal. They are kept so KV auto-unseal can be re-enabled
> later without infra changes.

### 3.6 Seal / init / unseal model (Shamir)

The server config uses **Shamir** seal (no `seal` stanza). Azure Key Vault
auto-unseal is intentionally **not** used: OpenBao 2.5.5's `azurekeyvault` seal
authenticates via IMDS Managed Identity and ignores the AKS workload-identity
federated token, so it cannot reach the vault under workload identity
([openbao-helm#56](https://github.com/openbao/openbao-helm/issues/56),
[hashicorp/vault#29717](https://github.com/hashicorp/vault/issues/29717)).

Consequences (one-time, per fresh cluster):

- After first rollout the vault is **uninitialised + sealed**. The readiness
  probe maps sealed/uninitialised to HTTP 200
  (`/v1/sys/health?...&uninitcode=200&sealedcode=200`) so pods report Ready and a
  `helm --wait` deploy does not block forever.
- An operator runs `bao operator init` once, then **unseals** with the Shamir
  key shares. **Store the unseal key shares and the root token in the per-env
  Azure Key Vault** (`openbao-root-token-<env>`).
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
  `helm upgrade` recreates the server pods to pick up config changes.

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

> **Related, but separable:** this branch also makes `accessTokenLifespan`
> configurable. Per-app `su-<app>` admin users are **not** chart-rendered; for
> test environments create them with `scripts/create-su-users.sh` (run locally
> against the Keycloak admin API). They are not required to run OpenBao.

---

## 4. Values reference

Minimum per-environment override to enable OpenBao (illustrative — real hosts,
client-id and DB host come from the environment):

```yaml
openbao:
  enabled: true

  configuration:
    enabled: true
    oidcUrl: https://openbao.<env>.example.nl      # == external route host / cert SAN
    keycloak:
      url: https://keycloak.<env>.example.nl
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
| `openbao.enabled` | master switch (default `false`) |
| `openbao.configuration.*` | consumed by the PodiumD `openbao-*` templates (OIDC/Keycloak wiring, config Job, kv path, bootstrap Secret name) |
| `openbao.database.*` | shared Azure PostgreSQL connection + schema Job |
| `openbao.server.*` | upstream sub-chart keys (image, SA/workload-identity, readiness, HA, storage, HCL `config`, resources) |

Defaults for hosts (`*.example.nl`), `client-id`, and `database.host`/`password`
are placeholders and **must** be overridden per environment.

---

## 5. Bootstrap runbook (first install)

1. **Infra (base-infra / `infra.yml`), out-of-band:**
   - PostgreSQL: create db `openbao` + role `openbao-admin`; store its password
     in Azure Key Vault (pipeline reads `REP_OPENBAO_DB_PASSWORD_REP`).
   - Managed Identity + federated credential for SA `openbao`, client-id noted.
   - Gateway/Ingress route → `<release>-openbao-active:8200` (HTTP), external
     host `openbao.<env>.example.nl`, TLS cert whose **SAN covers that host**.
2. **Chart values:** set the §4 overrides for the environment.
3. **Deploy** (`helm dep build` first if the `.tgz` is not vendored). The
   schema Job creates the tables; the server starts sealed/uninitialised; the
   `openbao-config` Job self-skips (no bootstrap token yet).
4. **Initialise + unseal (one-time, manual):**
   ```bash
   kubectl -n <ns> exec -it <release>-openbao-0 -- bao operator init
   # store the unseal key shares + root token in Azure Key Vault (openbao-root-token-<env>)
   kubectl -n <ns> exec -it <release>-openbao-0 -- bao operator unseal <key-share>   # x quorum, per pod
   ```
5. **Mint + seed the config token:**
   ```bash
   NAMESPACE=<ns> ./charts/podiumd/scripts/openbao-mint-config-token.sh
   ```
   Writes the scoped `podiumd-config-job` policy, mints an orphan periodic
   token (default period `768h` = 32 days; every config-Job run renews it), and
   seeds it into `Secret/openbao-bootstrap-token` (key `token`). Do **not**
   seed the root token.
6. **Re-run the deploy** (or just the `openbao-config` Job): it now enables
   kv-v2, writes the policy, configures OIDC, and binds the group.
7. **Verify** (§6), then **revoke the root token**: re-run the script with
   `--revoke-root` (asks for confirmation). If the config token ever expires
   (no deploy within its period), re-run step 5 — after root revocation that
   first needs `bao operator generate-root` with a quorum of unseal key shares.

> On upgrades OpenBao comes back **sealed** (Shamir) and must be unsealed again
> unless/until KV auto-unseal is adopted.

---

## 6. Verification

- **Sub-chart materialised:** `helm dep build charts/podiumd` succeeds and
  `charts/podiumd/charts/openbao-0.28.4.tgz` exists.
- **Render:** `helm template ... --set openbao.enabled=true` produces
  `openbao-db` Secret, `openbao-db-schema` Job, `openbao-config` Job, and the
  sub-chart StatefulSet/Services.
- **Sealed/unsealed:** `bao status` inside a server pod reports `Initialized
  true`, `Sealed false` after step 4.
- **Route + cert:** `curl -sSf https://openbao.<env>.example.nl/v1/sys/health`
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
- The **root token** captured at `bao operator init` is needed exactly once: to
  mint the scoped config token (§5, `scripts/openbao-mint-config-token.sh`).
  Store it only in Azure Key Vault and **revoke it** (`--revoke-root`) once a
  deploy has succeeded with the scoped token — revocation no longer breaks
  upgrades. Break-glass: a quorum of unseal key shares can mint a new root
  token via `bao operator generate-root`; the unseal keys themselves are never
  revoked.
- The `openbao-config` Job authenticates with the **`podiumd-config-job`
  token**: orphan (survives root revocation), periodic (renewed by the Job on
  every run), and restricted to the exact paths the Job configures — an
  attacker reading the namespace Secret gets config-plumbing rights, not the
  vault's contents or root control.

---

## 8. Sizing (defaults)

| Workload | requests | limits |
|---|---|---|
| server (each of 3 replicas) | 100m CPU / 256Mi | 500m CPU / 512Mi |
| `openbao-config` Job | 50m CPU / 64Mi | 250m CPU / 128Mi |
| `openbao-db-schema` Job | 50m CPU / 64Mi | 250m CPU / 128Mi |

---

## 9. Known limitations & open items

1. **Images manifest incomplete.** `docs/images/images-4.8.0.yaml` does not list
   `openbao/openbao:2.5.5`, `postgres:16-alpine`, or (if the injector is ever
   re-enabled) `hashicorp/vault-k8s:1.7.2`; no ACR mirror name or digest pin is
   recorded, and the tags are not digest-pinned. Add them (and override
   `server.image` / the Job images to the mirror) before shipping to a
   digest-pinned production environment. jim00 egress must reach `quay.io` and
   `docker.io` until then.
2. **Config-Job silent skip.** `openbao-bootstrap-token` is created out-of-band
   (§5); if it is **missing** the `openbao-config` Job exits 0 and the `helm
   upgrade` **succeeds while the vault stays unconfigured**. Check the Job log
   after deploy (`kubectl logs job/openbao-config`) — a green release is not
   proof the OIDC/policy config was applied. (A present-but-invalid token, by
   contrast, fails the Job loudly.) The Job is kept after success precisely so
   this log stays readable: `ttlSecondsAfterFinished: 600` garbage-collects it
   after ~10 minutes, and the next deploy replaces it (`before-hook-creation`).
2. **Release/upgrade docs.** OpenBao is not mentioned in `README.md` or
   `docs/upgrade-from-4.7.3-to-4.8.0.md`; it is opt-in, but the 4.8.0 notes
   should point operators here.
3. **No KV auto-unseal yet.** Shamir requires a manual `bao operator init` +
   unseal per fresh cluster and after every restart/upgrade. Revisit Azure Key
   Vault auto-unseal once OpenBao honours the workload-identity federated token
   (openbao-helm#56 / vault#29717). The MI + KV key are already provisioned.
4. **Route lives in `infra.yml`.** The external Gateway/Ingress route and its TLS
   cert (with the required SAN) are defined outside this chart; they must be kept
   in sync with `openbao.configuration.oidcUrl`.
5. **Branch divergence.** This branch diverged from `feature/podiumd-4.8.0`;
   rebase/merge before completing (see PR #343).

---

## References

- OpenBao docs: <https://openbao.org/docs/>
- PostgreSQL storage backend:
  <https://openbao.org/docs/configuration/storage/postgresql/>
- OpenBao Helm chart: <https://github.com/openbao/openbao-helm>
- Workload-identity unseal limitation:
  [openbao-helm#56](https://github.com/openbao/openbao-helm/issues/56) ·
  [hashicorp/vault#29717](https://github.com/hashicorp/vault/issues/29717)
- PR [#343](https://github.com/Dimpact-Samenwerking/helm-charts/pull/343)
