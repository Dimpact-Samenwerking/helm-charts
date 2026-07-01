# Deploying Zaakbrug (Frank!Framework console)

Zaakbrug is a Frank!Framework application that bridges legacy zaaksystemen to
the ZGW APIs. It ships as the umbrella sub-chart `wearefrank/zaakbrug` and is
**disabled by default** — enable it explicitly per environment with
`zaakbrug.enabled: true`.

> The sub-chart was introduced in 4.7.2 — see
> `docs/upgrade-from-4.7.1-to-4.7.2.md` for the original change. This document
> is the generic, end-to-end deploy guide.

## Quick reference

| Item | Value |
|------|-------|
| Chart key | `zaakbrug` |
| Enabled by default | `false` |
| Sub-chart | `wearefrank/zaakbrug` `2.3.27` (Frank!Framework `ff-common`) |
| Application image | `wearefrank/zaakbrug:1.26.14` (mirror to `acrprodmgmt.azurecr.io` for prod) |
| Namespace / workload | `podiumd` / Deployment `podiumd-zaakbrug` |
| Service | `podiumd-zaakbrug:80` → container port `8080` |
| JVM heap | `Xms=Xmx=4G` (`zaakbrug.frank.memory.{minimum,maximum}`) |
| K8s resources | requests `250m`/`5Gi`, limits `2`/`6Gi` |
| Keycloak client | `zaakbrug` (OIDC — console SSO) |
| Key Vault secrets | `zaakbrug`, `zaakbrug-oauth-client-secret`, `zaakbrug-zaken-api-jwt-password` |
| Console URL | `https://<env>-zaakbrug.<gemeente-domain>` |

Enabling Zaakbrug touches **four parties**: SSC (database + Key Vault),
the values file, the deploy pipeline, and the customer (DNS). All four are
required before the console comes up cleanly and redirects to Keycloak.

---

## 1. Create the database

Create a PostgreSQL database and user on the shared PG server (same pattern as
the other PodiumD component databases — `openzaak`, `openklant`, `ita`, …):

- Database name: `zaakbrug`
- Owner role: `zaakbrug`
- Default privileges on the role for the `public` schema
- TLS enforced by the server (the values use `ssl: true`)
- **Provision at the minimum tier.** Zaakbrug stores only Frank!Framework
  metadata + transient message-processing state — no high-volume tables.

Store the database password in Key Vault as `zaakbrug` (see step 2).

---

## 2. Key Vault secrets

Add three secrets to the per-environment Key Vault (via the standard
`keyvault.tfvars` `random_password` + `azurerm_key_vault_secret` loop, which
generates a 32-char value once and never overwrites it):

| Key Vault secret | Purpose | Pipeline env-var binding |
|---|---|---|
| `zaakbrug` | Postgres password for the `zaakbrug` DB user | `ZAAKBRUG_DATABASE_PASSWORD` |
| `zaakbrug-oauth-client-secret` | Keycloak `zaakbrug` client secret (console SSO + KC realm-config seed) | `ZAAKBRUG_OAUTH_CLIENT_SECRET` |
| `zaakbrug-zaken-api-jwt-password` | JWT password for Zaakbrug's outbound Zaken-API credentials | `ZAAKBRUG_ZAKEN_API_JWT_PASSWORD` |

The values file references these via the `REP_ZAAKBRUG_DATABASE_PASSWORD_REP`,
`REP_ZAAKBRUG_OAUTH_CLIENT_SECRET_REP` and
`REP_ZAAKBRUG_ZAKEN_API_JWT_PASSWORD_REP` placeholders, which `patch_values.py`
substitutes at deploy time from the env-var bindings above.

> The **OAuth client secret must be identical** on both sides: the Keycloak
> `zaakbrug` client (server-side, seeded from this secret) and the Frank console
> (client-side, see `frank.environmentVariables` in step 3). Both read the same
> `zaakbrug-oauth-client-secret`, so this is automatic — do not diverge them.

---

## 3. Add values to the environment values file

Two blocks in `applications/gemeenten/<gemeente>/<env>/podiumd.yml`.

### 3a. Keycloak client (under `keycloak.config.clients:`)

```yaml
keycloak:
  config:
    clients:
      # ... existing clients ...
      zaakbrug:
        name: Zaakbrug Frank!Framework console
        enabled: true
        secret: "REP_ZAAKBRUG_OAUTH_CLIENT_SECRET_REP"
        oidcUrl: "https://<env>-zaakbrug.<gemeente-domain>"   # the console host
```

