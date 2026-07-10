# Elastic (ECK stack) — Basics

## Management summary

PodiumD uses Elasticsearch as its search engine. The KISS contact application
searches knowledge-base articles and websites through it, and Open Inwoner uses
it to let residents search the portal. Instead of running these search clusters
by hand, PodiumD ships one central "operator" (Elastic Cloud on Kubernetes,
ECK) that automatically creates and maintains the Elasticsearch clusters inside
the Kubernetes cluster. It needs no database and no public web address — it is
only reachable by the other PodiumD applications. Footprint is significant:
the two search clusters together use roughly 8–10 GB of memory in a typical
environment, so plan node capacity accordingly.

## What it is

Upstream: [Elastic Cloud on Kubernetes (ECK)](https://github.com/elastic/cloud-on-k8s),
deployed via Elastic's official Helm charts from `https://helm.elastic.co`:

- **`eck-operator`** (chart 3.4.0, image `elastic/eck-operator:3.4.0`) — the
  central operator, one `elastic-operator` StatefulSet (1 pod) that watches the
  `podiumd` namespace (`eck-operator.managedNamespaces: [podiumd]`) and
  reconciles all `Elasticsearch` / `Kibana` / `EnterpriseSearch` custom
  resources there. The chart also installs the 12 `*.k8s.elastic.co` CRDs
  (`installCRDs: true`, annotated `helm.sh/resource-policy: keep`).
- **`kiss-eck`** (alias of chart `eck-stack` 0.19.0) — renders the KISS custom
  resources: `Elasticsearch` named `kiss` (version **8.19.3**, nodeSet
  `default`, 3 nodes → StatefulSet `kiss-es-default`), `Kibana` `kiss`
  (pod `kiss-kb-*`) and `EnterpriseSearch` `kiss` (pod `kiss-ent-*`, runs the
  web crawler for the KISS knowledge base, engine `kiss-engine`).
- **`openinwoner-elasticsearch`** — a second `Elasticsearch` CR (version
  **9.2.0**) rendered by the `openinwoner` subchart
  (`openinwoner.eck-elasticsearch`), 1 node on ontw/dim1 and 2 on accp,
  reconciled by the same central operator. The openinwoner subchart bundles its
  own `eck-operator`; it MUST stay disabled (`openinwoner.eck-operator.enabled:
  false`) or two operators fight over the same namespace.

Runtime components in the `podiumd` namespace: `elastic-operator-0`
(operator), `kiss-es-default-{0,1,2}` (ES data/master/ingest nodes),
`kiss-kb-*` (Kibana), `kiss-ent-*` (Enterprise Search),
`openinwoner-elasticsearch-es-default-{0..n}` (Open Inwoner ES nodes).

Enablement: the current chart enables the stack by default — dependency
conditions `eck-operator.enabled: true` and `kiss-eck.enabled: true` are set in
`values.yaml`, and a default render emits the operator and all three KISS CRs
(verified with `helm template`). Note the legacy line `tags:
eck-operator.enabled: false` at the top of `values.yaml`: it is a stale flat
tag key that does not match the Chart.yaml tag name (`eck-operator`), and Helm
conditions override tags anyway — the `eck-operator.enabled` condition is what
actually decides. Environments that already run a standalone `elastic-operator`
release should set `eck-operator.enabled: false` and keep it
(see the migration runbook). `kiss-eck` is additionally coupled to the KISS
tags `kiss-eck` and `contact`.

## Required resources

### Database

None. Elasticsearch stores its indices on its own PVCs; there is no PostgreSQL
database, Secret or ConfigMap contract for this stack.

### Storage

Yes — but **not** the usual `podiumd-standard` Azure Files pattern. The ECK
operator creates one `ReadWriteOnce` PVC per Elasticsearch node from the CR's
`volumeClaimTemplates`:

- `elasticsearch-data-kiss-es-default-{0,1,2}` (KISS)
- `elasticsearch-data-openinwoner-elasticsearch-es-default-{0..n}` (Open Inwoner)

The chart leaves `volumeClaimTemplates` unset for KISS, so the ECK default
applies (a 1Gi `elasticsearch-data` claim per node on the cluster default
StorageClass); the commented examples in `values.yaml` show how to set an
explicit size/class (e.g. `managed-csi`, 8Gi) per environment. **Warning:**
`volumeClaimTemplates` is immutable on the underlying StatefulSet — during
upgrades keep it identical to the existing PVCs; resizing requires a manual
StatefulSet recreate or snapshot/restore (see the migration runbook).

Kibana, Enterprise Search and the operator itself are stateless (no PVC).

### Routing / exposure (NGINX Gateway Fabric)

Cluster-internal only — no HTTPRoute and no public hostname. Other apps reach
the stack via the ECK-generated ClusterIP services:

- `kiss-es-http.podiumd.svc.cluster.local:9200` (HTTPS, ECK self-signed cert)
- `kiss-kb-http.podiumd.svc.cluster.local:5601` (Kibana)
- `kiss-ent-http.podiumd.svc.cluster.local:3002` (Enterprise Search)
- `openinwoner-elasticsearch-es-http.podiumd.svc.cluster.local:9200`
  (HTTP — self-signed TLS is disabled for this CR in the chart)

### Other dependencies

- **Consumers:** KISS connects via `kiss.config.elastic.baseUrl` /
  `username` (default `elastic`) / `password` and
  `kiss.config.enterpriseSearch.baseUrl` / API keys / `engine: kiss-engine`;
  Open Inwoner's web/worker pods use the `openinwoner-elasticsearch` cluster
  for portal search (`openinwoner-search-index` init container builds the
  index). The KISS sync job image `kiss-elastic-sync` feeds the knowledge base.
- **Credentials:** ECK generates the built-in `elastic` superuser password in
  Secrets `kiss-es-elastic-user` and
  `openinwoner-elasticsearch-es-elastic-user`.
- **CRDs / RBAC:** the 12 `*.k8s.elastic.co` CRDs are cluster-scoped, so the
  deploying identity needs cluster-scope RBAC (SSC pipeline: `useClusterAdmin:
  true`). Clusters with pre-4.8.0 CRDs need the one-time adoption script
  `charts/podiumd/scripts/pre-upgrade-prep-4.8.0.sh` before the first deploy.
- **Crawler tuning:** Enterprise Search crawler settings (user agent, thread /
  worker pool limits) are per-environment under
  `kiss-eck.eck-enterprise-search.config`.
- **Observability (optional):** `values-enable-observability.yaml` enables the
  operator `podMonitor` (requires the Prometheus Operator `PodMonitor` CRD).
- No Redis, no Keycloak client, no Open Zaak / Open Notificaties registration.

## CPU and memory

Chart defaults (from `values.yaml` and `docs/misc/resource-overview.md`; `(op)` =
injected by the ECK operator, tunable via the CR's `podTemplate`):

| Container | CPU request | Mem request | CPU limit | Mem limit | Notes |
|---|---|---|---|---|---|
| elastic-operator (manager) | 100m | 150Mi | 1000m | 1Gi | |
| kiss elasticsearch (x3) `(op)` | not set (burstable) | 2Gi | not set | 2Gi | via `kiss-eck.eck-elasticsearch` nodeSet podTemplate |
| kiss kibana `(op)` | not set (burstable) | 1Gi | not set | 1Gi | via Kibana CR podTemplate |
| kiss enterprise-search `(op)` | not set (burstable) | 4Gi | not set | 4Gi | via EnterpriseSearch CR podTemplate |
| elastic-internal-init-filesystem (init) `(op)` | 100m | 50Mi | 100m | 50Mi | set by operator |
| openinwoner elasticsearch (ontw-dim1, 1 node) | 200m | 1536Mi | 1000m | 1536Mi | per-env via `openinwoner.eck-elasticsearch.nodeSets` |

**Observed usage** (kubectl top, 2026-07-10): on ontw the ES data nodes sit at
16–27m / 1674–1744Mi each (x3), Enterprise Search at 8m / 3478Mi, Kibana at
11m / 630Mi, the operator at 4m / 69Mi and the Open Inwoner ES node at
14m / 1509Mi. accp is nearly identical (ES ~1750Mi x3, kiss-ent 3531Mi,
kiss-kb 688Mi, operator 123Mi, OIP ES x2 at 1563–1594Mi). Memory sits close to
the request/limit (JVM heap is sized from the limit), CPU is near-idle at
dev/accp load — treat CPU as baseline, not peak.

**Increase for production** (flagged in `resource-overview.md`): the KISS ES,
Kibana and Enterprise Search containers have only memory limits and no CPU
requests, putting them in the Burstable QoS class (eviction candidates under
node pressure). Suggested production settings: ES `500m / 4Gi`
(request = limit for Guaranteed QoS), Kibana `200m / 1Gi`, Enterprise Search
`500m / 4Gi`. For Open Inwoner ES, production recommendation is 3 nodes at
`500m / 4Gi` request, `2000m / 4Gi` limit — a single node is a SPOF for
search. PDBs are managed by ECK: `kiss-es-default` has `minAvailable: 1`;
`openinwoner-elasticsearch-es-default` defaults to `minAvailable: 0` and
should be raised to 1 when running 2+ nodes.

## Integrating Elastic (ECK) as a new app

The operator is shared: a new PodiumD application that needs its own search
cluster does not install another operator, it only adds an `Elasticsearch`
custom resource (the Open Inwoner pattern).

1. **Ensure the central operator is enabled** for the environment:
   `eck-operator.enabled: true` with `eck-operator.managedNamespaces:
   [podiumd]` (must include the namespace where the new CR will live). On
   clusters with pre-existing ECK CRDs, run
   `charts/podiumd/scripts/pre-upgrade-prep-4.8.0.sh --context <ctx>` once
   before deploying; verify afterwards with
   `kubectl get crd -o name | grep -c 'k8s.elastic.co'` (must print 12).
2. **Add an `Elasticsearch` CR via values.** Either give the app's subchart an
   `eck-elasticsearch` dependency (as `openinwoner` does) or extend an
   `eck-stack` alias block (as `kiss-eck` does). Set `fullnameOverride` /
   CR name deliberately — it determines the StatefulSet, PVC, Service and
   Secret names (`<name>-es-<nodeset>`, `elasticsearch-data-<name>-es-<nodeset>-N`,
   `<name>-es-http`, `<name>-es-elastic-user`) — and pin `version` explicitly.
3. **Configure `nodeSets` per environment**: `count` (1 for dev, 3 for
   production HA), `node.roles`, `node.store.allow_mmap: false` (required on
   AKS without vm.max_map_count tuning), pod resources + `ES_JAVA_OPTS` heap in
   `podTemplate`, and an explicit `volumeClaimTemplates` (size + storageClass).
   Keep the nodeSet name stable (`default`) — renaming it makes ECK build a
   new StatefulSet and rebalance all data.
4. **Wire the consumer app** to `<name>-es-http.podiumd.svc.cluster.local:9200`
   with the `elastic` user password from Secret `<name>-es-elastic-user`
   (disable `http.tls.selfSignedCertificate` in the CR if the client cannot
   handle ECK's self-signed cert, as openinwoner does).
5. **No DNS/HTTPRoute step** — keep the cluster internal.
6. **Verify:** the `Elasticsearch` CR reports health `green`
   (`kubectl get elasticsearch -n podiumd`), the PVCs are bound, and the
   operator stays up — check `kubectl get pod elastic-operator-0 -n podiumd`
   restart count after 5+ minutes (the missing-CRD failure mode crashloops on
   a ~2 minute cycle and can intermittently pass a `helm --wait`).

## Related documents

- [migrating-to-eck-stack.md](migrating-to-eck-stack.md) — runbook for the
  4.8.0 move from the legacy `kisselastic` subchart to the central
  `eck-operator` + `kiss-eck` (eck-stack) charts: resource-name preservation,
  volumeClaimTemplates pitfalls, one-time CRD adoption, validation and
  rollback.
