"""The upgrade doc's "Component versions" table row and "## Changes"
section for a component's version bump: find/update/remove the row,
build/insert/remove the section, strip stale scaffolding TODO
placeholders, and backfill rows/sections for components that changed
since upgrade_docs_baseline without being touched by this run.

The dataclasses below only bundle repeated parameter groups to stay
under pylint's too-many-arguments/too-many-locals limits."""

import re

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lib.chart.chart_state import BaselineState
from lib.chart.chart_state import ComponentState
from lib.chart.registered_paths import component_chart_versions
from lib.chart.registered_paths import image_paths_for
from lib.chart.registered_paths import version_paths_for
from lib.component_docs.baseline_doc_stubs import UPGRADE_CHANGES_STUB_TODO_LINE
from lib.component_docs.baseline_doc_stubs import UPGRADE_INTRO_STUB_TODO_LINE
from lib.component_docs.doc_lines import is_bare_placeholder_span
from lib.component_docs.doc_lines import normalize_blank_line_before_insert
from lib.component_docs.owned_parts import BLANK
from lib.component_docs.owned_parts import SectionShape
from lib.component_docs.owned_parts import edited_generated_lines
from lib.component_docs.owned_parts import generated_heading_name
from lib.component_docs.owned_parts import remove_section_owned_parts
from lib.component_docs.owned_parts import replace_section_owned_parts
from lib.component_docs.owned_parts import template_prefix_re
from lib.component_docs.owned_parts import template_re
from lib.upgradedoc.chart_image_index import ChartImageIndex
from lib.upgradedoc.consistency_checks import rowed_component_keys
from lib.upgradedoc.doc_names import images_manifest_name
from lib.upgradedoc.resolve_component_row import ResolutionContext
from lib.upgradedoc.resolve_component_row import resolve_component_row
from lib.upgradedoc.sorting_and_ordering import CHANGES_HEADING
from lib.upgradedoc.sorting_and_ordering import HeadingBlock
from lib.upgradedoc.sorting_and_ordering import OrderingContext
from lib.upgradedoc.sorting_and_ordering import block_for_component
from lib.upgradedoc.sorting_and_ordering import changes_blocks_with_lines
from lib.upgradedoc.sorting_and_ordering import changes_section_bounds
from lib.upgradedoc.sorting_and_ordering import component_insertion_index
from lib.upgradedoc.sorting_and_ordering import parse_upgrade_doc_changes_blocks
from lib.upgradedoc.string_and_parsing_basics import COMPONENT_VERSIONS_HEADING_RE
from lib.upgradedoc.string_and_parsing_basics import TableRow
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows
from lib.upgradedoc.string_and_parsing_basics import set_row_cells
from lib.upgradedoc.string_and_parsing_basics import text_names
from lib.upgradedoc.version_cells_and_key_changes import chart_version_suffix
from lib.upgradedoc.version_cells_and_key_changes import component_version_cell
from lib.upgradedoc.version_cells_and_key_changes import pin_version_text
from lib.upgradedoc.version_cells_and_key_changes import version_transition


@dataclass
class VersionChange:
    """A component's before/after app and chart versions.

    `new_chart == "-"`: native component without a Chart.yaml dependency.
    `old_chart is None`: no baseline dependency (new this hop).
    `old_app is None`: no baseline app version resolved (rendered "new")."""

    old_app: str | None = None
    new_app: str | None = None
    old_chart: str | None = None
    new_chart: str | None = None


@dataclass
class ComponentIdentity:
    """Display name (heading/prose), Chart.yaml dependency name (chart
    bullet) and values.yaml key (pin bullets) of a component."""

    friendly: str
    chart_name: str
    values_key: str


@dataclass
class DocContext:
    """chart_dir, target release label and upgrade_docs_baseline, passed
    through unchanged to the row/section builders."""

    chart_dir: Path
    target: str
    upgrade_docs_baseline: str | None = None


def find_component_row(rows: list[TableRow], friendly: str):
    """The row whose Name names `friendly` at word boundaries (see
    text_names), so "openbao" never takes an "openbao - ..." sidecar row.
    None when no row does."""
    return next((row for row in rows if text_names(row["name"], friendly)), None)


