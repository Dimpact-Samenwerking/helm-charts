# MI exports — Basics

## Management summary

MI (Management Information) exports give the municipality a weekly copy of the
data in its PodiumD applications, for reporting and analytics outside the
platform. Every Sunday night the cluster dumps the database of each deployed
application and uploads the result to a file server (SFTP) chosen by the
municipality, where analysts or downstream systems can pick it up. The feature
is off by default and switched on per environment; it needs no extra servers
inside the cluster — only a reachable SFTP server and one stored credential.
Footprint is small: short-lived weekly jobs, no always-on components.

## What it is

- **Upstream:** none — this is chart-native tooling, not a deployed
  application. The export container runs the stock
  `mcr.microsoft.com/azure-cli:2.71.0` image (`mi.image.*` in `values.yaml`)
  and installs `postgresql` client tools at job start.
- **Deployed via:** the podiumd chart's own templates (no subchart):
  - `templates/mi-export-cronjobs.yaml` — one CronJob per target component;
  - `templates/mi-export-scripts.yaml` — ConfigMap `mi-export-scripts`
    (`dump.sh`);
  - `templates/mi-export-sftp-secret.yaml` — the SFTP Secrets.
- **Enable flag:** `mi.enabled` (default `false` — opt-in per environment).
- **Runtime components:**
  - `CronJob/mi-export-<component>` — one per entry in `mi.targets[]` whose
    `<component>.enabled` is true (up to 13: openzaak, opennotificaties,
    objecten (now also covers what used to be the separate `objecttypen`
    target, merged into one app), openarchiefbeheer, openklant,
    openformulieren, openinwoner, referentielijsten, openbeheer, zac, ita,
    kiss, pabc).
    Default schedule `0 2 * * 0` (Sunday 02:00 Europe/Amsterdam),
    `concurrencyPolicy: Forbid`, jobs auto-cleaned after 24 h
    (`ttlSecondsAfterFinished: 86400`). No Deployments, StatefulSets or
    always-on pods.

Each job dumps its component's Postgres database (per-table `;`-separated
CSVs in a `.tar.gz`, or a single `pg_dump -Fc` file — env-wide
`mi.format: csv | pgdump`) and uploads it over SFTP to
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
the uploaded files is the SFTP server's concern — the chart enforces none.

### Routing / exposure (NGINX Gateway Fabric)

None — no Service, no HTTPRoute, no hostname. Egress only: the job pods must
be able to reach the configured SFTP server (`mi.sftp.host`, port
`mi.sftp.port`, default 22) from the cluster's egress range.

### Other dependencies

- **External SFTP server** — the upload target. Connection values
  `mi.sftp.{host,port,user,remotePath}`; chart-rendered
  `Secret/mi-export-sftp` carries them as `SFTP_*` envvars.
- **One SFTP credential** — exactly one of `mi.sftp.privateKey` (SSH keypair;
  rendered into `Secret/mi-export-sftp-key`, key `id`) or `mi.sftp.password`
  (password mode, chart 4.8.1+; rendered as `SFTP_PASSWORD`). Stored in Azure
  Key Vault as `mi-data-sftp-credential` and substituted at deploy time by the
  ExternalsPodiumD `application.yml` pipeline — never committed to git.
- No Redis, no Keycloak client, no SMTP, no inter-app secrets.

## CPU and memory

Per job pod, one container (`mi.resources` in `values.yaml`):

| Container | CPU request | Mem request | CPU limit | Mem limit | Ephemeral storage |
|-----------|-------------|-------------|-----------|-----------|-------------------|
| mi-export | 100m | 256Mi | 1000m | 1Gi | 20Gi request = limit |

Short-lived weekly jobs — no steady-state footprint. An oversized dump evicts
the pod (emptyDir `sizeLimit`), not the node; raise
`mi.resources.*.ephemeral-storage` plus the `tmp` volume `sizeLimit` in
`templates/mi-export-cronjobs.yaml` together if a component outgrows 20 GiB.

## Integrating MI exports as a new app

1. **SFTP server:** ensure one is reachable from the cluster egress range,
   with the export user provisioned (keypair in `authorized_keys`, or a
   password — e.g. Azure Blob SFTP local users).
2. **Key Vault:** store the credential (private key or password) as
   `mi-data-sftp-credential` (env-suffixed on the qa flavor).
3. **Values:** in `values-<env>.yml` set `mi.enabled: true`,
   `mi.gemeente: <env-name>`, `mi.sftp.{host,user,remotePath}`, and the
   placeholder `"REP_MI_DATA_SFTP_CREDENTIAL_REP"` in exactly one of
   `mi.sftp.privateKey` / `mi.sftp.password`. The render fails fast if a
   required value is missing or both/neither credentials are set.
4. **Targets:** normally untouched — a target only renders a CronJob when its
   `<component>.enabled` is true. Per-env opt-out via
   `mi.targets[].enabled: false`.
5. **Deploy** via the ExternalsPodiumD `application.yml` pipeline (substitutes
   the credential from Key Vault).
6. **Verify:** `kubectl -n podiumd get cronjob -l
   app.kubernetes.io/component=mi-export` lists one CronJob per enabled
   component; trigger a run with `kubectl -n podiumd create job
   --from=cronjob/mi-export-openzaak mi-test-now`, watch its logs for
   `done: … packaged/uploaded`, and confirm the file landed on the SFTP
   server. Full validation steps: [§ Validation](../../misc/mi-exports.md#4-validation).

## Related documents

- [`../../misc/mi-exports.md`](../../misc/mi-exports.md) — the full operator
  guide: architecture diagram, credential modes, host-key policy, output
  formats, activation walkthrough, troubleshooting table, changelog. Read it
  before enabling the feature in an environment. (Kept under `docs/misc/`
  because upgrade-path guides and the architecture overview link to it there.)
