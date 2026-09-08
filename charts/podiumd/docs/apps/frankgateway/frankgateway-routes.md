# Frank!Gateway — routes come from values

The chart ships **no routes**. Every environment's `podiumd.yaml` is the
complete list of what each traffic class serves; nothing is read from files in
the chart, and there is no deploy-side route tooling. This page is the
reference for writing that list, and it carries the bodies that used to ship
as chart defaults so an environment can copy them.

## The shape

```yaml
frankgateway:
  instances:
    outway:
      routes:
        apiproxy-bag:                         # <- the APISIX route id
          uri: "/lvbag/individuelebevragingen/v2/*"
          labels: { managed-by: iac }
          upstream:
            scheme: https
            pass_host: rewrite
            upstream_host: api.bag.kadaster.nl
            nodes: { "api.bag.kadaster.nl:443": 1 }
            type: roundrobin
```

- `frankgateway.instances.<class>.routes` is a map of **route id → route
  body**. The body is the APISIX Admin API route object, verbatim, written as
  YAML; the seed Job renders it to JSON and `PUT`s it to
  `/apisix/admin/routes/<id>` on that class. Anything APISIX accepts there is
  valid here — plugins, `hosts`, `methods`, `upstream_id`, and so on.
- The id must match `^[a-zA-Z0-9._-]+$` (it is also a ConfigMap key). A body
  that carries its own `id` must agree with the key.
- **Routes are per instance.** `frankgateway.routes` at the shared level is
  rejected: the shared block deep-merges into every class, so a route placed
  there would be seeded into inway, outway and internal alike.
- Put `labels: { managed-by: iac }` on every route you write. It is what
  `seed.prune` uses to tell your routes from ones made in the dashboard.

## How a route reaches etcd

