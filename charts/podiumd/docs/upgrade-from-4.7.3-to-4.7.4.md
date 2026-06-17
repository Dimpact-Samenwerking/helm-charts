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
(`tag` + `digest`) and `images/images-4.7.4.yaml`. The 26.6.3 CRDs are
byte-identical to 26.6.2, so **no CRD apply or migration is required**; the
adfinis 1.12.0 chart bundles the matching 26.6.3 CRDs.

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
