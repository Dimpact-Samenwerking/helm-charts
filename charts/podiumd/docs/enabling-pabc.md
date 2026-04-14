# Enabling PABC (Platform Autorisatie Beheer Component)

PABC is a .NET application that manages platform authorisation. It is disabled by default and must be explicitly enabled per environment.

## Quick reference

| Item | Value |
|------|-------|
| Chart key | `pabc` |
| Enabled by default | `false` |
| Image source | `oci://ghcr.io/platform-autorisatie-beheer-component` |
| Chart version | `1.1.0` |
| Keycloak clients created | `pabc` (OIDC), `pabc-keycloak-admin` (service account) |
| ZAC integration flag | `zac.featureFlags.pabcIntegration` |

---

## 1. Create the database

Create a PostgreSQL database and user on the shared PG server (same pattern as other components):

- Database name: `pabc`
- Username: `pabc`
- Store the password in Key Vault as `pabc-db-admin-<env>` (e.g. `pabc-db-admin-johnb00`)

---

## 2. Generate secrets

Generate three random secrets (e.g. `openssl rand -base64 32`):

| Secret | Purpose |
|--------|---------|
| `PABC_OIDC_CLIENT_SECRET` | PABC app authenticates to Keycloak |
| `PABC_KEYCLOAK_ADMIN_SECRET` | PABC app calls Keycloak Admin REST API |
| `PABC_API_KEY` | ZAC calls the PABC API (`X-API-KEY` header) |

If the environment uses the SSC pipeline `REP_…_REP` placeholder pattern, store the OIDC and admin secrets in Key Vault and reference them as `REP_PABC_OIDC_SECRET_REP` and `REP_PABC_KEYCLOAK_ADMIN_SECRET_REP` in the values file. Otherwise use literal values.

---

## 3. Add values to the environment values file

Add the following block to `values-<env>.yml` (e.g. `values-johnb00.yml`):

```yaml
pabc:
  enabled: true
  settings:
    database:
      host: <shared-pg-host>   # e.g. podiumd-johnb00-pg.postgres.database.azure.com
      name: pabc
      username: pabc
      # password: injected by deploy script from Key Vault (pabc-db-admin-<env>)
    apiKeys:
      - "<PABC_API_KEY>"       # same value used in zac.pabcApi.apiKey below
    oidc:
      authority: https://<keycloak-host>/realms/podiumd
      clientId: pabc
      clientSecret: "REP_PABC_OIDC_SECRET_REP"  # or literal value if not using pipeline
      oidcUrl: https://pabc.<env-domain>
    keycloakAdmin:
      clientId: pabc-keycloak-admin
      clientSecret: "REP_PABC_KEYCLOAK_ADMIN_SECRET_REP"
  ingress:
    enabled: true
    className: traefik
    annotations:
      cert-manager.io/cluster-issuer: letsencrypt-prod
      traefik.ingress.kubernetes.io/router.entrypoints: websecure
    hosts:
      - host: pabc.<env-domain>
        paths:
          - path: /
            pathType: Prefix
    tls:
      - secretName: pabc-tls
        hosts:
          - pabc.<env-domain>
  nodeSelector:
    kubernetes.azure.com/mode: user    # required on aks-blue clusters
```

Also enable ZAC integration in the same file:

```yaml
zac:
  featureFlags:
    pabcIntegration: true
  pabcApi:
    url: http://pabc/api   # internal cluster URL (fullnameOverride is "pabc")
    apiKey: "<PABC_API_KEY>"
```

