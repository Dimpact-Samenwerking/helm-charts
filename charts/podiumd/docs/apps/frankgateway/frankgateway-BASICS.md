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
optional: the chart ships it disabled. To run, it needs no database and no
public hostname — only a small disk for its configuration store, which the next
release removes as well. Every part of it runs at least twice over, so no
single failure interrupts traffic: nine lightweight pods in all.

Since 4.8.5 it always runs as **three separate gateways**, one per kind of
traffic — inbound, outbound and between applications — so each can be secured,
scaled and monitored on its own, and a problem with one cannot take the other
two down. See
[`frankgateway-traffic-classes.md`](frankgateway-traffic-classes.md).

## What it is

Upstream: [Apache APISIX](https://apisix.apache.org/) 3.16 packaged by
[WeAreFrank](https://wearefrank.nl/) as `ghcr.io/wearefrank/frank-gateway`
("APISIX + WeAreFrank patches"), image chart-pinned at
`1.1.0@sha256:2f944f...` (`frankgateway.image.tag` in
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
`-admin-credentials`, `-config` and `-seed` companions. There is no unsuffixed
`frankgateway` object. `<class>` below stands for whichever of the three is
meant:

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
  store, upstream `quay.io/coreos/etcd` build (no Bitnami), shared by the three
  classes with one prefix each — see
  [why one etcd and three prefixes](frankgateway-traffic-classes.md#why-one-etcd-and-three-prefixes).
  Members find each other through the headless Service
  `frankgateway-etcd-headless`, which publishes not-ready addresses so the
  cluster can form before any member is ready; `frankgateway-etcd` remains as
  the load-balanced Service for ad-hoc `etcdctl`. **Retired in the next
  release** — see [Changing in the next release](#changing-in-the-next-release).
- **frankgateway-\<class\>-seed** (hook Job, post-install/post-upgrade) —
  seeds that class's routes from **values only**
  (`frankgateway.instances.<class>.routes`, a map of route id → APISIX route
  body; idempotent PUTs), then the prometheus global rule and the data-plane
  certificate. The chart ships no routes: an environment's values are the
  complete list, and `seed.prune` can make etcd match them. Reference bodies
  and the rules are in [`frankgateway-routes.md`](frankgateway-routes.md).
- **External-API keys** are fetched from **OpenBao at request
  time** by `files/frankgateway/openbao-secret-header.lua` (mounted from the
  `frankgateway-lua` ConfigMap, resolved via `apisix.extra_lua_path`) — a
  configurable function taking the secret path, field and header name, so one
  implementation covers the BAG, KVK and ESB-consumer call sites. Key values
  never land in etcd, git, a ConfigMap, a Kubernetes Secret or the route JSONs;
  the pod carries only a scoped reader token. A route whose secret cannot be
  read answers **503** with a log line naming the path
  (`frankgateway.openbao.failMode: closed`) rather than passing the request on
  to be rejected as a 401, which is indistinguishable from a wrong key.

## Changing in the next release

The next PodiumD release after 4.9.3 ships a new Frank!Gateway version, and
two things this documentation describes go with it:

- **etcd is retired.** Frank!Gateway no longer uses etcd as its configuration
  store, so `frankgateway-etcd` — the three-member StatefulSet, its PVCs, the
  headless Service and its PodDisruptionBudget — and the per-class etcd
  prefixes disappear. Everything in these docs that depends on etcd (the 2Gi
  storage requirement, "the certificate must be in etcd before the connection
  arrives", the shared-store blast radius in
  [`frankgateway-traffic-classes.md`](frankgateway-traffic-classes.md))
  describes 4.9.3 and earlier.
- **The sync workaround stops.** The new Frank!Gateway fully supports OpenBao
  for both certificates and API keys, and reads them from OpenBao itself. The
  `client-cert-sync` CronJob that copies client certificates out of OpenBao
  into the gateway is no longer used, and neither are the Lua bridges the chart
  ships for 1.1.0 on APISIX 3.16 (`openbao-secret-header.lua`,
  `openbao-client.lua`, `openbao-consumer-auth.lua`). Why they existed is in
  [`frankgateway-routes.md`](frankgateway-routes.md#client-certificates-from-openbao-outbound-mtls).

What carries over unchanged is the OpenBao side: the layout under
`<mount>/frankgateway/`, the scoped reader token and the operator workflow
(`bao kv put` / `patch`). Credentials already written to OpenBao stay where
they are.

## Required resources

### Database

None — gateway configuration lives in the bundled etcd (see Storage).

### Storage

Yes, small: the etcd StatefulSet uses a `volumeClaimTemplate` PVC of **2Gi**
(`frankgateway.etcd.storage`), default storage class
(`frankgateway.etcd.storageClassName: ""`). It holds the APISIX
routes/upstreams/consumers created via the Admin API. No Azure Files
share, no chart-rendered PV. The PVCs go when etcd is retired in the next
release.

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
gets there and how it is renewed.

### Other dependencies

- **OpenBao** — **required**, not optional: it is the only source of
  external-API credentials, and `openbao.enabled: false` alongside
  `frankgateway.enabled: true` fails the render. Everything the gateway needs
  from it lives under `<mount>/frankgateway/`: the API keys at
  `frankgateway` (fields `bag_api_key`, `kvk_api_key`), the outbound client
  certificates at `frankgateway/client-certs/<name>` (fields `cert`, `key`) and
  the inbound consumer list at `frankgateway/consumers` (one field per
  consumer) — see [`frankgateway-routes.md`](frankgateway-routes.md). The
  gateway reads them with a scoped reader token supplied out-of-band in the
  Secret named by `frankgateway.openbao.tokenSecret` — never minted by this
  chart, because a token the chart could mint is a token the chart would
  store. Minting it is
  [runbook step 5](frankgateway-deploy-runbook.md#step-5--put-the-gateways-secrets-in-openbao);
  OpenBao itself is documented in
  [`frankgateway-openbao.md`](frankgateway-openbao.md).

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

APISIX's `$secret://` references narrow this gap but do not close it, and it
is worth being exact about what they do on the 3.16 this image builds on
(verified in the `release/3.16` source): a reference is resolved in **consumer
credentials** (key-auth keys and the like — with a cache of up to an hour, and
on a failed read the literal `$secret://…` string silently becomes the key), in
an SSL object's **`cert`/`key`** on the handshake path (300 s cache), and in a
handful of plugins. It is **not** resolved in `client.ca`, not in an upstream's
`tls.client_cert`/`client_key`, and not through `client_cert_id` — so it cannot
carry a client certificate the gateway presents to someone else. Until
Frank!Gateway moves past 3.16, the chart's own sync CronJob and Lua cover that
gap ([`frankgateway-routes.md`](frankgateway-routes.md)); the next release's
Frank!Gateway reads certificates and API keys from OpenBao itself.

So a certificate always has to be **in etcd before the connection arrives**.
Whatever issues it, something must push it there — which is exactly what the
sync CronJobs do. Changing the source does not remove that step. (For this
server certificate specifically, a `$secret://` reference in the SSL object
*would* work on 3.16 and refresh within 300 s; it is not used today because the
cert-manager path already renews and the CronJob already syncs — a possible
later simplification, not a gap.)

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
itself becomes the objection. With etcd retired in the next release, the copy
of the key in APISIX's etcd goes in any case.

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
| seed job | 25m | — | 32Mi | — | 250m | 128Mi |
| client-cert-sync job | 25m | — | 32Mi | — | 250m | 128Mi |

The 375Mi gateway peak is the number that mattered: the previous request was
**256Mi**, i.e. below the observed peak. A pod whose request understates its
real working set is the first one the kubelet evicts under node memory
pressure, while looking correctly sized in the values file. CPU went the other
way — every container was requesting several times its measured peak, which at
2 replicas × 3 classes reserves capacity nobody uses.

CPU on the gateway is deliberately left at 100m, twelve times the measured
peak: QA traffic says nothing about what the inway sees in production, and the
guaranteed share of a request-path proxy is the wrong place to economise.

Figures are per container. Multiply by the replica count and the number of
enabled classes for the real total: gateways run at 2 each, etcd at 3 — so the
floor is 9 pods. Why those replica counts, and the PodDisruptionBudgets and
spread rules that go with them, are in
[the footprint section](frankgateway-traffic-classes.md#footprint). That
comes to roughly **0.75 CPU and 2.8Gi of requests**. Retiring etcd in the next
release takes the three etcd members (150m / 576Mi) off that total.

A fresh install on jim00 (2026-08-14, first deploy of this chart) settled at
95–116Mi per gateway and 3–45Mi per etcd member — comfortably inside every
request above, with no OOMKill and no eviction. That is an idle figure and
says nothing the 375Mi peak does not already say; it is recorded only because
it is the first evidence that the three-class footprint fits on a node without
the kubelet intervening.

Sizing this way is what makes a cluster grow on first install: NAP took jim00
from 2 nodes to 9 to fit the new requests alongside the rest of PodiumD. That
is the intended behaviour, not a fault, but it means the first deploy into a
fixed-size cluster needs the headroom checked in advance.

These are still QA numbers. Nothing here has been measured against production
traffic, and the gateway CPU request in particular is a placeholder for
evidence that does not exist yet — revisit after a production environment has
run for a week.

## NetworkPolicies are not enforced everywhere

`frankgateway.networkPolicies.enabled: true` renders per-traffic-class
NetworkPolicies. Whether anything acts on them is a property of the cluster's
CNI, not of the chart.

**The CNI on the `aks-blue-*` clusters does not support NetworkPolicy.** There
the API server accepts every policy object and silently never enforces it:
`kubectl get networkpolicy` shows them, `kubectl describe` shows the rules, and
all traffic still flows. A policy that is not enforced reads exactly like a
policy that is.

So on those clusters, turning this on buys documentation of intent and nothing
else. Do not treat it as isolation, and do not use it as a control in a
security assessment without first confirming enforcement on the target cluster.

## Integrating Frank!Gateway as a new app

The full procedure, with commands, is
[`frankgateway-deploy-runbook.md`](frankgateway-deploy-runbook.md). In outline:

1. **Infrastructure** for OpenBao: database, Key Vault items, identity, route
   and certificate.
2. **Values:** `openbao.enabled: true` (the render fails without it) with the
   environment's hosts and database, and `frankgateway.enabled: true`.
3. **Deploy and initialise OpenBao**, storing the unseal (or recovery) key and
   root token in Key Vault.
4. **Configure OpenBao:** mint the config token so the `openbao-config` Job can
   run.
5. **Secrets:** write the external-API keys, client certificates and consumer
   list under `<mount>/frankgateway/`, then mint the gateway's reader token.
6. **Routes:** copy the bodies the environment needs into
   `frankgateway.instances.<class>.routes` and point callers at the right
   class.
7. **Verify** OpenBao, the seed Jobs and a real call through each class, then
   revoke the root token.

## Related documents

- [`frankgateway-deploy-runbook.md`](frankgateway-deploy-runbook.md) — the
  step-by-step procedure for a first deploy, and the checks after every later
  one. **Start here when deploying.**
- [`frankgateway-openbao.md`](frankgateway-openbao.md) — OpenBao, the secrets
  vault the gateway reads its credentials from: requirements, seal model,
  Keycloak wiring and security notes.
- [`frankgateway-traffic-classes.md`](frankgateway-traffic-classes.md) — running
  the gateway as three per-traffic-class instances (inway / outway / internal),
  with the architecture diagram, the NetworkPolicy model and the footprint.
- [`frankgateway-routes.md`](frankgateway-routes.md) — writing routes in
  values: the shape, the seed hook, prune, the reference bodies, client
  certificates and consumer identities.
- [`frankgateway-split-exploration.md`](frankgateway-split-exploration.md) — the
  feasibility assessment the three-class design came from (historical).
- [`frankgateway-tsa-setup-and-flow-NL.md`](frankgateway-tsa-setup-and-flow-NL.md)
  — for municipalities (in Dutch): how a task-specific application is
  onboarded through the inway.
- [`../apisix/`](../apisix/) — superseded experimental upstream-APISIX
  building block docs (kept for history; both files carry a superseded
  banner).
- [`../apiproxy/apiproxy-BASICS.md`](../apiproxy/apiproxy-BASICS.md) — the
  legacy egress proxy whose routes Frank!Gateway reproduces.
