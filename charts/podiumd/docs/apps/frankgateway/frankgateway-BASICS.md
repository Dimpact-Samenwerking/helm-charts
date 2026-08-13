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
a public hostname protected by the normal PodiumD login (Keycloak). Every part
of it runs at least twice over, so no single failure interrupts traffic:
nine lightweight pods with the management screens off, twenty-seven with all
three switched on.

Since 4.8.5 it always runs as **three separate gateways**, one per kind of
traffic — inbound, outbound and between applications — so each can be secured,
scaled and monitored on its own, and a problem with one cannot take the other
two down. See
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
  per-SNI certs from SSL objects in etcd. The chart can issue that certificate
  with cert-manager and keeps the SSL object in step with it (see
  [Certificate on the internal hop](#certificate-on-the-internal-hop)).
- **frankgateway-etcd** (StatefulSet, **3 replicas**, PVC each) — configuration
  store, upstream `quay.io/coreos/etcd` build (no Bitnami). Three because etcd
  is raft: quorum of three is two, so one member can be lost. Two would be
  worse than one. Members find each other through the headless Service
  `frankgateway-etcd-headless`, which publishes not-ready addresses so the
  cluster can form before any member is ready; `frankgateway-etcd` remains as
  the load-balanced Service for ad-hoc `etcdctl`. Shared by all instances:
  APISIX in traditional mode loads exactly the objects beneath its configured
  prefix, so a prefix per instance (`/frankgateway-<instance>`) isolates routes,
  consumers and SSL objects without running one etcd each.
- **frankgateway-dashboard** (Deployment) — `apache/apisix-dashboard` GUI.
  Never exposed directly; its built-in login is bypassed server-side.
- **frankgateway-\<class\>-oauth2-proxy + -shim** (Deployments) — Keycloak
  SSO chain for the dashboard: oauth2-proxy (OIDC client
  `frankgateway-dashboard-<class>`, one per class, seeded via the chart realm
  config; session kept in the chart's redis) forwards to an nginx shim that logs into the dashboard
  server-side and injects the dashboard JWT, so the dashboard's own
  `admin/<random>` credential never reaches a browser
  (`templates/frankgateway-dashboard-auth.yaml`).
- **frankgateway-\<class\>-apply-routes** (hook Job, post-install/post-upgrade) —
  seeds that class's routes from `files/frankgateway/routes/<class>/`
  (route id = file name, idempotent PUTs). An instance seeds the directory
  named after its key unless `routes.dirs` says otherwise: the five routes
  replacing the legacy apiproxy live under `outway/` (BAG + three KVK) and
  `internal/` (BRP). External-API keys are fetched from **OpenBao at request
  time** by `files/frankgateway/openbao-secret-header.lua` (mounted from the
  `frankgateway-lua` ConfigMap, resolved via `apisix.extra_lua_path`) — a
  configurable function taking the secret path, field and header name, so one
  implementation covers the BAG, KVK and ESB-consumer call sites. Key values
  never land in etcd, git, a ConfigMap, a Kubernetes Secret or the route JSONs;
  the pod carries only a scoped reader token. A route whose secret cannot be
  read answers **503** with a log line naming the path
  (`frankgateway.openbao.failMode: closed`) rather than passing the request on
  to be rejected as a 401, which is indistinguishable from a wrong key.

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

ClusterIP-only for the data plane: PodiumD apps call the class they mean on
`http://frankgateway-outway:9080/...` (external APIs) or
`http://frankgateway-internal:9080/...` (app-to-app); the Admin API `:9180` is
never exposed. With
`frankgateway.tls.enabled: true` the Service additionally exposes
`gateway-tls` (default `:9443`) for https in-cluster calls — needed when a
re-encrypting front door (e.g. Gateway API `BackendTLSPolicy`) terminates and
re-establishes TLS towards the gateway: the wearefrank APISIX nginx template
derives `X-Forwarded-Proto` from its own inbound scheme, so a plain-http hop
would poison upstream canonical URLs (ZGW 403s on writes, broken OIDC
redirects). The per-SNI server certificate is stored as an SSL object in etcd
rather than mounted as a file — see
[Certificate on the internal hop](#certificate-on-the-internal-hop) for how it
gets there and how it is renewed. The
dashboard's public hostname (`frankgateway.dashboard.auth.hostname`) is routed
deploy-side (ADO `ExternalsPodiumD` — Gateway API HTTPRoute → service
`frankgateway-<class>-oauth2-proxy:4180`, one per dashboard), or via the optional in-chart
Traefik Ingress (`frankgateway.dashboard.ingress.enabled`) for environments
without Gateway API. The gateway certificate SAN must cover the dashboard
hostname.

### Other dependencies

- **Keycloak** — one OIDC client per class (`frankgateway-dashboard-inway`,
  `-outway`, `-internal`) in the `podiumd` realm, seeded via the chart realm
  config (replaces jim00's `setup-keycloak-client.sh`); each secret consumed by
  that class's oauth2-proxy.
- **Redis** — the chart's shared `redis-ha` stores oauth2-proxy sessions
  (cookie-only storage drops chunked cookies behind NGF → login loops).
- **OpenBao** — **required**, not optional: it is the only source of
  external-API credentials, and `openbao.enabled: false` alongside
  `frankgateway.enabled: true` fails the render. The BAG/KVK keys live at
  `<mount>/frankgateway` (fields `bag_api_key`, `kvk_api_key`); the gateway
  reads them with a scoped token supplied out-of-band in the Secret named by
  `frankgateway.openbao.tokenSecret` (Key-Vault-fed, never minted by this
  chart — a token the chart could mint is a token the chart would store).
- **CoreDNS** — `frankgateway.dashboard.auth.dnsResolver` must be set to the
  cluster's CoreDNS ClusterIP (AKS default `10.0.0.10`; jim00 `172.16.0.10`)
  for the shim's request-time DNS re-resolution.

## Certificate on the internal hop

Inbound traffic crosses two encrypted hops: the front door (NGF) terminates the
public certificate, then re-encrypts to `frankgateway-inway:9443`. That second
hop needs its own certificate, and it is the one that historically nobody owned:
installed by hand when the environment was built, not managed by the chart, with
nothing watching the expiry date. It works perfectly until the day it does not,
and then all inbound traffic stops.

Two things have to be true for renewal to actually work, and only the first is
obvious:

1. **The certificate must be renewed.** `tls.certManager.enabled: true` has
   cert-manager issue and renew it, using the ClusterIssuer the environment
   already uses for its public certificates. `renewBefore` is 30 days, so a
   failing issuer is visible for a month before it can cause an outage.
2. **The renewed material must reach etcd.** APISIX in traditional mode does not
   read certificate files — it serves per-SNI certificates from SSL objects in
   etcd. A renewed Kubernetes Secret changes nothing on its own. And because
   cert-manager renews weeks after a deploy, a post-install Job cannot carry it
   either.

So the chart runs a small **CronJob** (`tls.sslSync`, nightly by default) that
PUTs the current certificate to `/apisix/admin/ssls/<instance>`. It is
idempotent, so a run that changes nothing costs nothing, and the same script
runs from the routes Job at deploy time so a fresh install serves TLS without
waiting for the first tick. Without that CronJob, automatic renewal produces a
valid Secret and an expired gateway — which is the failure this whole mechanism
exists to prevent, and the one that would look exactly like success.

```yaml
frankgateway:
  instances:
    inway:
      tls:
        enabled: true
        certManager:
          enabled: true
          issuerRef:
            name: letsencrypt-prod      # required; the render fails without it
          extraDnsNames:
            - frankgateway-inway.<env>.<domain>   # if the front door uses one
```

The in-cluster Service names (`frankgateway-inway`,
`frankgateway-inway.<ns>.svc`, `…svc.cluster.local`) are always included,
because that is what a `BackendTLSPolicy` validates against.

**Environments not using cert-manager** set `tls.certManager.enabled: false` and
supply the Secret themselves (`tls.sslSync.secretName`, keys `tls.crt` /
`tls.key`). The sync CronJob still runs, so whatever renews that Secret still
reaches etcd within a day. The Secret is mounted `optional`: until it exists the
sync logs "nothing to do" and exits 0, rather than failing the deploy.

### Why the certificate is not fetched from OpenBao like the API keys are

The obvious question, given that every other credential in this gateway comes
from OpenBao at request time: why not the certificate too?

**Because there is no request yet.** The API-key fetch runs in APISIX's
`rewrite` phase, which happens after a connection is established and a request
parsed. A server certificate has to be chosen and presented during the **TLS
handshake**, before any of that exists. APISIX matches the incoming SNI against
SSL objects it has already loaded from etcd; there is no request context in
which a Lua function could go and ask OpenBao for one.

APISIX's `$secret://` references do not close this gap either: they resolve
fields in **plugin** configuration (key-auth keys, jwt secrets and the like).
An SSL object is a core resource, not a plugin, and it is consumed at handshake
time.

So a certificate always has to be **in etcd before the connection arrives**.
Whatever issues it, something must push it there — which is exactly what the
sync CronJob does. Changing the source does not remove that step.

### OpenBao as the issuing CA

**Decided and implemented**: the certificate is issued *through* OpenBao's PKI
engine, and cert-manager still writes it to a Kubernetes Secret, which the sync
CronJob pushes into etcd. OpenBao becomes the CA and the audit point; nothing
else in the mechanism changes.

`tls.certManager.issuer.create: true` renders two objects, once per namespace:
a `ServiceAccount` and a cert-manager `Issuer` of type `vault` pointed at
`http://<release>-openbao-active:8200`. cert-manager exchanges that
ServiceAccount's token for a short-lived OpenBao token on each issuance, so
there is no static credential anywhere in the cluster. Every instance's
Certificate then uses that Issuer automatically — naming an issuer explicitly
in `issuerRef.name` still overrides it.

```yaml
frankgateway:
  tls:
    enabled: true
    certManager:
      enabled: true
      issuer:
        create: true          # issuerRef is then unnecessary
```

**OpenBao side, once per environment.** The chart cannot do this: it requires
an unsealed, authenticated OpenBao.

```bash
# PKI engine + an internal root
bao secrets enable pki
bao secrets tune -max-lease-ttl=8760h pki
bao write pki/root/generate/internal \
  common_name="PodiumD internal CA" ttl=8760h

# role the Issuer signs against — the names in the certificate's SANs
bao write pki/roles/frankgateway \
  allowed_domains="frankgateway-inway,frankgateway-outway,frankgateway-internal,svc.cluster.local" \
  allow_subdomains=true allow_bare_domains=true allow_glob_domains=true \
  max_ttl=2160h

# kubernetes auth, so cert-manager can trade a SA token for an OpenBao token
bao auth enable kubernetes
bao write auth/kubernetes/config kubernetes_host="https://kubernetes.default.svc"
bao policy write frankgateway-pki - <<'POLICY'
path "pki/sign/frankgateway" { capabilities = ["create", "update"] }
POLICY
bao write auth/kubernetes/role/frankgateway-pki \
  bound_service_account_names=frankgateway-pki \
  bound_service_account_namespaces=podiumd \
  policies=frankgateway-pki ttl=20m
```

> **The front door has to trust the new CA.** Moving from a public issuer to an
> internal OpenBao root changes who signed the certificate, and NGF validates
> it on this hop. Export the root
> (`bao read -field=certificate pki/cert/ca`) into the ConfigMap the
> `BackendTLSPolicy` references (`validation.caCertificateRefs`), or the hop
> fails closed the moment the new certificate is served — with a TLS error at
> the front door and nothing wrong in the gateway's own logs. Do this **before**
> switching the issuer, not after.

### What this does not change

The private key still lands in a Kubernetes Secret on its way to etcd, and it
still ends up in APISIX's etcd, because a certificate is selected during the
TLS handshake and has to be there before the connection arrives. Sourcing it
from OpenBao does not make it available any faster either: renewal starts 30
days before expiry and the sync runs within 24 hours of that, using 0.14% of
the margin. Immediacy is not the risk here; a sync failing silently for a month
is.

A stricter variant is possible — the sync job reading cert and key straight from
an OpenBao kv path with the same scoped token the gateway uses for API keys, so
no Kubernetes Secret exists at all. It was considered and not taken: it removes
one copy of the key while leaving the copy in APISIX's etcd, and it replaces
cert-manager's renewal machinery (which is watched, alerted and understood) with
bespoke logic in a shell script. Worth revisiting only if the Kubernetes Secret
itself becomes the objection.

One thing that would genuinely change with OpenBao PKI is **short-lived
certificates** — hours or days rather than 90 days, shrinking the window a
leaked key is useful. That inverts the timing argument above: a nightly sync
against a 72-hour certificate is no longer a rounding error, so
`tls.sslSync.schedule` must come down with the TTL. Do not shorten `duration`
without shortening the schedule.

**Owner.** Automation nobody watches fails the same way a manual process does,
only later and more quietly. Two checks belong to a named person:

- the CronJob's failed runs (`kubectl -n podiumd get jobs | grep ssl-sync` —
  failures are retained deliberately)
- days-to-expiry, from cert-manager's own
  `certmanager_certificate_expiration_timestamp_seconds`

## CPU and memory

Chart defaults, with the 7-day peak measured on jim00 (three classes live, QA
traffic levels) next to each request so the margin is visible:

| Container | CPU request | measured peak | Mem request | measured peak | CPU limit | Mem limit |
|-----------|-------------|---------------|-------------|---------------|-----------|-----------|
| frankgateway | 100m | 8m | 384Mi | 375Mi | 1 | 1Gi |
| frankgateway-etcd | 50m | 20m | 192Mi | 126Mi | 500m | 512Mi |
| frankgateway-dashboard | 25m | 11m | 128Mi | 90Mi | 500m | 512Mi |
| oauth2-proxy | 10m | <1m | 64Mi | 44Mi | 250m | 256Mi |
| shim (nginx) | 10m | 2m | 32Mi | 7Mi | 250m | 128Mi |
| apply-routes job | 25m | — | 32Mi | — | 250m | 128Mi |

The 375Mi gateway peak is the number that mattered: the previous request was
**256Mi**, i.e. below the observed peak. A pod whose request understates its
real working set is the first one the kubelet evicts under node memory
pressure, while looking correctly sized in the values file. CPU went the other
way — every container was requesting several times its measured peak, which at
2 replicas × 3 classes reserves capacity nobody uses.

CPU on the gateway is deliberately left at 100m, twelve times the measured
peak: QA traffic says nothing about what the inway sees in production, and the
guaranteed share of a request-path proxy is the wrong place to economise.

Each workload also gets a PodDisruptionBudget (`maxUnavailable: 1`,
`unhealthyPodEvictionPolicy: AlwaysAllow`), rendered only where the workload has
more than one replica — over a single replica a budget either does nothing or
blocks node drains forever.

Figures are per container. Multiply by the replica count and the number of
enabled classes for the real total: gateways, dashboards, oauth2-proxy and shim
run at 2 each, etcd at 3 — so the floor with all dashboards on is 27 pods, and
9 with them off (see the footprint table in
[`frankgateway-traffic-classes.md`](frankgateway-traffic-classes.md)). That
comes to roughly **1.0 CPU and 4.1Gi of requests** with every dashboard on, and
**0.75 CPU / 2.8Gi** with them off.

These are still QA numbers. Nothing here has been measured against production
traffic, and the gateway CPU request in particular is a placeholder for
evidence that does not exist yet — revisit after a production environment has
run for a week.

## Integrating Frank!Gateway as a new app

1. **Enable** in the gemeente values file: `frankgateway.enabled: true`.
2. **Set the per-environment must-sets**:
   `frankgateway.dashboard.auth.hostname` (public dashboard host) and
   `frankgateway.dashboard.auth.dnsResolver` (cluster CoreDNS ClusterIP).
3. **OpenBao.** Enable it (`openbao.enabled: true` — the render fails
   otherwise), write the external-API keys to `<mount>/frankgateway`
   (`bag_api_key`, `kvk_api_key`), and have the environment deployment create
   the scoped-reader-token Secret named by
   `frankgateway.openbao.tokenSecret`.
4. **Route the dashboards.** One per class that has one. Gateway API
   environments: HTTPRoute → `frankgateway-<class>-oauth2-proxy:4180` in ADO
   `ExternalsPodiumD` (`infra.yml`), and add each hostname to the gateway
   certificate SAN. Otherwise set `frankgateway.dashboard.ingress.enabled: true`.
5. **Point callers at the right class.** Applications that used `apiproxy` for
   BAG/KVK egress call `http://frankgateway-outway:9080/...`; BRP and other
   app-to-app calls go to `http://frankgateway-internal:9080/...` (route paths
   mirror the apiproxy paths; see `files/frankgateway/routes/<class>/`).
6. **Verify.** `kubectl -n podiumd get jobs` — every
   `frankgateway-<class>-apply-routes` must complete; `kubectl -n podiumd get
   pods -l app.kubernetes.io/component=frankgateway` all Running; each dashboard
   hostname logs in via Keycloak (no dashboard login form); a test call through
   a seeded route reaches its upstream.

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
