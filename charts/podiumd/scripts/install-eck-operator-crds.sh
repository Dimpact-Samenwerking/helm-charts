#!/usr/bin/env bash
# install-eck-operator-crds.sh
#
# Installs (or upgrades) the 12 ECK CRDs (*.k8s.elastic.co) from Elastic's
# eck-operator Helm chart, out-of-band from the podiumd release.
#
# Background:
#   The umbrella sets eck-operator.installCRDs: false. Rendering the CRDs adds
#   ~775 KB to the release manifest, and helm stores every revision as ONE
#   Kubernetes Secret (gzipped release blob) capped at 1 MiB by Kubernetes. On
#   grown environments that pushes the release over the cap and every deploy
#   fails with:
#     Secret "sh.helm.release.v1.podiumd.v<n>" is invalid: data: Too long
#   Keeping the CRDs out of the release keeps the deploy inside the cap. Same
#   pattern as install-keycloak-operator-crds.sh / install-redis-operator-crds.sh.
#
#   The CRDs are cluster-scoped and carry helm.sh/resource-policy: keep, so
#   nothing here destroys existing Elastic CRs or their data: a CRD update is a
#   schema update, the Elasticsearch/Kibana objects and their PVCs stay put.
#
# When to run:
#   - once per cluster before the first deploy of a chart that has
#     installCRDs: false and no ECK CRDs present yet (fresh install), and
#   - before every deploy that bumps the eck-operator chart version in
#     charts/podiumd/Chart.yaml (the CRDs move in lock-step with the operator).
#   Idempotent: re-running with the same version changes nothing.
#
# Usage:
#   ./install-eck-operator-crds.sh [OPTIONS]
#
# Options:
#   --version VERSION   eck-operator chart version to take the CRDs from
#                       (default: the eck-operator version in ../Chart.yaml)
#   --release NAME      Helm release name used for the app.kubernetes.io/instance
#                       label (default: podiumd)
#   --context CONTEXT   kubectl context to use (default: current context)
#   --dry-run           Print the CRDs that would be applied, change nothing
#   -h, --help          Show this help message
#
# Prerequisites:
#   - helm (>= 3.x) with internet egress to https://helm.elastic.co
#   - kubectl with cluster-admin on the target cluster (CRDs are cluster-scoped),
#     unless --dry-run
#
# Example:
#   ./install-eck-operator-crds.sh --context aks-blue-ontw-mayk
#   ./install-eck-operator-crds.sh --version 3.4.1
#   ./install-eck-operator-crds.sh --dry-run

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_YAML="${SCRIPT_DIR}/../Chart.yaml"
REPO_NAME="elastic"
REPO_URL="https://helm.elastic.co"
CHART_NAME="eck-operator"
CRD_TEMPLATE="charts/eck-operator-crds/templates/all-crds.yaml"
RELEASE_NAME="podiumd"
CONTEXT_ARG=""
DRY_RUN=false

# Default to the version the umbrella depends on, so the CRDs never drift from
# the operator. Falls back to a pinned version if the script runs outside the
# chart directory.
CHART_VERSION="$(awk '/^[[:space:]]*-[[:space:]]*name:[[:space:]]*eck-operator[[:space:]]*$/ {found=1; next}
                      found && /^[[:space:]]*version:/ {print $2; exit}' "${CHART_YAML}" 2>/dev/null || true)"
CHART_VERSION="${CHART_VERSION:-3.4.0}"

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
    --release)
      RELEASE_NAME="$2"
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
if ! helm repo list 2>/dev/null | grep -q "^${REPO_NAME}[[:space:]]"; then
  helm repo add "${REPO_NAME}" "${REPO_URL}"
fi
helm repo update "${REPO_NAME}"

# The CRDs live in the eck-operator-crds subchart's templates/ (not in a crds/
# directory), so `helm show crds` returns nothing; render the template instead.
echo "==> Rendering CRDs from ${REPO_NAME}/${CHART_NAME} version ${CHART_VERSION}..."
CRD_YAML="$(helm template "${RELEASE_NAME}" "${REPO_NAME}/${CHART_NAME}" \
  --version "${CHART_VERSION}" \
  --set installCRDs=true \
  --show-only "${CRD_TEMPLATE}")"

CRD_NAMES="$(printf '%s\n' "${CRD_YAML}" | awk '/^  name: .*k8s\.elastic\.co$/ {print $2}')"
CRD_COUNT="$(printf '%s\n' "${CRD_NAMES}" | grep -c . || true)"

if [[ "${CRD_COUNT}" -eq 0 ]]; then
  echo "ERROR: no CRDs rendered from ${REPO_NAME}/${CHART_NAME}:${CHART_VERSION}" >&2
  exit 1
fi

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "==> [dry-run] ${CRD_COUNT} CRDs that would be applied:"
  printf '%s\n' "${CRD_NAMES}" | sed 's/^/    /'
  exit 0
fi

# --force-conflicts: on clusters upgraded from podiumd 4.8.0-4.8.3 the CRDs are
# still owned by helm's field manager, and on kisselastic-era clusters by a
# client-side kubectl apply. Both conflict with a plain server-side apply.
# --server-side: the CRDs are far too large for the client-side apply annotation.
echo "==> Applying ${CRD_COUNT} CRDs (server-side apply)..."
printf '%s\n' "${CRD_YAML}" | kubectl ${CONTEXT_ARG} apply --server-side --force-conflicts -f -

echo "==> Waiting for CRDs to reach Established condition..."
for crd in ${CRD_NAMES}; do
  echo "    Waiting for CRD: ${crd}"
  kubectl ${CONTEXT_ARG} wait --for=condition=Established "crd/${crd}" --timeout=60s
done

echo "==> ECK CRDs installed successfully (${CRD_COUNT} CRDs, eck-operator ${CHART_VERSION})."
echo "    The podiumd deploy can run now; it no longer carries the CRDs itself."
