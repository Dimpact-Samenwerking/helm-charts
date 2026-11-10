"""Check the target version's upgrade guide and values-deltas doc against docs/_UPGRADE_DOCS_CHECKLIST.md.

Only the docs of the hop to Chart.yaml's version are checked, and only
while that version has no podiumd-<version> tag: guides of released
versions are frozen in the layout they shipped with. Report only: the
findings are printed, the step never fails.

The upgrade guide: the opening names the baseline and links the values-deltas
doc; the "##" sections from "## Checklist" to "## Changes" are all there, in
order, and nothing else is between them; D has "### If the run fails"; the
Checklist links every A to F section. Any "##" section may follow
"## Changes" (the reference part).

The values-deltas doc: an opening before the first "##" heading, and every
"##" heading is a component version heading ("<component> <old> → <new>",
the shape doc-consistency matches against the Component versions table)
or a gateway file. Prose beyond a section's lead sentence is not checked: a
trailing note on a YAML block reads the same as prose to a parser.
"""

import re
import shutil

from itertools import takewhile
from pathlib import Path

from lib.chart.release_baseline_basics import chart_version
from lib.chart.release_baseline_basics import upgrade_docs_baseline as read_upgrade_docs_baseline
from lib.chart.release_baseline_basics import upgrade_docs_side_paths as read_upgrade_docs_side_paths
from lib.component_docs.baseline_doc_stubs import CHANGES_SECTION
from lib.component_docs.baseline_doc_stubs import CHECKLIST_SECTION
from lib.component_docs.baseline_doc_stubs import COMPONENT_VERSIONS_SECTION
from lib.component_docs.baseline_doc_stubs import DEPLOY_RUN_SECTION
from lib.component_docs.baseline_doc_stubs import IF_THE_RUN_FAILS_SECTION
from lib.component_docs.baseline_doc_stubs import NO_ACTION_SECTION
from lib.component_docs.baseline_doc_stubs import RUNBOOK_SECTIONS
from lib.component_docs.baseline_doc_stubs import UPGRADE_GUIDE_SECTIONS
from lib.component_docs.owned_parts import generated_heading_name
from lib.gitutil import find_repo_root
from lib.gitutil import resolve_git_ref
from lib.upgradedoc.baseline_intro import BASELINE_INTRO_RE
from lib.upgradedoc.doc_names import doc_name
from lib.upgradedoc.sorting_and_ordering import is_changes_heading
from lib.upgradedoc.string_and_parsing_basics import COMPONENT_VERSIONS_HEADING_RE
from lib.upgradedoc.string_and_parsing_basics import MarkdownHeading
from lib.upgradedoc.string_and_parsing_basics import heading_slug
from lib.upgradedoc.string_and_parsing_basics import markdown_headings
from lib.version_numbers import is_bare_version

CHECKLIST_PATH = "docs/_UPGRADE_DOCS_CHECKLIST.md"
GATEWAY_FILE_HEADING_RE = re.compile(r"^`[\w-]+-gateway\.yml`$")
_ORDER = ", ".join(f'"## {name}"' for name in UPGRADE_GUIDE_SECTIONS)


# The Checklist and A to F may add to the name; the other sections are
# found exactly as the writers find them (finding a "## Changes: notes"
# would let insert_changes_section add a second "## Changes").
_SUFFIXED_SECTIONS = (CHECKLIST_SECTION, *RUNBOOK_SECTIONS)
_CHANGES_INDEX = UPGRADE_GUIDE_SECTIONS.index(CHANGES_SECTION)
# The UPGRADE_GUIDE_SECTIONS indices of the A to F runbook sections.
_RUNBOOK_INDICES = range(1, len(RUNBOOK_SECTIONS) + 1)


def _section_index(heading: MarkdownHeading) -> int | None:
    """The UPGRADE_GUIDE_SECTIONS index of a "##" heading, None for any other heading."""
    if is_changes_heading(heading):
        return _CHANGES_INDEX
    if COMPONENT_VERSIONS_HEADING_RE.match(heading.text):
        return UPGRADE_GUIDE_SECTIONS.index(COMPONENT_VERSIONS_SECTION)
    if heading.text == NO_ACTION_SECTION:
        return UPGRADE_GUIDE_SECTIONS.index(NO_ACTION_SECTION)
    for name in _SUFFIXED_SECTIONS:
        if heading.text == name or heading.text.startswith((f"{name}: ", f"{name} (")):
            return UPGRADE_GUIDE_SECTIONS.index(name)
    return None


