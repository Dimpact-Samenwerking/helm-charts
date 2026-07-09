#!/usr/bin/env bash
# adopt-eck-crds.sh
#
# One-time Helm adoption of pre-existing ECK CRDs (*.k8s.elastic.co).
#
# Background:
#   As of podiumd 4.8.0 the chart installs and upgrades the ECK CRDs itself
#   (eck-operator.installCRDs: true). On clusters where the CRDs were applied
#   earlier (kisselastic era, or a manual kubectl apply) they carry no Helm
#   ownership metadata, and the first `helm upgrade` fails with
#   "invalid ownership metadata". Run this script ONCE per cluster before that
#   first deploy; afterwards the regular helm deploy/upgrade works unchanged —
#   no pipeline changes and no --take-ownership flag needed.
#
#   Idempotent: safe to re-run. On a fresh cluster (no ECK CRDs) it is a
#   no-op — helm installs the CRDs itself. CRDs that are missing on old
#   clusters (packageregistries, autoopsagentpolicies) are simply created by
#   helm on the next deploy; there is no conflict, so nothing to adopt.
#
# Usage:
#   ./adopt-eck-crds.sh [OPTIONS]
#
# Options:
#   --release NAME      Helm release name (default: podiumd)
#   --namespace NS      Helm release namespace (default: podiumd)
#   --context CONTEXT   kubectl context to use (default: current context)
#   --dry-run           Show current vs target ownership metadata, change nothing
#   -h, --help          Show this help message
#
# Prerequisites:
#   - kubectl with cluster-admin on the target cluster (CRDs are cluster-scoped)
#
# Example:
#   ./adopt-eck-crds.sh --context my-aks-cluster
#   ./adopt-eck-crds.sh --dry-run

set -euo pipefail

RELEASE_NAME="podiumd"
RELEASE_NS="podiumd"
CONTEXT=""
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

echo "==> Looking for ECK CRDs (*.k8s.elastic.co)..."
CRDS="$(kc get crd -o name | grep 'k8s\.elastic\.co' || true)"

if [[ -z "${CRDS}" ]]; then
  echo "==> No ECK CRDs present — fresh cluster, helm installs them on the first deploy. Nothing to do."
  exit 0
fi

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
  echo "==> [dry-run] ${COUNT} ECK CRDs found; nothing changed."
else
  echo "==> Adopted ${COUNT} ECK CRDs into Helm release ${RELEASE_NS}/${RELEASE_NAME}."
  echo "==> The next helm deploy/upgrade manages them and creates any missing ones."
fi
