# Upgrade guide: PodiumD 4.8.0 → 4.9.0

> **Baseline:** written against `feature/podiumd-4.8.0 @ 27a68aa` (2026-06-28).
> Re-verify before release:
> `git diff 27a68aa..feature/podiumd-4.8.0 -- charts/podiumd/Chart.yaml charts/podiumd/values.yaml`

> See the Confluence Releases page for the agreed application
> targets: <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.

## Component versions

| Component | App version | Helm chart | |
|---|---|---|---|
| ZAC | 5.1.0 | 1.0.257 | **breaking config change** |
| ZGW Office Add-in | v0.9.352 | 0.0.88 | ACR mirror rename required |

## Changes

### ZAC 4.7.1 → 5.1.0 (chart 1.0.228 → 1.0.257)

PodiumD 4.9.0 upgrades **ZAC (Zaakafhandelcomponent)** from 4.7.1 to 5.1.0.

- Helm chart `zaakafhandelcomponent` `1.0.228` → `1.0.257` in `charts/podiumd/Chart.yaml`.
- Image tag pin `zac.image.tag` `4.7.1` → `5.1.0` in `charts/podiumd/values.yaml`.

Image / digest: see [`docs/images/images-4.9.0.yaml`](images/images-4.9.0.yaml).

#### Breaking config change: `brpApi.apiKey`

ZAC 5.1.0 changes the BRP API key configuration from a plain string to a
structured object with `header` and `value` fields.

**Action required:** update all environment values files that override
`zac.brpApi.apiKey`:

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

The `header` value (`x-api-key`) matches the default used by the BRP API
providers in use. Adjust if your environment uses a different header name.

#### Removed: `featureFlags.pabcIntegration`

The `zac.featureFlags.pabcIntegration` flag has been removed upstream — PABC
integration is now always enabled in ZAC 5.1.0. Remove this key from any
environment values files that set it:

```yaml
# Remove this block entirely:
zac:
  featureFlags:
    pabcIntegration: false
```

#### ZAC sidecar image bumps

The following ZAC sidecar images were updated as part of the 5.1.0 chart:

| Image | 4.8.0 | 4.9.0 |
|---|---|---|
| nginx-unprivileged | 1.30.2 | 1.31.1 |
| gotenberg | 8.31.0 | 8.33.0 |
| opa | 1.15.2-static | 1.17.1-static |
| busybox (Solr init) | 1.37.0-glibc | 1.38.0-glibc |

Mirror all of the above to ACR. Digests: see
[`docs/images/images-4.9.0.yaml`](images/images-4.9.0.yaml).

---

### ZGW Office Add-in v0.9.313 → v0.9.352 (chart 0.0.88, unchanged)

PodiumD 4.9.0 upgrades the **ZGW Office Add-in** frontend and backend from
`v0.9.313` to `v0.9.352`. The Helm chart version remains `0.0.88`.

- Image tag pins `zgw-office-addin.frontend.image.tag` and
  `zgw-office-addin.backend.image.tag` updated in `charts/podiumd/values.yaml`.

#### ACR mirror rename

The upstream image repository names changed — the hyphen between `add` and `in`
was dropped:

| Component | Old repository | New repository |
|---|---|---|
| Frontend | `ghcr.io/infonl/zgw-office-add-in-frontend` | `ghcr.io/infonl/zgw-office-addin-frontend` |
| Backend | `ghcr.io/infonl/zgw-office-add-in-backend` | `ghcr.io/infonl/zgw-office-addin-backend` |

**Action required:** mirror the new images under the new ACR names
(`zgw-office-addin-frontend` and `zgw-office-addin-backend`). The old ACR
entries (`zgw-office-add-in-*`) can be retained for reference but are no longer
used. Digests: see [`docs/images/images-4.9.0.yaml`](images/images-4.9.0.yaml).
