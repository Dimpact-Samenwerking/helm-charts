# Upgrade guide: PodiumD 4.7.3 → 4.7.4


## Changes

### Keycloak 26.6.2 → 26.6.3 (security)

4.7.4 bumps the Keycloak server **and** operator images from `26.6.2` to `26.6.3`
and the adfinis `keycloak-operator` chart dependency from `1.11.4` to `1.12.0`
(`appVersion` 26.6.3). 26.6.3 is a security release fixing 16 CVEs, most
notably **CVE-2026-9704** (privilege escalation via token exchange),
**CVE-2026-4874** (SSRF on the OIDC token endpoint) and **CVE-2026-9802**
(revoked-refresh-token replay after a server restart).

#### Action required

None beyond the standard image-pin update — the pins are already in `values.yaml`
and `images/images-4.7.4.yaml`. The 26.6.3 CRDs are byte-identical to 26.6.2, so
**no CRD apply or migration is required**; the adfinis 1.12.0 chart bundles the
matching 26.6.3 CRDs.

> **Caveat — operator image digest pinning differs from every other image.**
> The operator image is rendered by the adfinis subchart, which builds the ref as
> `repository:tag@sha256:{{ operator.image.sha }}` using a **separate `sha`
> field** — not by appending a digest to the tag. So, unlike `keycloak.image`
> (and all other PodiumD images, which take `tag: "<ver>@sha256:<digest>"`), the
> operator's `tag` must be **just the version**:
>
> ```yaml
> keycloak-operator:
>   operator:
>     image:
>       tag: "26.6.3"        # NOT "26.6.3@sha256:…"
> ```
>
> Embedding `@sha256:` in the operator tag yields an invalid **double digest**
> (`…:26.6.3@sha256:xxx@sha256:xxx`) because the chart still appends its own
> `sha`. The adfinis 1.12.0 chart already ships the matching 26.6.3 digest as the
> default `operator.image.sha` (`sha256:bd128cd6…`), so `tag: "26.6.3"` alone
> renders the correctly digest-pinned ref.
>
> **Disabling digest pinning (the `sha`, not the tag) — may be required on
> aks-blue / ACR-mirror environments.** Where the operator image is pulled from a
> mirror (e.g. an ACR) whose manifest digest does not match quay's, the bundled
> `sha` pin will make the pull fail (`ImagePullBackOff` / manifest not found).
> Turn digest pinning **off** by clearing the `sha` so the image resolves by tag
> only:
>
> ```yaml
> keycloak-operator:
>   operator:
>     image:
>       tag: "26.6.3"
>       sha: ""            # disables the @sha256 digest pin -> ...:26.6.3
> ```
>
> This is an env-level override (e.g. for the `aks-blue-*` environments); the
> shared `values.yaml` keeps the digest pin on.

### Open Zaak 1.27.1 → 1.27.2 (security)

4.7.4 bumps the Open Zaak image from `1.27.1` to `1.27.2` (image-tag override; the
`openzaak` chart dependency stays `1.14.1`). 1.27.2 is a security release fixing:

- **CVE-2026-54657** (`GHSA-f29q-7rpr-jmjx`) — results from the `/zaken/_zoek` and
  `/enkelvoudiginformatieobjecten/_zoek` endpoints are now filtered according to
  the authorizations of the token used. Previously these search endpoints could
  return zaken/documenten beyond the caller's authorizations (broken access
  control). **Highest-impact fix in this release.**
- **`GHSA-x5cj-23hr-5r54`** (CVE pending) — path-traversal hardening in document
  bulk import: imports are now restricted to paths under
  `IMPORT_DOCUMENTEN_BASE_DIR`.

#### Action required

- **`/zoek` authorization fix** — no configuration needed. Be aware that a token
  which previously saw too many results will now correctly see **only** authorized
  ones; verify autorisaties are scoped as intended.
