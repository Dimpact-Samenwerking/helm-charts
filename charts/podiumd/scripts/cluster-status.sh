#!/usr/bin/env bash
# Shows the PodiumD Helm release version and status for all known aks-blue-ontw-* clusters.
# Requires: az CLI (logged in), kubectl, helm
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

printf "%-26s %-10s %-16s %s\n" "CLUSTER" "VERSION" "STATUS" "DEPLOYED_AT"
printf "%-26s %-10s %-16s %s\n" "-------" "-------" "------" "-----------"

for entry in "${CLUSTERS[@]}"; do
  IFS=':' read -r subscription rg cluster <<< "$entry"

  # Ensure cluster credentials are available
  az aks get-credentials \
    --subscription "$subscription" \
    --resource-group "$rg" \
    --name "$cluster" \
    --overwrite-existing \
    --only-show-errors \
    > /dev/null 2>&1

  # Fetch helm metadata
  metadata=$(kubectl config use-context "$cluster" > /dev/null 2>&1 && \
    helm get metadata podiumd -n podiumd 2>/dev/null || true)

  if [[ -z "$metadata" ]]; then
    printf "%-26s %-10s %-16s %s\n" "$cluster" "N/A" "UNREACHABLE" "-"
    continue
  fi

  version=$(echo "$metadata"    | awk '/^VERSION:/{print $2}')
  status=$(echo "$metadata"     | awk '/^STATUS:/{print $2}')
  deployed_at=$(echo "$metadata" | awk '/^DEPLOYED_AT:/{print $2}')

  printf "%-26s %-10s %-16s %s\n" "$cluster" "$version" "$status" "$deployed_at"
done
