# Upgrade guide: PodiumD 4.6.5 → 4.7.0

## Changes

### OpenZaak 1.27.0 (helm chart 1.14.0)

No breaking changes. No required manual steps.

#### New optional features
We need to decide if we do anything with these, if not, remove this documentation else flesh it out for usage in an environment ! NO DECISION YET! 

**Azure Blob Storage for Documenten API**

OpenZaak 1.27.0 adds support for storing documents in Azure Blob Storage or S3 (S3 not supported in PodiumD). The default remains `filesystem`. To use Azure Blob Storage, set the following under `openzaak.settings`:

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

**Cloud Events**

OpenZaak 1.27.0 can emit cloud events for functional API operations and admin interface actions. Disabled by default. Requires Open Notificaties with cloud events support. To enable:

```yaml
openzaak:
  settings:
    enableCloudEvents: true
    notificationsSource: "openzaak"   # identifier used as the source field in cloud events
```

#### Notable application changes

- Archiving: for `afleidingswijze=vervaldatum_besluit` and `afleidingswijze=eigenschap`, the relevant value is no longer required at zaak closure — recalculation happens automatically when the value is set later.
- `Zaak.relevanteAndereZaken` is deprecated in the OpenAPI schema; the experimental `gerelateerdeZaken` attribute on the `/zaken` endpoint replaces it.
- Several bug fixes: 500 errors on document downloads, PATCH on `/zaaknotities`, and audit trail display in admin.

---

### ZAC 4.7.0 (helm chart 1.0.224)

⚠️ The ZAC helm chart now uses native **Gotenberg** (`gotenberg/gotenberg:8.30.1`) for document conversion, replacing the previous `ghcr.io/eugenmayer/kontextwork-converter` image. The container port changed from `8080` to `3000`.

#### Required manual steps

**Before upgrading — update the ACR mirror:**

1. The ACR mirror `acrprodmgmt.azurecr.io/office-converter` must be updated to mirror `gotenberg/gotenberg:8.30.1` instead of `ghcr.io/eugenmayer/kontextwork-converter`. Without this, all environments that override `office_converter.image.repository` will fail to pull the image.

2. **Run the migration script** to update `zac.office_converter.image.repository` in all gemeente `podiumd.yml` files from `<acr>/office-converter` to `<acr>/gotenberg`:

   ```bash
   # Preview changes without modifying files
   python3 charts/podiumd/scripts/migrate-zac-4.7.0.py --dry-run

   # Apply to all gemeente podiumd.yml files
   python3 charts/podiumd/scripts/migrate-zac-4.7.0.py

   # Or apply to a single file
   python3 charts/podiumd/scripts/migrate-zac-4.7.0.py path/to/gemeente/env/podiumd.yml
   ```

   The script handles both `acrprodmgmt.azurecr.io` and `acrtestmgmt.azurecr.io` registries and is idempotent.

The `containerPort` change (8080 → 3000) is handled automatically by the updated base `values.yaml`. No environment file overrides this value.

#### Notable application changes

- **BPMN process flow sidebar** with zoom controls and keyboard navigation when working on tasks.
- Versioning overhauled to use rolling dev pre-releases and proper hotfix patch versions.
- Fix: inbox document deserialization issue for retrieving documents from Open Zaak.

---

### Open Archiefbeheer 2.0.0 (helm chart 2.0.0)

⚠️ This release contains **breaking changes**. Follow the steps below before and after upgrading.

#### Required manual steps

**Before upgrading:**

1. Ensure no destruction lists are currently being processed or waiting for retry. The internal data structure for tracking destruction has been reworked; lists in-flight during the upgrade may end up in an inconsistent state.

**Before upgrading — update `podiumd.yml` files:**

2. **Run the OIDC migration script** to update `configuration.data` in all gemeente `podiumd.yml` files. The `mozilla-django-oidc-db` library was upgraded to v1.1.1, which requires a new YAML structure with a separate `providers` list. The old `items`-only format is no longer accepted.

   Run from the root of this repo (requires `yq` v4 — `brew install yq`):

   ```bash
   # Preview changes without modifying files
   python3 charts/podiumd/scripts/migrate-openarchiefbeheer-2.0.0.py --dry-run

   # Apply to all gemeente podiumd.yml files
   python3 charts/podiumd/scripts/migrate-openarchiefbeheer-2.0.0.py

   # Or apply to a single file
   python3 charts/podiumd/scripts/migrate-openarchiefbeheer-2.0.0.py path/to/gemeente/env/podiumd.yml
   ```

   The script transforms the `oidc_db_config_admin_auth` block in `configuration.data`:

   | Before | After |
   |--------|-------|
   | `items` only, with `endpoint_config` inline | Separate `providers` list holds `endpoint_config`; item references it via `oidc_provider_identifier` |
   | `username_claim`, `groups_claim`, `superuser_group_names`, `make_users_staff` as top-level item fields | Restructured into `options.user_settings` and `options.groups_settings` |
   | `claim_mapping`, `userinfo_claims_source`, `oidc_rp_scopes_list`, `sync_groups` present | Removed (deprecated) |

   After migration the `oidc_db_config_admin_auth` block looks like:

   ```yaml
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
         oidc_use_pkce: false
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

   The script is idempotent — re-running it on already-migrated files is safe.

**After upgrading:**

3. **Reconfigure the destruction report settings.** The destruction report configuration page has been reworked. Existing settings are not migrated automatically — open the admin interface and re-enter the destruction report configuration.

#### New optional features

**Destruction plugins for external registers**

Two new plugins allow destroying related resources in external systems when a destruction list is executed:

- **Object API plugin** — destroys resources stored in the Object API.
- **OpenKlant plugin** — destroys resources stored in OpenKlant (klantinteracties).

Configure via `configuration.data`:

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

**Post-destruction visibility period**

Destroyed lists now disappear from the kanban view after a configurable number of days (default: 7). Override via:

```yaml
openarchiefbeheer:
  settings:
    postDestructionVisibilityPeriod: "7"
```

**Disable related object counts**

To reduce load on external registers (Open Zaak, Selectielijst) and improve performance, the inline count of related objects can be disabled:

```yaml
openarchiefbeheer:
  settings:
    relatedCountDisabled: true
```
