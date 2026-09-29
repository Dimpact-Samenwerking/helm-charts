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

from lib.chart.chart_yaml import ChartDependency
from lib.chart.historical_baselines import historical_app_version_for_path
from lib.chart.registered_paths import component_chart_versions
from lib.chart.registered_paths import image_paths_for
from lib.chart.registered_paths import native_components
from lib.chart.registered_paths import version_paths_for
from lib.chart.values_tree_primitives import values_key_of
from lib.component_docs.baseline_doc_stubs import UPGRADE_CHANGES_STUB_TODO_LINE
from lib.component_docs.baseline_doc_stubs import UPGRADE_INTRO_STUB_TODO_LINE
from lib.upgradedoc.app_version_and_image_paths import actual_app_version
from lib.upgradedoc.consistency_checks import resolve_component_identity
from lib.upgradedoc.sorting_and_ordering import HeadingBlock
from lib.upgradedoc.sorting_and_ordering import changes_section_bounds
from lib.upgradedoc.sorting_and_ordering import component_order_key
from lib.upgradedoc.sorting_and_ordering import insertion_index
from lib.upgradedoc.sorting_and_ordering import parse_upgrade_doc_changes_blocks
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import COMPONENT_VERSIONS_HEADING_RE
from lib.upgradedoc.string_and_parsing_basics import TableRow
from lib.upgradedoc.string_and_parsing_basics import changes_heading_identities
from lib.upgradedoc.string_and_parsing_basics import match_dependency_excluding_sidecar_names
from lib.upgradedoc.string_and_parsing_basics import match_native_component
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows
from lib.upgradedoc.string_and_parsing_basics import text_names
from lib.upgradedoc.version_cells_and_key_changes import component_version_cell
from lib.upgradedoc.version_cells_and_key_changes import version_change_suffix
from lib.yaml_types import YamlMapping


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
class OrderingContext:
    """Inputs for component_order_key/insertion_index. canonical_names lets a
    bare "global" shared-image entry sort at its values.yaml position."""

    deps: list[ChartDependency]
    values: YamlMapping | None
    canonical_names: dict[str, tuple[str, ...]] | None = None


@dataclass
class ComponentIdentity:
    """Display name (heading/prose), Chart.yaml dependency name (chart
    bullet) and values.yaml key (pin bullets) of a component."""

    friendly: str
    chart_name: str
    values_key: str


@dataclass
class ComponentState:
    """Target or baseline deps/values; never mixed across sides."""

    deps: list[ChartDependency]
    values: YamlMapping


@dataclass
class BaselineState:
    """deps/values at upgrade_docs_baseline. deps is None when no baseline
    was resolved: baseline comparisons are then skipped."""

    deps: list[ChartDependency] | None
    values: YamlMapping | None


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


