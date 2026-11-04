# Grafana Authentication

Grafana is configured with **Keycloak OIDC as the only login method**. Users are auto-redirected to Keycloak on every visit. No local login form is shown by default.

---

## How login works

| Scenario | Behaviour |
|---|---|
| Normal user visits Grafana | Auto-redirected to Keycloak (`oauth_auto_login: true`) |
| Local login form | Disabled (`disable_login_form: true`) |

---

## OIDC configuration (Keycloak)

The following are **chart defaults** that must be overridden per environment in `values-monitoring.yaml`:

```yaml
grafana:
  grafana.ini:
    auth.generic_oauth:
      client_id: "monitoring"
      client_secret: "${GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET}"   # inject via secret
      auth_url: "https://<keycloak-host>/realms/<realm>/protocol/openid-connect/auth"
      token_url: "https://<keycloak-host>/realms/<realm>/protocol/openid-connect/token"
      api_url: "https://<keycloak-host>/realms/<realm>/protocol/openid-connect/userinfo"
    server:
      domain: "<grafana-hostname>"
      root_url: "https://<grafana-hostname>/"
```

### Scopes — do not add `offline_access`

```yaml
scopes: openid email profile roles      # chart default
use_refresh_token: true
```

The podiumd chart removes `offline_access` from `defaultOptionalClientScopes`
and from every client's `optionalClientScopes`, so the `monitoring` client in
realm `podiumd` cannot be granted it — see
[keycloak-security-updates.md](../../podiumd/docs/apps/keycloak/keycloak-security-updates.md).

Keycloak does not ignore an unavailable optional scope; it **refuses the whole
authorization request** with `invalid_scope` and redirects back to Grafana with
an `error=` parameter, which Grafana renders as *"Login failed — Login provider
denied login request"*. Every user is locked out, and nothing in the Grafana log
says the scope is the cause.

Grafana does not need the scope. `use_refresh_token: true` still receives a
refresh token from the ordinary authorization-code flow; that token is bound to
the SSO session (`ssoSessionIdleTimeout`, `ssoSessionMaxLifespan`) instead of
outliving it, which is all that `accessTokenLifespan: 60` requires. What
`offline_access` adds is a refresh token that keeps working after the browser
session ends — which is exactly what the security change set out to remove.

If you override `scopes` per environment, keep `offline_access` out of the list.

**Verifying the scope list against a live realm** — unauthenticated, read-only:

```bash
KC="https://<keycloak-host>"; GF="<grafana-hostname>"
AUTH="$KC/realms/podiumd/protocol/openid-connect/auth"
RU="https%3A%2F%2F$GF%2Flogin%2Fgeneric_oauth"

# the scope list the chart ships -> expect HTTP 200 (Keycloak renders its login page)
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" \
  "$AUTH?client_id=monitoring&redirect_uri=$RU&response_type=code&scope=openid%20email%20profile%20roles&state=p"

# with offline_access -> expect 302 and error=invalid_scope
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" \
  "$AUTH?client_id=monitoring&redirect_uri=$RU&response_type=code&scope=openid%20email%20profile%20offline_access%20roles&state=p"
```

### Recreated Keycloak accounts — `oauth_allow_insecure_email_lookup`

```yaml
auth:
  oauth_allow_insecure_email_lookup: true   # chart default
```

Grafana links an OAuth login to a Grafana user through the Keycloak user id
(`sub`), stored in `user_auth`. Delete a user in Keycloak and create them again
and that id changes, which breaks the link permanently:

1. the new `sub` matches no `user_auth` row;
2. the fallback lookup by e-mail is skipped, because
   `oauth_allow_insecure_email_lookup` defaults to `false` upstream, which
   leaves the lookup params empty for OAuth clients;
3. creating the user fails, because `LoginConflict` still finds the old row
   holding that e-mail.

Grafana logs the pair below and renders *"Login failed — User sync failed"*. The
user is locked out on every attempt, while Entra and Keycloak both report a
successful login and an active session.

```text
logger=user.sync     level=error msg="Failed to create user" error="user not found" auth_module=oauth_generic_oauth auth_id=<new keycloak id>
logger=authn.service level=error msg="Failed to run post auth hook" error="[user.sync.internal] unable to create user: user not found"
```

With the setting enabled Grafana falls back to the e-mail address, finds the
existing user and relinks it to the new Keycloak id on the next login. No
database surgery and no break-glass admin access needed.

Upstream calls the fallback insecure because Grafana then trusts whatever
e-mail the provider sends. This chart ships it on by default, which is safe as
long as the realm meets these preconditions — check them per environment, the
chart enforces none of them:

- Keycloak is the only identity provider for the `monitoring` client.
- Self-registration is off (`registrationAllowed: false`) and duplicate e-mail
  addresses are refused (`duplicateEmailsAllowed: false`), so an address in use
  by an active user cannot be claimed by someone else.
- Users cannot set their own e-mail address. The `podiumd` realm's user profile
  currently grants `edit: [admin, user]` on the `email` attribute and does not
  require verification, so this precondition is **not** met out of the box.