def new_row_insert_index(lines: list[str], rows: list[TableRow], friendly: str, ordering: OrderingContext):
    """Line index for a new component row: in values.yaml order among the
    existing rows, or right after the "Component versions" separator when
    the table is empty. Scoped to that section so a later pipe table is
    never hit. None if the doc has no such table."""
    if rows:
        idx = component_insertion_index(friendly, [r["name"] for r in rows], ordering)
        return rows[idx]["line_index"] if idx < len(rows) else rows[-1]["line_index"] + 1
    in_section = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if COMPONENT_VERSIONS_HEADING_RE.match(stripped):
            in_section = True
            continue
        if in_section and re.match(r"^##\s+\S", line):
            break
        if in_section and re.match(r"^\|\s*:?-+:?\s*\|", stripped):
            return i + 1
    return None


def update_component_table(text: str, friendly: str, change: VersionChange, ordering: OrderingContext):
    """Update the component's "Component versions" row, or insert one in
    values.yaml order. Returns (new_text, action), action "updated",
    "added", or None when the doc has no table."""
    lines = text.splitlines(keepends=True)
    rows = parse_upgrade_doc_rows(text)
    row = find_component_row(rows, friendly)

    app_cell = component_version_cell(change.old_app, change.new_app)
    chart_cell = component_version_cell(change.old_chart, change.new_chart)

    if row is not None:
        # No new version for a cell: leave what the row already says.
        set_row_cells(lines, row, app_cell, chart_cell)
        return "".join(lines), "updated"

    new_row_line = f"| {friendly} | {app_cell or '-'} | {chart_cell or '-'} | - |\n"
    insert_at = new_row_insert_index(lines, rows, friendly, ordering)
    if insert_at is None:
        return text, None
    lines.insert(insert_at, new_row_line)
    return "".join(lines), "added"


def remove_component_row(text: str, friendly: str):
    """Delete the component's "Component versions" row, for a bump that
    nets out to no change from upgrade_docs_baseline. Returns
    (new_text, removed)."""
    rows = parse_upgrade_doc_rows(text)
    row = find_component_row(rows, friendly)
    if row is None:
        return text, False
    lines = text.splitlines(keepends=True)
    del lines[row["line_index"]]
    return "".join(lines), True


# Wording of the generated parts of a "### ..." Changes section. The renderers format these;
# changes_body_kinds matches them, so a wording change reaches both.
INTRO_NEW = "PodiumD {target} introduces **{name}** at app version {new}."
INTRO_UNCHANGED = "**{name}**'s own app version ({new}) is unchanged this hop."
INTRO_UPGRADE = "PodiumD {target} upgrades **{name}** from app version {old}"
INTRO_UPGRADE_TO = "to {new}."
INTRO_REMOVED = "PodiumD {target} removes **{name}** (was {old})."
IMAGE_INTRO_NEW = "PodiumD {target} introduces the {image} image at {new},"
IMAGE_INTRO_KEPT = "PodiumD {target} keeps the {image} image at {new},"
IMAGE_INTRO_UPGRADE = "PodiumD {target} upgrades the {image} image to {new},"
PINNED_AT = "pinned at:"
HELM_CHART_BULLET = "- Helm chart `{chart}` `{old}` → `{new}` in"
CHART_YAML_LINE = "  `charts/podiumd/Chart.yaml`."
IMAGE_TAG_PIN_BULLET = "- Image tag pin `{path}` {pin} in"
VERSION_PIN_BULLET = "- Version pin `{path}` {pin} in"
VALUES_YAML_LINE = "  `charts/podiumd/values.yaml`."
IMAGE_PATH_BULLET = "- `{path}` {pin}"
ALIAS_NOTE = "(shares a YAML anchor with `{path}`)"
TODO_STUB = "TODO: describe this component's changes — its app version could not be resolved from the table row."
IMAGE_DIGEST_POINTER_PREFIX = "- Image / digest: see "


_FIELD_PATTERNS = {
    "target": r"\S+",
    "new": r"\S+",
    "old": r"\S+",
    "chart": r"\S+",
    "name": r".+?",
    "image": r".+?",
    "path": r"[^`\s]+",
    # pin_version_text, optionally followed by the aliased-pin note.
    "pin": (
        r"(?:`[^`]+` → `[^`]+`|`[^`]+` \((?:new|unchanged|digest changed)\))"
        r"(?: \(shares a YAML anchor with `[^`]+`\))?"
    ),
}


