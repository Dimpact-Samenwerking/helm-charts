# Backlog: verify monitoring-logging with verify-podiumd

Status: assessment only, not started. Written 2026-10-20 against
`feature/podiumd-4.10.0` (helm-charts `9294c856`) and this branch
(monitoring-logging 1.0.19). Line numbers may have moved since.

## Question

How much work is it to let `charts/podiumd/bin/verify-podiumd` check this chart
as well, so monitoring-logging gets the same lint, render, security and upgrade
checks as podiumd?

## Summary

About 1.5 to 2.5 days. The design already allows it: every check takes the
chart directory as an argument, and per-chart settings come from
`<chart>/etc/settings.yaml`. Most of the work is removing hardcoded "podiumd"
names, plus deciding which podiumd-specific checks to skip here.

## What ties verify-podiumd to podiumd

- **No chart option.** `verify-podiumd:128` fixes the chart directory to the
  script's own chart (`DEFAULT_CHART_DIR = SCRIPT_DIR.parent`, used in
  `resolve_chart_dir()` at :149-154). The only flags are `--skip`, `--include`
  and `--detail-*`.
- **Hardcoded release name.** `lib/render_scope.py:30` has
  `CHART_NAME = "podiumd"`, and :32 has
  `OWN_TEMPLATES_PREFIX = "podiumd/templates/"`. These drive the split between
  the chart's own templates and vendored ones in `release_secret_size.py`,
  `checks/digest_pinning.py`, `cve.py`, `yamllint.py` and `kube_score.py`.
- **Hardcoded paths.** `lib/chart/paths.py` resolves `docs/_UPGRADE_PATHS` and
  `docs/images` from its own location; `checks/lockstep.py` uses it.
  `gitutil.py:28` builds refs like `podiumd-<version>` and
  `feature/podiumd-<version>`.

## The checks for this chart

| Group | Checks | What they need |
|---|---|---|
| Generic | UTF-8, duplicates, DRY, vendored tgz, markdown lint, repo access, dependencies, Helm lint, full render, chart upgrades, image upgrades | only a chart option |
| Generic once the name comes from `Chart.yaml` | yamllint, kubeconform, shellcheck, kube-score, release secret size, root containers, CVE scan, CVE diff | `CHART_NAME` and `OWN_TEMPLATES_PREFIX` from the chart's `name` |
| Need per-chart config | helm-docs (README), node selector | `etc/settings.yaml` and `ci/lint-values.yaml` (below) |
| Skip here | image references, OIDC URL coverage, digest pinning, image digests, subchart image visibility, shared image usage, image repository, release baseline, lockstep versions, doc consistency | they assume podiumd's layout |

Why the last group does not fit this chart:

- **Image references** expect the `podiumd.image` helper
  (`image/references_check.py:12`).
- **OIDC URL coverage** needs `templates/keycloak-podiumd-realm-config.yaml`
  (`checks/oidc_url_coverage.py:18`) and fails without it.
- **The image checks** assume podiumd's tag plus digest layout and its
  `global.images.*` anchors. This chart pins no digests in `values.yaml` (plain
  tags such as `tag: v3.6.0`); only `docs/images/images-*.yaml` lists digests.
- **Release baseline** reads `etc/release-baseline.yaml`, which this chart does
  not have.
- **Doc consistency** expects `docs/_UPGRADE_PATHS`, files named
  `-to-<version>-upgrade.md` and "Baseline: podiumd" headers
  (`docs_consistency/__init__.py:769,775`). This chart uses
  `docs/upgrade-from-<from>-to-<to>.md`.

## What this chart has and lacks

- **Has:** `README.md` with `README.md.gotmpl` (helm-docs),
  `docs/images/images-*.yaml`, `docs/upgrade-from-*.md`,
  `values-enable-tempo.yaml`.
- **Lacks:**
  - `ci/lint-values.yaml`: the render steps then only warn;
  - `etc/settings.yaml`: Helm repo aliases for grafana, prometheus-community
    and opentelemetry, and accepted root containers;
  - `Chart.lock` and vendored `charts/*.tgz`.
- **Vendor classification:** with the defaults in `lib/settings.py:213-234`,
  every dependency is other-vendor, so findings in them only report and never
  fail.

## CI

No workflow runs verify-podiumd today.
`podiumd-test-podiumd-helm-chart-changes.yaml` lints and templates only
`charts/podiumd`. `release.yaml` packages every chart; its comment at :14-25
notes that `charts/monitoring-logging/.github/workflows/release.yaml` never runs.

## Plan and effort

1. **Chart option, about 1 day.**
   - Add `--chart`, and read the release name from `Chart.yaml`.
   - Let `lib/chart/paths.py` follow the chart directory.
   - Add a per-chart list of disabled steps in `etc/settings.yaml`.
   - Update the 24 test files in `charts/podiumd/bin/tests/verify-podiumd/` that
     assume podiumd: mainly `test_render_scope.py`, `test_kube_score.py`,
     `test_vendor_classification.py` and `test_digest_pinning_*`. Add tests for
     `--chart` and for the disabled steps.
2. **monitoring-logging setup, about 0.5 to 1 day.**
   - Add `etc/settings.yaml` with the repo aliases, the disabled steps and the
     accepted root containers.
   - Add `ci/lint-values.yaml`.
   - Sort out the findings of the first run.
3. **Optional CI job, about 0.5 day.** Run verify on changes under
   `charts/monitoring-logging/`.
4. **Optional digest pinning, about 1 day.** This is a policy change: pin
   digests in `values.yaml` so the image checks apply here too.

## Risks

- More hidden podiumd assumptions may show up beyond the ones above.
- kube-score and kubeconform will report a lot about the seven upstream
  subcharts. Those findings only report, but the run is slow.
- The tooling lives in `charts/podiumd/bin`. A tool shared by two charts belongs
  in a repo-level `bin/`; moving it is extra work.
- The script name and its summary output still say "podiumd".
