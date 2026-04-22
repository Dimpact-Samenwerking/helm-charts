# Upgrade guide: PodiumD 4.6.4 → 4.6.5

## Changes

### Keycloak clients added for `referentielijsten` and `openbeheer`

Both components now have a dedicated Keycloak OIDC client in the podiumd realm, consistent with all other Django-based components. The clients are registered automatically when the Keycloak realm import job runs during the upgrade.

For disabled components, the `oidcUrl` chart default is used for the redirect URI and the OIDC client secret is auto-generated (stable random, preserved across upgrades). **No environment values changes are needed unless you are enabling a component.**

#### Pre-deploy: Key Vault secrets for `openbeheer` and `referentielijsten`

The following secrets are **not yet in Key Vault** for the new components. Add each one before deploying, even if the component stays disabled — the pipeline wiring expects them to be present:

**`referentielijsten`:**

| secret variable name            | REP token in values file                      | Description                  |
|---------------------------------|-----------------------------------------------|------------------------------|
| `referentielijsten`             | `REP_REFERENTIELIJSTEN_DATABASE_PASSWORD_REP` | Django database password     |
| `referentielijsten-secret-key`  | `REP_REFERENTIELIJSTEN_SECRET_KEY_REP`        | Django secret key            |
| `referentielijsten-oidc-secret` | `REP_REFERENTIELIJSTEN_OIDC_SECRET_REP`       | Keycloak OIDC client secret  |

**`openbeheer`:**

| secret variable name           | REP token in values file               | Description                                                            |
|--------------------------------|----------------------------------------|------------------------------------------------------------------------|
| `openbeheer`                   | `REP_OPENBEHEER_DATABASE_PASSWORD_REP` | Django database password                                               |
| `openbeheer-secret-key`        | `REP_OPENBEHEER_SECRET_KEY_REP`        | Django secret key                                                      |
| `openbeheer-oidc-secret`       | `REP_OPENBEHEER_OIDC_SECRET_REP`       | Keycloak OIDC client secret                                            |
| `openzaak-openbeheer-secret`   | `REP_OPENZAAK_OPENBEHEER_SECRET_REP`   | ZGW JWT secret — shared between openbeheer and openzaak (admin)        |
| `objecttypen-openbeheer-token` | `REP_OBJECTTYPEN_OPENBEHEER_TOKEN_REP` | API token for openbeheer to authenticate to objecttypen (admin)        |
| `objecten-openbeheer-token`    | `REP_OBJECTEN_OPENBEHEER_TOKEN_REP`    | API token for openbeheer to authenticate to objecten (admin/superuser) |

For secrets (OIDC, ZGW JWT): `openssl rand -hex 32`  
For the Django secret key: `openssl rand -base64 50`

These are already wired in `ExternalsPodiumD/pipelines/application.yml` — you only need to create the Key Vault entries.

---

Before enabling either component, request SSC to provision a public URL and ingress for it. Set `oidcUrl` (and any other URL values in the environment values file) to the provisioned URL once SSC confirms it is available.

---

#### `referentielijsten`

When enabling (`referentielijsten.enabled: true`), set `oidcUrl` to the provisioned URL, provide the OIDC client secret, and add configuration data:

Referentielijsten only needs Keycloak OIDC — no peer ZGW services. Use the nested `providers:` / `items:` schema (older flat schema with `username_claim` at the item level is deprecated and rejected by mozilla-django-oidc-db ≥ 0.23):

```yaml
referentielijsten:
  settings:
    secretKey: "REP_REFERENTIELIJSTEN_SECRET_KEY_REP"
    database:
      password: "REP_REFERENTIELIJSTEN_DATABASE_PASSWORD_REP"
  configuration:
    oidcUrl: https://referentielijsten.example.nl
    secrets:
      keycloak_client_secret: "REP_REFERENTIELIJSTEN_OIDC_SECRET_REP"
    data: |-
      oidc_db_config_enable: true
      oidc_db_config_admin_auth:
        providers:
        - identifier: admin-oidc-provider
          oidc_use_nonce: true
          oidc_nonce_size: 32
          oidc_state_size: 32
          endpoint_config:
            oidc_op_discovery_endpoint: https://keycloak.example.nl/realms/podiumd/
        items:
        - identifier: admin-oidc
          oidc_provider_identifier: admin-oidc-provider
          enabled: true
          oidc_rp_client_id: referentielijsten
          oidc_rp_client_secret: {value_from: {env: keycloak_client_secret}}
          oidc_rp_scopes_list:
          - openid
          - email
          - profile
          - roles
          oidc_rp_sign_algo: RS256
          userinfo_claims_source: id_token
          options:
            user_settings:
              claim_mappings:
                username:
                  - preferred_username
                first_name:
                  - given_name
                last_name:
                  - family_name
                email:
                  - email
            groups_settings:
              claim_mapping:
                - groups
              sync: true
              sync_pattern: '*'
              default_groups: []
              make_users_staff: true
              superuser_group_names:
                - administrators
```