- **Document bulk import only** — the default `IMPORT_DOCUMENTEN_BASE_DIR` changed
  from `BASE_DIR` to `<BASE_DIR>/import-data` (`/app/import-data` in the container),
  and it **may no longer equal `BASE_DIR`**. PodiumD does not set this env var, so
  environments that do not use bulk import need **no action**. If you do use bulk
  import: ensure `IMPORT_DOCUMENTEN_BASE_DIR` is a subdirectory of `BASE_DIR` (not
  equal to it) and that import files live under `/app/import-data` (or your
  configured subdir).

### Outgoing/external request logging disabled by default (Open Formulieren)

4.7.4 disables outgoing/external HTTP request logging for **Open Formulieren** by
default, via the master switch **`LOG_OUTGOING_REQUESTS=False`** (set in
`values.yaml` under `openformulieren.extraEnvVars`, as the chart exposes no
structured key). With this off, Open Forms empties the `log_outgoing_requests`
logging handlers — it neither emits requests to the logs **nor** saves them to the
database, so nothing is logged on startup. `LOG_OUTGOING_REQUESTS_DB_SAVE` is left
at its upstream default (`False`) and is **not** changed by 4.7.4.

> **Open Inwoner has no equivalent switch.** At the deployed version (v2.1.2) Open
> Inwoner exposes **only** `LOG_OUTGOING_REQUESTS_DB_SAVE` (default `True`); there
> is no master `LOG_OUTGOING_REQUESTS` env var and its logging handlers are defined
> unconditionally. Outgoing-request logging therefore cannot be switched off
> entirely from the environment without also changing DB-save behaviour, so 4.7.4
> leaves Open Inwoner unchanged. To disable outgoing-request logging for Open
> Inwoner (DB persistence and/or the stdout emit handler), see
> [`openinwoner-outgoing-request-logging.md`](openinwoner-outgoing-request-logging.md).

#### Action required

- **None for the default.** On `helm upgrade` the Open Formulieren pods roll and
  pick up `LOG_OUTGOING_REQUESTS=False`; from then on outgoing requests are not
  logged. No data migration; existing log rows are not deleted.
- **The switch is a hard master — an admin cannot re-enable it from the UI.**
  `LOG_OUTGOING_REQUESTS=False` empties the `log_outgoing_requests` logger's handler
  list entirely (`handlers: []` in `conf/base.py`), so **neither** the stdout emit
  **nor** the DB-save handler is attached. The runtime admin model
  `OutgoingRequestsLogConfig` (Django admin → *Log outgoing requests* → *Outgoing
  requests log configuration*, field `save_to_db`) only governs whether the DB
  handler *writes* — but with the master off that handler is not attached, so
  setting `save_to_db = Always` has **no effect**. Logging stays off until the env
  switch is turned back on.
- **To re-enable outgoing-request logging for a specific environment**, override in
  that gemeente's values (the only way to re-enable):

  ```yaml
  openformulieren:
    extraEnvVars:
      - name: LOG_OUTGOING_REQUESTS
        value: "True"
  ```

  After the pods restart with this, DB persistence is then gated as normal by
  `LOG_OUTGOING_REQUESTS_DB_SAVE` (default `False`) and the runtime
  `OutgoingRequestsLogConfig.save_to_db` admin toggle.

### Add Datamigratie Keycloak client and Open Zaak secret

Datamigratie is deployed in a separate pipeline. But Datamigratie needs a connection to Open Zaak,
plus it needs a Keycloak Client, to allow user to log on. 

The PodiumD helm-chart includes these.

Update podiumd.yml for each gemeente
 

#### Action required

Verify if these 2 secrets exist in the Keyvault. If not, at them: 

`OPENZAAK_CREDENTIALS_DATAMIGRATIE_SECRET:   $(openzaak-credentials-datamigratie-secret)`

`DATAMIGRATIE_OIDC_SECRET:  $(datamigratie-oidc-secret)`


