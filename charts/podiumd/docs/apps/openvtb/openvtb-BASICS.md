# Open VTB — Basics

## Management summary

Open VTB (Open Verzoeken, Taken en Berichten) is a Maykin Media component that stores
"verzoeken", "taken" and "berichten" for citizens and civil servants behind a standard API.
It is new in PodiumD 4.10.0 and **disabled by default**: environments that do not enable it
see no change. When enabled it needs a PostgreSQL database, a small Azure file share, Redis
and a Keycloak client. Its footprint is small: two lightweight web pods.

## What it is

- Upstream: Maykin Media [`open-vtb`](https://github.com/maykinmedia/open-vtb), a Django
  application. Disabled by default (`openvtb.enabled: false`).
- Image: `maykinmedia/open-vtb:0.2.0`, digest-pinned in `openvtb.image.tag`.
- Delivered as a vendored sub-chart dependency (`openvtb` v0.2.0, repository `@maykinmedia`).
- Runtime components:
  - web Deployment, `replicaCount: 2` (uWSGI, listens on container port 8000)
  - `django-setup-configuration` Job on install/upgrade
    (`openvtb.configuration.job.enabled: true`)
- Runs as non-root uid `1000`, all capabilities dropped.
- Unlike Open Beheer there is no nginx sidecar: the sub-chart Service (`openvtb`, port 80)
  fronts the Django pods directly.

## Required resources

### Database

PostgreSQL, yes. Wired through chart values (not the shared Secret/ConfigMap contract):
`openvtb.settings.database.{host,port,username,password,name,sslmode}` (`sslmode` defaults to
`prefer`, port `5432`). Database and user are provisioned by the per-gemeente environment
deployment, not by this chart; the password is pipeline-injected.

### Storage

Yes. A 1 GiB `ReadWriteMany` Azure Files PVC shared by both replicas, rendered by
`charts/podiumd/templates/openvtb-storage.yaml`:

- Static PV `<namespace>-openvtb` (`file.csi.azure.com`), reclaim policy **Retain**,
  `helm.sh/resource-policy: keep`. The Azure file share must pre-exist.
- Share name `openvtb.persistentVolume.volumeAttributeShareName: openvtb`; storage class
  `podiumd-standard`; PVC name `openvtb` (`openvtb.persistence.existingClaim`); media under
  `openvtb.persistence.mediaMountSubpath: openvtb/media`.

### Routing / exposure (NGINX Gateway Fabric)

Public. The HTTPRoute and DNS record are created by the per-gemeente environment deployment
(ADO `ExternalsPodiumD`), not by this chart, with `backendRefs` to Service `openvtb` port 80.
The public hostname must equal the host in `openvtb.configuration.oidcUrl`; the realm-config
job derives the Keycloak redirect URIs (`{oidcUrl}/*`) from it. For non-NGF environments the
sub-chart ships an optional classic Ingress (`openvtb.ingress.*`, disabled by default).

### Other dependencies

- **Redis**: shared `redis-ha`, **db 19** for `default` and `axes` caches
  (`openvtb.settings.cache.*`); db 20 holds the Celery broker/result URLs (the sub-chart requires them; no worker is deployed). See
  `docs/apps/redis/redis-ha-databases.md`.
- **Keycloak**: OIDC client `openvtb` on realm `podiumd`, created by the realm-config job
  only while `openvtb.enabled: true`; secret from
  `openvtb.configuration.secrets.keycloak_client_secret` (random when empty). Optional PKCE via
  `openvtb.configuration.pkceEnabled`.
- **SMTP**: optional, `openvtb.settings.email.*` (defaults `localhost:25`).
- Django `SECRET_KEY` via `openvtb.settings.secretKey` (pipeline-injected).
- No Open Notificaties subscription, Open Zaak or Objecten wiring is provisioned by this chart.

## CPU and memory

Chart defaults (`openvtb.resources: {}`, no section in `docs/misc/resource-overview.md`):

| Container | CPU request | CPU limit | Memory request | Memory limit |
|---|---|---|---|---|
| web (x2) | not set (burstable) | not set | not set (burstable) | not set |
| configuration job | not set (burstable) | not set | not set (burstable) | not set |

No observed usage yet. Set requests and limits per environment before enabling.

## Integrating Open VTB as a new app

1. **Provision the database**: create database and user on the shared PostgreSQL server.
2. **Create the Azure file share** `openvtb` (1 GiB) next to the other shares.
3. **Provision secrets**: Django `SECRET_KEY` (`openssl rand -base64 50`), database password,
   Keycloak client secret (`openssl rand -hex 32`).
4. **Enable and configure** in the environment values file (mandatory values: see
   `_UPGRADE_PATHS/4.9.4-to-4.10.0-values-deltas.md`):

   ```yaml
   openvtb:
     enabled: true
     image:
       repository: acrprodmgmt.azurecr.io/maykinmedia/open-vtb
     settings:
       allowedHosts: "openvtb.example.nl,openvtb.podiumd.svc.cluster.local"
       database:
         host: <pg-host>
         name: openvtb
         username: openvtb
         password: "REP_OPENVTB_DATABASE_PASSWORD_REP"
       secretKey: "REP_OPENVTB_SECRET_KEY_REP"
     configuration:
       oidcUrl: "https://openvtb.example.nl"
       secrets:
         keycloak_client_secret: "REP_OPENVTB_OIDC_SECRET_REP"
       data: |
         # django-setup-configuration, see the commented example in values.yaml
   ```

5. **Mirror the image** to the ACR via the `pipelines/images.yml` job (SSC) before deploying.
6. **DNS + HTTPRoute**: have the environment deployment create the DNS record and the
   HTTPRoute with `backendRefs` to `openvtb` port 80; the host must match `oidcUrl`.
7. **Verify**: configuration Job completes; 2/2 pods Ready; browse to
   `https://<host>/admin/` and confirm the Keycloak redirect.

## Related documents

- [`redis-ha-databases.md`](../redis/redis-ha-databases.md): Redis database allocation (db 19/20).
- [`keycloak-BASICS.md`](../keycloak/keycloak-BASICS.md): realm and OIDC clients.
- [`openbeheer-BASICS.md`](../openbeheer/openbeheer-BASICS.md): the sibling Maykin component this one is modelled on.
