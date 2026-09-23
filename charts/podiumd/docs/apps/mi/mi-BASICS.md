# MI exports — Basics

## Management summary

MI (Management Information) exports give the municipality a weekly copy of the
data in its PodiumD applications, for reporting and analytics outside the
platform. Every Sunday night the cluster dumps the database of each deployed
application and uploads the result to a file server chosen by the municipality
— over SFTP or, since 4.8.3, classic FTP (optionally TLS-encrypted FTPS) —
where analysts or downstream systems can pick it up. The feature is off by
default and switched on per environment; it needs no extra servers inside the
cluster — only a reachable file server and one stored credential. Footprint is
small: short-lived weekly jobs, no always-on components.

## What it is

- **Upstream:** the standalone **`mi-data` chart** in this repo
  (`charts/mi-data`, released as `mi-data-<version>` by the same
  chart-releaser workflow as podiumd). Not a deployed application — the export
  container runs the stock `mcr.microsoft.com/azure-cli:2.71.0` image
  (`mi.image.*`) and installs `postgresql` client tools at job start.
- **Deployed via:** a podiumd chart dependency (since 4.8.3): `mi-data` under
  **alias `mi`**, `condition: mi.enabled` — so all values paths keep the
  familiar top-level `mi.*` prefix. Before 4.8.3 the same templates lived
  inline in the podiumd chart.
- **Enable flag:** `mi.enabled` (default `false` — opt-in per environment).
- **Runtime components:**
  - `CronJob/mi-export-<component>` — one per entry in `mi.targets[]` (up to
    14: openzaak, opennotificaties, objecten, objecttypen, openarchiefbeheer,
    openklant, openformulieren, openinwoner, referentielijsten, openbeheer,
    zac, ita, kiss, pabc). A target whose component is not deployed runs as a
    weekly no-op (the job logs `skip: …` and exits 0) — trim `mi.targets`
    per environment to remove them. Default schedule `0 2 * * 0` (Sunday
    02:00 Europe/Amsterdam), `concurrencyPolicy: Forbid`, jobs auto-cleaned
    after 24 h (`ttlSecondsAfterFinished: 86400`). No Deployments,
    StatefulSets or always-on pods.

Each job dumps its component's Postgres database (per-table `;`-separated
CSVs in a `.tar.gz`, or a single `pg_dump -Fc` file — env-wide
`mi.format: csv | pgdump`) and uploads it to
`<remotePath>/<gemeente>/<YYMMDD>/<component>/<HHMMSS>-<component>.<ext>`.

## Required resources

### Database

No database of its own. The jobs **read** every target component's existing
Postgres database, reusing the credentials from that component's own
Secret/ConfigMap (names default to `<component>`, overridable per-target via
`mi.targets[].secretName` / `configMapName`; .NET apps expose an Npgsql
connection string named by `connectionStringEnv` instead of `DB_*` envs).
Nothing is written to any database.

### Storage

No PV/PVC. Each job pod gets a throwaway `emptyDir` scratch volume at `/tmp`
(`sizeLimit` 20Gi, matching the `ephemeral-storage` request/limit) where the
dump is assembled before upload; it is destroyed with the pod. Retention of
the uploaded files is the file server's concern — the chart enforces none.

### Routing / exposure (NGINX Gateway Fabric)

None — no Service, no HTTPRoute, no hostname. Egress only: the job pods must
be able to reach the configured transfer server (`mi.transfer.host`, port
`mi.transfer.port`, default 22 for the sftp modes / 21 for ftp) from the
cluster's egress range.

### Other dependencies

- **External SFTP or FTP(S) server** — the upload target. Configured in the
  unified `mi.transfer.*` section: `mode: sftp-password | sftp-key | ftp`
  plus `host/port/user/remotePath` (and `ftps: true` for FTPS). The
  chart-rendered `Secret/mi-export-transfer` carries the connection envvars.
- **One transfer credential** — matching the mode: `mi.transfer.privateKey`
  (sftp-key; rendered into `Secret/mi-export-transfer-key`, key `id`) or
  `mi.transfer.password` (sftp-password and ftp modes). Stored in Azure Key
  Vault as `mi-data-sftp-credential` and substituted at deploy time by the
  ExternalsPodiumD `application.yml` pipeline — never committed to git.
- No Redis, no Keycloak client, no SMTP, no inter-app secrets.

## CPU and memory

Per job pod, one container (`mi.resources`):

| Container | CPU request | Mem request | CPU limit | Mem limit | Ephemeral storage |
|-----------|-------------|-------------|-----------|-----------|-------------------|
| mi-export | 100m | 256Mi | 1000m | 1Gi | 20Gi request = limit |

Short-lived weekly jobs — no steady-state footprint. An oversized dump evicts
the pod (emptyDir `sizeLimit`), not the node; raise
`mi.resources.*.ephemeral-storage` plus the `tmp` volume `sizeLimit` in the
mi-data chart's `templates/cronjobs.yaml` together if a component outgrows
20 GiB.

## Integrating MI exports as a new app

1. **Transfer server:** ensure an SFTP or FTP(S) server is reachable from the
   cluster egress range, with the export user provisioned (keypair in
   `authorized_keys` for sftp-key mode, or a password).
2. **Key Vault:** store the credential (private key or password) as
   `mi-data-sftp-credential` (env-suffixed on the qa flavor).
3. **Values:** in `values-<env>.yml` set `mi.enabled: true`,
   `mi.gemeente: <env-name>`, `mi.transfer.mode`,
   `mi.transfer.{host,user,remotePath}`, and the placeholder
   `"REP_MI_DATA_SFTP_CREDENTIAL_REP"` in the credential field the mode
   expects (`privateKey` for sftp-key, `password` otherwise). The render
   fails fast if a required value is missing or the credential doesn't match
   the mode.
4. **Targets:** trim `mi.targets` to the components deployed in the env
   (untrimmed targets run as weekly no-ops); per-env opt-out via
   `mi.targets[].enabled: false`.
5. **Deploy** via the ExternalsPodiumD `application.yml` pipeline (substitutes
   the credential from Key Vault).
6. **Verify:** `kubectl -n podiumd get cronjob -l
   app.kubernetes.io/component=mi-export` lists one CronJob per target;
   trigger a run with `kubectl -n podiumd create job
   --from=cronjob/mi-export-openzaak mi-test-now`, watch its logs for
   `done: … packaged/uploaded`, and confirm the file landed on the server.
   Full validation steps: [§ Validation](../../../../mi-data/docs/mi-exports.md#4-validation).

## Related documents

- [`charts/mi-data/docs/mi-exports.md`](../../../../mi-data/docs/mi-exports.md)
  — the full operator guide in the mi-data chart: architecture diagram,
  transfer modes, host-key policy, output formats, activation walkthrough,
  troubleshooting table, changelog. Read it before enabling the feature in an
  environment.
- [`4.8.2-to-4.8.3-upgrade.md`](../../_UPGRADE_PATHS/4.8.2-to-4.8.3-upgrade.md)
  — the `mi.sftp.*` → `mi.transfer.*` migration table.
