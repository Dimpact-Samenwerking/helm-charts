Add all required Helm repositories for the podiumd chart.

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add maykinmedia https://maykinmedia.github.io/charts/
helm repo add wiremind https://wiremind.github.io/wiremind-helm-charts
helm repo add dimpact https://Dimpact-Samenwerking.github.io/helm-charts/
helm repo add zac https://infonl.github.io/dimpact-zaakafhandelcomponent/
helm repo add zgw-office-addin https://infonl.github.io/zgw-office-addin
helm repo add adfinis https://charts.adfinis.com
helm repo add opstree https://ot-container-kit.github.io/helm-charts/
helm repo update
```

Report which repos were added and which already existed.
