# Values changes for PodiumD 4.9.0

> **Baseline:** written against `feature/podiumd-4.8.0 @ c68bfc1` (2026-06-26).
> Re-verify before release:
> `git diff c68bfc1..feature/podiumd-4.8.0 -- charts/podiumd/Chart.yaml charts/podiumd/values.yaml`

Companion to [upgrade-from-4.8.0-to-4.9.0.md](upgrade-from-4.8.0-to-4.9.0.md). This file lists every value override a gemeente `podiumd.yml` may need to add, change, or remove when moving from chart 4.8.0 to 4.9.0. Application-level changes and migration scripts are documented in the upgrade guide; this file focuses purely on the values surface.

## TL;DR

| Component | Required action | Type |
|-----------|----------------|------|
| `zac.brpApi.apiKey` | Restructure from string to object | **Required** if ZAC enabled |
| `zac.featureFlags.pabcIntegration` | Remove key | Cleanup |

## Required changes

### 1. `zac.brpApi.apiKey` — string → object

ZAC 5.1.0 changes the BRP API key from a plain string to a structured object.
**Any environment values file that overrides this key must be updated.**

```yaml
# Before (4.8.0)
zac:
  brpApi:
    apiKey: "your-api-key"

# After (4.9.0)
zac:
  brpApi:
    apiKey:
      header: "x-api-key"
      value: "your-api-key"
```

The `header` field specifies the HTTP header name used to pass the key; `x-api-key` is the correct value for the BRP providers in use. Only override `header` if your environment uses a different header name.

## Cleanup

### 2. Remove `zac.featureFlags.pabcIntegration`

PABC integration is now always enabled in ZAC 5.1.0; the flag no longer exists upstream. Remove it from all environment values files to avoid confusion:

```yaml
# Remove this block entirely:
zac:
  featureFlags:
    pabcIntegration: false
```

## New optional fields

None in 4.9.0.

## Cleanup — image tag overrides

The chart `values.yaml` already pins the new versions. Remove explicit tag overrides in gemeente files when they merely repeated a 4.8.0 value, otherwise bump to:

| Component | Key | New default tag |
|-----------|-----|----------------|
| ZAC | `zac.image.tag` | `5.1.0@sha256:d833d2f3...` |
| ZAC nginx | `zac.nginx.image.tag` | `1.31.1@sha256:9f6b3206...` |
| ZAC gotenberg | `zac.office_converter.image.tag` | `8.33.0@sha256:bddd8ea9...` |
| ZAC OPA | `zac.opa.image.tag` | `1.17.1-static@sha256:c29f8ee8...` |
| ZAC busybox | `zac.solr.busyBoxImage.tag` | `1.38.0-glibc@sha256:3ba03033...` |
| ZGW Office Add-in frontend | `zgw-office-addin.frontend.image.tag` | `v0.9.329@sha256:0ba74d8f...` |
| ZGW Office Add-in backend | `zgw-office-addin.backend.image.tag` | `v0.9.329@sha256:c9ffae04...` |

## Pre-deploy checklist

- [ ] `zac.brpApi.apiKey` restructured to `{header, value}` in all environment values files
- [ ] `zac.featureFlags.pabcIntegration` removed from all environment values files
- [ ] New ZAC and ZGW Office Add-in images mirrored to ACR (see [images-4.9.0.yaml](images/images-4.9.0.yaml))
- [ ] ACR mirror entries created for renamed repositories: `zgw-office-addin-frontend` and `zgw-office-addin-backend`
