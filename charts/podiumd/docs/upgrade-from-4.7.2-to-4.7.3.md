# Upgrade guide: PodiumD 4.7.2 → 4.7.3

> See the Confluence Releases page for the agreed application
> targets: <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.

## Changes

### MI exports — weekly Postgres dumps over SFTP

PodiumD 4.7.3 ships the first iteration of **Management Information (MI) data
exports** — weekly per-component Postgres dumps uploaded over SFTP. The
feature combines work from [IN-1650](https://dimpact.atlassian.net/browse/IN-1650)
(dump generator) and [IN-2119](https://dimpact.atlassian.net/browse/IN-2119)
(SFTP egress, semicolon CSV separator).

Highlights:

- One `mi-export-<component>` CronJob per enabled Postgres-backed app
  (openzaak, opennotificaties, objecten, …, zac, kiss, pabc — 14 default
  targets, each gated on the component's own `enabled` flag).
- Two output formats, env-wide via `mi.format`:
  - `csv` (default) — one `.tar.gz` per component, containing one `;`-separated
    CSV per table with a header row.
  - `pgdump` — one `pg_dump -Fc` file per component (DR / restore).
- Egress is **SFTP only** (no blob storage). Auth via an SSH keypair sourced
  from Azure Key Vault. Host-key checking is intentionally **disabled**
  (`StrictHostKeyChecking=no`, `UserKnownHostsFile=/dev/null`): the jobs are
  short-lived, single-shot containers reaching a DNS-fixed host and the private
  key already gates login, so no `known_hosts` is mounted or required. See the
  *Host-key policy* section of the operator doc.
- 20 GiB scratch budget on `/tmp` (`emptyDir.sizeLimit` plus matching
  `ephemeral-storage` requests/limits); pods are evicted before they can
  hurt the node.
- Dev/test sandboxes can bypass the Key-Vault flow via `mi.sftp.testMode`,
  which renders both the connection Secret and the key Secret inline from
  values.

Full operator documentation: [`docs/podiumd/mi-exports.md`](../../../docs/podiumd/mi-exports.md).

#### Action required

**Disabled by default** — the feature is fully opt-in, so existing envs see
no behavioural change after the upgrade. To enable in an env:

1. **Provision the SFTP target side first**: ensure a reachable SFTP server and
   install the gemeente's SSH public key in `authorized_keys`. No `known_hosts`
   capture is needed (host-key checking is disabled).
2. **Stage two K8s Secrets in the `podiumd` namespace** before the chart
   apply (Dimpact dev/test envs: the `podiumd-infra` `sync-mi-export-sftp-secret.sh`
   script materialises them from Key Vault; external-hosted prod: replicate
   in the provider's own Terraform):
   - `mi-export-sftp` — envvars `SFTP_HOST`, `SFTP_PORT`, `SFTP_USER`,
     `SFTP_REMOTE_PATH`.
   - `mi-export-sftp-key` — single key `id` (PEM private key).
3. **Set values** in the env's `values-<env>.yml`:
   ```yaml
   mi:
     enabled: true
     gemeente: <env-name>
     sftp:
       host: sftp.example.com
       user: miuser
       remotePath: /uploads/mi-exports
   ```
4. Validate per the [§ Validation](../../../docs/podiumd/mi-exports.md#4-validation)
   section of the operator doc.

For a dev sandbox without any Key-Vault setup, set `mi.sftp.testMode.enabled: true`
and inline `privateKey` in values — never in prod values. (`knownHosts` is no
longer used.)

> **Note on Azure Blob SFTP targets:** if the SFTP user's `homeDirectory` is a
> blob container, the user is chrooted into it — set `mi.sftp.remotePath` to a
> path *inside* that container (e.g. `/mi-exports`), not `/<container>/...`.

### Other changes

None.
