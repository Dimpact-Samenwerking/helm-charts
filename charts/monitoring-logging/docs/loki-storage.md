# Loki Storage — Production Setup

The chart ships with embedded **MinIO** as the object store. This is suitable for development and testing only. For production on AKS, switch to **Azure Blob Storage**.

---

## Current state (dev/test)

| Setting | Value |
|---|---|
| Object store | MinIO (single-node, in-cluster) |
| PVC size | 20Gi |
| Storage class | `managed-csi` (Azure disk) |
| Schema `object_store` | `s3` (MinIO is S3-compatible) |

**Why this is not production-ready:**
- MinIO is a single pod — any restart loses in-flight chunks until they are flushed
- 20Gi fills up quickly under real workloads (30-day retention + distributed mode)
- `managed-csi` (Azure managed disk) is block storage — lower throughput and higher cost per GB than Azure Blob

---

## Production: Azure Blob Storage

### 1. Create Azure resources

```bash
# Storage account — ZRS for zone-redundant HA (recommended), LRS for single-zone
az storage account create \
  --name <storage-account> \
  --resource-group <rg> \
  --location <region> \
  --sku Standard_ZRS \
  --kind StorageV2 \
  --access-tier Hot

# Blob container
az storage container create \
  --name loki \
  --account-name <storage-account>
```

### 2. Choose an authentication method

| Method | When to use |
|---|---|
| **Workload Identity** (recommended) | AKS with OIDC issuer + workload identity enabled |
| Storage account key | Simpler; acceptable if secret rotation is managed |

#### Option A — Workload Identity (recommended for AKS)

```bash
# Create managed identity
az identity create --name loki-storage --resource-group <rg>

# Grant Storage Blob Data Contributor on the storage account
az role assignment create \
  --assignee <identity-client-id> \
  --role "Storage Blob Data Contributor" \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<storage-account>

# Federate with the Loki service accounts (ingester, querier, compactor, etc.)
# Repeat for each Loki component service account that writes to object storage:
az identity federated-credential create \
  --name loki-ingester \
  --identity-name loki-storage \
  --resource-group <rg> \
  --issuer <aks-oidc-issuer> \
  --subject system:serviceaccount:<monitoring-ns>:<release>-loki-ingester
```

Then add to `values-monitoring.yaml`:

```yaml
loki:
  serviceAccount:
    annotations:
      azure.workload.identity/client-id: "<identity-client-id>"

  loki:
    storage:
      type: azure
      azure:
        accountName: "<storage-account>"
        useFederatedToken: true
        container: loki
      object_store:
        type: azure
        azure:
          accountName: "<storage-account>"
          useFederatedToken: true
```

#### Option B — Storage account key

Create the secret:

```bash
kubectl create secret generic loki-azure-storage \
  --namespace <monitoring-ns> \
  --from-literal=accountKey="$(az storage account keys list \
      --account-name <storage-account> \
      --query '[0].value' -o tsv)"
```

Then add to `values-monitoring.yaml`:

```yaml
loki:
  loki:
    extraEnv:
      - name: AZURE_STORAGE_ACCOUNT_KEY
        valueFrom:
          secretKeyRef:
            name: loki-azure-storage
            key: accountKey

    storage:
      type: azure
      azure:
        accountName: "<storage-account>"
        accountKey: "${AZURE_STORAGE_ACCOUNT_KEY}"
        container: loki
      object_store:
        type: azure
        azure:
          accountName: "<storage-account>"
          accountKey: "${AZURE_STORAGE_ACCOUNT_KEY}"
```

### 3. Update schema and disable MinIO

Add to `values-monitoring.yaml`:

```yaml
loki:
  minio:
    enabled: false   # disable embedded MinIO

  loki:
    schemaConfig:
      configs:
        - from: 2024-04-01
          store: tsdb
          object_store: azure   # was: s3
          schema: v13
          index:
            prefix: loki_index_
            period: 24h

    compactor:
      delete_request_store: azure   # was: s3
      # other compactor settings are inherited from chart defaults
```

---

## Sizing guidance

| Workload | Estimated daily ingestion | Recommended retention | Blob storage / month |
|---|---|---|---|
| Dev/test | < 1 GB/day | 7 days | < 10 GB |
| Small prod (≤ 10 services) | 1–5 GB/day | 30 days | ~75–150 GB |
| Full PodiumD prod | 5–20 GB/day | 30 days | ~150–600 GB |

Azure Blob (Hot, LRS) costs roughly €0.018/GB/month — budget accordingly.

Set retention in `values-monitoring.yaml` to match your requirements:

```yaml
loki:
  loki:
    limits_config:
      retention_period: 30d   # adjust per environment
      max_query_lookback: 30d
```

---

## Checklist

- [ ] Storage account created (ZRS recommended)
- [ ] Blob container `loki` created
- [ ] Authentication configured (workload identity or key secret)
- [ ] `minio.enabled: false` in `values-monitoring.yaml`
- [ ] `object_store: azure` + `compactor.delete_request_store: azure` set
- [ ] Retention period set to match environment requirements
- [ ] Ingester PVCs resized or removed (distributed mode uses object store, not PVCs)