#### `openbeheer`

When enabling (`openbeheer.enabled: true`), set `oidcUrl` to the provisioned URL, provide the OIDC client secret and ZGW JWT secret, and add configuration data:

> **Note on secret substitution.** `django-setup-configuration` (v0.11.0, used by all Maykin/PodiumD Django components) resolves env vars via the `value_from: {env: VAR_NAME}` pattern only. Shell-style `${VAR}` references are **not** substituted and would end up stored literally in the database (401 `unauthorized_client` on login). Always use the `value_from` form inside `configuration.data`.
>
> **Token-prefix caveat.** When a header carries a literal prefix (e.g. `Authorization: Token <value>`), the value_from form turns the whole field into a mapping, which the upstream config loader rejects. For those fields, keep the inline `REP_..._REP` token replaced by the pipeline's `patch_values.py` before Helm renders — the example below uses this workaround for `header_value: Token …`.

Open Beheer connects to four external services. All three authenticated ones require **admin-level** access — Open Beheer manages catalogi, object types, and the objects themselves:

- **Open Zaak (all APIs incl. Catalogi)** — ZGW JWT. Key Vault secret: `openzaak-openbeheer-secret`. Registered with `heeft_alle_autorisaties: true` on openzaak (full admin across zrc/ztc/drc/brc).
- **Objecttypen API** — API key. Key Vault secret: `objecttypen-openbeheer-token`. Registered in objecttypen's `tokenauth` (objecttypen tokens are unscoped → full access).
- **Objecten API** — API key. Key Vault secret: `objecten-openbeheer-token`. Registered in objecten's `tokenauth` with `is_superuser: true` (object-type permissions don't cover "manage all types"; superuser is the only admin scope).
- **Selectielijst API** — public endpoint, no authentication required.

Both `openbeheer` **and** each peer service (openzaak, objecttypen, objecten) need matching configuration. The consolidated openbeheer block and three peer blocks follow.

```yaml
openbeheer:
  settings:
    secretKey: "REP_OPENBEHEER_SECRET_KEY_REP"
    database:
      password: "REP_OPENBEHEER_DATABASE_PASSWORD_REP"
  configuration:
    oidcUrl: https://openbeheer.example.nl
    secrets:
      keycloak_client_secret: "REP_OPENBEHEER_OIDC_SECRET_REP"
      openzaak_openbeheer_secret: "REP_OPENZAAK_OPENBEHEER_SECRET_REP"
      objecttypen_openbeheer_token: "REP_OBJECTTYPEN_OPENBEHEER_TOKEN_REP"
      objecten_openbeheer_token: "REP_OBJECTEN_OPENBEHEER_TOKEN_REP"
    data: |-
      oidc_db_config_enable: true
      oidc_db_config_admin_auth:
        providers:
        - identifier: keycloak-provider
          oidc_use_nonce: true
          oidc_nonce_size: 32
          oidc_state_size: 32
          endpoint_config:
            oidc_op_discovery_endpoint: https://keycloak.example.nl/realms/podiumd/
        items:
        - identifier: admin-oidc
          enabled: true
          oidc_rp_client_id: openbeheer
          oidc_rp_client_secret: {value_from: {env: keycloak_client_secret}}
          oidc_rp_scopes_list:
          - openid
          - email
          - profile
          - roles
          oidc_rp_sign_algo: RS256
          oidc_provider_identifier: keycloak-provider
          userinfo_claims_source: id_token
          options:
            user_settings:
              claim_mappings:
                username:
                  - preferred_username
                first_name:
                  - given_name
                last_name:
                  - family_name
                email:
                  - email
            groups_settings:
              claim_mapping:
                - groups
              sync: true
              sync_pattern: '*'
              default_groups: []
              make_users_staff: true
              superuser_group_names:
                - administrators
      zgw_consumers_config_enable: true
      zgw_consumers:
        services:
        - identifier: objecttypen-service
          label: Objecttypen API
          api_root: https://objecttypen.example.nl/api/v2/
          api_type: orc
          auth_type: api_key
          header_key: Authorization
          header_value: Token REP_OBJECTTYPEN_OPENBEHEER_TOKEN_REP   # prefix+token — pipeline-replaced
        - identifier: objecten-service
          label: Objecten API
          api_root: https://objecten.example.nl/api/v2/
          api_type: orc
          auth_type: api_key
          header_key: Authorization
          header_value: Token REP_OBJECTEN_OPENBEHEER_TOKEN_REP       # prefix+token — pipeline-replaced
        - identifier: catalogi-service
          label: Open Zaak - Catalogi API
          api_root: https://openzaak.example.nl/catalogi/api/v1/
          api_type: ztc
          auth_type: zgw
          client_id: openbeheer
          secret: {value_from: {env: openzaak_openbeheer_secret}}
        - identifier: selectielijst-service
          label: Open Zaak (public) - Selectielijst API
          api_root: https://selectielijst.openzaak.nl/api/v1/
          api_type: orc
          auth_type: no_auth
      api_configuration_enabled: true
      api_configuration:
        selectielijst_service_identifier: selectielijst-service
        objecttypen_service_identifier: objecttypen-service
```

