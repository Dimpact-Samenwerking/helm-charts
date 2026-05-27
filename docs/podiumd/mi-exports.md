# MI exports — weekly database dumps to SFTP

Weekly Management Information (MI) data exports of every Postgres-backed component the PodiumD chart deploys, uploaded over **SFTP** to an external server. Designed for downstream consumers (gemeentes, analytics teams) that need a regular snapshot of the operational data.

> Jira: [IN-1650](https://dimpact.atlassian.net/browse/IN-1650) (epic) / [IN-1691](https://dimpact.atlassian.net/browse/IN-1691) (iter 1 — dump generator) / [IN-2119](https://dimpact.atlassian.net/browse/IN-2119) (egress switched from Azure Blob to SFTP, CSV separator `;`).

> **⚠️ Opt-in feature — disabled by default.** Set `mi.enabled: true` in your env values file to turn it on. Doing so **only** has effect when the SFTP-side prerequisites are already in place: a reachable SFTP server, a K8s `Secret/mi-export-sftp` carrying the connection envvars, and a K8s `Secret/mi-export-sftp-key` carrying the SSH private key + `known_hosts` entry. Without those, the CronJob pods fail on first run. See [§ Activation in an environment](#activation-in-an-environment) for the full checklist, or [§ Test mode](#test-mode) for a sandbox-only shortcut.

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
│   │  (Sun 02:00 NL time)    │ ──► │  K8s Secret: mi-export-sftp          │  │
│   │                         │     │  (SFTP_HOST/PORT/USER/REMOTE_PATH)   │  │
│   │  envFrom:               │     └──────────────────────────────────────┘  │
│   │   - mi-export-sftp      │     ┌──────────────────────────────────────┐  │
│   │   - <component> Secret  │ ──► │  K8s Secret: mi-export-sftp-key      │  │
│   │   - <component> CM      │     │   id          (SSH private key)      │  │
│   │                         │     │   known_hosts (pinned host key)      │  │
│   │  ConfigMap:             │     └────────────────┬─────────────────────┘  │
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
2. Reads the env's SFTP connection envvars from `Secret/mi-export-sftp` and the SSH key + `known_hosts` from `Secret/mi-export-sftp-key`.
3. Runs `dump.sh` in the chart's `mi-export-scripts` ConfigMap, accumulating per-table CSVs (or a single `pg_dump -Fc` file) under `/tmp` (a 20 GiB `emptyDir` scratch volume).
4. Uploads the result over `sftp -b -` to `<SFTP_REMOTE_PATH>/<gemeente>/<YYMMDD>/<component>/<HHMMSS>-<component>.<ext>`. `StrictHostKeyChecking=yes` is enforced.
5. The scratch volume and the pod are torn down at job end (`ttlSecondsAfterFinished: 86400`); nothing in `/tmp` is preserved.

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

Before enabling the chart feature, the env must already have:

- A **reachable SFTP server** accepting connections from the cluster's egress range. Host, port, user, and remote root path are all required values (no defaults).
- An **SSH keypair**:
  - The *public* half installed in the SFTP user's `authorized_keys` on the server.
  - The *private* half stored in the env's Key Vault. Convention: a multi-line KV secret named `mi-export-sftp-key-<env>`.
- A **`known_hosts` entry** for the SFTP server, generated once via `ssh-keyscan -t ed25519 <host>` and stored alongside the private key in Key Vault. The chart enforces `StrictHostKeyChecking=yes`; first-connect TOFU is not supported.
- A K8s `Secret/mi-export-sftp` in the `podiumd` namespace carrying four envvars:
  - `SFTP_HOST`
  - `SFTP_PORT`
  - `SFTP_USER`
  - `SFTP_REMOTE_PATH`
- A K8s `Secret/mi-export-sftp-key` in the `podiumd` namespace with two keys:
  - `id` — the SSH private key, as a single PEM block.
  - `known_hosts` — single-line `ssh-keyscan` output.

For test/dev envs (jim00, jos00, …): the `podiumd-infra` repo's `scripts/sync-mi-export-secret.sh` reads the KV material and creates both K8s Secrets. Run it once after a fresh app install. (Variant of the script for SFTP credentials lands alongside IN-2119; see [§ Production / external hosting](#production--external-hosting).)

For production-hosted envs: see [§ Production / external hosting](#production--external-hosting).

For a sandbox without any of the above (just iterating against a local atmoz/sftp pod), use [§ Test mode](#test-mode) instead.

### 2. Enable in `values-<env>.yml`

Minimum:

```yaml
mi:
  enabled: true
  gemeente: <env-name>            # path prefix on the SFTP server
  sftp:
    host: sftp.example.com        # required
    user: miuser                  # required
    remotePath: /uploads/mi-exports  # required (absolute path on SFTP server)
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
    remotePath: /uploads/mi-exports
    secretName: mi-export-sftp        # K8s Secret with connection envvars
    keySecretName: mi-export-sftp-key # K8s Secret with `id` + `known_hosts`
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

## Test mode

**Never enable in production values.**

For dev sandboxes (jim00 etc.) that need to iterate against a sandbox SFTP target without provisioning Key Vault entries, the chart can render both Secrets from inline values:

```yaml
mi:
  enabled: true
  gemeente: jim00
  sftp:
    host: sftp-test.podiumd.svc.cluster.local   # e.g. an atmoz/sftp pod in same ns
    port: 22
    user: miuser
    remotePath: /upload
    testMode:
      enabled: true
      privateKey: |
        -----BEGIN OPENSSH PRIVATE KEY-----
        ... ed25519 PEM …
        -----END OPENSSH PRIVATE KEY-----
      knownHosts: |
        sftp-test.podiumd.svc.cluster.local ssh-ed25519 AAAA…
```

Generating a throwaway keypair:

```bash
ssh-keygen -t ed25519 -N "" -f ./mi-test-key
# - mi-test-key       → paste into mi.sftp.testMode.privateKey
# - mi-test-key.pub   → install into the test SFTP server's authorized_keys
# - ssh-keyscan -t ed25519 <host>  → mi.sftp.testMode.knownHosts
```

When `mi.sftp.testMode.enabled: true`, the chart renders two extra Secrets (named per `mi.sftp.secretName` / `mi.sftp.keySecretName`) labeled `mi.podiumd.dimpact.nl/test-only: "true"` so they're trivially grep-able. The CronJob template enforces `required` on `privateKey` and `knownHosts` when testMode is enabled, so a half-filled testMode block fails fast.

## Production / external hosting

The Terraform in `ICATT-Menselijk-Digitaal/podiumd-infra` is **only for Dimpact's test/dev environments** (jim00, jos00, jimme00, etc.). Production environments hosted by external providers (e.g. SSC Twente — `dev.azure.com/ssctwente/ExternalsPodiumD`) need to replicate the same shape in their own Terraform module.

### What the hosting provider must add

The SFTP-side prerequisites in [§ SFTP prerequisites](#1-sftp-prerequisites-once-per-env): an addressable SFTP target (provider-supplied; could be a managed FTAaaS, a VM-based SSH server, or an on-prem hop) with the gemeente's public key in `authorized_keys`, plus the two K8s Secrets in the `podiumd` namespace materialised before the chart is installed.

Concretely, the provider's Terraform module needs:

1. A `keyvault_secret` for the SSH private key (e.g. `mi-export-sftp-key-<env>`), with rotation policy aligned to the gemeente's policy.
2. A `keyvault_secret` for the SFTP connection params (host/port/user/remotePath), or a config-only check-in.
3. A pipeline step that reads both KV secrets at deploy time and creates `Secret/mi-export-sftp` and `Secret/mi-export-sftp-key` in the `podiumd` namespace before the helm install runs.

The chart itself is hosting-provider-agnostic — it only needs the two Secrets to be present at install time. **Any** provisioning approach that delivers them with the right values works.

### What the hosting provider does *not* need

- **No Azure Blob Storage container / SA key.** Blob is no longer the egress target.
- **No Workload Identity / federated credentials.** SFTP key auth is end-to-end credential.
- **No new identity / RBAC** beyond access to the existing per-env Key Vault and SSH access to the SFTP target.

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
| `helm template` fails with `mi.sftp.host is required when mi.enabled is true` | Required SFTP value not supplied | Set `mi.sftp.{host,user,remotePath}` in the env values, or enable testMode. |
| Job pod fails with `SFTP_HOST: must be set` | `Secret/mi-export-sftp` not present in podiumd ns | Run the env's secret-sync script, or apply the Secret manually (see [§ Production / external hosting](#production--external-hosting)). |
| Job pod fails with `Host key verification failed.` | `known_hosts` entry doesn't match the SFTP server's current host key | Re-run `ssh-keyscan -t ed25519 <host>` and update the `known_hosts` key in `Secret/mi-export-sftp-key`. If the host key legitimately rotated, audit before trusting blindly. |
| Job pod fails with `Permissions 0644 for '…' are too open` | Private key Secret's `defaultMode` not 0400 | The chart sets `defaultMode: 0400` on the `sftp-key` volume; if you see this, something replaced the projected volume or a hostPath override is in play. |
| Job pod fails with `Couldn't get statSet for "/uploads/…": …: Permission denied` | SFTP user's home or remotePath isn't writable by `SFTP_USER` | Fix the server-side perms on `SFTP_REMOTE_PATH`. The script does `mkdir -p` recursively up from `/`, so any ancestor that the user can't enter blocks the upload. |
| Job pod fails with `password authentication failed for user "<component>"` | The component's K8s Secret has a stale DB password (env was rebuilt but Secret wasn't refreshed) | Re-run the deploy pipeline's "Create PostgreSQL Databases and Users" step; or `kubectl delete secret/<component> -n podiumd` and let the chart recreate it. |
| `csv` run logs `no tables found in schemas (...)` then exits 1 | Component's DB exists but has no tables (chart was deployed but the component's migration never ran) | Investigate the component's startup; the export script intentionally fails rather than upload an empty tarball. |
| Pod evicted with `Pod ephemeral local storage usage exceeds the total limit of containers 20Gi` | Component's tarball exceeded 20 GiB scratch budget | Increase `mi.resources.{requests,limits}.ephemeral-storage` and the matching `tmp` `emptyDir.sizeLimit` in `templates/mi-export-cronjobs.yaml`. |
| pgdump file rejected by `pg_restore` with `unsupported version (1.15)` | Consumer's PG client is older than PG16 | Use a PG16+ client to restore. |
| All Jobs fire on the same minute on a large cluster and overload the SFTP server | Default schedule is weekly Sunday 02:00 across all components | Stagger via per-target `schedule` overrides (chart values), or negotiate higher concurrency with the SFTP operator. |

## Changelog

- **Iter1 (chart 4.7.3)** — initial release: weekly per-component CronJobs, `csv` (`;`-separated) / `pgdump` env-wide knob, structured remote-path layout, SFTP egress with KV-stored keypair, testMode for dev sandboxes, 20 GiB ephemeral scratch.
- **Iter2** *(not started)* — Keycloak-fronted web portal so consumers can browse/download without an SSH key.
- **Iter3** ([IN-1993](https://dimpact.atlassian.net/browse/IN-1993)) — baked image (drop runtime `tdnf install`); Prometheus alerts on missed/failed runs; per-table allow/deny lists.
