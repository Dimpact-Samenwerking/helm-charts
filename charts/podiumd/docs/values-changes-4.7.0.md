# Values changes for PodiumD 4.7.0

Companion to [upgrade-from-4.6.5-to-4.7.0.md](upgrade-from-4.6.5-to-4.7.0.md). This file lists every value override a gemeente `podiumd.yml` may need to add, change, or remove when moving from chart 4.6.5 to 4.7.0. Application-level changes and migration scripts are documented in the upgrade guide; this file focuses purely on the values surface.

## TL;DR

| Component | Required action | Type |
|-----------|----------------|------|
| `openarchiefbeheer.configuration.data` (OIDC block) | Migrate `oidc_db_config_admin_auth` to providers/items + options structure | **Required** if openarchiefbeheer enabled |
| `zac.office_converter.image.repository` | Change `<acr>/office-converter` → `<acr>/gotenberg` | **Required** if repository overridden |
| `zac.office_converter.image.tag` | `1.8.2` → `8.31.0` | **Required** if tag overridden |
| `zac.office_converter.containerPort` | Remove override (chart default now `3000`) | **Required** if overridden to `8080` |
| `openzaak.settings.documentApiBackend` | New optional field, default `filesystem` | Optional |
| `openzaak.settings.azureBlobStorage` | New optional block | Optional |
| `openzaak.settings.enableCloudEvents` / `notificationsSource` | New optional fields | Optional |
| `openarchiefbeheer.settings.postDestructionVisibilityPeriod` | New optional field, default `7` | Optional |
| `openarchiefbeheer.settings.relatedCountDisabled` | New optional field, default `false` | Optional |
| `openarchiefbeheer.configuration.data` (`external_registers`) | New optional block (Object API + OpenKlant destruction plugins) | Optional |
| `openinwoner.image.tag` | Defaults to `2.1.2-rc1` (release candidate, DRT-557). Pin to a stable `2.1.2` before promoting 4.7.0 to production, or roll back to `2.1.1`. | ⚠️ **Before production** |
| Image tag overrides for openzaak / openformulieren / objecttypen / referentielijsten / omc / zgw-office-addin / keycloak | Drop overrides or bump to chart defaults | Cleanup |

## Required changes

### 1. openarchiefbeheer — OIDC config restructure

`mozilla-django-oidc-db` v1.1.1 requires a separate `providers` list. The old `items`-only format is no longer accepted. Run the migration script first; a manual edit looks like:

**Before (4.6.5):**

```yaml
openarchiefbeheer:
  configuration:
    data: |
      oidc_db_config_enable: true
      oidc_db_config_admin_auth:
        items:
          - identifier: admin-oidc
            enabled: true
            endpoint_config:
              oidc_op_discovery_endpoint: https://keycloak.example.nl/realms/podiumd/
            oidc_rp_scopes_list: [openid, email, profile]
            userinfo_claims_source: id_token
            oidc_rp_client_id: openarchiefbeheer
            oidc_rp_client_secret: {value_from: {env: keycloak_client_secret}}
            oidc_rp_sign_algo: RS256
            claim_mapping:
              email: [email]
              first_name: [given_name]
              last_name: [family_name]
            username_claim: [preferred_username]
            groups_claim: [groups]
            superuser_group_names: [administrators]
            make_users_staff: true
            sync_groups: true
```

**After (4.7.0):**

```yaml
openarchiefbeheer:
  configuration:
    data: |
      oidc_db_config_enable: true
      oidc_db_config_admin_auth:
        providers:
          - identifier: admin-oidc-provider
            endpoint_config:
              oidc_op_discovery_endpoint: https://keycloak.example.nl/realms/podiumd/
            oidc_token_use_basic_auth: false
        items:
          - identifier: admin-oidc
            enabled: true
            oidc_rp_client_id: openarchiefbeheer
            oidc_rp_client_secret: {value_from: {env: keycloak_client_secret}}
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
                  - administrators
                claim_mapping:
                  - groups
                make_users_staff: true
```

**Removed (deprecated):**
- `claim_mapping` (top-level on item)
- `userinfo_claims_source`
- `oidc_rp_scopes_list`
- `sync_groups`
- `username_claim`, `groups_claim` (replaced by `options.user_settings.claim_mappings.username` and `options.groups_settings.claim_mapping`)
- `endpoint_config` inline on item (moved to `providers[].endpoint_config`)

**Added:**
- `providers[]` list with `identifier` + `endpoint_config` + `oidc_token_use_basic_auth`
- `oidc_provider_identifier` reference on each item
- `options.user_settings` (claim_mappings, username_case_sensitive)
- `options.groups_settings` (superuser_group_names, claim_mapping, make_users_staff)

