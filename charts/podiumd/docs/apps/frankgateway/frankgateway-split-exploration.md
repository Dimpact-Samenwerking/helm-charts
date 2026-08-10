# Frank!Gateway — exploration: split into 3 traffic-class instances

> Status: **implemented in 4.8.4** (IN-2547). This document is kept as the
> feasibility assessment the design came from; it records why the split is
> shaped the way it is. For how to actually use it, see
> [`frankgateway-traffic-classes.md`](frankgateway-traffic-classes.md).
>
> Two things changed between this assessment and what was built:
>
> - the instances are named **`inway` / `outway` / `internal`**, not
>   incoming/outgoing/internal — matching the FSC vocabulary already used in the
>   backlog for the eventual inway work;
> - there is **one dashboard per instance**, not one designated instance, since
>   apisix-dashboard binds a single etcd prefix and operators want GUI access to
>   each class.
>
> The open questions at the bottom are answered in a closing section.

## Goal

Split the single `frankgateway` deployment into three independent sets of
pods, one per traffic class:

| Instance | Traffic | Examples today |
|----------|---------|----------------|
| `incoming` | North-south traffic entering PodiumD | *(none today — see below)* |
| `outgoing` | Calls from PodiumD apps to external services | BAG/Kadaster, KVK (4 of the 5 seeded routes) |
| `internal` | East-west calls between in-cluster services | BRP route → `brp-personen-mock:5010` (1 of 5) |

## Current state (4.8.2+ chart)

- One Deployment `frankgateway` (data plane `:9080`, Admin API `:9180`,
  optional TLS `:9443`), one ClusterIP Service, **one etcd** StatefulSet
  (traditional mode, prefix `/apisix`).
- Routes seeded declaratively from `files/frankgateway/routes/*.json` by the
  `frankgateway-apply-routes` hook Job (route id = file name, idempotent PUT).
- Dashboard chain: `oauth2-proxy → shim → apisix-dashboard`, one of each.
- External API keys injected as env vars from the out-of-band Secret
  `frankgateway-api-keys`; only var *names* appear in config.
- No in-chart consumer hardcodes `http://frankgateway:9080` — apps are pointed
  at the gateway through per-gemeente values. A split is therefore a
  deploy-side repoint, not a chart-wide refactor of consumers.

## Feasibility: yes — the key mechanism is etcd prefix separation

APISIX in traditional mode loads exactly the objects under its configured
etcd `prefix`. Three instances can share the **single existing etcd**
StatefulSet, each with its own prefix:

```
/apisix-incoming
/apisix-outgoing
/apisix-internal
```

Each instance gets its own Deployment + Service + config Secret (embedding
its own admin key) pointing at its prefix. Route/SSL/consumer objects are
fully isolated per instance without running three etcds.

### Proposed chart shape

Map-driven templates, defaulting to today's single instance so existing
deployments are untouched:

```yaml
frankgateway:
  enabled: false
  # Shared defaults: image, resources, apiKeys, metrics, tls...
  instances:
    gateway:            # default single instance == current behaviour
      enabled: true
    # Split mode (per-gemeente opt-in):
    # incoming:  {enabled: true}
    # outgoing:  {enabled: true}
    # internal:  {enabled: true}
```

- `templates/frankgateway.yaml`, `frankgateway-config.yaml`,
  `frankgateway-routes-job.yaml`, `frankgateway-servicemonitor.yaml` become
  `range` loops over enabled instances (Service/Deployment/Secret named
  `frankgateway-<instance>`, plus a legacy `frankgateway` Service alias kept
  on the single/default instance for migration).
- Route files move to `files/frankgateway/routes/<instance>/*.json`; the hook
  Job loops instances × files against each instance's Admin API.
- Per-instance overrides for `replicas`/`resources`/`tls` (incoming likely
  wants TLS; outgoing does not).

### Per-class wins (the reason to do this)

- **NetworkPolicies per class** — the real security gain:
  - `outgoing`: ingress only from app pods; egress only DNS + 443 internet.
  - `internal`: ingress only from app pods; egress only cluster CIDR.
  - `incoming`: ingress only from NGF/LB; egress only to backend Services.
  Today one pod needs the union of all three, so no meaningful egress policy
  is possible.
- Independent scaling and resource envelopes (outgoing is bursty against
  national registries; internal is steady).
