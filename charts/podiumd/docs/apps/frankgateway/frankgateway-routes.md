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
