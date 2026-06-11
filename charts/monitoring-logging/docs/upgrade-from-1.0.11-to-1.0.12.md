# Upgrade guide: monitoring-logging 1.0.11 → 1.0.12

## Summary of changes

### Remove `nodeSelector` from `alloy`

Alloy is a DaemonSet and must run on **every** node to collect pod logs cluster-wide. A `nodeSelector` restricts it to a single pool, leaving pods on other pools (system nodes, spot nodes, extra pools) without log shipping.

The 1.0.11 upgrade guide (and the `add-node-selectors.sh` script) wrote an `alloy.nodeSelector` block into environment values files. That was a mistake — 1.0.12 removes the entry from the script and requires operators to strip it from env values files.

### Environment values change

Remove the `alloy.nodeSelector` block from every `values-monitoring-<env>.yaml`:

```yaml
# Remove:
alloy:
  nodeSelector:
    agentpool: userpool
```

Leave the rest of the `alloy:` block (image, configMap, resources, etc.) untouched.

### Script update

`scripts/add-node-selectors.sh` no longer adds `nodeSelector` to `alloy`. Re-running the script on an already-migrated file is still safe (it skips components with an existing `nodeSelector`) — use the manual removal above to strip the block.

### Why

| Concern | Impact |
|---|---|
| DaemonSet scheduling | `nodeSelector` on a DaemonSet restricts pod placement; pods on excluded nodes have no log agent. |
| Log coverage | Missed nodes → missing logs in Loki → incomplete Grafana dashboards and invisible incidents on those nodes. |
| Cost pool isolation | Even if user workloads run only on `userpool`, system workloads on `systempool` still produce logs worth capturing. |

---

## No other changes

This release is a targeted fix for the `alloy` node selection regression introduced in 1.0.11. No other breaking changes, image updates, or schema migrations.
