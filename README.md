# Dimpact Helm charts
This repository contains Helm charts for:

- [brp mock](./charts/brp-personen-mock/)
- [kiss](./charts/kiss/README.md)
- [podiumd](./charts/podiumd/README.md)
- [podiumd monitoring and logging](./charts/monitoring-logging/README.md)
- [vng referentielijsten](./charts/vngreferentielijsten/README.md)


```bash
helm repo add dimpact https://Dimpact-Samenwerking.github.io/helm-charts/
helm search repo dimpact
helm install my-release dimpact/<chart>
```
