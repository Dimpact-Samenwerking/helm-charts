#!/bin/bash

# Script to delete indices from Elasticsearch.  
# This is needed when upgrading to PodiumD 4.9.x as the KISS interface now shows
# every index present in elasticsearch even if they contain no data
# The KISS helm-chart creates indices for all syncJobs in the values file
# By default all PodiumD installations contained syncjobs for Kennisbank and VAC.
# But every gemeente does not use them all.

# Usage: ./delete-es-index.sh <index-name> [namespace] [elasticsearch-name]
# Example: ./delete-es-index.sh "index-name"
# Example: ./delete-es-index.sh "index-name" "podiumd"
# Example: ./delete-es-index.sh "index-name" "podiumd" "kiss"
#
# [namespace] defaults to 'podiumd' if not specified
# [elasticsearch-name] defaults to 'kiss' if not specified
#
# Prerequisites:
#   - kubectl must be installed and configured with the correct context
#   - The Kubernetes secret '<elasticsearch-name>-es-elastic-user' must exist in the target namespace
#   - The Elasticsearch (ECK) service '<elasticsearch-name>-es-http' must exist in the target namespace
#
# Note: PodiumD's Elasticsearch clusters are managed by the ECK operator, which names
#       the Service and Secret after the Elasticsearch resource, e.g. cluster "kiss" gets
#       service "kiss-es-http" and secret "kiss-es-elastic-user" (data key "elastic").
# Note: This script automatically sets up port-forwarding to Elasticsearch
# Note: This script uses the Elasticsearch REST API (/<index>) directly,
#       which requires basic auth with Elasticsearch credentials.
# Note: This script uses --insecure flag to skip SSL certificate verification

set -e

# Configuration
INDEX_NAME="${1:-}"
NAMESPACE="${2:-podiumd}"
ELASTICSEARCH_NAME="${3:-kiss}"
USERNAME="elastic"
ELASTICSEARCH_SERVICE="${ELASTICSEARCH_NAME}-es-http"
ELASTIC_USER_SECRET="${ELASTICSEARCH_NAME}-es-elastic-user"
LOCAL_PORT="9200"
ENDPOINT="https://localhost:${LOCAL_PORT}"
PORT_FORWARD_PID=""

# Colors for output (only if terminal supports it)
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    NC='\033[0m' # No Color
else
    RED=''
    GREEN=''
    YELLOW=''
    NC=''
fi

# Functions
print_error() {
    echo -e "${RED}Error: $1${NC}" >&2
}

print_success() {
    echo -e "${GREEN}$1${NC}"
}

print_warning() {
    echo -e "${YELLOW}$1${NC}"
}

# Cleanup function to kill port-forward process on exit
cleanup() {
    if [[ -n "${PORT_FORWARD_PID}" ]] && kill -0 "${PORT_FORWARD_PID}" 2>/dev/null; then
        echo ""
        echo "Cleaning up port-forward process (PID: ${PORT_FORWARD_PID})..."
        kill "${PORT_FORWARD_PID}" 2>/dev/null || true
        wait "${PORT_FORWARD_PID}" 2>/dev/null || true
    fi
}

# Set trap to cleanup on exit
trap cleanup EXIT INT TERM

usage() {
    echo "Usage: $0 <index-name> [namespace] [elasticsearch-name]"
    echo ""
    echo "Arguments:"
    echo "  index-name         Index to delete (required)"
    echo "  namespace          Kubernetes namespace (default: podiumd)"
    echo "  elasticsearch-name ECK Elasticsearch resource name, e.g. 'kiss' (default: kiss)"
    echo ""
    echo "Prerequisites:"
    echo "  - kubectl must be installed and configured with the correct context"
    echo "  - The Kubernetes secret '${ELASTIC_USER_SECRET}' must exist in the namespace"
    echo "  - The Elasticsearch service '${ELASTICSEARCH_SERVICE}' must exist in the namespace"
    echo ""
    echo "Examples:"
    echo "  $0 index-name"
    echo "  $0 index-name podiumd"
    echo "  $0 index-name podiumd kiss"
    exit 1
}

# Require a single concrete index name; refuse to guess to avoid deleting the wrong index
if [[ -z "${INDEX_NAME}" || ! "${INDEX_NAME}" =~ ^[a-z0-9][a-z0-9._-]*$ ]]; then
    print_error "Index name must be a single concrete Elasticsearch index name"
    echo ""
    usage
fi

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    print_error "kubectl is not installed or not in PATH"
    exit 1
fi

