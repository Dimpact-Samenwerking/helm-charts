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

## Branching strategy

The repository uses a **forward-cascade** model centred on PodiumD releases.

```
main  (current release, e.g. 4.7.5)
 └── feature/podiumd-4.8.0          ← next release
      ├── feature/podiumd-4.8.0-*   ← feature branches to be merged into 4.8.0
      ├── feature/info-podiumd-4.8.0   ┐
      ├── feature/icatt-podiumd-4.8.0  ├ environment-specific branches (o-info / o-icatt / o-maykin)
      ├── feature/maykin-podiumd-4.8.0 ┘
      └── feature/podiumd-4.9.0     ← future release (changes that won't be part of 4.8.0)
           ├── feature/info-podiumd-4.9.0   ┐
           ├── feature/icatt-podiumd-4.9.0  ├ environment-specific branches
           └── feature/maykin-podiumd-4.9.0 ┘
```

| Branch pattern | Purpose |
|---|---|
| `main` | Current production release. Merging here triggers a production release. |
| `feature/podiumd-<X.Y.0>` | Upcoming release branch. Branched from `main` (or the previous release branch for future releases). All release work lands here before merging to `main`. |
| `feature/podiumd-<X.Y.0>-*` | Short-lived feature branches for changes destined for `<X.Y.0>`. Merged into the release branch when ready. |
| `feature/<env>-podiumd-<X.Y.0>` | Environment-specific branches (e.g. `o-info`, `o-icatt`, `o-maykin`) branched from the matching release branch. Changes here may or may not be promoted back into the release branch. |

### Rules

- Each release branch is branched from the tip of the previous release branch (or `main` for the immediate next release), so every release automatically contains all prior changes.
- Environment-specific branches (`feature/<env>-podiumd-*`) are branched from the corresponding release branch and kept in sync with it by rebasing or merging.
- Short-lived feature branches (`feature/podiumd-<X.Y.0>-*`) target the release branch they are named after and are deleted after merging.
- `main` always reflects the latest production release; only completed release branches are merged into it.

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
