"""values-deltas.md per-component "## <friendly> ..." sections, plus gemeente-specific.md placeholder checks.

Shared by update-component-version, update-image-version and fix-doc-consistency."""

import re

from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.registered_paths import component_chart_versions
from lib.component_docs.baseline_doc_stubs import GEMEENTE_SPECIFIC_STUB_LINE
from lib.component_docs.baseline_doc_stubs import VALUES_DELTAS_STUB_TODO_LINE
from lib.component_docs.owned_parts import BLANK
from lib.component_docs.owned_parts import generated_heading_name
from lib.component_docs.owned_parts import remove_section_owned_parts
from lib.component_docs.owned_parts import replace_section_owned_parts
from lib.component_docs.owned_parts import template_re
from lib.upgradedoc.app_version_and_image_paths import actual_app_version
from lib.upgradedoc.sorting_and_ordering import HeadingBlock
from lib.upgradedoc.sorting_and_ordering import block_for_component
from lib.upgradedoc.sorting_and_ordering import component_order_key
from lib.upgradedoc.sorting_and_ordering import insertion_index
from lib.upgradedoc.sorting_and_ordering import parse_values_delta_sections
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import changes_heading_identities
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.version_cells_and_key_changes import KEY_ADDED
from lib.upgradedoc.version_cells_and_key_changes import KEY_REMOVED
from lib.upgradedoc.version_cells_and_key_changes import KEY_RENAMED
from lib.upgradedoc.version_cells_and_key_changes import append_to_doc
from lib.upgradedoc.version_cells_and_key_changes import component_version_cell
from lib.upgradedoc.version_cells_and_key_changes import key_change_lines
from lib.upgradedoc.version_cells_and_key_changes import missing_key_change_lines
from lib.upgradedoc.version_cells_and_key_changes import strip_html_comments
from lib.yaml_types import YamlMapping


def values_delta_section_heading(
    friendly: str, old_app: str | None, new_app: str | None, old_chart: str | None, new_chart: str | None
):
    """The "## <friendly> <app> (chart ...)" heading for a component's values-deltas.md section.

    `new_chart == "-"` marks a native component: the chart clause is dropped.
    None `old_app`/`old_chart` render "(new)" via component_version_cell, matching
    make_changes_section. `new_app is None` (unresolvable) yields a chart-only
    heading with a TODO note."""
    if new_app is None:
        if new_chart == "-":
            return (
                f"## {friendly} — TODO: describe this component's changes; its app version "
                f"could not be resolved automatically.\n"
            )
        chart_bit = (
            f"chart {old_chart} → {new_chart}"
            if old_chart and normalize_version(old_chart) != normalize_version(new_chart)
            else f"chart {new_chart}, unchanged"
        )
        return (
            f"## {friendly} {chart_bit} — TODO: describe this component's changes; its app "
            f"version could not be resolved automatically.\n"
        )

    app_bit = component_version_cell(old_app, new_app)
    if new_chart == "-":
        chart_bit = ""
    elif old_chart is None:
        chart_bit = f" (chart {new_chart}, new)"
    else:
        chart_changed = normalize_version(old_chart) != normalize_version(new_chart)
        chart_bit = f" (chart {old_chart} → {new_chart})" if chart_changed else f" (chart {new_chart}, unchanged)"
    return f"## {friendly} {app_bit}{chart_bit}\n"


def find_values_delta_section(
    text: str, friendly: str, deps: list[ChartDependency], canonical_names: Mapping[str, tuple[str, ...]] | None = None
):
    """The existing "## ..." section sharing an identity with `friendly` (see changes_heading_identities), or None.

    Lets a hand-written section covering the component be reused instead of
    adding a duplicate."""
    target_idents = changes_heading_identities(friendly, deps, canonical_names)
    if not target_idents:
        return None
    for section in parse_values_delta_sections(text):
        if changes_heading_identities(section["heading"], deps, canonical_names) & target_idents:
            return section
    return None


