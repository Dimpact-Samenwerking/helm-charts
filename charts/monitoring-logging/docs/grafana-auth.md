# Grafana Authentication

Grafana is configured with **Keycloak OIDC as the primary login method**. Users are auto-redirected to Keycloak on every visit. A local admin account exists as a fallback for break-glass access when Keycloak is unavailable.

---

## How login works

| Scenario | Behaviour |
|---|---|
| Normal user visits Grafana | Auto-redirected to Keycloak (`oauth_auto_login: true`) |
| Keycloak is down / unreachable | Navigate to `/login?disableAutoLogin` — local login form appears |
| Local admin login | Username `admin`, password set via secret (see below) |

> The login form is **not shown by default** but is reachable. Grafana's `oauth_auto_login` only kicks in when no `disableAutoLogin` query param is present.

---

## OIDC configuration (Keycloak)

The following are **chart defaults** that must be overridden per environment in `values-monitoring.yaml`:

```yaml
grafana:
  grafana.ini:
    auth.generic_oauth:
      client_id: "<grafana-client-id>"
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

Reference it in `values-monitoring.yaml`:

```yaml
grafana:
  envFromSecret: grafana-oauth
  # or use extraSecretMounts / env if your chart version supports it
```

---

## Local admin account (break-glass)

The Grafana Helm chart generates a random `admin` password and stores it in a Kubernetes secret (`<release>-grafana`). This password is unknown unless you set it explicitly.

**Set a known admin password** by creating a secret and referencing it:

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

> Store this password in your team's vault (Azure Key Vault, Bitwarden, etc.). It is the only way into Grafana if Keycloak is unavailable.

### Break-glass login procedure

1. Navigate to `https://<grafana-hostname>/login?disableAutoLogin`
2. Enter username `admin` and the password from the secret above
3. Restore Keycloak or perform any emergency dashboard/datasource changes
4. Log out when done — normal users are unaffected

---

## Checklist

- [ ] `client_id` and `client_secret` set per environment
- [ ] `auth_url` / `token_url` / `api_url` pointing to correct Keycloak realm
- [ ] `server.domain` and `root_url` set to actual hostname
- [ ] `grafana-admin` secret created with a known password stored in vault
- [ ] `grafana.admin.existingSecret` set in `values-monitoring.yaml`
- [ ] Keycloak client `grafana` created with `monitoring_roles` claim mapper
- [ ] Grafana redirect URI `https://<hostname>/login/generic_oauth` added to Keycloak client
