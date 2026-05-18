Render the full podiumd chart with CI lint values for end-to-end template validation.

Usage: `/helm-render-all` (no args) or `/helm-render-all <extra-values.yaml>` to overlay an additional values file.

Default command:

```bash
helm template podiumd charts/podiumd \
  -f charts/podiumd/ci/lint-values.yaml \
  --skip-schema-validation
```

If `$ARGUMENTS` is a path to a values file, append `-f $ARGUMENTS` before the `--skip-schema-validation` flag.

Notes:
- `ci/lint-values.yaml` is required — default `values.yaml` leaves security fields blank and fails validation.
- `--skip-schema-validation` is required — KISS sub-chart JSON schema demands fields the CI values don't supply.
- Pipe output through `Select-String -Pattern "Error|error"` first if rendering succeeds visually but you want a quick sanity check.

After running, report:
- whether the render succeeded,
- any sub-chart errors (group by sub-chart),
- and which templates produced the most output (helps spot accidental explosions from new loops).
