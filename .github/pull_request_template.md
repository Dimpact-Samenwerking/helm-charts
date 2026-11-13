<!--
Delete the sections marked "optional" when they have nothing to say.
A release PR (feature/podiumd-<X.Y.0> into main) uses the release layout
instead: Upgrade paths, Component changes, Fixes and changes, Status.
-->
<!-- The PR title is the top-level heading, so this template starts at level 2. -->
<!-- pyml disable-next-line md041 -->

## Summary

<!--
The problem or trigger first, then the change. One bullet per changed file
or area that says what changed in it. With more than one commit, one
subsection per commit.
A component bump: `<component> <old> → <new> (chart <old> → <new>)` and the
command that made it.
-->

## Target branch

<!-- feature/podiumd-<X.Y.0>, a feature/podiumd-<X.Y.0>-* branch, or main. -->

## Effect on values and upgrade

<!--
Values keys added, renamed or removed; new render guards; what changes in
the rendered output; the upgrade-guide sections (A to F) this adds to.
"None" when nothing changes for an environment.
-->

## Checklist

- [ ] Rebased onto the target branch; the PR has only its own commits
- [ ] `/helm-precommit` passes (BOM check, duplicate keys, helm lint, `verify-podiumd` without CVE steps)
- [ ] `/verify-podiumd` passes, CVE steps included, or is listed under **Not run**
- [ ] `./run_python_checks` passes (only when `charts/podiumd/bin/` changed)
- [ ] Upgrade guide (`*-upgrade.md`) and values-deltas (`*-values-deltas.md`) updated, or not needed
- [ ] Images manifest (`docs/images/images-<version>.yaml`) updated, or not needed
- [ ] `/markdown-lint` passes on changed `*.md` files

## Checks

<!--
Each check that ran, with its result: exit code, steps passed, image CVE
counts before and after. Then **Not run:** and **Not tested:**, each with
the reason.
-->

## Tested (optional)

<!--
Testing beyond the checks: environment, chart version, date, what was done
and what was seen, before and after the fix.
For `charts/podiumd/bin/`: the new tests, and that they fail on the old code.
-->

## Reuse (optional)

<!--
Only for `charts/podiumd/bin/`: the existing functions checked for the same
concept, and which one was extended or why none fit.
-->

## To test on QA (optional)

<!-- What a tester checks after the deploy, per component. -->

## Open points (optional)

<!--
What has to happen before this leaves draft, and problems found on the base
branch that this PR leaves alone.
-->

## Ticket

<!-- Solves IN-xxxx, or "none". -->