def _template_re(template: str) -> re.Pattern[str]:
    return template_re(template, _FIELD_PATTERNS)


_POINTER_RE = re.compile(
    re.escape(IMAGE_DIGEST_POINTER_PREFIX) + r"\[`images-\S+\.yaml`\]\(\.\./images/images-\S+\.yaml\)\.$"
)
# (opening template, required continuation template or None, kind)
_OWNED_LINES = [
    (_template_re(INTRO_NEW), None, "intro"),
    (_template_re(INTRO_UNCHANGED), None, "intro"),
    (_template_re(INTRO_UPGRADE), _template_re(INTRO_UPGRADE_TO), "intro"),
    (_template_re(INTRO_REMOVED), None, "removed"),
    (_template_re(IMAGE_INTRO_NEW), _template_re(PINNED_AT), "intro"),
    (_template_re(IMAGE_INTRO_KEPT), _template_re(PINNED_AT), "intro"),
    (_template_re(IMAGE_INTRO_UPGRADE), _template_re(PINNED_AT), "intro"),
    (_template_re(HELM_CHART_BULLET), _template_re(CHART_YAML_LINE), "bullet"),
    (_template_re(IMAGE_TAG_PIN_BULLET), _template_re(VALUES_YAML_LINE), "bullet"),
    (_template_re(VERSION_PIN_BULLET), _template_re(VALUES_YAML_LINE), "bullet"),
    (_template_re(IMAGE_PATH_BULLET), None, "bullet"),
    (_template_re(TODO_STUB), None, "stub"),
    (_POINTER_RE, None, "pointer"),
]


def changes_body_kinds(body: Sequence[str]) -> list[str | None]:
    """The owned-part kind of each line after a "### ..." heading, None for a user line.

    A line is owned only when it matches a template the renderers write; a
    continuation line ("to 1.3.", "  `charts/podiumd/values.yaml`.",
    "pinned at:") only right after its opening line.
    """
    kinds: list[str | None] = []
    i = 0
    while i < len(body):
        line = body[i].rstrip("\n")
        if not line.strip():
            kinds.append(BLANK)
            i += 1
            continue
        match = next(((cont, kind) for opener, cont, kind in _OWNED_LINES if opener.match(line)), None)
        if match is None:
            kinds.append(None)
            i += 1
            continue
        continuation, kind = match
        kinds.append(kind)
        i += 1
        if continuation is not None and i < len(body) and continuation.match(body[i].rstrip("\n")):
            kinds.append(kind)
            i += 1
    return kinds


def _heading_name(heading_line: str, body_kinds: Sequence[str | None]) -> str | None:
    """The component name of a generated "### ..." heading, None for a hand-written one.

    A stub section's heading is "<name> <chart>", owned only with the stub line in its body.
    """
    heading = heading_line.rstrip("\n").removeprefix("### ")
    name = generated_heading_name(heading)
    if name is not None:
        return name
    if "stub" in body_kinds and " " in heading:
        return heading.rsplit(" ", 1)[0]
    return None


_CHANGES_SHAPE = SectionShape(
    changes_body_kinds,
    _heading_name,
    edited_openers=[
        template_prefix_re(template, _FIELD_PATTERNS)
        for template in (
            INTRO_NEW,
            INTRO_UNCHANGED,
            INTRO_UPGRADE,
            INTRO_REMOVED,
            IMAGE_INTRO_NEW,
            IMAGE_INTRO_KEPT,
            IMAGE_INTRO_UPGRADE,
            HELM_CHART_BULLET,
            IMAGE_TAG_PIN_BULLET,
            VERSION_PIN_BULLET,
            IMAGE_PATH_BULLET,
        )
    ],
    edited_continuations=[
        template_prefix_re(template, _FIELD_PATTERNS)
        for template in (INTRO_UPGRADE_TO, PINNED_AT, CHART_YAML_LINE, VALUES_YAML_LINE)
    ],
)


def edited_changes_lines(text: str) -> list[tuple[str, str]]:
    """(heading, line) for each hand-edited generated line in the "## Changes" "### ..." sections."""
    return edited_generated_lines(text, parse_upgrade_doc_changes_blocks(text), _CHANGES_SHAPE)


