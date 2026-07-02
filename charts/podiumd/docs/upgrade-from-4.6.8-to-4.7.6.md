# Upgrade guide: PodiumD 4.6.8 → 4.7.6

> **Consolidated guide.** This is a single official-path hop that folds the whole
> 4.7.x release line (4.7.0 → 4.7.6) into one document. See
> [`UPGRADING.md`](UPGRADING.md) for the full upgrade path. Granular per-release
> notes are kept alongside for reference:
> [4.7.0→4.7.1](upgrade-from-4.7.0-to-4.7.1.md),
> [4.7.1→4.7.2](upgrade-from-4.7.1-to-4.7.2.md),
> [4.7.2→4.7.3](upgrade-from-4.7.2-to-4.7.3.md),
> [4.7.3→4.7.4](upgrade-from-4.7.3-to-4.7.4.md).
>
> **Open Inwoner stays on stable `2.1.2`** for the whole 4.6.8 → 4.7.6 range —
> it does not change. The `2.1.2-rc1` release candidate is **never** part of
> this path; do not pin it.
>
> See the Confluence Releases page for the agreed application targets:
> <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.

## Component versions (target 4.7.6)

| Component | App version | Helm chart |
|---|---|---|
| Keycloak (server + operator) | 26.6.3 | adfinis 1.12.0 |
| OpenZaak | 1.27.2 | 1.14.1 |
| ZAC | 4.7.2 | 1.0.228 |
| Open Formulieren | 3.4.9 | 1.12.0 |
| Open Archiefbeheer | 2.0.0 | 2.0.0 (⚠️ breaking) |
| Open Beheer | 0.9.0 | 0.1.3 |
| Open Inwoner | 2.1.2 (stable — unchanged from 4.6.8) | 2.1.3 |
| Object Types API | 3.4.2 | 1.6.1 |
| Referentielijsten API | 0.7.2 | 0.1.1 |
| OMC (NotifyNL) | 1.17.19 | 0.14.1 |
| ZGW Office Add-in | v0.9.313 | 0.0.88 |
| ITA (interne taak-afhandeling) | 3.1.0 | — |
| nginx-unprivileged (api-proxy + Maykin/ZAC sidecars) | 1.30.2 | — |
| Zaakbrug (opt-in) | 1.26.13 | wearefrank 2.3.26 |
| APISIX (egress gateway, opt-in) | 3.16.0 | 2.14.0 |

> Open Inwoner is already on stable `2.1.2` at 4.6.8 and remains there through
> 4.7.6. There is no rc1 step on this path.

**What changed across the 4.7.x line (vs 4.6.8):**

- **4.7.0–4.7.3** — Open Archiefbeheer 2.0.0 (breaking, OIDC migration), Open Zaak
  chart 1.13.1→1.14.1 (configurable Documenten API backend), Keycloak 26.6.1→26.6.2
  (security, CRD `v2alpha1`→`v2beta1`), nginx 1.30.0→1.30.2 (security), ZAC 4.7.2 +
  native Gotenberg, Zaakbrug sub-chart (opt-in), MI exports (opt-in), APISIX egress
  (opt-in).
- **4.7.4** — Keycloak 26.6.2→26.6.3 (16 CVEs), Open Zaak 1.27.1→1.27.2 (`/zoek`
  authz + bulk-import path-traversal), Datamigratie Keycloak client + Open Zaak
  credentials, Open Formulieren outgoing-request logging disabled by default.
- **4.7.5** — ZGW Office Add-in v0.9.289→v0.9.313 (repo rename `add-in`→`addin`).
- **4.7.6** — Open Formulieren logging revert (back to upstream default), Open
  Archiefbeheer `external_registers` exact-match completion, Open Beheer ↔
  Objecttypen API token (IN-2345). No image bumps.

---

## Required manual steps

### Before upgrading