# Retrieve password from Kubernetes secret
echo "Retrieving credentials from Kubernetes secret..."
set +e
PASSWORD=$(kubectl get secret "${ELASTIC_USER_SECRET}" -o go-template='{{.data.elastic | base64decode }}' -n "${NAMESPACE}" 2>&1)
KUBECTL_EXIT_CODE=$?
set -e

if [[ ${KUBECTL_EXIT_CODE} -ne 0 ]]; then
    print_error "Failed to retrieve password from Kubernetes secret"
    echo "Namespace: ${NAMESPACE}"
    echo "Secret: ${ELASTIC_USER_SECRET}"
    echo "Error: ${PASSWORD}"
    echo ""
    echo "Make sure:"
    echo "  - The correct Kubernetes context is set"
    echo "  - The secret '${ELASTIC_USER_SECRET}' exists in namespace '${NAMESPACE}'"
    echo "  - You have permission to read secrets in the namespace"
    exit 1
fi

if [[ -z "${PASSWORD}" ]]; then
    print_error "Password retrieved from secret is empty"
    exit 1
fi

print_success "Credentials retrieved successfully"
echo ""

# Setup port-forwarding to Elasticsearch
echo "Setting up port-forward to Elasticsearch service..."

# Check if port is already in use
if nc -z localhost "${LOCAL_PORT}" 2>/dev/null; then
    print_warning "Port ${LOCAL_PORT} is already in use"
    echo "Assuming Elasticsearch is already accessible at ${ENDPOINT}"
else
    # Start port-forward in background
    kubectl port-forward "svc/${ELASTICSEARCH_SERVICE}" "${LOCAL_PORT}:9200" -n "${NAMESPACE}" &>/dev/null &
    PORT_FORWARD_PID=$!
    
    # Wait for port-forward to be ready
    echo "Waiting for port-forward to be ready..."
    MAX_WAIT=30
    WAIT_COUNT=0
    while ! nc -z localhost "${LOCAL_PORT}" 2>/dev/null; do
        sleep 1
        WAIT_COUNT=$((WAIT_COUNT + 1))
        if [[ ${WAIT_COUNT} -ge ${MAX_WAIT} ]]; then
            print_error "Port-forward did not become ready within ${MAX_WAIT} seconds"
            echo ""
            echo "Make sure:"
            echo "  - The Elasticsearch service '${ELASTICSEARCH_SERVICE}' exists in namespace '${NAMESPACE}'"
            echo "  - You have permission to port-forward in the namespace"
            exit 1
        fi
        # Check if port-forward process is still running
        if ! kill -0 "${PORT_FORWARD_PID}" 2>/dev/null; then
            print_error "Port-forward process died unexpectedly"
            echo ""
            echo "Make sure:"
            echo "  - The Elasticsearch service '${ELASTICSEARCH_SERVICE}' exists in namespace '${NAMESPACE}'"
            echo "  - The service has a running pod"
            exit 1
        fi
    done
    print_success "Port-forward established (PID: ${PORT_FORWARD_PID})"
fi
echo ""

echo "=============================================="
echo "Elasticsearch Index Deletion Tool"
echo "=============================================="
echo ""
echo "Endpoint:    ${ENDPOINT}"
echo "Index:       ${INDEX_NAME}"
echo "Elasticsearch cluster: ${ELASTICSEARCH_NAME}"
echo "Namespace:   ${NAMESPACE}"
echo "Username:    ${USERNAME}"
echo ""

# Step 1: First check if the index exists
echo "Step 1: Checking if index '${INDEX_NAME}' exists..."

set +e
HTTP_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${ENDPOINT}/${INDEX_NAME}" \
    --insecure \
    --connect-timeout 10 \
    --max-time 30 \
    -u "${USERNAME}:${PASSWORD}" \
    -H "Content-Type: application/json" 2>&1)

CURL_EXIT_CODE=$?
set -e

if [[ ${CURL_EXIT_CODE} -ne 0 ]]; then
    print_error "Failed to connect to API endpoint"
    echo "Endpoint: ${ENDPOINT}"
    case ${CURL_EXIT_CODE} in
        6)
            echo "Reason: Could not resolve host - check the endpoint URL"
            ;;
        7)
            echo "Reason: Failed to connect to host - API may be unavailable"
            ;;
        28)
            echo "Reason: Connection timeout - API is not responding"
            ;;
        35|51|60)
            echo "Reason: SSL/TLS certificate error"
            echo "Tip: The script already uses --insecure flag"
            ;;
        *)
            echo "Reason: Connection failed (exit code: ${CURL_EXIT_CODE})"
            ;;
    esac
    exit 1
fi