- Blast-radius isolation: a bad route or plugin on one class cannot take the
  other classes down; separate config checksums roll pods independently.
- Clean per-class metrics (Service/ServiceMonitor per instance).

### Costs and complications

1. **Dashboard is the main friction.** `apisix-dashboard` binds to exactly
   one etcd prefix. Options:
   - one dashboard per instance (3× dashboard + 3 hostnames + 3 Keycloak
     clients, oauth2-proxy/shim chain shared or tripled) — heavy;
   - dashboard on **one** designated instance only, others admin-API-only —
     pragmatic recommendation;
   - drop the dashboard in split mode.
2. Admin credentials: the lookup-stable random-key logic multiplies per
   instance (Secret `frankgateway-<instance>-admin-credentials`).
3. Consumer migration: per-gemeente values must repoint apps from
   `frankgateway:9080` to `frankgateway-outgoing:9080` (etc.). Mitigated by
   keeping the legacy Service name as an alias during transition.
4. **`incoming` has no current function.** North-south ingress is handled
   deploy-side by NGF/HTTPRoute straight to app Services; nothing routes
   inbound through the gateway today. An incoming instance only makes sense
   with a concrete use-case (e.g. exposing ZGW APIs to external parties with
   key-auth/rate-limiting at the gateway). Needs a product decision before
   building; the chart shape above supports it whenever defined.
5. Footprint grows from 4 pods to 6–8 (3 gateways + etcd + dashboard chain);
   BASICS doc and per-gemeente sizing need updating.
6. Routes job, ServiceMonitor and Prometheus dashboards multiply per
   instance (mechanical, low risk).

### Not recommended: three etcds

Separate etcd per instance triples PVCs and StatefulSets for no isolation
gain over prefixes — config isolation is already complete per prefix, and
etcd itself is not the blast-radius concern. Only worth revisiting if one
instance's config churn ever needs independent backup/restore.

## Suggested phasing

1. **Phase 1 (chart refactor, no behaviour change):** map-driven instances,
   default single `gateway` instance renders byte-identical to today.
   Verify with `helm template` diff against 4.8.4 base.
2. **Phase 2 (jim00):** enable `outgoing` + `internal` split, move the BRP
   route to `internal`, add the per-class NetworkPolicies, repoint app
   values. Dashboard on `outgoing` only.
3. **Phase 3 (blocked on use-case):** define what `incoming` fronts, then
   enable it with TLS + key-auth.

## Open questions

- What should `incoming` actually front? (ZGW APIs for external parties?)
- Dashboard: one-instance-only acceptable, or is GUI access needed per class?
- Shared admin key across instances (simpler pipelines) vs per-instance keys
  (better isolation)?
- Do any gemeente pipelines read Secret `frankgateway-admin-credentials` by
  name today (name changes in split mode)?

## Answers (decided for the 4.8.4 implementation)

- **What the inway fronts:** the five ZGW APIs that already enter through the
  gateway — openzaak, openklant, notificaties, objecten, objecttypen. No product
  decision was needed after all: the inbound path built for IN-2507 (NGF →
  BackendTLSPolicy re-encrypt → gateway TLS → app Service) *is* the inway, so
  the instance simply takes over routing that already exists. Exposing ZGW APIs
  to external parties with key-auth and rate-limiting remains a later use of the
  same instance, not a prerequisite.
- **Dashboard:** one per instance. The chain (dashboard + shim + oauth2-proxy +
  Keycloak client + realm secret) is templated per instance, so the cost is
  mechanical rather than manual; instances that do not need a GUI can set
  `dashboard.enabled: false` and keep Admin-API-only access.
- **Admin keys:** per instance. Each gets its own
  `frankgateway-<instance>-admin-credentials`, generated and lookup-stable like
  the single-instance one. A shared key would have re-coupled the classes for no
  operational gain, since the seeding Job reads whichever Secret belongs to the
  instance it is targeting.
- **Pipelines reading the Secret by name:** yes — the jim00 `apply-routes.sh`
  does. This is the one real migration hazard. It is why the default `gateway`
  instance keeps the unsuffixed names, and why `serviceAlias` exists: an
  environment can move applications across one at a time instead of having to
  change the gateway name, the Secret name and every consumer in one step.