def make_changes_section(
    identity: ComponentIdentity,
    target: str,
    change: VersionChange,
    image_paths: Sequence[str],
    version_paths: Sequence[str] = (),
) -> str:
    """Render a component's "### ..." Changes section.

    `image_paths` become "Image tag pin `<key>.<path>.tag`" bullets;
    `version_paths` (bare version fields, e.g. eck-stack) become
    "Version pin `<path>`" bullets. Callers must pick per image_paths_for/
    version_paths_for, or the bullet names a nonexistent values path.

    No "Helm chart" bullet when new_chart is "-" (native component) or
    old_chart is None (heading says "new"). old_app None renders
    "<app> (new)"; old_app == new_app renders "<app> (unchanged)" (the
    component qualifies only through another changed path, e.g. a new
    sidecar)."""
    chart_changed = (
        change.new_chart != "-"
        and change.old_chart is not None
        and normalize_version(change.old_chart) != normalize_version(change.new_chart)
    )
    chart_suffix = chart_version_suffix(change.old_chart, change.new_chart)
    heading = f"{identity.friendly} {version_transition(change.old_app, change.new_app)}{chart_suffix}"
    name, new = identity.friendly, change.new_app
    if change.old_app is None:
        intro = [INTRO_NEW.format(target=target, name=name, new=new) + "\n"]
    elif normalize_version(change.old_app) == normalize_version(change.new_app):
        intro = [INTRO_UNCHANGED.format(name=name, new=new) + "\n"]
    else:
        intro = [
            INTRO_UPGRADE.format(target=target, name=name, old=change.old_app) + "\n",
            INTRO_UPGRADE_TO.format(new=new) + "\n",
        ]
    pin = pin_version_text(change.old_app, change.new_app)
    bullets: list[str] = []
    if chart_changed:
        chart_bullet = HELM_CHART_BULLET.format(chart=identity.chart_name, old=change.old_chart, new=change.new_chart)
        bullets += [chart_bullet + "\n", CHART_YAML_LINE + "\n"]
    for path in image_paths:
        bullets += [IMAGE_TAG_PIN_BULLET.format(path=f"{identity.values_key}.{path}.tag", pin=pin) + "\n"]
        bullets += [VALUES_YAML_LINE + "\n"]
    for path in version_paths:
        bullets += [VERSION_PIN_BULLET.format(path=f"{identity.values_key}.{path}", pin=pin) + "\n"]
        bullets += [VALUES_YAML_LINE + "\n"]
    return render_changes_section(heading, intro, bullets, target)


def image_digest_pointer(target: str) -> str:
    """The "- Image / digest" line that ends every Changes section."""
    name = images_manifest_name(target)
    return f"{IMAGE_DIGEST_POINTER_PREFIX}[`{name}`](../images/{name}).\n"


@dataclass(frozen=True)
class PointerIssue:
    """A Changes section's "- Image / digest" pointer problem; `line` is where it applies."""

    heading: str
    kind: Literal["missing", "duplicate", "no-blank-line-before"]
    line: int
    count: int = 1


def pointer_issues(text: str) -> list[PointerIssue]:
    """Each Changes section's missing, duplicate or not blank-separated pointer, from one pass.

    TODO stub sections and removed items (their image is in no manifest) have no
    pointer by design and are skipped. A missing pointer's `line` is the
    section's last non-blank line.
    """
    lines, blocks = changes_blocks_with_lines(text)
    issues: list[PointerIssue] = []
    for block in blocks:
        body = range(block["start"] + 1, block["end"])
        if {"stub", "removed"} & set(changes_body_kinds([lines[i] for i in body])):
            continue
        pointers = [i for i in body if lines[i].startswith(IMAGE_DIGEST_POINTER_PREFIX)]
        if not pointers:
            last = max((i for i in body if lines[i].strip()), default=block["start"])
            issues.append(PointerIssue(block["heading"], "missing", last))
        elif len(pointers) > 1:
            issues.append(PointerIssue(block["heading"], "duplicate", pointers[1], len(pointers)))
        issues.extend(
            PointerIssue(block["heading"], "no-blank-line-before", i) for i in pointers if lines[i - 1].strip()
        )
    return issues


