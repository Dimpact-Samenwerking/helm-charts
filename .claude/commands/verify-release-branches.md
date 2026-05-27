Verify the release-branch landscape around the current `charts/podiumd/Chart.yaml` version: the previous-minor patch branch (alarm-only — out of scope to create), and the two next branches to prepare (current `+1 patch` and current `+1 minor.0`). For missing branches in scope, create them from `main`, bump version in `Chart.yaml` + docs, and ensure an open PR against `main`.

Usage: `/verify-release-branches` (no args — derives everything from `charts/podiumd/Chart.yaml`)

Examples:
- Chart at `4.7.2` →
  - previous-minor next patch: `4.6.<latest+1>` (alarm if no branch — handle out of scope)
  - current `+1 patch`: `4.7.3` (create + PR if missing)
  - current `+1 minor.0`: `4.8.0` (create + PR if missing)

Branch naming convention (locked in by prior releases): `feature/podiumd-<X.Y.Z>`.

PR base: `main`. PR title pattern: `feature: PodiumD <X.Y.Z>` (matches the historic squash-merge titles).

Behavior:

1. **Sync first.**
   ```bash
   git fetch --all --prune
   git checkout main && git pull --ff-only
   ```

2. **Read the current chart version.**
   ```bash
   grep -E '^version:' charts/podiumd/Chart.yaml | awk '{print $2}'
   ```
   Parse as `MAJOR.MINOR.PATCH`. Call this `CUR=X.Y.Z`.

3. **Find the latest GitHub release of the previous minor.**
   ```bash
   gh release list --repo Dimpact-Samenwerking/helm-charts --limit 30 \
     --json tagName,createdAt,isPrerelease \
     --jq '.[] | select(.isPrerelease|not) | .tagName' \
     | grep -E "^podiumd-${PREV_MAJOR_MINOR}\." \
     | sort -V | tail -1
   ```
   Where `PREV_MAJOR_MINOR = X.(Y-1)`. Strip the `podiumd-` prefix to get `PREV=X.(Y-1).N`. This is the latest *released* patch on the previous minor.

4. **Compute the three target versions.**
   - `PREV_NEXT  = X.(Y-1).(N+1)`  — previous-minor next patch (alarm-only)
   - `CUR_NEXT   = X.Y.(Z+1)`      — current `+1 patch`
   - `NEXT_MINOR = X.(Y+1).0`      — current `+1 minor.0`

5. **Check each target branch (local + remote).**
   ```bash
   for v in $PREV_NEXT $CUR_NEXT $NEXT_MINOR; do
     git rev-parse --verify --quiet "refs/remotes/origin/feature/podiumd-$v" >/dev/null \
       && echo "OK    feature/podiumd-$v" \
       || echo "MISS  feature/podiumd-$v"
   done
   ```

6. **For `PREV_NEXT` (previous-minor next patch): alarm-only.** If MISS, print a clear alarm block. Do NOT create. Reason: previous-minor releases are typically driven by a separate hotfix cadence with its own owner / cherry-pick policy, and the workflow has not yet been documented. Flag, move on. Sample alarm text:
   ```
   ⚠️  Previous-minor patch branch missing: feature/podiumd-<PREV_NEXT>
       Latest released previous-minor: podiumd-<PREV>
       This branch is out of scope for this command — handle separately
       (cherry-pick policy / hotfix workflow to be documented).
   ```

7. **For `CUR_NEXT` (current `+1 patch`): create + bump + open PR if missing.**
   ```bash
   git checkout main && git pull --ff-only
   git checkout -b feature/podiumd-$CUR_NEXT main
   # Bump Chart.yaml: version + appVersion
   # Edit charts/podiumd/Chart.yaml: version: <CUR_NEXT>, appVersion: "<CUR_NEXT>"
   # Bump version refs in docs (see step 9 for the file list)
   git add charts/podiumd/Chart.yaml <doc files touched>
   git commit -m "chore(podiumd): bump chart version to <CUR_NEXT>"
   git push -u origin feature/podiumd-$CUR_NEXT
   gh pr create --base main --head feature/podiumd-$CUR_NEXT \
     --title "feature: PodiumD <CUR_NEXT>" \
     --body "Release branch placeholder for podiumd <CUR_NEXT>. See Confluence Releases page for the agreed application-version targets: https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD"
   ```

8. **For `NEXT_MINOR` (current `+1 minor.0`): same flow as step 7**, branch name `feature/podiumd-$NEXT_MINOR`, commit message and PR title use `$NEXT_MINOR`.

