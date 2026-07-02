# Values changes for PodiumD 4.8.0

Companion to (upgrade-from-4.6.5-to-4.7.0.md). This file lists every value override a gemeente `podiumd.yml` may need to add, change, or remove when moving from chart 4.7.X to 4.8.0. Application-level changes and migration scripts are documented in the upgrade guide; this file focuses purely on the values surface.

## TL;DR

| Component | Required action | Type |
|-----------|----------------|------|
| `pabc.enabled` | Now defaults to `true` — provision an external DB or opt out | Required (see §5) |
| `ita.medewerker` | New required block | Required if ITA enabled |
| `zac.brpApi.apiKey` | String → object (`{header, value}`) | Required if ZAC enabled and key overridden |
| `zac.featureFlags.pabcIntegration` | Remove this key | Required if present in gemeente file |
| `zac.brpApi.protocollering` | Full restructure — see below | Required if protocollering was configured |
| `zac.brpApi.logLevel` | New field (default `"OFF"`) | Optional |
| `apiproxy.locations.brp.toepassingHeaderName` | Set to `""` — ZAC now owns this header via protocollering | Required for iConnect |

## Required changes

### 1. ITA new required environment specific values

```yaml
ita:
  ...
  medewerker:
    type: "https://<env>-objecttypen.<gemeente>.nl/api/v2/objecttypes/REP_CONTACT_MEDEWERKER_UUID_REP"    # -- Version of the medewerker objecttype that is used, most likely: 1 
    typeVersion: 1    
```

### 2. ZAC `brpApi.apiKey` — string to object (ZAC 5.0.1)

ZAC 5.x changed `brpApi.apiKey` from a plain string to a structured object.
If your gemeente file overrides this value, update it:

```yaml
# before (4.7.x)
zac:
  brpApi:
    apiKey: "your-api-key"

# after (5.0.1)
zac:
  brpApi:
    apiKey:
      header: "x-api-key"
      value: "your-api-key"
```

If the key is **not** overridden in your gemeente file, no action is needed —
the chart default already has the new structure.

### 3. ZAC `featureFlags.pabcIntegration` — removed (ZAC 5.0.1)

ZAC 5.x removed this feature flag entirely. If your gemeente file contains:

```yaml
zac:
  featureFlags:
    pabcIntegration: true   # or false
```

remove the entire `featureFlags.pabcIntegration` key (and `featureFlags:`
block if it becomes empty). Leaving it in place causes a Helm validation
error on deploy.

### 4. ZAC `brpApi.protocollering` — restructured (ZAC 5.0.1)

The entire protocollering block was redesigned. The `aanbieder` selector is
removed; each protocol dimension now has explicit header/value fields.

**Removed keys:**

| Key | Action |
|---|---|
| `zac.brpApi.protocollering.aanbieder` | Remove; replaced by `enabled` + explicit fields |
| `zac.brpApi.protocollering.verwerkingsregister` | Rename to `protocollering.verwerking.register` |

**New keys:** `zac.brpApi.logLevel`, `protocollering.enabled`,
`protocollering.systemUser`, `protocollering.originOin.{oin,header}`,
`protocollering.doelbinding.{perZaaktype,header}`,
`protocollering.verwerking.header`, `protocollering.gebruiker.header`,
`protocollering.toepassing.{header,value}`.

For full vendor-specific YAML blocks (iConnect, eServices, 2Secure/EnableU)
see [`docs/zac-brp-protocollering.md`](zac-brp-protocollering.md).

If protocollering was off (`aanbieder: ""`), replace with:

```yaml
zac:
  brpApi:
    protocollering:
      enabled: false
```

### 5. PABC enabled by default (`pabc.enabled: true`)

The chart default for `pabc.enabled` flipped from `false` to `true`, so the
PABC (PodiumD Autorisatie Beheer Component) subchart now deploys unless you
opt out. The bundled PostgreSQL is **off** (`pabc.postgresql.enabled: false`),
so PABC needs an external database. Provision one and set:

```yaml
pabc:
  enabled: true
  settings:
    database:
      host: "<pabc-db-host>"
      name: "pabc"
      username: "pabc"
      password: "<pabc-db-password>"
```

To keep PABC off (4.7.x behaviour), set `pabc.enabled: false` in your gemeente
file. Leaving it enabled without a reachable DB → PABC pods crashloop.

## New optional fields

None new in 4.8.0 beyond the component-specific keys documented above.

## Cleanup — image tag overrides

The chart `values.yaml` already pins the new versions. Remove explicit tag overrides in gemeente files when they merely repeated a 4.7.x value, otherwise bump to:

| Component | New default tag |
|-----------|----------------|
| `zac.image.tag` | `5.0.1@sha256:8c7844248b7decf56eafc0d2aca1f9e080f94e9bf2f6b6ac412589deb80d1659` |
| `*.nginx.image.tag` (all components) | `1.31.1@sha256:9f6b32064a29d747404d959e078c713a0523a9bd4e41f6912058126ebca94e61` |
| `zac.office_converter.image.tag` | `8.33.0@sha256:bddd8ea9d076e2d08b6ddaa6efae6403185202c6dab65a6488ed0a6923d6d8e8` |
| `zac.opa.image.tag` | `1.17.1-static@sha256:c29f8ee8dbe66608a1c04e9be84b04efc46877625e6b0877e559954565209efc` |
| `zac.solr.busyBoxImage.tag` | `1.38.0-glibc@sha256:3ba030337caebbfc2232b22b1e435eb213b28e5844a34942c74555bf904a265a` |


## Pre-deploy checklist

- [ ] **PABC** (§5): either provision an external DB and set
      `pabc.settings.database.{host,name,username,password}`, or set
      `pabc.enabled: false` to opt out. Default is now enabled.
- [ ] **Open Notificaties**: chart 2.0.0 removes RabbitMQ (broker → redis-ha
      db6). Before upgrading, drain RabbitMQ queues; after upgrading, delete the
      orphaned `*-opennotificaties-rabbitmq` PVC + secret. See the upgrade guide.
- [ ] **ITA** (§1): set `ita.medewerker.type` to the environment-specific
      Medewerker objecttype URL (render fails fast if left blank while ITA is enabled).
- [ ] **zgw-office-addin**: override `common.frontendUrl` and
      `backend.zgwApis.url` (chart defaults are example hosts) plus
      `msalClientId`/`msalTenantId`/`msalSecret` in the gemeente values. Leave
      `common.appEnv: "production"` unless this is a non-prod add-in instance
      (see upgrade guide).
- [ ] **Redis**: expect a rolling restart of the 3-node redis-ha cluster on
      upgrade (label add + redis-operator 0.24→0.25); brief sentinel failover.

