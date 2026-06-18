#!/usr/bin/env bash
#
# loki-dump.sh - orchestrate an in-cluster export of all Loki logs to a single
# gzip file on a sized PVC, then snapshot that PVC (Azure disk) for export.
#
# Phases:
#   1. measure   - Job hits index/volume API -> estimated ingested bytes
#   2. size+PVC  - compute /dump PVC size from the estimate, create PVC
#   3. dump      - Job paginates query_range -> /dump/loki-all.jsonl.gz
#   4. snapshot  - VolumeSnapshot of the PVC (deletionPolicy=Retain)
#
# Run from your laptop (BSD/macOS `date`). Requires kubectl + cluster access.
#
set -euo pipefail

# ---- config -----------------------------------------------------------------
CONTEXT="aks-blue-ontw-dim1"
NS="monitoring"
QUERY='{namespace=~".+"}'                 # adjust if some streams lack `namespace`
LIMIT="5000"
GATEWAY="http://monitoring-logging-loki-gateway.monitoring.svc.cluster.local"
LOOKBACK_DAYS="30"                        # cluster retention_period is 30d

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K="kubectl --context ${CONTEXT} -n ${NS}"

# ---- time window (ns since epoch) -------------------------------------------
# +1h keeps the start just inside max_query_lookback (30d) to avoid rejection.
START_NS="$(date -u -v-"${LOOKBACK_DAYS}"d -v+1H +%s)000000000"
END_NS="$(date -u +%s)000000000"
echo ">> window ${START_NS} .. ${END_NS} (last ${LOOKBACK_DAYS}d)"

# ---- scripts + env into the cluster -----------------------------------------
${K} create configmap loki-export-scripts \
  --from-file="${DIR}/scripts/measure.sh" \
  --from-file="${DIR}/scripts/dump.sh" \
  --dry-run=client -o yaml | ${K} apply -f -

${K} create configmap loki-export-env \
  --from-literal=GATEWAY="${GATEWAY}" \
  --from-literal=QUERY="${QUERY}" \
  --from-literal=START_NS="${START_NS}" \
  --from-literal=END_NS="${END_NS}" \
  --from-literal=LIMIT="${LIMIT}" \
  --dry-run=client -o yaml | ${K} apply -f -

# ---- phase 1: measure -------------------------------------------------------
echo ">> phase 1: measure"
${K} delete job loki-export-measure --ignore-not-found
${K} apply -f "${DIR}/manifests/measure-job.yaml"
${K} wait --for=condition=complete job/loki-export-measure --timeout=600s
bytes="$(${K} logs job/loki-export-measure | sed -n 's/^ESTIMATED_BYTES=//p' | tail -1)"
[[ -n "${bytes}" ]] || { echo "ERROR: no ESTIMATED_BYTES in measure log" >&2; exit 1; }
echo ">> estimated ingested bytes: ${bytes}"

# ---- phase 2: size + PVC ----------------------------------------------------
# Dump is gzipped JSONL. Conservatively assume only ~3x compression after
# JSONL overhead, add 20% headroom, floor at 8Gi. Oversizing is cheap (disk
# deleted after snapshot); undersizing fails the job with ENOSPC.
need=$(( bytes / 3 ))
need=$(( need + need / 5 ))
size=$(( need / 1073741824 + 1 ))
[[ "${size}" -lt 8 ]] && size=8
echo ">> PVC size: ${size}Gi"
sed "s/__SIZE__/${size}/" "${DIR}/manifests/pvc.yaml" | ${K} apply -f -

# ---- phase 3: dump ----------------------------------------------------------
echo ">> phase 3: dump"
${K} delete job loki-export-dump --ignore-not-found
${K} apply -f "${DIR}/manifests/dump-job.yaml"
echo ">> follow: kubectl --context ${CONTEXT} -n ${NS} logs -f job/loki-export-dump"
${K} wait --for=condition=complete job/loki-export-dump --timeout=21600s
${K} logs job/loki-export-dump | tail -5

# ---- phase 4: snapshot ------------------------------------------------------
echo ">> phase 4: snapshot"
${K} apply -f "${DIR}/manifests/volumesnapshotclass.yaml"
${K} apply -f "${DIR}/manifests/volumesnapshot.yaml"
${K} wait --for=jsonpath='{.status.readyToUse}'=true \
  volumesnapshot/loki-export-dump-snapshot --timeout=1800s
${K} get volumesnapshot loki-export-dump-snapshot

echo ">> DONE. Snapshot retained (deletionPolicy=Retain)."
echo ">> PVC loki-export-dump can be deleted; snapshot persists in Azure."
