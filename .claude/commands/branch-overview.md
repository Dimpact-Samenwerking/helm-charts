Triage every remote branch in this repo into three buckets — **released** (a `podiumd-X.Y.Z` or `monitoring-logging-X.Y.Z` release tag is reachable from its tip; the work has shipped), **active** (still in flight, no release yet, recent activity), and **stale** (no recent activity, no in-flight release, candidate for deletion). Also flag oddities (the `release/*` single-commit trigger branches for prev-minor patches, branches whose name explicitly says STALE, accidental refs like a literal `origin/origin`).

Usage: `/branch-overview`

Output: a markdown table per bucket plus a small "smell" section. Read-only — never deletes branches.

Why this exists: this repo uses **squash-merge to main**, so `git branch -r --merged origin/main` reports almost nothing useful (the squashed commit on main has a different SHA than the branch tip). The reliable "did this ship?" signal is **release-tag containment**: if a `podiumd-X.Y.Z` tag commit is an ancestor of a branch, that branch carries shipped work. The "release/*" branches are special — see `project_prev_minor_patch_workflow.md`.

Behavior:

1. **Sync.**
   ```bash
   git fetch --all --prune --quiet
   ```

2. **Build the inverted tag → branch map** (fast — one `git branch -r --contains <tag>` per release tag, not per branch):
   ```bash
   for tag in $(git for-each-ref --format='%(refname:short)' refs/tags/podiumd-[0-9]* refs/tags/monitoring-logging-[0-9]*); do
     branches=$(git branch -r --contains "$tag" 2>/dev/null \
       | sed 's@^[[:space:]]*origin/@@' | grep -v '^HEAD' | tr '\n' ' ')
     echo "$tag : $branches"
   done
   ```
   Filter to `^podiumd-[0-9]` / `^monitoring-logging-[0-9]` to skip oddball tags like `podiumd-4.5.9-feature-*-snapshot` and any other non-version tags that would pollute the sort.

