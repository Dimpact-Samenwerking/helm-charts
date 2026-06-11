Inspect a vendored sub-chart `.tgz` package in `charts/podiumd/charts/` without extracting it.

Usage: `/helm-tgz-inspect <chart-name>[:<inner-path>]`

Examples:
- `/helm-tgz-inspect openzaak` — list contents of the chart tarball
- `/helm-tgz-inspect openzaak:openzaak/templates/deployment.yaml` — read one file from the tarball to stdout

Why this skill exists: Helm prefers an extracted chart directory over a `.tgz` of the same name. If you ever `tar -xzf` a vendored package or check out an extracted version, `helm template`/`lint`/`upgrade` silently uses the extracted copy instead of the pinned package — which has caused broken deployments. **Always inspect without extracting.**

Behavior:

1. Resolve the tarball: find the newest matching file under `charts/podiumd/charts/` whose name starts with `<chart-name>-`.
2. If `$ARGUMENTS` has no colon, run:
   ```bash
   tar -tzf charts/podiumd/charts/<resolved>.tgz
   ```
3. If `$ARGUMENTS` is `<chart-name>:<inner-path>`, run:
   ```bash
   tar -xzOf charts/podiumd/charts/<resolved>.tgz <inner-path>
   ```
   (`-O` writes to stdout instead of disk.)
4. Never run `tar -xzf` (extracting), never `cd` into an extracted directory.

If you find that `charts/podiumd/charts/<chart-name>/` exists as a directory next to the `.tgz`, warn the user — it must be deleted (along with verifying the `.tgz` is still present and pinned) before any Helm operation.
