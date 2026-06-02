# MI exports — weekly database dumps to SFTP

Weekly Management Information (MI) data exports of every Postgres-backed component the PodiumD chart deploys, uploaded over **SFTP** to an external server. Designed for downstream consumers (gemeentes, analytics teams) that need a regular snapshot of the operational data.

> Jira: [IN-1650](https://dimpact.atlassian.net/browse/IN-1650) (epic) / [IN-1691](https://dimpact.atlassian.net/browse/IN-1691) (iter 1 — dump generator) / [IN-2119](https://dimpact.atlassian.net/browse/IN-2119) (egress switched from Azure Blob to SFTP, CSV separator `;`).

> **⚠️ Opt-in feature — disabled by default.** Set `mi.enabled: true` in your env values file to turn it on. The chart renders the SFTP Secrets (`mi-export-sftp` + `mi-export-sftp-key`) itself from the `mi.sftp.*` values — nothing is pre-provisioned. You only need a reachable SFTP server with the gemeente's public key installed, and the SSH private key supplied via `mi.sftp.privateKey` (the ExternalsPodiumD `application.yml` pipeline substitutes it from Key Vault at deploy time). See [§ Activation in an environment](#activation-in-an-environment).

## Audience

**PodiumD operators** running the chart via the `ExternalsPodiumD` `application.yml` pipeline — to enable, configure, validate and consume exports. The chart renders the SFTP Secrets from values, so the only out-of-band prerequisites are a reachable SFTP server and the SSH private key in Key Vault (see [§ Deployment](#deployment)).

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
│   │  (Sun 02:00 NL time)    │ ──► │  K8s Secret: mi-export-sftp          │  │
│   │                         │     │  (SFTP_HOST/PORT/USER/REMOTE_PATH)   │  │
│   │  envFrom:               │     └──────────────────────────────────────┘  │
│   │   - mi-export-sftp      │     ┌──────────────────────────────────────┐  │
│   │   - <component> Secret  │ ──► │  K8s Secret: mi-export-sftp-key      │  │
│   │   - <component> CM      │     │   id          (SSH private key)      │  │
│   │                         │     └────────────────┬─────────────────────┘  │
│   │   mi-export-scripts     │                      │                         │
│   │   (dump.sh)             │                      ▼                         │
│   │                         │     ┌──────────────────────────────────────┐  │
│   │  Volumes:               │     │  External SFTP server                │  │
│   │   /tmp (emptyDir 20Gi)  │ ──► │   <SFTP_REMOTE_PATH>/<gemeente>/     │  │
│   │   /etc/sftp (key 0400)  │     │     <YYMMDD>/<component>/            │  │
│   └─────────────────────────┘     │       <HHMMSS>-<component>.tar.gz    │  │
│                                   │       (or .pgdump)                   │  │
│                                   └──────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

Each CronJob:
1. Reads its target component's existing `<component>` Secret + ConfigMap (DB host, port, name, user, password — same secrets the app pods consume).
2. Reads the env's SFTP connection envvars from `Secret/mi-export-sftp` and the SSH private key from `Secret/mi-export-sftp-key` — both rendered by the chart from `mi.sftp.*` values.
3. Runs `dump.sh` in the chart's `mi-export-scripts` ConfigMap, accumulating per-table CSVs (or a single `pg_dump -Fc` file) under `/tmp` (a 20 GiB `emptyDir` scratch volume).
4. Uploads the result over `sftp -b -` to `<SFTP_REMOTE_PATH>/<gemeente>/<YYMMDD>/<component>/<HHMMSS>-<component>.<ext>`. Host-key checking is intentionally **disabled** (`StrictHostKeyChecking=no`, `UserKnownHostsFile=/dev/null`) — see [§ Host-key policy](#host-key-policy).
5. The scratch volume and the pod are torn down at job end (`ttlSecondsAfterFinished: 86400`); nothing in `/tmp` is preserved.

## Host-key policy

The CronJobs run `sftp` with host-key verification **disabled**:

```
-o UserKnownHostsFile=/dev/null
-o StrictHostKeyChecking=no
```

Rationale: these are short-lived, single-shot containers reaching a host fixed by DNS, and the **SSH private key already gates who can log in**. No `known_hosts` is mounted, consulted, or required. This trades MITM detection (which TOFU/pinning would add) for operational simplicity in the export path; the accepted risk is documented and intentional for this use case.

If a stricter posture is ever required, re-introduce a `known_hosts` seed and switch the script back to `StrictHostKeyChecking=accept-new` (TOFU) or `=yes` (pinned).

## Output format

Selected env-wide via `mi.format`. **All targets in a given environment use the same format** — there is no per-target override.

| `mi.format` | Tool | Output | Use case |
|---|---|---|---|
| `csv` *(default)* | `psql \COPY ... WITH (FORMAT csv, HEADER, DELIMITER ';')` per table | One `.tar.gz` per component, containing one `;`-separated CSV per table with a header row | Analytics consumers (Excel/EU-locale, pandas with `sep=";"`, ingest pipelines) |
| `pgdump` | `pg_dump -Fc --no-owner --no-privileges` per database | One `.pgdump` per component (custom format, zlib-compressed) | DR / cluster migration / point-in-time `pg_restore` |

Both formats honour `mi.targets[].schemas` (default `["public"]`; `zac` overrides to `["flowable"]`).

### SFTP layout

```
<SFTP_REMOTE_PATH>/<gemeente>/<YYMMDD>/<component>/<HHMMSS>-<component>.<ext>
```

A single timestamp is captured at script start, so every file from one CronJob run shares the same `<HHMMSS>` prefix and lands under the same date directory. The dated path is created with `sftp -mkdir` (which tolerates EEXIST), so existing trees are reused. Examples:

```
/uploads/mi-exports/jim00/260507/openzaak/095048-openzaak.tar.gz
/uploads/mi-exports/jim00/260507/openzaak/095048-openzaak.pgdump
/uploads/mi-exports/jim00/260507/objecten/091200-objecten.tar.gz
```

## Activation in an environment

### 1. SFTP prerequisites (once per env)

The chart renders both SFTP Secrets itself from `mi.sftp.*` values — you do **not** stage any K8s Secret manually. You need:

- A **reachable SFTP server** accepting connections from the cluster's egress range. Host, port, user, and remote root path are all required values (no defaults).
- An **SSH keypair**:
  - The *public* half installed in the SFTP user's `authorized_keys` on the server.
  - The *private* half stored in Azure Key Vault as `mi-data-sftp-rsa-private-key`. The [`application.yml`](https://dev.azure.com/ssctwente/ExternalsPodiumD) deploy pipeline reads it and substitutes it into the env values file's `mi.sftp.privateKey` placeholder at deploy time — it is never committed to git.

No `known_hosts` is needed — host-key checking is disabled (see [§ Host-key policy](#host-key-policy)).

From those values the chart renders, in the `podiumd` namespace:
- `Secret/mi-export-sftp` — `SFTP_HOST`, `SFTP_PORT`, `SFTP_USER`, `SFTP_REMOTE_PATH`.
- `Secret/mi-export-sftp-key` — single key `id` (the SSH private key, PEM).

### 2. Enable in `values-<env>.yml`

Minimum:

```yaml
mi:
  enabled: true
  gemeente: <env-name>            # path prefix on the SFTP server
  sftp:
    host: sftp.example.com        # required
    user: miuser                  # required
    remotePath: /mi-exports       # required (path on SFTP server)
    privateKey: "REP_MI_DATA_SFTP_RSA_PRIVATE_KEY_REP"  # required; pipeline substitutes from KV
```

Defaults: weekly schedule (Sunday 02:00 Europe/Amsterdam), `csv` format, port 22, all 14 default targets. A target only renders a CronJob when the corresponding `<component>.enabled` is `true` elsewhere in the env's values, so disabling a component automatically removes its export.

To switch the env to full database dumps:

```yaml
mi:
  enabled: true
  gemeente: <env-name>
  format: pgdump
  sftp:
    host: sftp.example.com
    user: miuser
    remotePath: /uploads/mi-exports
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
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
      ephemeral-storage: 20Gi
    limits:
      cpu: 1000m
      memory: 1Gi
      ephemeral-storage: 20Gi
  sftp:
    host: sftp.example.com
    port: 22
    user: miuser
    remotePath: /mi-exports
    privateKey: "REP_MI_DATA_SFTP_RSA_PRIVATE_KEY_REP"  # pipeline substitutes from KV
    secretName: mi-export-sftp        # chart-rendered Secret: connection envvars
    keySecretName: mi-export-sftp-key # chart-rendered Secret: `id` (SSH private key)
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

# Verify the upload landed (from a host with SFTP access)
sftp -i <private-key> miuser@sftp.example.com <<EOF
ls /uploads/mi-exports/<env>/$(date -u +%y%m%d)/openzaak/
EOF
```

A successful CSV run logs e.g.:

```
[ts] starting MI export: component=openzaak schemas=public format=csv
[ts] dumping public.zaken_zaak -> zaken_zaak.csv
... (one line per table)
[ts] packaging 127 CSV(s) into openzaak.tar.gz
[ts] uploading /uploads/mi-exports/<env>/260507/openzaak/095048-openzaak.tar.gz (482658 bytes) to miuser@sftp.example.com:22
[ts] uploaded 095048-openzaak.tar.gz
[ts] done: 127 table(s) packaged in <env>/260507/openzaak/095048-openzaak.tar.gz
```

A successful pgdump run logs:

```
[ts] starting MI export: component=openzaak schemas=public format=pgdump
[ts] running pg_dump -Fc on openzaak (schemas: public)
[ts] uploading /uploads/mi-exports/<env>/260507/openzaak/095048-openzaak.pgdump (533748 bytes) to miuser@sftp.example.com:22
[ts] uploaded 095048-openzaak.pgdump
[ts] done: pg_dump uploaded to <env>/260507/openzaak/095048-openzaak.pgdump
```

## Deployment

Deployment is via the **`application.yml` pipeline** in `dev.azure.com/ssctwente/ExternalsPodiumD` — the single supported path. There is no separate "test mode" and no manual Secret staging; the chart renders both SFTP Secrets from the `mi.sftp.*` values.

How the private key flows in:

1. The SSH private key is stored in Azure Key Vault as `mi-data-sftp-rsa-private-key`.
2. The pipeline's `AzureKeyVault@2` task exposes it as the variable `MI_DATA_SFTP_RSA_PRIVATE_KEY`.
3. The env values file carries a placeholder `mi.sftp.privateKey: "REP_MI_DATA_SFTP_RSA_PRIVATE_KEY_REP"`, which the pipeline substitutes with the KV value at deploy time (so the key never lands in git).
4. `helm upgrade` renders `Secret/mi-export-sftp` + `Secret/mi-export-sftp-key` from the values, and the CronJobs consume them.

The connection params (`host`, `port`, `user`, `remotePath`) live directly in the env values file. The SFTP server itself (with the gemeente's public key in `authorized_keys`) is the only out-of-band prerequisite.

### What is *not* needed

- **No manually-staged K8s Secrets.** The chart renders them from values.
- **No `known_hosts`.** Host-key checking is disabled (see [§ Host-key policy](#host-key-policy)).
- **No Azure Blob Storage container / SA key.** Blob is no longer the egress target.
- **No Workload Identity / federated credentials.** SFTP key auth is the credential.

## Operations

### Reading the uploaded files

Consumers with the gemeente's SSH key (or a federated `sftp` jump-host):

```bash
# List today's exports for an env
sftp -i <private-key> -o StrictHostKeyChecking=yes miuser@sftp.example.com <<EOF
ls /uploads/mi-exports/<env>/$(date -u +%y%m%d)/
EOF

# Download a single component's tarball
sftp -i <private-key> miuser@sftp.example.com:/uploads/mi-exports/<env>/260507/openzaak/095048-openzaak.tar.gz ./

# Inspect the CSVs without extracting
tar -tzf ./095048-openzaak.tar.gz | head

# For a pgdump file: list its TOC
pg_restore --list ./095048-openzaak.pgdump | head
```

> **Version note:** `pg_dump`/`pg_restore` in the chart's image (Azure Linux base + tdnf-installed `postgresql`) is currently PG16. A pgdump file written by PG16 cannot be read by older `pg_restore` clients — match the consumer's client version to PG16+ when restoring.

> **CSV separator:** `;` (per IN-2119). In pandas: `pd.read_csv("zaken_zaak.csv", sep=";")`. In Excel (Dutch locale): the file opens directly with one column per field; no Text-to-Columns step needed.

### Retention

The chart **does not** enforce retention on the uploaded files; that's the SFTP server side's concern. Configure the SFTP host's housekeeping (e.g. a server-side cron `find /uploads/mi-exports -type f -mtime +1825 -delete` for a 5-year retention, matching the typical gemeente case-data policy).

### Run-success monitoring

This iteration ships **without** alerting. The CronJob's standard Job/Pod failure events surface in `kubectl get events -n podiumd`. A future iteration ([IN-1993](https://dimpact.atlassian.net/browse/IN-1993)) wires up Prometheus alerting on missed schedules / failed runs.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `helm template` fails with `mi.format must be one of: csv, pgdump (got "X")` | Typo in `values-<env>.yml` | Set `mi.format` to `csv` or `pgdump` (or remove to use default `csv`). |
| `helm template` fails with `mi.sftp.host is required when mi.enabled is true` (or `…privateKey is required…`) | Required SFTP value not supplied | Set `mi.sftp.{host,user,remotePath,privateKey}` in the env values (the pipeline substitutes `privateKey` from Key Vault). |
| Job pod fails with `SFTP_HOST: must be set` | `Secret/mi-export-sftp` not rendered | Confirm `mi.enabled: true` and the `mi.sftp.*` connection values are set so the chart renders the Secret. |
| Upload fails with `No such file or directory` on `mkdir`/`put` | The first path segment of `remotePath` isn't a writable container/dir for `SFTP_USER`, **or** the user is chrooted into a home container and `remotePath` double-counts it | Confirm `SFTP_REMOTE_PATH`'s first segment exists and is writable. For Azure Blob SFTP local users whose `homeDirectory` is a container, paths are relative to that container — use `/<subpath>`, not `/<container>/<subpath>`. |
| Job pod fails with `Permissions 0644 for '…' are too open` | Private key Secret's `defaultMode` not 0400 | The chart sets `defaultMode: 0400` on the `sftp-key` volume; if you see this, something replaced the projected volume or a hostPath override is in play. |
| Job pod fails with `Couldn't get statSet for "/uploads/…": …: Permission denied` | SFTP user's home or remotePath isn't writable by `SFTP_USER` | Fix the server-side perms on `SFTP_REMOTE_PATH`. The script does `mkdir -p` recursively up from `/`, so any ancestor that the user can't enter blocks the upload. |
| Job pod fails with `password authentication failed for user "<component>"` | The component's K8s Secret has a stale DB password (env was rebuilt but Secret wasn't refreshed) | Re-run the deploy pipeline's "Create PostgreSQL Databases and Users" step; or `kubectl delete secret/<component> -n podiumd` and let the chart recreate it. |
| `csv` run logs `no tables found in schemas (...)` then exits 1 | Component's DB exists but has no tables (chart was deployed but the component's migration never ran) | Investigate the component's startup; the export script intentionally fails rather than upload an empty tarball. |
| Pod evicted with `Pod ephemeral local storage usage exceeds the total limit of containers 20Gi` | Component's tarball exceeded 20 GiB scratch budget | Increase `mi.resources.{requests,limits}.ephemeral-storage` and the matching `tmp` `emptyDir.sizeLimit` in `templates/mi-export-cronjobs.yaml`. |
| pgdump file rejected by `pg_restore` with `unsupported version (1.15)` | Consumer's PG client is older than PG16 | Use a PG16+ client to restore. |
| All Jobs fire on the same minute on a large cluster and overload the SFTP server | Default schedule is weekly Sunday 02:00 across all components | Stagger via per-target `schedule` overrides (chart values), or negotiate higher concurrency with the SFTP operator. |

## Changelog

- **Iter1 (chart 4.7.3)** — initial release: weekly per-component CronJobs, `csv` (`;`-separated) / `pgdump` env-wide knob, structured remote-path layout, SFTP egress with a KV-stored keypair (chart-rendered Secrets, host-key checking disabled), 20 GiB ephemeral scratch.
- **Iter2** *(not started)* — Keycloak-fronted web portal so consumers can browse/download without an SSH key.
- **Iter3** ([IN-1993](https://dimpact.atlassian.net/browse/IN-1993)) — baked image (drop runtime `tdnf install`); Prometheus alerts on missed/failed runs; per-table allow/deny lists.
