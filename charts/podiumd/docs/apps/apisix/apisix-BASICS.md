# APISIX — Basics

> **SUPERSEDED (podiumd 4.8.2):** the upstream `apisix` subchart described here
> was replaced by **Frank!Gateway** (WeAreFrank's hardened APISIX 3.16),
> deployed by the chart's own `frankgateway-*` templates. See
> [../frankgateway/frankgateway-BASICS.md](../frankgateway/frankgateway-BASICS.md).
> This document is kept as historical record.

## Management summary

APISIX is an API gateway: a traffic hub that PodiumD applications send their
outbound API calls through, instead of calling external services (such as
national registries) directly. Routing everything through one gate gives the
municipality a single place to control, limit and monitor that outbound
traffic. It is an optional building block — the chart ships it disabled, and
it is only switched on in environments that need centralised outbound API
control; the standard Dimpact ontw/accp environments do not run it today. To
run, it needs no database or disk share — only a public hostname for its
admin screen, which is protected by the normal PodiumD login (Keycloak). Its
footprint is small: three lightweight pods.

## What it is

Upstream project: [Apache APISIX](https://apisix.apache.org/) (gateway
version 3.16.0), deployed via the upstream Helm chart
[`apisix/apisix` 2.14.0](https://github.com/apache/apisix-helm-chart)
(repo `https://charts.apiseven.com`, condition `apisix.enabled`,
`fullnameOverride: apisix`). In PodiumD it is wired in as an **egress
(outbound) API gateway** — see
[apisix-egress-gateway.md](apisix-egress-gateway.md) — not as an ingress for
PodiumD apps. There is no APISIX operator; the bundled ingress-controller is
disabled (`apisix.ingress-controller.enabled: false`).

Runtime components when enabled:

- **apisix** (subchart Deployment) — the gateway data plane + Admin API with
  embedded dashboard UI at `:9180/ui/` (`apisix.apisix.admin.enable_admin_ui:
  true`). Runs in etcd-backed *traditional* mode
  (`apisix.apisix.deployment.mode: traditional`): routes/upstreams are
  written to etcd via the Admin API/UI, not via a standalone-YAML ConfigMap.
- **apisix-etcd** (StatefulSet, 1 replica) — hand-rolled minimal etcd from
  `templates/apisix-etcd.yaml` (image `gcr.io/etcd-development/etcd:v3.5.18`).
  The subchart's bundled Bitnami etcd is disabled (`apisix.etcd.enabled:
  false` — no Bitnami policy) and the subchart is pointed at this one via
  `apisix.externalEtcd.host: http://apisix-etcd:2379`.
- **apisix-oauth2-proxy** (Deployment, 1 replica) — `quay.io/oauth2-proxy/
  oauth2-proxy:v7.7.1` from `templates/apisix-oauth2-proxy.yaml`; fronts the
  Admin UI/API with Keycloak SSO and proxies to `apisix-admin:9180`.
- Supporting objects: Secret `apisix-admin-credentials`
  (`templates/apisix-admin-credentials.yaml` — random 32-char `admin`/`viewer`
  API keys replacing the upstream public defaults, `lookup`-stable), Secret
  `apisix-oauth2-proxy` (`templates/apisix-oauth2-proxy-secret.yaml`), and
  the admin-UI Ingress + Traefik redirect Middleware
  (`templates/apisix-admin-ingress.yaml`).

## Required resources

### Database

None. APISIX does not use PostgreSQL. Gateway configuration lives in the
co-deployed **etcd** (`apisix-etcd`). No `apisix` DB Secret/ConfigMap
contract applies.

### Storage

No PVC. The etcd StatefulSet uses an **emptyDir** data volume — single
replica, ephemeral, no auth/TLS (accepted PoC trade-off). Consequence:
routes/upstreams configured via the Admin API/UI are **lost when the etcd
pod restarts or is rescheduled** and must be re-applied.

### Routing / exposure (NGINX Gateway Fabric)

- **Data plane: cluster-internal only.** The gateway Service is `ClusterIP`
  (`apisix.service.type: ClusterIP`); PodiumD pods call it for outbound API
  traffic. No HTTPRoute exists for APISIX on the dimp clusters, and none is
  part of the standard per-gemeente set — data-plane exposure, if any, is a
  per-environment design decision.
- **Admin UI: chart-rendered Kubernetes Ingress**, not an NGF HTTPRoute.
  `templates/apisix-admin-ingress.yaml` renders an Ingress
  (`ingressClassName: traefik`, cert-manager annotation from
  `apisix.adminUi.clusterIssuer`, default `letsencrypt-prod`) at
  `apisix.adminUi.hostname` (required when enabled, e.g.
  `apisix-admin.<envName>.pd.test-rig.nl`), pointing at
  `apisix-oauth2-proxy:80`, with a Traefik Middleware redirecting `/` to
  `/ui/`. This pattern targets Traefik-based (podiumd-infra/test-rig)
  environments; NGF-based environments would need an equivalent route.

### Other dependencies

- **Keycloak** — the Admin UI is gated by oauth2-proxy (`keycloak-oidc`
  provider) against the `podiumd` realm. Client `apisix-dashboard`
  (confidential, standard flow); its secret is the
  `apisix-dashboard-oidc-secret` key in `keycloak-podiumd-realm-secrets`,
  auto-generated and mirrored into the `apisix-oauth2-proxy` Secret. With
  the umbrella `keycloak-operator` enabled this is zero-touch (realm import
  is gated on `apisix.enabled`); with an external Keycloak the client and
  secret must be created manually (see
  [apisix-egress-gateway.md](apisix-egress-gateway.md)).
- **cert-manager** — issues the admin-UI TLS cert (Secret
  `apisix-admin-tls`) via the ClusterIssuer named in
  `apisix.adminUi.clusterIssuer`.
- **etcd** (co-deployed, see above). No Redis, ClamAV, Elasticsearch,
  RabbitMQ or Open Zaak/Open Notificaties registrations.

## CPU and memory

`resource-overview.md` has no APISIX section. Chart-set values
(`charts/podiumd/values.yaml`, `apisix:` block):

| Container | Request CPU | Request mem | Limit CPU | Limit mem |
|---|---|---|---|---|
| apisix gateway (subchart) | not set by umbrella (subchart default) | not set | not set | not set |
| apisix-etcd (`apisix.etcdServer.resources`) | 100m | 128Mi | 500m | 512Mi |
| apisix-oauth2-proxy (`apisix.adminUi.oauth2Proxy.resources`) | 50m | 64Mi | 200m | 256Mi |

**Observed usage:** no APISIX pods were running on `aks-blue-ontw-dimp` or
`aks-blue-accp-dimp` at capture time (2026-07-10) — the chart default is
`enabled: false` and neither environment has opted in, so there are no live
numbers. Sizing guidance: the etcd and oauth2-proxy defaults above are
adequate for admin-plane use; set explicit requests/limits on the APISIX
gateway container per environment (start small and measure — data-plane load
depends entirely on how much outbound traffic is routed through it).

## Integrating APISIX as a new app

An environment enables APISIX when it wants a single controlled/observable
egress point for outbound third-party API calls (rate limits, allow-lists,
metrics, future mTLS) instead of each app calling upstream APIs directly.

1. No database or PVC provisioning — skip the usual DB Secret/ConfigMap step.
2. Enable in the environment values:

   ```yaml
   apisix:
     enabled: true
     adminUi:
       hostname: apisix-admin.<env-domain>       # required — render fails without it
       clusterIssuer: letsencrypt-prod            # match the env's cert-manager issuer
   ```

3. Keycloak client: nothing to do when the umbrella `keycloak-operator` is
   enabled (the `apisix-dashboard` client is added to the realm import and
   the OIDC secret auto-generated). With an external Keycloak, create client
   `apisix-dashboard` and put its secret in
   `keycloak-podiumd-realm-secrets` under key `apisix-dashboard-oidc-secret`.
4. Optional: to source Admin API keys from Azure Key Vault (CSI driver),
   override `apisix.apisix.admin.credentials.secretName` to your own Secret
   containing keys `admin` and `viewer`; the chart then skips generating
   `apisix-admin-credentials`.
5. DNS: point `adminUi.hostname` at the environment's Traefik ingress load
   balancer; cert-manager issues `apisix-admin-tls` automatically. (No NGF
   HTTPRoute — see Routing above.)
6. Configure egress routes/upstreams via the Admin UI
   (`https://<adminUi.hostname>/` redirects to `/ui/` after Keycloak login)
   or the Admin API with the `admin` key from `apisix-admin-credentials`.
   Then point consuming apps' outbound base URLs at the ClusterIP gateway
   Service in the release namespace.
7. Verify: pods `apisix-*`, `apisix-etcd-0` and `apisix-oauth2-proxy` are
   Running; the admin hostname serves the dashboard behind Keycloak; a test
   call through a configured route succeeds from an app pod. Remember: etcd
   is ephemeral (emptyDir) — after an etcd pod restart, re-apply the route
   configuration.

## Related documents

- [apisix-egress-gateway.md](apisix-egress-gateway.md) — why APISIX is an
  egress (not ingress) gateway in PodiumD, chart wiring, dashboard/OIDC
  setup, and egress-route examples. Note: its standalone-mode ConfigMap
  sections predate the current etcd-backed *traditional* mode in
  `values.yaml`; the role and rationale still apply.
- [agw-apisix-certmanager-tls-design.md](agw-apisix-certmanager-tls-design.md)
  — solution design for TLS termination at Azure Application Gateway with
  cert-manager as single CA, covering the ingress scenarios in which APISIX
  (or another Gateway API implementation) could sit behind AGW.
