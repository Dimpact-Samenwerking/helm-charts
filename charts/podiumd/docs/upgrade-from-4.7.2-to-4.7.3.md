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
- Egress is **SFTP only** (no blob storage). Auth via an SSH keypair. Host-key
  checking is intentionally **disabled** (`StrictHostKeyChecking=no`,
  `UserKnownHostsFile=/dev/null`): the jobs are short-lived, single-shot
  containers reaching a DNS-fixed host and the private key already gates login,
  so no `known_hosts` is mounted or required. See the *Host-key policy* section
  of the operator doc.
- **The chart renders both SFTP Secrets itself** from `mi.sftp.*` values
  (`mi-export-sftp` connection envvars + `mi-export-sftp-key` private key) —
  nothing is pre-provisioned in the namespace. The private key is supplied via
  `mi.sftp.privateKey`; the ExternalsPodiumD `application.yml` pipeline
  substitutes it from Azure Key Vault (`mi-data-sftp-rsa-private-key`) at deploy
  time, so it never lands in git.
- 20 GiB scratch budget on `/tmp` (`emptyDir.sizeLimit` plus matching
  `ephemeral-storage` requests/limits); pods are evicted before they can
  hurt the node.

Full operator documentation: [`docs/podiumd/mi-exports.md`](../../../docs/podiumd/mi-exports.md).

#### Action required

**Disabled by default** — the feature is fully opt-in, so existing envs see
no behavioural change after the upgrade. To enable in an env:

1. **Provision the SFTP target side**: ensure a reachable SFTP server and
   install the gemeente's SSH public key in `authorized_keys`. No `known_hosts`
   capture is needed (host-key checking is disabled).
2. **Store the SSH private key in Key Vault** as `mi-data-sftp-rsa-private-key`.
   The `application.yml` pipeline reads it and substitutes it into the env
   values file's `mi.sftp.privateKey` placeholder at deploy time. No K8s Secrets
   need to be staged — the chart renders `mi-export-sftp` + `mi-export-sftp-key`
   from the values.
3. **Set values** in the env's values file:
   ```yaml
   mi:
     enabled: true
     gemeente: <env-name>
     sftp:
       host: sftp.example.com
       user: miuser
       remotePath: /mi-exports
       privateKey: "REP_MI_DATA_SFTP_RSA_PRIVATE_KEY_REP"  # pipeline substitutes from KV
   ```
4. Validate per the [§ Validation](../../../docs/podiumd/mi-exports.md#4-validation)
   section of the operator doc.

> **Note on Azure Blob SFTP targets:** if the SFTP user's `homeDirectory` is a
> blob container, the user is chrooted into it — set `mi.sftp.remotePath` to a
> path *inside* that container (e.g. `/mi-exports`), not `/<container>/...`.

### Open Archiefbeheer

No new image. But for Open Archiefbeheer 2.0.0 it is necessary to add services for Objecten en Open Klant in Open Arhiefbheer. 

#### Action required

Add 2 new secrets to the keyvault of each gemeente: 

`OBJECTEN_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN:   $(objecten-credentials-openarchiefbeheer-token)`

`OPENKLANT_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN:  $(openklant-credentials-openarchiefbeheer-token)`


Update podiumd.yml for each gemeente, with values to configure the necessary Services to Objecten en Open Klant

- In Objecten, add Token Auth for OpenArchiefbeheer

```
objecten:
  configuration:
    ...
    data: |
      ...
      tokenauth_config_enable: true
      tokenauth:
        items:
          ...
          - identifier: openarchiefbeheer
            token: "REP_OBJECTEN_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP"
            contact_person: Dimpact
            email: servicedesk@dimpact.nl
```

- In Open Archiefbeheer, add 2 services for Objecten en OpenKlant

```
openarchiefbeheer:
  ...
  configuration:
    ...
    data: |
      zgw_consumers_config_enable: true
      zgw_consumers:
        services:
        ...
        - identifier: objecten-api
          label: Objecten API
          api_root: https://objecten.example.com/api/v2/
          api_type: orc
          auth_type: api_key
          header_key: Authorization
          header_value: "Token REP_OBJECTEN_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP"
        - identifier: klanten-api
          label: Klanten API
          api_root: https://opeklant.example.com/klantinteracties/api/v1/
          api_type: kc
          auth_type: api_key
          header_key: Authorization
          header_value: "Token REP_OPENKLANT_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP"
       
```

- In Open Klant, add Token Auth for OpenArchiefbeheer

```
openklant:
  configuration:
    ...
    data: |
      tokenauth_config_enable: true
      tokenauth:
        items:
          ...
          - identifier: openarchiefbeheer
            token: "REP_OPENKLANT_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP"
            contact_person: Dimpact
            email: servicedesk@dimpact.nl
```
