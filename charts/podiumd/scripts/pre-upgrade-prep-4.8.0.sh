#!/usr/bin/env bash
# pre-upgrade-prep-4.8.0.sh  (formerly adopt-eck-crds.sh)
#
# Pre-upgrade preparation for podiumd 4.7.x -> 4.8.0. Runs the three manual
# steps from the upgrade guide in one go:
#
#   1. ECK CRD adoption (one-time)
#      As of 4.8.0 the chart installs and upgrades the ECK CRDs itself
#      (eck-operator.installCRDs: true). CRDs applied in the kisselastic era
#      carry no Helm ownership metadata and the first `helm upgrade` fails
#      with "invalid ownership metadata". This step annotates/labels them
#      into the podiumd release. Idempotent; no-op on fresh clusters. CRDs
#      missing on old clusters (packageregistries, autoopsagentpolicies) are
#      simply created by helm on the next deploy.
#
#   2. RabbitMQ drain check
#      The 4.8.0 open-notificaties chart removes the bundled RabbitMQ (the
#      Celery broker moves to redis-ha). Undelivered tasks still in the
#      RabbitMQ queues at upgrade time are lost silently. This step checks
#      the queue depths; if messages are pending the script exits non-zero:
#      quiesce producers, let the workers drain, and re-run.
#
#   3. Elasticsearch baseline
#      Records per ECK Elasticsearch cluster: StatefulSet UIDs, PVCs and
#      search-* doc counts. Compare after the upgrade — UIDs, PVCs and doc
#      counts must be unchanged (see docs/apps/elastic/migrating-to-eck-stack.md sec. 5).
#
# Steps 2 and 3 are read-only. --dry-run makes step 1 read-only as well, so
# the whole script can be previewed without changing anything.
#
# Usage:
#   ./pre-upgrade-prep-4.8.0.sh [OPTIONS]
#
# Options:
#   --release NAME        Helm release name (default: podiumd)
#   --namespace NS        Helm release namespace (default: podiumd)
#   --context CONTEXT     kubectl context to use (default: current context)
#   --baseline-file FILE  Also write the step-3 baseline to FILE
#   --dry-run             Preview CRD adoption, change nothing
#   -h, --help            Show this help message
#
# Exit codes:
#   0  ready for the 4.8.0 upgrade
#   1  not ready (RabbitMQ queues not empty / not queryable) or usage error
#
# Prerequisites:
#   - kubectl with cluster-admin on the target cluster (CRDs are cluster-scoped)
#
# Example:
#   ./pre-upgrade-prep-4.8.0.sh --context my-aks-cluster --baseline-file baseline.txt
#   ./pre-upgrade-prep-4.8.0.sh --dry-run

set -euo pipefail

RELEASE_NAME="podiumd"
RELEASE_NS="podiumd"
CONTEXT=""
BASELINE_FILE=""
DRY_RUN=false

usage() {
  grep '^#' "$0" | grep -v '^#!/' | sed 's/^# //' | sed 's/^#//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release)
      RELEASE_NAME="$2"
      shift 2
      ;;
    --namespace)
      RELEASE_NS="$2"
      shift 2
      ;;
    --context)
      CONTEXT="$2"
      shift 2
      ;;
    --baseline-file)
      BASELINE_FILE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Run with --help for usage." >&2
      exit 1
      ;;
  esac
done

kc() {
  if [[ -n "${CONTEXT}" ]]; then
    kubectl --context "${CONTEXT}" "$@"
  else
    kubectl "$@"
  fi
}

# --- Step 1: ECK CRD adoption ------------------------------------------------

echo "==> Step 1/3: ECK CRD adoption (*.k8s.elastic.co)..."
CRDS="$(kc get crd -o name | grep 'k8s\.elastic\.co' || true)"

if [[ -z "${CRDS}" ]]; then
  echo "    No ECK CRDs present — fresh cluster, helm installs them on the first deploy. Nothing to do."
