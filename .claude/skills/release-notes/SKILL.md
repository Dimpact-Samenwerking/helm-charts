---
name: release-notes
description: Write the release notes and slide deck for a PodiumD chart release (minor or patch). They report our integration work - which component versions changed, how big each change is, the impact on helm-charts and SSC, and what we checked, tested and validated. Use before publishing a podiumd release, e.g. "/release-notes 4.10.0".
---

# Release notes for a PodiumD release

Arguments: `<target version>` (for example `4.10.0` or `4.9.4`), optionally
`<baseline version>`. Without a baseline, read it from
`charts/podiumd/etc/release-baseline.yaml` (`upgrade_docs`).

## What the notes are, and are not

The notes report **our integration work** for this release. They are not a
changelog of the components.

- **In:**
  - which component versions changed;
  - how big we judge each change (Klein, Middel or Groot);
  - the impact on helm-charts and on SSC (the hoster);
  - what we checked, tested and validated.
- **Out:**
  - **Upstream feature lists:** the suppliers publish those in their own repos.
  - **Actions for municipalities:** those are on the wiki release page. Link it, never repeat it:
    <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.
  - **Upgrade steps for the hoster:** those are in the upgrade guide,
    values-deltas and gemeente-specific docs. Summarise the impact in one line
    per component and link the docs.

Audience: stakeholders and municipalities. Language: **Dutch**, plain and short.

## Sources, in this order

1. **The release PR** into `main` (`Feature PodiumD <version>`). Its
   "Updated components", "Configuration changes", "Upgrade notes" and
   "Verification" sections are the primary source. Find it with
   `gh pr list --state merged --base main --search "PodiumD <version> in:title"`.
2. **The PRs merged into `feature/podiumd-<version>`**, listed in the release PR
   or with `git log podiumd-<baseline>..podiumd-<version>`. From each, take the
   "Verification", "Test plan" or "Validation" section. That is the evidence
   for "Wat wij hebben gecontroleerd".
3. **The component table** in
   `charts/podiumd/docs/_UPGRADE_PATHS/<baseline>-to-<version>-upgrade.md`
   (the versions and the "action required" notes).
4. **Upstream hints**, only for the size and impact assessment: run
   `python3 -I .claude/skills/release-notes/collect.py <baseline> <version> <out.json>`.
   - The collector reads the component table and the images manifest at tag
     `podiumd-<version>`.
   - It finds each source repo (OCI label `org.opencontainers.image.source`,
     a ghcr path, or `APP_OVERRIDES` in the script).
   - It fetches the releases in each version range: GitHub release, else the
     changelog at the release tag, else the PR titles of the compare range.
   - Read it for security fixes, breaking changes, migrations and deployment
     steps. Do not copy it into the notes.
   - Add a new component's repo to `APP_OVERRIDES` when the collector reports
     `source repo unknown`.

   For a release that is not tagged yet, the target tag does not exist: run
   it against the release branch head instead (adapt `tag` in `main()`), or
   rely on sources 1–3.
