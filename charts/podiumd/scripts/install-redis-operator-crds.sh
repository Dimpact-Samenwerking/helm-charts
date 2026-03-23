#!/usr/bin/env bash
# install-redis-operator-crds.sh
#
# Installs (or upgrades) the Redis Operator CRDs from the OT Container Kit Helm chart.
#
# Background:
#   Helm auto-installs CRDs from a chart's crds/ directory on the FIRST install,
#   but does NOT update them on subsequent `helm upgrade` runs.
#   Run this script before `helm upgrade` when upgrading the redis-operator chart
#   to a new version so that the CRDs are in sync.
#
# Usage:
#   ./install-redis-operator-crds.sh [OPTIONS]
#
# Options:
#   --version VERSION   Chart version to fetch CRDs from (default: 0.24.0)
#   --context CONTEXT   kubectl context to use (default: current context)
#   --dry-run           Print the CRDs YAML without applying them
#   -h, --help          Show this help message
#
# Prerequisites:
#   - helm (>= 3.x)
#   - kubectl (configured to reach the target cluster), unless --dry-run
#
# Example:
#   ./install-redis-operator-crds.sh
#   ./install-redis-operator-crds.sh --version 0.16.0
#   ./install-redis-operator-crds.sh --context my-aks-cluster
#   ./install-redis-operator-crds.sh --dry-run

set -euo pipefail

CHART_VERSION="0.24.0"
DRY_RUN=false
CONTEXT_ARG=""
REPO_NAME="opstree"
REPO_URL="https://ot-container-kit.github.io/helm-charts/"
CHART_NAME="redis-operator"

usage() {
  grep '^#' "$0" | grep -v '^#!/' | sed 's/^# //' | sed 's/^#//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      CHART_VERSION="$2"
      shift 2
      ;;
    --context)
      CONTEXT_ARG="--context $2"
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

echo "==> Ensuring Helm repo '${REPO_NAME}' is available..."
if ! helm repo list 2>/dev/null | grep -q "^${REPO_NAME}\s"; then
  helm repo add "${REPO_NAME}" "${REPO_URL}"
fi
helm repo update "${REPO_NAME}"

echo "==> Fetching CRDs from ${REPO_NAME}/${CHART_NAME} version ${CHART_VERSION}..."
CRD_YAML=$(helm show crds "${REPO_NAME}/${CHART_NAME}" --version "${CHART_VERSION}")

if [[ -z "${CRD_YAML}" ]]; then
  echo "ERROR: No CRDs found in ${REPO_NAME}/${CHART_NAME}:${CHART_VERSION}" >&2
  exit 1
fi

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "==> [dry-run] CRDs that would be applied:"
  echo "${CRD_YAML}" | awk '/^apiVersion:/ && NR>1 { print "---" } { print }'
  exit 0
fi

echo "==> Applying CRDs (server-side apply)..."
echo "${CRD_YAML}" \
  | awk '/^apiVersion:/ && NR>1 { print "---" } { print }' \
  | kubectl ${CONTEXT_ARG} apply --server-side -f -

echo "==> Waiting for CRDs to reach Established condition..."
CRD_NAMES=$(echo "${CRD_YAML}" | grep '^  name:' | awk '{print $2}')
for crd in ${CRD_NAMES}; do
  echo "    Waiting for CRD: ${crd}"
  kubectl ${CONTEXT_ARG} wait --for=condition=Established "crd/${crd}" --timeout=60s
done

echo "==> Redis Operator CRDs installed successfully (version ${CHART_VERSION})."
