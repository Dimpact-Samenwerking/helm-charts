# Open Zaak — Database Connection Pooling

## Status

> ⚠️ **Partially experimental** — this document proposes two independent sets of changes with different stability statuses:
>
> - **uWSGI settings** (`processes`, `threads`, `maxRequests`) — **not experimental**. These are standard uWSGI configuration knobs, fully supported and carry no caveats in the Open Zaak chart or documentation.
> - **DB connection pooling** (`dbPool.enabled: true`) — **explicitly experimental**. Open Zaak marks this as *not recommended for production use*. See: https://open-api-framework.readthedocs.io/en/latest/connection_pooling.html
>
> The uWSGI settings can be applied independently and safely. The pooling settings should only be applied after testing in a non-production environment and verifying stability under load — or once the Open Zaak team lifts the experimental label.

---

## Background

Open Zaak currently uses Django's legacy persistent connections (`DB_CONN_MAX_AGE=60`). This keeps a connection open per thread for up to 60 seconds, which is simple but does not cap total connection count or handle connection rotation.

The pooling feature uses psycopg3's built-in connection pool, operating at the **uWSGI process level**: each process maintains a shared pool that all its threads draw from. This reduces total connections to the database and allows explicit rotation of connections to prevent memory accumulation.

Connection pooling is completely separate from an external PgBouncer; these settings use Django's own pool and do **not** require `dbDisableServerSideCursors`.

---

## Proposed Values

Add the following to `openzaak.settings` in `values.yaml` (or an environment override file):

```yaml
openzaak:
  settings:
    uwsgi:
      processes: "2"       # 2 uWSGI worker processes per pod
      threads: "4"         # 4 threads per process (8 concurrent threads per pod)
      maxRequests: "1000"  # recycle worker process after 1000 requests — primary guard against memory bloat
    database:
      dbPool:
        enabled: true
        dbPoolMinSize: 4          # min connections per process; min=max → fixed pool
        dbPoolMaxSize: 4          # fixed pool: 2 processes × 4 conns = 8 conns per pod
        dbPoolMaxLifetime: 1800   # rotate connections after 30 min (default: 3600)
        dbPoolMaxIdle: 300        # close idle surplus connections after 5 min (default: 600)
        dbPoolTimeout: 30         # max wait for a free connection before error (default: 30)
        dbPoolMaxWaiting: 0       # no queue limit (0 = unlimited)
        dbPoolNumWorkers: 3       # background threads maintaining pool health (default: 3)
        dbPoolReconnectTimeout: 300  # give up reconnecting after 5 min (default: 300)
```

---

## Rationale

### uWSGI process/thread settings

| Setting | Value | Reason |
|---------|-------|--------|
| `processes` | 2 | 2 processes × 2 replicas = 4 total processes; well-suited to 250m CPU request |
| `threads` | 4 | 4 threads per process; higher than pool size so threads share the pool efficiently |
| `maxRequests` | 1000 | Recycles the worker process after 1000 requests, releasing any accumulated memory from Django request cycles, large ZTC/ZRC payloads, and GC-unreachable references |

### Pool sizing: `min = max < threads`

This is the configuration recommended by the Open Zaak/open-api-framework documentation as the most useful pattern:

```
DB_POOL_MIN_SIZE (4) = DB_POOL_MAX_SIZE (4) < UWSGI_THREADS (4)
```

Each process holds exactly 4 connections. With `min = max`, the pool never grows or shrinks, giving predictable and stable connection counts:

- Per pod: 2 processes × 4 connections = **8 connections**
- Across 2 replicas: **16 connections total**

This is well within the default Azure Database for PostgreSQL connection limits.

### Connection rotation: `maxLifetime` and `maxRequests`

Two mechanisms work together to prevent memory leaks and stale connections:

1. **`maxRequests: 1000`** (uWSGI) — rotates the entire worker process. This is the primary guard against Django-level memory leaks (ORM query plan caches, signal receiver accumulation, etc.).
2. **`dbPoolMaxLifetime: 1800`** (pool) — rotates individual connections after 30 minutes. psycopg3 closes and replaces them with fresh ones (with a ±10% jitter to avoid mass eviction). This prevents PostgreSQL-side session state from accumulating and avoids hitting `idle_in_transaction_session_timeout`.

### `dbPoolMaxIdle: 300`

Reduced from the default 600s to 300s. Since `min = max`, the pool is fixed and this setting has no effect in normal operation (it only triggers when `max > min`). It is included explicitly to document intent and as a safety net if pool sizing is changed later.

---

## What changes from current behavior

| | Current | Proposed |
|--|---------|----------|
| Connection model | 1 connection per thread, per pod (up to 16 total) | Pool per process; fixed 4 conns per process (8 per pod, 16 total) |
| `DB_CONN_MAX_AGE` | 60s (active) | ignored when pooling is enabled |
| Connection lifetime | up to 60s per request cycle | 30 min hard rotation via `maxLifetime` |
| Worker recycling | none | every 1000 requests via `maxRequests` |
| Max total DB connections | 16 (2 replicas × 2 processes × 4 threads) | 16 (2 replicas × 2 processes × 4 pool conns) |

The total connection count is the same, but the pool gives more control over lifetime and rotation.

---

## Before applying

### uWSGI settings (safe to apply now)
- [ ] Verify `processes` and `threads` align with the pod's CPU request (250m supports 2 processes comfortably)
- [ ] Apply to acceptance environment and monitor pod memory over time with `maxRequests` recycling

### DB connection pooling (apply only when no longer experimental)
- [ ] Check whether the Open Zaak team has lifted the "experimental" label in a newer release
- [ ] Test on an acceptance/OTAP environment first
- [ ] Monitor with `SELECT count(*) FROM pg_stat_activity WHERE datname = 'openzaak'` before and after
- [ ] Watch for `TooManyRequests` errors in logs (would indicate pool exhaustion)
- [ ] Confirm Open Zaak version supports psycopg3 pool (requires open-api-framework ≥ current; Open Zaak 1.26.0 ✅)
