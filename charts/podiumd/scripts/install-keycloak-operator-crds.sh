#!/usr/bin/env bash
# install-keycloak-operator-crds.sh
#
# Installs/upgrades the Keycloak Operator CRDs (`keycloaks.k8s.keycloak.org`,
# `keycloakrealmimports.k8s.keycloak.org`, and from Keycloak 26.7.0 also
# `keycloakoidcclients` and `keycloaksamlclients`) on the active kubectl context.
#
# Background:
#   Helm auto-installs CRDs from a chart's crds/ directory only on the FIRST
#   install; `helm upgrade` never touches them. Additionally, in PodiumD 4.7.0
#   the chart pins `keycloak-operator` to image 26.6.1, but the bundled adfinis
#   subchart 1.11.4 still ships `v2alpha1` CRDs from appVersion 26.5.6.
#   Operator 26.6.1 queries `apis/k8s.keycloak.org/v2beta1/...` and crashes
#   until the cluster has the upstream `v2beta1`-aware CRDs.
#
#   Default mode of this script fetches the upstream Keycloak `v1` CRD manifests
#   for a given Keycloak version (`v2beta1` storage + `v2alpha1` deprecated/served).
#   Use `--source chart` to fall back to whatever the adfinis subchart bundles.
#
# Usage:
#   ./install-keycloak-operator-crds.sh [OPTIONS]
#
# Options:
#   --keycloak-version VER   Upstream Keycloak version to fetch CRDs from
#                            (default: the chart's Keycloak pin,
#                            `keycloakImageVersion` in ../values.yaml;
#                            ignored when --source=chart)
#   --source upstream|chart  CRD source. Default: upstream
#                            upstream  -> github.com/keycloak/keycloak-k8s-resources
#                            chart     -> adfinis helm chart (legacy)
#   --chart-version VER      adfinis keycloak-operator chart version
#                            (default: 1.11.4; only used with --source=chart)
#   --context NAME           kubectl context (default: current-context)
#   --dry-run                Print CRDs without applying
#   -h, --help               Show this help
#
# Prerequisites:
#   - kubectl configured for the target cluster
#   - curl (for --source=upstream) OR helm 3.x (for --source=chart)
#
# Examples:
#   # Default: install the upstream CRDs for the chart's Keycloak pin on the
#   # current context
#   ./install-keycloak-operator-crds.sh
#
#   # Pin to a specific Keycloak version
#   ./install-keycloak-operator-crds.sh --keycloak-version 26.7.3
#
#   # Target a specific cluster
#   ./install-keycloak-operator-crds.sh --context aks-blue-ontw-dim1
#
#   # Preview without applying
#   ./install-keycloak-operator-crds.sh --dry-run
#
#   # Legacy: pull CRDs from adfinis subchart instead
#   ./install-keycloak-operator-crds.sh --source chart --chart-version 1.11.4

set -euo pipefail

# Default to the chart's own Keycloak pin, so the CRDs always match the
# operator this chart deploys (26.7.x needs the client CRDs).
VALUES_FILE="$(cd "$(dirname "$0")/.." && pwd)/values.yaml"
KEYCLOAK_VERSION=""
if [[ -f "${VALUES_FILE}" ]]; then
  KEYCLOAK_VERSION=$(sed -nE 's/.*&keycloakImageVersion "?([0-9][0-9.]*)"?.*/\1/p' "${VALUES_FILE}" | head -n1)
fi
CHART_VERSION="1.11.4"
SOURCE="upstream"
DRY_RUN=false
KCTX=""

REPO_NAME="adfinis"
REPO_URL="https://charts.adfinis.com"
CHART_NAME="keycloak-operator"

UPSTREAM_BASE="https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources"
CRD_FILES=(
  "keycloaks.k8s.keycloak.org-v1.yml"
  "keycloakrealmimports.k8s.keycloak.org-v1.yml"
)
# Client CRDs exist upstream from Keycloak 26.7.0. The 26.7.x operator watches
# them at startup and stops ("Informer startup error ... Not Found") when they
# are missing, so they are installed whenever the requested version has them.
OPTIONAL_CRD_FILES=(
  "keycloakoidcclients.k8s.keycloak.org-v1.yml"
  "keycloaksamlclients.k8s.keycloak.org-v1.yml"
)

usage() {
  grep '^#' "$0" | grep -v '^#!/' | sed 's/^# \{0,1\}//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keycloak-version) KEYCLOAK_VERSION="$2"; shift 2 ;;
    --source)           SOURCE="$2"; shift 2 ;;
    --chart-version)    CHART_VERSION="$2"; shift 2 ;;
    --context)          KCTX="$2"; shift 2 ;;
    --dry-run)          DRY_RUN=true; shift ;;
    -h|--help)          usage ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Run with --help for usage." >&2
      exit 1
      ;;
  esac
done

if [[ "${SOURCE}" == "upstream" && -z "${KEYCLOAK_VERSION}" ]]; then
  echo "ERROR: could not read the Keycloak version from ${VALUES_FILE}; pass --keycloak-version" >&2
  exit 1
fi

if [[ "${SOURCE}" != "upstream" && "${SOURCE}" != "chart" ]]; then
  echo "ERROR: --source must be 'upstream' or 'chart' (got '${SOURCE}')" >&2
  exit 1
fi

KUBECTL=(kubectl)
if [[ -n "${KCTX}" ]]; then
  KUBECTL+=(--context "${KCTX}")
fi

