# Redis HA — Operator Bug, Label Drift, and Mitigation

## Background

The Redis HA setup uses the [OT-CONTAINER-KIT redis-operator](https://github.com/OT-CONTAINER-KIT/redis-operator) (`quay.io/opstree/redis-operator`) to manage a 3-node Redis replication StatefulSet (`redis-ha`). A Kubernetes Service (`redis-ha-master`) routes writes to the current master by selecting pods labelled `redis-role=master`.

## Known Bug: redis-operator 0.24.0 — empty pod name crash loop

**Affects:** `redis-operator` v0.24.0 and earlier.

**Upstream fix:** [PR #1720](https://github.com/OT-CONTAINER-KIT/redis-operator/pull/1720) — merged 2026-03-26, **released in `0.25.0`** (2026-05-13) and confirmed still present in `0.26.1`, the version currently pinned in `Chart.yaml`.

**Symptoms:** The operator logs repeat every ~60 seconds:

```text
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
2. Compares it to every pod currently carrying `redis-role=master`
3. If exactly that pod carries it — exits immediately (`Labels correct: <pod> is master. Nothing to do.`)
4. If they differ — applies `redis-role=master` to the CR master pod and `redis-role=slave` to the others

With `masterReadinessCheck` on (the default since 4.10.0) the CronJob is also the only thing that
removes a stale master label. After a failover the old master can keep `redis-role=master` for a
while; the readiness check makes it NotReady, and redis-operator v0.27.0 skips pods that aren't
Ready when it fixes role labels. Keep the CronJob enabled as long as the readiness check is on.

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

## Known Bug: redis-operator 0.26.x — replication loop after an unreachable pod

**Affects:** `redis-operator` v0.26.0 (PodiumD 4.9.x).

**Upstream fix:** [PR #1843](https://github.com/OT-CONTAINER-KIT/redis-operator/pull/1843)
("skip unreachable RedisReplication pods during role discovery", issue #1842), released in
`0.27.0`, the version in PodiumD 4.10.0.

**Symptoms:** the operator logs these two lines about every 16 seconds, for hours or days:

```text
"Skipping replication reconfiguration because the current master could not be identified"
"Creating redis replication by executing replication creation commands"
```

Every round re-runs `REPLICAOF` on the pods. Each Celery worker blocked on its broker (all
Maykin workers use `redis-ha-master`) then exits with:

```text
Unrecoverable error: ResponseError('UNBLOCKED force unblock from blocking operation, instance state changed (master -> replica?)')
```

So all workers restart over and over. On test-rott (4.9.5, operator v0.26.0) this ran from
17 October 2026 06:58 UTC until the `redis-ha` pods were recreated on 20 October: the
Objecten worker restarted 637 times, Open Archiefbeheer 502, Open Klant 495, Open Zaak 436
and Open Notificaties 131.

**Root cause:** in v0.26.0 one Redis pod that Kubernetes reports as Ready but that does not
answer over Redis (for example after a node fault) makes the role discovery fail, so the
operator never finds the master and keeps reconfiguring replication.

**Mitigation in 4.9.x:** delete the `redis-ha` pods so they restart together, or upgrade to
4.10.0.

---

## Failover safeguards (since 4.10.0)

Three settings under `redis-operator.redis-ha` limit what a failover does to the apps:

| Value | Default | Effect |
| --- | --- | --- |
| `topologySpreadConstraints` | `maxSkew: 1` on `kubernetes.io/hostname`, `ScheduleAnyway` | The Redis pods go to different nodes where possible, so one node fault or drain takes out at most one of them. |
| `pdb` | `enabled: true`, `maxUnavailable: 1` | The operator creates a PodDisruptionBudget: a node drain evicts one Redis pod at a time. |
| `masterReadinessCheck.enabled` | `true` | A pod labelled `redis-role=master` that reports `role:slave` itself is NotReady, so it drops out of the `redis-ha-master` Service (IN-2961). |

Why the readiness check: the operator sets the new `redis-role=master` label before it removes
the old one. For about half a minute the `redis-ha-master` Service then also points at a
replica, and apps that connect in that window write to a read-only replica (IN-2869). The
check reads the pod's own labels from a downward API volume (`/etc/podinfo/labels`, refreshed
by the kubelet) and compares them with `INFO replication`. A correctly labelled replica is never
NotReady, so StatefulSet rolling updates are not blocked. Without any genuine master the
Service has no endpoints, and apps get a connection error instead of a rejected write.

Not covered here: a connection an app already holds to a replica stays there until the app
reconnects or restarts (IN-2962, for Maykin).

The spread only applies where the scheduler has a choice. The Redis volumes are zonal disks, so
an existing pod restarts in the zone of its disk; to move a replica, recreate it with a new volume
as described in the 4.10.0 upgrade guide ("Redis HA: failover safeguards").

---

## Upgrade path

The `redis-operator` subchart has carried PR #1720 since `0.25.0` (see above) — the chart is now on `0.26.1`, so this is no longer pending. The label-master CronJob is a **candidate for removal**
(`redis-operator.redis-ha.labelMasterCronJob.enabled: false`), but this has not been verified in
practice yet: before disabling it, confirm in a test environment that the operator self-heals
correctly after a simultaneous pod restart of all three `redis-ha` pods (e.g. during a Helm upgrade
that touches the StatefulSet). Once verified, disable the CronJob and remove this doc's "Known Bug"
framing (fold the historical context into a changelog note instead).

With `masterReadinessCheck` enabled the CronJob must stay: it is what removes the master label
from an old master that the readiness check made NotReady (see above).

Track: [https://github.com/OT-CONTAINER-KIT/redis-operator/releases](https://github.com/OT-CONTAINER-KIT/redis-operator/releases)
