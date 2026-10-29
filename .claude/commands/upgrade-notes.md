Scaffold the per-release upgrade guide for a podiumd version bump.

Usage: `/upgrade-notes <prev>-to-<new>` (e.g. `/upgrade-notes 4.7.0-to-4.7.1`)

Output path:

```text
charts/podiumd/docs/_UPGRADE_PATHS/<prev>-to-<new>-upgrade.md
```

Steps:

1. Refuse if `$ARGUMENTS` is missing or does not match `<X.Y.Z>-to-<X.Y.Z>`.
2. Create the stub with `charts/podiumd/bin/create-doc-version` (it reads `<prev>` from `upgrade_docs` in `charts/podiumd/etc/release-baseline.yaml`; refuse when that is not `<prev>`). The stub is in the layout of [`charts/podiumd/docs/_UPGRADE_DOCS_CHECKLIST.md`](../../charts/podiumd/docs/_UPGRADE_DOCS_CHECKLIST.md), the single source for what goes where. Never edit a guide of a released version.
3. Compute changes between the two refs (tag the previous release if it exists, otherwise diff `main...HEAD`):

   ```bash
   git diff <prev-ref>...HEAD -- charts/podiumd/Chart.yaml charts/podiumd/values.yaml
   ```

4. Fill the stub as the checklist and [`/upgrade-guide`](upgrade-guide.md) say. Keep every section A to F; a section with nothing to do keeps "Nothing for this hop.". Run `charts/podiumd/bin/fix-doc-consistency` for the generated "Component versions" table and "Changes" headings instead of writing them by hand.
5. Cross-reference the matching `charts/podiumd/docs/images/images-<new>.yaml` if it exists; if not, remind the user to run `/images-manifest <new>`.
6. Do not invent versions. Every component row must be backed by `Chart.yaml`; every image must be backed by `values.yaml`.
7. After writing, print the file path and a one-line summary of which sections were filled.
