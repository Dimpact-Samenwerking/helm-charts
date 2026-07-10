# ZGW Office Add-in — Basics

## Management summary

The ZGW Office Add-in lets municipal staff work with zaken without leaving Microsoft
Office: from Word or Outlook they can save and register documents (letters, e-mails,
attachments) directly into the zaakregistratie. This removes the manual detour of
downloading a file and uploading it again in ZAC or another zaak application, so
documents end up in the right zaak faster and more reliably. It is one of the
lightest components in PodiumD: two small containers (a static frontend and a small
backend), no database and no storage of its own. It only needs a public hostname, a
Microsoft Entra ID app registration for sign-in, and a connection to the ZGW APIs
(Open Zaak). Live usage is around 4 Mi (frontend) and 29 Mi (backend) of memory.

## What it is

- **Upstream project**: [infonl/zgw-office-addin](https://github.com/infonl/zgw-office-addin)
  (INFO.nl, the same developer as ZAC). Subchart `zgw-office-addin` version `0.0.89`
  (appVersion `0.2.0`), vendored in `charts/podiumd/charts/zgw-office-addin-0.0.89.tgz`.
- **Images** (chart defaults in `charts/podiumd/values.yaml`):
  - `ghcr.io/infonl/zgw-office-addin-frontend:v0.9.313@sha256:02cbd45a83f09f89b85dcd040840f9fb3e9bbadf67282edd6d258697a68684c7`
  - `ghcr.io/infonl/zgw-office-addin-backend:v0.9.313@sha256:64d49e401de5005c5f2b61c68fac72f5d7ba4f640dca5288d21f82cf57bcc8fb`
- **Role in the stack**: an Office add-in (Word/Outlook task pane). The frontend is
  an nginx container serving the add-in manifest files and static JavaScript from
  `common.frontendUrl`, and reverse-proxies API calls to the backend
  (`BACKEND_URL=http://zgw-office-addin-backend:3003`). The backend talks to the ZGW
  APIs provider (Open Zaak) to register documents against zaken.
- **Runtime components** (Deployments, 1 replica each, `fullnameOverride: zgw-office-addin`):
  - `zgw-office-addin-frontend` — nginx static/proxy, container port 8080 (8443 with
    `frontend.enableHttps`), Service `zgw-office-addin-frontend` ClusterIP port 80.
  - `zgw-office-addin-backend` — API backend, container port 3003, Service
    `zgw-office-addin-backend` ClusterIP port 3003.
- **Authentication**: Microsoft Entra ID via MSAL (`common.msalTenantId`,
  `common.msalClientId`, `backend.msalSecret`) — **not** Keycloak. This matches the
  Office/M365 identity the user is already signed in with.
- Both containers run non-root (uid 10001), read-only root filesystem, all
  capabilities dropped; liveness/readiness probes on `/health`.

## Required resources

### Database

**None.** The add-in is stateless: no PostgreSQL, no `DB_*` Secret/ConfigMap
contract. All persistent data lives in the ZGW APIs provider (Open Zaak) it writes
to.

### Storage

**None.** No PVC, no `*-storage.yaml` template in the umbrella chart; only
`emptyDir` volumes for nginx cache/tmp.

### Routing / exposure (NGINX Gateway Fabric)

- Public hostname pattern: `<env>-office-addin.dimpact.nl` (e.g.
  `ontw-office-addin.dimpact.nl`). This must equal `common.frontendUrl`, since Office
  clients fetch the manifest and static JS from it and it is the MSAL redirect URI.
- HTTPRoute `hr-zgw-office-addin-frontend` on Gateway `public-gateway`
  (namespace `ingress-basic`, gatewayClass `nginx`), backend Service
  `zgw-office-addin-frontend` port 80. Created by the per-gemeente environment
  deployment (ADO `ExternalsPodiumD`), not by this chart.
- The backend Service (`zgw-office-addin-backend:3003`) is **cluster-internal only**;
  clients reach it through the frontend nginx proxy.

### Other dependencies

- **Microsoft Entra ID**: an app registration for the add-in — tenant ID, client ID
  and a client secret (`common.msalTenantId`, `common.msalClientId`,
  `backend.msalSecret`). The frontend requests scope
  `api://<frontendUrl-host>/<clientId>/access_as_user`.
- **ZGW APIs (Open Zaak)**: `backend.zgwApis.url` (backend env `API_BASE_URL`) and
  `backend.zgwApis.secret` (backend env `JWT_SECRET`) — the secret signs the ZGW JWTs
  the backend sends, so a matching client credential must be configured in Open
  Zaak's API authorisations.
- No Redis, no Keycloak client, no ClamAV, no Elasticsearch, no RabbitMQ, no SMTP.
- The subchart's `values.schema.json` + `required` guards make
  `common.frontendUrl`, `common.msalClientId`, `common.msalTenantId`,
  `backend.msalSecret`, `backend.zgwApis.url` and `backend.zgwApis.secret` mandatory
  when the subchart is enabled (CI satisfies these via `ci/lint-values.yaml`).

## CPU and memory

Chart defaults (umbrella `values.yaml` + `docs/resource-overview.md`), default
replicas **1** per component:

| Container | CPU request | Mem request | CPU limit | Mem limit |
|-----------|-------------|-------------|-----------|-----------|
| frontend | 50m | 64Mi | — (see note) | — (see note) |
| backend | 100m | 256Mi | — (see note) | — (see note) |

> Note: `resource-overview.md` lists no limits, and the umbrella values only set
> `requests`. The vendored subchart's own defaults do include limits
> (frontend `250m / 128Mi`, backend `500m / 256Mi`) which survive the Helm values
> merge, so rendered pods carry those limits — the backend then runs with memory
> request == limit (256Mi, Guaranteed for memory).

**Observed usage** (`kubectl top pods -n podiumd`, 2026-07-10): on
`aks-blue-accp-dimp` the backend used **3m / 29Mi** and the frontend **1m / 4Mi**.
The add-in was not running on `aks-blue-ontw-dimp` at capture time (its HTTPRoute
exists there). Actual usage is a fraction of the requests; the chart defaults are
already generous for this workload and need no increase for production —
`resource-overview.md` flags nothing for this component.

## Integrating ZGW Office Add-in as a new app

1. **Create the Entra ID app registration** (per environment): note the tenant ID
   and application (client) ID, create a client secret, set the redirect URI to the
   public frontend URL, and expose the API scope `access_as_user`.
2. **Pick the public hostname** following the environment pattern, e.g.
   `https://<env>-office-addin.dimpact.nl`, and request DNS for it.
3. **Set the values** (all mandatory — the render fails without them):

   ```yaml
   zgw-office-addin:
     enabled: true
     common:
       appEnv: "Acc"                # "production" hides the env indicator in the manifest
       frontendUrl: "https://<env>-office-addin.dimpact.nl"
       msalTenantId: "<entra-tenant-id>"
       msalClientId: "<entra-client-id>"
     backend:
       msalSecret: "<entra-client-secret>"     # inject via secret management, not plaintext
       zgwApis:
         url: "<internal Open Zaak base URL>"
         secret: "<zgw-jwt-secret>"
   ```

4. **Register the client in Open Zaak**: add an API authorisation whose secret
   matches `backend.zgwApis.secret`, with rights on the Zaken/Documenten APIs the
   add-in uses.
5. **Create the HTTPRoute** via the environment deployment (`ExternalsPodiumD`):
   `hr-zgw-office-addin-frontend` on Gateway `public-gateway` (ns `ingress-basic`),
   hostname from step 2, backend Service `zgw-office-addin-frontend` port 80. Do not
   expose the backend Service.
6. **Deploy the add-in manifest to Microsoft 365**: the frontend serves the manifest
   files from `common.frontendUrl`; an M365 administrator deploys the add-in to the
   organisation (integrated apps) so it appears in users' Word/Outlook.
7. **Verify**: both pods Running in namespace `podiumd`
   (`kubectl get pods -n podiumd -l app=office-addin`), `/health` probes green,
   the manifest URL loads over the public hostname, and a test user can sign in via
   Entra ID from Word/Outlook and register a document on a zaak.

No database provisioning, Keycloak client, Open Notificaties registration or PVC is
needed for this component.
