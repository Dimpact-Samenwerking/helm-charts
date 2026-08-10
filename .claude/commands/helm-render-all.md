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

## Release Secret size check

Every Helm release revision is persisted as a Kubernetes Secret capped at
1 MiB by the apiserver. Run the estimator and record it for this version:

```bash
python3 charts/podiumd/scripts/helm-release-secret-size.py \
  --chart charts/podiumd -f charts/podiumd/ci/lint-values.yaml \
  --name podiumd --namespace podiumd --record
```

Requires `helm` and `yq` (mikefarah/yq) on PATH. `--record` appends/updates
this version's row in `charts/podiumd/docs/release-secret-size.md` — the
per-release history of this metric. Include the printed percentage in the
render-verify report every time.

The script exits non-zero and prints a warning once the estimate reaches
**90% of the 1 MiB limit**. Treat that as a release blocker, not a nitpick:
surface it prominently in your report (⚠️ at the top, not buried at the end)
and tell the user the chart is at real risk of `helm install`/`upgrade`
failing with an apiserver "request entity too large" error — investigate
before the release ships (trim `docs/`/CRDs/values via `.helmignore`, or
reconsider what's bundled).

The same script works for any chart — e.g. `--chart charts/monitoring-logging
--record` (no `-f` needed there, see `charts/monitoring-logging/docs/release-secret-size.md`).
