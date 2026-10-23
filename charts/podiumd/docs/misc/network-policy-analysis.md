# NetworkPolicy Analysis — podiumd chart

> Status: phase 1 and 2 implemented as opt-in (`networkPolicies.*`, off by
> default); egress (phase 3) is still analysis only. First test environment:
> johnb00, after its switch to the Cilium dataplane.
> Last updated: 2026-10-12. Source finding: NW-01 in
> [security-review.md](security-review.md).

The matrix below was derived from the rendered chart (johnb00 values plus
openarchiefbeheer, openvtb, clamav and openbao switched on): the hosts and
URLs in every container's environment, ConfigMaps and Secrets, and the
container ports of every workload. Rows marked _(not observed)_ still need
confirmation from live traffic (Hubble flow logs or a test run with the
policies enforced).

## What exists today

| Object | Source | Selects | Enforced where |
|---|---|---|---|
| `frankgateway-{inway,outway,internal}` | `templates/frankgateway-networkpolicy.yaml`, opt-in `frankgateway.networkPolicies.enabled` | the gateway class pods | clusters with a policy engine |
| Frank!Gateway dashboard/shim policies | `frankgateway.dashboard.networkPolicy`, only with the dashboard on | dashboard and shim pods | same |
| `keycloak-network-policy` | created by the Keycloak operator for the Keycloak CR. Under `networkPolicies.namespaceIsolation.enabled` the chart sets the CR's `spec.networkPolicy`: 8080/8443 from this namespace, the ingress controller and `namespaceIsolation.extraNamespaces`, 9000 from this namespace, the monitoring namespace and the extra namespaces (plus `keycloak.networkPolicy.extraFrom`) | Keycloak pods: 8080 and 9000 open to all without namespace isolation, 7800/57800 between Keycloak pods | same |
| `opennotificaties-rabbitmq` | Bitnami RabbitMQ subchart, where RabbitMQ is enabled | RabbitMQ pods | same |
| `podiumd-*` (this analysis) | `templates/networkpolicies.yaml`, opt-in `networkPolicies.enabled` | see below | same |

## Policy engine per cluster

A NetworkPolicy only has an effect when the cluster runs a policy engine.
Without one, the API server accepts the object and nothing enforces it.

| Cluster | Engine | Enforced |
|---|---|---|
| aks-blue-ontw-dim1, -dim2, -dim3, -dimp, aks-blue-test-dimp | Cilium (`enable-policy=default`) | yes |
| aks-blue-accp-dimp, aks-blue-ontw-icat, -info, -mayk | none | no |
| podiumd-johnb00-aks | none (Azure CNI overlay, dataplane `azure`), switch to Cilium planned | not yet |
| production | not checked | unknown |

With `enable-policy=default`, Cilium enforces policies only on pods that a
policy selects. Unselected pods stay open.

On Cilium, traffic from the local node (kubelet health probes) is always
allowed, so the policies need no node-CIDR exception for probes. Azure NPM and
Calico may need one; check before using them.

## Ports: always the pod port

A NetworkPolicy matches the port on the destination **pod**, after the Service
has translated it. A rule on Service port 80 blocks everything. The pod ports
in this chart:

