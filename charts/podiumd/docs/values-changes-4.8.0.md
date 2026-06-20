# Values changes for PodiumD 4.8.0

Companion to (upgrade-from-4.6.5-to-4.7.0.md). This file lists every value override a gemeente `podiumd.yml` may need to add, change, or remove when moving from chart 4.7.X to 4.8.0. Application-level changes and migration scripts are documented in the upgrade guide; this file focuses purely on the values surface.

## TL;DR

| Component | Required action | Type |
|-----------|----------------|------|
| `ita.medewerker` | New required block | Required if ITA enabled |
|  |  |  |

## Required changes

### 1. ITA new required environment specific values

```yaml
ita:
  ...
  medewerker:
    type: "https://<env>-objecttypen.<gemeente>.nl/api/v2/objecttypes/REP_CONTACT_MEDEWERKER_UUID_REP"    # -- Version of the medewerker objecttype that is used, most likely: 1 
    typeVersion: 1    
```

## New optional fields



## Cleanup — image tag overrides

The chart `values.yaml` already pins the new versions. Remove explicit tag overrides in gemeente files when they merely repeated a 4.6.x value, otherwise bump to:

| Component | New default tag |
|-----------|----------------|
|  |  |


## Pre-deploy checklist

