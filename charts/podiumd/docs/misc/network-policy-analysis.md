# NetworkPolicy Analysis — podiumd chart

> Status: open — preliminary analysis, policies not yet implemented
> Last updated: 2026-04-10

## Open Items (from security-review.md)

- **[Medium]** There are no `NetworkPolicy` resources anywhere in the chart. All pods in the namespace can communicate freely with each other, including with the Keycloak admin API and database endpoints. A single compromised pod can reach any other service. _Files: `templates/` (no NetworkPolicy templates found)._ Remediation: Add default-deny ingress/egress NetworkPolicies and explicit allow rules per component (see analysis below).

- **[Low]** All Keycloak jobs communicate with Keycloak over unencrypted HTTP (`http://keycloak-service:8080`). Admin credentials (`ADMIN_PASS`, `CLIENT_SECRET`) are transmitted in plaintext within the cluster. _Files: `templates/keycloak-ensure-operator-sa.yaml`, `templates/keycloak-ensure-podiumd-admin-user.yaml`, `templates/keycloak-import-master-realm-job.yaml`, `templates/keycloak-import-podiumd-realm-job.yaml`._ Remediation: If mTLS (e.g. via a service mesh) is not in use, consider enabling Keycloak's HTTPS port for internal service-to-service calls and mounting a cluster CA cert in job containers.

---

## Preliminary Access Matrix

This analysis covers **internal cluster communication only** — i.e., pod-to-pod traffic via Kubernetes Service DNS names. Traffic to public URLs (ingress from the internet, egress to government APIs) is noted separately.

All Maykin-family apps (OpenZaak, OpenNotificaties, Objecten, Objecttypen, OpenArchiefBeheer, OpenKlant, OpenFormulieren, OpenInwoner) are assumed to listen on port **8000** (nginx sidecar on **80**). Service DNS names follow `<fullnameOverride>.<namespace>.svc.cluster.local`.

### Ingress-controller → apps (user-facing traffic)

All components with an ingress are reached via the ingress controller. This is a shared allow rule: the ingress controller pod(s) may reach any pod on its configured ports.

| Target | Port |
|--------|------|
| keycloak (HTTP) | 8080 |
| openzaak | 80 |
| opennotificaties | 80 |
| objecten | 80 |
| objecttypen | 80 |
| openarchiefbeheer | 80 |
| openklant | 80 |
| openformulieren | 80 |
| openinwoner | 80 |
| referentielijsten | 80 |
| kiss (frontend) | 80 |
| kiss-adapter | 80 |
| zac | 80 |
| ita | 80 |
| pabc | 80 |
| zgw-office-addin (frontend + backend) | 80 |

---

### Component-to-component access

#### Keycloak

| From | To | Port | Reason |
|------|----|------|--------|
| keycloak Jobs (all four) | keycloak | 8080 | realm import, operator SA provisioning, admin user setup |
| keycloak ensure-operator-sa Job | postgres (external) | 5432 | psql bootstrap query |
| keycloak | postgres (external) | 5432 | Keycloak database |
| all app pods (OIDC discovery/token) | keycloak | 8080 | OIDC authentication via public URL — typically hits ingress, **not** direct pod-to-pod unless `oidcUrl` is set to an internal service name |

> **Note:** Most apps resolve Keycloak via the public `oidcUrl` (goes through ingress). If cluster-internal OIDC URLs are used in values (e.g., `http://keycloak.podiumd.svc.cluster.local:8080`), the relevant app pods also need a direct allow rule.

#### Redis HA (`redis-ha-master.podiumd.svc.cluster.local:6379`)

The shared Redis HA instance is used by all Maykin-family apps for Django cache, Django axes, and Celery. Each app uses a distinct DB number.

| From | DB(s) | Purpose |
|------|-------|---------|
| openzaak | 4 (cache/axes), 5 (celery) | cache, rate limiting, task queue |
| opennotificaties | 3 (cache/axes), 6 (celery result) | cache, rate limiting, celery |
| objecten | 1 (cache/axes/oidc), 2 (celery) | cache, OIDC session, task queue |
| objecttypen | 0 (cache/axes) | cache, rate limiting |
| openarchiefbeheer | 13 (cache/axes/choices), 14 (celery) | cache, task queue |
| openklant | 7 (cache/axes), 8 (celery) | cache, task queue |
| openformulieren | 9 (cache/axes), 10 (celery) | cache, task queue |
| openinwoner | 11 (cache/axes), 12 (celery) | cache, task queue |

> **Note:** `referentielijsten` and `openbeheer` use their own Redis subcharts (`referentielijsten-redis`, `openbeheer-redis`) — not the shared Redis HA.

**NetworkPolicy rule:** All of the above pods → `redis-ha-master` / `redis-ha-replica` on port **6379**.

#### OpenNotificaties (notification broker)

Apps send notifications to OpenNotificaties on its internal service. OpenNotificaties in turn calls back to OpenZaak for authorization checks.