| Workload | Pod port | Service port |
|---|---|---|
| Maykin Django apps (openzaak, opennotificaties, objecten, openklant, openformulieren, openinwoner, openbeheer, openarchiefbeheer, referentielijsten, openvtb) | 8000 | 80 |
| Their nginx sidecar Deployments (`*-nginx`) | 8080 (openklant-nginx: 8000) | 80 |
| keycloak | 8080 (HTTP), 9000 (management), 7800/57800 (cluster) | 8080 |
| zac | 8080, 9990 (management); OPA sidecar 8181 on localhost | 80 |
| zac-nginx, api-proxy, pabc, ita-web, podiumd-adapter, contact (KISS) | 8080 | 80 |
| zaakbrug | 8080, 8443 | 80 |
| zac-office-converter (Gotenberg) | 3000 | 80 |
| brp-personen-mock | 5010 | 5010 |
| redis-ha | 6379, exporter 9121 | 6379 |
| OpenBao | 8200 (API), 8201 (cluster) | 8200/8201 |
| Frank!Gateway | 9080 (proxy), 9180 (Admin API), 9091 (metrics) | same |
| Frank!Gateway etcd | 2379 (client), 2380 (peer) | same |
| Elasticsearch (ECK) | 9200 (HTTP), 9300 (transport) | 9200 |
| ZAC Solr | 8983 | 80 |
| ZooKeeper | 2181 (client), 2888/3888 (quorum), 7000 (metrics) | 2181 |
| ClamAV | 3310, exporter 9906 | same |
| RabbitMQ (Open Notificaties, where enabled) | 5672 | 5672 |

## Access matrix

### Ingress controller → apps

All public hosts go through the ingress controller (Traefik on johnb00), which
reaches the pod port of the Service behind each Ingress: the nginx sidecars,
keycloak 8080, zac-nginx, contact, ita-web, pabc, zaakbrug, OpenBao 8200,
Kibana, mailpit and the others. A policy on any of these pods must allow the
ingress controller namespace.

### Shared Redis HA

One `RedisReplication/redis-ha` (pods `app=redis-ha`) holds the Celery
brokers, caches, axes and OIDC state of the Django apps, each on its own
database index (see the `redis://` URLs in `values.yaml`). Security review
NW-04: no authentication, no TLS.

| From (pod `app.kubernetes.io/name`) | Port |
|---|---|
| openzaak, -worker, -beat, -config | 6379 |
| opennotificaties, -worker, -beat, -config | 6379 |
| objecten, -worker, -config | 6379 |
| openklant, -worker, -config | 6379 |
| openformulieren, -worker, -beat, -config | 6379 |
| openinwoner, -worker, -beat, -low-latency-worker, -celery-monitor, -config | 6379 |
| openbeheer, -config | 6379 |
| openarchiefbeheer, -worker, -beat, -config | 6379 |
| referentielijsten, -config | 6379 |
| openvtb, -config | 6379 |
| Frank!Gateway dashboard oauth2-proxy (sessions, only with the dashboard on) | 6379 |
| redis-ha pods (replication) | 6379 |
| redis-operator (`name=redis-operator`) | 6379 |
| monitoring namespace | 9121 |

The `redis-ha-label-master` CronJob talks only to the Kubernetes API.

### OpenBao

| From | Port |
|---|---|
| Frank!Gateway pods and jobs (`app.kubernetes.io/component` frankgateway, frankgateway-seed, frankgateway-client-cert-sync, frankgateway-ssl-sync) | 8200 |
| openbao-config job, openbao-token-renewal CronJob | 8200 |
| Keycloak realm import job (component `keycloak`) | 8200 |
| ingress controller (UI/API on the public host) | 8200 |
| OpenBao pods | 8200, 8201 |
| monitoring namespace | 8200 |
| cert-manager, when an Issuer uses OpenBao _(not observed)_ | 8200 |

The activation script (`scripts/openbao-activate.sh`) uses
`kubectl port-forward`, which does not pass through NetworkPolicy.

### Frank!Gateway etcd

Security review NW-02: no TLS, no authentication.

| From | Port |
|---|---|
| gateway pods (component `frankgateway`, also their wait-for-etcd init container) | 2379 |
| dashboards (component `frankgateway-dashboard`) | 2379 |
| etcd members | 2379, 2380 |

The seed, ssl-sync and client-cert-sync jobs only use the Admin API (9180)
and OpenBao, not etcd.

### Elasticsearch (ECK): KISS and Open Inwoner

