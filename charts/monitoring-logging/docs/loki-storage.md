# Loki Storage — Production Setup

The chart ships with embedded **MinIO** as the object store. This is suitable for development and testing only. For production on AKS, switch to **Azure Blob Storage**.

---

## Current state (dev/test)

| Setting | Value |
|---|---|
| Object store | MinIO (single pod, 2x 20Gi drives, erasure coding) |
| PVCs | `export-0` + `export-1` — 20Gi each (`managed-csi`) |
| Storage class | `managed-csi` (Azure disk) |
| Schema `object_store` | `s3` (MinIO is S3-compatible) |

MinIO mounts 2 drives and uses erasure coding — losing one drive does **not** lose data. However, it runs as a **single pod** (`monitoring-minio-0`): if that pod is unavailable, Loki ingesters cannot flush chunks. In-memory chunks are protected by the ingester WAL (3 zone-aware replicas), but any prolonged MinIO downtime blocks writes to storage.

**Why this is still not production-ready:**
- Single pod = availability risk (no MinIO HA / distributed mode)
- 2x 20Gi = 40Gi total raw; erasure coding gives ~20Gi usable — will fill under real 30-day retention
- `managed-csi` (Azure disk) has lower throughput than Azure Blob for this access pattern
- No automated backup of the MinIO volumes

---

## Option A — HA MinIO (test/staging clusters)

If switching to Azure Blob is not yet feasible, MinIO can be made pod-HA by running in distributed mode. MinIO requires a minimum of **4 drives total** (`replicas × drivesPerNode ≥ 4`) for distributed erasure coding.

```yaml
# values-monitoring.yaml
loki:
  minio:
    replicas: 2        # 2 pods × 2 drives = 4 drives total
    drivesPerNode: 2   # EC:2 — survives loss of 1 pod or 2 drives simultaneously
    persistence:
      storageClass: managed-csi
      size: 20Gi       # per drive — 4× 20Gi = 80Gi raw, ~40Gi usable after parity
```

> Alternatively `replicas: 4, drivesPerNode: 1` spreads across 4 pods (survives 2 simultaneous pod losses) at the cost of 4 separate disks.

This is sufficient for test-rig and development clusters. For real gemeente production deployments, use Azure Blob Storage (Option B below).

---

## Option B — Azure Blob Storage (production)

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