else
  COUNT=0
  while IFS= read -r crd; do
    COUNT=$((COUNT + 1))
    if [[ "${DRY_RUN}" == "true" ]]; then
      CURRENT="$(kc get "${crd}" -o jsonpath='{.metadata.annotations.meta\.helm\.sh/release-name}')"
      echo "    [dry-run] ${crd}: release-name '${CURRENT:-<none>}' -> '${RELEASE_NAME}'"
    else
      kc annotate "${crd}" \
        "meta.helm.sh/release-name=${RELEASE_NAME}" \
        "meta.helm.sh/release-namespace=${RELEASE_NS}" --overwrite >/dev/null
      kc label "${crd}" app.kubernetes.io/managed-by=Helm --overwrite >/dev/null
      echo "    adopted ${crd}"
    fi
  done <<< "${CRDS}"

  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "    [dry-run] ${COUNT} ECK CRDs found; nothing changed."
  else
    echo "    Adopted ${COUNT} ECK CRDs into Helm release ${RELEASE_NS}/${RELEASE_NAME}."
    echo "    The next helm deploy/upgrade manages them and creates any missing ones."
  fi
fi

# --- Step 2: RabbitMQ drain check ---------------------------------------------

echo "==> Step 2/3: RabbitMQ drain check (broker moves to redis-ha in 4.8.0)..."
RABBIT_READY=true
# Vendored subchart labels the pod name=opennotificaties-rabbitmq/instance=<release>;
# older bitnami-shaped deployments use name=rabbitmq/instance=opennotificaties.
RABBIT_POD="$(kc get pod -n "${RELEASE_NS}" \
  -l "app.kubernetes.io/name=opennotificaties-rabbitmq,app.kubernetes.io/instance=${RELEASE_NAME}" \
  -o name 2>/dev/null | head -n 1)"
if [[ -z "${RABBIT_POD}" ]]; then
  RABBIT_POD="$(kc get pod -n "${RELEASE_NS}" \
    -l 'app.kubernetes.io/name=rabbitmq,app.kubernetes.io/instance=opennotificaties' \
    -o name 2>/dev/null | head -n 1)"
fi

if [[ -z "${RABBIT_POD}" ]]; then
  echo "    No open-notificaties RabbitMQ pod found — already migrated or fresh install. Nothing to drain."
else
  QUEUE_TABLE="$(kc exec -n "${RELEASE_NS}" "${RABBIT_POD}" -c rabbitmq -- \
    rabbitmqctl list_queues name messages messages_ready messages_unacknowledged consumers 2>/dev/null || true)"
  if [[ -z "${QUEUE_TABLE}" ]]; then
    echo "    WARNING: could not query queues on ${RABBIT_POD} — check manually before upgrading." >&2
    RABBIT_READY=false
  else
    printf '%s\n' "${QUEUE_TABLE}" | sed 's/^/    /'
    PENDING="$(printf '%s\n' "${QUEUE_TABLE}" | awk '$2 ~ /^[0-9]+$/ {sum += $2} END {print sum + 0}')"
    if [[ "${PENDING}" -gt 0 ]]; then
      echo "    WARNING: ${PENDING} message(s) still queued. The 4.8.0 upgrade deletes RabbitMQ and" >&2
      echo "    undelivered tasks are lost. Quiesce producers, let the workers drain, re-run this script." >&2
      RABBIT_READY=false
    else
      echo "    Queues empty — safe to upgrade. (Producers stay live: re-check right before the deploy.)"
    fi
  fi
fi

# --- Step 3: Elasticsearch baseline -------------------------------------------

