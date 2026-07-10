# Migrating to Keycloak Operator

This guide explains how to migrate from the Bitnami Keycloak chart to the Hostzero Keycloak Operator.

## Overview

The PodiumD Helm chart is transitioning from:
- **Old**: Bitnami Keycloak chart (with Infinispan dependency)
- **New**: Hostzero Keycloak Operator (manages Keycloak instances via CRDs)

**Benefits of Keycloak Operator:**
- GitOps-friendly configuration via Custom Resources
- Automatic secret synchronization
- Drift detection
- Better support for Keycloak 20-26+
- Cleaner upgrade path

## Prerequisites

⚠️ **Important**: This migration involves downtime but does **NOT** affect realm configurations or user data stored in the database.

**What this migration does:**
- Removes old Keycloak and Infinispan Kubernetes resources (pods, services, PVCs)
- Installs the Keycloak Operator
- Creates new Keycloak instances managed by the operator

**What remains intact:**
- ✅ **Realm configurations** (stored in PostgreSQL database)
- ✅ **User data** (stored in PostgreSQL database)
- ✅ **Client configurations** (stored in PostgreSQL database)
- ✅ **Identity provider settings** (stored in PostgreSQL database)

The new Keycloak instance will connect to the **same PostgreSQL database** and will automatically have access to all existing realms, users, and configurations.

**Required:**
1. **Ensure database backups are in place** (assume regular backups are already configured)
2. **Verify database connection details** for the new Keycloak instance
3. **Plan for downtime** during the migration window

## Migration Steps

### Step 1: Cleanup Old Resources

The legacy Bitnami Keycloak and Infinispan (ispn) resources must be removed before installing the operator.

⚠️ **Note**: This cleanup removes Kubernetes resources only. Your database (realm configs, users, etc.) remains untouched.

**Run the cleanup script:**

```bash
# Set your namespace and release name
export NAMESPACE=<your-namespace>
export RELEASE_NAME=podiumd

# Make the script executable
chmod +x scripts/cleanup-keycloak-infinispan.sh

# Run the cleanup script
./scripts/cleanup-keycloak-infinispan.sh
```

The script will remove:
- Keycloak StatefulSets, Services, ConfigMaps, and Secrets
- Infinispan (ispn) StatefulSets, Services, ConfigMaps, Secrets, and PVCs

For details on what the script does, see `scripts/cleanup-keycloak-infinispan.sh`.

### Step 2: Update Your values.yaml

Disable the old charts and enable the operator:

```yaml
keycloak:
  enabled: false

infinispan:
  enabled: false

keycloak-operator:
  enabled: true
  # Add your keycloak-operator configuration here
```

### Step 3: Update Dependencies

```bash
helm dependency update
```

### Step 4: Deploy with Keycloak Operator

```bash
helm upgrade --install podiumd . -f values.yaml -n <namespace>
```

### Step 5: Verify Keycloak Operator Deployment

After the operator is installed, it will create a Keycloak custom resource based on your `values.yaml` configuration.

**Important**: Ensure your values.yaml database configuration points to your **existing PostgreSQL database** that contains your realm configurations and user data. The Keycloak custom resource will be automatically created by the PodiumD Helm chart.

### Step 6: Verify Keycloak Startup

Once the new Keycloak pods are running, verify they can connect to the database:

```bash
# Check pod status
kubectl get pods -n <namespace> -l app=keycloak

# Check logs for successful database connection
kubectl logs -n <namespace> -l app=keycloak --tail=100

# Access Keycloak and verify realms are present
# Your existing realms, users, and configurations should be immediately available
```

**No data import is needed** - the new Keycloak instance will automatically read all existing data from the PostgreSQL database.

## Realm Import Functionality

⚠️ **Note**: The Bitnami Keycloak chart included automatic realm import functionality via the `keycloak.extraStartupArgs` parameter. This functionality is **not yet implemented** in the keycloak-operator configuration.

**Current status:**
- Realm import will be implemented in a future release
- For now, manage realm configurations manually through the Keycloak Admin Console or via the Keycloak API
- Existing realms in the database will continue to work without any changes

**Workaround for new realms:**
If you need to import realm configurations, you can do so manually:
```bash
kubectl exec -n <namespace> <keycloak-pod> -- /opt/keycloak/bin/kc.sh import --file /path/to/realm.json
```

## Service Name Considerations

⚠️ **Service Name Conflicts**: If your applications reference a specific Keycloak service name (e.g., `keycloak-service`), you may need to:

1. **Update application configurations** to use the new service name created by the operator
2. **Configure the operator** to create a service with your desired name
3. **Create a Service alias** (additional Service pointing to the same endpoints)

The keycloak-operator typically creates services following its own naming convention. Check the operator documentation for service naming configuration options.

## Rollback Plan

If issues arise during migration:

1. **Disable keycloak-operator:**
   ```yaml
   keycloak-operator:
     enabled: false
   ```

2. **Re-enable legacy charts:**
   ```yaml
   keycloak:
     enabled: true
   infinispan:
     enabled: true
   ```

3. **Redeploy:**
   ```bash
   helm upgrade --install podiumd . -f values.yaml -n <namespace>
   ```

4. **Verify database connectivity** - Keycloak will reconnect to the same database with all existing data

## Troubleshooting

### Operator not creating resources

Check operator logs:
```bash
kubectl logs -n <namespace> -l app.kubernetes.io/name=keycloak-operator
```

### Database connection issues

Verify database credentials and connectivity:
```bash
kubectl get secret keycloak-db-secret -n <namespace> -o yaml
```

### Service not accessible

Check Keycloak CR status:
```bash
kubectl get keycloak -n <namespace> -o yaml
```

## References

- [Keycloak Operator Documentation](https://keycloak-operator.hostzero.com/)
- [Keycloak Operator GitHub](https://github.com/Hostzero-GmbH/keycloak-operator)
- [Keycloak Official Documentation](https://www.keycloak.org/documentation)
