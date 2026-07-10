# ZAC (Zaakafhandelcomponent) — Basics

## Management summary

ZAC is the case-handling application of PodiumD: municipal staff use it to treat
zaken (cases) from intake to closure — picking up tasks, handling documents,
sending mail, and following the process steps that belong to each case type.
It is the primary working screen for case workers, while the actual case and
document data live in Open Zaak. To run it needs a PostgreSQL database, a
Keycloak login client, connections to the other PodiumD registers (Open Zaak,
Open Klant, Objecten) and to national APIs (BRP, BAG, KvK), plus a small Solr
search cluster for fast case searching. Footprint: one ZAC pod of roughly
1.6 GiB memory plus three Solr pods of ~0.7 GiB each; CPU usage is low outside
peak load.

## What it is

- Upstream: [infonl/dimpact-zaakafhandelcomponent](https://github.com/infonl/dimpact-zaakafhandelcomponent),
  subchart `zaakafhandelcomponent` version `1.0.251`, alias `zac` (ZAC release 5.0.1).
- Image: `ghcr.io/infonl/zaakafhandelcomponent:5.0.1` (digest-pinned in `values.yaml`).
- Role in the stack: the case-handling UI/engine for municipal staff. Process
  logic (BPMN/CMMN) runs on an embedded Flowable engine; case/document data is
  read from and written to Open Zaak via the ZGW APIs.
- Runtime components (all 1 replica by default):
  - `zac` — Java (JVM) application with an OPA sidecar (`zac.opa.sidecar: true`)
    and an `init-solr-zac-core` init container. Liveness probe deliberately uses
    `/health/ready` with `failureThreshold: 16` (see comment in `values.yaml`) as a
    workaround for hanging ZGW-API-Client connections.
  - `zac-nginx` — nginx-unprivileged front (`client_max_body_size: 150M`, matching `zac.maxFileSizeMB`).
  - `zac-office-converter` — Gotenberg document converter.
  - `signaleren` CronJob — periodic signalling job.
  - Search: `solr-operator` + `zookeeper-operator` (both watch namespace `podiumd`)
    managing `zac-solr-solrcloud` (SolrCloud, 3 nodes) and its ZooKeeper ensemble
    (1 node by default; accp runs 3). `zac.solr-operator.solr.jobs.createZacCore: true`
    creates the `zac` core.

## Required resources

### Database

- PostgreSQL: **yes**. The subchart takes credentials directly from values:
  `zac.db.host` / `zac.db.name` (default `zac`) / `zac.db.user` / `zac.db.password`.
- The ZAC database holds the application tables **and** an extra `flowable`
  schema for the embedded Flowable BPMN/CMMN engine — one database, two schemas.
- The generic per-app contract (Secret `zac` with `DB_PASSWORD`, ConfigMap `zac`
  with `DB_HOST`/`DB_NAME`/`DB_USER`, created by the per-gemeente environment
  deployment) is used by the MI export CronJob. The ZAC MI target overrides the
  dump scope to `schemas: ["flowable"]` (`mi.targets` in `values.yaml`; other
  apps default to `["public"]`).

### Storage

- ZAC itself: **no PVC** — there is no `zac-storage.yaml` template; documents are
  stored in Open Zaak, not locally.
- Solr and ZooKeeper: **persistent volumes managed by the operators** (SolrCloud
  CRD `dataStorage.persistent` and ZooKeeper `storage`), both with
  `reclaimPolicy: Retain` so PVC data survives operator scale-down/node rotation
  (defaults in `zac.solr-operator.*` — see comments in `values.yaml`).

### Routing / exposure (NGINX Gateway Fabric)

- Public at `<env>-zac.dimpact.nl` (e.g. `ontw-zac.dimpact.nl`).
- HTTPRoute `hr-zac-nginx` on Gateway `public-gateway` (namespace `ingress-basic`,
  gatewayClass `nginx`), created by the per-gemeente environment deployment
  (ADO `ExternalsPodiumD`), not by this chart. Backend: service `zac-nginx`.
- `zac.contextUrl` must be set to this public URL.

### Other dependencies

- **Keycloak**: OIDC client `zac` in realm `podiumd` (`zac.auth.*`; PKCE not yet
  supported — `pkceEnabled: false`) plus an admin client `zac-admin-client`
  (`zac.keycloak.adminClient.*`) for reading users/groups.
- **Open Zaak (ZGW APIs)**: `zac.zgwApis.url`/`urlExtern` with client id `zac` +
  secret registered in the Open Zaak Autorisaties API.
- **Open Notificaties**: `zac.notificationsSecretKey` secures the notification
  callback endpoint.
- **Open Klant**: `zac.klantinteractiesApi.url` + token.
- **Objecten / Objecttypen**: `zac.objectenApi` / `zac.objecttypenApi` (url + token).
- **Open Formulieren**: `zac.openForms.url`.
- **PABC**: `zac.pabcApi.url` + `apiKey` (role/authorisation component).
- **External APIs**: BRP (`zac.brpApi`, optional protocollering — see related doc),
  BAG (`zac.bagApi`), KvK (`zac.kvkApi`), all with API keys; typically routed via
  api-proxy.
- **SMTP**: `zac.mail.smtp.*` for outgoing mail; sender identity from
  `zac.gemeente.mail`.
- **SmartDocuments** (optional): `zac.smartDocuments.*` (disabled by default).
- **zgw-office-addin**: the Office add-in backend works against the same ZGW
  APIs/ZAC environment.
- **Redis**: not used by ZAC (no entry in the redis-ha database allocation).
- **Solr operator CRDs**: must be installed cluster-wide before enabling
  (`all-with-dependencies.yaml` v0.10.0-prerelease per the `values.yaml` comment;
  `zookeeper-operator.crd.create: false`).

## CPU and memory

Chart defaults (from `values.yaml` and `docs/resource-overview.md`):

| Container | CPU request | Mem request | CPU limit | Mem limit |
|-----------|-------------|-------------|-----------|-----------|
| zac | 100m | 1Gi | not set (burstable) | not set (burstable) |
| opa (sidecar) | 10m | 20Mi | not set (burstable) | not set (burstable) |
| init-solr-zac-core (init) | 50m | 256Mi | not set (burstable) | not set (burstable) |
| nginx | 50m | 64Mi | not set (burstable) | not set (burstable) |
| office-converter | 100m | 512Mi | not set (burstable) | not set (burstable) |
| signaleren (CronJob) | not set | not set | not set | not set |
| solr-operator | 100m | 128Mi | 500m | 256Mi |
| solrcloud node (x3) | 500m | 1Gi | 2000m | 2Gi |
| zookeeper-operator | 50m | 64Mi | 200m | 128Mi |
| zookeeper | 100m | 256Mi | 500m | 512Mi |

Solr JVM heap: `zac.solr-operator.solr.javaMem` (default `-Xms512m -Xmx768m`).

Observed usage (2026-07-10): ontw — `zac` 3m/1613Mi, nginx 1m/5Mi,
office-converter 1m/29Mi, solr x3 3–4m/707–750Mi, zookeeper 9m/111Mi.
accp — `zac` 4m/1600Mi, nginx 1m/5Mi, office-converter 1m/216Mi,
solr x3 3–6m/674–714Mi, zookeeper x3 7–9m/104–125Mi. The ZAC pod already sits
at ~1.6Gi while idle, well above its 1Gi request.

Sizing: `resource-overview.md` flags **increase for production** — ZAC:
`500m / 2Gi` request, no CPU limit; office-converter `500m / 1Gi` for large
DOCX/PDF conversion. Solr for large ZAAK indices: heap `-Xms1g -Xmx2g` with
`1000m / 3Gi` per node (container limit ~1.5x heap); ZooKeeper `200m / 512Mi`.
The signaleren CronJob has no resource settings — suggested `100m / 256Mi`.
PDBs: SolrCloud `maxUnavailable: 2`, ZooKeeper `maxUnavailable: 1` (operator
managed); the single-replica ZAC pod should not get a PDB.

## Integrating ZAC as a new app

1. **Solr operator CRDs**: install the Solr operator CRDs (and the ZooKeeper
   CRD — `zookeeper-operator.crd.create: false`) cluster-wide before enabling.
2. **Database**: provision PostgreSQL database `zac` + user; set `zac.db.host`,
   `zac.db.name`, `zac.db.user`, `zac.db.password`. The `flowable` schema for the
   embedded process engine lives in the same database. If MI exports are enabled,
   also provide the `zac` Secret (`DB_PASSWORD`) and ConfigMap
   (`DB_HOST`/`DB_NAME`/`DB_USER`).
3. **Enable and configure**: `zac.enabled: true`; set `zac.contextUrl` (public
   URL), `zac.gemeente.code`/`naam`/`mail`, `zac.organizations.bron.rsin` and
   `verantwoordelijke.rsin`, `zac.catalogusDomein`, and pin `zac.image.tag`.
4. **Keycloak**: create realm client `zac` (secret into `zac.auth.secret`,
   `zac.auth.server`/`realm` pointing at the environment's Keycloak) and admin
   client `zac-admin-client` (`zac.keycloak.adminClient.secret`).
5. **ZGW registrations**: register client id/secret from `zac.zgwApis` in the
   Open Zaak Autorisaties API; set `zac.notificationsSecretKey` for Open
   Notificaties callbacks; set tokens for `zac.objectenApi`, `zac.objecttypenApi`,
   `zac.klantinteractiesApi`.
6. **External APIs and mail**: configure `zac.brpApi` (plus protocollering if the
   BRP gateway requires it), `zac.bagApi`, `zac.kvkApi`, `zac.pabcApi`, and
   `zac.mail.smtp.*`.
7. **DNS + HTTPRoute**: create DNS `<env>-zac.dimpact.nl` and HTTPRoute
   `hr-zac-nginx` (Gateway `public-gateway`, namespace `ingress-basic`) targeting
   service `zac-nginx` via the environment deployment.
8. **Verify**: `zac`, `zac-nginx`, `zac-office-converter`, `zac-solr-solrcloud-*`
   and ZooKeeper pods Running in namespace `podiumd`; the `init-solr-zac-core`
   job created the Solr core; `/health/ready` returns UP; log in via Keycloak at
   the public URL and open a zaak to confirm Open Zaak connectivity.

## Related documents

- [zac-brp-protocollering.md](zac-brp-protocollering.md) — per-vendor BRP
  protocollering configuration (iConnect, eServices, 2Secure/EnableU) under
  `zac.brpApi.protocollering`.