The umbrella realm-config registers a confidential client with
`redirectUris=<oidcUrl>/*` and a protocol mapper that flattens the client roles
into a top-level `roles` claim (Frank reads `authoritiesClaimName=roles`).

### 3b. Top-level `zaakbrug:` block

```yaml
zaakbrug:
  enabled: true
  staging:
    enabled: false            # block the bundled bitnami/redis transitive dep
  image:
    registry: acrprodmgmt.azurecr.io   # or docker.io/wearefrank for the public image
    repository: zaakbrug
    tag: "1.26.14"
  resources:
    requests: { cpu: 250m, memory: 5Gi }
    limits:   { cpu: "2",  memory: 6Gi }
  frank:
    memory:
      percentage: false
      minimum: 4G
      maximum: 4G
    dtap:
      stage: "TST"            # DEV / TST / ACC / PRD per environment
    credentials:
      secret: "zaakbrug-secrets"          # rendered by the umbrella chart
      key: "credentials.properties"
    zakenApi:
      jwt:
        username: "zaakbrug"
        password: "REP_ZAAKBRUG_ZAKEN_API_JWT_PASSWORD_REP"
    # --- Keycloak console SSO (REQUIRED) -----------------------------------
    # Dotted property keys: Frank binds these directly. UPPER_SNAKE env-vars
    # do NOT bind to these camelCase properties via Spring relaxed binding.
    # The chart has no template for them, so they MUST be supplied here —
    # WITHOUT them the console starts with no auth provider and serves its
    # system information openly (no redirect to Keycloak). See Troubleshooting.
    environmentVariables:
      application.security.console.authentication.type: "OAUTH2"
      application.security.console.authentication.provider: "custom"
      application.security.console.authentication.clientId: "zaakbrug"
      application.security.console.authentication.clientSecret: "REP_ZAAKBRUG_OAUTH_CLIENT_SECRET_REP"
      application.security.console.authentication.issuerUri: "https://<keycloak-host>/realms/podiumd"
      application.security.console.authentication.authorizationUri: "https://<keycloak-host>/realms/podiumd/protocol/openid-connect/auth"
      application.security.console.authentication.tokenUri: "https://<keycloak-host>/realms/podiumd/protocol/openid-connect/token"
      application.security.console.authentication.userInfoUri: "https://<keycloak-host>/realms/podiumd/protocol/openid-connect/userinfo"
      application.security.console.authentication.jwkSetUri: "https://<keycloak-host>/realms/podiumd/protocol/openid-connect/certs"
      application.security.console.authentication.userNameAttributeName: "preferred_username"
      application.security.console.authentication.scopes: "openid,profile,email,roles"
      application.security.console.authentication.authoritiesClaimName: "roles"
  connections:
    create: true
    jdbc:
      - name: "jdbc/podiumd"   # must equal jdbc/podiumd — Narayana looks it up by this default
        type: postgresql
        host: psql-<env>-<gemeente>.postgres.database.azure.com
        port: "5432"
        database: zaakbrug
        username: zaakbrug
        password: "REP_ZAAKBRUG_DATABASE_PASSWORD_REP"
        ssl: true              # YAML boolean — NOT the string "true" (see Troubleshooting)
```

> **`ssl` must be an unquoted YAML boolean.** The `ff-common` template renders
> `sslMode` via `ternary "REQUIRE" "DISABLE" (.ssl | default false)`, and the
> sprig `ternary` requires a real bool as its third argument. `ssl: "true"`
> (quoted string) fails the whole helm render with
> `wrong type for value; expected bool; got string`.

---

## 4. Open Zaak must trust the `zaakbrug` client

Zaakbrug authenticates to the Zaken API with the `zaakbrug` JWT client, so
register it in Open Zaak's autorisaties seed (the `openzaak.configuration.data`
blob). Add a `zaakbrug` entry to **both**:

- `vng_api_common_credentials` — `identifier: zaakbrug`, `secret:
  REP_ZAAKBRUG_ZAKEN_API_JWT_PASSWORD_REP` (must match
  `zaakbrug.frank.zakenApi.jwt.password`).
- `vng_api_common_applicaties` — a new `uuid`, `client_ids: [zaakbrug]`,
  `heeft_alle_autorisaties: true`, `label: Zaakbrug`.

Re-run the Open Zaak configuration job after editing.

---

## 5. Update the deploy pipeline

Three pipeline changes (e.g. ExternalsPodiumD `pipelines/application.yml`):

