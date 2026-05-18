Scaffold the per-release upgrade guide for a podiumd version bump.

Usage: `/upgrade-notes <prev>-to-<new>` (e.g. `/upgrade-notes 4.7.0-to-4.7.1`)

Output path:
```
charts/podiumd/docs/upgrade-from-<prev>-to-<new>.md
```

Steps:

1. Refuse if `$ARGUMENTS` is missing or does not match `<X.Y.Z>-to-<X.Y.Z>`.
2. Read the most recent existing upgrade doc under `charts/podiumd/docs/upgrade-from-*.md` (sort by mtime) to mirror its tone and section order. Style reference: `upgrade-from-4.5.13-to-4.6.0.md`.
3. Compute changes between the two refs (tag the previous release if it exists, otherwise diff `main...HEAD`):
   ```powershell
   git diff <prev-ref>...HEAD -- charts/podiumd/Chart.yaml charts/podiumd/values.yaml
   ```
4. Populate these sections (drop a section entirely if there's nothing to say — do NOT leave empty headers):
   - **New images requiring ACR override** — key paths + `values.yaml` snippets for any new `{registry, repository, tag}` triples.
   - **New optional components** — sub-charts newly enabled or newly available.
   - **Removed or deprecated components** — anything turned off/removed.
   - **Required manual steps** — DB migrations, secret rotations, cluster-side prep.
   - **Component version bump table** — markdown table with columns `| Component | old | new |` derived from `Chart.yaml` diff.
5. Cross-reference the matching `charts/podiumd/docs/images/images-<new>.yaml` if it exists; if not, remind the user to run `/images-manifest <new>`.
6. Do not invent versions. Every component row must be backed by `Chart.yaml`; every image must be backed by `values.yaml`.
7. After writing, print the file path and a one-line summary of which sections were filled.
