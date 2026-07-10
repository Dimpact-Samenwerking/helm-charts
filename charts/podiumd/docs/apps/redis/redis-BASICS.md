# Redis HA — Basics

## Management summary

Redis is the shared in-memory data store of PodiumD. It is not something a
citizen or civil servant ever sees: it makes the other applications fast and
lets them do work in the background. Almost every Django-based PodiumD app
(Open Zaak, Open Notificaties, Open Inwoner, Open Formulieren, Open Klant,
Open Archiefbeheer, Objecten, Objecttypen and more) uses it as a page/session
cache and as the queue for background tasks such as sending notifications and
processing documents. If Redis is down, those apps hang at startup and
background work stops. It needs no database and no public hostname — just
three small pods with a 2Gi disk each, run and healed automatically by an
operator.

## What it is

- Upstream: [Redis](https://redis.io/), deployed and managed by the
  [OT-CONTAINER-KIT redis-operator](https://github.com/OT-CONTAINER-KIT/redis-operator).
- Images: `quay.io/opstree/redis` tag `v8.6.2`
  (`redis-operator.redis-ha.image`); operator `quay.io/opstree/redis-operator`
  tag `v0.25.0` (`redis-operator.redisOperator`).
- Role in PodiumD: one shared HA Redis cluster replaces the per-component
  Redis subcharts. Each app gets its own **logical databases** (32 configured,
  `redis-operator.redis-ha.databases`) — see the allocation table in
  [redis-ha-databases.md](redis-ha-databases.md).
- Deployed as a `RedisReplication` custom resource (apiVersion
  `redis.redis.opstreelabs.in/v1beta2`, name `redis-ha`), rendered by
  `charts/podiumd/templates/redis-ha.yaml`. There is **no Sentinel** CR:
  the operator elects a master and labels pods `redis-role=master/slave`;
  the `redis-ha-master` Service selects the master pod.
- Runtime components:
  - `redis-operator` deployment — 1 replica (the controller)
  - `redis-ha` StatefulSet — 3 replicas (`redis-ha-0/1/2`,
    `redis-operator.redis-ha.replicaCount`), 1 master + 2 replicas
  - initContainer (busybox `1.38.0-glibc`,
    `redis-operator.redis-ha.initContainerImage`) — appends `databases 32`
    to `redis.conf`, because `databases` is a startup-only parameter the
    operator cannot set itself
  - `redis-ha-label-master` CronJob (every 2 minutes,
    `redis-operator.redis-ha.labelMasterCronJob`) — reconciles the
    `redis-role` labels from `RedisReplication.status.masterNode`; workaround
    for an operator bug where the `redis-ha-master` Service loses its
    endpoints after a simultaneous pod restart (see
    [redis-ha.md](redis-ha.md))
  - optional `redis-exporter` sidecar (`quay.io/opstree/redis-exporter`
    `v1.82.0`, port 9121) + PodMonitor — disabled by default, enabled via
    `values-enable-observability.yaml`

## Required resources

### Database

- PostgreSQL: **no**. Redis is itself the datastore (in-memory, persisted to
  its own PVC). No `DB_PASSWORD` Secret / `DB_HOST` ConfigMap contract
  applies.

### Storage

- PVC: **yes** — one per replica (3 total) via the StatefulSet
  `volumeClaimTemplate` (`redis-operator.redis-ha.storage`): 2Gi each,
  storage class `managed-csi-premiumv2` (Azure managed disk — **not** the
  Azure Files `podiumd-standard` class used by the apps), access mode
  ReadWriteOnce.
- `managed-csi-premiumv2` supports online volume expansion — to grow, patch
  the PVC directly:
  `kubectl patch pvc <pvc-name> -n podiumd -p '{"spec":{"resources":{"requests":{"storage":"8Gi"}}}}'`.
- `podSecurityContext.fsGroup: 1000` matches the redis container GID so the
  mounted data directory is writable.

### Routing / exposure (NGINX Gateway Fabric)

- **Cluster-internal only.** No HTTPRoute, no public hostname.
- Apps connect to the write endpoint
  `redis-ha-master.podiumd.svc.cluster.local:6379` — a ClusterIP Service
  selecting the pod labelled `redis-role=master`.

### Other dependencies

- None outbound: Redis needs no Keycloak client, no SMTP, no external APIs.
- Inbound, it is a dependency **of** nearly everything: each Django app is
  assigned one or two of the 32 logical databases. Summary (full table and
  rules in [redis-ha-databases.md](redis-ha-databases.md)):

  | DB | Component | DB | Component |
  |----|-----------|----|-----------|
  | 0 | objecttypen (cache) | 9–10 | openformulieren (cache / celery) |
  | 1–2 | objecten (cache / celery) | 11–12 | openinwoner (cache / celery) |
  | 3, 6 | opennotificaties (cache / celery result backend¹) | 13–14 | openarchiefbeheer (cache+axes / choices+celery) |
  | 4–5 | openzaak (cache / celery) | 15–16 | referentielijsten (cache / reserved) |
  | 7–8 | openklant (cache / celery) | 17–18 | openbeheer (cache / reserved) |
  | | | 19–20 | reserved for next component; 21–31 unallocated |

  ¹ Per the `values.yaml` allocation comment, the opennotificaties Celery
  broker is also Redis (instead of RabbitMQ) since opennotificaties chart
  2.0.0.
- Logical databases give key-namespace isolation only — **no** memory or
  performance isolation; all 32 share one memory pool.

## CPU and memory

Chart defaults (`charts/podiumd/values.yaml` + `docs/misc/resource-overview.md`):

| Container | Replicas | CPU request | Mem request | CPU limit | Mem limit |
|-----------|----------|-------------|-------------|-----------|-----------|
| redis-operator | 1 | 100m | 128Mi | 500m | 256Mi |
| redis-ha | 3 | 100m | 256Mi | 500m | 512Mi |
| redis-ha initContainer (busybox) | per pod | 10m | 16Mi | 50m | 32Mi |
| redis-exporter sidecar (optional) | per pod | 100m | 128Mi | 500m | 256Mi |
| redis-ha-label-master CronJob | — | 10m | 32Mi | 100m | 64Mi |

**Observed usage** (kubectl top, 2026-07-10): on `aks-blue-ontw-dimp` the
three redis-ha pods used 14–21m CPU / 115–124Mi and the operator 4m / 30Mi;
on `aks-blue-accp-dimp` redis-ha 6–17m / 81–94Mi and the operator 5m / 35Mi —
comfortably inside the 256Mi request. `resource-overview.md` flags Redis
memory as **"Increase for production"**: Redis holds all Celery task queues
and Django caches, so memory grows with queued task volume; the suggested
production sizing (request 256Mi, limit 512Mi) is already the chart default —
monitor and raise per environment if queues back up. CPU numbers are idle-ish
baselines, not peaks. The 3-replica StatefulSet has built-in quorum; a PDB is
not required but `minAvailable: 2` may be added to protect quorum.

## Integrating a new app with Redis

Redis itself ships with the umbrella chart (`redis-operator.enabled: true`,
`redis-operator.redis-ha.enabled: true`) — nothing extra is deployed per app.
"Integrating" means claiming logical database indexes for a new component:

1. **Pick the next free DB indexes** from the allocation table in
   [redis-ha-databases.md](redis-ha-databases.md). Convention: one DB for
   cache (+axes), one for Celery. At time of writing db 19 (cache) and
   db 20 (celery) are reserved for the next component; db 21–31 are
   unallocated.
2. **Set the app's Redis URLs** in its `settings` block in `values.yaml`.
   Cache URLs take **no** scheme prefix; Celery URLs **must** have
   `redis://`:

   ```yaml
   newcomponent:
     settings:
       cache:
         default: redis-ha-master.podiumd.svc.cluster.local:6379/19
         axes: redis-ha-master.podiumd.svc.cluster.local:6379/19
       celery:
         brokerUrl: redis://redis-ha-master.podiumd.svc.cluster.local:6379/20
         resultBackendl: redis://redis-ha-master.podiumd.svc.cluster.local:6379/20
   ```

   (The `resultBackendl` spelling — trailing `l` — is intentional; it matches
   the upstream Maykin chart key.)
3. **Record the allocation** in both places: the comment block under
   `redis-operator:` in `charts/podiumd/values.yaml` and the table in
   [redis-ha-databases.md](redis-ha-databases.md).
4. **Disable the component's standalone Redis subchart** (if its upstream
   chart bundles one): `tags.redis: false` and `redis.enabled: false` under
   the component's values block.
5. **Verify**: after deploying the app, check its keyspace is live —
   `kubectl exec -n podiumd redis-ha-0 -c redis-ha -- redis-cli INFO keyspace`
   should list `db19`/`db20` with keys, and the app's worker log should show
   Celery connected to `redis://redis-ha-master...:6379/20`.

## Related documents

- [redis-ha.md](redis-ha.md) — the redis-operator 0.24.0 empty-pod-name bug
  (upstream PR #1720), the resulting `redis-role` label drift, the
  `redis-ha-label-master` CronJob mitigation, and manual recovery steps.
- [redis-ha-databases.md](redis-ha-databases.md) — full logical-database
  allocation table, connection URL formats, and the procedure for adding a
  new Django component.