def fix_pointer_issues(text: str, target: str) -> tuple[str, list[PointerIssue]]:
    """Append a missing pointer after a blank line and add missing blank lines; duplicates are left.

    Returns (text, fixed issues).
    """
    fixed = [issue for issue in pointer_issues(text) if issue.kind != "duplicate"]
    lines = text.splitlines(keepends=True)
    for issue in sorted(fixed, key=lambda i: i.line, reverse=True):
        if issue.kind == "missing":
            lines[issue.line + 1 : issue.line + 1] = ["\n", image_digest_pointer(target)]
        else:
            lines.insert(issue.line, "\n")
    return "".join(lines), fixed


def render_changes_section(heading: str, intro: Sequence[str], bullets: Sequence[str], target: str) -> str:
    """A "### <heading>" Changes block: heading, intro, bullets and the image digest pointer.

    `intro` and `bullets` are lines ending in one "\\n"; the parts get one
    blank line between them.
    """
    parts = [f"### {heading}\n", "".join(intro), "".join(bullets), image_digest_pointer(target)]
    return "\n".join(part for part in parts if part) + "\n"


def _find_standalone_placeholder_line(lines: list[str], end: int, placeholder_text: str):
    """Index of a line in lines[:end] that stripped-equals placeholder_text
    and is its own paragraph (blank or doc edge on both sides), else None.
    Other content may surround it, e.g. the intro blockquote."""
    target = placeholder_text.strip()
    for i in range(end):
        if lines[i].strip() != target:
            continue
        before_ok = i == 0 or not lines[i - 1].strip()
        after_ok = i + 1 == end or not lines[i + 1].strip()
        if before_ok and after_ok:
            return i
    return None


def _strip_standalone_placeholder_line(lines: list[str], end: int, placeholder_text: str):
    """Remove that standalone placeholder line in place, collapsing the
    double blank left behind. Returns True if a line was removed."""
    idx = _find_standalone_placeholder_line(lines, end, placeholder_text)
    if idx is None:
        return False
    del lines[idx]
    if 0 < idx < len(lines) and not lines[idx].strip() and not lines[idx - 1].strip():
        del lines[idx]
    return True


def _strip_bare_changes_todo(lines: list[str], changes_idx: int, end_bound: int):
    """Delete "## Changes"' bare TODO stub in place if that is all the span
    holds; returns the new end bound (end_bound unchanged if nothing was
    stripped)."""
    if not is_bare_placeholder_span(lines, changes_idx + 1, end_bound, UPGRADE_CHANGES_STUB_TODO_LINE):
        return end_bound
    del lines[changes_idx + 1 : end_bound]
    return changes_idx + 1


def _insert_index_for_empty_changes_section(lines: list[str], changes_idx: int, section_end: int):
    """Insert index for a "## Changes" section with no blocks yet, after
    stripping both upgrade.md stub placeholders."""
    first_heading_idx = next((i for i, line in enumerate(lines) if re.match(r"^##\s+\S", line)), len(lines))
    if _strip_standalone_placeholder_line(lines, first_heading_idx, UPGRADE_INTRO_STUB_TODO_LINE):
        # Removal takes one or two lines: recompute instead of adjusting.
        new_changes_idx, section_end = changes_section_bounds(lines)
        if new_changes_idx is not None:
            changes_idx = new_changes_idx
    return _strip_bare_changes_todo(lines, changes_idx, section_end)


def insert_changes_section(text: str, section_text: str, friendly: str, ordering: OrderingContext):
    """Insert section_text into "## Changes" in values.yaml component order.
    Appended before the next "## " heading (or EOF) when the section has no
    blocks yet, after stripping both stub TODO placeholders (one event);
    appended at EOF under a new "## Changes" heading when the section
    doesn't exist, so later runs find the block instead of adding it again."""
    blocks = parse_upgrade_doc_changes_blocks(text)
    lines = text.splitlines(keepends=True)
    changes_idx, section_end = changes_section_bounds(lines)
    if changes_idx is None:
        if text and not text.endswith("\n\n"):
            text = text.rstrip("\n") + "\n\n"
        return f"{text}{CHANGES_HEADING}\n\n{section_text}"

    if not blocks:
        insert_at = _insert_index_for_empty_changes_section(lines, changes_idx, section_end)
    else:
        idx = component_insertion_index(friendly, [b["heading"] for b in blocks], ordering)
        insert_at = blocks[idx]["start"] if idx < len(blocks) else section_end

    insert_at = normalize_blank_line_before_insert(lines, insert_at)
    lines[insert_at:insert_at] = [section_text]
    return "".join(lines)