> **Note on PKCE.** Earlier drafts of this guide listed `oidc_use_pkce` as an item-level addition. OAB 2.0.0's `mozilla-django-oidc-db 1.1.1` schema rejects this field with `extra_forbidden`. Do not add it for OAB; PKCE for the OAB OIDC client must be set via Django admin or DB. The current `migrate-openarchiefbeheer-2.0.0.py` strips any stale entry via `yq del`.

### 2. ZAC — office converter (Gotenberg)

The image moved from `kontextwork-converter` to `gotenberg/gotenberg`. ACR mirror must be updated **before** deploy.

**Before:**

```yaml
zac:
  office_converter:
    image:
      repository: acrprodmgmt.azurecr.io/office-converter
      tag: "1.8.2"
    containerPort: 8080
```

**After:**

```yaml
zac:
  office_converter:
    image:
      repository: acrprodmgmt.azurecr.io/gotenberg
      tag: "8.31.0"
    # containerPort: drop the override; chart default is now 3000
```

If a gemeente file does **not** override `office_converter.image.repository`, no values change is needed — the chart `values.yaml` already points to `gotenberg/gotenberg:8.31.0` with `containerPort: 3000`.

The migration script `charts/podiumd/scripts/migrate-zac-4.7.0.py` automates the repository rewrite for `acrprodmgmt.azurecr.io` and `acrtestmgmt.azurecr.io`.

## New optional fields

### openzaak — Documenten API backend

```yaml
openzaak:
  settings:
    documentApiBackend: filesystem   # default; alt: azure_blob_storage
    # azureBlobStorage:
    #   accountName: ""
    #   clientSecret: ""
    #   clientId: ""
    #   tenantId: ""
    #   container: openzaak
```

### openzaak — Cloud Events

```yaml
openzaak:
  settings:
    enableCloudEvents: false           # default
    notificationsSource: openzaak      # source field for emitted events
```

Requires Open Notificaties with cloud events support.

### openarchiefbeheer — Destruction visibility & performance

```yaml
openarchiefbeheer:
  settings:
    postDestructionVisibilityPeriod: 7   # days a destroyed list stays visible
    relatedCountDisabled: false          # set true to skip related-object counts
```

### openarchiefbeheer — External-register destruction plugins

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

## Cleanup — image tag overrides

The chart `values.yaml` already pins the new versions. Remove explicit tag overrides in gemeente files when they merely repeated a 4.6.x value, otherwise bump to:

| Component | New default tag |
|-----------|----------------|
| `keycloak.image.tag` / `keycloak-operator.operator.image.tag` | `26.6.1` |
| `openzaak.image.tag` | `1.27.1` |
| `openformulieren.image.tag` | `3.4.9` |
| `openarchiefbeheer.image.tag` | `2.0.0` |
| `openinwoner.image.tag` | `2.1.2-rc1` (⚠️ release candidate — see [upgrade guide](upgrade-from-4.6.5-to-4.7.0.md#component-versions)) |
| `objecttypen.image.tag` | `3.4.2` |
| `referentielijsten.image.tag` | `0.7.2` |
| `omc.image.tag` | `1.17.19` |
| `zgw-office-addin.{frontend,backend}.image.tag` | `v0.9.289` |
| `zac.image.tag` | `4.7.1` |
| `zac.office_converter.image.tag` | `8.31.0` |
| `zac.opa.image.tag` | `1.15.2-static` |
| `zac.global.curlImage.tag` | `8.20.0` |

## Pre-deploy checklist

1. ACR mirror `office-converter` → `gotenberg/gotenberg:8.31.0` updated.
2. No destruction lists in flight (openarchiefbeheer 2.0.0 reworks internal data structure).
3. Migration scripts run (see [upgrade-from-4.6.5-to-4.7.0.md § Migration scripts and OIDC how-tos](upgrade-from-4.6.5-to-4.7.0.md#migration-scripts-and-oidc-how-tos)):
   - `python3 charts/podiumd/scripts/migrate-openarchiefbeheer-2.0.0.py` — required for Open Archiefbeheer 2.0.0
   - `python3 charts/podiumd/scripts/migrate-zac-4.7.0.py` — required only if `zac.office_converter.image.repository` is overridden
   - `python3 charts/podiumd/scripts/fix-oidc-config.py <values-file>` — generic OIDC sweep (flat → `options.user_settings`/`options.groups_settings`); useful as a catch-all after the openarchiefbeheer-specific script
4. Verify gemeente `podiumd.yml` for any inline OIDC block in `openarchiefbeheer.configuration.data` — the script handles standard cases but custom claim mappings need manual review.
5. After deploy: re-enter destruction report configuration in the openarchiefbeheer admin UI.