5. **Known issues** for "Bekende problemen": the private repository
   [infonl/podiumd-known-issues](https://github.com/infonl/podiumd-known-issues)
   (access: the PodiumD team). Read it with
   `gh api repos/infonl/podiumd-known-issues/contents/README.md -H 'Accept: application/vnd.github.raw'`,
   or clone it.
   - **The index:** the table in `README.md`, with one row per issue: Severity,
     report, product and version, the status of the last verification round,
     and the Fix column (scheduled or open).
   - **The detail:** each report in `issues/<id>-*.md`. Line 1 is an HTML
     comment with the upstream repository, the status, what was checked, and
     the last verification with its severity. Read the report before you judge
     the impact: the reports are more precise than the summary in
     `charts/podiumd/docs/misc/upstream-known-issues.md`, which can be out of
     date (it had omc-1 as fixed by Open Notificaties 1.17.0, and the
     2026-10-19 round still reproduced it).
   - **Which rows go in:** issues in a component version this release ships,
     with severity Critical or High, or with an impact that municipalities or
     SSC notice. Also include issues fixed in this release (status "Opgelost"
     with the PR). Leave out issues that only concern the QA estate or the
     tests.
   - **Impact:** say what a municipality or SSC notices, and when (for
     example only with OMC enabled, only with `wait_for_payment_to_register`,
     only during an SMTP outage). Take that from the report's "Impact",
     "Expected" and "Actual" sections, not from the title.
   - **Fix:** document every fix that is scheduled or open: the upstream
     release that contains it (and whether this release ships it), our PR, the
     Jira issue, or the workaround (for example the ingress for HSTS and
     nosniff). Write "Nog geen" when the Fix column is "-".
   - **Disclosure:** the notes are public, the reports are not. Never copy
     reproduction steps, environment names, hostnames or request bodies.
   - **Security findings** (authorization, authentication, data exposure,
     missing security headers, and the like) never get a row of their own,
     not even with a vague title. They appear only in a "Beveiligingsbevindingen"
     table, like the CVEs: the number per severity (Kritiek, Hoog, Middel,
     Laag) and how many have a fix or workaround, with the PR or Jira issue
     of that fix. No component names, no mechanism. They get a row of their
     own only once they are fixed and the fix is public.
     Never link the private repository from the notes; call it "het interne
     overzicht van bekende problemen".
   - **Date:** put the date of the verification round and of the Fix column
     in the section.
6. **Review statistics** for "Review en kwaliteit": run
   `python3 -I .claude/skills/release-notes/review_stats.py <version> <out.json>`.
   - It reads every open or merged PR into `feature/podiumd-<version>`, the
     open PRs into `feature/podiumd-<version>-*` (they still need a second
     merge step), and the release PR into `main`.
   - It reports PRs, reviews, approvals, "changes requested", human reviewers
     other than the author, review threads (resolved and open per PR), the
     median and longest time to merge, and merged PRs without a review.
   - "Reviews" includes plain review comments, also from the author: show
     the approvals next to it, never the count alone.
   - Name a merged PR without a review when it is large or risky, and say what
     testing covered it. Small docs fixes only get a count.
7. **The Jira build story** for a release that is not out yet:
   `PodiumD <version> bouwen` (for 4.10.0: IN-2971). Read its subtasks with the
   Jira tools (`parent = <key>`), once for the open ones
   (`statusCategory != Done`) and once for the done ones. Group the open
   ones by status: In Review, In Progress, Selected for Development.
   - Match each subtask to its PR with the review statistics (`jira` keys) or
     the PR number in the subtask title. Use the PR state from GitHub.
   - A subtask whose PR is merged but which is not Done in Jira gets "al
     gemerged; Jira nog bijwerken". Report it to the user too.
   - Jira and GitHub change during the day. Fetch both again right before
     every rebuild, and put the date (`stand <datum>`) in the section.

## Size

Start from semver, then raise it for integration impact. Never lower it.

| Size | When |
| --- | --- |
| **Klein** | Patch, or a rebuild of the same version. Image or chart bump only, no configuration change, no SSC action beyond mirroring the image. |
| **Middel** | Minor version; or a patch that brings a security fix, a new major version of a dependency (e.g. django-cms 4 → 5), a changed default, or an SSC action (backup, command, values change). |
| **Groot** | Major version, a data or values migration, a merged or replaced component (e.g. objecten + objecttypen → Open Object), or changes most environments must act on. |

State the reason in a few words next to the size.

## Files

Write both files to `release-notes/podiumd/` at the repository root (outside the
chart, so they are not linted as chart docs and not packaged):

- `<version>.md` from [`template.md`](template.md): the release notes. Replace
  every `{placeholder}`.
- `<version>-slides.md` from [`slides-template.md`](slides-template.md): a
  Marp deck with about 6 slides, built from the notes and never containing
  more than they do.

Rules:

- **Facts only.** Every claim about testing names the environment or check and
  comes from a PR or a recorded result. If something was only checked with
  `verify-podiumd`, say so, and say what was not tested.
- **QA environments by role, not by name.** Write "QA" for our own test
  environments (johnb00, jim00, kees00 and the other podiumd-infra
  environments) and "minikube" for a minikube install; never the
  environment's own name. SSC environments (ontw-*, test-*) keep their names.
- **Components:** one row per component or sub-image from the component
  table. Sub-images and rebuilds can share a row in the deck.
- **Configuration changes** that are not version bumps go in their own table.
- **Links:** to the PRs and Jira issues as given in the PRs, and at the end
  to the SSC docs and the images manifest.
- **Not released yet:** add `Nog open voor <version>` (source 7, one table per
  status) and keep "Review en kwaliteit" (source 6). After the release, drop
  "Nog open" and keep the review section with the final numbers.

## Check and hand over

1. Lint `<version>.md` with the verify settings (`/markdown-lint`). The slides
   file is Marp, not documentation: skip it.
2. Build the deck from `release-notes/podiumd/` (the deck links local files):

   ```bash
   out=~/Downloads/podiumd-<version>-presentatie
   mkdir -p "$out"
   npx -y @marp-team/marp-cli@4.1.2 <version>-slides.md --html -o "$out/podiumd-<version>.html"
   npx -y @marp-team/marp-cli@4.1.2 <version>-slides.md --html --allow-local-files --pdf -o "$out/podiumd-<version>.pdf"
   npx -y @marp-team/marp-cli@4.1.2 <version>-slides.md --html --allow-local-files --pptx -o "$out/podiumd-<version>.pptx"
   cp <version>.md "$out/podiumd-<version>-release-notes.md"
   ```

   - PDF and PPTX need a browser. Without Chrome in `/Applications`, marp
     fails with `No suitable browser found`: set `CHROME_PATH` to the
     puppeteer copy, for example
     `~/.cache/puppeteer/chrome/<version>/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`.
   - Check the PDF pages for text that runs off a slide. Keep each slide to
     about six bullets.
   - The release workflow builds the deck for a published release.
3. Show the user:
   - the size per component;
   - any claim you could not back with a source;
   - components the collector could not resolve.
4. Commit both files on the release branch through a PR. The release workflow
   puts `release-notes/podiumd/<version>.md` into the GitHub release text and
   attaches the deck as PDF and PPTX. That workflow step is not built yet: ask before changing
   `.github/workflows/release.yaml`.
