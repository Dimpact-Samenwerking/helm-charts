# Branch workflow — no merge commits

Branch protection on this repo **rejects merge commits** ("This branch must not contain merge commits"). Never `git merge` a base branch into a feature branch.

To bring a base branch into a feature branch, **rebase** the feature branch onto the base (or squash):

```bash
git checkout <feature>
git rebase <base>
git push --force-with-lease origin <feature>
```

When propagating a base change down to a child feature branch, **push the base first, then rebase the child**. Because the base is already pushed, the child PR's diff then shows only the child's own commits — not the base changes. Verify:

```bash
git rev-list --left-right --count <base>...HEAD   # expect: 0  N
```

The 4.8.0 integration base is `feature/podiumd-4.8.0`; the default branch is `main`.
