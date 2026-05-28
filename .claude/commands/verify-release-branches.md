Verify the release-branch landscape for **both** charts in the repo. Each chart has its own policy:

- **`charts/podiumd`** — three targets, derived from `charts/podiumd/Chart.yaml`:
  - previous-minor next patch (documented separate workflow, do NOT auto-create — see step 6);
  - current `+1 patch` (create + bump + PR if missing);
  - current `+1 minor.0` (create + bump + PR if missing).
- **`charts/monitoring-logging`** — one target only, derived from `charts/monitoring-logging/Chart.yaml`:
  - current `+1 patch` (create + bump + PR if missing).
  - No `+1 minor.0` track. No previous-minor track. **Exactly one open branch + PR at a time** — if a second monitoring-logging release branch shows up (e.g. someone speculatively opened a `+1 minor.0`), flag it as a smell and check with the user before keeping both.

Usage: `/verify-release-branches` (no args — derives everything from each chart's `Chart.yaml`)

Examples:
- `charts/podiumd` at `4.7.2` →
  - previous-minor next patch: `4.6.<latest+1>` (alarm if no branch — see step 6)
  - current `+1 patch`: `4.7.3` (create + PR if missing)
  - current `+1 minor.0`: `4.8.0` (create + PR if missing)
- `charts/monitoring-logging` at `1.0.13` →
  - current `+1 patch`: `1.0.14` (create + PR if missing) — only target

Branch naming conventions (locked in by prior releases):
- podiumd: `feature/podiumd-<X.Y.Z>`
- monitoring-logging: look at the latest released branch and follow it exactly (typically `feature/monitoring-logging-<X.Y.Z>`); verify before creating.

PR base: `main`.
PR title patterns:
- podiumd: `feature: PodiumD <X.Y.Z>` (matches historic squash-merge titles)
- monitoring-logging: follow the latest merged PR's title style for that chart.

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

6. **For `PREV_NEXT` (previous-minor next patch): documented separate workflow — do NOT create + bump + open PR like the other two.** Previous-minor patches **never merge to `main`** (main is already past this minor; merging would drag old code forward). Instead:

   a. Develop and test the patch on the `feature/podiumd-<PREV_NEXT>` branch (a regular feature branch — but with no PR to `main`).
   b. When the patch is ready and tested, **squash the entire feature branch into a single commit** on a `release/podiumd-<PREV_NEXT>` branch. That single commit is what triggers the helm-publish CI build. **Do not push further commits to `release/podiumd-<PREV_NEXT>`** — extra commits don't re-trigger cleanly and confuse the publish job.
   c. Tag / GitHub-release is cut from the `release/*` tip.

   If the **feature branch** is missing, print an alarm but do **not** auto-create it — the previous-minor owner picks which fix to backport and when. Sample alarm text:
   ```
   ⚠️  Previous-minor patch branch missing: feature/podiumd-<PREV_NEXT>
       Latest released previous-minor: podiumd-<PREV>
       Follow the prev-minor workflow:
         1. develop on feature/podiumd-<PREV_NEXT> (no PR to main, ever)
         2. squash all work into ONE commit on release/podiumd-<PREV_NEXT>
            — that single commit triggers the helm build
         3. no further commits on release/* after that
       Do not run create+bump+PR from this command — that flow is for the
       current minor (CUR_NEXT) and next minor (NEXT_MINOR) only.
   ```

   If the **`feature/podiumd-<PREV_NEXT>` branch exists but `release/podiumd-<PREV_NEXT>` is missing**, that means the patch is mid-development — no action needed yet, but note that the release/* trigger commit is still owed.

   **Visibility PR:** a PR for the prev-minor patch *may* exist against `main` for visibility/tracking. **Draft-state follows the same review-requested rule as the other two placeholders** — draft when no reviewers are requested, ready when reviewers are. The PR must **never actually merge to `main`** regardless of state (the release/* single-commit branch is the helm-build trigger).

   **Hard rules (follow to the letter):**
   - The prev-minor PR must never be merged to `main`, draft or not. If you find one in a "mergeable + approved" state, leave it — let the operator decide whether to close it.
   - Draft-state on the prev-minor PR mirrors `reviewRequests.length > 0` exactly (same rule as steps 7/8/11).
   - Never push a second commit to `release/podiumd-<PREV_NEXT>` once the squash commit is there.
   - Memory: see `project_prev_minor_patch_workflow.md` and `project_release_pr_draft_policy.md` in the project memory dir for the same rules.

7. **For `CUR_NEXT` (current `+1 patch`): create + bump + open DRAFT PR if missing.** The PR stays **draft** until the patch is actually scoped and ready (operator flips it via `gh pr ready <num>` when so).
   ```bash
   git checkout main && git pull --ff-only
   git checkout -b feature/podiumd-$CUR_NEXT main
   # Bump Chart.yaml: version + appVersion
   # Edit charts/podiumd/Chart.yaml: version: <CUR_NEXT>, appVersion: "<CUR_NEXT>"
   # Bump version refs in docs (see step 9 for the file list)
   git add charts/podiumd/Chart.yaml <doc files touched>
   git commit -m "chore(podiumd): bump chart version to <CUR_NEXT>"
   git push -u origin feature/podiumd-$CUR_NEXT
   gh pr create --base main --head feature/podiumd-$CUR_NEXT --draft \
     --title "feature: PodiumD <CUR_NEXT>" \
     --body "Release branch placeholder for podiumd <CUR_NEXT>. See Confluence Releases page for the agreed application-version targets: https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD"
   ```
   If an existing non-draft PR is found for this branch, flip it back to draft:
   ```bash
   gh pr ready <pr-number> --repo Dimpact-Samenwerking/helm-charts --undo
   ```

8. **For `NEXT_MINOR` (current `+1 minor.0`): same flow as step 7**, branch name `feature/podiumd-$NEXT_MINOR`, commit message and PR title use `$NEXT_MINOR`. **Same `--draft` rule** — the next-minor PR is a long-lived placeholder, must stay draft until the minor is actually being scoped for release.

9. **Docs files to bump alongside `Chart.yaml`.** Keep version refs in sync with `4.7.2` (the precedent) — at minimum:
   - `charts/podiumd/README.md`: add a new top entry under `## PodiumD versions` mirroring the latest entry's table structure; fill in known AppVersions / ChartVersions from `Chart.yaml` deps and `values.yaml` image tags. Mark application versions as TBD if Confluence has no firm target yet.
   - `charts/podiumd/docs/upgrade-from-<PREV_REL>-to-<NEW>.md`: create a new file with the same skeleton as the latest upgrade guide (sections per app, "Action required" subsections). Default to no-action stubs until the Confluence release page firms up.
   - Any other doc that explicitly lists the chart version (search before committing): `grep -rln "$CUR" charts/podiumd/docs/ charts/podiumd/README.md` and review hits.

10. **Confluence application-version targets** —
    <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.
    Claude Code's WebFetch cannot read authenticated Atlassian pages, so the operator must open the page manually and:
    - For `CUR_NEXT`: if the Confluence page lists app-version targets for the patch (e.g. ZAC X.Y.Z, OpenZaak A.B.C), pre-fill them into the bump commit. If empty, leave a TODO in the upgrade-notes doc.
    - For `NEXT_MINOR`: same — the minor's targets often arrive later, so leave TODOs and revisit when populated.

11. **PR-open + draft-state check for the prepared branches** (idempotent — run this whenever the branches already exist too; synchronises draft state to the reviewer-requested state):
    ```bash
    for v in $CUR_NEXT $NEXT_MINOR $PREV_NEXT; do
      json=$(gh pr list --repo Dimpact-Samenwerking/helm-charts \
            --head "feature/podiumd-$v" --base main --state open \
            --json number,isDraft,reviewRequests --jq '.[0]')
      if [ -z "$json" ] || [ "$json" = null ]; then
        echo "MISS  PR for feature/podiumd-$v"
        continue
      fi
      num=$(echo "$json" | python3 -c "import sys,json;print(json.load(sys.stdin)['number'])")
      draft=$(echo "$json" | python3 -c "import sys,json;print(json.load(sys.stdin)['isDraft'])")
      revcount=$(echo "$json" | python3 -c "import sys,json;print(len(json.load(sys.stdin).get('reviewRequests',[])))")
      if [ "$revcount" -gt 0 ]; then
        # PR is actively in review — must NOT be draft
        if [ "$draft" = "True" ]; then
          echo "FIX   PR #$num feature/podiumd-$v is draft but has $revcount reviewer(s) requested — promoting"
          gh pr ready "$num" --repo Dimpact-Samenwerking/helm-charts
        else
          echo "OK    PR #$num feature/podiumd-$v (ready, $revcount reviewer(s) requested)"
        fi
      else
        # No reviewers requested → still a placeholder, must stay draft
        if [ "$draft" = "True" ]; then
          echo "OK    PR #$num feature/podiumd-$v (draft, placeholder)"
        else
          echo "FIX   PR #$num feature/podiumd-$v is ready but no reviewers requested — flipping to draft"
          gh pr ready "$num" --repo Dimpact-Samenwerking/helm-charts --undo
        fi
      fi
    done
    ```

    **Draft policy (project rule, follow to the letter):** all three placeholder PRs (`PREV_NEXT`, `CUR_NEXT`, `NEXT_MINOR`) live in **draft** state **while they are still placeholders**. The trigger to leave draft is **a reviewer being requested on the PR** — that's the operator's signal that the release is being scoped for actual review/merge. Concretely:

    - `reviewRequests.length == 0` → must be **draft**. Flip back via `gh pr ready <num> --undo` if found ready.
    - `reviewRequests.length > 0`  → must be **ready (NOT draft)**. Promote via `gh pr ready <num>` if found draft.

    The skill never decides whether to *add* a reviewer (that's an operator action). It only synchronises draft-state to whatever reviewer-requested state the PR is already in.

## charts/monitoring-logging — single-branch flow

12. **Read** `charts/monitoring-logging/Chart.yaml` `version` → `ML_CUR=X.Y.Z`; compute `ML_NEXT = X.Y.(Z+1)`. **No `+1 minor.0` target, no prev-minor target — those branches must NOT exist for this chart.**

13. **Branch + PR check** (same idempotent shape as steps 5/11, just one target):
    ```bash
    if git rev-parse --verify --quiet "refs/remotes/origin/feature/monitoring-logging-$ML_NEXT" >/dev/null; then
      echo "OK    feature/monitoring-logging-$ML_NEXT"
    else
      echo "MISS  feature/monitoring-logging-$ML_NEXT — create from main"
    fi
    n=$(gh pr list --repo Dimpact-Samenwerking/helm-charts \
          --head "feature/monitoring-logging-$ML_NEXT" --base main --state open \
          --json number --jq 'length' 2>/dev/null)
    echo "  PRs open to main: ${n:-0}"
    ```

14. **If missing**, create from `main`, bump `charts/monitoring-logging/Chart.yaml` (`version` + `appVersion`), and any monitoring-logging README/docs that explicitly carry the version. Same commit/push/PR pattern as steps 7–8, just for the monitoring-logging chart. **Same `--draft` rule applies** — the single monitoring-logging release-branch PR is opened with `gh pr create … --draft` and stays draft until the patch is scoped and ready.

15. **Smell check**: also look for any *other* monitoring-logging release branch (e.g. someone opened `feature/monitoring-logging-X.(Y+1).0`):
    ```bash
    git for-each-ref refs/remotes/origin --format='%(refname:short)' \
      | grep -E '^origin/feature/monitoring-logging-' \
      | grep -v "feature/monitoring-logging-$ML_NEXT$"
    ```
    Anything that prints here is unexpected for this chart's policy — flag, ask the user, do **not** silently keep it. The rule is: one open monitoring-logging branch at a time.

Notes:

- This skill is **branch-scope only** — it does not touch the actual app-version bumps for sub-charts. The chart version + appVersion + doc skeleton land as a placeholder commit so renovate / per-app PRs can land on top.
- The created `+1 patch` branch (for either chart) should be expected to receive only patch-class changes (security bumps, doc fixes, digest refreshes). New sub-chart features go on `NEXT_MINOR` (podiumd only — monitoring-logging has no minor track here).
- Re-running the command on a clean repo is a no-op (`OK` for every branch + PR). Use that as a health check before cutting a release.
- Companion memory: `project_prev_minor_patch_workflow.md` (podiumd prev-minor) and `project_monitoring_logging_branch_workflow.md` (monitoring-logging single-branch rule).

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
echo "PR check (draft-state synchronised to reviewers-requested state):"
for v in $PREV_NEXT $CUR_NEXT $NEXT_MINOR; do
  pr_json=$(gh pr list --repo "$REPO" --head "feature/podiumd-$v" --base main --state open --json number,isDraft,reviewRequests --jq '.[0]' 2>/dev/null)
  if [ -z "$pr_json" ] || [ "$pr_json" = "null" ]; then
    echo "  feature/podiumd-$v -> no open PR"
    continue
  fi
  num=$(echo "$pr_json" | python3 -c "import sys,json;print(json.load(sys.stdin)['number'])")
  draft=$(echo "$pr_json" | python3 -c "import sys,json;print(json.load(sys.stdin)['isDraft'])")
  rc=$(echo "$pr_json" | python3 -c "import sys,json;print(len(json.load(sys.stdin).get('reviewRequests',[])))")
  if [ "$rc" -gt 0 ] && [ "$draft" = "True" ]; then
    echo "  feature/podiumd-$v -> PR #$num draft w/ $rc reviewer(s) — promote: gh pr ready $num --repo $REPO"
  elif [ "$rc" = 0 ] && [ "$draft" = "False" ]; then
    echo "  feature/podiumd-$v -> PR #$num ready w/ 0 reviewers — flip back: gh pr ready $num --repo $REPO --undo"
  else
    label=$([ "$draft" = "True" ] && echo "draft (placeholder)" || echo "ready ($rc reviewer(s))")
    echo "  feature/podiumd-$v -> PR #$num $label ✓"
  fi
done

echo
echo "Confluence release targets (open manually, WebFetch can't auth):"
echo "  https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD"

# ----- charts/monitoring-logging: single-branch (+1 patch only) -----
ML_CHART=charts/monitoring-logging/Chart.yaml
if [ -f "$ML_CHART" ]; then
  echo
  echo "=== monitoring-logging ==="
  ML_CUR=$(grep -E '^version:' "$ML_CHART" | awk '{print $2}')
  IFS=. read -r ML_MAJ ML_MIN ML_PAT <<<"$ML_CUR"
  ML_NEXT="$ML_MAJ.$ML_MIN.$((ML_PAT+1))"
  echo "Chart version (current): $ML_CUR  →  expected branch: feature/monitoring-logging-$ML_NEXT"
  if git rev-parse --verify --quiet "refs/remotes/origin/feature/monitoring-logging-$ML_NEXT" >/dev/null; then
    echo "OK    feature/monitoring-logging-$ML_NEXT"
  else
    echo "MISS  feature/monitoring-logging-$ML_NEXT — create from main"
  fi
  n=$(gh pr list --repo "$REPO" --head "feature/monitoring-logging-$ML_NEXT" --base main --state open --json number --jq 'length' 2>/dev/null)
  echo "  PRs open to main: ${n:-0}"
  # Smell check: any OTHER monitoring-logging branch must not exist
  extras=$(git for-each-ref refs/remotes/origin --format='%(refname:short)' \
    | grep -E '^origin/feature/monitoring-logging-' \
    | grep -v "feature/monitoring-logging-$ML_NEXT$" || true)
  if [ -n "$extras" ]; then
    echo "⚠️  Extra monitoring-logging branches present (policy is one-at-a-time):"
    echo "$extras" | sed 's/^/    /'
  fi
fi
```
