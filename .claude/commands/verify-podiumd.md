Run the full `verify-podiumd` on a branch or PR and fix or report every finding. This is the gate before a commit is pushed for review, before a PR is reported as ready, and before a release. It runs **every** step: a subset such as `--include markdown,doc-consistency` misses kube-score, kubeconform, shellcheck, release-baseline, image-digest and other failures that CI or the release run will find later.

Target: `$ARGUMENTS` is a PR number, a branch, or a worktree path. Without it, use the current checkout.

## 1. Check out the exact code

- **PR:** use the PR head (`gh pr view <n> --json headRefName,headRefOid`) in its own worktree. Never verify a local branch that is behind its remote.
- **Up to date with the base:** `verify-podiumd` compares with the release baseline and the base branch docs. Note when the branch is behind its base (`git rev-list --count HEAD..origin/<base>`); a stale branch can pass here and fail after the merge.

## 2. Make sure every tool is there

Every tool from `charts/podiumd/bin/README-release-process.md#setup` must be installed: a missing tool makes its step fail. The Python tools (`pymarkdown`) are in the main checkout's `.venv`; a worktree has none, so put it on the `PATH`:

```bash
export PATH="$(git worktree list | head -1 | cut -d' ' -f1)/.venv/bin:$PATH"
```

Docker is only needed for the CVE steps. Without it they are skipped, which is fine for a PR; say so in the report. For a release, start it (`colima start`) so the CVE steps run.

A FAIL from `Repo access` with `Internal Server Error` for docker.io images is usually a Docker Hub hiccup: rerun before reporting it.

## 3. Run every step

```bash
python3 charts/podiumd/bin/verify-podiumd 2>&1 | tee "$SCRATCHPAD/verify-<target>.log"
```

- Never pass `--include` or `--skip`. Use them only to rerun one step after a fix, and run the full set again before reporting.
- The run takes several minutes; run it in the background and wait for it.

## 4. Fix or report every finding

- A **FAIL** blocks. Fix it on the branch, or, for a PR you do not own, report it with the step name, file and line.
- Check whether the base branch fails the same step (run it there too). A failure that already exists on the base is reported as such, not blamed on the PR, but it is still listed.
- A **SKIP** needs a reason in the report (no Docker, a failed prerequisite). Nothing is skipped silently: a step skipped because a prerequisite failed was **not** checked, so fix the prerequisite and run again.
- Release completeness is part of the run (release baseline, doc consistency, images manifest, helm-doc). A release is only ready when these pass with no SKIP.

## Report

```text
VERIFY-PODIUMD <target> @ <sha>
  Result  : PASS | FAIL (<n> failed steps)
  Failed  : <step>: <one line with file:line>   (also failing on base: yes|no)
  Skipped : <step>: <reason>
  Behind base: <n> commits
```

Never commit or post the result to a PR without the user's approval.
