Render a single podiumd template without errors from unrelated sub-charts.

Usage: /helm-render <template.yaml> [extra --set flags]

Steps:
1. Run the following command (substitute the template name from $ARGUMENTS):

```bash
helm template podiumd charts/podiumd \
  -s templates/$ARGUMENTS \
  --set kiss.enabled=false \
  --set "zgw-office-addin.enabled=false" \
  --set zac.enabled=false \
  --set opennotificaties.enabled=false \
  --set openklant.enabled=false \
  --set openformulieren.enabled=false \
  --set openinwoner.enabled=false \
  --set kisselastic.enabled=false \
  --set ita.enabled=false \
  --set pabc.enabled=false \
  --set clamav.enabled=false \
  --set brppersonenmock.enabled=false \
  --set infinispan.enabled=false \
  --set "global.security.allowInsecureImages=true" \
  --skip-schema-validation
```

2. Show the rendered YAML output.
3. If there are errors, diagnose them and suggest fixes.

Note: if the template references sub-chart named templates (e.g. create-required-catalogi.yaml, create-required-objecttypen.yaml), do NOT disable openzaak/objecten/objecttypen.
