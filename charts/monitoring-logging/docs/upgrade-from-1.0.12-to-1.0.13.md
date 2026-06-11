# Upgrade guide: monitoring-logging 1.0.12 → 1.0.13

## Summary of changes

This release narrows Alloy's log collection scope to the `podiumd` and `monitoring` namespaces, pins Alloy to the user pool, and fixes the log path so container restarts (0.log → 1.log → …) keep being captured.

Three coupled changes in `charts/monitoring-logging/values.yaml` (Alloy config + scheduling), plus a `Chart.yaml` version bump. No env values changes are required, but operators with non-`userpool` pool naming should override `alloy.controller.nodeSelector`.

### 1. Namespace-scoped log discovery

The Alloy `discovery.kubernetes "pods"` block now uses a server-side namespace filter:

```alloy
discovery.kubernetes "pods" {
  role = "pod"

  namespaces {
    names = ["podiumd", "monitoring"]
  }
}
```

This narrows the K8s API watch (LIST/WATCH is namespace-scoped) instead of fetching all pods cluster-wide and dropping them with a relabel rule. Lower API server load, less memory in Alloy, fewer log lines flowing to Loki.

If your deployment needs different namespaces, override the entire `alloy.alloy.configMap.content` block in your env values file (the configMap content is a single string, so partial override is not supported).

### 2. `nodeSelector` pinned to user pool

The Alloy DaemonSet is now scheduled only on user pool nodes:

```yaml
alloy:
  controller:
    nodeSelector:
      kubernetes.azure.com/agentpool: userpool
```

This **reverses the 1.0.11 → 1.0.12 guidance** to leave Alloy unconstrained. The reversal is intentional and only safe given change #1: with log capture narrowed to `podiumd` + `monitoring`, both of which run on the user pool, there is nothing to collect on system or other pools.

If you change the namespace list to include workloads that run on other pools, **also remove or widen this nodeSelector** — otherwise pods on excluded pools become invisible.

Operators with a different pool name override the value in their env values file:

```yaml
alloy:
  controller:
    nodeSelector:
      kubernetes.azure.com/agentpool: <your-pool-name>
```

### 3. Log path glob + `local.file_match`

Container log files rotate on restart (`0.log`, `1.log`, `2.log`, …). The 1.0.11 fix used a literal `/0.log` path because `loki.source.file` does `os.Stat` directly and cannot resolve globs. That meant logs were lost on every container restart.

1.0.13 introduces `local.file_match` to expand the glob into real file paths:

```alloy
rule {
  ...
  replacement = "/var/log/pods/${1}_${2}_${3}/${4}/*.log"
  target_label = "__path__"
}

local.file_match "pod_logs" {
  path_targets = discovery.relabel.pod_logs.output
  sync_period  = "10s"
}

loki.source.file "pod_logs" {
  targets    = local.file_match.pod_logs.targets
  forward_to = [loki.process.cri.receiver]
}
```

`sync_period = "10s"` is how often Alloy re-scans the filesystem for newly rotated files. After a container restart, the new `1.log` is picked up within 10 seconds.

## Why this overrides the 1.0.11 → 1.0.12 guidance

| Concern (from 1.0.11→1.0.12) | Why it doesn't apply here |
|---|---|
| "Alloy is a DaemonSet and must run on every node to collect logs cluster-wide." | Cluster-wide capture is no longer the goal — scope is explicitly `podiumd` + `monitoring` only. |
| "A nodeSelector restricts it to a single pool, leaving pods on other pools without log shipping." | Workloads in scope run only on the user pool. Pods that *do* land on other pools (system add-ons, etc.) are intentionally out of scope. |
| "Cost pool isolation: even if user workloads run only on userpool, system workloads on systempool still produce logs worth capturing." | Decision: those system-pool logs are not in scope for this deployment. |

The 1.0.11 → 1.0.12 doc remains correct **for cluster-wide log capture deployments**. 1.0.13 is for the narrower podiumd-only scope.

## Operator action

For most deployments: nothing to do beyond `helm upgrade`. The chart defaults handle namespace scope, scheduling, and log path.

If your env values file has a manually-added `alloy.nodeSelector` block (per the now-superseded 1.0.11 guidance), remove it — the chart now sets `alloy.controller.nodeSelector` correctly. Note the path difference: `alloy.nodeSelector` was silently ignored by the Grafana Alloy subchart (which expects `alloy.controller.nodeSelector`), so the previous block was likely a no-op anyway.

If your user pool is not named `userpool` or uses a different label key, override:

```yaml
# values-monitoring-<env>.yaml
alloy:
  controller:
    nodeSelector:
      kubernetes.azure.com/agentpool: <your-pool-name>
```

## Verification after upgrade

```bash
# 1. Alloy pods are only on user-pool nodes
kubectl -n <namespace> get pods -l app.kubernetes.io/name=alloy -o wide

# 2. Alloy is healthy (no config validation errors)
kubectl -n <namespace> logs -l app.kubernetes.io/name=alloy --tail=50

# 3. Logs from podiumd + monitoring are flowing into Loki
#    (query in Grafana: {namespace="podiumd"} or {namespace="monitoring"})

# 4. Container restart capture works:
#    delete a podiumd pod and confirm new 1.log entries appear in Loki
#    within ~10s of the new container starting.
```

## No other changes

This release is targeted at Alloy. No other component versions, image tags, or schema changes.