9. **Docs files to bump alongside `Chart.yaml`.** Keep version refs in sync with `4.7.2` (the precedent) — at minimum:
   - `charts/podiumd/README.md`: add a new top entry under `## PodiumD versions` mirroring the latest entry's table structure; fill in known AppVersions / ChartVersions from `Chart.yaml` deps and `values.yaml` image tags. Mark application versions as TBD if Confluence has no firm target yet.
   - `charts/podiumd/docs/upgrade-from-<PREV_REL>-to-<NEW>.md`: create a new file with the same skeleton as the latest upgrade guide (sections per app, "Action required" subsections). Default to no-action stubs until the Confluence release page firms up.
   - Any other doc that explicitly lists the chart version (search before committing): `grep -rln "$CUR" charts/podiumd/docs/ charts/podiumd/README.md` and review hits.

10. **Confluence application-version targets** —
    <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.
    Claude Code's WebFetch cannot read authenticated Atlassian pages, so the operator must open the page manually and:
    - For `CUR_NEXT`: if the Confluence page lists app-version targets for the patch (e.g. ZAC X.Y.Z, OpenZaak A.B.C), pre-fill them into the bump commit. If empty, leave a TODO in the upgrade-notes doc.
    - For `NEXT_MINOR`: same — the minor's targets often arrive later, so leave TODOs and revisit when populated.

11. **PR-open check for the two prepared branches** (idempotent — run this whenever the branches already exist too, to make sure their PR didn't get closed without a merge):
    ```bash
    for v in $CUR_NEXT $NEXT_MINOR; do
      n=$(gh pr list --repo Dimpact-Samenwerking/helm-charts \
            --head "feature/podiumd-$v" --base main --state open \
            --json number --jq 'length')
      if [ "$n" = 0 ]; then
        echo "MISS  PR for feature/podiumd-$v → open one"
        # gh pr create … (same as step 7)
      else
        echo "OK    PR open for feature/podiumd-$v"
      fi
    done
    ```

Notes:

- This skill is **branch-scope only** — it does not touch the actual app-version bumps for sub-charts. The chart version + appVersion + doc skeleton land as a placeholder commit so renovate / per-app PRs can land on top.
- The created `+1 patch` branch should be expected to receive only patch-class changes (security bumps, doc fixes, digest refreshes). New sub-chart features go on `NEXT_MINOR`.
- Re-running the command on a clean repo is a no-op (`OK` for every branch + PR). Use that as a health check before cutting a release.

Reference one-shot script (read-only verification + alarms; bump+PR steps are interactive and best done by hand to confirm Confluence targets):

```bash
#!/usr/bin/env bash
set -uo pipefail
REPO=Dimpact-Samenwerking/helm-charts
CHART=charts/podiumd/Chart.yaml

git fetch --all --prune --quiet

CUR=$(grep -E '^version:' "$CHART" | awk '{print $2}')
IFS=. read -r MAJ MIN PAT <<<"$CUR"
PREV_MM="$MAJ.$((MIN-1))"
PREV_REL=$(gh release list --repo "$REPO" --limit 50 \
  --json tagName,isPrerelease \
  --jq ".[] | select(.isPrerelease|not) | .tagName" \
  | grep -E "^podiumd-${PREV_MM}\." | sort -V | tail -1)
PREV=${PREV_REL#podiumd-}
PREV_PAT=${PREV##*.}
PREV_NEXT="$PREV_MM.$((PREV_PAT+1))"
CUR_NEXT="$MAJ.$MIN.$((PAT+1))"
NEXT_MINOR="$MAJ.$((MIN+1)).0"

echo "Chart version (current): $CUR"
echo "Latest previous-minor release: $PREV_REL (parsed: $PREV)"
echo
printf '%-12s %-30s %s\n' "TARGET" "BRANCH" "STATUS"
for v in $PREV_NEXT $CUR_NEXT $NEXT_MINOR; do
  if git rev-parse --verify --quiet "refs/remotes/origin/feature/podiumd-$v" >/dev/null; then
    s=OK
  else
    s=MISS
  fi
  case $v in
    "$PREV_NEXT")  role="prev-minor+1patch (alarm)" ;;
    "$CUR_NEXT")   role="cur+1patch (create)" ;;
    "$NEXT_MINOR") role="cur+1minor.0 (create)" ;;
  esac
  printf '%-12s %-30s %s — %s\n' "$v" "feature/podiumd-$v" "$s" "$role"
done

echo
echo "PR check (for cur+1patch and cur+1minor only):"
for v in $CUR_NEXT $NEXT_MINOR; do
  n=$(gh pr list --repo "$REPO" --head "feature/podiumd-$v" --base main --state open --json number --jq 'length' 2>/dev/null)
  echo "  feature/podiumd-$v -> ${n:-0} open PR(s) to main"
done

echo
echo "Confluence release targets (open manually, WebFetch can't auth):"
echo "  https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD"
```