> **Note:** `oidcUrl` must exactly match the public URL of PABC (used as the Keycloak redirect URI base). A mismatch here is a common source of OIDC errors — see [Troubleshooting](#troubleshooting).

---

## 4. Update the deploy script

In `deploy-<env>.ps1`, add `pabc` to the `$DbApps` array so the password is retrieved from Key Vault:

```powershell
$DbApps = @(
    # ... existing entries ...
    "pabc",
)
```

Add the password `--set` override in the helm args section:

```powershell
$helmArgs += "--set", "pabc.settings.database.password=$($Passwords['pabc'])"
```

---

## 5. Keycloak realm config (automatic)

No manual Keycloak configuration is required. When `global.configuration.enabled: true`, the realm config job (keycloak-config-cli) automatically provisions all of the following.

### Clients created

| Client ID | Type | Purpose |
|-----------|------|---------|
| `pabc` (value of `pabc.settings.oidc.clientId`) | OIDC confidential | Used by the PABC web app to authenticate users |
| `pabc-keycloak-admin` (value of `pabc.settings.keycloakAdmin.clientId`) | Service account | Used by PABC to call the Keycloak Admin REST API to read users, groups, and roles |

#### `pabc` OIDC client details

- `redirectUris` and `webOrigins`: `https://pabc.<env-domain>/*` — derived from `pabc.settings.oidc.oidcUrl`
- Client secret: value of `pabc.settings.oidc.clientSecret` (injected as `$(KC_SECRET_PABC)`)
- Protocol mapper: maps the `pabc` client's roles into the JWT access token under the claim name **`roles`** — this must match `pabc.settings.oidc.roleClaimType` (default: `roles`)

#### `pabc-keycloak-admin` service account details

- `serviceAccountsEnabled: true` — grants it a service account in Keycloak
- Client secret: value of `pabc.settings.keycloakAdmin.clientSecret` (injected as `$(KC_SECRET_PABC_ADMIN)`)
- Realm-management roles assigned to service account: `view-users`, `view-realm`, `view-groups`

> **Important:** Both client secrets must be set in values before the first deploy. The realm config job uses them as literal secret values for the clients it creates. If the secrets are empty, the clients are created with blank secrets and login will fail.

### Client roles created

The `pabc` client gets a single role: **`administrator`**. This is the role that grants access to the PABC management UI. Its name must match `pabc.settings.oidc.functioneelBeheerderRole` (default: `administrator`).

### Group assignments (automatic)

The `administrators` Keycloak group automatically gets the `pabc.administrator` client role assigned. Any user in this group can log into and manage PABC.

### Re-provisioning

On first deploy no extra flags are needed. To force re-provisioning on a subsequent deploy (e.g. after changing `oidcUrl` or rotating secrets), set `global.configuration.overwrite: true` temporarily and redeploy.

---

## 6. Deploy

Run a normal `helm upgrade`. The `pabc-migrations` job runs automatically as part of the release and initialises the database schema.

```powershell
# Example — adjust to your deploy script pattern
.\deploy-<env>.ps1
```

Verify after deploy:
- `pabc` pod is `1/1 Running`
- `pabc-migrations-<revision>` job is `Complete`
- Keycloak clients `pabc` and `pabc-keycloak-admin` exist in the `podiumd` realm

---

## 7. Add a DNS record

Add a DNS A (or CNAME) record for `pabc.<env-domain>` pointing to the cluster's ingress IP — the same IP used by all other services on the environment.

---

## 8. Post-install: configure roles in PABC

After the first successful deploy, PABC needs to be configured to map Keycloak groups to ZAC roles. This is done through the PABC management UI and is **required** before PABC is functional for end users.

### Log in

1. Open `https://pabc.<env-domain>` in a browser
2. Log in with a user who is a member of the `administrators` Keycloak group (this group has the `pabc.administrator` role, which grants access to the management UI)

### Configure role mappings

PABC reads users and groups from Keycloak via the `pabc-keycloak-admin` service account. In the UI you configure which Keycloak groups are entitled to which ZAC roles/permissions.

The typical setup mirrors the existing Keycloak group structure:

| Keycloak group | Intended ZAC roles in PABC |
|----------------|---------------------------|
| `administrators` | All roles |
| `behandelaars` | `behandelaar`, `raadpleger`, `domein_elk_zaaktype` |
| `coordinators` | `coordinator`, `behandelaar`, `raadpleger`, `domein_elk_zaaktype` |
| `recordmanagers` | `recordmanager`, `coordinator`, `behandelaar`, `raadpleger`, `domein_elk_zaaktype` |
| `beheerders` | `beheerder`, `coordinator`, `behandelaar`, `raadpleger`, `domein_elk_zaaktype` |
| `raadplegers` | `raadpleger`, `domein_elk_zaaktype` |

> The exact role mapping depends on the municipality's authorisation requirements. The above is the standard PodiumD group/role structure.

### Verify ZAC integration

Once PABC is configured, verify ZAC can reach it:

1. In ZAC, open a zaak and check that the PABC authorisation panel loads (requires `zac.featureFlags.pabcIntegration: true` and a matching API key)
2. If ZAC shows errors, check the ZAC pod logs for `401` or connection errors to `http://pabc/api`

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `pabc-migrations` job fails on startup | PostgreSQL database or user not created | Create the `pabc` DB and user on the shared PG server before deploying |
| OIDC login redirect fails / "Invalid redirect URI" in Keycloak | `pabc.settings.oidc.oidcUrl` does not match the public PABC URL | Ensure `oidcUrl` is set to exactly `https://pabc.<env-domain>` (no trailing slash); redeploy with `global.configuration.overwrite: true` to update the Keycloak client's redirect URIs |
| Users can log in but are not recognised as admin / UI shows no management options | `functioneelBeheerderRole` mismatch or user not in `administrators` group | Verify `pabc.settings.oidc.functioneelBeheerderRole` is `administrator`; verify the user is in the `administrators` Keycloak group |
| PABC cannot load users/groups from Keycloak | `pabc-keycloak-admin` client secret wrong or service account roles missing | Check `pabc.settings.keycloakAdmin.clientSecret` matches what was provisioned; verify the service account has `view-users`, `view-realm`, `view-groups` in Keycloak |
| ZAC cannot reach PABC / authorisation calls return 401 | API key mismatch or wrong internal URL | Verify `pabc.settings.apiKeys[0]` and `zac.pabcApi.apiKey` are identical; verify `zac.pabcApi.url` is `http://pabc/api` |
| Keycloak clients `pabc` / `pabc-keycloak-admin` not created | `global.configuration.enabled` is `false`, or job ran before `pabc.enabled` was set | Set `global.configuration.enabled: true` with `pabc.enabled: true` and redeploy; if a partial run already created the clients with wrong config, also set `global.configuration.overwrite: true` |
| Pod stuck in `Pending` on aks-blue cluster | Missing `nodeSelector` | Ensure `pabc.nodeSelector: kubernetes.azure.com/mode: user` is set in the values file |
