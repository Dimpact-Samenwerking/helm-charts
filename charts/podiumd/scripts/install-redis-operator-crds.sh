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
#   --version VERSION   Chart version to fetch CRDs from (default: 0.27.0, the
#                       redis-operator chart PodiumD 4.10.0 ships)
#   --allow-downgrade   Allow a --version older than the default. The apply takes
#                       over the CRD fields (--force-conflicts), so an older
#                       version replaces the schema and prunes newer fields from
#                       the Redis CRs on their next write.
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
#   ./install-redis-operator-crds.sh --version 0.27.0
#   ./install-redis-operator-crds.sh --context my-aks-cluster
#   ./install-redis-operator-crds.sh --dry-run

set -euo pipefail

DEFAULT_VERSION="0.27.0"
CHART_VERSION="${DEFAULT_VERSION}"
ALLOW_DOWNGRADE=false
DRY_RUN=false
KUBECTL=(kubectl)
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
    --allow-downgrade)
      ALLOW_DOWNGRADE=true
      shift
      ;;
    --context)
      KUBECTL=(kubectl --context "$2")
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

if [[ "${ALLOW_DOWNGRADE}" != "true" && "${CHART_VERSION}" != "${DEFAULT_VERSION}" ]] \
  && [[ "$(printf '%s\n%s\n' "${CHART_VERSION}" "${DEFAULT_VERSION}" | sort -V | head -1)" == "${CHART_VERSION}" ]]; then
  echo "ERROR: --version ${CHART_VERSION} is older than ${DEFAULT_VERSION}. The forced apply would replace" >&2
  echo "       the newer CRD schema and prune its fields from the Redis CRs. Pass --allow-downgrade" >&2
  echo "       if that is really what you want." >&2
  exit 1
fi

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
  echo "${CRD_YAML}" | awk '/^apiVersion:/ && NR>1 && prev != "---" { print "---" } { print; prev = $0 }'
  exit 0
fi

# --force-conflicts takes the CRD fields over from Helm (or a GitOps tool);
# why that is safe here: docs/_UPGRADE_PATHS/4.9.5-to-4.10.0-operators-crds.md.
echo "==> Applying CRDs (server-side apply)..."
echo "${CRD_YAML}" \
  | awk '/^apiVersion:/ && NR>1 && prev != "---" { print "---" } { print; prev = $0 }' \
  | "${KUBECTL[@]}" apply --server-side --force-conflicts -f -

echo "==> Waiting for CRDs to reach Established condition..."
CRD_NAMES=$(echo "${CRD_YAML}" | grep '^  name:' | awk '{print $2}')
for crd in ${CRD_NAMES}; do
  echo "    Waiting for CRD: ${crd}"
  "${KUBECTL[@]}" wait --for=condition=Established "crd/${crd}" --timeout=60s
done

echo "==> Redis Operator CRDs installed successfully (version ${CHART_VERSION})."