3. **Classify each `origin/<branch>`** (skip `HEAD`, `main`, `master`):
   - **released** — at least one numeric release tag is reachable AND the highest such tag is also reachable from `origin/main` (work has shipped). Show the highest release tag found.
   - **active** — no release tag reachable yet, OR the highest reachable tag is one of the in-flight release branches (e.g. `feature/podiumd-4.7.3` already has 4.7.2 reachable but no 4.7.3 release yet — that's *active*, not stale).
   - **stale** — no release tag, no recent activity (default threshold ≥30 days since last commit), no open PR. Or branch name ends in `-STALE`. Or release tag is reachable but the work is older than 30d and the same release is already on main (a `feature/podiumd-X.Y.Z` whose `podiumd-X.Y.Z` tag is on main → shipped, retire).

4. **Per-branch age and open-PR signal**:
   ```bash
   git log -1 --format='%cI %h' "$ref"
   gh pr list --repo Dimpact-Samenwerking/helm-charts --head "<br>" --base main --state open --json number
   ```

5. **Oddity / smell flags** to surface (do NOT auto-delete):
   - A literal `origin/origin` ref (push artifact from `git push origin origin`).
   - `feature/*` branches with `-STALE` or `-OLD` suffix in the name.
   - Duplicate `feature/podiumd-X.Y.Z` + `release/podiumd-X.Y.Z` pairs on a previous-minor line — that's the documented prev-minor workflow (see `project_prev_minor_patch_workflow.md`), not a smell, but flag it so the reader sees both halves of the pair.
   - More than one `feature/monitoring-logging-*` branch open at once (policy violation per `project_monitoring_logging_branch_workflow.md`).
   - `renovate/*` branches with no open PR — Renovate normally cleans these up; an orphan suggests a closed-without-merge PR.

6. **Output shape — Slack-friendly (narrow, fenced code blocks).** Slack's monospace blocks soft-wrap around ~80 cols. Keep every row ≤ **70 chars**. Truncate long branch names with `…` (right-truncate to 38 chars; longest in this repo: `feature/podiumd-4.7.2-add-zaakbrug-v2` = 37). Drop low-signal columns. **Do not use markdown `|`-table syntax** — Slack renders that as literal pipes, not a table. Use fixed-width whitespace-aligned columns inside a triple-backtick code block.

   Per-bucket tables:

   ```
   ## Released (shipped — candidates to delete)
   ```
   ```
   branch                                  release      age
   ──────────────────────────────────────  ───────────  ─────
   feature/podiumd-4.7.1                   podiumd-4.7.1  9d
   feature/podiumd-4.6.7                   podiumd-4.6.7  15d
   …
   ```

   ```
   ## Active (keep)
   ```
   ```
   branch                                  age   PR?  role
   ──────────────────────────────────────  ────  ───  ───────────────────────
   feature/podiumd-4.7.3                   0d    yes  cur+1 patch
   feature/podiumd-4.8.0                   14d   yes  cur+1 minor.0
   feature/podiumd-4.6.8                   1d    -    prev-minor patch
   …
   ```

   ```
   ## Stale (candidates to delete)
   ```
   ```
   branch                                  age    reason
   ──────────────────────────────────────  ─────  ────────────────────────
   feature/podiumd-with-openbeheer         85d    superseded
   feature/IN-1372-zaakbrug-helm-integ…    70d    superseded by IN-1865
   …
   ```

   ```
   ## Smells
   ```
   ```
   - origin/origin            literal ref, push artifact
   - 2 monitoring-logging br… policy is one-at-a-time
   ```

   - Pick column widths so the dashes line ≤ 70 chars total. Aim for branch col = 38, age = 5, PR = 4, release/reason = remainder.
   - Render each bucket as its own fenced block so Slack doesn't merge them.
   - Don't paste raw `git log` SHAs — they bloat width and aren't actionable in Slack.

7. **End with**: do **not** propose any deletion commands automatically. If the user wants a batch `git push origin --delete …` list, ask for confirmation per-bucket and emit then. The default output is read-only triage.

Notes:

- The `release/podiumd-X.(Y-1).Z` branches are **expected** to exist for previous-minor patches even when the matching feature/* branch looks stale — they're the single-commit CI trigger. See `project_prev_minor_patch_workflow.md`. Do not flag those as candidates for deletion.
- `gh-pages` is the chart-publish branch — always show it under a separate "infrastructure" line, never list as stale.
- This skill is a pre-cut-release health check companion to `/verify-release-branches`. Run both before a new release.

Reference one-shot script (read-only):

```bash
#!/usr/bin/env bash
set -uo pipefail
REPO=Dimpact-Samenwerking/helm-charts
git fetch --all --prune --quiet

# inverted: tag -> branches containing it, restricted to numeric version tags
declare -A TAG_BRANCHES
for tag in $(git for-each-ref --format='%(refname:short)' \
   refs/tags/podiumd-[0-9]* refs/tags/monitoring-logging-[0-9]*); do
  TAG_BRANCHES[$tag]=$(git branch -r --contains "$tag" 2>/dev/null \
    | sed 's@^[[:space:]]*origin/@@' | grep -v '^HEAD' | tr '\n' ' ')
done

NOW=$(date -u +%s)
for ref in $(git for-each-ref --format='%(refname:short)' refs/remotes/origin); do
  br="${ref#origin/}"
  case "$br" in HEAD|main|master|origin) continue;; esac
  iso=$(git log -1 --format='%cI' "$ref")
  short=$(git log -1 --format='%h' "$ref")
  ts=$(python3 -c "import datetime;print(int(datetime.datetime.fromisoformat('$iso'.replace('Z','+00:00')).timestamp()))")
  age_days=$(( (NOW - ts) / 86400 ))

  # which release tags reach this branch
  rels=""
  for tag in "${!TAG_BRANCHES[@]}"; do
    if [[ " ${TAG_BRANCHES[$tag]} " == *" $br "* ]]; then rels="$rels $tag"; fi
  done
  highest=$(echo "$rels" | tr ' ' '\n' | grep . | sort -V | tail -1)

  # is that highest tag on origin/main? (shipped)
  shipped=no
  [ -n "$highest" ] && git merge-base --is-ancestor "refs/tags/$highest" origin/main 2>/dev/null && shipped=yes

  # open PR?
  pr=$(gh pr list --repo "$REPO" --head "$br" --base main --state open --json number --jq 'length' 2>/dev/null)
  pr=${pr:-0}

  # classify
  case "$br" in
    *-STALE|*-OLD)              cls=stale; reason="name says stale";;
    gh-pages)                   cls=infra; reason="chart publish";;
    origin)                     cls=smell; reason="literal 'origin' ref";;
    renovate/*)                 cls=$([ "$pr" -gt 0 ] && echo active || echo stale); reason="renovate auto";;
    release/*)                  cls=infra; reason="prev-minor single-commit CI trigger";;
  esac
  if [ -z "${cls:-}" ]; then
    if [ "$shipped" = yes ] && [ "$age_days" -gt 7 ]; then cls=released;
    elif [ -n "$highest" ] && [ "$age_days" -gt 30 ]; then cls=stale;  reason="released but $age_days d old";
    elif [ "$age_days" -gt 60 ] && [ "$pr" = 0 ];        then cls=stale;  reason="${age_days}d old, no PR";
    else                                                      cls=active; reason="${age_days}d, pr=$pr";
    fi
  fi
  printf '%s\t%s\t%dd\t%s\t%s\t%s\n' "$cls" "$br" "$age_days" "${highest:-—}" "${pr:-0}" "${reason:-}"
  unset cls
done | sort -k1,1 -k3,3nr
```
