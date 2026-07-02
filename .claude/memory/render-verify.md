# Render-verifying the podiumd chart

```bash
cd charts/podiumd
helm dependency update          # needs network: downloads openzaak/apisix/redis-operator/... subcharts
helm template podiumd . -f ci/lint-values.yaml
```

A render with only `-f ci/lint-values.yaml` now **passes** (exit 0). The
`zgw-office-addin` schema is satisfied from two places: the chart `values.yaml`
supplies the URL fields (`common.frontendUrl`, `backend.zgwApis.url` — example
hosts), and `ci/lint-values.yaml` supplies only the MSAL/secret placeholders
(`common.msalClientId`/`msalTenantId`, `backend.msalSecret`, `backend.zgwApis.secret`)
that would otherwise trip the subchart's `required` guards.

> Historical: before those placeholders existed, a bare render failed on the
> `zgw-office-addin` schema and needed a hand-written `/tmp/ovr.yaml` override.
> No longer required.

The same `ci/lint-values.yaml` is used by the GitHub workflow
`podiumd-test-podiumd-helm-chart-changes.yaml` (via k8s-bake `overrideFiles`), so
CI and local render match.

Related skills: `/helm-render-all`, `/helm-deps`.