1. **Quiesce Open Archiefbeheer** — ensure no destruction lists are processing or waiting for retry. The internal data structure for tracking destruction has been reworked; lists in-flight during the upgrade may end up in an inconsistent state.
2. **Update the ACR mirror for ZAC office_converter** — `acrprodmgmt.azurecr.io/office-converter` must be updated to mirror `gotenberg/gotenberg:8.31.0` instead of `ghcr.io/eugenmayer/kontextwork-converter`. Without this, environments overriding `zac.office_converter.image.repository` will fail to pull the image.
3. **Apply Keycloak `v2beta1` CRDs** (see [Keycloak CRD upgrade](#keycloak-crd-upgrade-v2alpha1--v2beta1)). Required for the 4.6.8 → 4.7.3 hop because the chart bumps the operator image to `26.6.x` while the bundled adfinis subchart `1.11.4` still ships `v2alpha1` CRDs. The 4.7.4 bump 26.6.2 → 26.6.3 needs **no** further CRD action (26.6.3 CRDs are byte-identical, and adfinis 1.12.0 bundles the matching set).
4. **Set `apiproxy.nginxCertsSecret` explicitly** if your environment uses upstream mTLS via the api-proxy and you have not already pinned it. The chart default is `""` (empty); environments that relied on the implicit `"api-proxy-certs"` default must pin the value in `podiumd.yml` **before** the upgrade or the cert volume mount disappears and upstream calls fall back to non-mTLS with `proxy_ssl_verify off`.
5. **Run the migration scripts** (see [Migration scripts](#migration-scripts)).
6. **Update the ACR mirror** for the new security-release image tags + digests: `keycloak`/`keycloak-operator` `26.6.3`, `nginx-unprivileged` `1.30.2`, Open Zaak `1.27.2`, ZGW Office Add-in `v0.9.313` (repos renamed `add-in`→`addin`). See the per-release image manifests (`images-4.7.2.yaml` … `images-4.7.5.yaml`).
7. **Add Open Archiefbeheer ↔ Objecten/OpenKlant secrets** (4.7.3, see [Open Archiefbeheer — add Objecten + OpenKlant services](#open-archiefbeheer--add-objecten--openklant-services)).
8. **Add Datamigratie Keycloak client + Open Zaak credentials** (4.7.4, see [Datamigratie Keycloak client + Open Zaak secret](#datamigratie-keycloak-client--open-zaak-secret)).
9. **Verify Open Archiefbeheer `external_registers` identifiers match** the provisioned `zgw_consumers` service identifiers (see [Open Archiefbeheer `external_registers` matching](#open-archiefbeheer-external_registers-must-match-the-zgw_consumers-service-identifiers)).
10. **Zaakbrug prerequisites** — only if enabling `zaakbrug.enabled: true` (see [Zaakbrug: new sub-chart](#zaakbrug-new-sub-chart)): Postgres DB, Key Vault secrets, DNS CNAME, and the `wearefrank` helm repo.

### After upgrading

11. **Reconfigure the destruction report settings** in the Open Archiefbeheer admin interface. The destruction report configuration page has been reworked; existing settings are not migrated automatically.
12. **Open Formulieren outgoing-request logging is ON again** (4.7.6 reverted the 4.7.4 default). If you want it off, add the opt-out override (see [Open Formulieren request logging](#open-formulieren--outgoing-request-logging-4744--476)).

---

## Keycloak CRD upgrade (`v2alpha1` → `v2beta1`)

Applies to the **4.6.8 → 4.7.3** hop. The chart pins `keycloak-operator` to image `quay.io/keycloak/keycloak-operator` at `26.6.x`, but the adfinis subchart `keycloak-operator-1.11.4` (appVersion `26.5.6`) ships the older `v2alpha1` CRDs. The operator issues informer queries against `apis/k8s.keycloak.org/v2beta1/...`.

> The later 4.7.4 bump to operator `26.6.3` (adfinis `1.12.0`) requires **no** CRD action — the 26.6.3 CRDs are byte-identical to 26.6.2 and the 1.12.0 chart bundles them.

### Apply procedure

Use the helper script (`charts/podiumd/scripts/install-keycloak-operator-crds.sh`). It defaults to the upstream Keycloak `v1` CRD manifests at the right Keycloak version and applies them server-side:

```bash
CTX=<your-aks-context>
NS=<keycloak-namespace>      # e.g. podiumd

# 1. Snapshot existing CRs (rollback insurance)
kubectl --context "$CTX" -n "$NS" get keycloak,keycloakrealmimport -o yaml > /tmp/kc-backup-$(date +%s).yml

# 2. Install upstream CRDs (adds v2beta1, keeps v2alpha1 deprecated/served)
charts/podiumd/scripts/install-keycloak-operator-crds.sh \
  --context "$CTX" --keycloak-version 26.6.3

# 3. Restart the operator so it re-establishes informers
kubectl --context "$CTX" -n "$NS" rollout restart deploy keycloak-operator

# 4. Migrate stored CRs to v2beta1 storage version (read + re-apply triggers re-serialization)
kubectl --context "$CTX" -n "$NS" get keycloak,keycloakrealmimport -o yaml \
  | kubectl --context "$CTX" apply -f -
```

The script accepts `--dry-run` to inspect the CRD YAML, `--keycloak-version` to pin to a specific Keycloak release, and `--source chart --chart-version 1.12.0` to fall back to the adfinis subchart CRDs.

- Upstream CRDs declare both versions:
  - `v2beta1`: `served: true`, `storage: true`
  - `v2alpha1`: `served: true`, `storage: false`, `deprecated: true`
- No conversion webhook → default `None` strategy, fields pass through by name.
- Schema is additive between 26.5.x and 26.6.x — no removed/renamed required fields.
- The Keycloak `StatefulSet` keeps running while the operator restarts; only reconciliation is paused.

---

## API proxy: `nginxCertsSecret` default + `sslVerifyDepth`

`apiproxy.nginxCertsSecret` defaults to `""` (empty). When empty:

- The cert volume / `/etc/nginx/certs` mount is omitted.
- `proxy_ssl_certificate` / `proxy_ssl_certificate_key` directives are not rendered (no client cert sent upstream).
- `apiproxy.locations.commonSettings.sslVerify` (still `""` = auto-derive) resolves to `"off"`, so upstream server certs are **not** validated.

`apiproxy.sslVerifyDepth` (default `6`) renders `proxy_ssl_verify_depth` for every upstream location. nginx default is `1`, which is too shallow for cross-signed government API chains. Override globally on the api-proxy block, or per upstream:

```yaml
apiproxy:
  sslVerifyDepth: 6              # global default
  locations:
    bag:
      sslVerifyDepth: 10         # override only for BAG
    brp:
      sslVerifyDepth: 4          # override only for BRP
```

### Action required

If your environment **does** use upstream mTLS via the api-proxy and the secret is provisioned in the `podiumd` namespace, pin the value explicitly in your gemeente `podiumd.yml` **before** running `helm upgrade`:

```yaml
apiproxy:
  enabled: true
  nginxCertsSecret: api-proxy-certs   # or whatever name the secret has in your cluster
```

If `apiproxy.enabled` is `false` (most non-DIMP gemeentes), no action is needed.

---

## Migration scripts

All scripts ship in `charts/podiumd/scripts/`. Run from the repo root (or use an absolute path). All are idempotent — re-running on an already-migrated file is safe.

| Script | Purpose | Required for |
|---|---|---|
| `migrate-openarchiefbeheer-2.0.0.py` | Migrate `openarchiefbeheer.configuration.data` OIDC block to v1.1.1 (`providers` + `options`) and drop deprecated keys | Open Archiefbeheer 2.0.0 upgrade |
| `migrate-zac-4.7.0.py` | Rewrite `zac.office_converter.image.repository` from `<acr>/office-converter` to `<acr>/gotenberg` | ZAC 4.7.x upgrade (only if repository overridden per-environment) |
| `fix-oidc-config.py` | Generic OIDC migration: flat `claim_mapping` / `username_claim` / `groups_claim` / `make_users_staff` → `options.user_settings` / `options.groups_settings`. Promotes inline `endpoint_config` to a top-level `providers` list and adds `oidc_provider_identifier` references | Any component using `mozilla-django-oidc-db ≥ 1.x` (openzaak, opennotificaties, objecten, objecttypen, openklant, openformulieren, openarchiefbeheer). Skips `openinwoner` (still flat format) automatically |

### `migrate-openarchiefbeheer-2.0.0.py` — Open Archiefbeheer 2.0.0 OIDC migration

Required for Open Archiefbeheer 2.0.0. The `mozilla-django-oidc-db` library was upgraded to v1.1.1, which requires a new YAML structure with a separate `providers` list. The old `items`-only format is no longer accepted. Requires `yq` v4 (`brew install yq`).

```bash
# Preview changes without modifying files
python3 charts/podiumd/scripts/migrate-openarchiefbeheer-2.0.0.py --dry-run

# Apply to all gemeente podiumd.yml files
python3 charts/podiumd/scripts/migrate-openarchiefbeheer-2.0.0.py

# Or apply to a single file
python3 charts/podiumd/scripts/migrate-openarchiefbeheer-2.0.0.py path/to/gemeente/env/podiumd.yml
```

#### Transformations

| Before | After |
|---|---|
| `items` only, with `endpoint_config` inline | Separate `providers` list holds `endpoint_config`; item references it via `oidc_provider_identifier` |
| `username_claim`, `groups_claim`, `superuser_group_names`, `make_users_staff` as top-level item fields | Restructured into `options.user_settings` and `options.groups_settings` |
| `claim_mapping`, `userinfo_claims_source`, `oidc_rp_scopes_list`, `sync_groups` present | Removed (deprecated) |

> **Note on PKCE.** OAB 2.0.0 ships with `mozilla-django-oidc-db 1.1.1`, whose `setup_configuration` schema does NOT accept `oidc_use_pkce` at item or provider level. Do not add this field for OAB. `openarchiefbeheer.configuration.pkceEnabled` is a no-op. If a previous run left `oidc_use_pkce: false` in your data, remove it or re-run the migration script (which strips it via `yq del`).

### `migrate-zac-4.7.0.py` — ZAC office_converter image rename

Only relevant if a gemeente values file overrides `zac.office_converter.image.repository`. Without an override, the chart `values.yaml` already points to `gotenberg/gotenberg:8.31.0` and no rewrite is needed. The script handles both `acrprodmgmt.azurecr.io` and `acrtestmgmt.azurecr.io`.

```bash
python3 charts/podiumd/scripts/migrate-zac-4.7.0.py --dry-run   # preview
python3 charts/podiumd/scripts/migrate-zac-4.7.0.py             # apply to all gemeente files
```

### `fix-oidc-config.py` — generic OIDC migration sweep

Catch-all for any component using `mozilla-django-oidc-db ≥ 1.x`. Skips `openinwoner` automatically. Requires `ruamel.yaml` (preferred) or `PyYAML`.

```bash
python3 charts/podiumd/scripts/fix-oidc-config.py values-<gemeente>.yml --dry-run   # writes nothing
python3 charts/podiumd/scripts/fix-oidc-config.py values-<gemeente>.yml             # in-place migrate
```

#### Recommended order for openarchiefbeheer

```bash
python3 charts/podiumd/scripts/migrate-openarchiefbeheer-2.0.0.py --dry-run
python3 charts/podiumd/scripts/migrate-openarchiefbeheer-2.0.0.py
python3 charts/podiumd/scripts/fix-oidc-config.py path/to/gemeente/env/podiumd.yml --dry-run
python3 charts/podiumd/scripts/fix-oidc-config.py path/to/gemeente/env/podiumd.yml
```

---

## Changes

### Keycloak 26.6.1 → 26.6.2 → 26.6.3 (security)

The 4.7.x line bumps Keycloak twice. **4.7.3** moves the server + operator images to `26.6.2` (operator chart adfinis `1.11.4`), and **4.7.4** moves them to `26.6.3` (operator chart adfinis `1.12.0`, appVersion `26.6.3`).

- **26.6.2** (4.7.3) — account-takeover-class CVEs: CVE-2026-7504 (redirect URI bypass), CVE-2026-7507 (session fixation), CVE-2026-7571 (access-token disclosure), CVE-2026-37982/37979/37978, CVE-2026-4630/4628 (UMA), CVE-2026-33871/33870 (HTTP/2 DoS + smuggling), CVE-2026-37981/37980 (XSS), Bouncy Castle fixes. See <https://www.keycloak.org/2026/05/keycloak-2662-released>.
- **26.6.3** (4.7.4) — 16 CVEs, notably **CVE-2026-9704** (privilege escalation via token exchange), **CVE-2026-4874** (SSRF on the OIDC token endpoint), **CVE-2026-9802** (revoked-refresh-token replay after a server restart).

**Action required:** no values-file changes for gemeenten — the chart bumps the image tags + digests centrally. The ACR mirror must mirror the new `quay.io/keycloak/keycloak:26.6.3` and `keycloak-operator:26.6.3` tags + digests before rollout. Apply the `v2beta1` CRDs for the initial 26.6.x move (see above); the 26.6.2 → 26.6.3 step needs no CRD action.

> **Caveat — operator image digest pinning differs from every other image.** The
> operator image is rendered by the adfinis subchart as
> `repository:tag@sha256:{{ operator.image.sha }}` using a **separate `sha`
> field**. So the operator `tag` must be **just the version**:
>
> ```yaml
> keycloak-operator:
>   operator:
>     image:
>       tag: "26.6.3"        # NOT "26.6.3@sha256:…" (double digest → invalid ref)
> ```
>
> On ACR-mirror environments whose manifest digest differs from quay's, clear the
> `sha` to pin by tag only (`sha: ""`) — an env-level override; the shared
> `values.yaml` keeps the digest pin on.

### nginx-unprivileged 1.30.0 → 1.30.2 (security)

All nginx sidecars and the apiproxy now pin `nginxinc/nginx-unprivileged:1.30.2`:

- CVE-2026-42945 — "nginx Rift", critical RCE in the HTTP request parser (fixed 1.30.1).
- CVE-2026-9256 — buffer overflow in `ngx_http_rewrite_module` (medium, fixed 1.30.2).

**Action required:** no values-file changes. Mirror the new `nginxinc/nginx-unprivileged:1.30.2` tag + digest before rollout.

### Open Zaak sub-chart 1.13.1 → 1.14.1 + app 1.27.1 → 1.27.2 + configurable Documenten API storage backend

The Open Zaak sub-chart is bumped `1.13.1` → `1.14.1` (4.7.3), and the Open Zaak **application image** is pinned `1.27.1` → `1.27.2` (4.7.4 security release). Chart 1.14.1 introduces a configurable **Documenten API storage backend**; PodiumD sets none of the new keys, so the `filesystem` backend and disabled Cloud Events remain the default.

**4.7.4 security (1.27.2):**

- **CVE-2026-54657** (`GHSA-f29q-7rpr-jmjx`) — `/zaken/_zoek` and `/enkelvoudiginformatieobjecten/_zoek` results are now filtered by the token's authorizations (previously broken access control). Highest-impact fix.
- **`GHSA-x5cj-23hr-5r54`** — path-traversal hardening in document bulk import (restricted under `IMPORT_DOCUMENTEN_BASE_DIR`).

New Documenten API backend keys under `openzaak:` (object storage instead of a filesystem PV):

| Key | Default | Purpose |
|---|---|---|
| `openzaak.documentApiBackend` | `filesystem` | `filesystem`, `azure_blob_storage`, or `s3_storage`. |
| `openzaak.azureBlobStorage.*` | `""` / defaults | Azure Storage account, Entra ID creds, container, expiry, … |
| `openzaak.s3storage.*` | — | S3 backend (not supported in PodiumD). |
| `openzaak.enableCloudEvents` | `false` | Emit CloudEvents for Documenten API changes. |

**Action required:**

- **`/zoek` authorization fix** — no config; be aware a token that previously saw too many results now sees only authorized ones. Verify autorisaties are scoped as intended.
- **Document bulk import only** — `IMPORT_DOCUMENTEN_BASE_DIR` default changed from `BASE_DIR` to `<BASE_DIR>/import-data`; PodiumD doesn't set it, so no action unless you use bulk import (then keep it a subdir of `BASE_DIR`, files under `/app/import-data`).
- **Storage backend** — none to keep current behaviour; leave the keys unset.

> **WARNING — backend migration must be planned first.** Switching
> `openzaak.documentApiBackend` away from `filesystem` does **not** migrate
> existing documents — files on the filesystem PV become inaccessible the moment
> the backend changes. Plan and validate a data migration in a non-prod
> environment, keep the filesystem PV until the new backend is confirmed, and
> treat it as a separate migration project — never part of a routine upgrade.

### ITA 3.0.0 → 3.1.0

The interne taak-afhandeling image goes `3.0.0` → `3.1.0`. **No action required.**

### KISS: added Kennisbank role

Added the Kennisbank role to the KISS-client. **No action required.**

### ZAC image 4.7.1 → 4.7.2

The ZAC application image is updated `4.7.1` → `4.7.2` (helm chart stays `1.0.228`). **No action required.**

### Zaakbrug: new sub-chart

The Zaakbrug Frank!Framework console is added as a new sub-chart (`wearefrank/zaakbrug` 2.3.26, application image `1.26.13`). It runs in the `podiumd` namespace as Deployment `podiumd-zaakbrug`, Service `podiumd-zaakbrug:80` → container port `8080`. **Disabled by default** — set `zaakbrug.enabled: true` to use it.

**Action required (only if enabling).** Three parties must each do work before Zaakbrug comes up cleanly:

**1. SSC — Postgres database.** Create the `zaakbrug` database on the shared Postgres flexible server (same procedure as other component DBs): database `zaakbrug`, owner role `zaakbrug`, default privileges on `public`, `ssl: true`. **Provision at the minimum size** — it stores only Frank!Framework metadata + transient state.

**2. SSC — KeyVault secrets (terraform).** Add to the per-environment `keyvault.tfvars` `passwords` array:

| KeyVault secret | Used for | Pipeline env-var |
|---|---|---|
| `zaakbrug` | Postgres password for the `zaakbrug` DB user | `ZAAKBRUG_DATABASE_PASSWORD` |
| `zaakbrug-oauth-client-secret` | Keycloak `zaakbrug` client secret | `ZAAKBRUG_OAUTH_CLIENT_SECRET` |
| `zaakbrug-zaken-api-jwt-password` | JWT password for Zaakbrug's Zaken-API credentials | `ZAAKBRUG_ZAKEN_API_JWT_PASSWORD` |

**3. Customer (gemeente) — DNS.** Create a CNAME for the Zaakbrug hostname (default `<env>-zaakbrug.<gemeente-domain>`) pointing at the **Azure Application Gateway load balancer** that terminates cluster ingress. cert-manager issues the TLS cert once the CNAME resolves.

**4. Deploy pipeline — add the wearefrank helm repo** before the dependency step:

```bash
helm repo add wearefrank https://wearefrank.github.io/charts --force-update
helm repo update
```

### MI exports — weekly Postgres dumps over SFTP

PodiumD 4.7.3 ships the first iteration of **Management Information (MI) data exports** — weekly per-component Postgres dumps over SFTP (IN-1650 + IN-2119). One `mi-export-<component>` CronJob per enabled Postgres-backed app; output `csv` (default) or `pgdump` via `mi.format`; SFTP-only egress with an SSH keypair. **Disabled by default.**

Full operator docs: [`docs/podiumd/mi-exports.md`](../../../docs/podiumd/mi-exports.md).

**Action required (only if enabling):** provision the SFTP target + gemeente public key, store the private key in Key Vault (`mi-data-sftp-rsa-private-key`), then:

```yaml
mi:
  enabled: true
  gemeente: <env-name>
  sftp:
    host: sftp.example.com
    user: miuser
    remotePath: /mi-exports
    privateKey: "REP_MI_DATA_SFTP_RSA_PRIVATE_KEY_REP"  # pipeline substitutes from KV
```

### Open Archiefbeheer — add Objecten + OpenKlant services

For Open Archiefbeheer 2.0.0 you must add Objecten and Open Klant services in OAB.

**Action required.** Add 2 secrets to each gemeente's Key Vault:

```
OBJECTEN_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN:   $(objecten-credentials-openarchiefbeheer-token)
OPENKLANT_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN:  $(openklant-credentials-openarchiefbeheer-token)
```

Then add token-auth in Objecten and Open Klant, and the two services in OAB. See the [`external_registers` matching](#open-archiefbeheer-external_registers-must-match-the-zgw_consumers-service-identifiers) section below for the exact-identifier requirement — the `services_identifiers` in `external_registers` must equal the `zgw_consumers.services[].identifier` values (commonly `objecten-api` and `openklant-api`).

### Datamigratie Keycloak client + Open Zaak secret

Datamigratie deploys in a separate pipeline but needs a connection to Open Zaak and a Keycloak client for user login. The chart includes both (4.7.4).

**Action required.** Verify these secrets exist in Key Vault (add if missing):

```
OPENZAAK_CREDENTIALS_DATAMIGRATIE_SECRET:   $(openzaak-credentials-datamigratie-secret)
DATAMIGRATIE_OIDC_SECRET:                   $(datamigratie-oidc-secret)
```

Then add the Datamigratie Keycloak client and the Open Zaak application/credential in each gemeente `podiumd.yml`:

```yaml
keycloak:
  config:
    clients:
      datamigratie:
        name: Datamigratie
        enabled: true
        secret: "REP_DATAMIGRATIE_OIDC_SECRET_REP"
        oidcUrl: "https://datamigratie.example.nl"
openzaak:
  configuration:
    data: |
      vng_api_common_credentials:
        items:
          - identifier: datamigratie
            secret: "REP_OPENZAAK_CREDENTIALS_DATAMIGRATIE_SECRET_REP"
      vng_api_common_applicaties_config_enable: true
      vng_api_common_applicaties:
        items:
          - uuid: dc69a5f8-c00a-4302-ada5-c67beddbc65c
            client_ids:
              - datamigratie
            heeft_alle_autorisaties: true
            label: Datamigratie
```

### Open Archiefbeheer `external_registers` must match the `zgw_consumers` service identifiers

> **Heads-up / action required — verify before upgrading.** (Introduced 4.7.4; example completed/corrected in 4.7.6.)

Open Archiefbeheer's `external_registers:` block references services **by their identifier string**. Each register (`openklant`, `objecten`) lists `services_identifiers`, and OAB resolves the register by an **exact** match against the identifiers under `zgw_consumers.services`. There is no fuzzy matching, so any mismatch silently breaks that register's link.

- **Open Klant** — in **most** PodiumD environments this service was provisioned as **`openklant-api`**, *not* `openklant-klantinteracties`. A mismatch cannot be resolved.
- **Objecten** — same rule; the register's `services_identifiers` must match the Objecten service identifier (e.g. **`objecten-api`**).

Working example (the `services_identifiers` values must be **identical** to the matching `zgw_consumers.services` `identifier`):

```yaml
openarchiefbeheer:
  configuration:
    data: |-
      zgw_consumers_config_enable: true
      zgw_consumers:
        services:
        - identifier: objecten-api            # <-- referenced below
          label: Objecten API
          api_root: https://objecten.example.com/api/v2/
          api_type: orc
          auth_type: api_key
          header_key: Authorization
          header_value: "Token REP_OBJECTEN_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP"
        - identifier: openklant-api           # <-- NOT openklant-klantinteracties
          label: Klanten API
          api_root: https://openklant.example.com/klantinteracties/api/v1/
          api_type: kc
          auth_type: api_key
          header_key: Authorization
          header_value: "Token REP_OPENKLANT_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP"

      external_registers_enabled: true
      external_registers:
        openklant:
          enabled: true
          services_identifiers:
          - openklant-api                     # must equal the service identifier above
        objecten:
          enabled: true
          services_identifiers:
          - objecten-api                      # must equal the service identifier above
```

**Action required:**

1. Find the identifiers of the Open Klant and Objecten services provisioned in your environment (`zgw_consumers.services[].identifier`, commonly `openklant-api` and `objecten-api`).
2. Make every entry under `external_registers.*.services_identifiers` use **those exact identifiers**.
3. Re-run the `openarchiefbeheer-config` Job (`helm upgrade`) and confirm both registers resolve.

Do not assume the example values are correct — check the per-gemeente `podiumd.yml` against what is actually provisioned. See [`openarchiefbeheer-known-issues.md`](openarchiefbeheer-known-issues.md) for other OAB traps.

### Open Beheer ↔ Objecttypen API token (IN-2345)

Open Beheer reads object types from the **Objecttypen API** and authenticates with an API token. Configure it **on both sides with the exact same secret**, `REP_OBJECTTYPEN_OPENBEHEER_TOKEN_REP` (Key Vault `objecttypen-openbeheer-token`, pipeline var `OBJECTTYPEN_OPENBEHEER_TOKEN`):

- **Objecttypen** — a `tokenauth` item granting Open Beheer the token (`token: {value_from: {env: objecttypen_openbeheer_token}}`).
- **Open Beheer** — the `objecttypen-service` consumer header: `header_value: "Token REP_OBJECTTYPEN_OPENBEHEER_TOKEN_REP"`. The `Token ` prefix is **required**.

**What IN-2345 fixed (do not repeat):**

- **Missing `Token ` prefix** on the Open Beheer header — Objecttypen rejects a header without it.
- **Mismatched secret name** (`OPENBEHEER_CREDENTIALS_OBJECTTYPEN_TOKEN` vs `OBJECTTYPEN_OPENBEHEER_TOKEN`) — standardise on **`OBJECTTYPEN_OPENBEHEER_TOKEN`**.

**Action required:**

1. Provision `objecttypen-openbeheer-token` in Key Vault and map it to `OBJECTTYPEN_OPENBEHEER_TOKEN` in the pipeline `application.yml` **in the shared/objecttypen section**.
2. **Only enable the objecttypen `openbeheer` tokenauth entry when Open Beheer is enabled and the secret is provisioned** — the `objecttypen-config` Job fails on an unsubstituted `REP_..._REP` placeholder; keep it commented while openbeheer is disabled.
3. Configure both sides with the same secret and re-run the upgrade; confirm Open Beheer can list object types (no 401/403).

### Open Formulieren — outgoing request logging (4.7.4 → 4.7.6)

4.7.4 disabled Open Formulieren outgoing/external HTTP request logging by default (`LOG_OUTGOING_REQUESTS=False` in `openformulieren.extraEnvVars`). **4.7.6 reverts this** — the override is removed and Open Formulieren returns to the upstream default (`LOG_OUTGOING_REQUESTS=True`, logging enabled). Net effect for a 4.6.8 → 4.7.6 upgrade: **outgoing-request logging is ON**.

> Open Inwoner has no equivalent master switch (v2.1.2 exposes only `LOG_OUTGOING_REQUESTS_DB_SAVE`); it is unchanged. See [`openinwoner-outgoing-request-logging.md`](openinwoner-outgoing-request-logging.md).

**Action required:** none if logging outgoing requests is acceptable. To **keep it disabled**, add the opt-out in the gemeente `podiumd.yml`:

```yaml
openformulieren:
  extraEnvVars:
    - name: LOG_OUTGOING_REQUESTS
      value: "False"
```

With logging on, DB persistence is gated as normal by `LOG_OUTGOING_REQUESTS_DB_SAVE` (default `False`) and the runtime `OutgoingRequestsLogConfig.save_to_db` admin toggle.

### ZGW Office Add-in v0.9.289 → v0.9.313 (4.7.5)

- `zgw-office-addin` chart dependency `0.0.87` → `0.0.88`.
- Frontend + backend images bumped to `v0.9.313` (digest-pinned).
- **Image repository names changed** `…-add-in-…` → `…-addin-…`:
  - `ghcr.io/infonl/zgw-office-addin-frontend`
  - `ghcr.io/infonl/zgw-office-addin-backend`

**Action required:** standard image-pin update (already in `values.yaml`). **ACR-mirror environments:** because the repo names changed from `add-in` to `addin`, mirror the **new** repository names/tags at `v0.9.313` — a mirror of the old `add-in` repos will not be used by the new pins. No config/schema/migration changes.

---

## Optional configuration blocks

All blocks below are **opt-in** — defaults are unchanged. Add to gemeente `podiumd.yml` only when wanted.

- **OpenZaak — Azure Blob Storage for Documenten API** — see the Open Zaak section above and its migration warning. Default remains `filesystem`.
- **Open Archiefbeheer — destruction plugins for external registers** — `external_registers_enabled: true` + per-register `services_identifiers` (see the matching section above).
- **Open Archiefbeheer — post-destruction visibility period** — `openarchiefbeheer.settings.postDestructionVisibilityPeriod: "7"`.
- **Open Archiefbeheer — disable related-object counts** — `openarchiefbeheer.settings.relatedCountDisabled: true`.
- **APISIX — egress API gateway (opt-in, IN-1867)** — `apisix.enabled: false` by default; see [`apisix-egress-gateway.md`](apisix-egress-gateway.md).

---

## Component changelogs (no action required)

- **Keycloak 26.6.x** — security releases (see CVE lists above).
- **OpenZaak 1.27.1 → 1.27.2** — `/zoek` authorization filtering + bulk-import path-traversal hardening (see above); 1.27.1 archiving/deprecation notes carried from 4.7.3.
- **ZAC 4.7.x (chart 1.0.228)** — native Gotenberg (`gotenberg/gotenberg:8.31.0`) replaces `kontextwork-converter`; container port `8080` → `3000`.
- **Open Formulieren 3.4.9** — validation/StUF-ZDS fixes, SDK 3.4.3, security patches; outgoing-request logging on by default as of 4.7.6.
- **Open Archiefbeheer 2.0.0** — ⚠️ breaking; see Required manual steps + `migrate-openarchiefbeheer-2.0.0.py`.
- **Open Beheer chart 0.1.3** — `SESSION_COOKIE_AGE` configmap fix; optional `OPEN_ZAAK_ADMIN_BASE_URL`.
- **Object Types API 3.4.2 / Referentielijsten API 0.7.2** — security dependency updates.
- **OMC (NotifyNL) 1.17.19 / chart 0.14.1** — `/callback` returns HTTP 202 when the reference field is empty.
- **ZGW Office Add-in v0.9.313 / chart 0.0.88** — dependency updates + repo rename `add-in` → `addin`.
- **Open Inwoner 2.1.2** — stable release (unchanged across this range; never use `2.1.2-rc1`).

---

## See also

- [`values-changes-4.7.0.md`](values-changes-4.7.0.md) — full table of values to add/change/remove for the 4.7.0 jump.
- Granular per-release notes: [4.7.0→4.7.1](upgrade-from-4.7.0-to-4.7.1.md), [4.7.1→4.7.2](upgrade-from-4.7.1-to-4.7.2.md), [4.7.2→4.7.3](upgrade-from-4.7.2-to-4.7.3.md), [4.7.3→4.7.4](upgrade-from-4.7.3-to-4.7.4.md).
- Next hop: [`upgrade-from-4.7.6-to-4.8.0.md`](upgrade-from-4.7.6-to-4.8.0.md).
- Images: `images-4.7.0.yaml` … `images-4.7.5.yaml` under [`docs/images/`](images/).
