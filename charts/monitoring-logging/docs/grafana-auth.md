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

---

**Role mapping** (from chart defaults — adjust if your Keycloak roles differ):

```
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
