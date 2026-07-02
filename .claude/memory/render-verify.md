# Render-verifying the podiumd chart

```bash
cd charts/podiumd
helm dependency update          # needs network: downloads openzaak/apisix/redis-operator/... subcharts
helm template podiumd . -f ci/lint-values.yaml
```

A render with only `-f ci/lint-values.yaml` now **passes** (exit 0). `ci/lint-values.yaml`
carries dummy `zgw-office-addin` values (`common.frontendUrl`/`msalClientId`/`msalTenantId`,
`backend.msalSecret`, `backend.zgwApis.url`/`secret`) that satisfy that subchart's
`values.schema.json` (`format: uri`) + `required` guards. The chart's own
`values.yaml` deliberately leaves `zgw-office-addin.common.frontendUrl` and
`backend.zgwApis.url` empty (`""`) for fail-fast in real deploys — the placeholders
belong only in `ci/lint-values.yaml`.

> Historical: before those keys were added to `ci/lint-values.yaml`, a bare render
> failed on the `zgw-office-addin` schema and needed a hand-written `/tmp/ovr.yaml`
> override. No longer required.

The same `ci/lint-values.yaml` is used by the GitHub workflow
`podiumd-test-podiumd-helm-chart-changes.yaml` (via k8s-bake `overrideFiles`), so
CI and local render match.

Related skills: `/helm-render-all`, `/helm-deps`.