def _section_issues(name: str, level2: list[MarkdownHeading]) -> tuple[list[str], dict[int, MarkdownHeading]]:
    """Unknown, misordered, repeated and missing "##" sections; also {section index: its heading}.

    After "## Changes" any other heading may follow (the reference part), but
    not a section of the layout again."""
    issues: list[str] = []
    found: dict[int, MarkdownHeading] = {}
    last_index, last_text = -1, ""
    for heading in level2:
        index = _section_index(heading)
        if index is None:
            if _CHANGES_INDEX not in found:
                issues.append(
                    f'{name}: "## {heading.text}" is not a section of the layout; move it under one of A to F, '
                    f'or after "## Changes" as a reference section'
                )
            continue
        if index in found:
            issues.append(f'{name}: "## {heading.text}" appears twice')
        elif index < last_index:
            issues.append(f'{name}: "## {heading.text}" comes after "## {last_text}"; the order is {_ORDER}')
        found.setdefault(index, heading)
        last_index, last_text = max((index, heading.text), (last_index, last_text))
    for index, section in enumerate(UPGRADE_GUIDE_SECTIONS):
        if index not in found:
            before = [UPGRADE_GUIDE_SECTIONS[position] for position in range(index) if position in found]
            after = f' after "## {found[UPGRADE_GUIDE_SECTIONS.index(before[-1])].text}"' if before else ""
            issues.append(f'{name}: missing "## {section}"{after}')
    return issues, found


def _if_the_run_fails_issues(name: str, headings: list[MarkdownHeading], deploy_run: MarkdownHeading) -> list[str]:
    after_deploy_run = headings[headings.index(deploy_run) + 1 :]
    subsections = takewhile(lambda heading: heading.marks != "##", after_deploy_run)
    if any(heading.marks == "###" and heading.text == IF_THE_RUN_FAILS_SECTION for heading in subsections):
        return []
    return [f'{name}: "## {deploy_run.text}" has no "### {IF_THE_RUN_FAILS_SECTION}" section']


def _checklist_link_issues(name: str, lines: list[str], found: dict[int, MarkdownHeading]) -> list[str]:
    """Each A to F section present must be linked from the Checklist, by its anchor.

    Nothing when the Checklist is not before them: the order finding covers that."""
    checklist = found[UPGRADE_GUIDE_SECTIONS.index(CHECKLIST_SECTION)]
    first_runbook = min(found[position].line for position in _RUNBOOK_INDICES if position in found)
    if first_runbook < checklist.line:
        return []
    checklist_text = "".join(lines[checklist.line : first_runbook])
    return [
        f'{name}: the Checklist does not link "## {heading.text}" (#{heading_slug(heading.text)})'
        for position, heading in sorted(found.items())
        if position in _RUNBOOK_INDICES and f"](#{heading_slug(heading.text)})" not in checklist_text
    ]


def upgrade_guide_layout_issues(name: str, text: str, upgrade_docs_baseline: str, target: str) -> list[str]:
    """Layout findings for the upgrade guide `name` with content `text`."""
    headings = markdown_headings(text)
    level2 = [heading for heading in headings if heading.marks == "##"]
    lines = text.splitlines(keepends=True)
    opening = "".join(lines[: level2[0].line] if level2 else lines)

    issues: list[str] = []
    if BASELINE_INTRO_RE.search(opening) is None:
        issues.append(
            f"{name}: the opening does not say which version it starts from "
            f'("For environments already on **{upgrade_docs_baseline}**."; doc-consistency checks the version)'
        )
    deltas = doc_name(upgrade_docs_baseline, target, "values-deltas")
    if f"]({deltas})" not in opening:
        issues.append(f"{name}: the opening does not link the companion {deltas}")

    section_issues, found = _section_issues(name, level2)
    issues.extend(section_issues)
    deploy_run = found.get(UPGRADE_GUIDE_SECTIONS.index(DEPLOY_RUN_SECTION))
    if deploy_run is not None:
        issues.extend(_if_the_run_fails_issues(name, headings, deploy_run))
    if UPGRADE_GUIDE_SECTIONS.index(CHECKLIST_SECTION) in found and any(
        position in found for position in _RUNBOOK_INDICES
    ):
        issues.extend(_checklist_link_issues(name, lines, found))
    return issues


