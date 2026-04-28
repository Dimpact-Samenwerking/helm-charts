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
