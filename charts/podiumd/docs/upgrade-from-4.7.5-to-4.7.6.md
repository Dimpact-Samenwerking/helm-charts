# Upgrade guide: PodiumD 4.7.5 → 4.7.6

4.7.6 is a documentation/configuration-hardening patch. No image bumps.

## Changes

### Open Archiefbeheer `external_registers` — objecten-api + openklant-api matching

4.7.6 completes the Open Archiefbeheer (OAB) `external_registers` example in
`values.yaml` and fixes a typo in the OpenKlant `api_root` of several older
upgrade guides (`opeklant` → `openklant`).

OAB resolves each external register by an **exact** match between the
identifiers under `external_registers.<register>.services_identifiers` and the
`identifier` of a `zgw_consumers.services` entry. There is no fuzzy matching, so
any mismatch silently breaks that register's link (the linked Open Klant /
Objecten register does not work in OAB, with no error at config time).

Two registers are wired in the example:

- **objecten** → `objecten-api` (service `api_type: orc`, api_key auth).
- **openklant** → `openklant-api` (service `api_type: kc`, api_key auth). In
  **most** PodiumD environments this service was provisioned as `openklant-api`,
  **not** `openklant-klantinteracties`. An example copied from elsewhere that
  points at `openklant-klantinteracties` while the provisioned service is
  `openklant-api` (or the reverse) cannot be resolved.

Working example (the `services_identifiers` values must be **identical** to the
`identifier` of the matching `zgw_consumers.services` entry):

```yaml
openarchiefbeheer:
  configuration:
    data: |-
      zgw_consumers_config_enable: true
      zgw_consumers:
        services:
        # ... other services ...
        - identifier: objecten-api            # <-- referenced below
          label: Objecten API
          api_root: https://objecten.example.com/api/v2/
          api_type: orc
          auth_type: api_key
          header_key: Authorization
          header_value: "Token REP_OBJECTEN_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP"
        - identifier: openklant-api           # <-- referenced below (NOT openklant-klantinteracties)
          label: Klanten API
          api_root: https://openklant.example.com/klantinteracties/api/v1/
          api_type: kc
          auth_type: api_key
          header_key: Authorization
          header_value: "Token REP_OPENKLANT_CREDENTIALS_OPENARCHIEFBEHEER_TOKEN_REP"

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

#### Action required

1. Find the identifiers of the Open Klant and Objecten services provisioned in
   your environment (the `zgw_consumers.services[].identifier` values — commonly
   `openklant-api` and `objecten-api`).
2. Make every entry under `external_registers.*.services_identifiers` use
   **those exact identifiers**.
3. Re-run the `openarchiefbeheer-config` Job (`helm upgrade`) and confirm both
   registers resolve.

Do not assume the example values are correct — check the per-gemeente
`podiumd.yml` against what is actually provisioned. This is the same trap first
documented in [`upgrade-from-4.7.3-to-4.7.4.md`](upgrade-from-4.7.3-to-4.7.4.md);
4.7.6 only corrects/completes the in-repo example. See
[`openarchiefbeheer-known-issues.md`](openarchiefbeheer-known-issues.md) for
other OAB configuration traps.
