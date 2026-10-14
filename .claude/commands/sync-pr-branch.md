Bring a PR branch up to date with its release branch so the PR contains only its own changes. Use it when GitHub shows far more changed files than the PR made, or conflicts keep coming back: the release branch (`feature/podiumd-<X.Y.0>`) was rebased onto `main` and force-pushed, and the PR branch still carries the old copies of its commits.

Target: `$ARGUMENTS` is a PR number.

## 1. Find the old base

```bash
gh pr view <n> --json headRefName,baseRefName,files -q '.headRefName, .baseRefName, (.files|length)'
git fetch origin
B=origin/<baseRefName>; H=origin/<headRefName>
git merge-base --is-ancestor "$B" "$H" && echo "already on the current base"
git reflog show origin/<baseRefName>   # earlier tips, "forced-update" marks a rewrite
```

- Use the branch refs (`origin/<headRefName>`), not `pull/<n>/head`: GitHub updates that ref late.
- The old base is the newest earlier base tip that is an ancestor of `$H`. Without a local reflog, take the newest commit on `$H` whose subject also exists on `$B`.
- Check it: `git diff --stat <old-base> "$H"` must list only the PR's own files.

## 2. Move only the PR's own changes

Rebase, keeping every commit of the PR:

```bash
git rebase --onto "$B" <old-base> "$H"
```

Always rebase, also on branches that allow merge commits. A merge commit makes the branch non-linear: a GitHub stack then reports "stack branches diverged" and blocks the merge. Feature branches (`feature/podiumd-*`) also reject merge commits.

Resolve conflicts by keeping both sides. For generated docs (`_UPGRADE_PATHS/`, `images-*.yaml`), take the base version, run `fix-doc-consistency`, and add the PR's hand-written text back: a plain "keep both" duplicates generated lists and breaks tables.

## 3. Verify, then push

1. Run the full `/verify-podiumd` on the result.
2. Ask the user before a force push, and before pushing to a branch someone else owns.
3. Push with a lease on the head you started from:
   `git push --force-with-lease=<head>:<old-head-sha> origin HEAD:refs/heads/<head>`
4. Check that GitHub shows only the PR's own files and that the PR is mergeable:
   `gh pr view <n> --json mergeable,files -q '.mergeable, (.files|length)'`.
5. Comment on the PR: why it was synced, the old base, how conflicts were resolved, and the verify result.

## Report

```text
SYNC-PR-BRANCH #<n> <head>
  Old base : <sha> (<date of the base rewrite>)
  Files    : <before> -> <after>
  Verify   : PASS | FAIL
  Pushed   : <new head sha>
```