### 5a. Register the wearefrank helm repo

Before the `helm dependency build` / `helm install|upgrade` step:

```bash
helm repo add wearefrank https://wearefrank.github.io/charts --force-update
helm repo update
```

### 5b. Bind the three Key Vault secrets

Add the env-var bindings (consumed by `patch_values.py`):

```yaml
ZAAKBRUG_DATABASE_PASSWORD: $(zaakbrug)
ZAAKBRUG_OAUTH_CLIENT_SECRET: $(zaakbrug-oauth-client-secret)
ZAAKBRUG_ZAKEN_API_JWT_PASSWORD: $(zaakbrug-zaken-api-jwt-password)
```

### 5c. Post-deploy mount patch (required for console SSO)

The umbrella chart renders ConfigMap `zaakbrug-oauth-role-mapping` (the files
`oauth-role-mapping.properties` and `RoutingProfiles.json`, **both required by
Frank at startup**). The upstream `wearefrank/zaakbrug` chart has **no
`extraVolumes`/`extraVolumeMounts` support**, so this ConfigMap must be mounted
into the Deployment by a post-deploy `kubectl patch`:

```bash
kubectl -n podiumd patch deployment podiumd-zaakbrug --type strategic --patch '
spec:
  template:
    spec:
      volumes:
        - name: oauth-role-mapping
          configMap: { name: zaakbrug-oauth-role-mapping }
      containers:
        - name: zaakbrug
          volumeMounts:
            - { name: oauth-role-mapping, mountPath: /opt/frank/resources/oauth-role-mapping.properties, subPath: oauth-role-mapping.properties }
            - { name: oauth-role-mapping, mountPath: /opt/frank/resources/RoutingProfiles.json, subPath: RoutingProfiles.json }
'
kubectl -n podiumd rollout status deployment podiumd-zaakbrug --timeout=5m
```

> ⚠️ **Temporary workaround — only needed in the current Zaakbrug version.**
> Once the upstream `wearefrank/zaakbrug` chart supports
> `extraVolumes`/`extraVolumeMounts`, move the mount into the values block and
> drop both this patch step and the crash-loop it works around. Track this as a
> follow-up with wearefrank and remove the workaround at the chart upgrade.

> **Deploy without `helm --wait`/`--atomic`** while the patch workaround is in
> place. With `--wait`/`--atomic` helm blocks on (or rolls back) the
> un-mounted, crash-looping pod before the patch can run. Deploy the release,
> run the patch, then gate health with the `rollout status` above.

---

## 6. Keycloak realm config (automatic)

When `zaakbrug.enabled: true`, the umbrella chart renders automatically:

- the `zaakbrug` Keycloak client (step 3a) into the podiumd realm import;
- ConfigMap `zaakbrug-oauth-role-mapping` (mounted in step 5c);
- Secret `zaakbrug-secrets` (`credentials.properties` with the Zaken-API JWT).

The Frank→Keycloak role mapping defaults to (`zaakbrug.oauthRoleMapping`):

| Frank console role | Keycloak client role |
|---|---|
| `IbisAdmin` | `administrators` |
| `IbisTester` | `zaakbrug_admin` |
| `IbisDataAdmin` | `dataadmin` |

---

## 7. Add a DNS record (customer)

Create a CNAME for the console host (pattern `<env>-zaakbrug.<gemeente-domain>`,
e.g. `ontw-zaakbrug.dimpact.nl`) pointing at the **Azure Application Gateway**
load balancer that terminates ingress for the cluster (the same LB the other
PodiumD services CNAME to). The Gateway API `HTTPRoute` for this host has no
externally reachable hostname without it, and **OAuth2 callbacks from Keycloak
will fail**. cert-manager issues the TLS certificate automatically once the
CNAME resolves.

---

## 8. Deploy and verify

1. Deploy the chart (see deploy-method note in step 5c).
2. The pod takes ~2 minutes to start (Frank!Framework JVM, 4G heap). Expect
   `podiumd-zaakbrug` `1/1 Running`.
3. Verify the console redirects to Keycloak — from inside the pod:

   ```bash
   kubectl -n podiumd exec deploy/podiumd-zaakbrug -c zaakbrug -- \
     curl -sI -o /dev/null -w '%{http_code} %{redirect_url}\n' http://localhost:8080/iaf/gui
   ```

   Expected: `302 http://localhost:8080/iaf/gui/oauth2/authorization/custom`,
   which in turn `302`s to `https://<keycloak-host>/realms/podiumd/protocol/openid-connect/auth?...`
   (Authorization-Code + PKCE).

