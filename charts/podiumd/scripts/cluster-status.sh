#!/usr/bin/env -S bash -l
# Shows the PodiumD Helm release version and status for all known aks-blue-ontw-* clusters.
# Requires: az CLI (logged in), kubectl, helm, kubelogin
#
# Uses a dedicated kubeconfig at ~/.kube/aks-blue so refetching credentials never
# stomps the user's main ~/.kube/config (which other tools and shells share).
#
# Usage: ./scripts/cluster-status.sh

set -euo pipefail

CLUSTERS=(
  "O-Dim1:rg-ontw-dim1:aks-blue-ontw-dim1"
  "O-Dimp:rg-ontw-dimp:aks-blue-ontw-dimp"
  "O-Icat:rg-ontw-icat:aks-blue-ontw-icat"
  "O-Info:rg-ontw-info:aks-blue-ontw-info"
  "O-Mayk:rg-ontw-mayk:aks-blue-ontw-mayk"
)

KCFG="${AKS_BLUE_KUBECONFIG:-$HOME/.kube/aks-blue}"
mkdir -p "$(dirname "$KCFG")"
export KUBECONFIG="$KCFG"

# Verify az session is alive (kubelogin -l azurecli depends on the cached MSAL token)
if ! az account get-access-token \
       --resource 6dae42f8-4a1f-4b48-883b-b5ed68c5d52c \
       --only-show-errors >/dev/null 2>&1; then
  echo "ERROR: az session expired or missing AKS server token. Run: az login" >&2
  exit 1
fi

printf "%-26s %-10s %-16s %s\n" "CLUSTER" "VERSION" "STATUS" "DEPLOYED_AT"
printf "%-26s %-10s %-16s %s\n" "-------" "-------" "------" "-----------"

for entry in "${CLUSTERS[@]}"; do
  IFS=':' read -r subscription rg cluster <<< "$entry"

  az aks get-credentials \
    --subscription "$subscription" \
    --resource-group "$rg" \
    --name "$cluster" \
    --overwrite-existing \
    --only-show-errors \
    --file "$KCFG" \
    > /dev/null 2>&1

  metadata=$(helm --kube-context "$cluster" get metadata podiumd -n podiumd 2>/dev/null || true)

  if [[ -z "$metadata" ]]; then
    printf "%-26s %-10s %-16s %s\n" "$cluster" "N/A" "UNREACHABLE" "-"
    continue
  fi

  version=$(echo "$metadata"    | awk '/^VERSION:/{print $2}')
  status=$(echo "$metadata"     | awk '/^STATUS:/{print $2}')
  deployed_at=$(echo "$metadata" | awk '/^DEPLOYED_AT:/{print $2}')

  printf "%-26s %-10s %-16s %s\n" "$cluster" "$version" "$status" "$deployed_at"
done

# Convert all user blocks in the dedicated kubeconfig once at the end.
kubelogin convert-kubeconfig -l azurecli >/dev/null 2>&1 || true