def _is_bare_values_deltas_todo_stub(lines: list[str]):
    """True if `lines` is exactly the values-deltas stub: an H1 title plus VALUES_DELTAS_STUB_TODO_LINE."""
    non_blank = [line.strip() for line in lines if line.strip()]
    return (
        len(non_blank) == 2 and non_blank[0].startswith("# ") and non_blank[1] == VALUES_DELTAS_STUB_TODO_LINE.strip()
    )


@dataclass
class ValuesDeltaOrdering:
    """Component identity and values.yaml-order context for placing a values-deltas.md section."""

    deps: list[ChartDependency]
    values: YamlMapping | None
    canonical_names: dict[str, tuple[str, ...]] | None = None


@dataclass
class ValuesDeltaBaseline:
    """deps/values at upgrade_docs_baseline, used to resolve a new section's old versions."""

    deps: list[ChartDependency] | None
    values: YamlMapping | None


def insert_values_delta_section(
    text: str, friendly: str, heading_line: str, body_lines: list[str], ordering: ValuesDeltaOrdering
):
    """Insert a new section (heading_line ends in a newline) in values.yaml component order.

    Mirrors insert_changes_section one heading level up, including dropping the
    bare TODO stub before the first real section lands."""
    body = "".join(body_lines)
    section_text = heading_line + "\n" + body + ("\n" if body else "")
    sections = parse_values_delta_sections(text)
    lines = text.splitlines(keepends=True)
    if not sections:
        if _is_bare_values_deltas_todo_stub(lines):
            lines = [line for line in lines if line.strip() != VALUES_DELTAS_STUB_TODO_LINE.strip()]
            text = "".join(lines)
        if text and not text.endswith("\n\n"):
            text = text.rstrip("\n") + "\n\n"
        return text + section_text

    key_order = values_key_order(ordering.values)
    new_key = component_order_key(friendly, ordering.deps, key_order, ordering.canonical_names, ordering.values)
    existing_keys = [
        component_order_key(s["heading"], ordering.deps, key_order, ordering.canonical_names, ordering.values)
        for s in sections
    ]
    idx = insertion_index(new_key, existing_keys)
    insert_at = sections[idx]["start"] if idx < len(sections) else len(lines)
    if insert_at > 0 and lines[insert_at - 1].strip():
        lines.insert(insert_at, "\n")
        insert_at += 1
    lines[insert_at:insert_at] = [section_text]
    return "".join(lines)


def strip_stale_values_deltas_todo_stub(text: str):
    """Remove the TODO stub line left between the H1 title and the first real section.

    Callers can use the `changed` flag alone as a check. A doc with no real
    section yet is left alone. Returns (new_text, changed)."""
    sections = parse_values_delta_sections(text)
    if not sections:
        return text, False

    lines = text.splitlines(keepends=True)
    first_section_start = sections[0]["start"]
    prefix = lines[:first_section_start]
    if not _is_bare_values_deltas_todo_stub(prefix):
        return text, False

    title_line = next(line for line in prefix if line.strip())
    return title_line + "\n" + "".join(lines[first_section_start:]), True


GEMEENTE_SECTION_HEADING_RE = re.compile(r"^##\s+\S.*$", re.MULTILINE)


def has_real_gemeente_specific_content(text: str):
    """True if gemeente-specific.md has a real "## ..." section outside HTML comments.

    The stub's example heading lives inside a "<!-- ... -->" block, hence
    scanning strip_html_comments' output."""
    return bool(GEMEENTE_SECTION_HEADING_RE.search(strip_html_comments(text)))


def has_stale_gemeente_specific_placeholder(text: str):
    """True if gemeente-specific.md still has its "_None recorded yet._" line next to a real section.

    Check-only: the content is human-authored, so nothing auto-fixes it."""
    if not has_real_gemeente_specific_content(text):
        return False
    return any(line.strip() == GEMEENTE_SPECIFIC_STUB_LINE.strip() for line in text.splitlines())


