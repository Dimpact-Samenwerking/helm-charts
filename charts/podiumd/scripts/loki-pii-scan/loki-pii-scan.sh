#!/usr/bin/env bash
#
# loki-pii-scan.sh - one-off Dutch-PII sweep of Loki, in-cluster.
#
# Phases:
#   1. scan      - Job runs per-category LogQL filters, validates + masks,
#                  writes a MASKED report to a PVC (/report)
#   2. snapshot  - VolumeSnapshot of the report PVC (deletionPolicy=Retain)
#
# Output contains masked PII locations only. Treat the snapshot as confidential.
#
set -euo pipefail

# ---- config -----------------------------------------------------------------
CONTEXT="aks-blue-ontw-dim1"
NS="monitoring"
QUERY='{namespace=~".+"}'
LIMIT="5000"
GATEWAY="http://monitoring-logging-loki-gateway.monitoring.svc.cluster.local"
LOOKBACK_DAYS="30"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K="kubectl --context ${CONTEXT} -n ${NS}"

# ---- 30d window (ns since epoch); +1h keeps start inside max_query_lookback --
START_NS="$(date -u -v-"${LOOKBACK_DAYS}"d -v+1H +%s)000000000"
END_NS="$(date -u +%s)000000000"
echo ">> window ${START_NS} .. ${END_NS} (last ${LOOKBACK_DAYS}d)"

# ---- scripts + env into the cluster -----------------------------------------
${K} create configmap loki-pii-scripts \
  --from-file="${DIR}/scripts/scan.sh" \
  --from-file="${DIR}/scripts/classify.awk" \
  --dry-run=client -o yaml | ${K} apply -f -

${K} create configmap loki-pii-env \
  --from-literal=GATEWAY="${GATEWAY}" \
  --from-literal=QUERY="${QUERY}" \
  --from-literal=START_NS="${START_NS}" \
  --from-literal=END_NS="${END_NS}" \
  --from-literal=LIMIT="${LIMIT}" \
  --dry-run=client -o yaml | ${K} apply -f -

# ---- phase 1: scan ----------------------------------------------------------
echo ">> phase 1: scan"
${K} apply -f "${DIR}/manifests/pvc.yaml"
${K} delete job loki-pii-scan --ignore-not-found
${K} apply -f "${DIR}/manifests/scan-job.yaml"
echo ">> follow: kubectl --context ${CONTEXT} -n ${NS} logs -f job/loki-pii-scan"
${K} wait --for=condition=complete job/loki-pii-scan --timeout=21600s

# Surface the counts-only summary (no masked values printed by the job tail).
${K} logs job/loki-pii-scan | sed -n '/===== SUMMARY/,$p'

# ---- phase 2: snapshot ------------------------------------------------------
echo ">> phase 2: snapshot"
${K} apply -f "${DIR}/manifests/volumesnapshotclass.yaml"
${K} apply -f "${DIR}/manifests/volumesnapshot.yaml"
${K} wait --for=jsonpath='{.status.readyToUse}'=true \
  volumesnapshot/loki-pii-report-snapshot --timeout=1800s
${K} get volumesnapshot loki-pii-report-snapshot

echo ">> DONE. Masked report on PVC loki-pii-report, snapshotted (Retain)."
echo ">> Pull the full masked report with:"
echo "   ${K} debug ... or mount the snapshot; or kubectl cp from a helper pod (see README)."
