# Open Archiefbeheer — known issues and configuration traps

## 1. `oidc_use_pkce` rejected by setup_configuration in OAB 2.0.0

### Symptom

`openarchiefbeheer-config` Job fails with `BackoffLimitExceeded`. Pod logs:

```
Validating requirements...
Invalid configuration settings for step "Configuration for admin login via OpenID Connect":
    1 validation error for ConfigSettingsSourceOidc_db_config_admin_auth
    oidc_db_config_admin_auth.items.0.oidc_use_pkce
      Extra inputs are not permitted [type=extra_forbidden,
                                      input_value=False, input_type=bool]
        For further information visit https://errors.pydantic.dev/2.9/v/extra_forbidden

CommandError: Failed to validate requirements for 1 steps
```

When the `*-config` Job has TTL'd already, helm `--wait` reports the Job as `NotFound` instead of failed (see [`openformulieren-known-issues.md`](openformulieren-known-issues.md) for the broader TTL-vs-`--wait` race).

### Root cause

OAB 2.0.0 ships:

- `mozilla-django-oidc-db == 1.1.1`
- `mozilla-django-oidc == 4.0.1`

Schema probed live from `acrprodmgmt.azurecr.io/openarchiefbeheer:2.0.0`:

```python
>>> from mozilla_django_oidc_db.setup_configuration import models
>>> list(models.AdminOIDCConfigurationModelItem.model_fields.keys())
['identifier', 'enabled', 'oidc_rp_scopes_list', 'options', 'endpoint_config',
 'oidc_provider_identifier', 'claim_mapping', 'oidc_token_use_basic_auth',
 'oidc_use_nonce', 'oidc_nonce_size', 'oidc_state_size', 'username_claim',
 'groups_claim', 'superuser_group_names', 'default_groups', 'sync_groups',
 'sync_groups_glob_pattern', 'make_users_staff', 'oidc_rp_client_id',
 'oidc_rp_client_secret', 'oidc_rp_sign_algo', 'oidc_rp_idp_sign_key',
 'oidc_keycloak_idp_hint', 'userinfo_claims_source']
>>> list(models.OIDCConfigProviderModel.model_fields.keys())
['identifier', 'endpoint_config', 'oidc_token_use_basic_auth',
 'oidc_use_nonce', 'oidc_nonce_size', 'oidc_state_size']
```

Neither model declares `oidc_use_pkce`. Pydantic's default config rejects unknown fields → `extra_forbidden`. The `options` dict is free-form (`dict[str, Any]`) but `AdminOIDCConfigurationStep` does not consume PKCE keys from there — putting them under `options` is silently ignored.

**The field has no valid YAML location in OAB 2.0.0.** Other Maykin/Django apps (openzaak, openformulieren, openklant, opennotificaties, objecten, objecttypen) accept `oidc_use_pkce` at item level — only OAB rejects it for now, because its `mozilla-django-oidc-db` is pinned to 1.1.1 instead of a newer release that adds PKCE to the schema.

### Affected versions

- OAB 2.0.0 (helm chart `openarchiefbeheer 2.0.0`, PodiumD 4.7.0+)
- Earlier `mozilla-django-oidc-db` < 1.x do not even have a `providers`/`items` schema, so this is specifically a 1.1.1 quirk

### Fix

Do **not** add `oidc_use_pkce` to OAB `configuration.data`. The current `migrate-openarchiefbeheer-2.0.0.py` strips any stale entry via `yq del`. If you ran an earlier version of the script (which incorrectly added `oidc_use_pkce: false`), either:

1. Re-run the current migration script — it deletes the field idempotently:

   ```bash
   python3 charts/podiumd/scripts/migrate-openarchiefbeheer-2.0.0.py path/to/podiumd.yml
   ```

2. Or remove the line manually from `openarchiefbeheer.configuration.data` in your gemeente values file.

Then redeploy. The `openarchiefbeheer-config` Job runs `setup_configuration` and validates cleanly:

```
Validating requirements...
Valid configuration settings found for all steps.

Executing steps...
    Successfully executed step: Configuration to connect with external services
    Successfully executed step: API Configuration
    Successfully executed step: Configuration for admin login via OpenID Connect

Configuration completed.
```

### PKCE for OAB

PKCE for OAB's OIDC client cannot currently be configured via YAML / setup_configuration. If it ever needs to be enabled, toggle it via the Django admin UI on the `OIDCClient` admin page or directly on the underlying `OIDCClient` DB row. The PodiumD-level `keycloak-podiumd-realm-config.yaml` PKCE consistency check does not apply to OAB; `openarchiefbeheer.configuration.pkceEnabled` is reserved for future use and is a no-op for 4.7.0.

### Manual workaround on a stuck cluster

If a deploy has already pushed a broken `openarchiefbeheer-configuration` ConfigMap and the Job is in `BackoffLimitExceeded`, patch the live cm and re-run a debug Job to validate before the next helm upgrade:

```bash
CTX=<your-aks-context>
NS=podiumd

# 1. Strip oidc_use_pkce from the live configmap
kubectl --context "$CTX" -n "$NS" get cm openarchiefbeheer-configuration -o yaml \
  | sed '/oidc_use_pkce: /d' \
  | kubectl --context "$CTX" apply -f -

# 2. Recreate the configuration Job with a debug name (the original is
#    immutable until deleted; .spec.template can't be patched)
helm --kube-context "$CTX" -n "$NS" get manifest podiumd \
  | sed -n '/^# Source: .*openarchiefbeheer.*job-config/,/^---/p' \
  | sed 's/name: openarchiefbeheer-config$/name: openarchiefbeheer-config-debug/' \
  | sed 's/app.kubernetes.io\/name: openarchiefbeheer-config$/app.kubernetes.io\/name: openarchiefbeheer-config-debug/g' \
  | kubectl --context "$CTX" apply -f -

# 3. Watch
kubectl --context "$CTX" -n "$NS" logs -f \
  job/openarchiefbeheer-config-debug

# 4. Once green, delete the debug Job and let the next helm upgrade
#    recreate the canonical openarchiefbeheer-config Job with the
#    corrected ConfigMap content
kubectl --context "$CTX" -n "$NS" delete job openarchiefbeheer-config-debug
```

### See also

- `charts/podiumd/scripts/migrate-openarchiefbeheer-2.0.0.py`
- `charts/podiumd/docs/upgrade-from-4.6.5-to-4.7.0.md` § *PKCE note*
- `charts/podiumd/docs/values-changes-4.7.0.md` § *PKCE note*
- `charts/podiumd/docs/keycloak-security-updates.md` § *PKCE Enforcement* (general PKCE wiring; OAB exception explained there too)
