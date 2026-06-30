# Render-verifying the podiumd chart

```bash
cd charts/podiumd
helm dependency update          # needs network: downloads openzaak/apisix/redis-operator/... subcharts
helm template podiumd . -f ci/lint-values.yaml -f /tmp/ovr.yaml
```

A **bare** render with only `-f ci/lint-values.yaml` FAILS: the `zgw-office-addin` subchart ships empty defaults that trip its `values.schema.json` (`format: uri`) and the `required` template guards. This is pre-existing and expected — real deploys inject these via the gemeente values pipeline, so production is unaffected; only the bare CI lint/render breaks.

To verify past the gate, supply an override with the EXACT key shape (note `msalSecret` is under `backend`, NOT `common`):

```yaml
# /tmp/ovr.yaml
zgw-office-addin:
  common:
    frontendUrl: "https://addin.example.com"   # must be format:uri
    msalClientId: "dummy-client"
    msalTenantId: "dummy-tenant"
  backend:
    msalSecret: "dummy-secret"
    zgwApis:
      url: "https://zgw.example.com"            # must be format:uri
      secret: "dummy-secret"
```

Related skills: `/helm-render-all`, `/helm-deps`.
