# Dimpact Helm charts
This repository contains Helm charts for:

- [brp mock](./charts/brp-personen-mock/)
- [kiss](./charts/kiss/README.md)
- [mi data (MI exports)](./charts/mi-data/docs/mi-exports.md)
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
- History stays linear. The release branch protection requires linear history, and the repository only allows squash merges, so a merge commit cannot land on a release branch or on `main`.
- A release branch takes new `main` commits by rebasing only its own commits onto `main`: `git rebase --onto origin/main <old-main> feature/podiumd-<X.Y.0>`, where `<old-main>` is the `main` commit (or previous release tip) it was based on. Because releases reach `main` as one squash commit, a plain `git rebase origin/main` would replay the previous release's commits and conflict. Announce the force push first: every open PR on the release branch then needs a sync.
- After a release branch was rewritten, rebase each open PR onto it with only its own commits: `/sync-pr-branch <PR>` (`git rebase --onto origin/feature/podiumd-<X.Y.0> <old-base> <branch>`). Do not merge the release branch into a PR branch: a non-linear branch blocks a GitHub stack ("stack branches diverged").

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