That last point is the residual risk: a deleted account releases its e-mail
address, and a user who can edit their own address can take it over. On the
next login the fallback links them to the departed user's Grafana account.
Roles and the Grafana admin flag are re-read from the token claims on every
login (`role_attribute_path`, `skip_org_role_sync: false`) rather than from the
Grafana user row, so no roles are gained, but team memberships and explicit
folder or dashboard permissions sit on the Grafana user and do carry over, as
do that user's dashboards and preferences.

PodiumD accepts this risk and keeps self-service e-mail editing: it takes an
authenticated user in the realm, the account they target has to be gone, and
what carries over is one departed colleague's dashboards and teams in a
monitoring tool — no roles, no admin rights, no access to any other component.
Weighed against the alternative, where every recreated account needs manual
repair in the Grafana database through break-glass access, the fallback wins.

An environment that wants it closed anyway can make `email` admin-only in the
realm's user profile, or set `oauth_allow_insecure_email_lookup: false` and
accept the manual repair.

**Verifying it is applied:**

```bash
kubectl -n <monitoring-ns> exec deploy/<release>-grafana -c grafana -- \
  grep -n insecure_email /etc/grafana/grafana.ini
```

---

**Role mapping** (from chart defaults — adjust if your Keycloak roles differ):

```text
contains(monitoring_roles[*], 'admin')  → Grafana Admin
contains(monitoring_roles[*], 'editor') → Editor
(no match)                              → Viewer
```

Assign roles in Keycloak by adding `monitoring_roles` as a client claim containing `admin` or `editor`.

### Secret for OAuth client secret

```bash
kubectl create secret generic grafana-oauth \
  --namespace <monitoring-ns> \
  --from-literal=client_secret="<your-client-secret>"
```

```yaml
# values-monitoring.yaml
grafana:
  envFromSecret: grafana-oauth
```

---

## Session lifetime

Grafana does **not** request the `offline_access` scope from Keycloak (as of chart
1.0.17) — the `monitoring` Keycloak client stopped granting it (podiumd chart PR
#441, see `docs/apps/keycloak/keycloak-security-updates.md` § "Offline Access
Disabled"), so a persistent refresh token was never actually available to renew
the login silently. `use_refresh_token` is `false` to match.

Instead, how long a user stays logged in without being sent back to Keycloak is
controlled entirely by **Grafana's own session cookie**, via two `auth.*`
settings (chart defaults shown — Grafana's own upstream defaults):

```yaml
grafana:
  grafana.ini:
    auth:
      login_maximum_inactive_lifetime_duration: 7d   # idle timeout
      login_maximum_lifetime_duration: 30d            # absolute session cap
```

If operators are being redirected to Keycloak more often than acceptable, raise
these in `values-monitoring.yaml` (e.g. `30d` / `90d`) rather than trying to
restore `offline_access` — the Keycloak client no longer grants it, so setting
`use_refresh_token: true` again would have no effect without also reverting the
`monitoring` client's scopes on the podiumd side.

---

## Break-glass access (Keycloak unavailable)

By default there is no local login. If you need emergency access when Keycloak is down:

**Before an incident** — set a known admin password:

```bash
kubectl create secret generic grafana-admin \
  --namespace <monitoring-ns> \
  --from-literal=admin-user=admin \
  --from-literal=admin-password="<strong-password>"
```

```yaml
# values-monitoring.yaml
grafana:
  admin:
    existingSecret: grafana-admin
    userKey: admin-user
    passwordKey: admin-password
```

> Store this password in your team's vault. Without it the auto-generated password is unknown.

**During an incident** — temporarily re-enable the login form via a patch:

```bash
# Enable the login form without a full Helm upgrade
kubectl patch configmap <release>-grafana \
  --namespace <monitoring-ns> \
  --type merge \
  -p '{"data":{"grafana.ini":"[auth]\ndisable_login_form = false\n"}}'

kubectl rollout restart deployment/<release>-grafana -n <monitoring-ns>
```

Then log in at `https://<grafana-hostname>/login` with `admin` / vault password.

Revert with a normal `helm upgrade` after the incident.

---

## Checklist

- [ ] `client_id` and `client_secret` set per environment
- [ ] `auth_url` / `token_url` / `api_url` pointing to correct Keycloak realm
- [ ] `server.domain` and `root_url` set to actual hostname
- [ ] `grafana-admin` secret created with a known password stored in vault
- [ ] `grafana.admin.existingSecret` set in `values-monitoring.yaml`
- [ ] Keycloak client `monitoring` created with `monitoring_roles` claim mapper
- [ ] Grafana redirect URI `https://<hostname>/login/generic_oauth` added to Keycloak client `monitoring`
- [ ] `scopes` does not contain `offline_access` (chart default is already correct)
- [ ] `auth.oauth_allow_insecure_email_lookup` is `true` (chart default), so a recreated Keycloak account does not lock the user out
