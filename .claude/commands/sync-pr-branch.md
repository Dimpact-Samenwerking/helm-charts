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

Feature branches that reject merge commits (`feature/podiumd-*`): rebase, keeping every commit.

```bash
git rebase --onto "$B" <old-base> "$H"
```

Branches that allow merge commits: keep the history and add one merge commit whose tree is the current base plus the PR's own diff. No force push is needed.

```bash
git switch --detach "$B"
git diff <old-base> "$H" | git apply --3way --index   # resolve conflicts, git add
T=$(git write-tree)
NEW=$(git commit-tree "${T}" -p "$H" -p "$B" -m "Merge <base> into <head>")
```

In zsh, write `${T}` and `${NEW}`: `$NEW:r` is a zsh modifier.

Resolve conflicts by keeping both sides. Generated docs (`_UPGRADE_PATHS/`, `images-*.yaml`) follow `values.yaml` order: run `fix-doc-consistency` afterwards.

## 3. Verify, then push

1. Run the full `/verify-podiumd` on the result.
2. Ask the user before a force push, and before pushing to a branch someone else owns.
3. Push with a lease on the head you started from:
   - rebase: `git push --force-with-lease=<head>:<old-head-sha> origin HEAD:refs/heads/<head>`
   - merge: `git push origin "${NEW}:refs/heads/<head>"`
4. Check that GitHub shows only the PR's own files and that the PR is mergeable:
   `gh pr view <n> --json mergeable,files -q '.mergeable, (.files|length)'`.
5. Comment on the PR: why it was synced, the old base, how conflicts were resolved, and the verify result.

## Report

```text
SYNC-PR-BRANCH #<n> <head>
  Old base : <sha> (<date of the base rewrite>)
  Method   : rebase | merge commit
  Files    : <before> -> <after>
  Verify   : PASS | FAIL
  Pushed   : <new head sha>
```
