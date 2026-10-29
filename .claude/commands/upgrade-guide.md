Write or review the upgrade docs of the current hop: the upgrade guide and the values-deltas doc from the `upgrade_docs` baseline to the chart's version. The single source for their layout and for what goes where is [`charts/podiumd/docs/_UPGRADE_DOCS_CHECKLIST.md`](../../charts/podiumd/docs/_UPGRADE_DOCS_CHECKLIST.md). Read it first and follow it; this command does not repeat it.

Target: `$ARGUMENTS` is `write` or `review` (default `review`), optionally followed by a PR number or a worktree path. Without one, use the current checkout. For a PR, work in a worktree on its head.

## 1. Find the hop

The baseline is `upgrade_docs` in `charts/podiumd/etc/release-baseline.yaml`, the target is `version` in `charts/podiumd/Chart.yaml`. The docs are `charts/podiumd/docs/_UPGRADE_PATHS/<baseline>-to-<target>-upgrade.md` and `-values-deltas.md`.

**Never edit the guides of released versions** (every other `<from>-to-<to>-*.md`, such as `4.9.4-to-4.9.5-upgrade.md`). They are frozen; a step that also holds for an older hop goes in the current guide.

When the docs do not exist yet, `charts/podiumd/bin/create-doc-version` (also run by `create-podiumd-version`) creates them as stubs in the checklist layout: every section is there and says "Nothing for this hop.".

## 2. Write

- Fill the sections of the stub in the checklist's order. Keep "Nothing for this hop." where it is true; delete it where the section gets content.
- The tooling writes the "Component versions" table and the `###` headings under "## Changes". Do not rewrite them by hand; run `charts/podiumd/bin/fix-doc-consistency` after editing.
- The values-deltas doc is config only and written by hand: one `## <component> <old> → <new>` section per component, as in the "Component versions" table, and one per gateway file. Prose goes in the upgrade guide.

## 3. Review

Go through the checklist's questions and its table of parts, one by one, against both docs. For each item that is not met, name the section and what is missing or in the wrong place.

## 4. Check

```bash
python3 charts/podiumd/bin/verify-podiumd --include upgrade-doc-layout,markdown,doc-consistency
```

- `upgrade-doc-layout` checks that the guide's `##` sections from "Checklist" to "Changes" are all there and in order, that D has "If the run fails", that the Checklist links A to F and that the opening names the baseline and links the values-deltas doc. In the values-deltas doc it checks for an opening and that every `##` heading is a component or a gateway file. It does not judge the content of a step or the length of the prose: that is the review in step 3.
- Lint both docs with pymarkdown and the verify settings, as in [`/markdown-lint`](markdown-lint.md), until there are 0 findings.

## Report

```text
UPGRADE DOCS <baseline> → <target>
  Layout check    : PASS | FAIL (<n> issue(s): <first one>)
  Markdown        : PASS (0 findings) | FAIL (<rule> <file>:<line>, ...)
  Doc consistency : PASS | FAIL (<detail>)
  Checklist       : <items not met, with their section>, or "all met"
```
