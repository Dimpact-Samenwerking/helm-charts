#!/usr/bin/env bash
# install-prometheus-operator-crds.sh
#
# Installs the Prometheus Operator CRDs required by monitoring-logging 1.0.11+.
#
# The monitoring-logging chart uses kube-prometheus-stack 83.0.0 which bundles
# prometheus-operator v0.90.1. CRDs are managed separately (crds.enabled: false
# in chart values) so they survive Helm upgrades and chart uninstalls without
# accidentally being deleted.
#
# Usage:
#   ./install-prometheus-operator-crds.sh [--context <cluster>] [--upgrade]
#
# Options:
#   --context <name>   kubectl context to use (recommended; avoids acting on the
#                      wrong cluster). Defaults to current context.
#   --upgrade          Re-apply CRDs even if they already exist (safe; uses
#                      server-side apply with --force-conflicts).
#
# Requirements:
#   - kubectl >= 1.18 (server-side apply)
#   - helm >= 3.8
#   - prometheus-community Helm repo registered:
#       helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
#       helm repo update
#
# What this installs:
#   CRDs from prometheus-operator v0.90.1 (kube-prometheus-stack 83.0.0):
#   - monitoring.coreos.com/v1   AlertManager, Prometheus, PrometheusRule,
#                                ServiceMonitor, PodMonitor, ThanosRuler, Probe
#   - monitoring.coreos.com/v1alpha1  PrometheusAgent, ScrapeConfig
#   - monitoring.coreos.com/v1beta1  AlertmanagerConfig

set -euo pipefail

CHART_VERSION="83.0.0"
KUBECTL_CONTEXT=""
FORCE_UPGRADE=false

# --- Argument parsing ---------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --context)
      KUBECTL_CONTEXT="$2"
      shift 2
      ;;
    --upgrade)
      FORCE_UPGRADE=true
      shift
      ;;
    -h|--help)
      sed -n '/^# Usage:/,/^[^#]/{ /^[^#]/d; s/^# \{0,1\}//; p }' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

KUBECTL_FLAGS=()
if [[ -n "$KUBECTL_CONTEXT" ]]; then
  KUBECTL_FLAGS+=(--context "$KUBECTL_CONTEXT")
fi

# --- Preflight ----------------------------------------------------------------
echo "==> Checking prerequisites..."

if ! command -v kubectl &>/dev/null; then
  echo "ERROR: kubectl not found in PATH" >&2
  exit 1
fi
if ! command -v helm &>/dev/null; then
  echo "ERROR: helm not found in PATH" >&2
  exit 1
fi

if ! helm repo list 2>/dev/null | grep -q prometheus-community; then
  echo "==> Adding prometheus-community Helm repo..."
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
fi
echo "==> Updating Helm repo cache..."
helm repo update prometheus-community

# --- Check whether CRDs already exist ----------------------------------------
EXISTING_CRDS=$(kubectl "${KUBECTL_FLAGS[@]}" get crd 2>/dev/null \
  | grep "monitoring.coreos.com" | wc -l || echo 0)

if [[ "$EXISTING_CRDS" -gt 0 && "$FORCE_UPGRADE" == false ]]; then
  echo ""
  echo "INFO: Found $EXISTING_CRDS existing monitoring.coreos.com CRD(s)."
  echo "      To upgrade/re-apply them, re-run with --upgrade."
  echo "      Skipping CRD installation."
  echo ""
  echo "Existing CRDs:"
  kubectl "${KUBECTL_FLAGS[@]}" get crd | grep "monitoring.coreos.com"
  exit 0
fi

# --- Extract and apply CRDs ---------------------------------------------------
echo ""
echo "==> Extracting CRDs from kube-prometheus-stack ${CHART_VERSION}..."

APPLY_FLAGS=(--server-side --field-manager=helm)
if [[ "$FORCE_UPGRADE" == true ]]; then
  APPLY_FLAGS+=(--force-conflicts)
fi

helm show crds prometheus-community/kube-prometheus-stack --version "${CHART_VERSION}" \
  | kubectl "${KUBECTL_FLAGS[@]}" apply "${APPLY_FLAGS[@]}" -f -

echo ""
echo "==> CRDs installed successfully. Installed CRDs:"
kubectl "${KUBECTL_FLAGS[@]}" get crd | grep "monitoring.coreos.com"
echo ""
echo "Done. You can now deploy monitoring-logging with:"
echo "  helm upgrade --install monitoring charts/monitoring-logging \\"
echo "    -f values-monitoring-<env>.yaml \\"
echo "    -n monitoring --create-namespace"
