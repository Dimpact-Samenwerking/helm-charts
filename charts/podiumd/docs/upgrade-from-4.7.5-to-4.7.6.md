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

### Open Formulieren — outgoing request logging re-enabled (revert of 4.7.4)

4.7.4 introduced `LOG_OUTGOING_REQUESTS=False` in `openformulieren.extraEnvVars` to
disable outgoing/external HTTP request logging by default. After further analysis this
override is **removed in 4.7.6**, reverting Open Formulieren to the upstream default
(`LOG_OUTGOING_REQUESTS=True` — logging enabled).

After upgrading, Open Formulieren pods will restart and outgoing requests will be
logged again (both the stdout handler and, if configured, the DB-save handler).

#### Action required

Operators who want to **keep outgoing request logging disabled** (the 4.7.4 behaviour)
must add the override in their per-gemeente `podiumd.yml`:

```yaml
openformulieren:
  extraEnvVars:
    - name: LOG_OUTGOING_REQUESTS
      value: "False"
```

No action is needed if logging outgoing requests is acceptable.

See [`upgrade-from-4.7.3-to-4.7.4.md`](upgrade-from-4.7.3-to-4.7.4.md) for the full
background on what `LOG_OUTGOING_REQUESTS` controls and how the DB-save handler
interacts with it.

### Open Beheer ↔ Objecttypen API token (IN-2345)

Open Beheer reads object types from the **Objecttypen API** and authenticates
with an API token. The token must be configured **on both sides with the exact
same secret**, `REP_OBJECTTYPEN_OPENBEHEER_TOKEN_REP` (Key Vault
`objecttypen-openbeheer-token`, pipeline var `OBJECTTYPEN_OPENBEHEER_TOKEN`):

- **Objecttypen** — a `tokenauth` item that grants Open Beheer the token:

  ```yaml
  objecttypen:
    configuration:
      data: |-
        tokenauth_config_enable: true
        tokenauth:
          items:
            - identifier: openbeheer
              token: {value_from: {env: objecttypen_openbeheer_token}}   # REP_OBJECTTYPEN_OPENBEHEER_TOKEN_REP
              contact_person: Dimpact
              email: servicedesk@dimpact.nl
  ```

- **Open Beheer** — the `objecttypen-service` consumer that *uses* the token.
  The header value **must** carry the literal `Token ` prefix:

  ```yaml
  openbeheer:
    configuration:
      data: |-
        zgw_consumers:
          services:
            - identifier: objecttypen-service
              api_root: https://<env>-objecttypen.<gemeente>.nl/api/v2/
              api_type: orc
              auth_type: api_key
              header_key: Authorization
              header_value: "Token REP_OBJECTTYPEN_OPENBEHEER_TOKEN_REP"   # 'Token ' prefix is required
  ```

Both are already in the chart `values.yaml` example blocks (objecttypen
`tokenauth` and openbeheer `zgw_consumers`); this is the same matching trap as
Open Archiefbeheer above — the token string must be identical on both ends.

#### What IN-2345 fixed (do not repeat)

- **Missing `Token ` prefix** on the Open Beheer `header_value` — it was just
  `REP_..._REP`. Objecttypen rejects a header without `Token `.
- **Mismatched secret name** — the two sides used different tokens
  (`OPENBEHEER_CREDENTIALS_OBJECTTYPEN_TOKEN` vs `OBJECTTYPEN_OPENBEHEER_TOKEN`).
  Standardise on **`OBJECTTYPEN_OPENBEHEER_TOKEN`** everywhere.

#### Action required

1. Provision the `objecttypen-openbeheer-token` secret in Key Vault and map it
   to `OBJECTTYPEN_OPENBEHEER_TOKEN` in the pipeline `application.yml` **in the
   shared/objecttypen section**, not only the openbeheer block — otherwise the
   `objecttypen-config` Job cannot substitute it.
2. **Only enable the objecttypen `openbeheer` tokenauth entry when Open Beheer
   is enabled and the secret is provisioned.** The `objecttypen-config` Job
   validates the token strictly and **fails on an unsubstituted `REP_..._REP`
   placeholder** — keep the entry commented out while openbeheer is disabled.
3. Configure both sides with the same secret and re-run the upgrade; confirm
   Open Beheer can list object types (no 401/403 against the Objecttypen API).
