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

**Current mitigation:** The `redis-ha-label-master` CronJob described below.

---

## The `redis-ha-label-master` CronJob (since 4.6.4)

`templates/redis-ha-label-master.yaml` defines a CronJob that runs every 2 minutes. Each run:

1. Reads the authoritative master from `RedisReplication.status.masterNode`
2. Compares it to the pod currently carrying `redis-role=master`
3. If they match — exits immediately (`Labels correct: <pod> is master. Nothing to do.`)
4. If they differ — applies `redis-role=master` to the CR master pod and `redis-role=slave` to the others

Unlike the previous one-shot Job, the CronJob:
- Always reconciles from the CR — no early-exit based on an existing label
- Runs continuously, so label drift is corrected within 2 minutes
- Uses `backoffLimit: 0` and `restartPolicy: Never` — a failed run is discarded; the next scheduled run retries

### Pre-4.6.4 history (one-shot Job)

Before 4.6.4 a Helm post-install/post-upgrade Job handled labelling. It had two gaps:

**Gap 1 — Early exit on existing label:** The job skipped labelling if any pod already carried `redis-role=master`, which silently failed when the label was on the wrong pod or had drifted.

**Gap 2 — One-shot execution (TTL 10 min):** After the job completed and was cleaned up by its `ttlSecondsAfterFinished: 600`, no ongoing process re-applied labels if the operator later failed. This was observed on 2026-04-17:

- Helm upgrade ran → one-shot job applied labels correctly → job TTL'd
- Operator's reconciliation loop continued failing silently
- Pod restarts caused labels to drift; `redis-ha-master` Service lost its endpoint
- All Redis-dependent apps failed to start

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

## Upgrade path

Once OT-CONTAINER-KIT releases a version containing PR #1720, bump the `redis-operator` subchart to that version. At that point the label-master CronJob can be disabled (`redis-operator.redis-ha.labelMasterCronJob.enabled: false`) as the operator will correctly self-heal after simultaneous pod restarts.

Track: https://github.com/OT-CONTAINER-KIT/redis-operator/releases