def append_values_delta_section_body(text: str, section: HeadingBlock, new_lines: list[str]):
    """Append new_lines at the end of an existing section, blank-line-separated, leaving its content untouched."""
    lines = text.splitlines(keepends=True)
    head = "".join(lines[: section["end"]])
    tail = "".join(lines[section["end"] :])
    new_head = append_to_doc(head, new_lines)
    if tail:
        new_head = new_head.rstrip("\n") + "\n\n"
    return new_head + tail


_KEY_LINE_RES = [
    template_re(template, {"path": r"[^`\s]+", "new_path": r"[^`\s]+"})
    for template in (KEY_ADDED, KEY_REMOVED, KEY_RENAMED)
]
_TODO_HEADING_RE = re.compile(r"^(?P<name>.+?)(?: chart [^—]*)? — TODO: describe this component's changes; .*$")


def values_delta_body_kinds(body: Sequence[str]) -> list[str | None]:
    """The owned-part kind of each line after a "## ..." heading: "keys" for a
    describe_key_changes line, BLANK, or None for a user line."""
    kinds: list[str | None] = []
    for line in body:
        text = line.rstrip("\n")
        if not text.strip():
            kinds.append(BLANK)
        elif any(r.match(text) for r in _KEY_LINE_RES):
            kinds.append("keys")
        else:
            kinds.append(None)
    return kinds


def _values_delta_heading_name(heading_line: str, _body_kinds: Sequence[str | None]) -> str | None:
    """The component name of a generated "## ..." heading, None for a hand-written one."""
    return generated_heading_name(heading_line.rstrip("\n").removeprefix("## "), _TODO_HEADING_RE)


def _component_section(
    text: str, friendly: str, deps: list[ChartDependency], canonical_names: Mapping[str, tuple[str, ...]] | None
) -> HeadingBlock | None:
    """The section naming exactly `friendly`'s component; sections covering several components never match."""
    return block_for_component(parse_values_delta_sections(text), friendly, deps, canonical_names)


def values_delta_section_for(
    text: str, friendly: str, deps: list[ChartDependency], canonical_names: Mapping[str, tuple[str, ...]] | None = None
) -> HeadingBlock | None:
    """`friendly`'s own section, else the first section sharing an identity with it, else None.

    The one lookup the writer and the checker both use for a component's key lines."""
    own = _component_section(text, friendly, deps, canonical_names)
    return own if own is not None else find_values_delta_section(text, friendly, deps, canonical_names)


def section_block_text(text: str, section: HeadingBlock):
    """The heading line and body of `section`."""
    return "".join(text.splitlines(keepends=True)[section["start"] : section["end"]])


def remove_values_delta_section(
    text: str, friendly: str, deps: list[ChartDependency], canonical_names: Mapping[str, tuple[str, ...]] | None = None
) -> tuple[str, bool, bool]:
    """Remove the generated parts of `friendly`'s section: (new_text, removed, kept_user_text).

    See remove_section_owned_parts."""
    return remove_section_owned_parts(
        text, _component_section(text, friendly, deps, canonical_names), values_delta_body_kinds
    )


def write_values_delta_section(
    text: str, friendly: str, heading_line: str, key_lines: list[str], ordering: "ValuesDeltaOrdering"
) -> str:
    """Write `friendly`'s section: replace the generated heading and key lines of its section, or insert one.

    The heading is replaced only when it is generated for the same component;
    user lines stay in place.
    """
    section = _component_section(text, friendly, ordering.deps, ordering.canonical_names)
    if section is None:
        return insert_values_delta_section(text, friendly, heading_line, key_lines, ordering)
    text, section = _insert_first_key_lines(text, section, key_lines)
    section_text = heading_line + "\n" + "".join(key_lines)
    return replace_section_owned_parts(text, section, section_text, values_delta_body_kinds, _values_delta_heading_name)


