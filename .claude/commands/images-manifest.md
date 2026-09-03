Create an images manifest for a podiumd release.

Usage: `/images-manifest <version>` (e.g. `/images-manifest 4.7.1`)

Output path:
```
charts/podiumd/docs/images/images-$ARGUMENTS.yaml
```

Rules:
- Include **only** images new or changed compared to the previous release (tag bumps, new sidecars/exporters, newly digest-pinned entries even if the tag is unchanged — call those out in a comment like `# newly digest-pinned in <version>; tag unchanged`).
- Every listed image must have a corresponding `{registry, repository, tag}` entry in `values.yaml` — never invent versions.
- Each entry requires a `digest` field (`sha256:...`) fetched from the source registry via `/fetch-image-digest`.
- Format: flat YAML list, no pipeline wrapper, no indentation on list items.
- **`name:` is the ACR mirror repo name** at `acrprodmgmt.azurecr.io/<name>`. Under the current strip-registry convention (see [`charts/podiumd/docs/images/acr-mirror-naming.md`](../../charts/podiumd/docs/images/acr-mirror-naming.md)) this is mechanical — the upstream `url:` with only the registry host stripped, full `<namespace>/<repo>` path kept verbatim (e.g. `ghcr.io/infonl/zaakafhandelcomponent` → `infonl/zaakafhandelcomponent`). `charts/podiumd/scripts/mirror-strip-registry.py --gen-manifest` computes `name:`/`url:` for every known image this way — use it instead of hand-deriving. The "Legacy translation table" further down that doc (hand-translated names like `zac`, `openinwoner`) is migration-only, for environments still on the old scheme — don't consult it for a new manifest entry.
- `url:` keeps the canonical upstream form (hyphens, vendor path, English name — whatever the source registry serves). This is what `/fetch-image-digest` consumes.
- Group entries with short English comments at the top of each section (use English; the 4.7.2 manifest dropped the legacy Dutch header). Real-world groupings seen in `images-4.7.0.yaml`:
  - `# <App name>` (one comment per logical app, e.g. `# Open Zaak`, `# ZAC`, `# Keycloak (operator + server)`)
  - `# <App> - <sidecar>` for sidecars (e.g. `# ZAC - Open Policy Agent`)
  - `# APISIX - oauth2-proxy (Keycloak SSO sidecar for admin UI)` — short context in parens is fine.
- File header: `# Images new or changed in podiumd <version> vs <prev>.` (English; replaces the older `# Images die nieuw of gewijzigd zijn in podiumd ... t.o.v. ...` Dutch phrasing).
- Mirror the field order from `ExternalsPodiumD/pipelines/images.yml`: `name`, `url`, `version`, `digest`.

Steps:

1. Find the previous release manifest under `charts/podiumd/docs/images/` (highest semver less than `$ARGUMENTS`). Use it as both a template for grouping/style **and** the baseline for what to exclude.
2. Detect changes:
   ```powershell
   git diff <prev-tag>...HEAD -- charts/podiumd/values.yaml | Select-String "^\+.*tag:"
   git diff <prev-tag>...HEAD -- charts/podiumd/Chart.yaml
   ```
   If the previous git tag doesn't exist, diff against `main`.
3. For every changed image, invoke `/fetch-image-digest <registry>/<repo>:<tag>` to obtain the digest. Never hand-write digests.
4. Reuse the previous manifest's comment grouping where the same images still apply; add new groups only for new apps.
5. Write the file. Reference style: `images-4.7.0.yaml`.
6. Run `/helm-dupecheck` to verify `values.yaml` is clean before finalizing.
7. **Update `images-baseline.yaml` too** — it's the single complete strip-registry manifest and does not auto-update from per-release delta files. For every entry just added to `images-$ARGUMENTS.yaml`, add the matching entry to `images-baseline.yaml` (same `name`/`url`/`version`/`digest`), keeping the previous version's entry immediately below it as history (see the existing `clamav/clamav` or `curlimages/curl` duplicate-name entries for the pattern) rather than replacing it. Insert alphabetically by `name`. Easy to forget since it's a separate file from the one this command writes — do not skip it.
8. After writing both files, print: file paths, count of entries in each, and any image whose digest fetch failed (must be resolved before commit).
