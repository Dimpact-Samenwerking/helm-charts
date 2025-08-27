#!/bin/bash

# ITA Deployment Script with Database Initialization
# This script ensures the database user exists before deploying ITA

set -e

# Configuration
NAMESPACE="beproeving"
RELEASE_NAME="ita"
CHART_URL="oci://ghcr.io/interne-taak-afhandeling/internetaakafhandeling"
CHART_VERSION="0.2.2"
VALUES_FILE="charts/beproeving/values.yaml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Build common Helm --set flags from environment variables
build_helm_set_flags() {
    HELM_SET_FLAGS=()

    # Required secrets (fail fast if missing)
    : "${PG_PASSWORD:?Set PG_PASSWORD (postgresql.auth.password)}"
    : "${PG_ADMIN_PASSWORD:?Set PG_ADMIN_PASSWORD (postgresql.auth.postgresPassword)}"
    : "${DB_PASSWORD:?Set DB_PASSWORD (database.password for user 'ita')}"
    : "${OPENKLANT_API_KEY:?Set OPENKLANT_API_KEY}"
    : "${OBJECT_API_KEY:?Set OBJECT_API_KEY}"
    : "${ZAAKSYSTEEM_KEY:?Set ZAAKSYSTEEM_KEY}"
    : "${ITA_CLIENT_SECRET:?Set ITA_CLIENT_SECRET (web.oidc.clientSecret)}"

    # Optional
    : "${POLLER_SMTP_PASSWORD:=}"

    HELM_SET_FLAGS+=(
        --set postgresql.auth.password="${PG_PASSWORD}"
        --set postgresql.auth.postgresPassword="${PG_ADMIN_PASSWORD}"
        --set database.password="${DB_PASSWORD}"
        --set apiConnections.openKlant.apiKey="${OPENKLANT_API_KEY}"
        --set apiConnections.object.apiKey="${OBJECT_API_KEY}"
        --set apiConnections.zaakSysteem.key="${ZAAKSYSTEEM_KEY}"
        --set web.oidc.clientSecret="${ITA_CLIENT_SECRET}"
    )

    if [[ -n "${POLLER_SMTP_PASSWORD}" ]]; then
        HELM_SET_FLAGS+=(--set poller.smtp.password="${POLLER_SMTP_PASSWORD}")
    fi
}

# Function to check if namespace exists
check_namespace() {
    if kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
        print_success "Namespace '$NAMESPACE' exists"
    else
        print_status "Creating namespace '$NAMESPACE'"
        kubectl create namespace "$NAMESPACE"
        print_success "Namespace '$NAMESPACE' created"
    fi
}

# Function to deploy PostgreSQL first
deploy_postgresql() {
    print_status "Deploying PostgreSQL first..."
    
    helm upgrade --install "$RELEASE_NAME" "$CHART_URL" \
        --version "$CHART_VERSION" \
        --namespace "$NAMESPACE" \
        --values "$VALUES_FILE" \
        "${HELM_SET_FLAGS[@]}" \
        --wait \
        --timeout 10m
    
    print_success "ITA with PostgreSQL deployed successfully"
}

# Function to wait for PostgreSQL to be ready
wait_for_postgresql() {
    print_status "Waiting for PostgreSQL to be ready..."
    
    # Wait for PostgreSQL pod to be running
    kubectl wait --for=condition=ready pod \
        -l app.kubernetes.io/name=postgresql -n "$NAMESPACE" --timeout=300s
    
    # Wait for PostgreSQL service to be available
    kubectl wait --for=condition=ready pod \
        -l app.kubernetes.io/component=primary -n "$NAMESPACE" --timeout=300s
    
    # Get the actual PostgreSQL service name
    POSTGRES_SERVICE=$(kubectl get svc -n "$NAMESPACE" \
        -l app.kubernetes.io/name=postgresql \
        -o jsonpath='{.items[0].metadata.name}')
    print_status "PostgreSQL service name: $POSTGRES_SERVICE"
    
    print_success "PostgreSQL is ready"
}

