# Upgrade guide: PodiumD 4.6.5 → 4.7.0

## Component versions

| Component | App version | Helm chart |
|---|---|---|
| Keycloak | 26.6.1 | adfinis 1.11.4 |
| OpenZaak | 1.27.1 | 1.13.1 (chart bump to 1.14.0 deferred — see [openzaak-known-issues.md § 0](openzaak-known-issues.md#0-podiumd-470-stays-on-open-zaak-helm-chart-1131-not-1140)) |
| ZAC | 4.8.0 | 1.0.228 |
| Open Formulieren | 3.4.9 | 1.12.0 |
| Open Archiefbeheer | 2.0.0 | 2.0.0 (⚠️ breaking) |
| Open Beheer | 0.9.0 | 0.1.3 |
| Open Inwoner | 2.1.2-rc1 (⚠️ release candidate — see warning below) | 2.1.3 |
| Object Types API | 3.4.2 | 1.6.1 |
| Referentielijsten API | 0.7.2 | 0.1.1 |
| OMC (NotifyNL) | 1.17.19 | 0.14.1 |
| ZGW Office Add-in | v0.9.289 | 0.0.87 |
| APISIX (egress gateway, opt-in) | 3.16.0 | 2.14.0 |

> ⚠️ **Open Inwoner 2.1.2-rc1 is a release candidate and is NOT suitable for production.**
> The image is carried in 4.7.0 to inherit the DRT-557 fix shipped via PodiumD 4.6.7
> ([#306](https://github.com/Dimpact-Samenwerking/helm-charts/pull/306)). Before
> promoting 4.7.0 to a production environment, pin `openinwoner.image.tag` to a
> stable `2.1.2` release (or roll back to `2.1.1` if no fixed release is available
> at promotion time).

---

## Required manual steps

### Before upgrading

1. **Quiesce Open Archiefbeheer** — ensure no destruction lists are processing or waiting for retry. The internal data structure for tracking destruction has been reworked; lists in-flight during the upgrade may end up in an inconsistent state.
2. **Update the ACR mirror for ZAC office_converter** — `acrprodmgmt.azurecr.io/office-converter` must be updated to mirror `gotenberg/gotenberg:8.31.0` instead of `ghcr.io/eugenmayer/kontextwork-converter`. Without this, environments overriding `zac.office_converter.image.repository` will fail to pull the image.
3. **Apply Keycloak `v2beta1` CRDs** (see [Keycloak CRD upgrade](#keycloak-crd-upgrade-v2alpha1--v2beta1)). Required because the chart bumps the operator image to `26.6.1` while the bundled adfinis subchart `1.11.4` still ships `v2alpha1` CRDs from appVersion `26.5.6`. Operator `26.6.1` queries `v2beta1` and will `CrashLoopBackOff` until the upgraded CRDs are applied.
4. **Set `apiproxy.nginxCertsSecret` explicitly** if your environment uses upstream mTLS via the api-proxy (see [API proxy: nginxCertsSecret default changed](#api-proxy-nginxcertssecret-default-changed)). The chart default is now `""` (empty); environments that previously relied on the implicit `"api-proxy-certs"` default must pin the value in `podiumd.yml` **before** the upgrade or the cert volume mount disappears and upstream calls fall back to non-mTLS with `proxy_ssl_verify off`.
5. **Run the migration scripts** (see [Migration scripts](#migration-scripts)).

### After upgrading

6. **Reconfigure the destruction report settings** in the Open Archiefbeheer admin interface. The destruction report configuration page has been reworked; existing settings are not migrated automatically.

---

## Keycloak CRD upgrade (`v2alpha1` → `v2beta1`)

The chart pins `keycloak-operator` to image `quay.io/keycloak/keycloak-operator:26.6.1` (see `values.yaml`), but the adfinis subchart `keycloak-operator-1.11.4` (appVersion `26.5.6`) ships the older `v2alpha1` CRDs. Operator `26.6.1` issues informer queries against `apis/k8s.keycloak.org/v2beta1/...`.

### Apply procedure

Use the helper script (`charts/podiumd/scripts/install-keycloak-operator-crds.sh`). It defaults to the upstream Keycloak `v1` CRD manifests at the right Keycloak version and applies them server-side:

```bash
CTX=<your-aks-context>
NS=<keycloak-namespace>      # e.g. podiumd

# 1. Snapshot existing CRs (rollback insurance)
kubectl --context "$CTX" -n "$NS" get keycloak,keycloakrealmimport -o yaml > /tmp/kc-backup-$(date +%s).yml

# 2. Install upstream 26.6.1 CRDs (adds v2beta1, keeps v2alpha1 deprecated/served)
charts/podiumd/scripts/install-keycloak-operator-crds.sh \
  --context "$CTX" --keycloak-version 26.6.1

# 3. Restart the operator so it re-establishes informers
kubectl --context "$CTX" -n "$NS" rollout restart deploy keycloak-operator

# 4. Migrate stored CRs to v2beta1 storage version (read + re-apply triggers re-serialization)
kubectl --context "$CTX" -n "$NS" get keycloak,keycloakrealmimport -o yaml \
  | kubectl --context "$CTX" apply -f -
```

The script accepts `--dry-run` to inspect the CRD YAML, `--keycloak-version` to pin to a specific Keycloak release, and `--source chart --chart-version 1.11.4` to fall back to the adfinis subchart CRDs

- Upstream 26.6.1 CRDs declare both versions:
  - `v2beta1`: `served: true`, `storage: true`
  - `v2alpha1`: `served: true`, `storage: false`, `deprecated: true`, `deprecationWarning: "Please migrate to v2beta1"`
- No conversion webhook → default `None` strategy, fields pass through by name.
- Schema is additive between 26.5.x and 26.6.x — no removed/renamed required fields.
- The Keycloak `StatefulSet` keeps running while the operator restarts; only reconciliation is paused.

---

## API proxy: `nginxCertsSecret` default changed

`apiproxy.nginxCertsSecret` previously defaulted to `"api-proxy-certs"`. That secret is **not** present in every environment (only some clusters provision it for upstream mTLS to BAG/BRP/KVK), so the implicit default produced a missing-secret error or, where the secret happened to exist with a different name, a silently misconfigured proxy.

In 4.7.0 the default is `""` (empty). When empty:

- The cert volume / `/etc/nginx/certs` mount is omitted.
- `proxy_ssl_certificate` / `proxy_ssl_certificate_key` directives are not rendered (no client cert sent upstream).
- `apiproxy.locations.commonSettings.sslVerify` (still `""` = auto-derive) resolves to `"off"`, so upstream server certs are **not** validated.

Also new in 4.7.0: `apiproxy.sslVerifyDepth` (default `6`) renders `proxy_ssl_verify_depth` for every upstream location. nginx default is `1`, which is too shallow for cross-signed government API chains. Override globally on the api-proxy block, or per upstream:

```yaml
apiproxy:
  sslVerifyDepth: 6              # global default
  locations:
    bag:
      sslVerifyDepth: 10         # override only for BAG
    brp:
      sslVerifyDepth: 4          # override only for BRP
```

Per-location values take precedence over the global; the global takes precedence over the chart default of `6`. No action required if the default works.

### Action required

If your environment **does** use upstream mTLS via the api-proxy and the secret is provisioned in the `podiumd` namespace, pin the value explicitly in your gemeente `podiumd.yml` **before** running `helm upgrade`:

```yaml
apiproxy:
  enabled: true
  nginxCertsSecret: api-proxy-certs   # or whatever name the secret has in your cluster
```

To check the current setting and whether the secret exists:

```bash
helm --kube-context "$CTX" get values podiumd -n podiumd -o yaml \
  | yq '.apiproxy.nginxCertsSecret // "<unset — will use new chart default>"'

kubectl --context "$CTX" -n podiumd get secret api-proxy-certs --ignore-not-found
```

If `apiproxy.enabled` is `false` (most non-DIMP gemeentes), no action is needed.

---

## Migration scripts

All scripts ship in `charts/podiumd/scripts/`. Run from the repo root (or use an absolute path). All three are idempotent — re-running on an already-migrated file is safe.

| Script | Purpose | Required for |
|---|---|---|
| `migrate-openarchiefbeheer-2.0.0.py` | Migrate `openarchiefbeheer.configuration.data` OIDC block to v1.1.1 (`providers` + `options`) and drop deprecated keys | Open Archiefbeheer 2.0.0 upgrade |
| `migrate-zac-4.7.0.py` | Rewrite `zac.office_converter.image.repository` from `<acr>/office-converter` to `<acr>/gotenberg` | ZAC 4.7.0 upgrade (only if repository overridden per-environment) |
| `fix-oidc-config.py` | Generic OIDC migration: flat `claim_mapping` / `username_claim` / `groups_claim` / `make_users_staff` → `options.user_settings` / `options.groups_settings`. Promotes inline `endpoint_config` to a top-level `providers` list and adds `oidc_provider_identifier` references | Any component using `mozilla-django-oidc-db ≥ 1.x` (openzaak, opennotificaties, objecten, objecttypen, openklant, openformulieren, openarchiefbeheer). Skips `openinwoner` (still flat format) automatically |

### `migrate-openarchiefbeheer-2.0.0.py` — Open Archiefbeheer 2.0.0 OIDC migration

Required for Open Archiefbeheer 2.0.0. The `mozilla-django-oidc-db` library was upgraded to v1.1.1, which requires a new YAML structure with a separate `providers` list. The old `items`-only format is no longer accepted.

Requires `yq` v4 (`brew install yq`).

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

#### Configuration example — before

```yaml
openarchiefbeheer:
  configuration:
    data: |-
      oidc_db_config_admin_auth:
        items:
          - identifier: admin-oidc
            enabled: true
            oidc_rp_client_id: <client-id>
            oidc_rp_client_secret: "REP_OPENARCHIEFBEHEER_OIDC_SECRET_REP"
            oidc_rp_sign_algo: RS256
            endpoint_config:
              oidc_op_discovery_endpoint: "https://<keycloak>/realms/<realm>/"
            username_claim:
              - preferred_username
            groups_claim:
              - groups
            superuser_group_names:
              - administrators
            make_users_staff: true
            claim_mapping: {}                # removed by migration
            userinfo_claims_source: ...      # removed by migration
            oidc_rp_scopes_list: [...]       # removed by migration
            sync_groups: ...                 # removed by migration
```

#### Configuration example — after

```yaml
openarchiefbeheer:
  configuration:
    data: |-
      oidc_db_config_admin_auth:
        providers:
          - identifier: admin-oidc-provider
            endpoint_config:
              oidc_op_discovery_endpoint: "https://<keycloak>/realms/<realm>/"
            oidc_token_use_basic_auth: false
        items:
          - identifier: admin-oidc
            enabled: true
            oidc_rp_client_id: <client-id>
            oidc_rp_client_secret: "REP_OPENARCHIEFBEHEER_OIDC_SECRET_REP"
            oidc_rp_sign_algo: RS256
            oidc_provider_identifier: admin-oidc-provider
            options:
              user_settings:
                claim_mappings:
                  username:
                    - preferred_username
                username_case_sensitive: false
              groups_settings:
                superuser_group_names:
                  - "administrators"
                claim_mapping:
                  - groups
                make_users_staff: true
```

> **Note on PKCE.** OAB 2.0.0 ships with `mozilla-django-oidc-db 1.1.1`, whose `setup_configuration` schema does NOT accept `oidc_use_pkce` at item or provider level (`extra_forbidden` validation error from pydantic). Do not add this field for OAB. The `keycloak-podiumd-realm-config.yaml` PKCE consistency check does not apply to OAB; `openarchiefbeheer.configuration.pkceEnabled` is a no-op for 4.7.0. If PKCE for the OAB OIDC client is ever required, toggle it via the Django admin UI or directly on the underlying `OIDCClient` DB row. Earlier versions of `migrate-openarchiefbeheer-2.0.0.py` injected `oidc_use_pkce: false` here; re-running the current script removes it.

If a previous (buggy) run of the migration script left `oidc_use_pkce: false` in your `openarchiefbeheer.configuration.data`, remove the line manually or re-run the migration script — the current version explicitly strips the field via `yq del`.

---

### `migrate-zac-4.7.0.py` — ZAC office_converter image rename

Only relevant if a gemeente values file overrides `zac.office_converter.image.repository`. Without an override, the chart `values.yaml` already points to `gotenberg/gotenberg:8.31.0` and no rewrite is needed.

The script handles both `acrprodmgmt.azurecr.io` and `acrtestmgmt.azurecr.io`. The chart-level `containerPort` change (8080 → 3000) lives in the base `values.yaml` and does not need a per-environment edit unless overridden.

```bash
# Preview
python3 charts/podiumd/scripts/migrate-zac-4.7.0.py --dry-run

# Apply to all gemeente podiumd.yml files
python3 charts/podiumd/scripts/migrate-zac-4.7.0.py

# Or single file
python3 charts/podiumd/scripts/migrate-zac-4.7.0.py path/to/gemeente/env/podiumd.yml
```

#### Configuration example — before

```yaml
zac:
  office_converter:
    image:
      repository: acrprodmgmt.azurecr.io/office-converter
      # base values.yaml previously: ghcr.io/eugenmayer/kontextwork-converter
      # containerPort: 8080
```

#### Configuration example — after

```yaml
zac:
  office_converter:
    image:
      repository: acrprodmgmt.azurecr.io/gotenberg
      # base values.yaml: gotenberg/gotenberg:8.31.0
      # containerPort: 3000  (handled in base values.yaml — no override needed)
```

---

### `fix-oidc-config.py` — generic OIDC migration sweep

Catch-all for any component using `mozilla-django-oidc-db ≥ 1.x`: openzaak, opennotificaties, objecten, objecttypen, openklant, openformulieren, openarchiefbeheer. Skips `openinwoner` (still flat format) automatically.

Use this when:

- A gemeente still has a `claim_mapping`, `username_claim`, or `groups_claim` block at the OIDC item level for any affected component.
- An OIDC item has `endpoint_config` inline rather than a separate top-level `providers` list with `oidc_provider_identifier` references.
- You want a quick `--dry-run` diff to confirm a values file is already on the new format.

```bash
# Dry-run (writes nothing)
python3 charts/podiumd/scripts/fix-oidc-config.py values-<gemeente>.yml --dry-run

# In-place migrate
python3 charts/podiumd/scripts/fix-oidc-config.py values-<gemeente>.yml

# Write to a separate file
python3 charts/podiumd/scripts/fix-oidc-config.py values-<gemeente>.yml -o values-<gemeente>-migrated.yml
```

Requires `ruamel.yaml` (preferred — preserves comments/quotes) or `PyYAML` as fallback:

```bash
pip install ruamel.yaml
```

The script processes every literal block scalar (`data: |` / `data: |-`) that contains `oidc_db_config_admin_auth` and leaves the rest of the file untouched (no global re-indent, no comment loss). It does **not** strip deprecated keys (`oidc_rp_scopes_list`, `userinfo_claims_source`) — for openarchiefbeheer, run `migrate-openarchiefbeheer-2.0.0.py` first or alongside.

#### Configuration example — before

```yaml
<component>:               # e.g. openzaak, openformulieren, openklant, ...
  configuration:
    data: |-
      oidc_db_config_admin_auth:
        items:
          - identifier: admin-oidc
            enabled: true
            oidc_rp_client_id: <client-id>
            oidc_rp_client_secret: "REP_<COMPONENT>_OIDC_SECRET_REP"
            oidc_rp_sign_algo: RS256
            endpoint_config:
              oidc_op_discovery_endpoint: "https://<keycloak>/realms/<realm>/"
            username_claim:
              - preferred_username
            groups_claim:
              - groups
            make_users_staff: true
```

#### Configuration example — after

```yaml
<component>:
  configuration:
    data: |-
      oidc_db_config_admin_auth:
        providers:
          - identifier: admin-oidc-provider
            endpoint_config:
              oidc_op_discovery_endpoint: "https://<keycloak>/realms/<realm>/"
        items:
          - identifier: admin-oidc
            enabled: true
            oidc_rp_client_id: <client-id>
            oidc_rp_client_secret: "REP_<COMPONENT>_OIDC_SECRET_REP"
            oidc_rp_sign_algo: RS256
            oidc_provider_identifier: admin-oidc-provider
            options:
              user_settings:
                claim_mappings:
                  username:
                    - preferred_username
              groups_settings:
                claim_mapping:
                  - groups
                make_users_staff: true
```

---

### Recommended order for openarchiefbeheer

For Open Archiefbeheer 2.0.0 specifically, prefer `migrate-openarchiefbeheer-2.0.0.py` — it is purpose-built and removes all deprecated keys. Use `fix-oidc-config.py` as a catch-all for environments that have additional components with stale flat-format OIDC blocks.

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

## Optional configuration blocks

All blocks below are **opt-in** — defaults are unchanged. Add to gemeente `podiumd.yml` only when wanted.

### OpenZaak — Azure Blob Storage for Documenten API

OpenZaak 1.27.1 adds support for storing documents in Azure Blob Storage or S3 (S3 not supported in PodiumD). The default remains `filesystem`. To use Azure Blob Storage, set the following under `openzaak.settings`:

```yaml
openzaak:
  settings:
    documentApiBackend: azure_blob_storage
    azureBlobStorage:
      accountName: "<storage-account-name>"
      clientSecret: "<client-secret>"
      clientId: "<client-id>"
      tenantId: "<tenant-id>"
      container: "openzaak"
```

> **Status:** No decision yet on adopting this for any environment.

### OpenZaak — Cloud Events

OpenZaak 1.27.1 can emit cloud events for functional API operations and admin interface actions. Disabled by default. Requires Open Notificaties with cloud events support.

```yaml
openzaak:
  settings:
    enableCloudEvents: true
    notificationsSource: "openzaak"   # identifier used as the source field in cloud events
```

> **Status:** No decision yet.

### Open Archiefbeheer — destruction plugins for external registers

Two new plugins allow destroying related resources in external systems when a destruction list is executed:

- **Object API plugin** — destroys resources stored in the Object API.
- **OpenKlant plugin** — destroys resources stored in OpenKlant (klantinteracties).

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

Reduce load on external registers (Open Zaak, Selectielijst) and improve performance by disabling inline counts of related objects.

```yaml
openarchiefbeheer:
  settings:
    relatedCountDisabled: true
```

---

## Component changelogs (no action required)

### Keycloak 26.6.1 (adfinis helm chart 1.11.4)

⚠️ Requires the [Keycloak CRD upgrade](#keycloak-crd-upgrade-v2alpha1--v2beta1) before upgrading the chart. The adfinis subchart `1.11.4` still bundles `v2alpha1` CRDs from appVersion `26.5.6`, but the operator image is overridden to `26.6.1` which queries `v2beta1`.

#### Security fixes

- **CVE-2026-4366** — Blind Server-Side Request Forgery (SSRF) via HTTP Redirect Handling. Keycloak's outgoing HTTP connections no longer follow redirects by default. This prevents redirect-based bypasses of allowed URL policies. In PodiumD, outgoing Keycloak connections (Entra ID / Azure AD OIDC discovery, CRL endpoints) use HTTPS and do not rely on HTTP redirects; no impact expected.
- **CVE-2026-4633** — User enumeration via identity-first login. Fixed in the Keycloak server itself; no configuration change required.

#### Notable changes from 26.6.0 (included in 26.6.1)

- **Endpoints open during initialization** — Keycloak now opens HTTP(S) and Management ports while initialization (including DB migrations) is still in progress, provided health endpoints are enabled. PodiumD already sets `health-enabled: true`, so readiness probes will correctly withhold traffic until `/health/ready` returns OK. Resolves potential pod restarts during long-running migrations on Kubernetes.
- **Stricter client URI validation (`secure-client-uris` executor)** — If active in a realm, the `Post logout redirect URIs`, `Logo URL`, `Policy URL`, and `Terms of Service URL` fields now require HTTPS. PodiumD does not configure this executor by default; only relevant if a gemeente has manually enabled it.
- **Identity Provider issuer uniqueness** — If multiple Identity Providers in a realm share the same issuer, JWT authorization grant and client assertion flows will now fail. PodiumD Entra ID configurations use per-tenant issuer URLs and are not affected.

### OpenZaak 1.27.1 (helm chart **stays on 1.13.1**)

No breaking changes. No required manual steps.

> The Open Zaak helm chart bump to `1.14.0` is **deferred** — PodiumD 4.7.0 keeps `Chart.yaml` pinned at `openzaak.version: 1.13.1` and rides the new app version `1.27.1` through the existing chart machinery. Reason: chart `1.14.0` was not released yet when gemeente deploys for this release cycle started, and a mid-rollout chart bump would have re-opened the values surface for every gemeente file. See [openzaak-known-issues.md § 0](openzaak-known-issues.md#0-podiumd-470-stays-on-open-zaak-helm-chart-1131-not-1140).

- Archiving: for `afleidingswijze=vervaldatum_besluit` and `afleidingswijze=eigenschap`, the relevant value is no longer required at zaak closure — recalculation happens automatically when the value is set later.
- `Zaak.relevanteAndereZaken` is deprecated in the OpenAPI schema; the experimental `gerelateerdeZaken` attribute on the `/zaken` endpoint replaces it.
- Bug fixes: 500 errors on document downloads, PATCH on `/zaaknotities`, audit trail display in admin.

### ZAC 4.8.0 (helm chart 1.0.228)

⚠️ The ZAC helm chart now uses native **Gotenberg** (`gotenberg/gotenberg:8.31.0`) for document conversion, replacing the previous `ghcr.io/eugenmayer/kontextwork-converter` image. The container port changed from `8080` to `3000`. The `containerPort` change is handled automatically by the updated base `values.yaml` — no environment file overrides this value.

- **BPMN process flow sidebar** with zoom controls and keyboard navigation when working on tasks.
- Versioning overhauled to use rolling dev pre-releases and proper hotfix patch versions.
- Fix: inbox document deserialization issue for retrieving documents from Open Zaak.

### Open Formulieren 3.4.9 (helm chart 1.12.0)

No breaking changes. No required manual steps.

- Fixed validation messages being linked to the wrong steps, causing confusing errors in the public frontend.
- Fixed missing required XML-attributes in StUF-ZDS messages.
- Fixed crash in JSON schema generation when a fieldset is inside an editgrid.
- Fixed wrong entity type in StUF-ZDS element for cosigner details.
- Fixed simple conditionals not interpreting empty file upload fields correctly.
- Fixed dynamic radio/selectboxes/select options with empty labels being rendered.
- Fixed missing structlog context propagation across threads, causing prefill audit logs not to be saved.
- Upgraded SDK to 3.4.3 with fixes in the new renderer.
- Applied latest security patches.

### Open Archiefbeheer 2.0.0 (helm chart 2.0.0)

⚠️ Breaking changes — see [Required manual steps](#required-manual-steps) and the `migrate-openarchiefbeheer-2.0.0.py` script above. Optional new features documented in [Optional configuration blocks](#optional-configuration-blocks).

### Open Beheer helm chart 0.1.3

Bug fix: `SESSION_COOKIE_AGE` was incorrectly defined in the configmap. Also adds optional support for a new `OPEN_ZAAK_ADMIN_BASE_URL` setting (no action required).

### Object Types API 3.4.2

Maintenance release: security dependency updates (Django 5.2.13, cryptography 46.0.6, mozilla-django-oidc 5.0.2) and uWSGI memory optimisation (workers restart after 1000 requests).

### Referentielijsten API 0.7.2

Minor bug fix: styling on the `account_blocked.html` page. Same security dependency updates as Object Types API 3.4.2.

### OMC (NotifyNL) 1.17.19 / helm chart 0.14.1

Bug fix: the `/callback` endpoint now returns HTTP 202 instead of an error when the reference field is empty.

### ZGW Office Add-in v0.9.289 / helm chart 0.0.87

Dependency updates only (Renovate-managed). No functional changes.

### APISIX 3.16.0 / helm chart 2.14.0 (new — opt-in)

New egress API gateway, tracked under [IN-1867](https://dimpact.atlassian.net/browse/IN-1867). **Disabled by default** (`apisix.enabled: false`) — existing environments are unaffected by the upgrade.

To opt in, see [`apisix-egress-gateway.md`](apisix-egress-gateway.md) for the full setup. Minimum tenant `podiumd.yml` to enable:

```yaml
apisix:
  enabled: true
  apisix:
    deployment:
      standalone:
        config: |
          routes:
            - id: apisix-dashboard-oidc
              uri: /ui/*
              upstream:
                type: roundrobin
                nodes:
                  "127.0.0.1:9180": 1
              plugins:
                openid-connect:
                  client_id: "apisix-dashboard"
                  client_secret: "$env://OIDC_CLIENT_SECRET"
                  discovery: "https://<your-keycloak>/realms/podiumd/.well-known/openid-configuration"
                  scope: "openid profile email"
                  bearer_only: false
                  realm: "podiumd"
                  introspection_endpoint_auth_method: "client_secret_basic"
                  ssl_verify: true
```

Plus a `Secret/apisix-oidc-client-secret` with key `clientSecret` for the Keycloak client. Admin/viewer API keys are auto-generated by the umbrella chart — no manual rotation needed.

---

## See also

- [`values-changes-4.7.0.md`](values-changes-4.7.0.md) — full table of values that need to be added, changed, or removed in gemeente `podiumd.yml` files for the 4.6.5 → 4.7.0 jump.