| From | To | Port | Reason |
|------|----|------|--------|
| openzaak | opennotificaties | 80 | send notifications |
| objecten | opennotificaties | 80 | send notifications |
| openklant | opennotificaties | 80 | send notifications |
| openinwoner | opennotificaties | 80 | send notifications |
| opennotificaties | openzaak | 80 | authorization API check |

> OpenNotificaties also receives webhook callbacks from external subscribers — those come via ingress.

#### OpenNotificaties → RabbitMQ

OpenNotificaties uses an internal RabbitMQ subchart for Celery task brokering.

| From | To | Port | Reason |
|------|----|------|--------|
| opennotificaties (all pods) | opennotificaties-rabbitmq | 5672 | Celery broker |

#### OpenZaak (zaak & document APIs)

| From | To | Port | Reason |
|------|----|------|--------|
| kiss-adapter | openzaak | 80 | ZGW APIs (zaak, ztc, drc) |
| zac | openzaak | 80 | ZGW APIs |
| ita | openzaak | 80 | ZAC/zaak access |
| zgw-office-addin (backend) | openzaak | 80 | ZGW APIs |
| openformulieren | openzaak | 80 | document/zaak creation on form submit |
| openinwoner | openzaak | 80 | zaak status display |
| create-required-catalogi Job | openzaak | 80 | seed catalogus/zaaktypen data |

#### Objecten / Objecttypen

| From | To | Port | Reason |
|------|----|------|--------|
| kiss-adapter | objecten | 80 | smoelenboek / interne taken objects |
| kiss-adapter | objecttypen | 80 | objecttype URL resolution (internal) |
| zac | objecten | 80 | object registration |
| ita | objecten | 80 | log/afdeling/groep objects |
| create-required-objecttypen Job | objecttypen | 80 | seed objecttype data |
| create-required-objecttypen Job | objecten | 80 | seed object data |

#### OpenKlant (klantinteracties API)

| From | To | Port | Reason |
|------|----|------|--------|
| kiss-adapter | openklant | 80 | klanten / contactmomenten |
| zac | openklant | 80 | klantinteracties |
| ita | openklant | 80 | klantinteracties polling |

#### OpenFormulieren

| From | To | Port | Reason |
|------|----|------|--------|
| openformulieren | clamav | 3310 | virus scan on file uploads |

#### OpenInwoner → Elasticsearch (ECK)

| From | To | Port | Reason |
|------|----|------|--------|
| openinwoner | openinwoner-elasticsearch-es-http | 9200 | search index |
| kiss (elastic-sync) | kisselastic (ECK) | 9200 | sync KISS search index |
| kiss (frontend) | kisselastic (ECK) | 9200 | KISS search queries |

#### KISS Adapter

KISS Adapter is the internal backend that mediates between the KISS frontend and ZGW APIs. The adapter service is referenced by its internal DNS name `kiss-adapter.<namespace>.svc.cluster.local`.

| From | To | Port | Reason |
|------|----|------|--------|
| kiss (frontend) | kiss-adapter | 80 | all ZGW proxy requests from KISS UI |
| kiss-adapter | openzaak | 80 | zaak/ztc/drc APIs |
| kiss-adapter | objecten | 80 | smoelenboek objects |
| kiss-adapter | objecttypen | 80 | objecttype URLs |
| kiss-adapter | openklant | 80 | klantinteracties API |

#### ZAC

ZAC communicates with most ZGW components and with the API proxy for government data.

| From | To | Port | Reason |
|------|----|------|--------|
| zac | openzaak | 80 | zaak/ztc/drc APIs |
| zac | objecten | 80 | object registration |
| zac | objecttypen | 80 | objecttype resolution |
| zac | openklant | 80 | klantinteracties |
| zac | opennotificaties | 80 | notification subscriptions |
| zac | api-proxy | 80 | BAG, BRP, KVK lookups |
| zac | pabc | 80 | autorisatie beheer (if `pabcIntegration: true`) |

#### ITA (Interne Taak Afhandeling)

| From | To | Port | Reason |
|------|----|------|--------|
| ita (poller) | openklant | 80 | klantinteracties polling |
| ita | objecten | 80 | log/afdeling/groep object access |
| ita | openzaak | 80 | zaak access |

#### API Proxy (nginx)

| From | To | Port | Reason |
|------|----|------|--------|
| zac | api-proxy | 80 | BAG/BRP/KVK lookups |
| kiss | api-proxy | 80 | Haal Centraal / KVK lookups (if configured) |
| api-proxy | external BAG API | 443 | upstream government API |
| api-proxy | external BRP API | 443 | upstream government API |
| api-proxy | external KVK API | 443 | upstream government API |

#### PABC (Platform Autorisatie Beheer Component)

| From | To | Port | Reason |
|------|----|------|--------|
| zac | pabc | 80 | autorisatie checks |