APISIX runs in traditional (etcd) mode and reads no route files; the only way
in is the Admin API. The chart's **seed hook** does that: one
post-install/post-upgrade Job per class, `frankgateway-<class>-seed`, with the
rendered bodies in the ConfigMap of the same name. It runs after the gateway
pods are up (it waits for the class's Admin API), and it does, in order:

1. the routes — one idempotent `PUT` per id; zero routes is a valid state and
   the Job still succeeds,
2. **prune** (only when `frankgateway.seed.prune: true`) — every route in etcd
   that carries `managed-by: iac` but is not in this render is deleted; routes
   without the label are never touched,
3. the prometheus `global_rule`, so per-route metrics exist for every route,
4. the data-plane certificate sync, when `tls.sslSync` is on.

`PUT`s overwrite, so every deploy re-applies the full set and a hand-edited
route is put back to what values say. Settings live under `frankgateway.seed`
(`enabled`, `prune`, `job.image`, `job.nodeSelector`, `job.backoffLimit`,
`job.ttlSecondsAfterFinished`), and can be overridden per instance like every
shared key.

Check a run with `kubectl -n podiumd logs job/frankgateway-<class>-seed`: it
prints one `seed: routes/<id> -> 2xx` line per route, and the Admin API's answer
when one is rejected. The chart's NOTES also list any enabled class that has no
routes at all — such a class answers 404 to everything.

## Adding, changing, removing

Helm layers values files key by key, so with `-f base.yaml -f env.yaml`:

- **add or override** a route: define the id in the later file;
- **change one field** of a route from an earlier file: only that field —
  maps merge key by key;
- **remove** a route from the render: set `routes.<id>: null` in the later file;
- **remove it from etcd too**: that needs `seed.prune: true` — off by default,
  so a route dropped from values lingers in etcd until you turn it on or delete
  it by hand.

## Reference bodies

These are the routes the chart shipped before 4.9.1. Copy what your
environment needs; nothing here is applied unless you do.

### outway — external registries (API keys from OpenBao)

The key is fetched **at request time** from OpenBao by
`openbao-secret-header.lua` and set as an upstream header; the value never
appears in the route, in etcd or in git — see
[`frankgateway-BASICS.md`](frankgateway-BASICS.md). The KVK routes use the
KvK **test** dataset (`/test/` prefix); drop the `proxy-rewrite` for production.

```yaml
frankgateway:
  instances:
    outway:
      routes:
        apiproxy-bag:
          uri: "/lvbag/individuelebevragingen/v2/*"
          name: apiproxy-bag
          labels: { managed-by: iac }
          plugins:
            serverless-pre-function:
              phase: rewrite
              functions:
                - 'local set_secret_header = require("openbao-secret-header") return set_secret_header({ path = "frankgateway", field = "bag_api_key", header = "X-Api-Key" })'
          upstream:
            scheme: https
            pass_host: rewrite
            upstream_host: api.bag.kadaster.nl
            nodes: { "api.bag.kadaster.nl:443": 1 }
            type: roundrobin
        # The three KVK routes differ only in uri and name: one definition,
        # merged three ways with a YAML anchor (Helm's loader resolves it).
        apiproxy-kvk-basic:
          <<: &kvkRoute
            labels: { managed-by: iac }
            plugins:
              proxy-rewrite:
                regex_uri: ["^/(.*)", "/test/$1"]
              serverless-pre-function:
                phase: rewrite
                functions:
                  - 'local set_secret_header = require("openbao-secret-header") return set_secret_header({ path = "frankgateway", field = "kvk_api_key", header = "apikey" })'
            upstream:
              scheme: https
              pass_host: rewrite
              upstream_host: api.kvk.nl
              nodes: { "api.kvk.nl:443": 1 }
              type: roundrobin
          uri: "/api/v1/basisprofielen*"
          name: apiproxy-kvk-basic
        apiproxy-kvk-branch:
          <<: *kvkRoute
          uri: "/api/v1/vestigingsprofielen*"
          name: apiproxy-kvk-branch
        apiproxy-kvk-search:
          <<: *kvkRoute
          uri: "/api/v2/zoeken*"
          name: apiproxy-kvk-search
```

### internal — app to app

For a ZGW API prefer `pass_host: rewrite` with `upstream_host` set to the
application's **public** FQDN: those APIs emit absolute self-referencing URLs,
and a caller cannot resolve a cluster-local one.

```yaml
frankgateway:
  instances:
    internal:
      routes:
        apiproxy-brp:
          uri: "/haalcentraal/api/brp/*"
          name: apiproxy-brp
          labels: { managed-by: iac }
          upstream:
            scheme: http
            pass_host: rewrite
            upstream_host: brp-personen-mock
            nodes: { "brp-personen-mock:5010": 1 }
            type: roundrobin
        internal-openzaak:
          uri: /*
          labels: { managed-by: iac }
          upstream:
            scheme: http
            pass_host: rewrite
            upstream_host: openzaak.<env>.<domain>
            nodes: { "openzaak-nginx.podiumd.svc.cluster.local:80": 1 }
            type: roundrobin
```

### inway — the front door

An inway route matches the environment's own public hostname, which is why it
could never have been a chart file. The re-encrypting front door (NGF with a
`BackendTLSPolicy`) delivers the request with that host intact.

```yaml
frankgateway:
  instances:
    inway:
      routes:
        inbound-openzaak:
          uri: /*
          host: openzaak.<env>.<domain>
          labels: { managed-by: iac }
          upstream:
            type: roundrobin
            scheme: http
            pass_host: pass
            nodes: { "openzaak-nginx.podiumd.svc.cluster.local:80": 1 }
```

## Coming from 4.9.0 or earlier

- `frankgateway.routes.extra` → `frankgateway.instances.<class>.routes`;
  `frankgateway.routes.seed` / `routes.job` → `frankgateway.seed.enabled` /
  `seed.job`. The render fails, naming the key, if the old ones are still set.
- The five routes the chart used to ship (BAG, KVK×3, BRP) are **no longer
  applied by the chart**. Copy them from this page into your values, or the
  next deploy leaves them as they are in etcd (unlabelled from the chart's point
  of view they are not, so `seed.prune` would remove them — turn it on only
  once values are complete).
- The hook objects were renamed from `frankgateway-<class>-apply-routes` /
  `-routes` to `-seed`. Hook ConfigMaps are not release-tracked, so the old
  ones stay behind once: `kubectl -n podiumd delete configmap -l app.kubernetes.io/component=frankgateway-routes`.

## Client certificates from OpenBao (outbound mTLS)

> **Temporary by design — obsolete with the next Frank!Gateway release.**
> Everything in this section and the next (the `client-cert-sync` CronJob,
> `openbao-client.lua`, `openbao-consumer-auth.lua`, and the request-time
> header function for API keys) exists only because Frank!Gateway 1.1.0 runs
> APISIX 3.16, where a `$secret://` reference cannot carry an upstream client
> certificate and is unsafe for consumer credentials. The next Frank!Gateway
> release moves to an APISIX that resolves `$secret://` in those places, and
> the native reference replaces all of it: the CronJob and the Lua go, the
> OpenBao layout (`<mount>/frankgateway/…`) and the reader token stay. Do not
> build on the Lua modules' interfaces; treat them as a bridge.

Some external APIs want the gateway to present a client certificate (BRP / Haal
Centraal with a PKIoverheid certificate, an ESB, KvK production). The
certificate and key live in **OpenBao and nowhere else**; the chart pulls them
into an APISIX SSL object that the route references.

```yaml
frankgateway:
  instances:
    outway:
      clientCertificates:
        brp:                                    # -> SSL object id client-brp
          openbaoPath: frankgateway/client-certs/brp
      routes:
        apiproxy-brp:
          uri: "/haalcentraal/api/brp/*"
          labels: { managed-by: iac }
          upstream:
            scheme: https
            pass_host: rewrite
            upstream_host: brp.example.nl
            nodes: { "brp.example.nl:443": 1 }
            type: roundrobin
            tls:
              client_cert_id: client-brp          # the SSL object above
              verify: true                        # verify the upstream too
```

- **OpenBao:** `bao kv put <mount>/frankgateway/client-certs/brp cert=@chain.pem key=@key.pem`
  — `cert` is the PEM leaf plus intermediates, `key` the PEM private key.
- **Sync:** for every instance with `clientCertificates`, the chart renders a
  CronJob `frankgateway-<class>-client-cert-sync` (schedule
  `frankgateway.clientCertSync.schedule`, default every 5 minutes) that reads
  each path with the gateway's reader token and `PUT`s
  `/apisix/admin/ssls/client-<name>` (`type: client`) when the certificate
  changed. The seed Job runs the same sync first, before the routes — APISIX
  rejects a route whose `client_cert_id` does not exist yet.
- **Rotation:** `bao kv put` the new material; it is live within one schedule
  tick, no deploy. Check `kubectl -n podiumd get jobs | grep client-cert-sync`
  and the latest one's log (`unchanged`, or `ssls/client-brp -> 200`).
- **Failure:** if OpenBao cannot be read and an SSL object already exists, the
  sync keeps it and exits 2 — a retained failed CronJob run, and at deploy time
  a warning rather than a failed install. No object to fall back on is a hard
  failure, and the dependent route is rejected: nothing is served with a
  missing certificate.
- **Validation:** a route whose `client_cert_id` names no `clientCertificates`
  entry of its instance fails the render.

### Why a sync job and not `$secret://`

On the APISIX 3.16 this image builds on, a `$secret://` reference is resolved
for consumer credentials and for an SSL object's `cert`/`key` on the handshake
path — but **not** for `upstream.tls.client_cert`/`client_key`, and not through
`client_cert_id`, so it cannot carry a certificate the gateway presents to an
upstream. APISIX 3.18 fixes that (and the consumer-credential caveats below).
When Frank!Gateway ships on 3.18 — its next release — the sync CronJob is
replaced by a reference in the SSL object (`"cert": "$secret://vault/<id>/frankgateway/client-certs/brp/cert"`),
with a KV **v1** mount, which is all APISIX's Vault backend speaks, and one
APISIX `secret` resource per instance (each class has its own etcd prefix).
The retirement is a chart change plus a KV mount change; the certificates
themselves do not move.

## Consumer identities from OpenBao (inbound)

> **Temporary by design** — see the note at the top of the previous section.
> With the next Frank!Gateway release this becomes a native APISIX consumer
> whose credential is a `$secret://` reference; `openbao-consumer-auth.lua`
> is retired then.

External parties authenticate to the inway with a **client certificate**. The
certificate is verified by the front door, which forwards the identity in a
request header; the gateway maps that identity to a consumer name using a list
kept in **OpenBao**, at request time — the same mechanism the API keys use, so
onboarding or rotating a consumer needs no deploy.

```yaml
frankgateway:
  instances:
    inway:
      routes:
        inbound-openzaak:
          uri: /*
          host: openzaak.<env>.<domain>
          labels: { managed-by: iac }
          plugins:
            serverless-pre-function:
              phase: access
              functions:
                - 'local consumer_auth = require("openbao-consumer-auth") return consumer_auth({ path = "frankgateway/consumers", verificationHeader = "X-Client-Cert-Verification", allow = { "zaaksysteem-x" } })'
          upstream:
            type: roundrobin
            scheme: http
            pass_host: pass
            nodes: { "openzaak-nginx.podiumd.svc.cluster.local:80": 1 }
```

- **OpenBao:** one secret, one field per consumer, the value its certificate's
  SHA-1 fingerprint — or several, comma-separated, so old and new certificates
  overlap during a rotation:
  `bao kv patch <mount>/frankgateway/consumers zaaksysteem-x=ab12…ef,98fe…01`.
  Removing a field revokes the consumer. Changes are live within 300 s (the
  gateway's cache).
- **Options:** `path` (required), `header` (default `X-Client-Cert-Fingerprint`),
  `verificationHeader` (when set, must read `SUCCESS`), `allow` (consumer names
  this route admits; omit to admit every known consumer), `stale_ttl` (seconds
  the last-good list is served while OpenBao is unreachable; default 3600, `0`
  to fail closed at once — the copy is per gateway pod, so one successful read
  since the pod started covers every worker in it). Values are compared case-insensitively with colons
  and spaces removed, so forwarding the certificate **subject** instead and
  listing subject DNs works the same way.
- **Answers:** 401 without an identity or with an unknown one, 403 for a known
  consumer not in `allow`, 503 when OpenBao is unreachable and no last-good
  list is within `stale_ttl`. On success the upstream receives
  `X-Consumer-Username` (overwriting anything the caller sent), and the JSON
  access log carries it as `consumer`.
- **Only on the inway.** The function trusts the header. That is sound only
  behind a front door that verified the certificate and overwrites the header
  on every request, with the inway reachable through nothing else
  (`networkPolicies.ingressNamespace`); the render refuses the function on any
  other class.

### What the front door must send

For the Azure Application Gateway that fronts the environments (owned by the
hosting partner): mutual authentication in **strict** mode on the listener's SSL
profile, with the trusted client CA chain(s) uploaded, and a **rewrite rule
set** on the routing rule that writes these request headers from server
variables:

| Header | Server variable | Note |
|---|---|---|
| `X-Client-Cert-Fingerprint` | `{var_client_certificate_fingerprint}` | **SHA-1**, hex — the value to list in OpenBao |
| `X-Client-Cert-Subject` | `{var_client_certificate_subject}` | subject DN; optional, for subject-based matching |
| `X-Client-Cert-Verification` | `{var_client_certificate_verification}` | `SUCCESS` in strict mode; pass as `verificationHeader` |

Application Gateway cannot pass TLS through (it is a terminating proxy), so the
existing chain stays as it is: it re-encrypts to NGINX Gateway Fabric, which
re-encrypts to the inway on 9443 (`BackendTLSPolicy`). Nothing on the AKS side
changes for mTLS traffic; only the headers are new. Because the gateway sets
them on every request, a caller cannot forge one — provided the inway is not
reachable by any other path.

### Why not APISIX consumers with `$secret://` keys

It would be the idiomatic way, and it is the way to go once Frank!Gateway is on
APISIX 3.18. On 3.16 the consumer path caches a resolved key for up to an hour,
and a failed OpenBao read leaves the literal `$secret://…` string as the key —
silently. `key-auth` on the fingerprint header would also accept the same value
from the `?apikey=` query string, which cannot be disabled, and a fingerprint is
public. The request-time Lua fails closed, refreshes in 300 s, and reads only
the header it is told to.

