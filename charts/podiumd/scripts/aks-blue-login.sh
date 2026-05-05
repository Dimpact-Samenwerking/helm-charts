#!/usr/bin/env -S bash -l
# aks-blue-login.sh
#
# Refreshes credentials for all known aks-blue-ontw-* clusters into a dedicated
# kubeconfig at ~/.kube/aks-blue (override with $AKS_BLUE_KUBECONFIG). Leaves the
# user's main ~/.kube/config alone so other tools/shells aren't disrupted.
#
# Pairs with cluster-status.sh and any kubectl/helm invocation that exports
# KUBECONFIG to the same file. After running, use one of:
#
#   export KUBECONFIG=~/.kube/aks-blue
#   kubectl --kubeconfig ~/.kube/aks-blue get pods -n podiumd --context aks-blue-ontw-dim1
#
# Or define a shell helper:
#
#   kbblue() { KUBECONFIG=~/.kube/aks-blue kubectl "$@"; }
#
# Usage:
#   ./scripts/aks-blue-login.sh             # all clusters
#   ./scripts/aks-blue-login.sh dim1 info   # subset by short name
#
# Requires: az CLI, kubelogin

set -euo pipefail

CLUSTERS=(
  "dim1:O-Dim1:rg-ontw-dim1:aks-blue-ontw-dim1"
  "dimp:O-Dimp:rg-ontw-dimp:aks-blue-ontw-dimp"
  "icat:O-Icat:rg-ontw-icat:aks-blue-ontw-icat"
  "info:O-Info:rg-ontw-info:aks-blue-ontw-info"
  "mayk:O-Mayk:rg-ontw-mayk:aks-blue-ontw-mayk"
)

KCFG="${AKS_BLUE_KUBECONFIG:-$HOME/.kube/aks-blue}"
mkdir -p "$(dirname "$KCFG")"

# Filter by short names if any args given
SELECTED=("$@")
match() {
  local short="$1"
  if [[ ${#SELECTED[@]} -eq 0 ]]; then return 0; fi
  for s in "${SELECTED[@]}"; do
    [[ "$s" == "$short" ]] && return 0
  done
  return 1
}

if ! az account get-access-token \
       --resource 6dae42f8-4a1f-4b48-883b-b5ed68c5d52c \
       --only-show-errors >/dev/null 2>&1; then
  echo "ERROR: az session expired or missing AKS server token. Run: az login" >&2
  exit 1
fi

echo "==> Writing kubeconfig: $KCFG"

for entry in "${CLUSTERS[@]}"; do
  IFS=':' read -r short subscription rg cluster <<< "$entry"
  match "$short" || continue

  echo "    [$short] $cluster (sub=$subscription rg=$rg)"
  az aks get-credentials \
    --subscription "$subscription" \
    --resource-group "$rg" \
    --name "$cluster" \
    --overwrite-existing \
    --only-show-errors \
    --file "$KCFG" \
    > /dev/null
done

echo "==> Converting users to kubelogin -l azurecli"
KUBECONFIG="$KCFG" kubelogin convert-kubeconfig -l azurecli

echo
echo "Done. To use this kubeconfig:"
echo "  export KUBECONFIG=$KCFG"
echo "Or per-call:"
echo "  kubectl --kubeconfig $KCFG get pods -n podiumd --context aks-blue-ontw-dim1"
