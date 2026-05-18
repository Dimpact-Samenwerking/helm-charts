Check whether the local repo is fresh enough to start work. Refresh if stale. Rule lives in `.github/copilot-instructions.md` under "Check repo updates before work".

Steps:

1. Read the timestamp of `.git/FETCH_HEAD` (or `.git/HEAD` if `FETCH_HEAD` doesn't exist). Compare to now.
2. If older than 24 hours, run:
   ```bash
   git fetch --all --prune
   ```
3. Show new upstream commits on the current branch and on `origin/main`:
   ```bash
   git log --oneline HEAD..@{u} 2>$null
   git log --oneline HEAD..origin/main
   ```
4. If `$ARGUMENTS` is `--pull` AND the current branch has an upstream AND there are no local uncommitted changes (check `git status --porcelain`), run `git pull --ff-only`. Otherwise, only report; never auto-pull on a dirty working tree.
5. If the user also has the external ZAC repo (`C:\Users\johnb\IdeaProjects\dimpact-zaakafhandelcomponent`) and `$ARGUMENTS` contains `--zac`, repeat the freshness check there (read-only — no auto-pull).

Final report:
- Last fetch age (e.g. "3h 12m" or "2 days").
- Commits behind upstream / behind main.
- Whether a fetch and/or pull happened, or just a report.
