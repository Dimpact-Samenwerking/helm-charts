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
- Use the **component name from the chart** (e.g. `openinwoner`, not `open-inwoner`).
- Group entries with short Dutch comments at the top of each section. Real-world groupings seen in `images-4.7.0.yaml`:
  - `# <App name>` (one comment per logical app, e.g. `# Open Zaak`, `# ZAC`, `# Keycloak (operator + server)`)
  - `# <App> - <sidecar>` for sidecars (e.g. `# ZAC - Open Policy Agent`)
  - `# APISIX - oauth2-proxy (Keycloak SSO sidecar for admin UI)` — short Dutch context is fine in parens.
- File header is a single comment line: `# Images die nieuw of gewijzigd zijn in podiumd <version> t.o.v. <prev>.`
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
7. After writing, print: file path, count of entries, and any image whose digest fetch failed (must be resolved before commit).