#### Redis-ha-label-master Job

| From | To | Port | Reason |
|------|----|------|--------|
| redis-ha-label-master Job | Kubernetes API server | 443 | kubectl label command |

#### Monitoring / Observability

Prometheus (via kube-prometheus-stack or Alloy) scrapes metrics from PodMonitors/ServiceMonitors. This is namespace-local pod scraping traffic.

| From | To | Port | Reason |
|------|----|------|--------|
| prometheus / alloy | redis-ha pods | 9121 | redis_exporter metrics |
| prometheus / alloy | keycloak | 8080 | Keycloak metrics endpoint |
| prometheus / alloy | clamav | metrics port | ClamAV exporter |
| prometheus / alloy | all app pods | metrics port | Django/app metrics |

---

## AKS / Azure CNI Considerations

NetworkPolicy enforcement on AKS is **not automatic** — it depends on which network policy engine was selected at cluster creation time.

| Engine | Flag at cluster creation | Notes |
|--------|--------------------------|-------|
| Azure Network Policy Manager (NPM) | `--network-policy azure` | iptables/ipset based; fully enforces standard `NetworkPolicy` |
| Calico | `--network-policy calico` | DaemonSet based; enforces standard `NetworkPolicy` plus Calico CRDs |
| Cilium | `--network-dataplane cilium` | eBPF based; enforces standard `NetworkPolicy` |
| **None (default)** | *(flag omitted)* | `NetworkPolicy` objects are accepted by the API server but **silently not enforced** |

If the cluster was created without a `--network-policy` flag, any policies added will be stored in etcd but have no effect. Verify enforcement is active before relying on policies for security.

### Azure CNI pod-to-node address overlap

With Azure CNI, pods receive IPs from the **same subnet as the AKS nodes** (unlike kubenet, where pods have a separate overlay network). This has one important consequence for egress NetworkPolicies:

**Kubelet health probes originate from the node IP, not from a pod IP.** When you apply a default-deny egress policy to a pod, you are restricting outbound traffic from that pod — but kubelet liveness/readiness probes are *inbound* from the node IP. However, if you apply a default-deny *ingress* policy, you must explicitly allow ingress from the node CIDR, or liveness/readiness probes will be blocked and pods will be restarted.

Concrete mitigation options:

1. **Allow ingress from node CIDR**: add an ingress rule permitting traffic from the node subnet IP range (e.g. `10.240.0.0/16`) on the container's probe port. This is the simplest approach.

2. **Use a pod-level `hostNetwork: false` policy with node CIDR exception**: same as above, scoped to just the probe port rather than all ports.

3. **Switch to exec-based probes**: replace `httpGet` probes with `exec` probes (e.g. `curl localhost:8080/_health`). These run inside the container and are not subject to NetworkPolicy.

The api-proxy deployment uses `httpGet` probes on port 8080; the same applies to any app pod with `httpGet` or `tcpSocket` probes. All probe ports must be reachable from the node CIDR under a default-deny ingress policy.

### kube-dns CIDR

On AKS, `kube-dns` runs in the `kube-system` namespace. The DNS service ClusterIP is typically `10.0.0.10` (the `resolverIp` already hardcoded in `values.yaml`). Egress NetworkPolicies must allow UDP/TCP port 53 to this IP, or to the `kube-system` namespace by label selector, on every pod.

---

## Recommended NetworkPolicy Strategy

1. **Default deny all ingress+egress** per pod (or per namespace): start with a `NetworkPolicy` that selects all pods and allows nothing.

2. **Ingress controller allow**: allow ingress from the ingress controller namespace (or by pod label) to all service ports listed in the ingress-controller table above.

3. **Node CIDR ingress allow for probes**: allow ingress from the AKS node subnet on each container's probe port to prevent kubelet health probes from being blocked (see AKS/Azure CNI section above).

4. **Per-component egress policies**: each component gets an egress policy limited to its required destinations (see matrix above).

5. **Shared Redis HA**: a single ingress policy on the Redis HA pods allowing port 6379 from the set of app pod selectors.

6. **Keycloak jobs**: narrow egress to Keycloak port 8080 only (+ port 5432 for the psql init job). These are one-shot Jobs — the policy can be tied to the Job pod label.

7. **DNS egress**: all pods need egress to `kube-dns` on port 53 UDP/TCP (ClusterIP `10.0.0.10` on AKS) — easy to forget and blocks all name resolution if omitted.

8. **External egress**: the API proxy needs egress to `0.0.0.0/0:443` (or specific IP ranges for government APIs). All other pods should have no egress to the internet except via the API proxy or through the ingress controller's public path.

> **Ambiguity to resolve before implementing:** Most apps use public Keycloak `oidcUrl` values (through the ingress), so OIDC traffic from app pods goes through the ingress controller, not directly to the Keycloak service. If direct internal OIDC URLs are ever used, additional pod→keycloak allow rules would be needed per app.
