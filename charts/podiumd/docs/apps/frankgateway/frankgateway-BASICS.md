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

## What it is

Upstream: [Apache APISIX](https://apisix.apache.org/) 3.16 packaged by
[WeAreFrank](https://wearefrank.nl/) as `ghcr.io/wearefrank/frank-gateway`
("APISIX + WeAreFrank patches"), deployed by this chart's own templates —
there is no subchart and no APISIX operator. Enabled with
`frankgateway.enabled: true`. It replaces:

- the previous **`apisix` subchart** (upstream Apache chart 2.14.0) — removed
  from `Chart.yaml`; and
- the legacy **`apiproxy`** nginx for outbound calls to BAG/Kadaster, KVK and
  BRP/Haal Centraal — reproduced as declarative APISIX routes.

Runtime components when enabled:

- **frankgateway** (Deployment) — gateway data plane `:9080` + Admin API
  `:9180`, etcd-backed *traditional* mode. Admin/viewer API keys are random,
  auto-generated and upgrade-stable (Secret `frankgateway-admin-credentials`);
  the APISIX `config.yaml` is mounted from a Secret because it embeds those
  keys (`templates/frankgateway-config.yaml`).
- **frankgateway-etcd** (StatefulSet, 1 replica, PVC) — configuration store,
  upstream `quay.io/coreos/etcd` build (no Bitnami).
- **frankgateway-dashboard** (Deployment) — `apache/apisix-dashboard` GUI.
  Never exposed directly; its built-in login is bypassed server-side.
- **frankgateway-oauth2-proxy + frankgateway-shim** (Deployments) — Keycloak
  SSO chain for the dashboard: oauth2-proxy (OIDC client
  `frankgateway-dashboard`, seeded via the chart realm config; session kept in
  the chart's redis) forwards to an nginx shim that logs into the dashboard
  server-side and injects the dashboard JWT, so the dashboard's own
  `admin/<random>` credential never reaches a browser
  (`templates/frankgateway-dashboard-auth.yaml`).
- **frankgateway-apply-routes** (hook Job, post-install/post-upgrade) — seeds
  the apiproxy-replacement routes from `files/frankgateway/routes/*.json`
  (route id = file name, idempotent PUTs). External-API keys are injected at
  request time from env vars fed by the out-of-band Secret
  `frankgateway.apiKeys.existingSecret` — key values never land in etcd, git
  or the route JSONs. An OpenBao-backed variant (keys fetched from the
  in-cluster vault at request time) is available as
  `files/frankgateway/openbao-apikey-function.lua`.

## Exposure

Everything is ClusterIP-only. PodiumD apps call the gateway on
`http://frankgateway:9080/...`. The dashboard's public hostname
(`frankgateway.dashboard.auth.hostname`) is routed deploy-side (Gateway API
HTTPRoute → `frankgateway-oauth2-proxy:4180` on jim00) or via the optional
in-chart Ingress (`frankgateway.dashboard.ingress.enabled`, Traefik).

## Values

See the `frankgateway:` block in `values.yaml`. Per-environment must-sets when
enabling: `dashboard.auth.hostname`, `dashboard.auth.dnsResolver` (CoreDNS
ClusterIP of the cluster, AKS default `10.0.0.10`), and the out-of-band
Secret with the external API keys. Everything else has working defaults.

## History

Replaces the experimental upstream-APISIX building block (see the superseded
docs under `docs/apps/apisix/`) and is ported 1:1 from the manifests proven on
the jim00 QA environment. Not yet ported from jim00: the config-persistence
CronJob (Postgres snapshot of GUI-created objects; deploy-side follow-up).
