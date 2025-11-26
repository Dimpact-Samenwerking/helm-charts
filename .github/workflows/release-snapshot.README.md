# Snapshot Release Workflow

## Overview

The `release-snapshot.yaml` workflow allows you to create snapshot releases of Helm charts for testing purposes. These releases are:

- **Branch-based**: Created from any branch you're working on
- **Clearly marked**: Include the branch name and `-snapshot` suffix
- **Pre-release**: Marked as not production ready in GitHub
- **Temporary**: Automatically cleaned up after 3 weeks

## How to Use

### Triggering a Snapshot Release

1. Navigate to the **Actions** tab in the GitHub repository
2. Select **"Release Snapshot Charts"** from the workflows list
3. Click **"Run workflow"**
4. Select the branch you want to release from
5. (Optional) Specify specific charts to release, or leave empty to release all changed charts
6. Click **"Run workflow"** to start the release

### What Happens

The workflow will:

1. **Delete existing snapshot releases** for the current branch (if any exist)

2. **Modify chart versions** to include:
   - Original version number
   - Sanitized branch name
   - `-snapshot` suffix
   
   Example: `1.0.0` becomes `1.0.0-feature-auth-snapshot`

3. **Package and release** the charts using the standard Helm chart-releaser

4. **Mark as pre-release** in GitHub with a warning message indicating it's not production ready

5. **Clean up old snapshots** by deleting any snapshot releases older than 3 weeks

## Version Naming Convention

Snapshot versions follow this pattern:

```
{original-version}-{branch-name}-snapshot
```

Where:
- `{original-version}`: The version from Chart.yaml
- `{branch-name}`: The branch name with `/` replaced by `-` and special characters removed
- `snapshot`: Literal suffix

Examples:
- Main branch: `1.0.0-main-snapshot`
- Feature branch: `1.0.0-feature-new-config-snapshot`
- Release branch: `1.0.0-release-v1.2-snapshot`

**Note:** Each time you run the snapshot workflow on the same branch, it overwrites the previous snapshot release for that branch.

## Important Notes

### Manual Trigger Only

This workflow **never runs automatically**. It must be manually triggered by a user through the GitHub Actions interface.

### Pre-release Status

All snapshot releases are marked as "pre-release" in GitHub with a clear warning message. This prevents them from being confused with production releases.

### Overwriting Behavior

Each time you run the snapshot workflow on a branch, it **overwrites** the previous snapshot release for that branch. This ensures you always have the latest snapshot version without accumulating old test releases.

### Automatic Cleanup

Snapshot releases older than 3 weeks are automatically deleted when a new snapshot release is created. This keeps the releases page clean and removes outdated test releases from other branches.

### Production Releases

For production releases, continue using the standard `release.yaml` workflow, which runs automatically on pushes to `main` or `release/*` branches.

## Use Cases

- **Testing chart changes** before merging to main
- **Validating configurations** in development environments
- **Sharing work-in-progress** charts with team members
- **Integration testing** with specific chart versions

## Comparison with Production Releases

| Feature | Snapshot Release | Production Release |
|---------|------------------|-------------------|
| Trigger | Manual only | Automatic on push |
| Version format | Includes branch name | Standard semver |
| GitHub status | Pre-release | Release |
| Behavior | Overwrites on re-run | Never overwrites |
| Retention | 3 weeks | Permanent |
| Use case | Testing | Production |

## Troubleshooting

### Release not appearing

- Check that your chart's version was modified correctly
- Verify that the chart passes `helm lint`
- Check the Actions log for any errors

### Old snapshots not cleaned up

- The cleanup job runs after each snapshot release
- Only snapshots with `-snapshot` in the name are cleaned up
- Production releases are never touched

### Permission errors

- Ensure the workflow has `contents: write` permissions
- Verify that `GITHUB_TOKEN` has sufficient access