**objecttypen side** — register `openbeheer-token`. `token:` is a plain scalar (no prefix), so `value_from` applies directly:

```yaml
objecttypen:
  configuration:
    secrets:
      objecttypen_openbeheer_token: "REP_OBJECTTYPEN_OPENBEHEER_TOKEN_REP"
    data: |-
      tokenauth_config_enable: true
      tokenauth:
        items:
        - identifier: openbeheer-token
          token: {value_from: {env: objecttypen_openbeheer_token}}
          contact_person: Open Beheer
          email: openbeheer@example.com
          organization: Open Beheer
          application: Open Beheer
          administration: Open Beheer
```

**objecten side** — register `openbeheer-token` with **`is_superuser: true`** so it can read/write across all object types:

```yaml
objecten:
  configuration:
    secrets:
      objecten_openbeheer_token: "REP_OBJECTEN_OPENBEHEER_TOKEN_REP"
    data: |-
      tokenauth_config_enable: true
      tokenauth:
        items:
        - identifier: openbeheer-token
          token: {value_from: {env: objecten_openbeheer_token}}
          contact_person: Open Beheer
          email: openbeheer@example.com
          application: Open Beheer
          is_superuser: true
```

**openzaak side** — register openbeheer as an authorised application with full admin rights:

```yaml
openzaak:
  configuration:
    secrets:
      openzaak_openbeheer_secret: "REP_OPENZAAK_OPENBEHEER_SECRET_REP"
    data: |-
      vng_api_common_applicaties_config_enable: true
      vng_api_common_applicaties:
        items:
        - uuid: 3690fccd-b625-4896-8829-992b14bca77a
          client_ids:
          - openbeheer
          label: Open Beheer
          heeft_alle_autorisaties: true
      vng_api_common_credentials_config_enable: true
      vng_api_common_credentials:
        items:
        - identifier: openbeheer
          secret: {value_from: {env: openzaak_openbeheer_secret}}
```

---

> **PKCE:** both clients are created without PKCE by default. To enable it, set `pkceEnabled: true` on the Keycloak client **and** add `oidc_use_pkce: true` under the `items` entry in `configuration.data`. Both must be set together — the chart validates this at render time.

---

#### Keycloak roles and group assignments

The following roles are created automatically in the podiumd realm:

| Client              | Role             |
|---------------------|------------------|
| `referentielijsten` | `administrators` |
| `openbeheer`        | `administrators` |

The `administrators` Keycloak group is automatically assigned these roles on import. Users in that group gain admin access to both apps.

---

### `configuration.data` secrets: use `value_from: {env: var}` inside `configuration.data`

All Maykin PodiumD Django components use `django-setup-configuration` v0.11.0, which resolves env vars **only** via the `value_from: {env: VAR_NAME}` pattern. Shell-style `${VAR}` references are **not** substituted at runtime — they land in the database as literal strings and break authentication (401 `unauthorized_client`). The correct pattern is:

```yaml
<component>:
  configuration:
    secrets:
      my_secret: "REP_MY_SECRET_REP"   # injected as env var into the config job pod
    data: |-
      some_field: {value_from: {env: my_secret}}   # resolved at runtime
```

Historical patterns you may still encounter in environment values files:

- **Inline `REP_..._REP` tokens** in `configuration.data` — replaced by the pipeline's `patch_values.py` *before* Helm renders. Still works, but puts plaintext secrets in the rendered ConfigMap.
- **`${var}` shell-style references** in `configuration.data` — does **not** work at runtime. Migrate to `value_from: {env: var}`.

Exception: when a value carries a literal prefix inside the same string (e.g. `Authorization: Token <value>`), `{value_from: {env: var}}` turns the field into a mapping and the config loader rejects it. Keep inline `REP_..._REP` tokens for those fields until upstream accepts a scalar concatenation.

#### Migration script

`charts/podiumd/scripts/migrate-configuration-secrets.py` automates this migration:

1. Finds all `REP_..._REP` tokens and `${var}` references inside every `configuration.data` block
2. Adds matching `configuration.secrets` entries for REP tokens: `foo_bar_secret: "REP_FOO_BAR_SECRET_REP"`
3. Replaces both inline REP tokens and `${var}` references in `configuration.data` with `{value_from: {env: foo_bar_secret}}`
4. Emits a warning for `Token REP_..._REP` header-value patterns (prefix+token) that need manual review.

**Requirements:** `pip install ruamel.yaml` (already present in the deployment pipeline)

```bash
# Preview without writing:
python migrate-configuration-secrets.py applications/gemeenten/dim1/ontw/podiumd.yml --dry-run

# Apply in-place:
python migrate-configuration-secrets.py applications/gemeenten/dim1/ontw/podiumd.yml
```

After running, the pipeline `patch_values.py` still substitutes `REP_..._REP` tokens — now from `configuration.secrets` values instead of inline in `configuration.data`.