---

## Console login and access

**The zaakbrug console has no local username or password.** Authentication is
delegated to Keycloak via OAuth2 SSO (the `frank.environmentVariables` block in
step 3b). Users log in with their **normal Keycloak account** in the `podiumd`
realm — the same identity they use for the other PodiumD applications. The chart
does not provision any standalone console credential.

Do not confuse these secrets with a login — none of them is a human password:

| Secret | What it is | Not |
|---|---|---|
| `zaakbrug-oauth-client-secret` | OAuth2 *client* secret (app ↔ Keycloak) | a user password |
| `zaakbrug` (DB) | Postgres password for the `zaakbrug` DB user | a console login |
| `zaakbrug-zaken-api-jwt-password` | JWT for outbound Zaken-API calls | a console login |

### Who can log in

Access is gated by **Keycloak client roles** on the `zaakbrug` client. A user
only reaches the console if their account holds one of the mapped client roles
(step 6). The role travels in the `roles` claim (client-role → top-level `roles`
protocol mapper, step 3a); Frank reads it via `authoritiesClaimName=roles` and
resolves the console role through `RoutingProfiles.json` /
`oauth-role-mapping.properties`:

| Keycloak `zaakbrug` client role | Frank console role | Grants |
|---|---|---|
| `administrators` | `IbisAdmin` | full admin |
| `zaakbrug_admin` | `IbisTester` | test/observe |
| `dataadmin` | `IbisDataAdmin` | data admin |

A Keycloak user **without** one of these roles authenticates successfully but is
denied by Frank (no matching routing profile).

### Grant a user access

In the Keycloak admin console for the `podiumd` realm:

1. **Clients → `zaakbrug` → Roles** — confirm `administrators` / `zaakbrug_admin`
   / `dataadmin` exist (seeded by the realm import, step 6).
2. **Users → _<user>_ → Role mapping → Assign role** — filter by the `zaakbrug`
   client and assign the appropriate client role (directly, or via a group /
   composite realm role your gemeente already uses).
3. The user opens `https://<env>-zaakbrug.<gemeente-domain>/iaf/gui`, is
   redirected to Keycloak, and logs in with **their own Keycloak username and
   password**. After consent they land in the console with the mapped role.

> There is no break-glass local account. If Keycloak is unreachable the console
> cannot be logged into — this is by design.

---

## Troubleshooting

### Console opens with system information, no Keycloak login

The exact symptom of an incomplete config. The console reaches `200` and serves
Frank system info instead of redirecting to Keycloak. Two independent causes —
check both:

1. **Missing `frank.environmentVariables` console keys** (step 3b). Without
   `application.security.console.authentication.*`, Frank has no OAuth provider
   configured and `/iaf/gui/oauth2/authorization/custom` returns `404`. This is
   independent of `application.security.http.authentication` (which may stay
   `false`).
2. **`zaakbrug-oauth-role-mapping` not mounted** (step 5c). The post-deploy
   patch did not run.

Reproduce/confirm:

| State | `/iaf/gui` | `…/oauth2/authorization/custom` |
|---|---|---|
| console keys present + mounted | `302` → oauth2 → Keycloak | `302` → Keycloak |
| console keys absent | `200` open console | `404` |

### `wrong type for value; expected bool; got string`

```
template: podiumd/charts/zaakbrug/charts/ff-common/templates/_configmap.context.yaml:
executing "ff-common.configmap.context.tpl" at <false>: wrong type for value; expected bool; got string
```

`connections.jdbc[].ssl` is a quoted string (`"true"`). Use the unquoted YAML
boolean `ssl: true` (step 3b).

### Pod CrashLoopBackOff immediately after deploy

The `oauth-role-mapping.properties` / `RoutingProfiles.json` files are not
present at `/opt/frank/resources/` — the post-deploy mount patch (step 5c) has
not been applied. Frank requires both at startup once OAuth is enabled. Apply
the patch; the pod recovers.

### helm reports the deploy as "failed" but the pod is up

A side effect of `helm --wait`/`--atomic` blocking on the pod that crash-loops
until the mount patch runs. Deploy without `--wait`/`--atomic` and gate health
with `kubectl rollout status` after the patch (step 5c).

---

## Related documentation

- `docs/upgrade-from-4.7.1-to-4.7.2.md` — original sub-chart introduction.
- `docs/enabling-pabc.md` — comparable opt-in component enablement guide.
