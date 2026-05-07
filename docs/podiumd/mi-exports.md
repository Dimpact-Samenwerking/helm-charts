# MI exports — weekly database dumps to blob storage

Weekly Management Information (MI) data exports of every Postgres-backed component the PodiumD chart deploys, written directly to Azure Blob Storage. Designed for downstream consumers (gemeentes, analytics teams) that need a regular snapshot of the operational data.

> Jira: [IN-1650](https://dimpact.atlassian.net/browse/IN-1650) (epic) / [IN-1691](https://dimpact.atlassian.net/browse/IN-1691) (iteration 1).

## Audience

Two readers:
- **PodiumD operators** running the chart in any environment — to enable, configure, validate and consume exports.
- **External hosting providers** who run PodiumD in production via their own Terraform — to see what cloud-side prerequisites the chart needs.

Test/dev infra in `ICATT-Menselijk-Digitaal/podiumd-infra` provisions these prerequisites for our own jim00/jos00/etc. clusters. Production-hosted environments must replicate the same shape using their own Terraform module — see [§ Production / external hosting](#production--external-hosting).

## How it works

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                       AKS cluster — namespace: podiumd                        │
│                                                                              │
│   ┌─────────────────────────┐     ┌──────────────────────────────────────┐  │
│   │  CronJob                │     │  Postgres (flexible-server)          │  │
│   │  mi-export-<component>  │ ──► │  database: <component>               │  │
│   │  (one per enabled       │     │                                      │  │
│   │   Postgres component)   │     └──────────────────────────────────────┘  │
│   │                         │                                                │
│   │  schedule: 0 2 * * 0    │     ┌──────────────────────────────────────┐  │
│   │  (Sun 02:00 NL time)    │ ──► │  K8s Secret: mi-export-storage       │  │
│   │                         │     │  (SA name + key + container name)    │  │
│   │  envFrom:               │     └────────────────┬─────────────────────┘  │
│   │   - mi-export-storage   │                      │                         │
│   │   - <component> Secret  │                      ▼                         │
│   │   - <component> CM      │     ┌──────────────────────────────────────┐  │
│   │                         │     │  Azure Storage Account               │  │
│   │  ConfigMap:             │     │  podiumd<env>st                      │  │
│   │   mi-export-scripts     │     │                                      │  │
│   │   (dump.sh)             │ ──► │  Container: mi-exports               │  │
│   │                         │     │   <gemeente>/<YYMMDD>/<component>/   │  │
│   └─────────────────────────┘     │     <HHMMSS>-<component>.tar.gz      │  │
│                                   │     (or .pgdump)                     │  │
│                                   └──────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

Each CronJob:
1. Reads its target component's existing `<component>` Secret + ConfigMap (DB host, port, name, user, password — same secrets the app pods consume).
2. Reads the env's storage credentials from the K8s `Secret/mi-export-storage` (SA name, SA key, container name).
3. Runs `dump.sh` in the chart's `mi-export-scripts` ConfigMap.
4. Writes the result as a single blob.

## Output format

Selected env-wide via `mi.format`. **All targets in a given environment use the same format** — there is no per-target override.

| `mi.format` | Tool | Output | Use case |
|---|---|---|---|
| `csv` *(default)* | `psql \COPY` per table | One `.tar.gz` per component, containing one CSV per table | Analytics consumers (Excel, pandas, ingest pipelines) |
| `pgdump` | `pg_dump -Fc --no-owner --no-privileges` per database | One `.pgdump` per component (custom format, zlib-compressed) | DR / cluster migration / point-in-time `pg_restore` |

Both formats honour `mi.targets[].schemas` (default `["public"]`; `zac` overrides to `["flowable"]`).

### Blob layout

```
<container>/<gemeente>/<YYMMDD>/<component>/<HHMMSS>-<component>.<ext>
```

A single timestamp is captured at script start, so every blob from one CronJob run shares the same `<HHMMSS>` prefix and lands under the same date directory. Examples:

```
mi-exports/jim00/260507/openzaak/095048-openzaak.tar.gz
mi-exports/jim00/260507/openzaak/095048-openzaak.pgdump
mi-exports/jim00/260507/objecten/091200-objecten.tar.gz
```

## Activation in an environment

### 1. Cloud prerequisites (once per env)

Before enabling the chart feature, the env's cloud must already have:

- A storage container named **`mi-exports`** in the env's standard storage account (`podiumd<env>st`). No new SA is required; **do not** create a dedicated SA.
- The SA's primary access key stored in the base Key Vault as a secret named **`mi-export-storage-<env>`**. The chart uses storage-account-key auth, **not** workload identity (decision recorded in [§ Why SA keys, not workload identity](#why-sa-keys-not-workload-identity)).
- A K8s `Secret/mi-export-storage` in the `podiumd` namespace with three keys:
  - `AZURE_STORAGE_ACCOUNT` (e.g. `podiumdjim00st`)
  - `AZURE_STORAGE_KEY` (the value from KV)
  - `AZURE_STORAGE_CONTAINER` (e.g. `mi-exports`)

For test/dev envs (jim00, jos00, …): the `podiumd-infra` repo ships a script `scripts/sync-mi-export-secret.sh` that reads the KV secret and creates the K8s Secret. Run it once after a fresh app install.

For production-hosted envs: see [§ Production / external hosting](#production--external-hosting).

### 2. Enable in `values-<env>.yml`

Minimum:

```yaml
mi:
  enabled: true
  gemeente: <env-name>   # used as the top-level path prefix in the blob layout
```

Defaults: weekly schedule (Sunday 02:00 Europe/Amsterdam), `csv` format, all 14 default targets. A target only renders a CronJob when the corresponding `<component>.enabled` is `true` elsewhere in the env's values, so disabling a component automatically removes its export.

To switch the env to full database dumps:

```yaml
mi:
  enabled: true
  gemeente: <env-name>
  format: pgdump
```

Other knobs (chart defaults shown):

```yaml
mi:
  enabled: true
  gemeente: <env-name>
  format: csv                       # csv | pgdump
  schedule: "0 2 * * 0"             # weekly Sun 02:00
  timeZone: "Europe/Amsterdam"
  concurrencyPolicy: Forbid         # don't overlap runs
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  ttlSecondsAfterFinished: 86400    # auto-clean Job + pod after 24h
  storage:
    secretName: mi-export-storage   # name of the K8s Secret
```

### 3. Trim or override the target list (optional)

The chart's default `mi.targets[]` covers all 14 Postgres-backed components. You typically don't need to touch it — let `<component>.enabled` drive what's exported. If you need to override (e.g. override schemas for a custom component):

```yaml
mi:
  targets:
    - component: openzaak
    - component: zac
      schemas: ["flowable"]    # zac uses Flowable schema, not public
    - component: openklant
      enabled: false           # ad-hoc opt-out for this env only
    - component: opennotificaties
      secretName: notificaties # override when subchart key ≠ resource name
      configMapName: notificaties
```

### 4. Validation

After the next chart apply:

```bash
# Should list one CronJob per enabled component
kubectl -n podiumd get cronjob -l app.kubernetes.io/component=mi-export

# Trigger an out-of-schedule run for one component
kubectl -n podiumd create job --from=cronjob/mi-export-openzaak mi-test-now

# Watch
kubectl -n podiumd logs -l job-name=mi-test-now -f --tail=50

# Verify the blob landed
SA_KEY=$(az keyvault secret show --vault-name <base-kv-name> \
           --name mi-export-storage-<env> --query value -o tsv)
az storage blob list \
  --account-name podiumd<env>st \
  --account-key  "${SA_KEY}" \
  --container-name mi-exports \
  --prefix "<env>/$(date -u +%y%m%d)/openzaak/" -o table
```

A successful CSV run logs e.g.:

```
[ts] starting MI export: component=openzaak schemas=public format=csv
[ts] dumping public.zaken_zaak -> zaken_zaak.csv
... (one line per table)
[ts] packaging 127 CSV(s) into openzaak.tar.gz
[ts] uploading <env>/260507/openzaak/095048-openzaak.tar.gz (482658 bytes)
[ts] done: 127 table(s) packaged in <env>/260507/openzaak/095048-openzaak.tar.gz
```

A successful pgdump run logs:

```
[ts] starting MI export: component=openzaak schemas=public format=pgdump
[ts] running pg_dump -Fc on openzaak (schemas: public)
[ts] uploading <env>/260507/openzaak/095048-openzaak.pgdump (533748 bytes)
[ts] done: pg_dump uploaded to <env>/260507/openzaak/095048-openzaak.pgdump
```

## Production / external hosting

The Terraform in `ICATT-Menselijk-Digitaal/podiumd-infra` is **only for Dimpact's test/dev environments** (jim00, jos00, jimme00, etc.). Production environments hosted by external providers (e.g. SSC Twente — `dev.azure.com/ssctwente/ExternalsPodiumD`) need to replicate the same shape in their own Terraform module.

### What the hosting provider must add

The cloud-side prerequisites in [§ Cloud prerequisites](#1-cloud-prerequisites-once-per-env) — `mi-exports` blob container on the existing per-env standard SA, the SA primary key stored in the base Key Vault as `mi-export-storage-<env>`, and the cluster-side `Secret/mi-export-storage` materialised before the chart is installed.

For SSC Twente's hosted environments, the Terraform module that already provisions the storage account and Key Vault is in `dev.azure.com/ssctwente/_git/ExternalsPodiumD`. The corresponding changes there land in branch `feature/IN-1691-mi-exports-storage` (matching the Jira ticket [IN-1691](https://dimpact.atlassian.net/browse/IN-1691)) and add:

1. The `mi-exports` blob container resource on the existing per-env SA.
2. A `keyvault_secret` for the SA primary key, named `mi-export-storage-<env>`.
3. A pipeline step that reads that KV secret at deploy time and creates the in-cluster `Secret/mi-export-storage` in the `podiumd` namespace before the helm install runs.

The chart itself is hosting-provider-agnostic — it only needs the three envvars in `Secret/mi-export-storage` to be present at install time. **Any** provisioning approach that delivers that secret with the right values works.

### What the hosting provider does *not* need

- **No Workload Identity / federated credentials.** SA-key auth was chosen deliberately (see decision below).
- **No SFTP / file share.** Blob is the only export sink.
- **No new identity / RBAC** beyond access to the existing per-env SA's key.

## Why SA keys, not workload identity

Decision recorded during the iter1 design phase:

- The export workload is a single-purpose batch job that needs only "write to one container in one SA". Wiring up federated credentials, role assignments, and identity bindings adds operational surface for no functional gain.
- The SA primary key already lives in the base Key Vault; rotation of the key automatically refreshes the cached K8s Secret on the next deploy / sync run.
- Workload Identity may be revisited if/when a future iteration needs cross-tenant access or fine-grained per-component credentials.

## Operations

### Reading the blobs

For consumers with the SA key (or a SAS token issued from it):

```bash
# List all of today's exports for an env
az storage blob list --account-name podiumd<env>st \
  --account-key "${SA_KEY}" \
  --container-name mi-exports \
  --prefix "<env>/$(date -u +%y%m%d)/" -o table

# Download a single component's tarball
az storage blob download --account-name podiumd<env>st \
  --account-key "${SA_KEY}" \
  --container-name mi-exports \
  --name "<env>/260507/openzaak/095048-openzaak.tar.gz" \
  --file ./openzaak.tar.gz

# Inspect the CSVs without extracting
tar -tzf ./openzaak.tar.gz | head

# For a pgdump file: list its TOC
pg_restore --list ./openzaak.pgdump | head
```

> **Version note:** `pg_dump`/`pg_restore` in the chart's image (Azure Linux base + tdnf-installed `postgresql`) is currently PG16. A pgdump file written by PG16 cannot be read by older `pg_restore` clients — match the consumer's client version to PG16+ when restoring.

### Retention

The chart **does not** enforce retention on the blobs themselves; that's the SA's lifecycle-management policy. See the Terraform snippet above for a 30d-Cool / 365d-Archive default. Choose a `delete_after_days_…` value consistent with the gemeente's data-retention policy (typically 5 years for case-related data).

### Run-success monitoring

Iter1 ships **without** alerting. The CronJob's standard Job/Pod failure events surface in `kubectl get events -n podiumd`. A future iteration (IN-1993) wires up Prometheus alerting on missed schedules / failed runs.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `helm template` fails with `mi.format must be one of: csv, pgdump (got "X")` | Typo in `values-<env>.yml` | Set `mi.format` to `csv` or `pgdump` (or remove to use default `csv`). |
| Job pod fails with `ERROR: AZURE_STORAGE_KEY: must be set` | `Secret/mi-export-storage` not present in podiumd ns | Run `scripts/sync-mi-export-secret.sh <env>` (test/dev) or apply the Secret manually (see [§ Production / external hosting](#production--external-hosting)). |
| Job pod fails with `password authentication failed for user "<component>"` | The component's K8s Secret has a stale password (env was rebuilt but Secret wasn't refreshed) | Re-run the deploy pipeline's "Create PostgreSQL Databases and Users" step; or `kubectl delete secret/<component> -n podiumd` and let the chart recreate it. |
| `csv` run logs `no tables found in schemas (...)` then exits 1 | Component's DB exists but has no tables (chart was deployed but the component's migration never ran) | Investigate the component's startup; the export script intentionally fails rather than upload an empty tarball. |
| pgdump file rejected by `pg_restore` with `unsupported version (1.15)` | Consumer's PG client is older than PG16 | Use a PG16+ client to restore. |
| All Jobs fire on the same minute on a large cluster and overload the SA | Default schedule is weekly Sunday 02:00 across all components | Stagger via per-target `schedule` overrides (chart values), or ask Azure for higher SA throughput tier. |

## Changelog

- **Iter1 (chart 4.6.x onwards)** — initial dump-to-blob, `csv`/`pgdump` env-wide knob, structured blob layout, gated per-component CronJobs.
- **Iter2** *(not started)* — Keycloak-fronted web portal so consumers can browse/download without an SAS link.
- **Iter3** ([IN-1993](https://dimpact.atlassian.net/browse/IN-1993)) — baked image (drop runtime `tdnf install`); SA lifecycle policy automation; Prometheus alerts on missed/failed runs; `ephemeral-storage` limits to bound /tmp use; per-table allow/deny lists.
