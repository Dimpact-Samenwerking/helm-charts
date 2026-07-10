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
      # Role in the 'pabc' Keycloak client that grants management UI access.
      # Must match the client role created by the realm config (always "administrator").
      functioneelBeheerderRole: administrator
      # Must match the protocol mapper claim name on the 'pabc' Keycloak client.
      roleClaimType: roles
      nameClaimType: preferred_username
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

## 8. Post-install: seed PABC role mappings (automated)

After the first successful deploy, the PABC database must be seeded with:
- The ZAC application roles (`behandelaar`, `beheerder`, `coordinator`, `raadpleger`, `recordmanager`)
- Functional roles that map 1:1 to the Keycloak group names in the `podiumd` realm
- A domain and mappings that authorise each group for its intended ZAC roles

**Important:** The `pabc-migrations` job seeds the application with the name `"zac"`, but ZAC always sends `application-name="zaakafhandelcomponent"` to the PABC API. Without renaming the application, all ZAC authorisation calls return empty results. The init job below corrects this.

### Automated approach (recommended)

Run the PABC init job from `podiumd-infra`:

```bash
kubectl delete job post-deployment-pabc-init -n podiumd --ignore-not-found
kubectl apply  -f kubernetes/post-deployment-setup/post-deployment-pabc-init-job.yml
kubectl logs   -n podiumd -l job-name=post-deployment-pabc-init --follow
```

The job is idempotent and safe to re-run. It performs the following SQL operations:
1. Renames application `"zac"` → `"zaakafhandelcomponent"` (matches `APPLICATION_NAME_ZAC` constant in ZAC source)
2. Adds missing application roles: `behandelaar`, `beheerder`, `coordinator`, `raadpleger`, `recordmanager`
3. Renames functional role `"administrator"` → `"administrators"` (must match Keycloak group name)
4. Adds functional roles for each Keycloak group: `behandelaars`, `beheerders`, `coordinators`, `raadplegers`, `recordmanagers`
5. Creates domain `"Podiumd"`
6. Creates mappings with `is_all_entity_types=true` (covers all zaaktypen):

| Keycloak group | ZAC application roles |
|---|---|
| `administrators` | all roles |
| `behandelaars` | `behandelaar`, `raadpleger` |
| `coordinators` | `coordinator`, `behandelaar`, `raadpleger` |
| `recordmanagers` | `recordmanager`, `coordinator`, `behandelaar`, `raadpleger` |
| `beheerders` | `beheerder`, `coordinator`, `behandelaar`, `raadpleger` |
| `raadplegers` | `raadpleger` |

> **Note on `domein_elk_zaaktype`:** This role is deprecated in ZAC (annotated `@Deprecated`) and is not seeded by the init job. The `is_all_entity_types=true` flag in the mappings already covers all zaaktypen without it.

### Manual approach (fallback)

If you prefer to configure role mappings through the PABC management UI:

1. Open `https://pabc.<env-domain>` in a browser
2. Log in with a user who is a member of the `administrators` Keycloak group
3. Configure the group → role mappings per the table above

You still need to fix the application name and seed the application roles, which requires running the init job or manually executing its SQL.

### Verify ZAC integration

After seeding, verify the PABC API returns groups for a ZAC role:

```bash
kubectl run tmp-verify --rm -i --restart=Never --image=curlimages/curl:8.6.0 -n podiumd -- \
  curl -s -H "X-API-KEY: <pabc-api-key>" \
  "http://pabc/api/v1/groups?application-name=zaakafhandelcomponent&application-role-name=behandelaar&entity-type-id=test&entity-type=ZAAKTYPE"
# Expected: {"groups":[{"name":"behandelaars",...}]}
```

Then verify ZAC can reach PABC:
1. In ZAC, open a zaak of the e2e zaaktype and confirm the behandelaar assignment works
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
| PABC API returns `{"groups":[]}` for any role query | Application name mismatch: DB has `"zac"`, ZAC sends `"zaakafhandelcomponent"` | Run `post-deployment-pabc-init-job.yml` — it renames the application and seeds all required roles and mappings |
| ZAC authorisation works for no groups / all users denied | PABC DB has no role mappings | Run `post-deployment-pabc-init-job.yml` to seed functional roles, domain, and mappings |
| Keycloak clients `pabc` / `pabc-keycloak-admin` not created | `global.configuration.enabled` is `false`, or job ran before `pabc.enabled` was set | Set `global.configuration.enabled: true` with `pabc.enabled: true` and redeploy; if a partial run already created the clients with wrong config, also set `global.configuration.overwrite: true` |
| Pod stuck in `Pending` on aks-blue cluster | Missing `nodeSelector` | Ensure `pabc.nodeSelector: kubernetes.azure.com/mode: user` is set in the values file |