def _new_row_insert_index(lines: list[str], rows: list[TableRow], friendly: str, ordering: OrderingContext):
    """Line index for a new component row: in values.yaml order among the
    existing rows, or right after the "Component versions" separator when
    the table is empty. Scoped to that section so a later pipe table is
    never hit. None if the doc has no such table."""
    if rows:
        key_order = values_key_order(ordering.values)
        new_key = component_order_key(friendly, ordering.deps, key_order, ordering.canonical_names, ordering.values)
        existing_keys = [
            component_order_key(r["name"], ordering.deps, key_order, ordering.canonical_names, ordering.values)
            for r in rows
        ]
        idx = insertion_index(new_key, existing_keys)
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
        old_line = lines[row["line_index"]]
        cells = [c.strip() for c in old_line.strip().strip("|").split("|")]
        # No new version for a cell: leave what the row already says.
        if app_cell is not None:
            cells[1] = app_cell
        if chart_cell is not None:
            cells[2] = chart_cell
        suffix = "\n" if old_line.endswith("\n") else ""
        lines[row["line_index"]] = "| " + " | ".join(cells) + " |" + suffix
        return "".join(lines), "updated"

    new_row_line = f"| {friendly} | {app_cell or '-'} | {chart_cell or '-'} | - |\n"
    insert_at = _new_row_insert_index(lines, rows, friendly, ordering)
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
    if change.new_chart == "-":
        chart_changed = False
        chart_suffix = ""
    elif change.old_chart is None:
        chart_changed = False
        chart_suffix = f" (chart {change.new_chart}, new)"
    else:
        chart_changed = normalize_version(change.old_chart) != normalize_version(change.new_chart)
        chart_suffix = (
            f" (chart {change.old_chart} → {change.new_chart})"
            if chart_changed
            else f" (chart {change.new_chart}, unchanged)"
        )
    app_suffix = version_change_suffix(change.old_app, change.new_app)
    app_heading = f"{change.new_app} {app_suffix}" if app_suffix else f"{change.old_app} → {change.new_app}"
    lines = [f"### {identity.friendly} {app_heading}{chart_suffix}\n\n"]
    if change.old_app is None:
        lines.append(f"PodiumD {target} introduces **{identity.friendly}** at app version {change.new_app}.\n\n")
    elif normalize_version(change.old_app) == normalize_version(change.new_app):
        lines.append(f"**{identity.friendly}**'s own app version ({change.new_app}) is unchanged this hop.\n\n")
    else:
        lines.append(f"PodiumD {target} upgrades **{identity.friendly}** from app version {change.old_app}\n")
        lines.append(f"to {change.new_app}.\n\n")
    pin_suffix = f"`{change.new_app}` {app_suffix}" if app_suffix else f"`{change.old_app}` → `{change.new_app}`"
    if chart_changed:
        lines.append(f"- Helm chart `{identity.chart_name}` `{change.old_chart}` → `{change.new_chart}` in\n")
        lines.append("  `charts/podiumd/Chart.yaml`.\n")
    for path in image_paths:
        lines.append(f"- Image tag pin `{identity.values_key}.{path}.tag` {pin_suffix} in\n")
        lines.append("  `charts/podiumd/values.yaml`.\n")
    for path in version_paths:
        lines.append(f"- Version pin `{identity.values_key}.{path}` {pin_suffix} in\n")
        lines.append("  `charts/podiumd/values.yaml`.\n")
    lines.append(f"- Image / digest: see [`images-{target}.yaml`](../images/images-{target}.yaml).\n\n")
    return "".join(lines)


def _is_bare_placeholder_span(lines: list[str], start: int, end: int, placeholder_text: str):
    """True if lines[start:end] holds only blank lines and exactly one line
    equal to placeholder_text (stripped). Exact match on purpose: human
    prose mentioning the placeholder must never be deleted."""
    non_blank = [line.strip() for line in lines[start:end] if line.strip()]
    return non_blank == [placeholder_text.strip()]


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
    if not _is_bare_placeholder_span(lines, changes_idx + 1, end_bound, UPGRADE_CHANGES_STUB_TODO_LINE):
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


def _normalize_blank_line_before_insert(lines: list[str], insert_at: int):
    """Ensure exactly one blank line before insert_at, returning the shifted
    index. Section text starts with "### " and the preceding trailing blank
    may already be gone (EOF collapsing), which would break MD022/MD032."""
    blank_count = 0
    i = insert_at - 1
    while i >= 0 and not lines[i].strip():
        blank_count += 1
        i -= 1
    if blank_count == 0:
        lines[insert_at:insert_at] = ["\n"]
        insert_at += 1
    elif blank_count > 1:
        del lines[insert_at - (blank_count - 1) : insert_at]
        insert_at -= blank_count - 1
    return insert_at


def insert_changes_section(text: str, section_text: str, friendly: str, ordering: OrderingContext):
    """Insert section_text into "## Changes" in values.yaml component order.
    Appended before the next "## " heading (or EOF) when the section has no
    blocks yet, after stripping both stub TODO placeholders (one event);
    appended at EOF when the section doesn't exist."""
    blocks = parse_upgrade_doc_changes_blocks(text)
    lines = text.splitlines(keepends=True)
    changes_idx, section_end = changes_section_bounds(lines)
    if changes_idx is None:
        if text and not text.endswith("\n\n"):
            text = text.rstrip("\n") + "\n\n"
        return text + section_text

    if not blocks:
        insert_at = _insert_index_for_empty_changes_section(lines, changes_idx, section_end)
    else:
        key_order = values_key_order(ordering.values)
        new_key = component_order_key(friendly, ordering.deps, key_order, ordering.canonical_names, ordering.values)
        existing_keys = [
            component_order_key(b["heading"], ordering.deps, key_order, ordering.canonical_names, ordering.values)
            for b in blocks
        ]
        idx = insertion_index(new_key, existing_keys)
        insert_at = blocks[idx]["start"] if idx < len(blocks) else section_end

    insert_at = _normalize_blank_line_before_insert(lines, insert_at)
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


