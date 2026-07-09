# Migration: legacy kiss-elastic to eck-operator + eck-stack

This runbook describes the move from the legacy `kiss-elastic` subchart to
Elastic's official Helm charts (`eck-operator` + `eck-stack`), as introduced in
PR #331. Guiding principle: **migrate without data loss**.

Tested on a development environment with data, see [Validation](#5-validation).

## 1. What changes at chart level

| | Before | After |
|---|---|---|
| KISS Elasticsearch | `kiss-elastic` subchart (1.1.0), which bundled the eck-operator itself | `eck-stack` dependency (0.19.0, alias `kiss-eck`) |
| ECK operator | From the `kiss-elastic` subchart, or installed standalone per environment | **Central** in the umbrella: root-level `eck-operator` (3.4.0) with `managedNamespaces: [podiumd]` |
| OIP Elasticsearch | `eck-elasticsearch` from the `openinwoner` subchart | Unchanged; still comes from the `openinwoner` subchart |
| OIP operator | `openinwoner.eck-operator.enabled: false` | Unchanged; OIP uses the central operator |

Core principle: the ECK operator is implemented centrally in PodiumD, no longer
from a subchart of KISS or OIP. KISS and OIP only provide their own
Elasticsearch resource; the central operator reconciles both in the `podiumd`
namespace.

## 2. Resource naming: no change, so data is preserved

The ECK operator derives the StatefulSet and PVC names from the name of the
`Elasticsearch` resource and the nodeSet name. As long as those stay the same,
the existing StatefulSet is kept and the PVCs (the data) remain.

| Resource | Name before | Name after |
|---|---|---|
| `Elasticsearch` (KISS) | `kiss` | `kiss` (via `fullnameOverride: kiss`) |
| `Kibana` / `EnterpriseSearch` (KISS) | `kiss` | `kiss` |
| nodeSet | `default` | `default` |
| StatefulSet | `kiss-es-default` | `kiss-es-default` |
| PVCs | `elasticsearch-data-kiss-es-default-{0,1,2}` | same |
| `Elasticsearch` (OIP) | `openinwoner-elasticsearch` | `openinwoner-elasticsearch` |

**Important:** do not change the nodeSet name (keep `default`). A different
nodeSet name makes the operator create a new StatefulSet and rebalance data,
which is disruptive.

The `Elasticsearch` spec is functionally identical before and after (same
`version`, `nodeSets[].name`, `count` and `config`). The only real change on the
CR is the Helm label `helm.sh/chart` (`kisselastic-1.1.0` becomes
`eck-elasticsearch-0.19.x`). Because of this the ECK operator does not rebuild
the StatefulSet and does not restart the pods.

### volumeClaimTemplates: clean swap only when storage size is unchanged

The rule "data is preserved" holds as long as the **`volumeClaimTemplates`
(storage size + storageClass) stays unchanged**. In the default chart this is
the case: both the legacy `kiss-elastic` and the new `kiss-eck` leave
`volumeClaimTemplates` unset, so both fall back to the same ECK default. As a
result the existing StatefulSet is kept (tested on a development environment:
StatefulSet UID and PVCs unchanged), no manual steps.

**Watch out when an environment overrides the volume size.** A StatefulSet's
`volumeClaimTemplates` is **immutable** in Kubernetes. If the new
volumeClaimTemplate differs from the existing PVCs (e.g. 1Gi -> 8Gi), ECK cannot
apply it in place: the operator gets stuck in a reconcile error (ES neither old
nor new) until the StatefulSet is deleted manually. Then manual steps are
required:

- **Clean recreate (data loss acceptable):** `kubectl delete sts kiss-es-default`
  and the associated PVCs, and let ECK recreate everything from scratch.
- **Resize while keeping data:** cannot be done in place. Use an Elasticsearch
  snapshot/restore, or reindex into a nodeSet with the new size.

Rule of thumb: during the migration keep the `volumeClaimTemplates` equal to the
existing PVCs -> clean swap. If you want to resize at the same time, plan that as
a separate step with snapshot/restore.

## 3. Impact on municipal helm values

### KISS
- Remove the `kisselastic:` block. Replace it with `kiss-eck:` (eck-stack) and a
  root-level `eck-operator:` block. See `values.yaml` for the defaults.
- nodeSets, resources and crawler settings are now set per environment under
  `kiss-eck.eck-enterprise-search.config` and
  `kiss-eck.eck-elasticsearch.nodeSets` (this resolves DS-5060: crawler config
  per environment).
- The `contact` tag still drives KISS (`kiss-eck` has `tags: [kiss-eck, contact]`).

### OIP (openinwoner)
- No new dependency needed. OIP already provides `eck-elasticsearch` via the
  `openinwoner` subchart.
- Make sure `openinwoner.eck-operator.enabled: false` stays set, so OIP uses the
  central operator and does not spin up its own `openinwoner-elastic-operator`.
- nodeSets for OIP live under `openinwoner.eck-elasticsearch.nodeSets`
  (per environment).

### Central operator
- `eck-operator.enabled: true` and `eck-operator.managedNamespaces: [podiumd]`
  (or the namespace where PodiumD runs). The operator must cover the namespace of
  both `kiss` and `openinwoner-elasticsearch`.

## 4. Migration steps for SSC (environment already running)

The KISS Elasticsearch migration itself is a metadata-only change (see section
2). The two real points of attention are **how you handle the operator** when
an environment already runs a standalone `elastic-operator` Helm release
(installed outside the umbrella), and the **ECK CRDs** (section 4b).

### 4a. Decide how the operator is managed

- **Fresh install / no operator yet:** set `eck-operator.enabled: true`. The
  umbrella installs the central operator. Nothing else needed.
- **A standalone `elastic-operator` already runs (outside the umbrella):**
  **recommended** is to leave it in place and set `eck-operator.enabled: false`.
  The umbrella then only swaps the KISS Elasticsearch chart (`kisselastic` ->
  `kiss-eck`); the existing operator keeps reconciling. No ownership transfer
  needed. Centralizing the operator can be a separate, later step.

The operator is stateless (the data lives in the Elasticsearch StatefulSet/PVCs),
so the choice above does not affect the data.

<details>
<summary>Optional (advanced): have the umbrella adopt the standalone operator</summary>

If you want the umbrella operator to take over the existing operator resources
(`eck-operator.enabled: true` while a standalone release is running), first strip
the Helm ownership so no conflict occurs:

```bash
NS=podiumd
# Namespace-scoped operator resources
for r in serviceaccount/elastic-operator service/elastic-operator-webhook statefulset/elastic-operator; do
  kubectl annotate -n "$NS" "$r" meta.helm.sh/release-name- meta.helm.sh/release-namespace- --overwrite || true
  kubectl label   -n "$NS" "$r" app.kubernetes.io/managed-by- --overwrite || true
done
# Cluster-scoped operator resources
for r in clusterrole/elastic-operator clusterrole/elastic-operator-edit clusterrole/elastic-operator-view clusterrolebinding/elastic-operator; do
  kubectl annotate "$r" meta.helm.sh/release-name- meta.helm.sh/release-namespace- --overwrite || true
  kubectl label   "$r" app.kubernetes.io/managed-by- --overwrite || true
done
```

> Mind the operator version jump. When the umbrella operator (3.4.0) takes over,
> the `elastic-operator` StatefulSet may hit an immutable `spec.selector` conflict
> on `helm upgrade`. Resolve it by deleting the `elastic-operator` StatefulSet
> (it holds no data) and letting helm recreate it.

</details>

### 4b. CRDs: installed by the chart (one-time adoption on existing clusters)

The umbrella installs and upgrades the ECK CRDs itself
(`eck-operator.installCRDs: true`, the upstream default): all **12**
`*.k8s.elastic.co` CRDs are applied on every deploy, in lock-step with the
operator version — no manual step on version bumps. The CRDs carry
`helm.sh/resource-policy: keep`, so `helm uninstall` never removes them and
the Elastic CRs (and their data) survive a release removal.

Two requirements:

1. **Cluster-scope RBAC.** CRDs are cluster-scoped, so the deploying identity
   must be allowed to create/update them. The SSC deploy pipeline runs
   `HelmDeploy` with `useClusterAdmin: true`, which covers this.
2. **One-time adoption on clusters that already have the CRDs.** CRDs applied
   in the kisselastic era (by a manual `kubectl apply`, or owned by a
   standalone `elastic-operator` release) don't belong to the `podiumd`
   release, and Helm refuses to overwrite them (`rendered manifests contain a
   resource that already exists ... invalid ownership metadata`). Run the
   helper script once per cluster, **before** the first 4.8.0 deploy
   (idempotent, safe to re-run; no-op on fresh clusters; `--dry-run` to
   preview):

   ```bash
   charts/podiumd/scripts/adopt-eck-crds.sh --context <kubectl-context>
   ```

   After adoption the regular deploy needs no extra flags and the pipeline
   needs no changes — Helm owns the CRDs from then on. The two CRDs new in
   ECK 3.4.0 (`packageregistries`, `autoopsagentpolicies`) don't exist yet on
   old clusters, so there is no conflict: Helm simply creates them on the
   next deploy.

   Alternative: deploy once with `--take-ownership` (helm >= 3.17). Works,
   but the flag is not scoped to CRDs — it relaxes the ownership check for
   **every** resource in the release, silently adopting conflicts a strict
   deploy would flag. Prefer the one-time script and keep the pipeline
   unchanged.

Verify after the deploy (must print `12`):

```bash
kubectl get crd -o name | grep -c 'k8s.elastic.co'
```

**Symptom of missing/stale CRDs** (e.g. `installCRDs` overridden to `false`
without a manual apply): ECK operator 3.4.0 needs 12 CRDs; kisselastic-era
clusters have only 10 — `packageregistries.packageregistry.k8s.elastic.co`
and `autoopsagentpolicies.autoops.k8s.elastic.co` are missing. The operator's
informer cache then cannot sync (`failed to wait for packageregistry-controller
caches to sync`), the process exits cleanly every ~2 minutes (exit code 0) and
the `elastic-operator` StatefulSet ends up in `CrashLoopBackOff`. Treacherous:
`helm --wait` can sample the operator during an up-phase, so a deploy may
**intermittently go green** while the operator is broken — the failure then
surfaces on a later rollout. After fixing the CRDs, delete the operator pod
once to skip the remaining backoff:
`kubectl delete pod elastic-operator-0 -n podiumd`.

<details>
<summary>Installers without cluster-scope RBAC: manual CRD apply</summary>

Set `eck-operator.installCRDs: false` and apply the CRDs manually before the
upgrade (cluster-admin, repeat on every operator version bump). The CRDs are
too large for client-side apply, hence `--server-side`:

```bash
# Option A — render from the chart's own bundled eck-operator (version always matches)
tar -xzf charts/podiumd/charts/eck-operator-3.4.0.tgz -C /tmp
helm template eck /tmp/eck-operator --set installCRDs=true \
  --show-only charts/eck-operator-crds/templates/all-crds.yaml > /tmp/eck-crds.yaml
kubectl apply --server-side --force-conflicts -f /tmp/eck-crds.yaml

# Option B — upstream, same content (needs internet egress)
kubectl apply --server-side --force-conflicts \
  -f https://download.elastic.co/downloads/eck/3.4.0/crds.yaml
```

</details>

### 4c. The upgrade

1. Make a backup/snapshot of the Elasticsearch data (or at least record the
   index/doc counts, see section 5).
2. Run `helm upgrade` with the new chart and the adjusted environment values.
3. The `kiss` and `openinwoner-elasticsearch` StatefulSets are updated in place
   (not rebuilt).

## 5. Validation

Record before and after the upgrade:

```bash
NS=podiumd
# StatefulSet UID (must stay identical = not rebuilt)
kubectl get sts kiss-es-default -n $NS -o jsonpath='{.metadata.uid}{"\n"}'
# PVCs (must keep existing)
kubectl get pvc -n $NS -l 'elasticsearch.k8s.elastic.co/cluster-name=kiss'
# Doc counts as data baseline
PW=$(kubectl get secret kiss-es-elastic-user -n $NS -o go-template='{{.data.elastic|base64decode}}')
kubectl exec -n $NS kiss-es-default-0 -c elasticsearch -- \
  curl -s -k -u "elastic:$PW" "https://localhost:9200/_cat/indices/search-*?v&h=index,docs.count"
```

After the upgrade the StatefulSet UID, PVCs and doc counts must be unchanged and
the `Elasticsearch` health must be `green`.

Also verify the **operator stays up**. The CRD failure mode (section 4b) exits
every ~2 minutes, so a single `Running` sample proves nothing — check the
restart count after at least 5 minutes:

```bash
kubectl get pod elastic-operator-0 -n $NS \
  -o jsonpath='{.status.containerStatuses[0].restartCount}{"\n"}'
# must stay 0 (and AGE keeps growing)
```

### Validation test result
With a realistic data baseline (475 documents: `search-kennisbank` +
`search-vac`), the chart swap was tested: StatefulSet `kiss-es-default` kept its
UID (not rebuilt), the PVCs remained, ES stayed `green` and all 475 documents
were intact. The migration is a metadata-only change on the Elasticsearch CR,
without data loss or disruption.

## 6. Rollback

Because the migration is a chart swap and the underlying Elasticsearch data
(PVCs) is not touched, rolling back to the `kiss-elastic` chart is possible
without data loss: `helm rollback` or `helm upgrade` again with the old chart.
The StatefulSet and PVC names stay the same in both directions.