# Function to run database initialization
run_db_init() {
    print_status "Running database initialization..."
    
    # Clean up any existing failed jobs
    if kubectl get job ita-db-init -n "$NAMESPACE" >/dev/null 2>&1; then
        print_status "Cleaning up existing database initialization job..."
        kubectl delete job ita-db-init -n "$NAMESPACE"
        sleep 5
    fi
    
    # Get the actual PostgreSQL service name
    POSTGRES_SERVICE=$(kubectl get svc -n "$NAMESPACE" \
        -l app.kubernetes.io/name=postgresql \
        -o jsonpath='{.items[0].metadata.name}')
    print_status "Using PostgreSQL service: $POSTGRES_SERVICE"
    
    
    # Apply the database initialization job with the correct service name
    TMP_JOB_MANIFEST=$(mktemp)
    awk -v host="$POSTGRES_SERVICE" -v dbpw="${DB_PASSWORD}" -v pgpw="${PG_ADMIN_PASSWORD}" '
      /name: DB_HOST/ { print; getline; sub(/value: ".*"/, "value: \"" host "\""); print; next }
      /name: DB_PASSWORD/ { print; getline; sub(/value: ".*"/, "value: \"" dbpw "\""); print; next }
      /name: POSTGRES_PASSWORD/ { print; getline; sub(/value: ".*"/, "value: \"" pgpw "\""); print; next }
      { print }
    ' charts/beproeving/db-init-job.yaml > "$TMP_JOB_MANIFEST"

    kubectl apply -f "$TMP_JOB_MANIFEST"
    rm -f "$TMP_JOB_MANIFEST"
    
    # Wait for the job to complete
    print_status "Waiting for database initialization to complete..."
    kubectl wait --for=condition=complete job/ita-db-init -n "$NAMESPACE" \
        --timeout=300s
    
    # Check if the job was successful
    if kubectl get job/ita-db-init -n "$NAMESPACE" \
        -o jsonpath='{.status.succeeded}' | grep -q "1"; then
        print_success "Database initialization completed successfully"
    else
        print_error "Database initialization failed"
        print_status "Job logs:"
        kubectl logs job/ita-db-init -n "$NAMESPACE"
        print_status "Job status:"
        kubectl describe job ita-db-init -n "$NAMESPACE"
        print_status "Pod logs:"
        kubectl logs -l app=ita-db-init -n "$NAMESPACE" --tail=50
        exit 1
    fi
}

# Function to deploy ITA application
deploy_ita() {
    print_status "Deploying ITA application..."
    
    # Deploy the full ITA application
    helm upgrade --install "$RELEASE_NAME" "$CHART_URL" \
        --version "$CHART_VERSION" \
        --namespace "$NAMESPACE" \
        --values "$VALUES_FILE" \
        "${HELM_SET_FLAGS[@]}" \
        --wait \
        --timeout 10m
    
    print_success "ITA application deployed successfully"
}

# Function to show deployment status
show_status() {
    print_status "Deployment completed! Checking status..."
    
    echo ""
    echo "📊 Deployment Status:"
    echo "====================="
    
    # Show pods
    echo ""
    echo "🔍 Pods:"
    kubectl get pods -n "$NAMESPACE" \
        -l app.kubernetes.io/instance="$RELEASE_NAME"
    
    # Show services
    echo ""
    echo "🌐 Services:"
    kubectl get svc -n "$NAMESPACE" \
        -l app.kubernetes.io/instance="$RELEASE_NAME"
    
    # Show jobs
    echo ""
    echo "⚙️  Jobs:"
    kubectl get jobs -n "$NAMESPACE" -l app=ita-db-init
    
    echo ""
    print_success "ITA is ready! You can now set up port forwarding:"
    echo "  kubectl port-forward -n $NAMESPACE svc/ita-web-svc 3000:80"
    echo ""
    echo "Then access ITA at: http://localhost:3000"
}

# Main deployment process
main() {
    print_status "Starting ITA deployment with database initialization..."
    
    # Build helm flags from environment and validate presence of required vars
    build_helm_set_flags
    
    # Step 1: Check/create namespace
    check_namespace
    
    # Step 2: Deploy PostgreSQL first
    deploy_postgresql
    
    # Step 3: Wait for PostgreSQL to be ready
    wait_for_postgresql
    
    # Step 4: Run database initialization
    run_db_init
    
    # Step 5: Deploy ITA application
    deploy_ita
    
    # Step 6: Show status
    show_status
}

# Run main function
main "$@"