# Extract HTTP status code and response body
HTTP_CODE=$(echo "${HTTP_RESPONSE}" | tail -n1)
RESPONSE=$(echo "${HTTP_RESPONSE}" | sed '$d')

# Check if index exists
if [[ "${HTTP_CODE}" -eq 404 ]]; then
    print_warning "Index '${INDEX_NAME}' does not exist or was already deleted."
    echo "No action needed."
    exit 0
elif [[ "${HTTP_CODE}" -ne 200 ]]; then
    print_error "Failed to check index status (HTTP ${HTTP_CODE})"
    case ${HTTP_CODE} in
        401)
            echo "Reason: Unauthorized - invalid username or password"
            ;;
        403)
            echo "Reason: Forbidden - insufficient permissions"
            ;;
        *)
            echo "Reason: Unexpected error"
            ;;
    esac
    if [[ -n "${RESPONSE}" ]]; then
        echo "Response: ${RESPONSE}"
    fi
    exit 1
fi

print_success "✓ Index '${INDEX_NAME}' found"

# Display index info if jq is available
if command -v jq &> /dev/null; then
    DOC_COUNT_RESPONSE=$(curl -s -X GET "${ENDPOINT}/${INDEX_NAME}/_count" \
        --insecure \
        --connect-timeout 10 \
        --max-time 30 \
        -u "${USERNAME}:${PASSWORD}" \
        -H "Content-Type: application/json" 2>/dev/null)
    DOCUMENT_COUNT=$(echo "${DOC_COUNT_RESPONSE}" | jq -r '.count // "unknown"')
    echo "  - Document count: ${DOCUMENT_COUNT}"
fi
echo ""

# Step 2: Confirm deletion
echo "Step 2: Preparing to delete index..."
print_warning "WARNING: This will permanently delete the index '${INDEX_NAME}' and all its data!"
echo ""

# Check if running interactively
if [[ -t 0 ]]; then
    read -r -p "Are you sure you want to delete this index? (yes/no): " CONFIRM
    if [[ "${CONFIRM}" != "yes" ]]; then
        echo "Deletion cancelled."
        exit 0
    fi
else
    print_warning "Running non-interactively - proceeding with deletion"
fi
echo ""

# Step 3: Delete the index
echo "Step 3: Deleting index '${INDEX_NAME}'..."

set +e
HTTP_RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${ENDPOINT}/${INDEX_NAME}" \
    --insecure \
    --connect-timeout 10 \
    --max-time 60 \
    -u "${USERNAME}:${PASSWORD}" \
    -H "Content-Type: application/json" 2>&1)

CURL_EXIT_CODE=$?
set -e

if [[ ${CURL_EXIT_CODE} -ne 0 ]]; then
    print_error "Failed to connect to API endpoint during deletion"
    echo "Curl exit code: ${CURL_EXIT_CODE}"
    exit 1
fi

# Extract HTTP status code and response body
HTTP_CODE=$(echo "${HTTP_RESPONSE}" | tail -n1)
RESPONSE=$(echo "${HTTP_RESPONSE}" | sed '$d')

# Check deletion result
if [[ "${HTTP_CODE}" -eq 200 ]]; then
    # Verify the response contains acknowledged: true
    if command -v jq &> /dev/null; then
        ACKNOWLEDGED=$(echo "${RESPONSE}" | jq -r '.acknowledged // false')
        if [[ "${ACKNOWLEDGED}" == "true" ]]; then
            print_success "✓ Index '${INDEX_NAME}' successfully deleted!"
        else
            print_warning "Index deletion request completed but 'acknowledged' flag was not true"
            echo "Response: ${RESPONSE}"
        fi
    else
        print_success "✓ Index '${INDEX_NAME}' successfully deleted!"
    fi
elif [[ "${HTTP_CODE}" -eq 404 ]]; then
    print_warning "Index '${INDEX_NAME}' was not found (may have been already deleted)"
else
    print_error "Failed to delete index (HTTP ${HTTP_CODE})"
    case ${HTTP_CODE} in
        401)
            echo "Reason: Unauthorized - invalid username or password"
            ;;
        403)
            echo "Reason: Forbidden - insufficient permissions to delete index"
            ;;
        409)
            echo "Reason: Conflict - index may have an in-progress operation (e.g. snapshot)"
            ;;
        *)
            echo "Reason: Unexpected error"
            ;;
    esac
    if [[ -n "${RESPONSE}" ]]; then
        echo "Response: ${RESPONSE}"
    fi
    exit 1
fi

echo ""
echo "=============================================="
print_success "Operation completed successfully"
echo "=============================================="