Update podiumd.yml for each gemeente, to add the Keycloak client for datamigratie, and
to add the Datamigratie application to Open Zaak. 

* In Keycloak, add client for Datamigratie

```
keycloak:
  ...
  config:
    ...
    clients:
      datamigratie:
        name: Datamigratie
        enabled: true
        secret: "REP_DATAMIGRATIE_OIDC_SECRET_REP"
        oidcUrl: "https://datamigratie.example.nl"

```

* In Open Zaak, add the application and the client secret for Datamigratie

```
openzaak:
  ...
  configuration:
    ...
    data: |
      ...
      vng_api_common_credentials:
        items:
          ...
          - identifier: datamigratie
            secret: "REP_OPENZAAK_CREDENTIALS_DATAMIGRATIE_SECRET_REP"  
      vng_api_common_applicaties_config_enable: true
      vng_api_common_applicaties:
        items:
          ...
          - uuid: dc69a5f8-c00a-4302-ada5-c67beddbc65c
            client_ids:
              - datamigratie
            heeft_alle_autorisaties: true
            label: Datamigratie
```

### Open Archiefbeheer `external_registers` must match the `zgw_consumers` service identifiers

> **Heads-up / action required — verify before upgrading.**

Open Archiefbeheer's `external_registers:` block references services **by their
identifier string**. Each register (`openklant`, `objecten`) lists
`services_identifiers`, and OAB resolves the register by an *exact* match
against the identifiers defined under `zgw_consumers.services`. There is no
fuzzy matching, so any mismatch makes that register fail to resolve — the
linked register (Open Klant / Objecten) silently does not work in OAB.

The trap: the identifiers in `external_registers` must equal the identifiers of
the `Service` entries actually provisioned in the environment.

- **Open Klant** — in **most** PodiumD environments this service was
  provisioned as **`openklant-api`**, *not* `openklant-klantinteracties`. An
  `external_registers` entry (or example config copied from elsewhere) pointing
  at `openklant-klantinteracties` while the provisioned service is
  `openklant-api` (or the reverse) cannot be resolved.
- **Objecten** — the same rule applies; the register's
  `services_identifiers` must match the Objecten service identifier (e.g.
  **`objecten-api`**).

#### Working example

The `services_identifiers` values below must be **identical** to the
`identifier` of the matching `zgw_consumers.services` entry:

```yaml
openarchiefbeheer:
  configuration:
    data: |-
      zgw_consumers_config_enable: true
      zgw_consumers:
        services:
        # ... other services ...
        - identifier: openklant-api          # <-- referenced below
          label: Klanten API
          api_root: https://openklant.example.com/klantinteracties/api/v1/
          api_type: kc
          auth_type: api_key
          header_key: Authorization
          header_value: "Token REP_OPENKLANT_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP"
        - identifier: objecten-api            # <-- referenced below
          label: Objecten API
          api_root: https://objecten.example.com/api/v2/
          api_type: orc
          auth_type: api_key
          header_key: Authorization
          header_value: "Token REP_OBJECTEN_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP"

      external_registers_enabled: true
      external_registers:
        openklant:
          enabled: true
          services_identifiers:
          - openklant-api                     # must equal the service identifier above
        objecten:
          enabled: true
          services_identifiers:
          - objecten-api                      # must equal the service identifier above
```

**Action required:**

1. Find the identifiers of the Open Klant and Objecten services provisioned in
   your environment (the `zgw_consumers.services[].identifier` values — commonly
   `openklant-api` and `objecten-api`).
2. Make every entry under `external_registers.*.services_identifiers` use
   **those exact identifiers**.
3. Re-run the `openarchiefbeheer-config` Job (helm upgrade) and confirm both
   registers resolve.

Do not assume the example values are correct — check the per-gemeente
`podiumd.yml` against what is actually provisioned. See
[`openarchiefbeheer-known-issues.md`](openarchiefbeheer-known-issues.md) for
other OAB configuration traps.
