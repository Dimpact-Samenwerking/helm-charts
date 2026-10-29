"""Check the target version's upgrade guide and values-deltas doc against docs/_UPGRADE_DOCS_CHECKLIST.md.

Only the docs of the hop to Chart.yaml's version are checked: guides of
released versions are frozen in the layout they shipped with.

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

from pathlib import Path

from lib.chart.release_baseline_basics import chart_version
from lib.chart.release_baseline_basics import upgrade_docs_baseline as read_upgrade_docs_baseline
from lib.component_docs.baseline_doc_stubs import DEPLOY_RUN_SECTION
from lib.component_docs.baseline_doc_stubs import IF_THE_RUN_FAILS_SECTION
from lib.component_docs.baseline_doc_stubs import RUNBOOK_SECTIONS
from lib.component_docs.baseline_doc_stubs import UPGRADE_GUIDE_SECTIONS
from lib.component_docs.owned_parts import generated_heading_name
from lib.upgradedoc.baseline_intro import BASELINE_INTRO_RE
from lib.upgradedoc.doc_names import doc_name
from lib.upgradedoc.string_and_parsing_basics import MarkdownHeading
from lib.upgradedoc.string_and_parsing_basics import heading_slug
from lib.upgradedoc.string_and_parsing_basics import markdown_headings
from lib.version_numbers import is_bare_version

CHECKLIST_PATH = "docs/_UPGRADE_DOCS_CHECKLIST.md"
GATEWAY_FILE_HEADING_RE = re.compile(r"^`[\w-]+-gateway\.yml`$")
_ORDER = ", ".join(f'"## {name}"' for name in UPGRADE_GUIDE_SECTIONS)


def _section_index(heading: str) -> int | None:
    """The UPGRADE_GUIDE_SECTIONS index `heading` names: the name alone, or followed by ": ..." or " (...)"."""
    for i, name in enumerate(UPGRADE_GUIDE_SECTIONS):
        if heading == name or heading.startswith((f"{name}: ", f"{name} (")):
            return i
    return None


def _section_issues(name: str, level2: list[MarkdownHeading]) -> tuple[list[str], dict[int, MarkdownHeading]]:
    """Unknown, misordered and missing "##" sections up to "## Changes"; also {section index: its heading}."""
    issues: list[str] = []
    found: dict[int, MarkdownHeading] = {}
    last_index, last_text = -1, ""
    for heading in level2:
        index = _section_index(heading.text)
        if index is None:
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
        last_index, last_text = index, heading.text
        if index == len(UPGRADE_GUIDE_SECTIONS) - 1:
            break
    for index, section in enumerate(UPGRADE_GUIDE_SECTIONS):
        if index not in found:
            after = f' after "## {UPGRADE_GUIDE_SECTIONS[index - 1]}"' if index else ""
            issues.append(f'{name}: missing "## {section}"{after}')
    return issues, found


def _if_the_run_fails_issues(name: str, headings: list[MarkdownHeading], deploy_run: MarkdownHeading) -> list[str]:
    start = headings.index(deploy_run) + 1
    end = next((i for i in range(start, len(headings)) if headings[i].marks == "##"), len(headings))
    if any(h.marks == "###" and h.text.startswith(IF_THE_RUN_FAILS_SECTION) for h in headings[start:end]):
        return []
    return [f'{name}: "## {deploy_run.text}" has no "### {IF_THE_RUN_FAILS_SECTION}" section']


def _checklist_link_issues(name: str, lines: list[str], found: dict[int, MarkdownHeading]) -> list[str]:
    """Each A to F section present must be linked from the Checklist, by its anchor."""
    checklist = found[UPGRADE_GUIDE_SECTIONS.index("Checklist")]
    first_runbook = min(found[i].line for i in range(1, len(RUNBOOK_SECTIONS) + 1) if i in found)
    checklist_text = "".join(lines[checklist.line : first_runbook])
    return [
        f'{name}: the Checklist does not link "## {heading.text}" (#{heading_slug(heading.text)})'
        for i, heading in sorted(found.items())
        if 1 <= i <= len(RUNBOOK_SECTIONS) and f"](#{heading_slug(heading.text)})" not in checklist_text
    ]


def upgrade_guide_layout_issues(name: str, text: str, upgrade_docs_baseline: str, target: str) -> list[str]:
    """Layout findings for the upgrade guide `name` with content `text`."""
    headings = markdown_headings(text)
    level2 = [h for h in headings if h.marks == "##"]
    lines = text.splitlines(keepends=True)
    opening = "".join(lines[: level2[0].line] if level2 else lines)

    issues: list[str] = []
    if BASELINE_INTRO_RE.search(opening) is None:
        issues.append(
            f"{name}: the opening does not say which version it starts from "
            f'("For environments already on **{upgrade_docs_baseline}**.")'
        )
    deltas = doc_name(upgrade_docs_baseline, target, "values-deltas")
    if f"]({deltas})" not in opening:
        issues.append(f"{name}: the opening does not link the companion {deltas}")

    section_issues, found = _section_issues(name, level2)
    issues.extend(section_issues)
    deploy_run = found.get(UPGRADE_GUIDE_SECTIONS.index(DEPLOY_RUN_SECTION))
    if deploy_run is not None:
        issues.extend(_if_the_run_fails_issues(name, headings, deploy_run))
    if UPGRADE_GUIDE_SECTIONS.index("Checklist") in found and any(
        i in found for i in range(1, len(RUNBOOK_SECTIONS) + 1)
    ):
        issues.extend(_checklist_link_issues(name, lines, found))
    return issues


def values_deltas_layout_issues(name: str, text: str) -> list[str]:
    """Layout findings for the values-deltas doc `name` with content `text`."""
    headings = markdown_headings(text)
    level2 = [h for h in headings if h.marks == "##"]
    lines = text.splitlines()
    title_end = next((h.line + 1 for h in headings if h.marks == "#"), 0)
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


def check_upgrade_doc_layout(chart_dir: Path):
    """(ok, detail) for verify-podiumd: the target version's upgrade docs follow the checklist's layout."""
    baseline = read_upgrade_docs_baseline(chart_dir)
    if not is_bare_version(baseline):
        print(f'upgrade_docs baseline "{baseline}" is missing or not a bare version — nothing to check')
        return True, "no bare upgrade_docs baseline — skipped"
    target = chart_version(chart_dir / "Chart.yaml")
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    guide = doc_dir / doc_name(baseline, target, "upgrade")
    deltas = doc_dir / doc_name(baseline, target, "values-deltas")

    # A missing doc is the doc-consistency step's finding.
    checked: list[str] = []
    issues: list[str] = []
    if guide.is_file():
        checked.append(guide.name)
        issues.extend(upgrade_guide_layout_issues(guide.name, guide.read_text(encoding="utf-8"), baseline, target))
    if deltas.is_file():
        checked.append(deltas.name)
        issues.extend(values_deltas_layout_issues(deltas.name, deltas.read_text(encoding="utf-8")))

    if not checked:
        print(f"no {baseline}-to-{target} upgrade guide or values-deltas doc — nothing to check")
        return True, "no matching docs found — skipped"
    if issues:
        print(f"{len(issues)} layout issue(s); the layout is in {CHECKLIST_PATH}:")
        for issue in issues:
            print(" ", issue)
        return False, f"{len(issues)} layout issue(s)"
    print(f"OK: {', '.join(checked)} follow {CHECKLIST_PATH}")
    return True, f"layout of {', '.join(checked)} OK"
