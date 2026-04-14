# Redis HA Database Allocation

PodiumD uses a single shared Redis HA cluster (3 replicas, managed by the OT Redis Operator)
instead of per-component Redis subcharts. Each component is assigned one or two dedicated
logical databases within Redis, identified by the `/N` suffix in the connection URL.

The Redis HA service is reachable at:
```
redis-ha-master.podiumd.svc.cluster.local:6379
```

The cluster is configured with **32 logical databases** (`databases: 32` in `values.yaml`).
This is set via an initContainer because `databases` is a startup-only parameter and the OT
Redis Operator v0.24.0 does not include it in the main `redis.conf` automatically.

---

## Database Allocation Table

| DB  | Component         | Purpose                              | values.yaml key(s)                                  |
|-----|-------------------|--------------------------------------|-----------------------------------------------------|
| 0   | objecttypen       | Cache (default + axes)               | `objecttypen.settings.cache.default/axes`           |
| 1   | objecten          | Cache (default + axes + oidc)        | `objecten.settings.cache.default/axes/oidc`         |
| 2   | objecten          | Celery broker + result backend       | `objecten.settings.celery.brokerUrl/resultBackendl` |
| 3   | opennotificaties  | Cache (default + axes)               | `opennotificaties.settings.cache.default/axes`      |
| 4   | openzaak          | Cache (default + axes)               | `openzaak.settings.cache.default/axes`              |
| 5   | openzaak          | Celery broker + result backend       | `openzaak.settings.celery.brokerUrl/resultBackendl` |
| 6   | opennotificaties  | Celery result backend only¹          | `opennotificaties.settings.celery.celeryResultBackend` |
| 7   | openklant         | Cache (default + axes)               | `openklant.settings.cache.default/axes`             |
| 8   | openklant         | Celery broker + result backend       | `openklant.settings.celery.brokerUrl/resultBackendl` |
| 9   | openformulieren   | Cache (default + axes)               | `openformulieren.settings.cache.default/axes`       |
| 10  | openformulieren   | Celery broker + result backend       | `openformulieren.settings.celery.brokerUrl/resultBackendl` |
| 11  | openinwoner       | Cache (default + axes)               | `openinwoner.settings.cache.default/axes`           |
| 12  | openinwoner       | Celery broker + result backend       | `openinwoner.settings.celery.brokerUrl/resultBackendl` |
| 13  | openarchiefbeheer | Cache (default + axes)               | `openarchiefbeheer.settings.cache.default/axes`     |
| 14  | openarchiefbeheer | Cache (choices) + Celery broker + result backend² | `openarchiefbeheer.settings.cache.choices` + celery |
| 15  | referentielijsten | Cache (default + axes)               | `referentielijsten.settings.cache.default/axes`     |
| 16  | referentielijsten | **Reserved** — celery not yet used   | —                                                   |
| 17  | openbeheer        | Cache (default + axes)               | `openbeheer.settings.cache.default/axes`            |
| 18  | openbeheer        | **Reserved** — celery not yet used   | —                                                   |
| 19  | *(future)*        | Cache (default + axes)               | See [Adding a new component](#adding-a-new-django-component) |
| 20  | *(future)*        | Celery broker + result backend       | See [Adding a new component](#adding-a-new-django-component) |
| 21–31 | —             | **Unallocated**                      | —                                                   |

> ¹ `opennotificaties` uses RabbitMQ as its Celery broker. Redis db 6 is only used as the
> Celery result backend.
>
> ² `openarchiefbeheer` reuses db 14 for both the `choices` cache backend and Celery
> (broker + result backend).

---

## Why Logical Databases?

Redis logical databases (`SELECT N`) provide namespace isolation within a single Redis
instance. Each component's keys are scoped to its own database number, preventing accidental
key collisions between components (e.g. a `session:xyz` key in openzaak cannot clash with
one in openklant).

**Important:** Logical databases do **not** provide performance or memory isolation. All
databases share the same Redis memory pool. If one component produces excessive key volume,
it affects all components. Monitor Redis memory usage across the cluster.

---

## Connection URL Format

Django-based components use two types of Redis connections:

| Type | URL format | Example |
|------|-----------|---------|
| Cache | `host:port/N` | `redis-ha-master.podiumd.svc.cluster.local:6379/4` |
| Celery broker | `redis://host:port/N` | `redis://redis-ha-master.podiumd.svc.cluster.local:6379/5` |
| Celery result backend | `redis://host:port/N` | `redis://redis-ha-master.podiumd.svc.cluster.local:6379/5` |

Cache URLs do **not** include the `redis://` prefix — Django's cache backend adds this
internally. Celery URLs **must** include the `redis://` prefix.

---

## Adding a New Django Component

When adding a new Django-based component to the chart, follow these steps:

1. **Pick the next two unallocated database numbers** from the table above. At time of writing,
   the next free pair is **db 19 (cache) and db 20 (celery)**.

2. **Add the Redis endpoints to the component's `settings` block in `values.yaml`:**

   ```yaml
   # Example: future-component — uses db 19 (cache) and db 20 (celery)
   future-component:
     settings:
       cache:
         default: redis-ha-master.podiumd.svc.cluster.local:6379/19
         axes: redis-ha-master.podiumd.svc.cluster.local:6379/19
       celery:
         brokerUrl: redis://redis-ha-master.podiumd.svc.cluster.local:6379/20
         resultBackendl: redis://redis-ha-master.podiumd.svc.cluster.local:6379/20
   ```

   > **Note:** The `resultBackendl` key has a typo (extra `l`) — this is intentional to match
   > the upstream Maykin Media chart's values key.

3. **Update the allocation table comment in `values.yaml`** under `redis-operator.redis-ha`:

   ```yaml
   #   future-component   : db 19 (cache), db 20 (celery)
   ```

4. **Update this document** — add the new component to the allocation table above.

5. **Remove or disable the component's standalone `redis:` subchart block** (if present).
   Standalone per-component Redis subcharts are disabled globally in this chart. Leaving the
   block in place is harmless but may cause confusion — remove it when migrating a component
   to the shared cluster.

---

## Standalone Redis Subchart Blocks

Some component sections in `values.yaml` still contain a `redis:` subchart configuration
block (e.g. `referentielijsten.redis`, `openbeheer.redis`). These are **not active** — the
subchart is disabled globally via the chart dependency configuration. The blocks remain as
reference for environments that may need to revert to per-component Redis, but can be removed
once the shared Redis HA approach is confirmed stable for all components.

---

## Reservations

Database numbers are reserved (not yet configured in the application) when:
- The component is new to the chart and Celery support is unknown or not yet implemented.
- A future feature may require Celery (e.g. background tasks, async processing).

Reserved databases are pre-allocated in the table to prevent future conflicts. The next
maintainer assigning a new component can safely skip them and pick from the **Unallocated**
range (db 21–31).
