# Loki one-off tooling — usage & lifecycle

> ⚠️ **TEMPORARY / ONE-OFF TOOLING — NOT a permanent part of the chart.**
> These scripts exist to run a specific task once (or a handful of times) and
> are **expected to be removed** once that task is complete. They are not wired
> into the Helm release, CI, or any pipeline, and must not be relied on as
> standing infrastructure. See [Decommissioning](#decommissioning) below.

Two operator tools under `charts/podiumd/scripts/`:

| Tool | Folder | Purpose |
|------|--------|---------|
| Log export | [`loki-dump/`](./loki-dump/) | Export all Loki logs (last 30d) to one gzip file on a PVC, then snapshot it. |
| PII scan | [`loki-pii-scan/`](./loki-pii-scan/) | One-off Dutch-PII (AVG) sweep of Loki; writes a **masked** findings report to a PVC, then snapshots it. |

Each folder has its own detailed `README.md`. This file is the umbrella usage +
lifecycle note.

## Why these are one-off

- Built for point-in-time needs: a full log export, and a compliance/PII audit.
- They provision throwaway resources (Jobs, a PVC, a VolumeSnapshot) in the
  `monitoring` namespace and are meant to be torn down after use.
- They are **not** GitOps-managed, **not** part of `helm upgrade`, and carry no
  ongoing reconciliation. Leaving them running or deployed provides no value and
  only adds attack surface and cost (disk, snapshots).
- The PII scan in particular produces sensitive output (a masked map of where
  PII leaks). That output, and the tooling that generates it, should not linger.

## Prerequisites

- Cluster access to `aks-blue-ontw-dim1` (AAD; `az login` to tenant
  `fd01cf75-7056-4925-9d69-9d83fa9278a5`, then `kubelogin` refreshes).
- The `monitoring-logging` Loki stack deployed (gateway svc
  `monitoring-logging-loki-gateway`).
- Base image `acrprodmgmt.azurecr.io/k8s:1.34.7` pullable by the cluster
  (internal ACR; no public egress). Verify the tag if pulls fail:
  `az acr repository show-tags -n acrprodmgmt --repository k8s -o table`.
- `kubectl` configured locally; the orchestrators use BSD/macOS `date`.

## Running

```bash
# full log export
cd charts/podiumd/scripts/loki-dump      && ./loki-dump.sh

# one-off PII scan
cd charts/podiumd/scripts/loki-pii-scan  && ./loki-pii-scan.sh
```

Each orchestrator: pushes the scripts as ConfigMaps, creates a PVC, runs the
Job to completion, then takes a `VolumeSnapshot` (`deletionPolicy: Retain`) so
the result survives cleanup. Follow live with
`kubectl -n monitoring logs -f job/<job-name>`.

## Expected lifetime

- **In-cluster resources**: delete immediately after the run completes and the
  result (snapshot / pulled file) is secured. Do not leave Jobs/PVCs around.
- **These scripts in the repo**: remove once the task they served is done and no
  re-run is foreseen. Track removal as a follow-up (work item / PR) rather than
  letting them accrue as dead code.
- **Snapshots**: retained on purpose — delete deliberately once the exported
  data / audit evidence is no longer needed (mind data-retention obligations).

## Decommissioning

In-cluster cleanup (per tool — see each README for the exact commands):

```bash
# log export
kubectl --context aks-blue-ontw-dim1 -n monitoring delete \
  job/loki-export-measure job/loki-export-dump pvc/loki-export-dump \
  configmap/loki-export-scripts configmap/loki-export-env

# PII scan
kubectl --context aks-blue-ontw-dim1 -n monitoring delete \
  job/loki-pii-scan pvc/loki-pii-report \
  configmap/loki-pii-scripts configmap/loki-pii-env
```

Snapshots are kept (`Retain`) — remove explicitly when done:

```bash
kubectl --context aks-blue-ontw-dim1 -n monitoring delete \
  volumesnapshot/loki-export-dump-snapshot volumesnapshot/loki-pii-report-snapshot
# the VolumeSnapshotClasses are harmless to leave, or:
kubectl --context aks-blue-ontw-dim1 delete \
  volumesnapshotclass/loki-export-azuredisk volumesnapshotclass/loki-pii-azuredisk
```

Repo cleanup when retired:

```bash
git rm -r charts/podiumd/scripts/loki-dump charts/podiumd/scripts/loki-pii-scan \
         charts/podiumd/scripts/loki-tooling-USAGE.md
```

## Removal checklist

- [ ] Task complete; result (snapshot or pulled report) secured & verified.
- [ ] In-cluster Jobs / PVCs / ConfigMaps deleted.
- [ ] Snapshots deleted once data no longer needed (data-retention reviewed).
- [ ] Scripts removed from the repo (`git rm`), change merged.
