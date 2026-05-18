# Upgrade guide: PodiumD 4.7.0 → 4.7.1

## Changes

### Patch version for IA

Version of ITA goes from 3.0.0 to 3.1.0

#### Action required

No action required.

### Open Zaak sub-chart 1.13.1 → 1.14.1

The Open Zaak sub-chart is bumped from `1.13.1` to `1.14.1` (sub-chart
default `appVersion` moves 1.26.0 → 1.28.1; PodiumD keeps the Open Zaak
**application image pinned at 1.27.1**, so the running app version does
not change in this release).

Chart 1.14.1 introduces a configurable **Documenten API storage backend**.
PodiumD does not set any of these keys, so the chart defaults apply and
behaviour is unchanged after the upgrade (documents keep using the
existing `filesystem` backend, Cloud Events stay disabled).

#### New configuration options

These are exposed under the `openzaak:` key in `values.yaml` and may be
useful for production environments that want object storage instead of a
filesystem PersistentVolume for Documenten API files:

| Key | Default | Purpose |
|---|---|---|
| `openzaak.documentApiBackend` | `filesystem` | Storage backend for the Documenten API. One of: `filesystem`, `azure_blob_storage`, `s3_storage`. |
| `openzaak.azureBlobStorage.accountName` | `""` | Azure Storage account name. |
| `openzaak.azureBlobStorage.clientId` | `""` | Entra ID client id (workload identity / service principal). |
| `openzaak.azureBlobStorage.clientSecret` | `""` | Entra ID client secret. |
| `openzaak.azureBlobStorage.tenantId` | `""` | Entra ID tenant id. |
| `openzaak.azureBlobStorage.container` | `openzaak` | Blob container name. |
| `openzaak.azureBlobStorage.location` | `documenten` | Path/prefix within the container. |
| `openzaak.azureBlobStorage.connectionTimeout` | `5` | Connection timeout (seconds). |
| `openzaak.azureBlobStorage.apiStorageVersion` | `""` | Pin a specific Azure Storage API version (optional). |
| `openzaak.azureBlobStorage.urlExpirationTime` | `60` | Signed-URL expiry (seconds). |
| `openzaak.s3storage.accessKeyId` | `""` | S3 access key id. |
| `openzaak.s3storage.secretAccessKey` | `""` | S3 secret access key. |
| `openzaak.s3storage.storageBucketName` | `openzaak` | S3 bucket name. |
| `openzaak.s3storage.maxMemorySize` | `0` | Max in-memory size before spooling to disk (bytes; `0` = default). |
| `openzaak.s3storage.querystringExpire` | `60` | Signed-URL expiry (seconds). |
| `openzaak.s3storage.fileOverwrite` | `false` | Allow overwriting an existing object with the same key. |
| `openzaak.s3storage.location` | `documenten/` | Key prefix within the bucket. |
| `openzaak.s3storage.regionName` | `""` | S3 region. |
| `openzaak.s3storage.endpointUrl` | `""` | Custom S3 endpoint (for non-AWS / S3-compatible stores). |
| `openzaak.s3storage.customDomain` | `""` | Custom domain used when generating object URLs. |
| `openzaak.enableCloudEvents` | `false` | Emit CloudEvents for Documenten API changes. |
| `openzaak.notificationsSource` | `openzaak` | `source` attribute on emitted CloudEvents. |

#### Action required

None to stay on the current behaviour — leave these keys unset and the
`filesystem` backend continues to be used.

> **WARNING — backend migration must be investigated and performed
> first.** Switching `openzaak.documentApiBackend` away from
> `filesystem` to `azure_blob_storage` or `s3_storage` does **not**
> migrate existing documents. Files already written to the filesystem
> PersistentVolume will become **inaccessible** to the Documenten API
> the moment the backend is changed, and newly stored files go only to
> the new backend. Before flipping the backend in production you MUST:
>
> 1. Investigate the current document volume (count, total size, PV
>    contents) and the target object-store capacity/permissions.
> 2. Plan and validate a data-migration path that copies all existing
>    Documenten API files from the filesystem PV into the target
>    Azure Blob / S3 location, preserving the keys/paths Open Zaak
>    expects.
> 3. Execute and verify the migration (read-back checks) in a
>    non-production environment first.
> 4. Only then change `openzaak.documentApiBackend` and roll out, with
>    a tested rollback (keep the filesystem PV until the new backend is
>    confirmed good).
>
> Do not change the backend as part of a routine 4.7.0 → 4.7.1 upgrade.
> Treat it as a separate, planned migration project.
