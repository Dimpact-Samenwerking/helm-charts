# Values changes for PodiumD 4.9.0

> **Baseline:** written against `feature/podiumd-4.8.0 @ c56fc33` (2026-07-06).
> Re-verify before release:
> `git diff c56fc33..feature/podiumd-4.8.0 -- charts/podiumd/Chart.yaml charts/podiumd/values.yaml`

Companion to [upgrade-from-4.8.0-to-4.9.0.md](upgrade-from-4.8.0-to-4.9.0.md). This file lists every value override a gemeente `podiumd.yml` may need to add, change, or remove when moving from chart 4.8.0 to 4.9.0. Application-level changes and migration scripts are documented in the upgrade guide; this file focuses purely on the values surface.

## TL;DR

| Component | Required action | Type |
|-----------|----------------|------|
| ZAC + ZGW Office Add-in | Mirror new images to ACR | Required |

## Required changes

None. All breaking changes from ZAC 5.x are already in 4.8.0 — see
[values-changes-4.8.0.md](values-changes-4.8.0.md) (§2, §3, §4).

## New optional fields

None in 4.9.0.

## Cleanup — image tag overrides

The chart `values.yaml` already pins the new versions. Remove explicit tag overrides in gemeente files when they merely repeated a 4.8.0 value, otherwise bump to:

| Component | Key | New default tag |
|-----------|-----|----------------|
| ZAC | `zac.image.tag` | `5.1.0@sha256:d833d2f3...` |
| ZGW Office Add-in frontend | `zgw-office-addin.frontend.image.tag` | `v0.9.352@sha256:bf248581...` |
| ZGW Office Add-in backend | `zgw-office-addin.backend.image.tag` | `v0.9.352@sha256:c5bf9a7b...` |

## Pre-deploy checklist

- [ ] New ZAC and ZGW Office Add-in images mirrored to ACR (see [images-4.9.0.yaml](images/images-4.9.0.yaml))