def values_deltas_layout_issues(name: str, text: str) -> list[str]:
    """Layout findings for the values-deltas doc `name` with content `text`."""
    headings = markdown_headings(text)
    level2 = [candidate for candidate in headings if candidate.marks == "##"]
    lines = text.splitlines()
    title_end = next((candidate.line + 1 for candidate in headings if candidate.marks == "#"), 0)
    opening = lines[title_end : level2[0].line if level2 else len(lines)]

    issues: list[str] = []
    if not any(line.strip() for line in opening):
        issues.append(f"{name}: no opening before the first section (what the doc covers, a link to the guide)")
    issues.extend(
        f'{name}: "## {heading.text}" is neither a component section ("## <component> <old> → <new>", as in '
        f'the Component versions table) nor a gateway file section ("## `ssl-gateway.yml`"); '
        "prose belongs in the upgrade guide"
        for heading in level2
        if generated_heading_name(heading.text) is None and not GATEWAY_FILE_HEADING_RE.match(heading.text)
    )
    return issues


def _is_released(chart_dir: Path, target: str) -> bool | None:
    """Whether the local repository has the podiumd-<target> tag; None when there is no git repository to ask."""
    repo_root = find_repo_root(chart_dir) if shutil.which("git") else None
    if repo_root is None:
        return None
    return resolve_git_ref(repo_root, [f"refs/tags/podiumd-{target}"]) is not None


def check_upgrade_doc_layout(chart_dir: Path):
    """(True, detail) for verify-podiumd: report where the target version's upgrade docs leave the checklist's layout.

    Never fails. A released target (tagged) is skipped; without git the docs
    are checked anyway, with a warning, since the findings only inform."""
    baseline = read_upgrade_docs_baseline(chart_dir)
    if not is_bare_version(baseline):
        print(f'upgrade_docs baseline "{baseline}" is missing or not a bare version — nothing to check')
        return True, "no bare upgrade_docs baseline — skipped"
    target = chart_version(chart_dir / "Chart.yaml")
    released = _is_released(chart_dir, target)
    if released:
        print(f"podiumd-{target} is tagged: its upgrade docs are released and frozen — nothing to check")
        return True, f"{target} is released — skipped"
    if released is None:
        print(f"WARNING: no git repository, so whether {target} is released is unknown — checking its docs anyway")
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"

    # A missing doc is the doc-consistency step's finding.
    checked: list[str] = []
    issues: list[str] = []
    # The side paths' docs are upgrade docs of the same target.
    for path_baseline in (baseline, *read_upgrade_docs_side_paths(chart_dir)):
        guide = doc_dir / doc_name(path_baseline, target, "upgrade")
        deltas = doc_dir / doc_name(path_baseline, target, "values-deltas")
        if guide.is_file():
            checked.append(guide.name)
            text = guide.read_text(encoding="utf-8")
            issues.extend(upgrade_guide_layout_issues(guide.name, text, path_baseline, target))
        if deltas.is_file():
            checked.append(deltas.name)
            issues.extend(values_deltas_layout_issues(deltas.name, deltas.read_text(encoding="utf-8")))

    if not checked:
        print(f"no {baseline}-to-{target} upgrade guide or values-deltas doc — nothing to check")
        return True, "no matching docs found — skipped"
    if issues:
        print(f"WARNING: {len(issues)} layout issue(s) (report only); the layout is in {CHECKLIST_PATH}:")
        for issue in issues:
            print(" ", issue)
        return True, f"{len(issues)} layout issue(s) (report-only, not a failure)"
    print(f"OK: {', '.join(checked)} follow {CHECKLIST_PATH}")
    return True, f"layout of {', '.join(checked)} OK"
