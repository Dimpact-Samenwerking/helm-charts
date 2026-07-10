# API Proxy — Basics

## Management summary

The API Proxy is a small traffic forwarder that sits between PodiumD applications and external Dutch government data services, such as the personal records database (BRP), the Chamber of Commerce (KvK) and the buildings and addresses register (BAG). Instead of every application connecting to these outside services directly — each with its own keys and addresses — everything goes through this one component, which adds the right access keys and forwards the request. This keeps sensitive API keys in one place and makes it easy to switch suppliers (for example iConnect) without changing every application. It needs no database and no storage, and it is one of the smallest components in the stack: it uses almost no CPU or memory.

## What it is

An nginx-based forward proxy rendered directly by the umbrella chart (no sub-chart, no upstream project). Templates: `charts/podiumd/templates/api-proxy-configmap.yaml`, `api-proxy-deployment.yaml`, `api-proxy-service.yaml`. Disabled by default (`apiproxy.enabled: false`).

- Image: `nginxinc/nginx-unprivileged:1.31.1` (digest-pinned in `values.yaml`).
- Runtime components: a single `nginx` container in Deployment `api-proxy` (1 replica), ClusterIP Service `api-proxy` (port 80 → container port 8080), plus a ConfigMap `api-proxy-nginx-config` holding the generated `nginx.conf`. The deployment name can be changed with `apiproxy.nameOverride` (e.g. `iconnect-proxy`).
- Role in the stack: one stable in-cluster endpoint (`http://api-proxy.podiumd.svc.cluster.local/`) that fronts external APIs. Per upstream `location` it can inject an API key (`X-Api-Key` for BAG, `apikey` for the KvK endpoints), set the upstream `Host` header, do mTLS to the upstream, verify the upstream certificate chain (`sslVerifyDepth`, default 6), rewrite external URLs in response bodies back to the proxy URL (BAG, via `sub_filter`), and pass through or default an `X-Toepassing` application header (BRP/iConnect).
- Configured upstreams in the chart defaults (`apiproxy.locations`): `bag`, `brp`, `kvkSearch`, `kvkBasic`, `kvkBranch` — all pointing at iConnect lab URLs (`lab.api.mijniconnect.nl`) as examples; per-gemeente values override them.
- Runs hardened: non-root, read-only root filesystem, all capabilities dropped; `/tmp` and `/var/cache/nginx` are `emptyDir` volumes. Health endpoint `/_health/` serves both probes.

## Required resources

### Database

None. The API Proxy is stateless — no PostgreSQL, no `DB_*` Secret/ConfigMap contract.

### Storage

None. No PVC; only two `emptyDir` volumes for nginx tmp and cache.

### Routing / exposure (NGINX Gateway Fabric)

Cluster-internal only — no HTTPRoute is created for it in the Dimpact environments. Consumers reach it at `http://api-proxy.podiumd.svc.cluster.local/<path>` (service port 80). If BAG URL rewriting is used with a public `internalUrl`, exposing the proxy externally is an environment-level decision (see the URL-rewriting document below); by default keep it internal.

### Other dependencies

- Outbound HTTPS to the external API gateways (iConnect/2Secure, or the national endpoints directly) — cluster egress must allow this.
- Optional mTLS to upstreams: Kubernetes Secret referenced by `apiproxy.nginxCertsSecret` containing `client.crt`, `client.key` and `ca.crt`. When set, upstream certificate verification (`proxy_ssl_verify`) auto-derives to `on`; when empty, to `off`.
- KubeDNS resolver IP hardcoded in values (`apiproxy.resolverIp: 10.0.0.10`) — adjust if the cluster's DNS service IP differs.
- No Redis, no Keycloak client, no Open Zaak / Open Notificaties registration, no SMTP.

## CPU and memory

Chart defaults (`apiproxy.resources`, matching `docs/misc/resource-overview.md`, replicas: 1):

| Container | CPU request | Mem request | CPU limit | Mem limit |
|-----------|-------------|-------------|-----------|-----------|
| nginx | 100m | 128Mi | 500m | 256Mi |

Observed usage (live clusters, 2026-07): `api-proxy` runs at **1m CPU / 5Mi** on both aks-blue-ontw-dimp and aks-blue-accp-dimp. The chart defaults are already generous for this workload; no production increase is needed. Note that enabling BAG URL rewriting makes nginx buffer whole response bodies, so memory use scales with response size under load — the 256Mi limit still leaves ample headroom.

## Integrating API Proxy as a new app

1. Enable it in the environment values: `apiproxy.enabled: true`.
2. Configure the upstream locations under `apiproxy.locations`, overriding the lab defaults with the real supplier endpoints:
   - `bag` / `brp`: set `path`, `targetUrl` and `hostHeader`; add `apikey` where the supplier authenticates with an API key (BAG sends it as `X-Api-Key`).
   - `kvkSearch` / `kvkBasic` / `kvkBranch`: set `targetUrl`, `hostHeader` and `apikey` (sent as `apikey` header). These locations have **no default `path`** in `values.yaml` — you must set `locations.<loc>.path` per environment or the rendered `nginx.conf` is invalid.
   - For iConnect BRP: set `locations.brp.toepassingHeaderName: "X-Toepassing"` and optionally `toepassingDefaultValue` for callers that do not send the header themselves.
3. If the supplier requires client-certificate (mTLS) authentication, create a Secret with `client.crt`, `client.key` and `ca.crt` in the `podiumd` namespace and set `apiproxy.nginxCertsSecret` to its name. Tune `apiproxy.sslVerifyDepth` (global, default 6) or `locations.<loc>.sslVerifyDepth` if the upstream chain is deep.
4. Optionally enable response URL rewriting for BAG (`locations.bag.urlRewrite.enabled: true` + `internalUrl`) so `_links` in BAG responses point at the proxy instead of the supplier — see the URL-rewriting document below.
5. Point the consuming applications (e.g. haal-centraal BRP / KvK / BAG client configuration in Open Inwoner, KISS, Open Formulieren) at `http://api-proxy.podiumd.svc.cluster.local/<path>` instead of the external URL, and remove any per-app API keys — the proxy injects them.
6. Verify: `kubectl -n podiumd rollout status deployment/api-proxy`, check `/_health/` returns 200, curl one proxied path from an in-cluster pod, and check `kubectl -n podiumd logs deployment/api-proxy` for upstream TLS or 401/403 errors. Config changes roll the pod automatically via the ConfigMap checksum annotation.

## Related documents

- [api-proxy-url-rewriting.md](api-proxy-url-rewriting.md) — how the BAG response URL rewriting works (`sub_filter`), configuration per environment, performance caveats, testing and troubleshooting.
