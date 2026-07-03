# Upgrade guide: PodiumD 4.7.6 → 4.7.7

4.7.7 is a small patch release: it bumps **Open Zaak** only. No other
components change.

## Changes

### Open Zaak `1.27.2` → `1.27.3`

- Image tag override updated to `1.27.3` (digest-pinned) in
  `charts/podiumd/values.yaml`. The `openzaak` chart dependency stays `1.14.1`.

Image / digest: see [`docs/images/images-4.7.7.yaml`](images/images-4.7.7.yaml).

#### Action required

- **Standard image-pin update** — the pin is already in `values.yaml` and
  `images/images-4.7.7.yaml`.
- **ACR-mirror environments:** mirror `docker.io/openzaak/open-zaak:1.27.3`.
- No config, schema, or migration changes.
