#!/usr/bin/env bash
# install-keycloak-operator-crds.sh
#
# Installs (or upgrades) the Keycloak Operator CRDs from the adfinis Helm chart.
#
# Background:
#   Helm auto-installs CRDs from a chart's crds/ directory on the FIRST install,
#   but does NOT update them on subsequent `helm upgrade` runs.
#   Run this script before `helm upgrade` when upgrading the keycloak-operator chart
#   to a new version so that the CRDs are in sync.
#
# Usage:
#   ./install-keycloak-operator-crds.sh [OPTIONS]
#
# Options:
#   --version VERSION   Chart version to fetch CRDs from (default: 1.11.2)
#   --dry-run           Print the CRDs YAML without applying them
#   -h, --help          Show this help message
#
# Prerequisites:
#   - helm (>= 3.x)
#   - kubectl (configured to reach the target cluster), unless --dry-run
#
# Example:
#   ./install-keycloak-operator-crds.sh
#   ./install-keycloak-operator-crds.sh --version 1.12.0
#   ./install-keycloak-operator-crds.sh --dry-run

set -euo pipefail

CHART_VERSION="1.11.2"
DRY_RUN=false
REPO_NAME="adfinis"
REPO_URL="https://charts.adfinis.com"
CHART_NAME="keycloak-operator"

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
  echo "${CRD_YAML}"
  exit 0
fi

echo "==> Applying CRDs (server-side apply)..."
echo "${CRD_YAML}" | kubectl apply --server-side -f -

echo "==> Waiting for CRDs to reach Established condition..."
# Extract CRD names from the YAML and wait for each
CRD_NAMES=$(echo "${CRD_YAML}" | grep '^  name:' | awk '{print $2}')
for crd in ${CRD_NAMES}; do
  echo "    Waiting for CRD: ${crd}"
  kubectl wait --for=condition=Established "crd/${crd}" --timeout=60s
done

echo "==> Keycloak Operator CRDs installed successfully (version ${CHART_VERSION})."
