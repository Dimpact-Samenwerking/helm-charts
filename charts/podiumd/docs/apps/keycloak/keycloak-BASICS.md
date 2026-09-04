# Keycloak — Basics

## Management summary

Keycloak is the central login system of PodiumD. Municipal employees and
administrators sign in once, and every other PodiumD application (case handling,
forms, customer contact, and so on) reuses that login instead of managing its own
passwords. It can also hand the actual login off to the municipality's own
Microsoft Entra ID, so staff use their normal work account. Keycloak is a core
component that is always part of a PodiumD environment; it needs a PostgreSQL
database and two public web addresses (one for users, one for administrators).
Its footprint is modest: two server pods of roughly 2 GB memory each plus a
small operator pod.

## What it is

- Upstream project: [Keycloak](https://www.keycloak.org/) — open source
  identity and access management (SSO, OIDC, SAML, identity brokering).
- Image: `quay.io/keycloak/keycloak:26.6.4` (digest-pinned in
  `keycloak.image.tag`).
- Operator-managed: the chart does not deploy Keycloak directly. The
  `keycloak-operator` subchart (Adfinis wrapper chart 1.12.1 around the official
  operator, image `quay.io/keycloak/keycloak-operator:26.6.4`) runs the operator,
  and the umbrella chart renders a **Keycloak CR**
  (`templates/keycloak-cr.yaml`, `k8s.keycloak.org/v2beta1`) with
  `instances: 2`. The operator reconciles that CR into the actual StatefulSet.
- Role in the stack: OIDC provider for the `podiumd` realm. Every other PodiumD
  app is a **client** of this Keycloak; nothing else in the stack does its own
  authentication.
- Runtime components:
  - `keycloak-0` / `keycloak-1` — server pods (operator-managed StatefulSet),
    each with a `keycloak-builder` init container (runs `kc.sh build` into an
    `emptyDir`) and the `keycloak` main container.
  - `keycloak-operator` — operator Deployment (1 replica).
  - Bootstrap Jobs (Helm-rendered, `ttlSecondsAfterFinished` garbage-collected):
    `ensure-podiumd-admin-user` (python + psql — seeds the admin user in the
    DB), `ensure-keycloak-operator-sa` (curl — provisions the
    `keycloak-operator` service-account client),
    `import-master-realm-job-*` and `import-podiumd-realm-job-*`
    (`adorsys/keycloak-config-cli:6.5.1-26` — apply realm configuration).

## Required resources

### Database

PostgreSQL: **yes** (all Keycloak state — realms, clients, users, sessions
config — lives here). Keycloak is an **exception** to the common
`<component>` Secret/ConfigMap contract: the connection is configured in values,
not via a pre-created ConfigMap:

- `keycloak.externalDatabase.{vendor,host,port,database,user,password}` (legacy
  keys) or the newer CRD-style `keycloak.db.*` block (takes precedence via
  `coalesce`).
- The chart renders Secret `keycloak-secrets` (keys `database_username`,
  `database_password`) from `externalDatabase.user`/`.password`; the Keycloak CR
  references it via `db.usernameSecret`/`db.passwordSecret`.
- `keycloak.auth.adminPassword` **must be non-empty** or the render fails
  (guard in `templates/keycloak-secrets.yaml`). It seeds Secret
  `keycloak-podiumd-admin` (bootstrap admin) — only consumed on first boot with
  an empty database.

### Storage

None. No PVC — the `keycloak-build-data` volume is an `emptyDir` (rebuilt by
the init container on every pod start); persistent state is in PostgreSQL.

### Routing / exposure (NGINX Gateway Fabric)

Two public hostnames, both HTTPRoutes on Gateway `public-gateway` in namespace
`ingress-basic`, created by the per-gemeente environment deployment (ADO
`ExternalsPodiumD`), not by this chart:

| HTTPRoute | Hostname | Purpose |
|---|---|---|
| `hr-keycloak-nginx` | `<env>-keycloak.dimpact.nl` | Realm frontend (user logins, OIDC endpoints) |
| `hr-keycloak-admin-nginx` | `<env>-keycloak-admin.dimpact.nl` | Admin console |

Backends target the operator-created ClusterIP service `keycloak-service`
(port 8080). TLS terminates at the gateway: `keycloak.http.httpEnabled: true`
and `keycloak.proxy.headers: xforwarded`. Hostnames are set via
`keycloak.hostname.hostname` / `keycloak.hostname.admin` (fallback:
`keycloak.config.adminFrontendUrl`); the realm frontend URL is
`keycloak.config.realmFrontendUrl`.

### Other dependencies

- **SMTP** — realm mail settings under `keycloak.config.smtp` (password reset,
  notifications).
- **Microsoft Entra ID (optional)** — identity brokering via
  `keycloak.config.identityProviders` / `adminIdentityProviders` (commented
  examples in values.yaml); per-gemeente values supply clientId/clientSecret.
- **No Redis, no ClamAV, no Elasticsearch.** Clustering uses Infinispan
  (`cache: ispn`) between the two instances.
- Everything else depends on **it**: the podiumd realm import provisions OIDC
  clients for openzaak, opennotificaties, objecten, objecttypen,
  openarchiefbeheer, openklant, openformulieren, openinwoner,
  referentielijsten, openbeheer, kiss, zac (+ zac-admin), ita, pabc
  (+ pabc-admin), apisix-dashboard, plus the extra clients under
  `keycloak.config.clients` (monitoring/Grafana, datamigratie, zaakbrug).
  Client secrets live in Secret `keycloak-podiumd-realm-secrets` and are
  substituted into the realm import by keycloak-config-cli.

## CPU and memory

Chart defaults (values.yaml + resource-overview.md):

| Container | CPU request | Mem request | CPU limit | Mem limit | Values key |
|---|---|---|---|---|---|
| keycloak (main, x2) | 500m | 1700Mi | 1000m | 2Gi | `keycloak.resources` → `spec.resources` in the Keycloak CR |
| keycloak-builder (init) | 250m | 512Mi | 1000m | 1Gi | `keycloak.podTemplate.spec.initContainers` |
| keycloak-operator | 100m | 128Mi | 500m | 768Mi | `keycloak-operator.operator.resources` (limit raised from 256Mi after OOMKills, IN-2233) |
| jobs: ensure-* (curl/python/psql) | 50m | 64Mi | 200m | 128Mi | `keycloak-operator.jobs.resources` |
| jobs: import-*-realm (kc-config-cli) | 50m | 256Mi | 200m | 512Mi | `keycloak-operator.jobs.configCliResources` |

`spec.resources` in the CR is the operator's supported sizing field; the
operator's own built-in defaults (when nothing is set) are 1700Mi request / 2Gi
limit, memory only — the chart sets these explicitly and adds the 500m CPU
request.

**Observed usage** (kubectl top, 2026-07-10): ontw `keycloak-0` 3m/538Mi,
`keycloak-1` 3m/531Mi, operator 3m/245Mi; accp `keycloak-0` 8m/620Mi,
`keycloak-1` 3m/602Mi, operator 3m/287Mi. Idle SSO load sits well inside the
defaults. resource-overview.md flags **Increase for production**: memory
request 2Gi, limit 3Gi for environments with many realms or high SSO load (CPU
limit intentionally not set — burstable). A PDB with `minAvailable: 1` is
recommended for the 2-replica server.

## Integrating Keycloak as a new app

Keycloak is a core component: it ships enabled in every PodiumD environment.
"Integrating a new app" with Keycloak normally means **adding an OIDC client to
the `podiumd` realm** (via the realm import or the admin console), *not*
deploying Keycloak again. Standing up Keycloak in a fresh environment:

1. Provision the PostgreSQL database (Azure Database for PostgreSQL Flexible
   Server) and set `keycloak.externalDatabase.host/database/user/password`
   (or the `keycloak.db.*` block) in the environment values.
2. Set the mandatory values: `keycloak.auth.adminPassword` (render fails if
   empty), `keycloak.hostname.hostname` / `keycloak.hostname.admin`,
   `keycloak.config.realmFrontendUrl` / `keycloak.config.adminFrontendUrl`,
   `keycloak.config.smtp.*`, and
   `keycloak-operator.jobs.ensureOperatorSa.clientSecret` (without it the
   realm-import jobs do not render).
3. Deploy; the operator reconciles the Keycloak CR into `keycloak-0`/`-1` and
   the bootstrap jobs run in order: `ensure-podiumd-admin-user` (seeds the
   admin user directly in the DB), `ensure-keycloak-operator-sa`, then
   `import-master-realm-job-*` and `import-podiumd-realm-job-*`
   (keycloak-config-cli, authenticating as the `keycloak-operator` client).
   Realm imports re-run automatically when the realm config or client-secret
   inputs change (checksum-suffixed job names).
   The import jobs talk to Keycloak via the in-cluster service
   (`http://keycloak-service:8080`) by default — NOT the public admin host,
   which may sit behind a gateway IP-allowlist that does not include the
   cluster egress IP (symptom: `HTTP 403 Forbidden` from nginx at token
   grant, import pods in a retry loop). Override with
   `keycloak-operator.jobs.keycloakUrl` if the jobs must use another URL.

   The same allowlist trap applies to every other in-cluster consumer of the
   Keycloak **admin surface** (`/admin/*` is typically filtered on BOTH the
   admin host and the realm host, since Keycloak serves the admin REST API on
   any hostname). Per component:
   - **PABC** — builds its admin-REST base and token endpoint directly from
     `pabc.settings.oidc.authority` (no OIDC discovery for those). Point it
     at the in-cluster service: `http://keycloak-service:8080/realms/podiumd`
     plus `pabc.settings.oidc.requireHttps: false`. Browser-facing endpoints
     still resolve to the realm's public `frontendUrl` via discovery.
   - **ITA** — `ita.web.oidc.authority` is used for OIDC discovery/login
     only (no admin REST) and has no requireHttps override, so use the
     public **realm** host (`https://<env>-keycloak.dimpact.nl/realms/podiumd`),
     never the admin host.
   - **ZAC** — its Keycloak admin client is built from `AUTH_SERVER`
     (`zac.auth.server`), the same value that drives browser login redirects,
     so it CANNOT be pointed at the internal service. On environments that
     IP-filter `/admin`, the cluster egress IP must be in the allowlist for
     ZAC's user/group lookups to work.
4. DNS + HTTPRoutes: point `<env>-keycloak.dimpact.nl` and
   `<env>-keycloak-admin.dimpact.nl` at the public gateway and have the
   environment deployment create `hr-keycloak-nginx` /
   `hr-keycloak-admin-nginx` targeting `keycloak-service:8080`.
5. Optional: configure Entra ID brokering (`keycloak.config.identityProviders` + mappers) and per-client secrets/oidcUrls under `keycloak.config.clients`.
6. Verify: both pods pass `/health/ready` (port 9000), all four jobs
   Completed, admin console reachable on the admin hostname, `podiumd` realm
   present with the expected clients, and a dependent app (e.g. Open Zaak)
   completes an OIDC login round-trip.

## Related documents

- [keycloak-security-updates.md](keycloak-security-updates.md) — audit log of
  security-relevant realm settings (BIO 2.0 / Forum Standaardisatie mapping,
  current vs target values, where each is implemented).
- [migrating-to-keycloak-operator.md](migrating-to-keycloak-operator.md) — how
  to migrate an existing installation from the old Bitnami Keycloak chart to
  the operator-managed setup (CRDs, DB reuse, secret handling).
