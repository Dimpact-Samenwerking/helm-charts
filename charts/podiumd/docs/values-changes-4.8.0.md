# Values changes for PodiumD 4.8.0

Companion to (upgrade-from-4.6.5-to-4.7.0.md). This file lists every value override a gemeente `podiumd.yml` may need to add, change, or remove when moving from chart 4.7.X to 4.8.0. Application-level changes and migration scripts are documented in the upgrade guide; this file focuses purely on the values surface.

## TL;DR

| Component | Required action | Type |
|-----------|----------------|------|
| `ita.medewerker` | New required block | Required if ITA enabled |
| `zac.brpApi.apiKey` | String → object (`{header, value}`) | Required if ZAC enabled and key overridden |
| `zac.featureFlags.pabcIntegration` | Remove this key | Required if present in gemeente file |

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

## New optional fields



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