fetch_upstream() {
  local out=""
  local first=true
  for f in "${CRD_FILES[@]}"; do
    local url="${UPSTREAM_BASE}/${KEYCLOAK_VERSION}/kubernetes/${f}"
    echo "    Fetching ${url}" >&2
    local body
    if ! body=$(curl -sfL "${url}"); then
      echo "ERROR: Failed to fetch ${url}" >&2
      exit 1
    fi
    if [[ -z "${body}" ]]; then
      echo "ERROR: Empty CRD body from ${url}" >&2
      exit 1
    fi
    if ${first}; then first=false; else out+=$'\n---\n'; fi
    out+="${body}"
  done
  # Only a 404 below 26.7.0 means "not published". From 26.7.0 the operator
  # needs the client CRDs, so any failure is fatal; a network, TLS or server
  # error is fatal for every version, so it never passes as "not published".
  local needs_clients=false
  if [[ "$(printf '%s\n%s\n' "26.7.0" "${KEYCLOAK_VERSION}" | sort -V | head -n1)" == "26.7.0" ]]; then
    needs_clients=true
  fi
  for f in "${OPTIONAL_CRD_FILES[@]}"; do
    local url="${UPSTREAM_BASE}/${KEYCLOAK_VERSION}/kubernetes/${f}"
    local tmp code
    tmp=$(mktemp)
    if ! code=$(curl -sL -o "${tmp}" -w '%{http_code}' "${url}"); then
      rm -f "${tmp}"
      echo "ERROR: Failed to fetch ${url} (network or TLS error)" >&2
      exit 1
    fi
    if [[ "${code}" == "200" && -s "${tmp}" ]]; then
      echo "    Fetched ${url}" >&2
      out+=$'\n---\n'"$(cat "${tmp}")"
      rm -f "${tmp}"
    elif [[ "${code}" == "404" ]] && ! ${needs_clients}; then
      rm -f "${tmp}"
      echo "    Skipping ${f}: not published for Keycloak ${KEYCLOAK_VERSION} (client CRDs start at 26.7.0)" >&2
    else
      rm -f "${tmp}"
      if [[ "${code}" == "404" ]]; then
        echo "ERROR: ${url} not found (HTTP 404), but Keycloak ${KEYCLOAK_VERSION} needs this CRD" >&2
      else
        echo "ERROR: Failed to fetch ${url} (HTTP ${code}); retry later" >&2
      fi
      exit 1
    fi
  done
  printf '%s\n' "${out}"
}

fetch_chart() {
  if ! command -v helm >/dev/null 2>&1; then
    echo "ERROR: helm not found (required for --source=chart)" >&2
    exit 1
  fi
  echo "    Ensuring Helm repo '${REPO_NAME}' is available..." >&2
  if ! helm repo list 2>/dev/null | grep -q "^${REPO_NAME}\s"; then
    helm repo add "${REPO_NAME}" "${REPO_URL}" >&2
  fi
  helm repo update "${REPO_NAME}" >&2
  echo "    Fetching CRDs from ${REPO_NAME}/${CHART_NAME} ${CHART_VERSION}..." >&2
  local body
  body=$(helm show crds "${REPO_NAME}/${CHART_NAME}" --version "${CHART_VERSION}")
  if [[ -z "${body}" ]]; then
    echo "ERROR: No CRDs found in ${REPO_NAME}/${CHART_NAME}:${CHART_VERSION}" >&2
    exit 1
  fi
  # adfinis ships concatenated docs without '---' separators
  printf '%s\n' "${body}" | awk '/^apiVersion:/ && NR>1 { print "---" } { print }'
}

echo "==> Source: ${SOURCE}"
case "${SOURCE}" in
  upstream) echo "==> Keycloak version: ${KEYCLOAK_VERSION}"; CRD_YAML=$(fetch_upstream) ;;
  chart)    echo "==> Chart version: ${CHART_VERSION}";       CRD_YAML=$(fetch_chart)    ;;
esac

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "==> [dry-run] CRDs that would be applied:"
  printf '%s\n' "${CRD_YAML}"
  exit 0
fi

CTX_LABEL=$("${KUBECTL[@]}" config current-context 2>/dev/null || echo "<unknown>")
echo "==> Applying CRDs to context: ${CTX_LABEL}"
printf '%s\n' "${CRD_YAML}" | "${KUBECTL[@]}" apply --server-side --force-conflicts -f -

echo "==> Waiting for CRDs to reach Established condition..."
CRD_NAMES=$(printf '%s\n' "${CRD_YAML}" | awk '/^kind: *"?CustomResourceDefinition"?$/{flag=1; next} flag && /^metadata:/{getline; if ($1=="name:"){gsub(/"/,"",$2); print $2; flag=0}}')
if [[ -z "${CRD_NAMES}" ]]; then
  # Fallback parser if metadata block uses different ordering
  CRD_NAMES=$(printf '%s\n' "${CRD_YAML}" | grep -E '^  name: *"?(keycloaks|keycloakrealmimports|keycloakoidcclients|keycloaksamlclients)\.' | awk '{gsub(/"/,"",$2); print $2}' | sort -u)
fi
for crd in ${CRD_NAMES}; do
  echo "    Waiting for CRD: ${crd}"
  "${KUBECTL[@]}" wait --for=condition=Established "crd/${crd}" --timeout=60s
done

echo
echo "==> Verifying served versions:"
for crd in ${CRD_NAMES}; do
  vers=$("${KUBECTL[@]}" get crd "${crd}" -o jsonpath='{.spec.versions[*].name}{"\n"}')
  echo "    ${crd}: ${vers}"
done

cat <<EOF

==> CRDs installed successfully.

If existing CRs were stored under v2alpha1 (PodiumD 4.6.x), trigger a re-storage
to v2beta1 by reading them and re-applying:

    ${KUBECTL[*]} -n <namespace> get keycloak,keycloakrealmimport -o yaml \\
      | ${KUBECTL[*]} apply -f -

Then restart the operator:

    ${KUBECTL[*]} -n <namespace> rollout restart deploy keycloak-operator
EOF
