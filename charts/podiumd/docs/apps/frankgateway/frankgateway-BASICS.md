# Frank!Gateway — Basics

## Management summary

Frank!Gateway is the API gateway that PodiumD applications send their outbound
API calls through, instead of calling external services (such as the national
registries for addresses, companies and persons) directly. Routing everything
through one gate gives the municipality a single place to control, limit and
monitor that outbound traffic, and one place to keep the API keys for those
external services. It is WeAreFrank's hardened build of the open-source Apache
APISIX gateway — the same product family as ZaakBrug — and it replaces both
the earlier experimental APISIX building block and the legacy api-proxy. It is
optional: the chart ships it disabled. To run, it needs no database — only a
small disk for its configuration store and, if the management screen is wanted,
a public hostname protected by the normal PodiumD login (Keycloak). Footprint:
four lightweight pods.

Since 4.8.4 it can also run as **three separate gateways**, one per kind of
traffic — inbound, outbound and between applications — so each can be secured,
scaled and monitored on its own. That is opt-in; an environment that does not
ask for it keeps exactly the single gateway described here. See
[`frankgateway-traffic-classes.md`](frankgateway-traffic-classes.md).

## What it is

Upstream: [Apache APISIX](https://apisix.apache.org/) 3.16 packaged by
[WeAreFrank](https://wearefrank.nl/) as `ghcr.io/wearefrank/frank-gateway`
("APISIX + WeAreFrank patches"), image chart-pinned at
`104@sha256:a830b9...` (`frankgateway.image.tag` in
`charts/podiumd/values.yaml`), deployed by this chart's own templates —
there is no subchart and no APISIX operator. Optional; enabled with
`frankgateway.enabled: true` (default `false`).

Introduced in 4.8.2, ported 1:1 from the manifests proven on the jim00 QA
environment. It replaces:

- the previous **`apisix` subchart** (upstream Apache chart 2.14.0) — removed
  from `Chart.yaml`; see the superseded docs under
  [`../apisix/`](../apisix/); and
- the legacy **`apiproxy`** nginx for outbound calls to BAG/Kadaster, KVK and
  BRP/Haal Centraal — reproduced as declarative APISIX routes.

Runtime components when enabled. Everything except etcd is **per traffic
class**: enabling Frank!Gateway renders one set of objects for each of
`inway`, `outway` and `internal`, named `frankgateway-<class>` with their
`-admin-credentials`, `-config`, `-dashboard`, `-shim`, `-oauth2-proxy`,
`-routes` companions. There is no unsuffixed `frankgateway` object. `<class>`
below stands for whichever of the three is meant:

- **frankgateway-\<class\>** (Deployment) — gateway data plane `:9080` + Admin API
  `:9180`, etcd-backed *traditional* mode. Admin/viewer API keys are random,
  auto-generated and upgrade-stable, per class (Secret
  `frankgateway-<class>-admin-credentials`);
  the APISIX `config.yaml` is mounted from a Secret because it embeds those
  keys (`templates/frankgateway-config.yaml`). Since 4.8.3 an optional TLS
  data-plane listener (`frankgateway.tls.enabled`, default off, port
  `frankgateway.tls.port: 9443`) can be enabled for callers behind a
  re-encrypting front door; certificates are not mounted — APISIX serves
  per-SNI certs from SSL objects in etcd, seeded via the Admin API like
  routes (deploy-side).
- **frankgateway-etcd** (StatefulSet, 1 replica, PVC) — configuration store,
  upstream `quay.io/coreos/etcd` build (no Bitnami). Shared by all instances:
  APISIX in traditional mode loads exactly the objects beneath its configured
  prefix, so a prefix per instance (`/apisix-<instance>`) isolates routes,
  consumers and SSL objects without running one etcd each.
- **frankgateway-dashboard** (Deployment) — `apache/apisix-dashboard` GUI.
  Never exposed directly; its built-in login is bypassed server-side.
- **frankgateway-oauth2-proxy + frankgateway-shim** (Deployments) — Keycloak
  SSO chain for the dashboard: oauth2-proxy (OIDC client
  `frankgateway-dashboard`, seeded via the chart realm config; session kept in
  the chart's redis) forwards to an nginx shim that logs into the dashboard
  server-side and injects the dashboard JWT, so the dashboard's own
  `admin/<random>` credential never reaches a browser
  (`templates/frankgateway-dashboard-auth.yaml`).
- **frankgateway-\<class\>-apply-routes** (hook Job, post-install/post-upgrade) —
  seeds that class's routes from `files/frankgateway/routes/<class>/`
  (route id = file name, idempotent PUTs). An instance seeds the directory
  named after its key unless `routes.dirs` says otherwise: the five routes
  replacing the legacy apiproxy live under `outway/` (BAG + three KVK) and
  `internal/` (BRP). External-API keys are injected at
  request time from env vars fed by the out-of-band Secret
  `frankgateway.apiKeys.existingSecret` — key values never land in etcd, git
  or the route JSONs. An OpenBao-backed variant (keys fetched from the
  in-cluster vault at request time) is available as
  `files/frankgateway/openbao-secret-header.lua` — a configurable function taking
  the secret path, field and header name, so one implementation covers the BAG,
  KVK and ESB-consumer call sites.

## Required resources

### Database

None — gateway configuration lives in the bundled etcd (see Storage). The
config-persistence CronJob from jim00 (Postgres snapshot/replay of GUI-created
APISIX objects) is **not** ported into the chart; it stays a deploy-side
follow-up.

### Storage

Yes, small: the etcd StatefulSet uses a `volumeClaimTemplate` PVC of **2Gi**
(`frankgateway.etcd.storage`), default storage class
(`frankgateway.etcd.storageClassName: ""`). It holds the APISIX
routes/upstreams/consumers created via Admin API or dashboard. No Azure Files
share, no chart-rendered PV.

### Routing / exposure (NGINX Gateway Fabric)

ClusterIP-only for the data plane: PodiumD apps call the gateway in-cluster on
`http://frankgateway:9080/...`; the Admin API `:9180` is never exposed. With
`frankgateway.tls.enabled: true` the Service additionally exposes
`gateway-tls` (default `:9443`) for https in-cluster calls — needed when a
re-encrypting front door (e.g. Gateway API `BackendTLSPolicy`) terminates and
re-establishes TLS towards the gateway: the wearefrank APISIX nginx template
derives `X-Forwarded-Proto` from its own inbound scheme, so a plain-http hop
would poison upstream canonical URLs (ZGW 403s on writes, broken OIDC
redirects). The per-SNI server certificates are seeded deploy-side via the
Admin API (SSL objects in etcd), not mounted by the chart. The
dashboard's public hostname (`frankgateway.dashboard.auth.hostname`) is routed
deploy-side (ADO `ExternalsPodiumD` — Gateway API HTTPRoute → service
`frankgateway-oauth2-proxy:4180`, as on jim00), or via the optional in-chart
Traefik Ingress (`frankgateway.dashboard.ingress.enabled`) for environments
without Gateway API. The gateway certificate SAN must cover the dashboard
hostname.

### Other dependencies

- **Keycloak** — OIDC client `frankgateway-dashboard` in the `podiumd` realm,
  seeded via the chart realm config (replaces jim00's
  `setup-keycloak-client.sh`); secret consumed by oauth2-proxy.
- **Redis** — the chart's shared `redis-ha` stores oauth2-proxy sessions
  (cookie-only storage drops chunked cookies behind NGF → login loops).
- **External API keys** — out-of-band Secret named by
  `frankgateway.apiKeys.existingSecret` (Key-Vault-fed, created by the
  environment deployment) with the BAG/KVK keys the routes inject at request
  time.
- **CoreDNS** — `frankgateway.dashboard.auth.dnsResolver` must be set to the
  cluster's CoreDNS ClusterIP (AKS default `10.0.0.10`; jim00 `172.16.0.10`)
  for the shim's request-time DNS re-resolution.
- **OpenBao** (optional) — alternative request-time key source via
  `files/frankgateway/openbao-secret-header.lua` — a configurable function taking
  the secret path, field and header name, so one implementation covers the BAG,
  KVK and ESB-consumer call sites.

## CPU and memory

Chart defaults:

| Container | CPU request | Mem request | CPU limit | Mem limit |
|-----------|-------------|-------------|-----------|-----------|
| frankgateway | 100m | 256Mi | 1 | 1Gi |
| frankgateway-etcd | 50m | 128Mi | 500m | 512Mi |
| frankgateway-dashboard | 50m | 128Mi | 500m | 512Mi |
| oauth2-proxy | 25m | 64Mi | 250m | 256Mi |
| shim (nginx) | 25m | 32Mi | 250m | 128Mi |
| apply-routes job | 25m | 32Mi | 250m | 128Mi |

No observed-usage numbers yet — first chart-based deployment pending (jim00
still runs the pre-chart raw manifests).

## Integrating Frank!Gateway as a new app

1. **Enable** in the gemeente values file: `frankgateway.enabled: true`.
2. **Set the per-environment must-sets**:
   `frankgateway.dashboard.auth.hostname` (public dashboard host) and
   `frankgateway.dashboard.auth.dnsResolver` (cluster CoreDNS ClusterIP).
3. **API keys Secret.** Have the environment deployment create the
   out-of-band Secret (BAG/KVK keys, Key-Vault-fed) and point
   `frankgateway.apiKeys.existingSecret` at it.
4. **Route the dashboard.** Gateway API environments: HTTPRoute →
   `frankgateway-oauth2-proxy:4180` in ADO `ExternalsPodiumD` (`infra.yml`),
   and add the hostname to the gateway certificate SAN. Otherwise set
   `frankgateway.dashboard.ingress.enabled: true`.
5. **Repoint callers.** Applications that used `apiproxy` for BAG/KVK/BRP
   egress call `http://frankgateway:9080/...` instead (route paths mirror the
   apiproxy paths; see `files/frankgateway/routes/*.json`).
6. **Verify.** `kubectl -n podiumd get jobs` — `frankgateway-apply-routes`
   must complete; `kubectl -n podiumd get pods -l app=frankgateway` all
   Running; dashboard hostname logs in via Keycloak (no dashboard login form);
   a test call through a seeded route reaches its upstream.

## Related documents

- [`frankgateway-traffic-classes.md`](frankgateway-traffic-classes.md) — running
  the gateway as three per-traffic-class instances (inway / outway / internal),
  with the architecture diagram, the NetworkPolicy model and the migration order.
- [`frankgateway-split-exploration.md`](frankgateway-split-exploration.md) — the
  feasibility assessment that design came from.
- [`../apisix/`](../apisix/) — superseded experimental upstream-APISIX
  building block docs (kept for history; both files carry a superseded
  banner).
- [`../apiproxy/apiproxy-BASICS.md`](../apiproxy/apiproxy-BASICS.md) — the
  legacy egress proxy whose routes Frank!Gateway reproduces.
- `files/frankgateway/routes/` (chart source) — the declarative route JSONs
  seeded by the apply-routes job.