collect_baseline() {
  local es_names es cluster_pod es_pw tls_disabled scheme
  echo "podiumd 4.8.0 pre-upgrade Elasticsearch baseline"
  echo "generated: $(date -u '+%Y-%m-%dT%H:%M:%SZ')  namespace: ${RELEASE_NS}  context: ${CONTEXT:-<current>}"
  es_names="$(kc get elasticsearch -n "${RELEASE_NS}" -o name 2>/dev/null | sed 's|^.*/||' || true)"
  if [[ -z "${es_names}" ]]; then
    echo "No ECK Elasticsearch clusters found — nothing to baseline."
    return 0
  fi
  while IFS= read -r es; do
    echo ""
    echo "--- Elasticsearch cluster: ${es} ---"
    echo "StatefulSets (UID must be identical after the upgrade = not rebuilt):"
    kc get sts -n "${RELEASE_NS}" -l "elasticsearch.k8s.elastic.co/cluster-name=${es}" \
      -o custom-columns='NAME:.metadata.name,UID:.metadata.uid,READY:.status.readyReplicas' 2>/dev/null | sed 's/^/  /'
    echo "PVCs (must survive the upgrade):"
    kc get pvc -n "${RELEASE_NS}" -l "elasticsearch.k8s.elastic.co/cluster-name=${es}" \
      -o custom-columns='NAME:.metadata.name,UID:.metadata.uid,CAPACITY:.status.capacity.storage,STORAGECLASS:.spec.storageClassName,STATUS:.status.phase' 2>/dev/null | sed 's/^/  /'
    cluster_pod="$(kc get pod -n "${RELEASE_NS}" \
      -l "elasticsearch.k8s.elastic.co/cluster-name=${es}" \
      --field-selector=status.phase=Running -o name 2>/dev/null | head -n 1)"
    es_pw="$(kc get secret -n "${RELEASE_NS}" "${es}-es-elastic-user" \
      -o go-template='{{index .data "elastic" | base64decode}}' 2>/dev/null || true)"
    if [[ -z "${cluster_pod}" || -z "${es_pw}" ]]; then
      echo "  (no running pod or elastic-user secret — skipping doc counts)"
      continue
    fi
    # ECK serves plain HTTP when spec.http.tls.selfSignedCertificate.disabled is true.
    tls_disabled="$(kc get elasticsearch "${es}" -n "${RELEASE_NS}" \
      -o jsonpath='{.spec.http.tls.selfSignedCertificate.disabled}' 2>/dev/null || true)"
    scheme="https"
    if [[ "${tls_disabled}" == "true" ]]; then
      scheme="http"
    fi
    echo "Health and search-* doc counts (must be unchanged after the upgrade):"
    # Credentials go through curl's stdin config (-K -), never the command line.
    printf 'user = "elastic:%s"\n' "${es_pw}" | kc exec -i -n "${RELEASE_NS}" "${cluster_pod}" -c elasticsearch -- \
      curl -s -k -K - "${scheme}://localhost:9200/_cat/health?h=status" 2>/dev/null | sed 's/^/  health: /' || true
    printf 'user = "elastic:%s"\n' "${es_pw}" | kc exec -i -n "${RELEASE_NS}" "${cluster_pod}" -c elasticsearch -- \
      curl -s -k -K - "${scheme}://localhost:9200/_cat/indices/search-*?v&h=index,health,docs.count&s=index" 2>/dev/null | sed 's/^/  /' || true
  done <<< "${es_names}"
}

echo "==> Step 3/3: Elasticsearch baseline..."
BASELINE="$(collect_baseline)"
printf '%s\n' "${BASELINE}" | sed 's/^/    /'
if [[ -n "${BASELINE_FILE}" ]]; then
  printf '%s\n' "${BASELINE}" > "${BASELINE_FILE}"
  echo "    Baseline written to ${BASELINE_FILE}"
fi

# --- Summary -------------------------------------------------------------------

if [[ "${RABBIT_READY}" == "true" ]]; then
  echo "==> Pre-upgrade prep complete — ready for the 4.8.0 deploy."
else
  echo "==> NOT ready: RabbitMQ queues are not confirmed empty (see step 2)." >&2
  exit 1
fi
