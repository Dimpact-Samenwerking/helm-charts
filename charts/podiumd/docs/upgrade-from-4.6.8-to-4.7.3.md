# Upgrade guide: PodiumD 4.6.8 → 4.7.3

> **Consolidated guide.** This is a single official-path hop that folds the
> 4.7.x release line (4.7.0, 4.7.1, 4.7.2, 4.7.3) into one document. See
> [`UPGRADING.md`](UPGRADING.md) for the full upgrade path. The granular
> per-release notes are kept alongside for reference:
> [4.7.0→4.7.1](upgrade-from-4.7.0-to-4.7.1.md),
> [4.7.1→4.7.2](upgrade-from-4.7.1-to-4.7.2.md),
> [4.7.2→4.7.3](upgrade-from-4.7.2-to-4.7.3.md).
>
> **Open Inwoner stays on stable `2.1.2`** for the whole 4.6.8 → 4.7.3 range —
> it does not change. The `2.1.2-rc1` release candidate is **never** part of
> this path; do not pin it.
>
> See the Confluence Releases page for the agreed application targets:
> <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.

## Component versions (target 4.7.3)

| Component | App version | Helm chart |
|---|---|---|
| Keycloak | 26.6.2 | adfinis 1.11.4 |
| OpenZaak | 1.27.1 | 1.14.1 |
| ZAC | 4.7.2 | 1.0.228 |
| Open Formulieren | 3.4.9 | 1.12.0 |
| Open Archiefbeheer | 2.0.0 | 2.0.0 (⚠️ breaking) |
| Open Beheer | 0.9.0 | 0.1.3 |
| Open Inwoner | 2.1.2 (stable — unchanged from 4.6.8) | 2.1.3 |
| Object Types API | 3.4.2 | 1.6.1 |
| Referentielijsten API | 0.7.2 | 0.1.1 |
| OMC (NotifyNL) | 1.17.19 | 0.14.1 |
| ZGW Office Add-in | v0.9.289 | 0.0.87 |
| ITA (interne taak-afhandeling) | 3.1.0 | — |
| nginx-unprivileged (api-proxy + Maykin/ZAC sidecars) | 1.30.2 | — |
| Zaakbrug (opt-in) | 1.26.13 | wearefrank 2.3.26 |
| APISIX (egress gateway, opt-in) | 3.16.0 | 2.14.0 |

> Open Inwoner is already on stable `2.1.2` at 4.6.8 and remains there through
> 4.7.3. There is no rc1 step on this path.

---

## Required manual steps

### Before upgrading

