# MI exports — weekly database dumps to SFTP or FTP(S)

Weekly Management Information (MI) data exports of every Postgres-backed component the PodiumD chart deploys, uploaded over **SFTP or FTP(S)** to an external server. Designed for downstream consumers (gemeentes, analytics teams) that need a regular snapshot of the operational data.

> Jira: [IN-1650](https://dimpact.atlassian.net/browse/IN-1650) (epic) / [IN-1691](https://dimpact.atlassian.net/browse/IN-1691) (iter 1 — dump generator) / [IN-2119](https://dimpact.atlassian.net/browse/IN-2119) (egress switched from Azure Blob to SFTP, CSV separator `;`) / [IN-2499](https://dimpact.atlassian.net/browse/IN-2499) (standalone `mi-data` chart, unified transfer config, FTP/FTPS mode).

> **Chart home:** this feature lives in the standalone **`mi-data`** chart (`charts/mi-data`), consumed by the podiumd umbrella chart as an optional dependency under alias `mi`. **All values paths in this document are written as `mi.*`** — the podiumd form operators actually use. When installing the chart standalone, drop the `mi.` prefix (`transfer.host`, not `mi.transfer.host`).

> **⚠️ Opt-in feature — disabled by default.** Set `mi.enabled: true` in your env values file to turn it on. The chart renders the transfer Secrets (`mi-export-transfer`, plus `mi-export-transfer-key` in sftp-key mode) itself from the `mi.transfer.*` values — nothing is pre-provisioned. You need a reachable SFTP or FTP server and **exactly one** transfer mode via `mi.transfer.mode`: `sftp-password`, `sftp-key`, or `ftp`. The credential is substituted from Key Vault by the ExternalsPodiumD `application.yml` pipeline at deploy time. See [§ Activation in an environment](#activation-in-an-environment).

## Audience

**PodiumD operators** running the chart via the `ExternalsPodiumD` `application.yml` pipeline — to enable, configure, validate and consume exports. The chart renders the transfer Secrets from values, so the only out-of-band prerequisites are a reachable SFTP/FTP server and the credential (SSH private key or password) in Key Vault as `mi-data-sftp-credential` (see [§ Deployment](#deployment)).

## How it works

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                       AKS cluster — namespace: podiumd                        │
│                                                                              │
│   ┌─────────────────────────┐     ┌──────────────────────────────────────┐  │
│   │  CronJob                │     │  Postgres (flexible-server)          │  │
│   │  mi-export-<component>  │ ──► │  database: <component>               │  │
│   │  (one per target in     │     │                                      │  │
│   │   mi.targets[])         │     └──────────────────────────────────────┘  │
│   │                         │                                                │
│   │  schedule: 0 2 * * 0    │     ┌──────────────────────────────────────┐  │
│   │  (Sun 02:00 NL time)    │ ──► │  K8s Secret: mi-export-transfer      │  │
│   │                         │     │  (SFTP_* or FTP_* connection envs)   │  │
│   │  envFrom:               │     └──────────────────────────────────────┘  │
│   │   - mi-export-transfer  │     ┌──────────────────────────────────────┐  │
│   │   - <component> Secret  │ ──► │  K8s Secret: mi-export-transfer-key  │  │
│   │   - <component> CM      │     │   id   (SSH key; sftp-key mode only) │  │
│   │                         │     └────────────────┬─────────────────────┘  │
│   │   mi-export-scripts     │                      │                         │
│   │   (dump.sh)             │                      ▼                         │
│   │                         │     ┌──────────────────────────────────────┐  │
│   │  Volumes:               │     │  External SFTP / FTP(S) server       │  │
│   │   /tmp (emptyDir 20Gi)  │ ──► │   <REMOTE_PATH>/<gemeente>/          │  │
│   │   /etc/sftp (key 0400)  │     │     <YYMMDD>/<component>/            │  │
│   └─────────────────────────┘     │       <HHMMSS>-<component>.tar.gz    │  │
│                                   │       (or .pgdump)                   │  │
│                                   └──────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

Each CronJob:
1. Reads its target component's existing Secret + ConfigMap (same credentials the app pods consume; names default to `<component>`, overridable per-target via `secretName`/`configMapName`). `dump.sh` normalises three credential shapes to `DB_*`:
   - `DB_HOST/DB_NAME/DB_USER/DB_PASSWORD` (+`DB_PORT`) — the Django apps;
   - `POSTGRES_HOST/DB/USER/PASSWORD` (+`POSTGRES_PORT`) — kiss frontend (Secret/ConfigMap `contact`);
   - an Npgsql connection string (`Host=…;Port=…;Database=…;Username=…;Password=…`) in the env named by the per-target `connectionStringEnv` — the .NET apps (ita: `ConnectionStrings__DefaultConnection` in `ita-secrets`, pabc: `ConnectionStrings__Pabc`).

   Both refs are mounted `optional: true`: a component that exposes credentials in none of these shapes (e.g. not deployed in this env) is treated as **not using PostgreSQL** — the job logs `skip: … no DB_* credentials` and exits green instead of hanging in `CreateContainerConfigError`. A *partial* credential set still fails the job (real misconfiguration).
2. Reads the env's transfer connection envvars from `Secret/mi-export-transfer` (the `SFTP_*` family in the sftp modes, the `FTP_*` family in ftp mode) and — in sftp-key mode — the SSH private key from `Secret/mi-export-transfer-key`. Both rendered by the chart from `mi.transfer.*` values.
3. Runs `dump.sh` in the chart's `mi-export-scripts` ConfigMap, accumulating per-table CSVs (or a single `pg_dump -Fc` file) under `/tmp` (a 20 GiB `emptyDir` scratch volume).
4. Uploads the result to `<REMOTE_PATH>/<gemeente>/<YYMMDD>/<component>/<HHMMSS>-<component>.<ext>` — over `sftp -b -` in the sftp modes (host-key checking intentionally **disabled**, see [§ Host-key policy](#host-key-policy)), or via `curl` in ftp mode (`--ftp-create-dirs`; `--ssl-reqd` when `mi.transfer.ftps: true`).
5. The scratch volume and the pod are torn down at job end (`ttlSecondsAfterFinished: 86400`); nothing in `/tmp` is preserved.

## Transfer modes

Selected via `mi.transfer.mode` — exactly one per environment; the render fails fast on a missing/typo'd mode or a credential that doesn't match it.

| `mi.transfer.mode` | Protocol | Credential field | Notes |
|---|---|---|---|
| `sftp-password` | SFTP (SSH) | `mi.transfer.password` | E.g. Azure Blob SFTP local users. Fed to `sftp` via an `SSH_ASKPASS` helper (on Azure Linux `sshpass` would drag in `openssh-server`, whose install fails in the azure-cli image). |
| `sftp-key` | SFTP (SSH) | `mi.transfer.privateKey` | The *public* half must be installed in the SFTP user's `authorized_keys`. Key mounted at `/etc/sftp/id`, mode 0400. |
| `ftp` | FTP, optionally FTPS | `mi.transfer.password` | Uploaded via `curl`. **Plain FTP transmits credentials and data cleartext on the wire — set `mi.transfer.ftps: true` (explicit TLS, `curl --ssl-reqd`) whenever the server supports it.** |

> **FTP path semantics:** an FTP URL path is relative to the login home directory (RFC 1738), unlike SFTP where `remotePath` is absolute. On servers whose FTP home is not `/`, use a double leading slash to force an absolute path: `remotePath: "//uploads/mi-exports"`.

## Host-key policy

In the sftp modes the CronJobs run `sftp` with host-key verification **disabled**:

```
-o UserKnownHostsFile=/dev/null
-o StrictHostKeyChecking=no
```

Rationale: these are short-lived, single-shot containers reaching a host fixed by DNS, and the **credential already gates who can log in**. No `known_hosts` is mounted, consulted, or required. This trades MITM detection (which TOFU/pinning would add) for operational simplicity in the export path; the accepted risk is documented and intentional for this use case.

If a stricter posture is ever required, re-introduce a `known_hosts` seed and switch the script back to `StrictHostKeyChecking=accept-new` (TOFU) or `=yes` (pinned).

(ftp mode has no host-key concept; server authenticity is only verified when `ftps: true` and the server presents a TLS certificate curl can validate.)

## Output format

Selected env-wide via `mi.format`. **All targets in a given environment use the same format** — there is no per-target override.

| `mi.format` | Tool | Output | Use case |
|---|---|---|---|
| `csv` *(default)* | `psql \COPY ... WITH (FORMAT csv, HEADER, DELIMITER ';')` per table | One `.tar.gz` per component, containing one `;`-separated CSV per table with a header row | Analytics consumers (Excel/EU-locale, pandas with `sep=";"`, ingest pipelines) |
| `pgdump` | `pg_dump -Fc --no-owner --no-privileges` per database | One `.pgdump` per component (custom format, zlib-compressed) | DR / cluster migration / point-in-time `pg_restore` |

Both formats honour `mi.targets[].schemas` (default `["public"]`; `zac` overrides to `["flowable"]`).

### Remote layout

```
<REMOTE_PATH>/<gemeente>/<YYMMDD>/<component>/<HHMMSS>-<component>.<ext>
```

A single timestamp is captured at script start, so every file from one CronJob run shares the same `<HHMMSS>` prefix and lands under the same date directory. In the sftp modes the script probes each ancestor directory with a silent `cd` and only `mkdir`s the missing tail, so existing trees are reused without emitting `remote mkdir: Failure` noise (Azure Blob SFTP reports EEXIST as a generic failure); the mkdirs it does emit still tolerate EEXIST, because sibling component jobs on the same schedule share the `<gemeente>/<YYMMDD>` ancestors and may create them concurrently. In ftp mode curl's `--ftp-create-dirs` handles missing directories. Examples:

```
/uploads/mi-exports/jim00/260507/openzaak/095048-openzaak.tar.gz
/uploads/mi-exports/jim00/260507/openzaak/095048-openzaak.pgdump
/uploads/mi-exports/jim00/260507/objecten/091200-objecten.tar.gz
```

## Activation in an environment

### 1. Transfer prerequisites (once per env)

The chart renders the transfer Secrets itself from `mi.transfer.*` values — you do **not** stage any K8s Secret manually. You need:

- A **reachable SFTP or FTP(S) server** accepting connections from the cluster's egress range. Mode, host, user, and remote root path are all required values (no defaults; port defaults to 22 for the sftp modes, 21 for ftp).
- The **credential matching `mi.transfer.mode`** (see [§ Transfer modes](#transfer-modes)): a password (`sftp-password`, `ftp`) or an SSH private key (`sftp-key`). The render fails when the credential doesn't match the mode.

  The credential lives in Azure Key Vault under the **same secret name** regardless of mode: `mi-data-sftp-credential` (env-suffixed on the qa flavor, e.g. `mi-data-sftp-credential-jim00`). The KV name does not encode the credential type — `mi.transfer.mode` picks how it is used.

  The [`application.yml`](https://dev.azure.com/ssctwente/ExternalsPodiumD) deploy pipeline substitutes the credential from Key Vault at deploy time — it is never committed to git.

No `known_hosts` is needed — host-key checking is disabled in the sftp modes (see [§ Host-key policy](#host-key-policy)).

From those values the chart renders, in the `podiumd` namespace:
- `Secret/mi-export-transfer` — the `SFTP_*` connection envvars in the sftp modes, or the `FTP_*` family (`FTP_HOST/PORT/USER/PASSWORD/REMOTE_PATH/FTP_FTPS`) in ftp mode. The unused family is rendered with empty values so a mode switch never leaves stale keys behind.
- `Secret/mi-export-transfer-key` — single key `id` (the SSH private key, PEM). sftp-key mode only.

### 2. Enable in `values-<env>.yml`

sftp-key mode:

```yaml
mi:
  enabled: true
  gemeente: <env-name>            # path prefix on the server
  transfer:
    mode: sftp-key
    host: sftp.example.com        # required
    user: miuser                  # required
    remotePath: /mi-exports       # required (absolute path on the SFTP server)
    privateKey: "REP_MI_DATA_SFTP_CREDENTIAL_REP"  # pipeline substitutes from KV
```

sftp-password mode (e.g. Azure Blob SFTP local users):

```yaml
mi:
  enabled: true
  gemeente: <env-name>
  transfer:
    mode: sftp-password
    host: fdrpsftp8bbbe0.blob.core.windows.net
    user: fdrpsftp8bbbe0.floepdorp        # Azure Blob SFTP: <account>.<localuser>
    remotePath: /mi-exports
    password: "REP_MI_DATA_SFTP_CREDENTIAL_REP"  # pipeline substitutes from KV
```

ftp mode (set `ftps: true` whenever the server supports TLS):

```yaml
mi:
  enabled: true
  gemeente: <env-name>
  transfer:
    mode: ftp
    host: ftp.example.com
    user: miuser
    remotePath: /mi-exports       # relative to the FTP login home; "//abs/path" forces absolute
    password: "REP_MI_DATA_SFTP_CREDENTIAL_REP"  # pipeline substitutes from KV
    ftps: true                    # explicit TLS (AUTH TLS); omit/false = plain FTP (cleartext!)
```

Defaults: weekly schedule (Sunday 02:00 Europe/Amsterdam), `csv` format, all 14 default targets. A target whose component is not deployed in the env runs as a weekly no-op (the job logs `skip: …` and exits 0) — trim `mi.targets` per environment to avoid the no-op runs entirely.

To switch the env to full database dumps, add `format: pgdump` at the `mi:` level.

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
  transfer:
    mode: ""                          # sftp-password | sftp-key | ftp (required)
    host: ""
    port: ""                          # empty → 22 (sftp modes) / 21 (ftp)
    user: ""
    remotePath: ""
    password: ""                      # sftp-password + ftp modes
    privateKey: ""                    # sftp-key mode
    ftps: false                       # ftp mode: explicit TLS
    secretName: mi-export-transfer        # chart-rendered Secret: connection envvars
    keySecretName: mi-export-transfer-key # chart-rendered Secret: `id` (sftp-key mode only)
```

### 3. Trim or override the target list (optional)

The chart's default `mi.targets[]` covers all 14 Postgres-backed components. Targets for components that are not deployed are harmless no-ops, but trimming the list keeps the CronJob inventory clean:

```yaml
mi:
  targets:
    - component: openzaak
    - component: zac
      schemas: ["flowable"]    # zac uses Flowable schema, not public
    - component: openklant
      enabled: false           # ad-hoc opt-out for this env only
    - component: opennotificaties
      secretName: notificaties # override when podiumd subchart key ≠ resource name
      configMapName: notificaties
    - component: ita
      secretName: ita-secrets   # .NET app: creds live in a connection string
      configMapName: ita-config
      connectionStringEnv: ConnectionStrings__DefaultConnection
    - component: kiss
      secretName: contact       # kiss-frontend fullnameOverride; POSTGRES_* keys
      configMapName: contact
```

### 4. Validation

After the next chart apply:

```bash
# Should list one CronJob per (non-opted-out) target
kubectl -n podiumd get cronjob -l app.kubernetes.io/component=mi-export

# Trigger an out-of-schedule run for one component
kubectl -n podiumd create job --from=cronjob/mi-export-openzaak mi-test-now

# Watch
kubectl -n podiumd logs -l job-name=mi-test-now -f --tail=50

# Verify the upload landed (from a host with SFTP access; for ftp mode use an FTP client)
sftp -i <private-key> miuser@sftp.example.com <<EOF
ls /uploads/mi-exports/<env>/$(date -u +%y%m%d)/openzaak/
EOF
```

A successful CSV run logs e.g.:

```
[ts] starting MI export: component=openzaak schemas=public format=csv transfer=sftp
[ts] dumping public.zaken_zaak -> zaken_zaak.csv
... (one line per table)
[ts] packaging 127 CSV(s) into openzaak.tar.gz
[ts] uploading /uploads/mi-exports/<env>/260507/openzaak/095048-openzaak.tar.gz (482658 bytes) to miuser@sftp.example.com:22
[ts] uploaded 095048-openzaak.tar.gz
[ts] done: 127 table(s) packaged in <env>/260507/openzaak/095048-openzaak.tar.gz
```

A successful pgdump run logs:

```
[ts] starting MI export: component=openzaak schemas=public format=pgdump transfer=sftp
[ts] running pg_dump -Fc on openzaak (schemas: public)
[ts] uploading /uploads/mi-exports/<env>/260507/openzaak/095048-openzaak.pgdump (533748 bytes) to miuser@sftp.example.com:22
[ts] uploaded 095048-openzaak.pgdump
[ts] done: pg_dump uploaded to <env>/260507/openzaak/095048-openzaak.pgdump
```

(ftp mode logs `uploading … to ftp://miuser@ftp.example.com:21 (ftps=true)` instead.)

## Deployment

Deployment is via the **`application.yml` pipeline** in `dev.azure.com/ssctwente/ExternalsPodiumD` — the single supported path. There is no separate "test mode" and no manual Secret staging; the chart renders the transfer Secrets from the `mi.transfer.*` values.

How the credential flows in (same path for every mode — only the values field differs):

1. The credential (SSH private key **or** password) is stored in Azure Key Vault as `mi-data-sftp-credential` (env-suffixed on the qa flavor).
2. The pipeline's `AzureKeyVault@2` task exposes it as the variable `MI_DATA_SFTP_CREDENTIAL`.
3. The env values file carries the placeholder `"REP_MI_DATA_SFTP_CREDENTIAL_REP"` in `mi.transfer.privateKey` (sftp-key mode) or `mi.transfer.password` (sftp-password / ftp mode); the pipeline substitutes the KV value at deploy time (so the credential never lands in git).
4. `helm upgrade` renders `Secret/mi-export-transfer` (+ `Secret/mi-export-transfer-key` in sftp-key mode) from the values, and the CronJobs consume them.

The connection params (`mode`, `host`, `port`, `user`, `remotePath`, `ftps`) live directly in the env values file. The server itself (with the gemeente's public key in `authorized_keys` for sftp-key mode) is the only out-of-band prerequisite.

### What is *not* needed

- **No manually-staged K8s Secrets.** The chart renders them from values.
- **No `known_hosts`.** Host-key checking is disabled in the sftp modes (see [§ Host-key policy](#host-key-policy)).
- **No Azure Blob Storage container / SA key.** Blob is not an egress target.
- **No Workload Identity / federated credentials.** The transfer credential (keypair or password) is the only auth.

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

The chart **does not** enforce retention on the uploaded files; that's the server side's concern. Configure the host's housekeeping (e.g. a server-side cron `find /uploads/mi-exports -type f -mtime +1825 -delete` for a 5-year retention, matching the typical gemeente case-data policy).

### Run-success monitoring

This iteration ships **without** alerting. The CronJob's standard Job/Pod failure events surface in `kubectl get events -n podiumd`. A future iteration ([IN-1993](https://dimpact.atlassian.net/browse/IN-1993)) wires up Prometheus alerting on missed schedules / failed runs.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `helm template` fails with `format must be one of: csv, pgdump (got "X")` | Typo in `values-<env>.yml` | Set `mi.format` to `csv` or `pgdump` (or remove to use default `csv`). |
| `helm template` fails with `transfer.mode must be one of: sftp-password, sftp-key, ftp` | `mi.transfer.mode` missing or typo'd — including values files not yet migrated from the pre-1.0.0 `mi.sftp.*` layout | Set `mi.transfer.mode` (and migrate `mi.sftp.*` keys to `mi.transfer.*` — see the podiumd 4.8.2→4.8.3 upgrade notes). |
| `helm template` fails with `transfer.host is required…` (or `…user…` / `…remotePath…`) | Required transfer value not supplied | Set `mi.transfer.{host,user,remotePath}` in the env values. |
| `helm template` fails with `transfer.password is required in … mode` / `transfer.privateKey must be empty in … mode` (or the sftp-key inverses) | Credential doesn't match `mi.transfer.mode` | Supply exactly the credential the mode expects (the pipeline substitutes it from Key Vault). |
| Job pod fails with `no transfer configured: one of FTP_HOST or SFTP_HOST must be set` | `Secret/mi-export-transfer` not rendered or stale | Confirm `mi.enabled: true` and the `mi.transfer.*` values are set so the chart renders the Secret; re-apply. |
| Job logs `skip: component <x> exposes no DB_* credentials …` and exits 0 | The component's Secret/ConfigMap carry credentials in none of the three supported shapes (`DB_*`, `POSTGRES_*`, `connectionStringEnv`) — usually the component isn't deployed in this env | Expected when the component isn't deployed (trim `mi.targets` to silence). If the component *should* export, point per-target `secretName`/`configMapName` at the resources that carry its credentials and/or set `connectionStringEnv`. |
| Job pod fails with `partial DB_* credentials for <x> (missing: …)` | Some but not all `DB_*` envs resolve — typo'd per-target `secretName`/`configMapName`, half-migrated component Secret/ConfigMap, or a connection string missing a field | Fix the target override, the component's Secret/ConfigMap, or the connection string so all four `DB_*` values resolve. |
| Upload fails with `No such file or directory` on `mkdir`/`put` (sftp modes) | The first path segment of `remotePath` isn't a writable container/dir for the user, **or** the user is chrooted into a home container and `remotePath` double-counts it | Confirm `remotePath`'s first segment exists and is writable. For Azure Blob SFTP local users whose `homeDirectory` is a container, paths are relative to that container — use `/<subpath>`, not `/<container>/<subpath>`. |
| ftp upload fails with `curl: (9) Server denied you to change to the given directory` | `remotePath` doesn't resolve under the FTP login home — FTP URL paths are home-relative | Use a path relative to the login home, or force absolute with a double leading slash (`remotePath: "//uploads/mi-exports"`). |
| ftp upload fails with `curl: (64) Requested SSL level failed` (or a TLS handshake error) | `ftps: true` but the server doesn't support explicit TLS (AUTH TLS), or presents an invalid certificate | Fix the server's TLS support/cert, or (trusted networks only) set `ftps: false` — plain FTP transmits credentials cleartext. |
| ftp upload fails with `curl: (67) Access denied` / login failure | Wrong `mi.transfer.user`/password for the FTP account | Verify the FTP account credentials; check the KV secret `mi-data-sftp-credential` holds the FTP password for this env. |
| Job pod fails with `Permissions 0644 for '…' are too open` | Private key Secret's `defaultMode` not 0400 | The chart sets `defaultMode: 0400` on the `sftp-key` volume; if you see this, something replaced the projected volume or a hostPath override is in play. |
| Job pod fails with `Couldn't get statSet for "/uploads/…": …: Permission denied` | SFTP user's home or remotePath isn't writable by the user | Fix the server-side perms on `remotePath`. The script probes and creates ancestor directories from `/` down, so any ancestor that the user can't enter blocks the upload. |
| Job pod fails with `password authentication failed for user "<component>"` | The component's K8s Secret has a stale DB password (env was rebuilt but Secret wasn't refreshed) | Re-run the deploy pipeline's "Create PostgreSQL Databases and Users" step; or `kubectl delete secret/<component> -n podiumd` and let the chart recreate it. |
| `csv` run logs `no tables found in schemas (...)` then exits 1 | Component's DB exists but has no tables (chart was deployed but the component's migration never ran) | Investigate the component's startup; the export script intentionally fails rather than upload an empty tarball. |
| Pod evicted with `Pod ephemeral local storage usage exceeds the total limit of containers 20Gi` | Component's tarball exceeded 20 GiB scratch budget | Increase `mi.resources.{requests,limits}.ephemeral-storage` and the matching `tmp` `emptyDir.sizeLimit` in `templates/cronjobs.yaml`. |
| pgdump file rejected by `pg_restore` with `unsupported version (1.15)` | Consumer's PG client is older than PG16 | Use a PG16+ client to restore. |
| All Jobs fire on the same minute on a large cluster and overload the transfer server | Default schedule is weekly Sunday 02:00 across all components | Stagger via per-target `schedule` overrides (chart values), or negotiate higher concurrency with the server operator. |

## Changelog

- **Iter1 (podiumd chart 4.7.3)** — initial release: weekly per-component CronJobs, `csv` (`;`-separated) / `pgdump` env-wide knob, structured remote-path layout, SFTP egress with a KV-stored keypair (chart-rendered Secrets, host-key checking disabled), 20 GiB ephemeral scratch.
- **podiumd chart 4.8.1** — password auth added: `mi.sftp.password` (XOR with `privateKey`), rendered as `SFTP_PASSWORD` in the connection Secret and fed to `sftp` via an `SSH_ASKPASS` helper; supports e.g. Azure Blob SFTP local users.
- **mi-data chart 1.0.0** ([IN-2499](https://dimpact.atlassian.net/browse/IN-2499)) — extracted from the podiumd chart into the standalone `mi-data` chart (podiumd consumes it under alias `mi` from 4.8.3). Unified `mi.transfer` section with explicit `mode: sftp-password | sftp-key | ftp` replaces `mi.sftp.*` (breaking; see the podiumd 4.8.2→4.8.3 upgrade notes). New ftp mode via curl with optional FTPS (`ftps: true`). Secrets renamed `mi-export-transfer` / `mi-export-transfer-key`. Per-target rendering no longer reads the umbrella chart's `<component>.enabled` flags — undeployed components run as no-op skips; trim `mi.targets` to remove them.
- **Iter2** *(not started)* — Keycloak-fronted web portal so consumers can browse/download without an SSH key.
- **Iter3** ([IN-1993](https://dimpact.atlassian.net/browse/IN-1993)) — baked image (drop runtime `tdnf install`); Prometheus alerts on missed/failed runs; per-table allow/deny lists.