def strip_stale_upgrade_placeholders(text: str):
    """Remove the intro TODO and "## Changes"' bare TODO once a real "### "
    block exists; untouched otherwise. Also the checker: callers that only
    ask whether a placeholder is stranded use `changed` and discard the
    text. Returns (new_text, changed)."""
    blocks = parse_upgrade_doc_changes_blocks(text)
    if not blocks:
        return text, False

    lines = text.splitlines(keepends=True)
    changed = False

    first_heading_idx = next((i for i, line in enumerate(lines) if re.match(r"^##\s+\S", line)), len(lines))
    if _strip_standalone_placeholder_line(lines, first_heading_idx, UPGRADE_INTRO_STUB_TODO_LINE):
        changed = True
        blocks = parse_upgrade_doc_changes_blocks("".join(lines))  # indices shifted -- recompute

    changes_idx, _ = changes_section_bounds(lines)
    if changes_idx is not None and blocks:
        first_block_start = blocks[0]["start"]
        new_end = _strip_bare_changes_todo(lines, changes_idx, first_block_start)
        if new_end != first_block_start:
            lines[changes_idx + 1 : changes_idx + 1] = ["\n"]
            changed = True

    if not changed:
        return text, False
    return "".join(lines), True


def replace_changes_block(text: str, block: HeadingBlock, section_text: str) -> str:
    """`block` with its owned parts replaced by `section_text`'s; user lines stay in place."""
    return replace_section_owned_parts(text, block, section_text, _CHANGES_SHAPE)


def remove_changes_block(text: str, block: HeadingBlock | None) -> tuple[str, bool, bool]:
    """Remove `block`'s owned parts: (new_text, removed, kept_user_text); see remove_section_owned_parts."""
    return remove_section_owned_parts(text, block, _CHANGES_SHAPE)


def component_changes_block(text: str, friendly: str, ordering: OrderingContext) -> HeadingBlock | None:
    """The component's "### ..." block, matched by identity the same way
    check_docs_consistency pairs headings with rows, so a sidecar's block is
    never taken for its parent's."""
    return block_for_component(
        parse_upgrade_doc_changes_blocks(text), friendly, ordering.deps, ordering.canonical_names
    )


def remove_changes_section(text: str, friendly: str, ordering: OrderingContext) -> tuple[str, bool, bool]:
    """remove_changes_block for the component's block: (new_text, removed, kept_user_text)."""
    return remove_changes_block(text, component_changes_block(text, friendly, ordering))


def replace_changes_section(text: str, section_text: str, friendly: str, ordering: OrderingContext) -> str:
    """Write the component's Changes section: replace the owned parts of its block, or insert it."""
    block = component_changes_block(text, friendly, ordering)
    if block is None:
        return insert_changes_section(text, section_text, friendly, ordering)
    return replace_changes_block(text, block, section_text)


def resolve_component_own_version_change(
    key: str,
    target_state: ComponentState,
    baseline_state: BaselineState,
    chart_dir: Path | None,
    upgrade_docs_baseline: str | None = None,
):
    """(dep, chart_name, old_chart, new_chart, old_app, new_app, unchanged)
    for a changed component key. `unchanged` is True when both its own chart
    and primary app version are identical: the change is elsewhere (e.g. a
    new sidecar, which gets its own row), so no row is needed for it.

    None for a key that is neither a Chart.yaml dependency nor a native
    component. Shared by add_missing_component_rows and
    check_docs_consistency so they agree on which keys need a row."""
    chart_versions = component_chart_versions(chart_dir, key, target_state.deps, baseline_state.deps)
    if chart_versions is None:
        return None
    dep, chart_name, old_chart, new_chart = chart_versions
    chart_unchanged = new_chart == "-" or (
        old_chart is not None and normalize_version(old_chart) == normalize_version(new_chart)
    )
    # The same resolver as the key's table row, so a row added here can't contradict it.
    resolved = resolve_component_row(
        key, {}, ResolutionContext(chart_dir, target_state, baseline_state, upgrade_docs_baseline)
    )
    old_app = resolved["baseline_app"] if resolved["kind"] != "unmatched" else None
    new_app = resolved["target_app"] if resolved["kind"] != "unmatched" else None
    # No own app version on either side (only sidecar images) is unchanged too:
    # a sidecar change gets its own row, not one for its parent.
    app_unchanged = normalize_version(old_app) == normalize_version(new_app)
    return dep, chart_name, old_chart, new_chart, old_app, new_app, (chart_unchanged and app_unchanged)