| From | Port |
|---|---|
| KISS frontend and the kennisbank/smoelenboek/vac sync CronJobs (`app.kubernetes.io/name=contact`) | 9200 |
| openinwoner, -worker, -beat, -low-latency-worker, -celery-monitor, -config | 9200 |
| Kibana (`common.k8s.elastic.co/type=kibana`) | 9200 |
| ECK operator (`app.kubernetes.io/name=elastic-operator`, any namespace) | 9200 |
| Elasticsearch nodes | 9200, 9300 |

### ZAC: Solr, ZooKeeper, office-converter, OPA

| From | To | Port |
|---|---|---|
| zac | Solr (`technology=solr-cloud`) | 8983 |
| solr-operator (`control-plane=solr-operator`) | Solr | 8983 |
| Solr pods | Solr | 8983 |
| Solr pods, ZooKeeper members | ZooKeeper (`technology=zookeeper`) | 2181 |
| zookeeper-operator, solr-operator | ZooKeeper | 2181 |
| ZooKeeper members | ZooKeeper | 2888, 3888 |
| zac | office-converter | 3000 |
| zac | OPA | 8181 on localhost, same pod: no policy needed |

### Component-to-component (application APIs)

All targets on their nginx or Django pod port (8080/8000), unless stated.

| From | To | Reason |
|---|---|---|
| zac | openzaak, objecten, openklant, opennotificaties | ZGW APIs, notification subscriptions |
| zac | pabc (8080) | authorisation |
| zac | frankgateway-outway (9080) or api-proxy (8080) | BAG, BRP, KvK |
| contact (KISS), podiumd-adapter | openzaak, objecten, openklant | ZGW and klantinteracties |
| contact (KISS), its sync jobs | api-proxy | Haal Centraal, KvK |
| ita-web, ita poller | openklant, objecten, openzaak | klantinteracties, taken |
| openformulieren, its config job | openzaak, objecten, openklant, opennotificaties, api-proxy | registration backends, prefill |
| openformulieren, -worker | clamav (3310) | virus scan of uploads |
| openinwoner, -worker | clamav (3310) | virus scan of uploads |
| openformulieren/openinwoner-configure-clamav jobs (`app.kubernetes.io/name=podiumd`, component = the app) | clamav (3310) | clamd ping before writing the ClamAV settings |
| this chart's openformulieren/openinwoner Django shell jobs (configure-clamav, configure-customer-interactions) | redis-ha (6379) | the app settings load the Redis cache; `GlobalConfiguration` saves time out without it |
| openinwoner | openzaak, openklant, objecten, openformulieren, opennotificaties | portal data |
| openinwoner-config | api-proxy | prefill configuration |
| opennotificaties | openzaak | authorisation checks |
| **opennotificaties-worker** | **every subscriber** (zac, openinwoner, objecten, openklant, openbeheer, ...) | **notification delivery: easy to forget** |
| pabc (2.x) | openzaak | zaaktype import |
| zgw-office-addin backend | openzaak | ZGW APIs |
| zaakbrug | openzaak, Frank!Gateway | StUF-ZGW bridge _(not observed)_ |
| create-required-catalogi job | openzaak | seed data |
| create-required-objecttypen job | objecten | seed data |
| Keycloak jobs (4), pabc-keycloak-groups job | keycloak (8080) | realm import, admin user, groups |
| keycloak-operator | keycloak (8080, 9000) | reconcile |
| api-proxy, Frank!Gateway outway seed | brp-personen-mock (5010) | test BRP |
| monitoring namespace | metrics ports of every component | scraping |

Most apps reach Keycloak through the **public** `oidcUrl`. That traffic leaves
the pod towards the ingress IP and comes back in through the ingress
controller, so for ingress policies it counts as "from the ingress controller
namespace". For egress policies (phase 3) it needs an egress rule to the
ingress load balancer IP.

### Egress outside the cluster (phase 3, not implemented)

