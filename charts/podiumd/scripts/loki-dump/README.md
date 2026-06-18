# loki-dump

In-cluster export of all Loki logs (`aks-blue-ontw-dim1`, ns `monitoring`) to a
single gzip file on a self-sized PVC, then snapshotted to an Azure disk for
export/save.

## What it does

1. **measure** Job — queries Loki `index/volume` for estimated ingested bytes.
2. **size + PVC** — computes `/dump` PVC size from the estimate (`managed-csi`).
3. **dump** Job — paginates `query_range` forward, streams gzipped JSONL to
   `/dump/loki-all.jsonl.gz` (+ `manifest.txt`).
4. **snapshot** — `VolumeSnapshot` of the PVC (`deletionPolicy: Retain`).

## Run

```bash
./loki-dump.sh
```

Follow the dump live:

```bash
kubectl --context aks-blue-ontw-dim1 -n monitoring logs -f job/loki-export-dump
```

## Cluster facts (verified)

- Loki 3.6.7, distributed, `auth_enabled: false` → no `X-Scope-OrgID` needed.
- `retention_period: 30d`, `max_query_lookback: 30d` → window = last 30d only.
- Read entrypoint: svc `monitoring-logging-loki-gateway:80`.
- No NetworkPolicy in `monitoring` → job reaches the gateway.
- StorageClass `managed-csi` (disk.csi.azure.com, expandable).
- No VolumeSnapshotClass existed → this creates `loki-export-azuredisk`.

## Output record format

```json
{"ts":"1718000000000000000","line":"<log line>","labels":{"namespace":"x","app":"y"}}
```

Read it back: `gzip -dc loki-all.jsonl.gz | jq .`

## Export the snapshot off Azure (optional)

The snapshot is a managed Azure disk snapshot. To pull it down as a VHD:

```bash
# find the snapshot's Azure resource id
kubectl --context aks-blue-ontw-dim1 -n monitoring get volumesnapshotcontent \
  -o jsonpath='{.items[?(@.spec.volumeSnapshotRef.name=="loki-export-dump-snapshot")].status.snapshotHandle}'

# grant temporary SAS + download
az snapshot grant-access --ids <snapshot-resource-id> \
  --resource-group <node-rg> --duration-in-seconds 3600 --query accessSas -o tsv
azcopy copy "<sas-url>" ./loki-snapshot.vhd
az snapshot revoke-access --ids <snapshot-resource-id> --resource-group <node-rg>
```

Or restore the snapshot to a new PVC and `kubectl cp` the file out.

## Caveats

- **Selector** `{namespace=~".+"}` covers all pod streams. If some streams lack
  a `namespace` label, widen it (e.g. add an OR on another always-present label).
- **Base image**: `acrprodmgmt.azurecr.io/k8s:1.34.7` (mirror of `docker.io/alpine/k8s`,
  per `charts/podiumd/docs/images/images-4.7.0.yaml`). Ships bash+curl+jq+gzip,
  so no `apk` / no public egress — the ontw/dim1 cluster already pulls from this
  ACR. If that exact tag isn't mirrored yet (`ImagePullBackOff`), fall back to a
  tag from an earlier manifest (`1.33.10`, `1.33.2`) or verify with:
  `az acr repository show-tags -n acrprodmgmt --repository k8s -o table`.
- **ns cursor**: pagination advances `maxts+1`; entries sharing an identical
  nanosecond at a batch boundary could be dropped (negligible at ns precision).
- **Size estimate** can undercount on high stream cardinality; the `/3 +20%`
  headroom covers normal cases. On `ENOSPC`, expand the PVC (managed-csi allows
  it) and re-run the dump Job.

## Cleanup

```bash
kubectl --context aks-blue-ontw-dim1 -n monitoring delete \
  job/loki-export-measure job/loki-export-dump \
  pvc/loki-export-dump \
  configmap/loki-export-scripts configmap/loki-export-env
# snapshot is retained on purpose; delete it only when you no longer need the dump:
# kubectl ... delete volumesnapshot loki-export-dump-snapshot
```
