# Upgrade guide: monitoring-logging 1.0.13 → 1.0.14

## Summary of changes

1.0.13 introduced a **server-side namespace filter** on Alloy's pod discovery, hardcoded to `["podiumd", "monitoring"]`. Deployments whose workloads run in a *different* namespace (e.g. `default`) stopped collecting logs, because their pods were no longer in scope.

1.0.14 makes that namespace list configurable through a new value: `alloy.logCollectionNamespaces`. No behaviour change for deployments that use the `podiumd` namespace — the default is unchanged.

## The new value

```yaml
# charts/monitoring-logging/values.yaml (defaults)
alloy:
  logCollectionNamespaces:
    - podiumd
    - monitoring
```

This list is rendered directly into the Alloy `discovery.kubernetes "pods"` namespace filter:

```alloy
discovery.kubernetes "pods" {
  role = "pod"

  namespaces {
    names = ["podiumd", "monitoring"]   // <- from logCollectionNamespaces
  }
}
```

Previously (1.0.13) the only way to change these namespaces was to override the entire `alloy.alloy.configMap.content` string. That is no longer necessary.

## Operator action

**If your applications run in the `podiumd` namespace:** nothing to do. The default is unchanged.

**If your applications run in another namespace** (for example `default`), set the value in your env values file so logs are collected again:

```yaml
# values-monitoring-<env>.yaml
alloy:
  logCollectionNamespaces:
    - default
    - monitoring
```

Keep `monitoring` in the list so the monitoring stack's own pod logs continue to be captured, and add any other namespaces you deploy workloads to.

> ⚠️ Note the coupling with `alloy.controller.nodeSelector` (pinned to `userpool` since 1.0.13). If you add a namespace whose workloads run on a different node pool, also widen or remove that nodeSelector — otherwise pods on excluded pools are not tailed. See `upgrade-from-1.0.12-to-1.0.13.md`.

## Verification after upgrade

```bash
# 1. Confirm the rendered namespace filter matches your namespaces
helm template ml charts/monitoring-logging \
  --set 'alloy.logCollectionNamespaces={default,monitoring}' \
  --show-only charts/alloy/templates/configmap.yaml | grep -A2 'namespaces {'

# 2. Alloy is healthy after upgrade
kubectl -n <namespace> logs -l app.kubernetes.io/name=alloy --tail=50

# 3. Logs from your namespace are flowing into Loki
#    (query in Grafana: {namespace="default"})
```

## No other changes

This release only parameterizes the Alloy log-collection namespace list. No other component versions, image tags, or schema changes.
