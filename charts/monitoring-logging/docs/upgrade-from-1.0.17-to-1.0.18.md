# Upgrade guide: monitoring-logging 1.0.17 → 1.0.18

## Summary of changes

One line: Grafana no longer requests the `offline_access` OIDC scope. This
repairs Grafana login on every environment running podiumd 4.9.1 or later,
where logging in is currently impossible. **No component version changes.**

**Environments that pin `scopes` in their own values file must change it there
too — the chart default alone does not reach them.** That change does not
require this chart release: it can be made on the PodiumD version already
deployed. See
[What to change in the values file](#what-to-change-in-the-values-file-before-a-redeploy-of-an-existing-podiumd-version--no-chart-update-needed).

| | |
|---|---|
| Ticket | [IN-2882](https://dimpact.atlassian.net/browse/IN-2882) |
| Caused by | podiumd 4.9.1, commit `d2f92fa` ([#441](https://github.com/Dimpact-Samenwerking/helm-charts/pull/441), for [IN-2519](https://dimpact.atlassian.net/browse/IN-2519)) |
| Affected | Every environment on podiumd ≥ 4.9.1 with monitoring-logging deployed |

## The problem

podiumd 4.9.1 hardened the Keycloak realm import. `templates/keycloak-podiumd-realm-config.yaml`
sets `optionalClientScopes: *defaultOptionalClientScopes` — `[address, phone,
microprofile-jwt]` — on every client, and keycloak-config-cli applies that to
clients that already exist. The 4.9.1 upgrade therefore actively stripped
`offline_access` from the `monitoring` client.

Grafana kept asking for it:

```yaml
scopes: openid email profile offline_access roles
```

Keycloak does not ignore an optional scope it cannot grant — it rejects the
authorization request with `invalid_scope` and redirects back to Grafana with an
`error=` parameter. Grafana renders that as:

> Login failed — Login provider denied login request

No credentials are ever requested, and the Grafana log does not name the scope,
so the cause is not visible from Grafana's side.

## The change

`charts/monitoring-logging/values.yaml`:

```diff
-      scopes: openid email profile offline_access roles
+      scopes: openid email profile roles
```

`use_refresh_token: true` is unchanged. Grafana still receives a refresh token
from the ordinary authorization-code flow; it is bound to the SSO session
(`ssoSessionIdleTimeout` 1800 s, `ssoSessionMaxLifespan` 36000 s) rather than
outliving it, which is what `accessTokenLifespan: 60` needs. What
`offline_access` adds — a refresh token that keeps working after the browser
session ends — is precisely what IN-2519 set out to remove, so **the security
change stays in place**. The fix is on the Grafana side only.

## Action required

The chart default does not reach environments that set `scopes` themselves, and
every PodiumD environment does — so this chart bump alone fixes nothing in
production. Each environment's own `monitoring.yml` has to change too, and it
can change **before** and **independently of** this chart release. Full
instructions and worked examples:
[What to change in the values file](#what-to-change-in-the-values-file-before-a-redeploy-of-an-existing-podiumd-version--no-chart-update-needed).

## What to change in the values file before a redeploy of an EXISTING PodiumD version — no chart update needed

**You do not have to wait for 4.9.2, and you must not upgrade PodiumD to fix
this.** The `scopes` line is set in the environment's own values file, which
overrides whatever the chart ships. Changing it there repairs login on the
version you are running today.

This is the whole change, and it is the same on every environment:

```diff
-      scopes: openid email profile offline_access roles
+      scopes: openid email profile roles
```

| | |
|---|---|
| Chart version | unchanged — stays on whatever is deployed (1.0.13, 1.0.15, 1.0.17, …) |
| PodiumD version | unchanged — do **not** upgrade or redeploy the `podiumd` release |
| Releases to deploy | `monitoring` only |
| Other values | none — leave `use_refresh_token`, `use_pkce`, the URLs and the secret placeholders exactly as they are |

When monitoring-logging 1.0.18 is later rolled out, this line already matches
the new chart default, so the upgrade is a no-op for this setting. Making the
change now costs nothing later.

### Full example — test-rott

File: `applications/gemeenten/rott/test/monitoring.yml`

Before (line 130 in the current file):

```yaml
  grafana.ini:
    # -- Authentication and Authorization with Keycloak
    auth.generic_oauth:
      enabled: true
      name: Keycloak-podiumd
      allow_sign_up: true
      allow_assign_grafana_admin: true
      client_id: "monitoring"
      client_secret: "REP_GRAFANA_OIDC_SECRET_REP"
      scopes: openid email profile offline_access roles
      email_attribute_path: email
      login_attribute_path: username
      name_attribute_path: name
      auth_url: "https://test-keycloak.rotterdam.nl/realms/podiumd/protocol/openid-connect/auth"
      token_url: "https://test-keycloak.rotterdam.nl/realms/podiumd/protocol/openid-connect/token"
      api_url: "https://test-keycloak.rotterdam.nl/realms/podiumd/protocol/openid-connect/userinfo"
      role_attribute_path: "contains(monitoring_roles[*], 'admin') && 'Admin' || contains(monitoring_roles[*], 'editor') && 'Editor' || 'Viewer'"
      role_attribute_strict: false
      org_mapping: "*:Viewer"
      skip_org_role_sync: false
      groups_attribute_path: groups
      use_refresh_token: true
      sync_ttl: 60
      use_pkce: true
```

After — one line changed, everything else byte-for-byte identical:

```yaml
  grafana.ini:
    # -- Authentication and Authorization with Keycloak
    auth.generic_oauth:
      enabled: true
      name: Keycloak-podiumd
      allow_sign_up: true
      allow_assign_grafana_admin: true
      client_id: "monitoring"
      client_secret: "REP_GRAFANA_OIDC_SECRET_REP"
      scopes: openid email profile roles
      email_attribute_path: email
      login_attribute_path: username
      name_attribute_path: name
      auth_url: "https://test-keycloak.rotterdam.nl/realms/podiumd/protocol/openid-connect/auth"
      token_url: "https://test-keycloak.rotterdam.nl/realms/podiumd/protocol/openid-connect/token"
      api_url: "https://test-keycloak.rotterdam.nl/realms/podiumd/protocol/openid-connect/userinfo"
      role_attribute_path: "contains(monitoring_roles[*], 'admin') && 'Admin' || contains(monitoring_roles[*], 'editor') && 'Editor' || 'Viewer'"
      role_attribute_strict: false
      org_mapping: "*:Viewer"
      skip_org_role_sync: false
      groups_attribute_path: groups
      use_refresh_token: true
      sync_ttl: 60
      use_pkce: true
```

Note `client_secret` keeps its `REP_GRAFANA_OIDC_SECRET_REP` placeholder — it is
resolved from Key Vault at deploy time and must not be filled in.

Verify afterwards, with Rotterdam's own hostnames:

```bash
KC="https://test-keycloak.rotterdam.nl"
GF="test-podiumd-logs.rotterdam.nl"
AUTH="$KC/realms/podiumd/protocol/openid-connect/auth"
RU="https%3A%2F%2F$GF%2Flogin%2Fgeneric_oauth"

# Grafana now sends the corrected scope list
curl -s -o /dev/null -w "%{redirect_url}\n" "https://$GF/login/generic_oauth" \
  | tr '&' '\n' | grep scope=

# and offline_access is still refused, so the hardening is untouched
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" \
  "$AUTH?client_id=monitoring&redirect_uri=$RU&response_type=code&scope=openid%20email%20profile%20offline_access%20roles&state=p"
```

Then log in at https://test-podiumd-logs.rotterdam.nl and run the browser checks
under [After the upgrade](#after-the-upgrade).

### Generic example — any environment

File: `applications/gemeenten/{gemeente}/{omgeving}/monitoring.yml`

```yaml
grafana:
  grafana.ini:
    auth.generic_oauth:
      enabled: true
      client_id: "monitoring"
      client_secret: "REP_GRAFANA_OIDC_SECRET_REP"

      # the only line that changes:
      #   was  scopes: openid email profile offline_access roles
      scopes: openid email profile roles

      auth_url:  "https://{keycloak-host}/realms/podiumd/protocol/openid-connect/auth"
      token_url: "https://{keycloak-host}/realms/podiumd/protocol/openid-connect/token"
      api_url:   "https://{keycloak-host}/realms/podiumd/protocol/openid-connect/userinfo"

      # leave these exactly as they are
      use_refresh_token: true
      use_pkce: true
```

Find every file that still needs it:

```bash
grep -rn "offline_access" applications/gemeenten/*/*/monitoring.yml
```

Apply it per environment, then deploy the `monitoring` release for that
environment only.

> **Do not use `yq -i` on these files.** It reformats the whole document and
> loses the comments. Edit the single line.

### Order of work

Environments already on PodiumD 4.9.1 are broken now and come first:
**test-rott**, then **acc-asse** and **acc-gron**. Everything else is still on
4.9.0 or earlier and keeps working until it upgrades — change those files
whenever convenient, but before their next PodiumD upgrade, or login breaks the
moment that upgrade lands.

## Verification

Set these to the environment you are working on:

```bash
KC="https://<keycloak-host>"; GF="<grafana-hostname>"
AUTH="$KC/realms/podiumd/protocol/openid-connect/auth"
RU="https%3A%2F%2F$GF%2Flogin%2Fgeneric_oauth"
```

### Before the upgrade — confirm the fault

```bash
# current scope list -> expect 302 with error=invalid_scope
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" \
  "$AUTH?client_id=monitoring&redirect_uri=$RU&response_type=code&scope=openid%20email%20profile%20offline_access%20roles&state=p"

# scope list after the change -> expect 200, Keycloak renders its login page
curl -s -o /dev/null -w "%{http_code}\n" \
  "$AUTH?client_id=monitoring&redirect_uri=$RU&response_type=code&scope=openid%20email%20profile%20roles&state=p"
```

On an environment still on podiumd 4.9.0 both return `200` — the fault only
appears from 4.9.1.

### After the upgrade

1. **Grafana sends the new scope list.**

   ```bash
   curl -s -o /dev/null -w "%{redirect_url}\n" "https://$GF/login/generic_oauth" \
     | tr '&' '\n' | grep scope=
   ```

   Expect `scope=openid+email+profile+roles`, without `offline_access`.

2. **Login works.** Open Grafana in a private window, click
   `Keycloak-podiumd`, sign in. Expect a dashboard. Any user in realm `podiumd`
   can do this — `allow_sign_up: true` with `org_mapping: "*:Viewer"` admits
   them as Viewer; `monitoring_roles` is only needed for Admin or Editor.

3. **The session survives on its own.** Stay logged in, idle three minutes,
   then reload or open another dashboard. You must still be logged in. The
   realm's `accessTokenLifespan` is 60 seconds, so this is what proves the
   session-bound refresh token is doing its job without `offline_access`. If
   this puts you back on the login screen, stop and report it — the assumption
   behind this fix would be wrong.

4. **The security change is untouched.** Re-run the first probe: it must still
   return `error=invalid_scope`. In the Keycloak admin console, **Clients →
   monitoring → Client scopes** must still show no `offline_access`.

### Validated on

Reproduced and fixed end to end on **ontw-dim1** (podiumd 4.9.1,
monitoring-logging 1.0.13), 2026-09-16:

| Probe | Before | After |
|---|---|---|
| `scope=… offline_access roles` | `302 error=invalid_scope` | `302 error=invalid_scope` (hardening intact) |
| `scope=openid email profile roles` | `200` | `200` |
| Grafana's own authorize URL | `scope=…+offline_access+roles` | `scope=openid+email+profile+roles` → `200` |
| Browser login + 3 min idle | login refused | succeeds, session survives |

The same two probes were run against **test-dimp** (podiumd 4.9.1,
monitoring-logging 1.0.15) and produced identical results before the change,
confirming the fault is not environment-specific.

## Rollback

Revert the `scopes` line and redeploy the monitoring release. Login breaks
again on any environment running podiumd ≥ 4.9.1, so rollback is only
meaningful on 4.9.0 and earlier.