def _insert_first_key_lines(text: str, section: HeadingBlock, key_lines: list[str]) -> tuple[str, HeadingBlock]:
    """(text, section) with key_lines right after the heading, for a section with user lines but no key lines.

    replace_section_owned_parts would put them after the user text instead; key
    lines lead every section."""
    lines = text.splitlines(keepends=True)
    body_start = section["start"] + 1
    kinds = values_delta_body_kinds(lines[body_start : section["end"]])
    if not key_lines or "keys" in kinds or None not in kinds:
        return text, section
    first_user = body_start + kinds.index(None)
    inserted = [*([] if first_user > body_start else ["\n"]), *key_lines, "\n"]
    lines[first_user:first_user] = inserted
    return "".join(lines), {**section, "end": section["end"] + len(inserted)}


def _values_delta_new_section_heading(
    chart_dir: Path, key: str, ordering: ValuesDeltaOrdering, baseline: ValuesDeltaBaseline
):
    """Heading for a new section for `key`; None when it has no Chart.yaml dependency or native entry."""
    chart_versions = component_chart_versions(chart_dir, key, ordering.deps, baseline.deps)
    if chart_versions is None:
        return None
    dep, chart_name, old_chart, new_chart = chart_versions
    old_app = actual_app_version(baseline.values, key, chart_name) if baseline.values else None
    new_app = actual_app_version(ordering.values, key, chart_name, chart_dir=chart_dir, dep=dep)
    return values_delta_section_heading(key, old_app, new_app, old_chart, new_chart)


def _sync_section_key_lines(
    text: str, key: str, section: HeadingBlock, key_lines: list[str], ordering: ValuesDeltaOrdering
) -> str:
    """`section` with `key`'s generated key lines, user text untouched.

    The component's own section gets its key lines rewritten, right after the
    heading when it has none yet. A section shared with other components only
    gets the missing lines appended, since its generated lines can't be told apart."""
    if section == _component_section(text, key, ordering.deps, ordering.canonical_names):
        heading_line = text.splitlines(keepends=True)[section["start"]]
        return write_values_delta_section(text, key, heading_line, key_lines, ordering)
    missing = missing_key_change_lines(section_block_text(text, section), key_lines)
    return append_values_delta_section_body(text, section, missing) if missing else text


def sync_values_delta_sections(
    text: str,
    chart_dir: Path,
    ordering: ValuesDeltaOrdering,
    baseline: ValuesDeltaBaseline,
    actual_changed_keys: set[str],
) -> tuple[str, list[str], list[str]]:
    """Give every key in `actual_changed_keys` its describe_key_changes lines.

    Writes them into the section for the key's identity (see
    _sync_section_key_lines), or creates one in values.yaml order. No new
    section is created for a key without key lines (a pure version bump needs no
    gemeente action) or without a dependency/native entry.
    Returns (new_text, created_names, updated_names)."""
    created_names: list[str] = []
    updated_names: list[str] = []
    for key in sorted(actual_changed_keys):
        key_lines = key_change_lines(key, baseline.values, ordering.values)
        section = values_delta_section_for(text, key, ordering.deps, ordering.canonical_names)
        if section is not None:
            new_text = _sync_section_key_lines(text, key, section, key_lines, ordering)
            if new_text != text:
                text = new_text
                updated_names.append(key)
            continue
        if not key_lines:
            continue

        heading_line = _values_delta_new_section_heading(chart_dir, key, ordering, baseline)
        if heading_line is None:
            continue
        text = insert_values_delta_section(text, key, heading_line, key_lines, ordering)
        created_names.append(key)

    return text, created_names, updated_names


def prune_empty_values_delta_sections(text: str) -> tuple[str, list[str]]:
    """Delete every "## ..." section with a blank body, with its trailing blank lines.

    Hand-written sections always have prose, so only generated heading-only ones
    are hit. Returns (new_text, removed_headings)."""
    lines = text.splitlines(keepends=True)
    sections = parse_values_delta_sections(text)
    removed_headings: list[str] = []
    for section in reversed(sections):
        body = "".join(lines[section["start"] + 1 : section["end"]]).strip()
        if body:
            continue
        start, end = section["start"], section["end"]
        while end < len(lines) and not lines[end].strip():
            end += 1
        del lines[start:end]
        removed_headings.append(section["heading"])
    return "".join(lines), list(reversed(removed_headings))
