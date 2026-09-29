# Open Beheer — Basics

## Management summary

Open Beheer is the administration console for the case-type catalogues that drive
"zaakgericht werken". Municipal functional administrators use it to create and maintain
case-types, document-types and object schemas in one place, instead of editing them through
the raw Open Zaak and Objecttypen admin screens. It is part of PodiumD because every other
component (ZAC, Open Formulieren, Open Inwoner) depends on well-maintained catalogi, and
Open Beheer makes that maintenance manageable. To run it needs a PostgreSQL database, a
small Azure file share, Redis, a Keycloak client and API credentials for Open Zaak,
Objecttypen, and Objecten. Its footprint is small: two lightweight web pods plus an nginx sidecar,
roughly 250–270 MiB memory each and near-idle CPU.

## What it is

- Upstream: Maykin Media [`open-beheer`](https://github.com/maykinmedia/open-beheer), a
  Django application. New in PodiumD 4.8.0 (IN-2157), **disabled by default**
  (`openbeheer.enabled: false`).
- Image: `maykinmedia/open-beheer:0.9.1`; nginx sidecar `nginxinc/nginx-unprivileged:1.31.4`
  (shared `global.images.nginx`, digest-pinned).
- Delivered as a vendored sub-chart dependency (`openbeheer` v0.1.3, repository
  `@maykinmedia`).
- Role: admin/management UI on top of the ZGW APIs — manages zaaktypes and
  informatieobjecttypes via the Open Zaak **Catalogi** API, object schemas via the
  **Objecttypen** API, and reads retention schedules from the public **Selectielijst** API.
- Runtime components:
  - web Deployment, `replicaCount: 2` (uWSGI; the chart forces `UWSGI_MASTER=1` — see
    known issues)
  - nginx sidecar serving static/media in front of uWSGI
  - `django-setup-configuration` Job on install/upgrade
    (`openbeheer.configuration.job.enabled: true`)
- Runs as non-root uid `1000`, all capabilities dropped.

## Required resources

### Database

PostgreSQL, yes — database `openbeheer`, user `openbeheer` on the shared Azure Database
for PostgreSQL Flexible Server. Unlike apps that use the `<component>` Secret
(`DB_PASSWORD`) + ConfigMap (`DB_HOST`/`DB_NAME`/`DB_USER`) contract, Open Beheer is wired
directly through chart values: `openbeheer.settings.database.{host,port,username,password,name,sslmode}`
(`sslmode` defaults to `prefer`, port `5432`). The password is pipeline-injected from Key
Vault (convention: `openbeheer-db-admin-<env>`). Database and user are provisioned by the
per-gemeente environment deployment, not by this chart.

### Storage

Yes — a 1 GiB `ReadWriteMany` Azure Files PVC shared by both replicas, rendered by
`charts/podiumd/templates/openbeheer-storage.yaml`:

- Static PV `<namespace>-openbeheer` (`file.csi.azure.com`), reclaim policy **Retain**,
  `helm.sh/resource-policy: keep` — PV, PVC and share survive `helm uninstall`. No dynamic
  provisioning: the Azure file share must pre-exist.
- Share name from `openbeheer.persistentVolume.volumeAttributeShareName: openbeheer`;
  storage class `podiumd-standard`; PVC name `openbeheer`
  (`openbeheer.persistence.existingClaim`); size `openbeheer.persistence.size: 1Gi`.
- Mount options `uid=1000`/`gid=1000` match the container user; media lives under
  `openbeheer.persistence.mediaMountSubpath: openbeheer/media`.

### Routing / exposure (NGINX Gateway Fabric)

Public. In Dimpact environments an HTTPRoute `hr-openbeheer-nginx` on Gateway
`public-gateway` (namespace `ingress-basic`, gatewayClass `nginx`) routes
`<env>-openbeheer.<gemeente>.nl` (e.g. `ontw-openbeheer.assen.nl`) to the app's ClusterIP
service. The HTTPRoute and DNS record are created by the per-gemeente environment
deployment (ADO `ExternalsPodiumD`), not by this chart. The public hostname must equal the
host in `openbeheer.configuration.oidcUrl` — the realm-config job derives the Keycloak
redirect URIs (`{oidcUrl}/*`) from it. For non-NGF environments the sub-chart also ships an
optional classic Ingress template (`openbeheer.ingress.*`, disabled by default) — see
[openbeheer.md](openbeheer.md).

### Other dependencies

- **Redis**: shared `redis-ha` at `redis-ha-master.podiumd.svc.cluster.local:6379`,
  **db 17** for both `default` and `axes` caches (`openbeheer.settings.cache.*`); db 18 is
  reserved for Celery but unused — Open Beheer runs no Celery worker. Allocation table:
  `docs/apps/redis/redis-ha-databases.md`.
- **Keycloak**: OIDC client `openbeheer` on realm `podiumd`, created automatically by the
  realm-config job; secret from `openbeheer.configuration.secrets.keycloak_client_secret`
  (Key Vault `openbeheer-oidc-secret`). Optional PKCE via
  `openbeheer.configuration.pkceEnabled`.
- **Open Zaak**: ZGW consumer with client id `openbeheer` (client-credentials JWT), secret
  in `openbeheer.configuration.secrets.openzaak_openbeheer_secret`; registered in the
  Open Zaak admin so the Catalogi API accepts Open Beheer.
- **Objecttypen**: API token (`auth_type: api_key`) in
  `openbeheer.configuration.secrets.objecttypen_openbeheer_token`; token holder registered
  in the Objecttypen admin.
- **Objecten**: API token (`auth_type: api_key`) in
  `openbeheer.configuration.secrets.objecten_openbeheer_token`; token holder registered in
  the Objecten admin with `is_superuser: true`.
- **Selectielijst**: public `https://selectielijst.openzaak.nl/api/v1/`, no auth.
- **SMTP**: optional, `openbeheer.settings.email.*` (defaults `localhost:25`).
- Django `SECRET_KEY` via `openbeheer.settings.secretKey` (pipeline-injected).

## CPU and memory

Chart defaults (`charts/podiumd/values.yaml`; Open Beheer has **no** section in
`docs/misc/resource-overview.md`):

| Container | CPU request | CPU limit | Memory request | Memory limit |
|---|---|---|---|---|
| web (x2) | not set (burstable) | not set | not set (burstable) | not set |
| nginx sidecar | 10m | not set | 16Mi | not set |
| configuration job | not set (burstable) | not set | not set (burstable) | not set |

Observed usage (2026-07-10, `kubectl top pods -n podiumd`): on aks-blue-ontw-dimp the two
web pods use ~4m CPU and 249–269 MiB memory each, the nginx sidecar ~1m/4Mi. Not deployed
on accp at capture time. CPU is essentially idle at dev load; memory is steady around
250–270 MiB per web pod. Before enabling Open Beheer, configure requests and limits for every
container. A production baseline is 50m CPU / 384Mi memory requested and 250m CPU / 512Mi
memory limited for each web pod, 10m / 16Mi requested and 50m / 64Mi limited for nginx, and
50m / 128Mi requested and 100m / 256Mi limited for the configuration job. Adjust these values
with production workload measurements.

## Integrating Open Beheer as a new app

1. **Provision the database**: create database `openbeheer` and user `openbeheer` on the
   shared PostgreSQL Flexible Server; store the password in Key Vault as
   `openbeheer-db-admin-<env>`.
2. **Create the Azure file share**: share `openbeheer` (1 GiB) in the storage account the
   cluster-wide CSI credential (`persistentVolume.nodeStageSecretRefName` /
   `...Namespace`) authenticates against — the PV is static, the share must pre-exist.
3. **Provision Key Vault secrets**: Django `SECRET_KEY` (`openssl rand -base64 50`),
   Keycloak client secret `openbeheer-oidc-secret` (`openssl rand -hex 32`), Open Zaak ZGW
   secret, Objecten API token and Objecttypen API token (all `openssl rand -hex 32`).
4. **Enable and configure** in the environment values file:

   ```yaml
    openbeheer:
      enabled: true
      image:
        repository: acrprodmgmt.azurecr.io/maykinmedia/open-beheer
      nodeSelector:
        kubernetes.azure.com/mode: user
      nginx:
        image:
          repository: acrprodmgmt.azurecr.io/nginxinc/nginx-unprivileged
      settings:
        allowedHosts: "openbeheer.example.nl,.svc.cluster.local"
        database:
          name: openbeheer
          username: openbeheer
          password: "REP_OPENBEHEER_DATABASE_PASSWORD_REP"
        secretKey: "REP_OPENBEHEER_SECRET_KEY_REP"
        email:
          host: mail.example.nl
          defaultFrom: "noreply@<gemeente>.nl"
        environment: dimpact-dimp-ontw
      configuration:
        enabled: true
        oidcUrl: "https://openbeheer.example.nl"
        secrets:
          keycloak_client_secret: "REP_OPENBEHEER_OIDC_SECRET_REP"
          openzaak_openbeheer_secret: "REP_OPENZAAK_OPENBEHEER_SECRET_REP"
          objecttypen_openbeheer_token: "REP_OBJECTTYPEN_OPENBEHEER_TOKEN_REP"
          objecten_openbeheer_token: "REP_OBJECTEN_OPENBEHEER_TOKEN_REP"
        data: |
          oidc_db_config_enable: true
          oidc_db_config_admin_auth:
            providers:
              - identifier: keycloak-provider
                oidc_use_nonce: true
                oidc_nonce_size: 32
                oidc_state_size: 32
                endpoint_config:
                  oidc_op_discovery_endpoint: "https://keycloak.example.nl/realms/podiumd/"
            items:
              - identifier: admin-oidc
                enabled: true
                oidc_rp_client_id: openbeheer
                oidc_rp_client_secret: {value_from: {env: keycloak_client_secret}}
                oidc_rp_scopes_list:
                  - openid
                  - email
                  - profile
                  - roles
                oidc_rp_sign_algo: RS256
                oidc_provider_identifier: keycloak-provider
                userinfo_claims_source: id_token
                options:
                  user_settings:
                    claim_mappings:
                      username:
                        - preferred_username
                      first_name:
                        - given_name
                      last_name:
                        - family_name
                      email:
                        - email
                  groups_settings:
                    claim_mapping:
                      - groups
                    sync: true
                    sync_pattern: "*"
                    default_groups: []
                    make_users_staff: true
                    superuser_group_names:
                      - administrators
          zgw_consumers_config_enable: true
          zgw_consumers:
            services:
              - identifier: objecttypen-service
                label: Objecttypen API
                api_root: "https://objecttypen.example.nl/api/v2/"
                api_type: orc
                auth_type: api_key
                header_key: Authorization
                header_value: "Token REP_OBJECTTYPEN_OPENBEHEER_TOKEN_REP"
              - identifier: objecten-service
                label: Objecten API
                api_root: "https://objecten.example.nl/api/v2/"
                api_type: orc
                auth_type: api_key
                header_key: Authorization
                header_value: "Token REP_OBJECTEN_OPENBEHEER_TOKEN_REP"
              - identifier: catalogi-service
                label: Open Zaak - Catalogi API
                api_root: "https://openzaak.example.nl/catalogi/api/v1/"
                api_type: ztc
                auth_type: zgw
                client_id: openbeheer
                secret: {value_from: {env: openzaak_openbeheer_secret}}
              - identifier: selectielijst-service
                label: Open Zaak (public) - Selectielijst API
                api_root: "https://selectielijst.openzaak.nl/api/v1/"
                api_type: orc
                auth_type: no_auth
          api_configuration_enabled: true
          api_configuration:
            selectielijst_service_identifier: selectielijst-service
            objecttypen_service_identifier: objecttypen-service
     ```

   Secrets inside `configuration.data` use django-setup-configuration's
   `value_from: {env: VAR}` pattern; the Objecttypen and Objecten `Authorization: Token ...`
   headers are exceptions and keep inline `REP_..._REP` tokens.
5. Configure the matching peer services (openzaak, objecttypen, objecten):
   **objecttypen side** — register `openbeheer-token`. `token:` is a plain scalar (no prefix), so `value_from` applies directly:

   ```yaml
   objecttypen:
     configuration:
       secrets:
         objecttypen_openbeheer_token: "REP_OBJECTTYPEN_OPENBEHEER_TOKEN_REP"
       data: |-
          tokenauth_config_enable: true
          tokenauth:
            items:
              - identifier: openbeheer-token
                token: {value_from: {env: objecttypen_openbeheer_token}}
                contact_person: Open Beheer
                email: openbeheer@example.com
                organization: Open Beheer
                application: Open Beheer
                administration: Open Beheer
   ```

   **objecten side** — register `openbeheer-token` with **`is_superuser: true`** so it can read/write across all object types:

   ```yaml
   objecten:
     configuration:
       secrets:
         objecten_openbeheer_token: "REP_OBJECTEN_OPENBEHEER_TOKEN_REP"
       data: |-
          tokenauth_config_enable: true
          tokenauth:
            items:
              - identifier: openbeheer-token
                token: {value_from: {env: objecten_openbeheer_token}}
                contact_person: Open Beheer
                email: openbeheer@example.com
                application: Open Beheer
                is_superuser: true
   ```

   **openzaak side** — register openbeheer as an authorised application with full admin rights:

   ```yaml
   openzaak:
     configuration:
       secrets:
         openzaak_openbeheer_secret: "REP_OPENZAAK_OPENBEHEER_SECRET_REP"
       data: |-
          vng_api_common_applicaties_config_enable: true
          vng_api_common_applicaties:
            items:
              - uuid: 3690fccd-b625-4896-8829-992b14bca77a
                client_ids:
                  - openbeheer
                label: Open Beheer
                heeft_alle_autorisaties: true
          vng_api_common_credentials_config_enable: true
          vng_api_common_credentials:
            items:
              - identifier: openbeheer
                secret: {value_from: {env: openzaak_openbeheer_secret}}
   ```

6. **Keycloak client**: created automatically by the realm-config job from
   `configuration.oidcUrl`; populate `openbeheer-oidc-secret` **before** the first deploy
   or the job generates a random secret you must reconcile.
7. **Register API consumers**: in Open Zaak, add a ZGW application/credential for client id
   `openbeheer` with the ZGW secret; in Objecttypen, create a token-authorised user holding
   the API token; in Objecten, create a token-authorised user with `is_superuser: true`.
8. **DNS + HTTPRoute**: have the environment deployment create the
   `<env>-openbeheer.<gemeente>.nl` DNS record and the HTTPRoute on `public-gateway`; the
   hostname must match `configuration.oidcUrl`.
9. **Verify**: configuration Job completes (`kubectl -n podiumd get jobs -l
   app.kubernetes.io/name=openbeheer` → 1/1); 2/2 pods Ready with 0 restarts (uWSGI master
   fix active: `kubectl -n podiumd get cm openbeheer -o jsonpath='{.data.UWSGI_MASTER}'`
   → `1`); browse to `https://<env>-openbeheer.<gemeente>.nl/admin/` and confirm the Keycloak
   redirect; in the UI confirm the Catalogi, Objecttypen, Objecten and Selectielijst services
   resolve and catalogi load from Open Zaak.

## Related documents

- [openbeheer.md](openbeheer.md) — full enablement guide: resource checklist (DB, file
  share, Key Vault entries), declarative configuration via django-setup-configuration,
  secrets handling, storage details and validation steps.
- [openbeheer-known-issues.md](openbeheer-known-issues.md) — the uWSGI master-process
  restart trap in open-beheer 0.9.1 and earlier (why `settings.uwsgi.master: "1"` must stay set).
