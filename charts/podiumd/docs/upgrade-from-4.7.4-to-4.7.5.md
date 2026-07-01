# Upgrade guide: PodiumD 4.7.4 → 4.7.5

4.7.5 is a small patch release: it bumps the **ZGW Office Add-in** only. No
other components change.

## Changes

### ZGW Office Add-in `v0.9.289` → `v0.9.313`

- `zgw-office-addin` chart dependency `0.0.87` → `0.0.88` in
  `charts/podiumd/Chart.yaml`.
- Frontend and backend images bumped to `v0.9.313` (digest-pinned) in
  `charts/podiumd/values.yaml`.
- **Image repository names changed** `…-add-in-…` → `…-addin-…`:
  - `ghcr.io/infonl/zgw-office-addin-frontend`
  - `ghcr.io/infonl/zgw-office-addin-backend`

Image / digests: see [`docs/images/images-4.7.5.yaml`](images/images-4.7.5.yaml).

#### Action required

- **Standard image-pin update** — pins are already in `values.yaml` and
  `images/images-4.7.5.yaml`.
- **ACR-mirror environments:** because the repository names changed from
  `add-in` to `addin`, mirror the **new** repository names/tags
  (`zgw-office-addin-frontend` / `zgw-office-addin-backend` at `v0.9.313`).
  An existing mirror of the old `add-in` repositories will not be used by the
  new pins.
- No config, schema, or migration changes.
