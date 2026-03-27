#!/bin/bash

# Cleanup script for legacy Keycloak and Infinispan resources
# This script removes resources created by the Bitnami Keycloak chart and Infinispan chart
# Run this before migrating to keycloak-operator

set -e

NAMESPACE="${NAMESPACE:-default}"
RELEASE_NAME="${RELEASE_NAME:-podiumd}"

echo "This script will remove Keycloak and Infinispan resources from namespace: $NAMESPACE"
echo "Release name: $RELEASE_NAME"
echo ""
echo "WARNING: This will delete:"
echo "  - Keycloak Deployments/StatefulSets"
echo "  - Keycloak Services"
echo "  - Keycloak PVCs (Persistent Volume Claims) - DATA WILL BE LOST"
echo "  - Infinispan StatefulSets"
echo "  - Infinispan Services"
echo "  - Infinispan PVCs (Persistent Volume Claims) - DATA WILL BE LOST"
echo ""
read -p "Are you sure you want to continue? (yes/no): " confirm

if [[ "$confirm" != "yes" ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "Starting cleanup..."

# Function to safely delete resources
delete_resource() {
    resource_type=$1
    selector=$2
    echo "Deleting $resource_type with selector: $selector"
    kubectl delete $resource_type -n $NAMESPACE -l $selector --ignore-not-found=true
}

# Cleanup Keycloak resources
echo ""
echo "==> Cleaning up Keycloak resources..."
delete_resource "deployment" "app.kubernetes.io/name=keycloak"
delete_resource "statefulset" "app.kubernetes.io/name=keycloak"
delete_resource "service" "app.kubernetes.io/name=keycloak"
delete_resource "configmap" "app.kubernetes.io/name=keycloak"
delete_resource "secret" "app.kubernetes.io/name=keycloak"
delete_resource "pvc" "app.kubernetes.io/name=keycloak"

# Alternative cleanup if labeled differently
delete_resource "deployment" "app.kubernetes.io/component=keycloak"
delete_resource "statefulset" "app.kubernetes.io/component=keycloak"
delete_resource "service" "app.kubernetes.io/component=keycloak"
delete_resource "pvc" "app.kubernetes.io/component=keycloak"

# Cleanup Infinispan resources (installed as "ispn")
echo ""
echo "==> Cleaning up Infinispan resources..."
# Infinispan is typically installed with clusterName=ispn and meta.helm.sh/release-name=ispn
delete_resource "statefulset" "clusterName=ispn"
delete_resource "service" "clusterName=ispn"
delete_resource "configmap" "clusterName=ispn"
delete_resource "pvc" "clusterName=ispn"

# Alternative cleanup using helm release name
delete_resource "statefulset" "meta.helm.sh/release-name=ispn"
delete_resource "service" "meta.helm.sh/release-name=ispn"
delete_resource "configmap" "meta.helm.sh/release-name=ispn"

# Cleanup ispn secrets (some have no labels, need to be deleted by name)
echo "Deleting ispn secrets by name..."
kubectl delete secret ispn-secret ispn-generated-secret ispn-transport-secret -n $NAMESPACE --ignore-not-found=true

# Legacy cleanup patterns (for older infinispan installations)
delete_resource "statefulset" "app.kubernetes.io/name=infinispan"
delete_resource "service" "app.kubernetes.io/name=infinispan"
delete_resource "configmap" "app.kubernetes.io/name=infinispan"
delete_resource "secret" "app.kubernetes.io/name=infinispan"
delete_resource "pvc" "app.kubernetes.io/name=infinispan"

delete_resource "statefulset" "app.kubernetes.io/component=infinispan"
delete_resource "service" "app.kubernetes.io/component=infinispan"
delete_resource "pvc" "app.kubernetes.io/component=infinispan"

# Cleanup by release name pattern (fallback)
echo ""
echo "==> Cleaning up resources by release name pattern..."
delete_resource "deployment,statefulset" "app.kubernetes.io/instance=${RELEASE_NAME}-keycloak"
delete_resource "service" "app.kubernetes.io/instance=${RELEASE_NAME}-keycloak"
delete_resource "pvc" "app.kubernetes.io/instance=${RELEASE_NAME}-keycloak"

delete_resource "statefulset" "app.kubernetes.io/instance=${RELEASE_NAME}-infinispan"
delete_resource "service" "app.kubernetes.io/instance=${RELEASE_NAME}-infinispan"
delete_resource "pvc" "app.kubernetes.io/instance=${RELEASE_NAME}-infinispan"

echo ""
echo "==> Cleanup completed!"
echo ""
echo "You can now proceed with installing keycloak-operator."
echo "Make sure to update your values.yaml with:"
echo "  keycloak:"
echo "    enabled: false"
echo "  infinispan:"
echo "    enabled: false"
echo "  keycloak-operator:"
echo "    enabled: true"