| From | To | Port |
|---|---|---|
| every Django app, keycloak, pabc, zac, ita, openbao, kiss | Azure PostgreSQL flexible server | 5432 |
| api-proxy, frankgateway-outway | BAG, BRP, KvK (internet) | 443 |
| openformulieren, openinwoner | DigiD/eHerkenning IdPs, KvK, StUF endpoints | 443 |
| zac, openformulieren, openinwoner, ita | SMTP (mailpit on test) | 25/587/1025 |
| clamav (freshclam) | `database.clamav.net` | 443 |
| every pod | kube-dns | 53 UDP/TCP |
| every OIDC client | Keycloak public URL (ingress load balancer) | 443 |
| operators | Kubernetes API server | 443 |

## Implementation (templates/networkpolicies.yaml)

Values: `networkPolicies.*`, off by default. `ingressControllerNamespace` is
required once enabled (the render fails without it).

**Phase 1, `protectBackends`** (on by default once `networkPolicies.enabled`):
ingress-only policies, one per sensitive backend, with exactly the clients
above.

| Policy | Selects | Rendered when |
|---|---|---|
| `podiumd-redis-ha` | `app=redis-ha` | `redis-operator.enabled` and `redis-operator.redis-ha.enabled` |
| `podiumd-openbao` | `app.kubernetes.io/name=openbao` | `openbao.enabled` |
| `podiumd-frankgateway-etcd` | `app.kubernetes.io/component=frankgateway-etcd` | `frankgateway.enabled` |
| `podiumd-elasticsearch` | `common.k8s.elastic.co/type=elasticsearch` | `kiss-eck`, `kiss` or `openinwoner` enabled |
| `podiumd-zac-solr`, `podiumd-zac-zookeeper`, `podiumd-zac-office-converter` | Solr, ZooKeeper, Gotenberg | `zac.enabled` |
| `podiumd-clamav` | `app.kubernetes.io/name=clamav` | `clamav.enabled` |

`protectBackends.extraFrom.<backend>` adds environment-specific callers.

**Phase 2, `namespaceIsolation`** (opt-in): one policy for every other pod in
the namespace. It allows traffic from the own namespace, the ingress
controller, monitoring and `extraNamespaces`, and blocks other namespaces.

**Why a disabled component does not break anything.** NetworkPolicies are
selectors, not references. A policy whose `podSelector` matches no pods does
nothing, and an allow rule that names a client which is not deployed matches
nothing. On top of that, each backend policy is only rendered when its
component is enabled.

**Why phase 2 excludes the phase-1 backends.** Policies are additive: a pod is
reachable when any policy that selects it allows the traffic. If the
namespace-wide policy also selected Redis, it would allow every pod in the
namespace to reach Redis again. The namespace policy therefore uses `NotIn`
selectors for exactly the backends that phase 1 rendered, for the
Frank!Gateway class pods when their own policies are enabled, and for the
Frank!Gateway dashboard and shim when `frankgateway.dashboard.networkPolicy`
renders. The dashboard's oauth2-proxy has no policy of its own and stays
under namespace isolation, which admits the ingress controller (port 4180).

**Phase 3, egress**: not implemented. It breaks most easily (DNS, PostgreSQL,
OIDC through the public URL, external APIs). Start from the egress table
above and from observed flows.

## Test plan (johnb00)

1. Switch johnb00 to the Cilium dataplane; confirm `keycloak-network-policy`
   still lets everything work (it is enforced from that moment).
2. Deploy with `networkPolicies.enabled=true`,
   `ingressControllerNamespace=traefik` (phase 1 only).
3. Run `tests/` in podiumd-infra, plus negative checks: from a pod in another
   namespace and from an unlisted pod in `podiumd`, connections to Redis
   6379, etcd 2379 and OpenBao 8200 must time out.
4. Check the Cilium drop counters for unexpected denies, add missing clients
   to the template or `extraFrom`, update this matrix.
5. Repeat with `namespaceIsolation.enabled=true`.
6. Rollback at any point: `networkPolicies.enabled=false` and redeploy.