1. **Quiesce Open Archiefbeheer** — ensure no destruction lists are processing or waiting for retry. The internal data structure for tracking destruction has been reworked; lists in-flight during the upgrade may end up in an inconsistent state.
2. **Update the ACR mirror for ZAC office_converter** — `acrprodmgmt.azurecr.io/office-converter` must be updated to mirror `gotenberg/gotenberg:8.31.0` instead of `ghcr.io/eugenmayer/kontextwork-converter`. Without this, environments overriding `zac.office_converter.image.repository` will fail to pull the image.
3. **Apply Keycloak `v2beta1` CRDs** (see [Keycloak CRD upgrade](#keycloak-crd-upgrade-v2alpha1--v2beta1)). Required because the chart bumps the operator image to `26.6.x` while the bundled adfinis subchart `1.11.4` still ships `v2alpha1` CRDs from appVersion `26.5.6`. The operator queries `v2beta1` and will `CrashLoopBackOff` until the upgraded CRDs are applied.
4. **Set `apiproxy.nginxCertsSecret` explicitly** if your environment uses upstream mTLS via the api-proxy and you have not already pinned it. The chart default is `""` (empty); environments that relied on the implicit `"api-proxy-certs"` default must pin the value in `podiumd.yml` **before** the upgrade or the cert volume mount disappears and upstream calls fall back to non-mTLS with `proxy_ssl_verify off`.
5. **Run the migration scripts** (see [Migration scripts](#migration-scripts)).
6. **Update the ACR mirror** for the new security-release image tags + digests: `keycloak`/`keycloak-operator` `26.6.2`, `nginx-unprivileged` `1.30.2` (see [`docs/images/images-4.7.2.yaml`](images/images-4.7.2.yaml) and [`images-4.7.3.yaml`](images/images-4.7.3.yaml)).
7. **Add Open Archiefbeheer ↔ Objecten/OpenKlant secrets** (4.7.3, see [Open Archiefbeheer — add Objecten + OpenKlant services](#open-archiefbeheer--add-objecten--openklant-services)).
8. **Zaakbrug prerequisites** — only if enabling `zaakbrug.enabled: true` (see [Zaakbrug: new sub-chart](#zaakbrug-new-sub-chart)): Postgres DB, Key Vault secrets, DNS CNAME, and the `wearefrank` helm repo.

### After upgrading

9. **Reconfigure the destruction report settings** in the Open Archiefbeheer admin interface. The destruction report configuration page has been reworked; existing settings are not migrated automatically.

---

## Keycloak CRD upgrade (`v2alpha1` → `v2beta1`)

The chart pins `keycloak-operator` to image `quay.io/keycloak/keycloak-operator` at `26.6.x` (see `values.yaml`), but the adfinis subchart `keycloak-operator-1.11.4` (appVersion `26.5.6`) ships the older `v2alpha1` CRDs. The operator issues informer queries against `apis/k8s.keycloak.org/v2beta1/...`.

### Apply procedure

Use the helper script (`charts/podiumd/scripts/install-keycloak-operator-crds.sh`). It defaults to the upstream Keycloak `v1` CRD manifests at the right Keycloak version and applies them server-side:

```bash
CTX=<your-aks-context>
NS=<keycloak-namespace>      # e.g. podiumd

# 1. Snapshot existing CRs (rollback insurance)
kubectl --context "$CTX" -n "$NS" get keycloak,keycloakrealmimport -o yaml > /tmp/kc-backup-$(date +%s).yml

# 2. Install upstream CRDs (adds v2beta1, keeps v2alpha1 deprecated/served)
charts/podiumd/scripts/install-keycloak-operator-crds.sh \
  --context "$CTX" --keycloak-version 26.6.2

# 3. Restart the operator so it re-establishes informers
kubectl --context "$CTX" -n "$NS" rollout restart deploy keycloak-operator

# 4. Migrate stored CRs to v2beta1 storage version (read + re-apply triggers re-serialization)
kubectl --context "$CTX" -n "$NS" get keycloak,keycloakrealmimport -o yaml \
  | kubectl --context "$CTX" apply -f -
```

The script accepts `--dry-run` to inspect the CRD YAML, `--keycloak-version` to pin to a specific Keycloak release, and `--source chart --chart-version 1.11.4` to fall back to the adfinis subchart CRDs.

- Upstream CRDs declare both versions:
  - `v2beta1`: `served: true`, `storage: true`
  - `v2alpha1`: `served: true`, `storage: false`, `deprecated: true`, `deprecationWarning: "Please migrate to v2beta1"`
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

Per-location values take precedence over the global; the global takes precedence over the chart default of `6`.

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

> **Note on PKCE.** OAB 2.0.0 ships with `mozilla-django-oidc-db 1.1.1`, whose `setup_configuration` schema does NOT accept `oidc_use_pkce` at item or provider level (`extra_forbidden` validation error from pydantic). Do not add this field for OAB. `openarchiefbeheer.configuration.pkceEnabled` is a no-op. If a previous (buggy) run of the migration script left `oidc_use_pkce: false` in your `openarchiefbeheer.configuration.data`, remove the line manually or re-run the migration script — the current version explicitly strips the field via `yq del`.

### `migrate-zac-4.7.0.py` — ZAC office_converter image rename

Only relevant if a gemeente values file overrides `zac.office_converter.image.repository`. Without an override, the chart `values.yaml` already points to `gotenberg/gotenberg:8.31.0` and no rewrite is needed. The script handles both `acrprodmgmt.azurecr.io` and `acrtestmgmt.azurecr.io`. The chart-level `containerPort` change (8080 → 3000) lives in the base `values.yaml` and does not need a per-environment edit unless overridden.

```bash
python3 charts/podiumd/scripts/migrate-zac-4.7.0.py --dry-run   # preview
python3 charts/podiumd/scripts/migrate-zac-4.7.0.py             # apply to all gemeente files
```

### `fix-oidc-config.py` — generic OIDC migration sweep

Catch-all for any component using `mozilla-django-oidc-db ≥ 1.x`: openzaak, opennotificaties, objecten, objecttypen, openklant, openformulieren, openarchiefbeheer. Skips `openinwoner` (still flat format) automatically. Requires `ruamel.yaml` (preferred — preserves comments/quotes) or `PyYAML` as fallback.

```bash
python3 charts/podiumd/scripts/fix-oidc-config.py values-<gemeente>.yml --dry-run   # writes nothing
python3 charts/podiumd/scripts/fix-oidc-config.py values-<gemeente>.yml             # in-place migrate
```

The script processes every literal block scalar (`data: |` / `data: |-`) that contains `oidc_db_config_admin_auth` and leaves the rest of the file untouched. It does **not** strip deprecated keys (`oidc_rp_scopes_list`, `userinfo_claims_source`) — for openarchiefbeheer, run `migrate-openarchiefbeheer-2.0.0.py` first or alongside.

#### Recommended order for openarchiefbeheer

```bash
# 1. Preview
python3 charts/podiumd/scripts/migrate-openarchiefbeheer-2.0.0.py --dry-run
# 2. Apply to all gemeente podiumd.yml files
python3 charts/podiumd/scripts/migrate-openarchiefbeheer-2.0.0.py
# 3. Sweep for any remaining flat-format OIDC blocks in other components
python3 charts/podiumd/scripts/fix-oidc-config.py path/to/gemeente/env/podiumd.yml --dry-run
python3 charts/podiumd/scripts/fix-oidc-config.py path/to/gemeente/env/podiumd.yml
```

---

## Changes

### Keycloak 26.6.1 → 26.6.2 (security release)

Upstream Keycloak 26.6.2 ships fixes for a substantial set of CVEs, including several account-takeover-class issues. Both the Keycloak server image and the keycloak-operator image are bumped to `26.6.2` with refreshed digests; the operator chart (Adfinis 1.11.4) is unchanged.

CVEs addressed:

- CVE-2026-7504 — Redirect URI validation bypass
- CVE-2026-7507 — OIDC session fixation leading to account takeover
- CVE-2026-7571 — Access token disclosure / implicit-flow bypass via forged client data
- CVE-2026-37982 — Execute-actions token replay allows unauthorized WebAuthn credential enrollment
- CVE-2026-37979 — OIDC introspection endpoint does not enforce audience restriction
- CVE-2026-37978 — Cross-role PII leakage via evaluate-scopes
- CVE-2026-4630 — UMA Protection API IDOR
- CVE-2026-37981 — PII enumeration via account user lookup
- CVE-2026-33871 — HTTP/2 CONTINUATION frame flood DoS
- CVE-2026-33870 — HTTP request smuggling
- CVE-2026-4628 — UMA broken access control
- CVE-2026-37980 — Stored XSS
- Bouncy Castle cryptographic fixes

See <https://www.keycloak.org/2026/05/keycloak-2662-released>.

**Action required:** no values-file changes for gemeenten — the chart bumps the image tag and digest centrally. The ACR mirror must mirror the new `quay.io/keycloak/keycloak:26.6.2` and `keycloak-operator:26.6.2` tags + digests before rolling out.

### nginx-unprivileged 1.30.0 → 1.30.2 (security release)

All nginx sidecars and the apiproxy now pin `nginxinc/nginx-unprivileged:1.30.2`. The 1.30.x stable line gained two security fixes:

- CVE-2026-42945 — "nginx Rift", critical RCE in the HTTP request parser, fixed in 1.30.1.
- CVE-2026-9256 — buffer overflow in `ngx_http_rewrite_module` (medium), fixed in 1.30.2.

**Action required:** no values-file changes. The ACR mirror must mirror the new `nginxinc/nginx-unprivileged:1.30.2` tag and digest before rollout.

### Open Zaak sub-chart 1.13.1 → 1.14.1 + configurable Documenten API storage backend

The Open Zaak sub-chart is bumped from `1.13.1` to `1.14.1` (sub-chart default `appVersion` moves 1.26.0 → 1.28.1; PodiumD keeps the Open Zaak **application image pinned at 1.27.1**, so the running app version does not change). Chart 1.14.1 introduces a configurable **Documenten API storage backend**. PodiumD does not set any of these keys, so the chart defaults apply and behaviour is unchanged (documents keep using the existing `filesystem` backend, Cloud Events stay disabled).

New configuration options exposed under `openzaak:` (useful for production environments that want object storage instead of a filesystem PersistentVolume):

| Key | Default | Purpose |
|---|---|---|
| `openzaak.documentApiBackend` | `filesystem` | Storage backend. One of: `filesystem`, `azure_blob_storage`, `s3_storage`. |
| `openzaak.azureBlobStorage.accountName` | `""` | Azure Storage account name. |
| `openzaak.azureBlobStorage.clientId` | `""` | Entra ID client id (workload identity / service principal). |
| `openzaak.azureBlobStorage.clientSecret` | `""` | Entra ID client secret. |
| `openzaak.azureBlobStorage.tenantId` | `""` | Entra ID tenant id. |
| `openzaak.azureBlobStorage.container` | `openzaak` | Blob container name. |
| `openzaak.azureBlobStorage.location` | `documenten` | Path/prefix within the container. |
| `openzaak.azureBlobStorage.connectionTimeout` | `5` | Connection timeout (seconds). |
| `openzaak.azureBlobStorage.apiStorageVersion` | `""` | Pin a specific Azure Storage API version (optional). |
| `openzaak.azureBlobStorage.urlExpirationTime` | `60` | Signed-URL expiry (seconds). |
| `openzaak.s3storage.*` | — | S3 backend (access key, bucket, region, endpoint, …). S3 is not supported in PodiumD. |
| `openzaak.enableCloudEvents` | `false` | Emit CloudEvents for Documenten API changes. |
| `openzaak.notificationsSource` | `openzaak` | `source` attribute on emitted CloudEvents. |

**Action required:** none to stay on the current behaviour — leave these keys unset and the `filesystem` backend continues to be used.

> **WARNING — backend migration must be investigated and performed first.**
> Switching `openzaak.documentApiBackend` away from `filesystem` to
> `azure_blob_storage` or `s3_storage` does **not** migrate existing
> documents. Files already written to the filesystem PersistentVolume become
> **inaccessible** to the Documenten API the moment the backend is changed,
> and newly stored files go only to the new backend. Before flipping the
> backend in production you MUST: (1) investigate the current document volume
> and target object-store capacity/permissions; (2) plan and validate a
> data-migration path that copies all existing files into the target,
> preserving the keys/paths Open Zaak expects; (3) execute and verify the
> migration (read-back checks) in a non-production environment first; (4) only
> then change the backend and roll out, with a tested rollback (keep the
> filesystem PV until the new backend is confirmed good). Treat this as a
> separate, planned migration project — never as part of a routine upgrade.

### ITA 3.0.0 → 3.1.0

The interne taak-afhandeling (ITA) image goes from `3.0.0` to `3.1.0`. **No action required.**

### KISS: added Kennisbank role

Added the Kennisbank role to the KISS-client. **No action required.**

### ZAC image 4.7.1 → 4.7.2

The ZAC application image is updated from `4.7.1` to `4.7.2` (helm chart stays `1.0.228`). **No action required.**

### Zaakbrug: new sub-chart

The Zaakbrug Frank!Framework console is added as a new sub-chart (`wearefrank/zaakbrug` 2.3.26, application image `1.26.13`). It runs in the `podiumd` namespace as Deployment `podiumd-zaakbrug`, Service `podiumd-zaakbrug:80` → container port `8080`. Default JVM heap is `Xms=Xmx=4G` (`zaakbrug.frank.memory.{minimum,maximum}`); umbrella values set matching K8s resource requests/limits (`5Gi`/`6Gi` memory, `250m`/`2` CPU). **Disabled by default** — environments that need it set `zaakbrug.enabled: true`.

**Action required (only if enabling).** Three parties must each do work before Zaakbrug will come up cleanly:

**1. SSC — Postgres database.** Create the `zaakbrug` database on the shared Postgres flexible server in the **normal fashion** (same procedure as the other PodiumD component databases):

- Database name: `zaakbrug`; owner role: `zaakbrug`; default privileges on the role for `public` schema; `ssl: true`.
- **Provision at the minimum possible size** — Zaakbrug stores only Frank!Framework metadata + transient message-processing state. Scale up later from observed usage only if needed.

The chart sets `zaakbrug.connections.jdbc[0]` to point at the shared Postgres host with database `zaakbrug` / user `zaakbrug`; the password comes from the KeyVault secret below.

**2. SSC — KeyVault secrets (terraform).** Add to the per-environment `keyvault.tfvars` `passwords` array:

| KeyVault secret name | Used for | Pipeline env-var binding |
|---|---|---|
| `zaakbrug` | Postgres password for the `zaakbrug` DB user | `ZAAKBRUG_DATABASE_PASSWORD` |
| `zaakbrug-oauth-client-secret` | Keycloak `zaakbrug` client secret (Frank!Framework console SSO + KC realm-config seed) | `ZAAKBRUG_OAUTH_CLIENT_SECRET` |
| `zaakbrug-zaken-api-jwt-password` | JWT password for Zaakbrug's Zaken-API outbound credentials | `ZAAKBRUG_ZAKEN_API_JWT_PASSWORD` |

The values file already references these via `REP_ZAAKBRUG_DATABASE_PASSWORD_REP`, `REP_ZAAKBRUG_OAUTH_CLIENT_SECRET_REP` and `REP_ZAAKBRUG_ZAKEN_API_JWT_PASSWORD_REP` placeholders, which `patch_values.py` substitutes at deploy time.

**3. Customer (gemeente) — DNS.** Create a CNAME for the Zaakbrug hostname (default pattern `<env>-zaakbrug.<gemeente-domain>`, e.g. `ontw-zaakbrug.dimpact.nl`) pointing at the **Azure Application Gateway load balancer** that terminates ingress traffic for the cluster. Without the DNS record, the Gateway API HTTPRoute (`hr-zaakbrug-nginx` on `public-gateway`) has no externally reachable hostname and OAuth2 callbacks from Keycloak will fail. The TLS certificate is issued automatically by cert-manager once the CNAME resolves.

**4. Deploy pipeline — add the wearefrank helm repo.** Any pipeline that runs `helm dependency build|update` / `helm install|upgrade` against this umbrella chart **must register the wearefrank helm repository** before the dependency step:

```bash
helm repo add wearefrank https://wearefrank.github.io/charts --force-update
helm repo update
```

### MI exports — weekly Postgres dumps over SFTP

PodiumD 4.7.3 ships the first iteration of **Management Information (MI) data exports** — weekly per-component Postgres dumps uploaded over SFTP ([IN-1650](https://dimpact.atlassian.net/browse/IN-1650) + [IN-2119](https://dimpact.atlassian.net/browse/IN-2119)).

Highlights:

- One `mi-export-<component>` CronJob per enabled Postgres-backed app (openzaak, opennotificaties, objecten, …, zac, kiss, pabc — 14 default targets, each gated on the component's own `enabled` flag).
- Two output formats, env-wide via `mi.format`: `csv` (default — one `.tar.gz` per component, `;`-separated CSV per table with header row) or `pgdump` (one `pg_dump -Fc` file per component, for DR / restore).
- Egress is **SFTP only** (no blob storage). Auth via an SSH keypair. Host-key checking is intentionally **disabled** (`StrictHostKeyChecking=no`, `UserKnownHostsFile=/dev/null`): the jobs are short-lived single-shot containers reaching a DNS-fixed host and the private key already gates login.
- **The chart renders both SFTP Secrets itself** from `mi.sftp.*` values (`mi-export-sftp` connection envvars + `mi-export-sftp-key` private key) — nothing is pre-provisioned. The private key is supplied via `mi.sftp.privateKey`; the `application.yml` pipeline substitutes it from Azure Key Vault (`mi-data-sftp-rsa-private-key`) at deploy time.
- 20 GiB scratch budget on `/tmp` (`emptyDir.sizeLimit` plus matching `ephemeral-storage` requests/limits).

Full operator documentation: [`docs/podiumd/mi-exports.md`](../../../docs/podiumd/mi-exports.md).

**Action required: disabled by default** — fully opt-in. To enable in an env:

1. **Provision the SFTP target side**: a reachable SFTP server with the gemeente's SSH public key in `authorized_keys`. No `known_hosts` capture is needed.
2. **Store the SSH private key in Key Vault** as `mi-data-sftp-rsa-private-key`.
3. **Set values** in the env's values file:
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
4. Validate per the [§ Validation](../../../docs/podiumd/mi-exports.md#4-validation) section of the operator doc.

> **Note on Azure Blob SFTP targets:** if the SFTP user's `homeDirectory` is a blob container, the user is chrooted into it — set `mi.sftp.remotePath` to a path *inside* that container (e.g. `/mi-exports`), not `/<container>/...`.

### Open Archiefbeheer — add Objecten + OpenKlant services

No new image, but for Open Archiefbeheer 2.0.0 it is necessary to add services for Objecten and Open Klant in Open Archiefbeheer.

**Action required.** Add 2 new secrets to the keyvault of each gemeente:

```
OBJECTEN_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN:   $(objecten-credentials-openarchiefbeheer-token)
OPENKLANT_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN:  $(openklant-credentials-openarchiefbeheer-token)
```

Update `podiumd.yml` for each gemeente to configure the Services to Objecten and Open Klant.

- In Objecten, add Token Auth for OpenArchiefbeheer:

```yaml
objecten:
  configuration:
    data: |
      tokenauth_config_enable: true
      tokenauth:
        items:
          - identifier: openarchiefbeheer
            token: "REP_OBJECTEN_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP"
            contact_person: Dimpact
            email: servicedesk@dimpact.nl
```

- In Open Archiefbeheer, add 2 services for Objecten and OpenKlant:

```yaml
openarchiefbeheer:
  configuration:
    data: |
      zgw_consumers_config_enable: true
      zgw_consumers:
        services:
        - identifier: objecten-api
          label: Objecten API
          api_root: https://objecten.example.com/api/v2/
          api_type: orc
          auth_type: api_key
          header_key: Authorization
          header_value: "Token REP_OBJECTEN_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP"
        - identifier: klanten-api
          label: Klanten API
          api_root: https://openklant.example.com/klantinteracties/api/v1/
          api_type: kc
          auth_type: api_key
          header_key: Authorization
          header_value: "Token REP_OPENKLANT_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP"
```

- In Open Klant, add Token Auth for OpenArchiefbeheer:

```yaml
openklant:
  configuration:
    data: |
      tokenauth_config_enable: true
      tokenauth:
        items:
          - identifier: openarchiefbeheer
            token: "REP_OPENKLANT_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP"
            contact_person: Dimpact
            email: servicedesk@dimpact.nl
```

---

## Optional configuration blocks (4.7.0)

All blocks below are **opt-in** — defaults are unchanged. Add to gemeente `podiumd.yml` only when wanted.

### OpenZaak — Azure Blob Storage for Documenten API

See the [Open Zaak sub-chart](#open-zaak-sub-chart-1131--1141--configurable-documenten-api-storage-backend) section above and its migration warning. The default remains `filesystem`.

### Open Archiefbeheer — destruction plugins for external registers

Two new plugins allow destroying related resources in external systems when a destruction list is executed (Object API plugin, OpenKlant plugin):

```yaml
openarchiefbeheer:
  configuration:
    data: |-
      external_registers_enabled: true
      external_registers:
        openklant:
          enabled: true
          services_identifiers:
            - openklant-klantinteracties
        objecten:
          enabled: true
          services_identifiers:
            - objecten-api
```

### Open Archiefbeheer — post-destruction visibility period

Days that destroyed lists remain visible in the kanban view (default: 7).

```yaml
openarchiefbeheer:
  settings:
    postDestructionVisibilityPeriod: "7"
```

### Open Archiefbeheer — disable related-object counts

Reduce load on external registers (Open Zaak, Selectielijst) by disabling inline counts of related objects.

```yaml
openarchiefbeheer:
  settings:
    relatedCountDisabled: true
```

### APISIX — egress API gateway (opt-in, IN-1867)

New egress API gateway. **Disabled by default** (`apisix.enabled: false`) — existing environments are unaffected. To opt in, see [`apisix-egress-gateway.md`](apisix-egress-gateway.md) for the full setup.

---

## Component changelogs (no action required)

- **Keycloak 26.6.x** — security releases (see CVE lists above); endpoints open during initialization (PodiumD already sets `health-enabled: true`); stricter client-URI validation only if the `secure-client-uris` executor is manually enabled.
- **OpenZaak 1.27.1** — no breaking changes. Archiving recalculation for `afleidingswijze=vervaldatum_besluit`/`eigenschap`; `Zaak.relevanteAndereZaken` deprecated in favour of experimental `gerelateerdeZaken`; bug fixes (document download 500s, `/zaaknotities` PATCH, admin audit trail).
- **ZAC 4.7.x (chart 1.0.228)** — native **Gotenberg** (`gotenberg/gotenberg:8.31.0`) replaces `kontextwork-converter`; container port `8080` → `3000` (handled in base `values.yaml`). BPMN process flow sidebar; inbox document deserialization fix.
- **Open Formulieren 3.4.9** — validation/StUF-ZDS fixes, SDK 3.4.3, security patches.
- **Open Archiefbeheer 2.0.0** — ⚠️ breaking; see [Required manual steps](#required-manual-steps) and `migrate-openarchiefbeheer-2.0.0.py`.
- **Open Beheer chart 0.1.3** — `SESSION_COOKIE_AGE` configmap fix; optional `OPEN_ZAAK_ADMIN_BASE_URL`.
- **Object Types API 3.4.2 / Referentielijsten API 0.7.2** — security dependency updates (Django 5.2.13, cryptography 46.0.6, mozilla-django-oidc 5.0.2); uWSGI worker recycling.
- **OMC (NotifyNL) 1.17.19 / chart 0.14.1** — `/callback` returns HTTP 202 when the reference field is empty.
- **ZGW Office Add-in v0.9.289 / chart 0.0.87** — dependency updates only.
- **Open Inwoner 2.1.2** — stable release (unchanged across this range; never use `2.1.2-rc1`).

---

## See also

- [`values-changes-4.7.0.md`](values-changes-4.7.0.md) — full table of values to add/change/remove in gemeente `podiumd.yml` for the 4.7.0 jump.
- Granular per-release notes: [4.7.0→4.7.1](upgrade-from-4.7.0-to-4.7.1.md), [4.7.1→4.7.2](upgrade-from-4.7.1-to-4.7.2.md), [4.7.2→4.7.3](upgrade-from-4.7.2-to-4.7.3.md).
- Images: [`images-4.7.0.yaml`](images/images-4.7.0.yaml), [`images-4.7.1.yaml`](images/images-4.7.1.yaml), [`images-4.7.2.yaml`](images/images-4.7.2.yaml), [`images-4.7.3.yaml`](images/images-4.7.3.yaml).
