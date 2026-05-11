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

---

## Image overrides for ACR-restricted environments

Some clusters enforce an Azure Policy assignment (e.g. `K8sAzureV2ContainerAllowedImages`) that only admits pods whose container images come from an allowed registry — typically the organisation's own Azure Container Registry. On those clusters, the upstream defaults shipped by this chart (`quay.io/opstree/redis-operator`, `quay.io/opstree/redis`, `docker.io/library/busybox`, `docker.io/alpine/k8s`) are rejected at admission, and the `redis-ha-label-master` CronJob in particular fails on every run — so the `redis-role=master` label never lands on the master pod, `Service/redis-ha-master` ends up with empty endpoints, and every Redis-dependent app crashes on first connection.

**Reference incident:** IN-2021 — `aks-blue-ontw-mayk` openformulieren 502 (root cause: `busybox:1.37.0-glibc` and `quay.io/opstree/redis:v8.4.2` denied by `K8sAzureV2ContainerAllowedImages`).

### How to fix

Mirror every image referenced by the `redis-operator` block into the cluster's allowed registry, then override the chart values per environment. Example overlay:

```yaml
# Per-environment values overlay (e.g. values-<cluster>.yaml).
# Replace <ACR> with your registry hostname (e.g. acrprodmgmt.azurecr.io).

redis-operator:
  redisOperator:
    imageName: <ACR>/redis-operator        # default: quay.io/opstree/redis-operator
    # imageTag unchanged — keep matching the chart default
  redis-ha:
    image:
      registry: <ACR>                      # default: quay.io
      repository: redis                    # default: opstree/redis (mirror name in ACR is conventionally just `redis`)
      # tag unchanged
    redisExporter:
      image:
        registry: <ACR>                    # default: quay.io
        repository: redis-exporter         # default: opstree/redis-exporter
        # tag unchanged
    initContainerImage:
      repository: <ACR>/busybox            # default: busybox (implicit docker.io/library/busybox)
      # tag unchanged
    labelMasterCronJob:
      image:
        repository: <ACR>/alpine/k8s       # default: docker.io/alpine/k8s
        # tag unchanged
```

### Required ACR imports

Each override above requires the corresponding image to be present in `<ACR>` first. In the SSC Twente setup these are mirrored via the `Container Image Import` pipeline (`ExternalsPodiumD/pipelines/images.yml`, ADO pipeline id `108`), which uses `skopeo copy --all` so multi-arch manifests survive the round trip:

| Source                                          | ACR repo (after import)        | Used for                                                                    |
|-------------------------------------------------|--------------------------------|-----------------------------------------------------------------------------|
| `quay.io/opstree/redis-operator:<tag>`          | `redis-operator`               | redis-operator Deployment                                                   |
| `quay.io/opstree/redis:<tag>`                   | `redis`                        | redis-ha StatefulSet                                                        |
| `quay.io/opstree/redis-exporter:<tag>`          | `redis-exporter`               | optional sidecar (see `values-enable-observability.yaml`)                   |
| `docker.io/library/busybox:1.37.0-glibc`        | `busybox`                      | redis-ha `initContainer` that appends `databases N` to `redis.conf`         |
| `docker.io/alpine/k8s:<tag>`                    | `alpine/k8s`                   | `redis-ha-label-master` CronJob (workaround for redis-operator 0.24.0 bug)  |

Confirm the import has run before the chart upgrade — otherwise pods will fail with `ImagePullBackOff` rather than the policy denial:

```bash
az acr repository show-tags --name <acr-name> --repository redis            --output table
az acr repository show-tags --name <acr-name> --repository busybox          --output table
az acr repository show-tags --name <acr-name> --repository alpine/k8s       --output table
```

### Caveats

- **`solr.busyBoxImage`** elsewhere in `values.yaml` also defaults to `library/busybox:1.37.0-glibc`. If the same Azure Policy applies cluster-wide, that field needs the same `<ACR>/busybox` override or the SolrCloud init will be denied admission too.
- **Tag drift.** Whenever this chart bumps any of the redis-operator subchart images (operator, redis-ha, redis-exporter), the matching tag must be added to `ExternalsPodiumD/pipelines/images.yml` *and* the import pipeline re-run *before* the chart upgrade reaches an ACR-restricted cluster.
- **Why the in-place mitigation in IN-2021 worked anyway.** Removing the `redis-role` selector key from `Service/redis-ha-master` is a pure Service-spec edit (no new pod admission), so it bypasses the policy entirely. It's only safe with a single Redis replica and is intended as a temporary workaround until the image overrides above are in place.