def remove_changes_block(text: str, block: HeadingBlock | None) -> tuple[str, bool]:
    """Delete `block` and its trailing blank lines. Returns
    (new_text, removed); (text, False) if block is None."""
    if block is None:
        return text, False
    lines = text.splitlines(keepends=True)
    start, end = block["start"], block["end"]
    while end < len(lines) and not lines[end].strip():
        end += 1
    del lines[start:end]
    return "".join(lines), True


def remove_changes_section(text: str, friendly: str, ordering: OrderingContext) -> tuple[str, bool]:
    """Delete the component's "### ..." block, matched by identity the same
    way check_docs_consistency pairs headings with rows, so a sidecar's
    block is never taken for its parent's. Returns (new_text, removed)."""
    deps, canonical_names = ordering.deps, ordering.canonical_names
    ident = resolve_component_identity(friendly, deps, canonical_names)
    blocks = parse_upgrade_doc_changes_blocks(text)
    block = next(
        (b for b in blocks if ident and changes_heading_identities(b["heading"], deps, canonical_names) == {ident}),
        None,
    )
    return remove_changes_block(text, block)


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
    old_app = actual_app_version(baseline_state.values, key, chart_name) if baseline_state.values else None
    new_app = actual_app_version(target_state.values, key, chart_name, chart_dir=chart_dir, dep=dep)
    if old_app is None and baseline_state.values:
        # Baseline values lack the path (e.g. image block added this
        # release): fall back to past images-<version>.yaml manifests.
        for path in image_paths_for(chart_name, chart_dir):
            old_app = historical_app_version_for_path(
                chart_dir, target_state.deps, target_state.values, (key, *tuple(path.split("."))), upgrade_docs_baseline
            )
            if old_app is not None:
                break
    if old_app is None and baseline_state.values and dep is not None and chart_unchanged:
        # The vendored-.tgz appVersion fallback is keyed on dep["version"],
        # so it's normally unavailable for the baseline; with an unchanged
        # chart the same .tgz backs both sides (e.g. openbao's blank tag).
        old_app = actual_app_version(baseline_state.values, key, chart_name, chart_dir=chart_dir, dep=dep)
    app_unchanged = (
        old_app is not None and new_app is not None and normalize_version(old_app) == normalize_version(new_app)
    )
    return dep, chart_name, old_chart, new_chart, old_app, new_app, (chart_unchanged and app_unchanged)


def _matched_component_keys(text: str, target_deps: list[ChartDependency], chart_dir: Path) -> set[str]:
    """Component keys (dependency alias-or-name or native component) that
    already have a "Component versions" row in `text`."""
    matched_keys: set[str] = set()
    for row in parse_upgrade_doc_rows(text):
        # A sidecar row like "redis-operator - redis" must not count as
        # redis-operator's own row.
        dep = match_dependency_excluding_sidecar_names(row["name"], target_deps)
        if dep:
            matched_keys.add(values_key_of(dep))
            continue
        native_key = match_native_component(row["name"], native_components(chart_dir))
        if native_key:
            matched_keys.add(native_key)
    return matched_keys


def _new_component_section(key: str, chart_name: str, change: VersionChange, doc_context: DocContext):
    """Changes section for an auto-added row: make_changes_section when the
    app version resolved (version_paths_for wins over image_paths_for), else
    a TODO stub rather than guessed prose."""
    if change.new_app is not None:
        version_paths = version_paths_for(chart_name, doc_context.chart_dir)
        image_paths = [] if version_paths else image_paths_for(chart_name, doc_context.chart_dir)
        identity = ComponentIdentity(key, chart_name, key)
        return make_changes_section(identity, doc_context.target, change, image_paths, version_paths)
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

    text, _ = remove_changes_section(text, key, OrderingContext(target_state.deps, target_state.values))
    change = VersionChange(old_app, new_app, old_chart, new_chart)
    text = insert_changes_section(
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
    matched_keys = _matched_component_keys(text, target_state.deps, doc_context.chart_dir)
    added_names: list[str] = []
    for key in sorted(actual_changed_keys - matched_keys):
        text, added = _add_missing_row_for_key(text, key, target_state, baseline_state, doc_context)
        if added:
            added_names.append(key)
    return text, added_names
