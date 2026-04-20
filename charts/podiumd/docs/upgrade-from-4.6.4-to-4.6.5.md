# Upgrade guide: PodiumD 4.6.4 → 4.6.5

## Changes

### Keycloak clients added for `referentielijsten` and `openbeheer`

Both components now have a dedicated Keycloak OIDC client in the podiumd realm, consistent with all other Django-based components. The clients are registered automatically when the Keycloak realm import job runs during the upgrade.

For disabled components, the `oidcUrl` chart default is used for the redirect URI and the OIDC client secret is auto-generated (stable random, preserved across upgrades). **No environment values changes are needed unless you are enabling a component.**

#### Pre-deploy: Key Vault secrets for `openbeheer`

The following secrets are **not yet in Key Vault** for openbeheer. Add each one before deploying, even if the component stays disabled — the pipeline wiring expects them to be present:

| Key Vault secret name        | Pipeline env var               | Description                                             |
|------------------------------|--------------------------------|---------------------------------------------------------|
| `openbeheer`                 | `OPENBEHEER_DATABASE_PASSWORD` | Django database password                                |
| `openbeheer-secret-key`      | `OPENBEHEER_SECRET_KEY`        | Django secret key                                       |
| `openbeheer-oidc-secret`     | `OPENBEHEER_OIDC_SECRET`       | Keycloak OIDC client secret                             |
| `openzaak-openbeheer-secret` | `OPENZAAK_OPENBEHEER_SECRET`   | ZGW JWT secret — shared between openbeheer and openzaak |

For secrets (OIDC, ZGW JWT): `openssl rand -hex 32`  
For the Django secret key: `openssl rand -base64 50`

These are already wired in `ExternalsPodiumD/pipelines/application.yml` — you only need to create the Key Vault entries.

---

Before enabling either component, request SSC to provision a public URL and ingress for it. Set `oidcUrl` (and any other URL values in the environment values file) to the provisioned URL once SSC confirms it is available.

---

#### `referentielijsten`

When enabling (`referentielijsten.enabled: true`), set `oidcUrl` to the provisioned URL, provide the OIDC client secret, and add configuration data:

```yaml
referentielijsten:
  configuration:
    oidcUrl: https://referentielijsten.example.nl
    secrets:
      keycloak_client_secret: "REP_REFERENTIELIJSTEN_OIDC_SECRET_REP"
    data: |-
      oidc_db_config_enable: true
      oidc_db_config_admin_auth:
        items:
        - identifier: admin-oidc
          enabled: true
          oidc_rp_client_id: referentielijsten
          oidc_rp_client_secret: ${keycloak_client_secret}
          oidc_rp_scopes_list:
          - openid
          - email
          - profile
          oidc_rp_sign_algo: RS256
          endpoint_config:
            oidc_op_discovery_endpoint: https://keycloak.example.nl/realms/podiumd/
          userinfo_claims_source: id_token
          oidc_use_nonce: true
          oidc_nonce_size: 32
          oidc_state_size: 32
          username_claim:
          - sub
          groups_claim:
          - groups
          claim_mapping:
            first_name:
            - given_name
            last_name:
            - family_name
            email:
            - email
          sync_groups: true
          sync_groups_glob_pattern: '*'
          default_groups: []
          make_users_staff: true
          superuser_group_names:
          - administrators
```

#### `openbeheer`

When enabling (`openbeheer.enabled: true`), set `oidcUrl` to the provisioned URL, provide the OIDC client secret and ZGW JWT secret, and add configuration data:

```yaml
openbeheer:
  configuration:
    oidcUrl: https://openbeheer.example.nl
    secrets:
      keycloak_client_secret: "REP_OPENBEHEER_OIDC_SECRET_REP"
      openzaak_openbeheer_secret: "REP_OPENZAAK_OPENBEHEER_SECRET_REP"
    data: |-
      zgw_consumers_config_enable: true
      zgw_consumers:
        services:
        - identifier: openzaak-catalogi-api
          label: Open Zaak Catalogi API
          api_root: https://openzaak.example.nl/catalogi/api/v1/
          api_type: ztc
          auth_type: zgw
          client_id: openbeheer
          secret: ${openzaak_openbeheer_secret}
          user_id: openbeheer
          user_representation: Open Beheer
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
          oidc_rp_client_secret: ${keycloak_client_secret}
          oidc_rp_scopes_list:
          - openid
          - email
          - profile
          oidc_rp_sign_algo: RS256
          oidc_provider_identifier: keycloak-provider
          userinfo_claims_source: id_token
          options:
            user_settings:
              claim_mappings:
                username:
                  - sub
                first_name:
                  - given_name
                email:
                  - email
              username_case_sensitive: true
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

#### openbeheer — Open Zaak Catalogi API connection

Open Beheer connects to Open Zaak's Catalogi API via ZGW JWT authentication. Both sides must be configured when enabling openbeheer.

`REP_OPENZAAK_OPENBEHEER_SECRET_REP` maps to Key Vault secret `openzaak-openbeheer-secret` — already listed in the table above. The pipeline wiring in `application.yml` is already present; only the Key Vault entry needs to be created.

**openzaak side** — register openbeheer as an authorised application. Add to the openzaak environment values file:

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
          secret: ${openzaak_openbeheer_secret}
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

### `configuration.data` secrets: move inline tokens to `configuration.secrets`

All Maykin applications resolve `${VAR_NAME}` references inside `configuration.data` at job runtime (via `envsubst` or `django-setup-configuration`'s built-in substitution). The correct pattern is:

```yaml
<component>:
  configuration:
    secrets:
      my_secret: "REP_MY_SECRET_REP"   # injected as env var into the config job pod
    data: |-
      some_field: ${my_secret}          # resolved at runtime
```

Existing environment values files place `REP_..._REP` tokens **inline** in `configuration.data` strings. These are replaced by the pipeline's `patch_values.py` before Helm renders. Both approaches work; moving secrets to `configuration.secrets` is the cleaner long-term pattern.

#### Migration script

`charts/podiumd/scripts/migrate-configuration-secrets.py` automates this migration:

1. Finds all `REP_..._REP` tokens inside every `configuration.data` block
2. Creates `configuration.secrets` entries: `foo_bar_secret: "REP_FOO_BAR_SECRET_REP"`
3. Replaces inline tokens in `configuration.data` with `${foo_bar_secret}`

**Requirements:** `pip install ruamel.yaml` (already present in the deployment pipeline)

```bash
# Preview without writing:
python migrate-configuration-secrets.py applications/gemeenten/dim1/ontw/podiumd.yml --dry-run

# Apply in-place:
python migrate-configuration-secrets.py applications/gemeenten/dim1/ontw/podiumd.yml
```

After running, the pipeline `patch_values.py` still substitutes `REP_..._REP` tokens — now from `configuration.secrets` values instead of inline in `configuration.data`.
