# Open Beheer — admin/management UI for the ZGW ecosystem

PodiumD 4.8.0 ships the `openbeheer` component (IN-2157) — a Django-based admin/management UI
(Maykin Media [`open-beheer`](https://github.com/maykinmedia/open-beheer)) for configuring the
typologies that drive Zaakgericht Werken. From a single console an administrator manages
case-types (`zaaktype`) and document-types (`informatieobjecttype`) through the Open Zaak
**Catalogi** API, object schemas through the **Objecttypen** API, and references retention
schedules from the public **Selectielijst** API.

Open Beheer is delivered as a vendored Helm sub-chart dependency (`openbeheer` v0.1.3, repository
`@maykinmedia`, `charts/podiumd/Chart.yaml:59-62`). It is **disabled by default**
(`openbeheer.enabled: false`) — existing environments see no change after the upgrade; the feature
is fully opt-in.

> Component dump troubles? See [`openbeheer-known-issues.md`](openbeheer-known-issues.md) for the
> uWSGI master-process restart trap. Redis database assignment is tracked in
> [`redis-ha-databases.md`](redis-ha-databases.md).

## Quick reference

| Item | Value |
|------|-------|
| Chart key | `openbeheer` |
| Sub-chart dependency | `openbeheer` v0.1.3 (`@maykinmedia`, `Chart.yaml:59-62`) |
| Application image | `maykinmedia/open-beheer:0.9.0` |
| Nginx sidecar image | `nginx:1.30.2` (digest-pinned) |
| Enabled by default | **No** (`openbeheer.enabled: false`) |
| Replicas | `2` (`openbeheer.replicaCount`) |
| Database | PostgreSQL (`openbeheer.settings.database.*`) |
| Cache | Redis HA `db 17` — both `default` and `axes` (db 18 reserved, no Celery) |
| Storage | 1 GiB RWX Azure file share `openbeheer` (`templates/openbeheer-storage.yaml`) |
| Auth | OIDC via Keycloak — client `openbeheer` on realm `podiumd` |
| API path | `/api/v1` (`openbeheer.settings.apiPath`) |
| Config tooling | `django-setup-configuration` job (on install/upgrade) |
| Security context | non-root uid `1000`, all capabilities dropped |

## Highlights

### Component dependencies

Open Beheer is a thin admin layer over other PodiumD services — it stores its own admin users and
service registry in Postgres, but the data it manages lives in the ZGW APIs:

| Dependency | Role | `zgw_consumers` identifier | Auth |
|------------|------|----------------------------|------|
| Keycloak | OIDC login / SSO for admin users | — | OIDC client `openbeheer` |
| Open Zaak (Catalogi) | zaaktypes, informatieobjecttypes | `catalogi-service` | `zgw` (client + secret) |
| Objecttypen | object type schemas | `objecttypen-service` | `api_key` |
| Selectielijst (public) | retention schedules | `selectielijst-service` | `no_auth` |
| PostgreSQL | admin users, service registry | — | username/password |
| Redis HA | session cache + rate-limit counters | — | db 17 |

### Declarative configuration (django-setup-configuration)

The runtime wiring (OIDC provider, `zgw_consumers` services, API configuration) is **not** set
through the Django admin by hand. It is declared once in `openbeheer.configuration.data` (a YAML
document) and applied by a Kubernetes Job on install/upgrade
(`openbeheer.configuration.job.enabled: true`, `ttlSecondsAfterFinished: 600`, `backoffLimit: 6`).
The job records a checksum so unchanged config is not re-applied; set
`openbeheer.configuration.overwrite: true` to force a re-apply.

Secret substitution inside `configuration.data` uses django-setup-configuration's
`value_from: {env: VAR}` pattern (v0.11.0+) — shell-style `${VAR}` references are **not** resolved
at runtime. The exception is header fields with a literal prefix (e.g.
`Authorization: Token <value>`): those must keep inline `REP_..._REP` tokens, which `patch_values.py`
replaces before Helm renders (`values.yaml:2114-2118`).

### Secrets

Sensitive values for the config job live under `openbeheer.configuration.secrets` and are injected
into the job's environment — they are **never** rendered into the ConfigMap:

| Secret | Used for |
|--------|----------|
| `keycloak_client_secret` | OIDC client secret for the `openbeheer` Keycloak client |
| `openzaak_openbeheer_secret` | ZGW (JWT) secret for the Open Zaak Catalogi service |
| `objecttypen_openbeheer_token` | API token for the Objecttypen service |

The Django `SECRET_KEY` (`openbeheer.settings.secretKey`) and the database password
(`settings.database.password`) are likewise per-environment and supplied from Key Vault via the
deploy pipeline.

### Storage

`templates/openbeheer-storage.yaml` provisions a single Azure file share (`file.csi.azure.com`) as
a `ReadWriteMany` PersistentVolume so all replicas share media:

- PV name `<namespace>-openbeheer`, capacity from `persistence.size` (1 GiB default), reclaim
  policy **Retain**, `helm.sh/resource-policy: keep` (survives `helm uninstall`).
- PVC `openbeheer` (`persistence.existingClaim`), bound to that PV, `storageClassName`
  `podiumd-standard`.
- Azure share name from `persistentVolume.volumeAttributeShareName: openbeheer`; mount options
  `uid=1000`/`gid=1000` match the container's non-root user. Media is served under
  `persistence.mediaMountSubpath: openbeheer/media`.

### uWSGI master process (required)

`open-beheer` 0.9.0's image launches uWSGI **without** `--master`, so workers that hit their
`max-requests` quota are not respawned and the container exits (code 30) roughly every 80–90 min on
probe traffic. The chart sets `openbeheer.settings.uwsgi.master: "1"` (→ `UWSGI_MASTER=1`) to fix
this. **Do not unset it.** Full analysis: [`openbeheer-known-issues.md`](openbeheer-known-issues.md).

### Other defaults

- Throttling on (`settings.throttling.enable: true`): anonymous `2500/hour`, authenticated
  `15000/hour`.
- Session cookie lifetime `900` s (`settings.sessionCookieAge`).
- Nginx sidecar serves static/media in front of uWSGI; allowed host
  `openbeheer-nginx.podiumd.svc.cluster.local`.

## Action required

Disabled by default — to enable Open Beheer in an environment:

1. **Provision a PostgreSQL database** for openbeheer and set `openbeheer.settings.database.*`
   (`host`, `name`, `username`, `password`, `port`, `sslmode`).

2. **Create the Keycloak OIDC client** `openbeheer` on realm `podiumd` (or rely on realm config
   where automated) and capture its client secret.

3. **Store secrets in Key Vault** and reference them through the pipeline:
   `settings.secretKey`, `settings.database.password`, and the three
   `configuration.secrets.*` values.

4. **Declare `configuration.data`** — the OIDC provider, `zgw_consumers` services, and
   `api_configuration`. The commented example in `values.yaml:2124-2192` is the template; fill in
   the real `api_root`s for your Open Zaak / Objecttypen endpoints.

5. **Set the enable block** in the environment values file:

   ```yaml
   openbeheer:
     enabled: true
     configuration:
       oidcUrl: https://openbeheer.<env>.example.nl
       secrets:
         keycloak_client_secret: "REP_OPENBEHEER_KEYCLOAK_CLIENT_SECRET_REP"
         openzaak_openbeheer_secret: "REP_OPENBEHEER_OPENZAAK_SECRET_REP"
         objecttypen_openbeheer_token: "REP_OPENBEHEER_OBJECTTYPEN_TOKEN_REP"
       data: |-
         oidc_db_config_enable: true
         oidc_db_config_admin_auth:
           providers:
           - identifier: keycloak-provider
             endpoint_config:
               oidc_op_discovery_endpoint: https://keycloak.<env>.example.nl/realms/podiumd/
           items:
           - identifier: admin-oidc
             enabled: true
             oidc_rp_client_id: openbeheer
             oidc_rp_client_secret: {value_from: {env: keycloak_client_secret}}
             oidc_rp_scopes_list: [openid, email, profile, roles]
             oidc_rp_sign_algo: RS256
             oidc_provider_identifier: keycloak-provider
             options:
               groups_settings:
                 claim_mapping: [groups]
                 sync: true
                 make_users_staff: true
                 superuser_group_names: [administrators]
         zgw_consumers_config_enable: true
         zgw_consumers:
           services:
           - identifier: objecttypen-service
             label: Objecttypen API
             api_root: https://objecttypen.<env>.example.nl/api/v2/
             api_type: orc
             auth_type: api_key
             header_key: Authorization
             header_value: Token REP_OBJECTTYPEN_OPENBEHEER_TOKEN_REP   # literal prefix → pipeline token
           - identifier: catalogi-service
             label: Open Zaak - Catalogi API
             api_root: https://openzaak.<env>.example.nl/catalogi/api/v1/
             api_type: ztc
             auth_type: zgw
             client_id: openbeheer
             secret: {value_from: {env: openzaak_openbeheer_secret}}
           - identifier: selectielijst-service
             label: Open Zaak (public) - Selectielijst API
             api_root: https://selectielijst.openzaak.nl/api/v1/
             api_type: orc
             auth_type: no_auth
         api_configuration_enabled: true
         api_configuration:
           selectielijst_service_identifier: selectielijst-service
           objecttypen_service_identifier: objecttypen-service
     settings:
       secretKey: "REP_OPENBEHEER_SECRET_KEY_REP"
       environment: <env-name>
       database:
         host: <pg-host>
         name: openbeheer
         username: openbeheer
         password: "REP_OPENBEHEER_DB_PASSWORD_REP"
   ```

   > `value_from: {env: VAR}` pulls from `configuration.secrets`; the literal `REP_..._REP`
   > tokens (e.g. the `Token` header) are pipeline-substituted. Mixing them is intentional — see
   > the Declarative configuration note above.

6. **Add the ingress host / DNS record** for `configuration.oidcUrl` and register the matching
   redirect URI on the Keycloak client. Enable PKCE with `configuration.pkceEnabled: true`
   (adds `oidc_use_pkce: true` requirement to `configuration.data`).

## Validation

After deploying with `openbeheer.enabled: true`:

```bash
CTX=<your-aks-context>
NS=podiumd

# 1. Config job completed
kubectl --context "$CTX" -n "$NS" get jobs -l app.kubernetes.io/name=openbeheer
# Expect: COMPLETIONS 1/1 on the configuration job

# 2. Pods up, uWSGI running with --master, no restart cycling
kubectl --context "$CTX" -n "$NS" get pods -l app.kubernetes.io/name=openbeheer
# Expect: 2/2 Ready, RESTARTS stable at 0
kubectl --context "$CTX" -n "$NS" get cm openbeheer -o jsonpath='{.data.UWSGI_MASTER}'
# Expect: "1"

# 3. Admin login reaches the OIDC flow
#    Browse to https://openbeheer.<env>.example.nl/admin/ — expect a redirect to Keycloak,
#    and after login a Django admin session (superuser if in the administrators group).
```

In the Open Beheer UI, confirm the three `zgw_consumers` services (Catalogi, Objecttypen,
Selectielijst) resolve and that catalogi/zaaktypes load from Open Zaak.