def component_changes_section(identity: ComponentIdentity, change: VersionChange, doc_context: DocContext) -> str:
    """make_changes_section for a dependency or native component, with its registered pins.

    version_paths_for wins over image_paths_for: registered bare-version
    fields (eck-stack) have no image block, so the generic
    "<key>.image.tag" would name a nonexistent path."""
    version_paths = version_paths_for(identity.chart_name, doc_context.chart_dir)
    image_paths = [] if version_paths else image_paths_for(identity.chart_name, doc_context.chart_dir)
    return make_changes_section(identity, doc_context.target, change, image_paths, version_paths)


def _new_component_section(key: str, chart_name: str, change: VersionChange, doc_context: DocContext):
    """Changes section for an auto-added row: component_changes_section when
    the app version resolved, else a TODO stub rather than guessed prose."""
    if change.new_app is not None:
        return component_changes_section(ComponentIdentity(key, chart_name, key), change, doc_context)
    chart_suffix = (
        f"{change.old_chart} → {change.new_chart}"
        if change.old_chart and normalize_version(change.old_chart) != normalize_version(change.new_chart)
        else change.new_chart
    )
    return (
        f"### {key} {chart_suffix}\n\n"
        f"TODO: describe this component's changes — its app version could not be "
        f"resolved automatically.\n\n"
    )


def _add_missing_row_for_key(
    text: str, key: str, target_state: ComponentState, baseline_state: BaselineState, doc_context: DocContext
):
    """Add `key`'s missing row and Changes section. Returns (new_text, True)
    if added; (text, False) when unresolvable, unchanged, or the doc has no
    table."""
    resolved = resolve_component_own_version_change(
        key, target_state, baseline_state, doc_context.chart_dir, doc_context.upgrade_docs_baseline
    )
    if resolved is None:
        return text, False
    _, chart_name, old_chart, new_chart, old_app, new_app, unchanged = resolved
    if unchanged:
        return text, False

    # "-" only for the table cell; the section needs the raw None to pick
    # the TODO stub.
    text, table_action = update_component_table(
        text,
        key,
        VersionChange(old_app, new_app if new_app is not None else "-", old_chart, new_chart),
        OrderingContext(target_state.deps, target_state.values),
    )
    if table_action is None:
        return text, False  # doc has no "Component versions" table at all to insert into

    change = VersionChange(old_app, new_app, old_chart, new_chart)
    text = replace_changes_section(
        text,
        _new_component_section(key, chart_name, change, doc_context),
        key,
        OrderingContext(target_state.deps, target_state.values),
    )
    return text, True


def add_missing_component_rows(
    text: str,
    doc_context: DocContext,
    target_state: ComponentState,
    baseline_state: BaselineState,
    actual_changed_keys: set[str],
) -> tuple[str, list[str]]:
    """Add a row and Changes section for every changed key without a row,
    matching exactly what check_docs_consistency's "changed but has no row"
    finding reports. Rows use the dependency's literal name/alias.

    Keys that are neither a dependency nor a native component are skipped
    (add those by hand). Native components get chart "-". An unresolvable
    app version gets "-" and a TODO-stub section. Returns
    (new_text, added_names)."""
    canonical_names = ChartImageIndex(doc_context.chart_dir, target_state.deps, target_state.values).canonical_names
    matched_keys = rowed_component_keys(parse_upgrade_doc_rows(text), target_state.deps, canonical_names)
    added_names: list[str] = []
    for key in sorted(actual_changed_keys - matched_keys):
        text, added = _add_missing_row_for_key(text, key, target_state, baseline_state, doc_context)
        if added:
            added_names.append(key)
    return text, added_names
