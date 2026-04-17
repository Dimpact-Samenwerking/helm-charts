# Redis HA — Operator Bug, Label Drift, and Mitigation

## Background

The Redis HA setup uses the [OT-CONTAINER-KIT redis-operator](https://github.com/OT-CONTAINER-KIT/redis-operator) (`quay.io/opstree/redis-operator`) to manage a 3-node Redis replication StatefulSet (`redis-ha`). A Kubernetes Service (`redis-ha-master`) routes writes to the current master by selecting pods labelled `redis-role=master`.

## Known Bug: redis-operator 0.24.0 — empty pod name crash loop

**Affects:** `redis-operator` v0.24.0 (latest release as of April 2026)

**Upstream fix:** [PR #1720](https://github.com/OT-CONTAINER-KIT/redis-operator/pull/1720) — merged 2026-03-26, **not yet released**

**Symptoms:** The operator logs repeat every ~60 seconds:

```
"Error in getting Redis pod IP"
"error":"resource name may not be empty"
stacktrace: getRedisServerIP @ internal/k8sutils/redis.go:50
             CreateMasterSlaveReplication
             reconcileRedis
```

**Root cause:** When all three Redis pods restart simultaneously (e.g. during a Helm upgrade that updates the StatefulSet), `GetRedisReplicationRealMaster()` returns an empty string because at that moment no pod yet has connected slaves (`connected_slaves:0`). That empty string is passed to `getRedisServerIP("")`, which calls the Kubernetes API with an empty resource name and fails.

**Effect:** The operator cannot set up replication topology or apply `redis-role` labels to pods. The `redis-ha-master` Service ends up with no endpoints, causing all dependent apps (openzaak, opennotificaties, kiss, zac, etc.) to hang on first Redis connection and fail their startup/readiness probes.

**Upstream fix summary (PR #1720):** Adds a fallback chain — if the live Redis check returns empty, fall back to `status.masterNode` from the `RedisReplication` CR, then fall back to `masterNodes[0]`.

**Workaround until a fixed release is available:** See label-master job and CronJob sections below.

---

## The `redis-ha-label-master` Job

A Helm post-install/post-upgrade Job (`templates/redis-ha-label-master.yaml`) was added as a workaround. It:

1. Waits for all `redis-ha` pods to be Running
2. Reads the authoritative master from `RedisReplication.status.masterNode`
3. Applies `redis-role=master` to the master pod and `redis-role=slave` to the others
4. Verifies the `redis-ha-master` Service endpoint is populated before exiting

### Gap 1: Early exit when label already exists

The job skips labeling entirely if any pod already carries `redis-role=master` (lines 96–103 of the template). This is safe for the happy path (operator recovered by itself) but **fails silently** if:

- The label is present on the wrong pod (stale from a previous master)
- The label drifts away after the job completes

### Gap 2: One-shot execution — TTL 10 minutes

The job has `ttlSecondsAfterFinished: 600`. Once it completes and is cleaned up, there is no ongoing process to re-apply labels if the operator later fails to maintain them. This was observed in production on 2026-04-17:

- Helm upgrade to 4.6.4 ran → label-master job applied labels correctly → job TTL'd
- Over time the operator's reconciliation loop continued failing silently
- Pod restarts caused labels to drift; the `redis-ha-master` Service lost its endpoint
- All apps using Redis (openzaak, ZAC, etc.) failed to start or became not-ready

**Manual recovery applied (2026-04-17):**
```bash
MASTER_IP=$(kubectl get pod redis-ha-0 -n podiumd -o jsonpath='{.status.podIP}')
kubectl exec -n podiumd redis-ha-1 -c redis-ha -- redis-cli REPLICAOF $MASTER_IP 6379
kubectl exec -n podiumd redis-ha-2 -c redis-ha -- redis-cli REPLICAOF $MASTER_IP 6379
kubectl label pod redis-ha-0 -n podiumd redis-role=master --overwrite
kubectl label pod redis-ha-1 -n podiumd redis-role=slave --overwrite
kubectl label pod redis-ha-2 -n podiumd redis-role=slave --overwrite
```

---

## Recommended Fix: Replace Job with a CronJob

To close the gap until a fixed operator release is available, replace or supplement the one-shot Job with a CronJob that runs every 1–2 minutes. The key change from the current job script is to **remove the early-exit** — always reconcile the label from the live Redis state or the CR, rather than skipping if a label already exists.

Logic the CronJob should implement:

1. Determine the real master: query each pod with `redis-cli INFO replication`, find the one with `role:master` that the others are replicating from (or fall back to `RedisReplication.status.masterNode`)
2. Apply `redis-role=master` to that pod (always, with `--overwrite`)
3. Apply `redis-role=slave` to all other redis-ha pods
4. Optionally verify the `redis-ha-master` Service endpoint is populated

The CronJob needs the same RBAC (get/list/patch pods, get endpointslices, get redisreplications) as the existing Job.

---

## Upgrade path

Once OT-CONTAINER-KIT releases a version containing PR #1720, bump the `redis-operator` subchart to that version. At that point the label-master CronJob can be disabled/removed as the operator will correctly self-heal after simultaneous pod restarts.

Track: https://github.com/OT-CONTAINER-KIT/redis-operator/releases
