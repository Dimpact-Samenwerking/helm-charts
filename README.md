# Dimpact Helm charts
This repository contains Helm charts for:

- [brp mock](./charts/brp-personen-mock/)
- [kiss](./charts/kiss/README.md)
- [podiumd](./charts/podiumd/README.md)
- [podiumd monitoring and logging](./charts/monitoring-logging/README.md)
- [vng referentielijsten](./charts/vngreferentielijsten/README.md)

## Usage

```bash
helm repo add dimpact https://Dimpact-Samenwerking.github.io/helm-charts/
helm search repo dimpact
helm install my-release dimpact/<chart>
```

## Releases

### Production Releases

Production releases are automatically created when changes are pushed to the `main` or `release/*` branches. These releases follow semantic versioning and are production-ready.

### Snapshot Releases (Podiumd Only)

For testing purposes, you can manually create snapshot releases of the **podiumd** chart from any branch. Snapshot releases:

- Include the branch name in the version (e.g., `podiumd-1.0.0-feature-new-config-snapshot`)
- Are marked as pre-release (not production ready)
- Are overwritten each time you run the workflow on the same branch
- Are automatically cleaned up after 3 weeks
- **Only apply to the podiumd chart** - all other charts are excluded from snapshot releases

To create a snapshot release, go to the [Actions tab](../../actions/workflows/release-snapshot.yaml) and manually trigger the **Release Snapshot Charts** workflow.

See [Snapshot Release Documentation](./.github/workflows/release-snapshot.README.md) for more details.
