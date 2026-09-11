# Deploying to a custom namespace

By default the podiumd umbrella chart is deployed into the `podiumd` namespace, and a number of
cluster-internal references historically hard-coded that name. The chart now resolves almost all
of these relative to the release namespace, so it can be installed into **any** namespace. This
document explains what adapts automatically and the one thing you still have to override.

## What adapts automatically (namespace-agnostic)

These no longer contain a hard-coded `podiumd` and follow the release namespace on their own:

| Reference | Old value (hard-coded) | New value | How it resolves |
|-----------|------------------------|-----------|-----------------|
| Redis connection strings (all apps) | `redis-ha-master.podiumd.svc.cluster.local:6379/N` | `redis-ha-master:6379/N` | Bare service name resolves via the pod's DNS search path to the app's own namespace. |
| Django `allowedHosts` (all apps) | `<svc>.podiumd.svc.cluster.local` | `.svc.cluster.local` | Leading-dot wildcard — accepted by both nginx `server_name` and Django `ALLOWED_HOSTS`; matches the service FQDN in any namespace. |
| `clamavHost` (openformulieren, openinwoner) | `clamav.podiumd.svc.cluster.local` | `clamav` | Bare service name, resolved in-namespace. |
| KISS Kibana host / `publicBaseUrl` | `kiss-kb-http.podiumd.svc.cluster.local:5601` | `kiss-kb-http:5601` | Bare service name; the ECK-generated cert SAN includes the short name. |

The redis-ha `RedisReplication` CR, its label-master CronJob, pre-delete Job, PodMonitor, and all
other custom templates already use `{{ .Release.Namespace }}`, so the Redis pods themselves deploy
into the release namespace too.

## What you must override (operator watch-scopes)

Three operators need to be told which namespace to watch. An operator watches either a **specific
namespace** or **all namespaces**, and Helm cannot template `values.yaml` with
`.Release.Namespace`. The chart uses namespace-scoped RBAC
(`eck-operator.createClusterScopedResources: false`), so "all namespaces" is not a safe default —
therefore these default to `podiumd` and must be overridden when you deploy elsewhere:

| Value | Default |
|-------|---------|
| `eck-operator.managedNamespaces` | `[podiumd]` |
| `zac.solr-operator.watchNamespaces` | `"podiumd"` |
| `zac.solr-operator.zookeeper-operator.watchNamespace` | `"podiumd"` |

If you deploy into `podiumd`, no action is needed.

### Option A — override values file

Copy [`ci/values-namespace-scope.example.yaml`](../../ci/values-namespace-scope.example.yaml),
replace `<namespace>`, and pass it alongside your environment values:

```bash
helm upgrade --install podiumd charts/podiumd \
  -f <your-env-values>.yaml \
  -f charts/podiumd/ci/values-namespace-scope.example.yaml \
  -n <namespace>
```

### Option B — `--set` on the command line (pipeline-friendly)

```bash
NS=<namespace>
helm upgrade --install podiumd charts/podiumd -f <your-env-values>.yaml -n "$NS" \
  --set "eck-operator.managedNamespaces={$NS}" \
  --set "zac.solr-operator.watchNamespaces=$NS" \
  --set "zac.solr-operator.zookeeper-operator.watchNamespace=$NS"
```

Always make sure the `-n` / `--namespace` you install into matches the namespace you set for the
operator watch-scopes.
