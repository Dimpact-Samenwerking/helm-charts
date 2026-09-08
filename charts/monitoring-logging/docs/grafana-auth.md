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
