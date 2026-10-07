"""fix-doc-consistency: repair "Component versions" table cells and Changes/values-deltas heading app versions."""

import re

from dataclasses import dataclass

from lib.component_docs.changes_section import remove_changes_section
from lib.component_docs.changes_section import remove_component_row
from lib.upgradedoc.app_version_and_image_paths import ImagePath
from lib.upgradedoc.images_manifest_ordering import header_name_segment
from lib.upgradedoc.resolve_component_row import ResolutionContext
from lib.upgradedoc.resolve_component_row import ResolvedRow
from lib.upgradedoc.resolve_component_row import changes_heading_has_app_version
from lib.upgradedoc.resolve_component_row import resolve_component_row
from lib.upgradedoc.resolve_component_row import resolved_row_unchanged
from lib.upgradedoc.sorting_and_ordering import HeadingBlock
from lib.upgradedoc.sorting_and_ordering import OrderingContext
from lib.upgradedoc.sorting_and_ordering import parse_upgrade_doc_changes_blocks
from lib.upgradedoc.sorting_and_ordering import parse_values_delta_sections
from lib.upgradedoc.string_and_parsing_basics import TableRow
from lib.upgradedoc.string_and_parsing_basics import changes_heading_identities
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows
from lib.upgradedoc.string_and_parsing_basics import set_row_cells
from lib.upgradedoc.version_cells_and_key_changes import canonical_version_cell
from lib.upgradedoc.version_cells_and_key_changes import component_version_cell


@dataclass
class HeadingFixInputs:
    """The caller-varying inputs of _fix_heading_app_versions ("###" vs "##" docs)."""

    resolved_by_values_key: dict[str, tuple[str, ResolvedRow]]
    canonical_names: dict[str, ImagePath]
    blocks: list[HeadingBlock]
    heading_marker: str


# Native components and sidecars have no chart: "-" is what the checker expects.
NO_CHART = "-"


def _new_dependency_row_update(lines: list[str], row: TableRow, resolved: ResolvedRow) -> tuple[str, str, str] | None:
    """Rewrite a baseline_resolved=False row to "<target> (new)" cells.

    The chart cell is "(new)" regardless; the app may predate the dependency
    (resolved["baseline_app"] from a past manifest). Returns (row_name,
    app_cell, chart_cell) if the row changed, else None."""
    target_chart, target_app = resolved["target_chart"], resolved["target_app"]
    cells = set_row_cells(
        lines,
        row,
        component_version_cell(resolved["baseline_app"], target_app) if target_app is not None else None,
        component_version_cell(None, target_chart) if target_chart is not None else NO_CHART,
    )
    return (row["name"], cells[1], cells[2]) if cells else None


def _existing_row_update(lines: list[str], row: TableRow, resolved: ResolvedRow) -> tuple[str, str, str] | None:
    """Rewrite a baseline_resolved=True row to source-to-target cells.

    The baseline app can be None even when the dependency existed (image
    pinned only this hop), rendering "(new)"; full cell text is compared so a
    stale "(new)"/"(unchanged)" gets fixed. Returns (row_name, app_cell,
    chart_cell) if the row changed, else None."""
    target_chart, target_app = resolved["target_chart"], resolved["target_app"]
    baseline_chart = resolved["baseline_chart"]
    if target_chart is None:
        chart_cell = NO_CHART
    elif baseline_chart is not None:
        chart_cell = canonical_version_cell(baseline_chart, target_chart)
    else:
        chart_cell = None
    cells = set_row_cells(
        lines,
        row,
        component_version_cell(resolved["baseline_app"], target_app) if target_app is not None else None,
        chart_cell,
    )
    return (row["name"], cells[1], cells[2]) if cells else None


def fix_component_version_table(
    text: str, resolution: ResolutionContext
) -> tuple[str, list[tuple[str, str, str]], list[str], list[str]]:
    """Rewrite each "Component versions" row's App/Helm-chart cells to the actual baseline and target versions.

    A row is rewritten only when source and target are verifiable, except a
    component absent at the baseline, which gets "<target> (new)" cells. A row
    whose current version can't be resolved is left as-is and reported.

    A canonical sidecar/shared-image row name (see canonical_sidecar_row_names)
    is corrected against its own resolved tag, not match_dependency, whose fuzzy
    match could hit an unrelated dependency sharing the leading word (e.g.
    "redis-operator - redis"). Its chart cell is "-". Returns (new_text,
    changed_rows, unmatched_names, unresolved_names)."""
    lines = text.splitlines(keepends=True)
    rows = parse_upgrade_doc_rows(text)
    changed_rows: list[tuple[str, str, str]] = []
    unmatched_names: list[str] = []
    unresolved_names: list[str] = []

    canonical_names = resolution.target_index.canonical_names

    for row in rows:
        # Same resolver as the checker, so fixer and checker can't drift apart.
        resolved = resolve_component_row(row["name"], canonical_names, resolution)
        if resolved["kind"] == "unmatched":
            # A "<key> - <image-basename>" row without a resolvable repository is
            # unresolved, never matched against a dependency sharing its first word.
            if " - " in row["name"]:
                unresolved_names.append(row["name"])
            else:
                unmatched_names.append(row["name"])
            continue

        if resolved["baseline_resolved"] is None:
            unresolved_names.append(row["name"])
            continue

        if resolved["baseline_resolved"] is False:
            # For a sidecar, False can also mean its current tag didn't
            # resolve (broken, not new); a missing target_app tells them apart.
            if resolved["dep"] is None and resolved["target_app"] is None:
                unresolved_names.append(row["name"])
                continue
            changed = _new_dependency_row_update(lines, row, resolved)
        else:
            changed = _existing_row_update(lines, row, resolved)

        if changed:
            changed_rows.append(changed)

    return "".join(lines), changed_rows, unmatched_names, unresolved_names


def _resolved_rows_by_values_key(
    upgrade_doc_text: str, resolution: ResolutionContext, canonical_names: dict[str, ImagePath]
) -> dict[str, tuple[str, ResolvedRow]]:
    """{values_key: (row_name, resolved)} for every resolvable row of the upgrade doc's table.

    Excludes "unmatched" rows and rows without target_app. The single source for
    both the upgrade doc's and the values-deltas doc's heading fixes (the latter
    has no table). "" (no upgrade doc yet) gives {}. Sidecar rows are keyed by
    their dotted values path."""
    resolved_by_values_key: dict[str, tuple[str, ResolvedRow]] = {}
    for row in parse_upgrade_doc_rows(upgrade_doc_text):
        resolved = resolve_component_row(row["name"], canonical_names, resolution)
        if resolved["kind"] != "unmatched" and resolved["target_app"] is not None:
            resolved_by_values_key[resolved["values_key"]] = (row["name"], resolved)
    return resolved_by_values_key


def _chart_clause(heading: str):
    """The heading's trailing " (chart ...)" clause verbatim, or ""."""
    match = re.search(r"\s*\(chart[^)]*\)", heading)
    return match.group(0) if match else ""


def _heading_resolved_row(
    heading: str, resolution: ResolutionContext, inputs: HeadingFixInputs, canonical_path_to_name: dict[ImagePath, str]
) -> tuple[str, ResolvedRow, str | None, str | None] | None:
    """(row_name, resolved, old_app, expected_bare_name) for heading, or None if it doesn't apply.

    None for an ambiguous or orphaned identity, or one without row data."""
    idents = changes_heading_identities(heading, resolution.target.deps, inputs.canonical_names)
    if len(idents) != 1:
        return None
    kind, values_key = next(iter(idents))
    if kind == "sidecar" and isinstance(values_key, tuple):
        lookup_key = ".".join(values_key)
        expected_bare_name = canonical_path_to_name.get(values_key)
    elif kind == "dep" and isinstance(values_key, str):
        lookup_key = values_key
        expected_bare_name = values_key
    else:
        return None
    if lookup_key not in inputs.resolved_by_values_key:
        return None
    row_name, resolved = inputs.resolved_by_values_key[lookup_key]

    if resolved["baseline_resolved"] is None:
        return None
    old_app = resolved["baseline_app"]
    return row_name, resolved, old_app, expected_bare_name


def _heading_replacement(
    block: HeadingBlock,
    resolution: ResolutionContext,
    inputs: HeadingFixInputs,
    canonical_path_to_name: dict[ImagePath, str],
) -> tuple[str, str] | None:
    """(new_heading_line, original_heading) when block's heading needs correcting, else None."""
    heading = block["heading"]
    # Headings without a version marker (e.g. "## zaakbrug") are free-form.
    if not changes_heading_has_app_version(heading):
        return None
    found = _heading_resolved_row(heading, resolution, inputs, canonical_path_to_name)
    if found is None:
        return None
    row_name, resolved, old_app, expected_bare_name = found

    expected_app_heading = component_version_cell(old_app, resolved["target_app"])
    if expected_app_heading is None:
        return None  # no app version on either side to write into the heading
    without_chart_clause = re.sub(r"\(chart[^)]*\)", "", heading)
    current_name = header_name_segment(heading)
    # Replace the name only if it is still the auto-written bare name; a
    # hand-customized heading name is an editorial choice and must be kept.
    corrected_name = row_name if current_name == expected_bare_name else current_name
    if expected_app_heading in without_chart_clause and corrected_name == current_name:
        return None
    return f"{inputs.heading_marker} {corrected_name} {expected_app_heading}{_chart_clause(heading)}", heading


def _fix_heading_app_versions(
    text: str, resolution: ResolutionContext, inputs: HeadingFixInputs
) -> tuple[str, list[str]]:
    """Rewrite stale heading names/app versions in inputs.blocks; shared by the "###" and "##" fixes.

    Both callers pass the same _resolved_rows_by_values_key map so the two docs
    can't disagree. A sidecar identity (a values path tuple) is looked up by its
    dotted form, and its bare name is its canonical_names key, not the path.
    Returns (new_text, updated_headings), the latter the original heading texts."""
    canonical_path_to_name = {path: name for name, path in inputs.canonical_names.items()}
    lines = text.splitlines(keepends=True)
    updated_headings: list[str] = []
    for block in inputs.blocks:
        replacement = _heading_replacement(block, resolution, inputs, canonical_path_to_name)
        if replacement is None:
            continue
        new_heading, original_heading = replacement
        suffix = "\n" if lines[block["start"]].endswith("\n") else ""
        lines[block["start"]] = f"{new_heading}{suffix}"
        updated_headings.append(original_heading)

    return "".join(lines), updated_headings


def fix_changes_heading_app_versions(text: str, resolution: ResolutionContext):
    """Rewrite "### ..." Changes headings' name and app version to match the table row.

    The "(chart ...)" clause and body are untouched. Old/new are re-resolved via
    resolve_component_row rather than parsed from the rendered row cell, because
    "<v> (new)" and "<v> (unchanged)" cells extract to the same pair.

    Only a heading naming exactly one identity whose row has a target app
    version is touched; ambiguous, orphaned, unverifiable or already-correct
    headings are left as-is. Returns (new_text, updated_headings), the latter
    the original heading texts."""
    canonical_names = resolution.target_index.canonical_names
    resolved_by_values_key = _resolved_rows_by_values_key(text, resolution, canonical_names)
    blocks = parse_upgrade_doc_changes_blocks(text)
    return _fix_heading_app_versions(
        text, resolution, HeadingFixInputs(resolved_by_values_key, canonical_names, blocks, "###")
    )


def fix_values_delta_heading_app_versions(
    upgrade_doc_text: str, values_deltas_text: str, resolution: ResolutionContext
):
    """fix_changes_heading_app_versions for the values-deltas doc's "## ..." headings.

    upgrade_doc_text (already corrected) supplies the row data, since the
    values-deltas doc has no table of its own."""
    canonical_names = resolution.target_index.canonical_names
    resolved_by_values_key = _resolved_rows_by_values_key(upgrade_doc_text, resolution, canonical_names)
    blocks = parse_values_delta_sections(values_deltas_text)
    return _fix_heading_app_versions(
        values_deltas_text, resolution, HeadingFixInputs(resolved_by_values_key, canonical_names, blocks, "##")
    )


def remove_unchanged_component_rows(text: str, resolution: ResolutionContext) -> tuple[str, list[str]]:
    """Delete every row whose app and chart versions equal the baseline's, with its Changes section.

    A row whose baseline can't be resolved stays. Returns (new_text, removed_names)."""
    canonical_names = resolution.target_index.canonical_names
    ordering = OrderingContext(resolution.target.deps, resolution.target.values, canonical_names)

    removed_names: list[str] = []
    for row in parse_upgrade_doc_rows(text):
        resolved = resolve_component_row(row["name"], canonical_names, resolution)
        if resolved["kind"] == "unmatched" or not resolved_row_unchanged(resolved):
            continue
        removed_names.append(row["name"])
    for name in removed_names:
        text, _row_removed = remove_component_row(text, name)
        text, _section_removed, _kept_user_text = remove_changes_section(text, name, ordering)
    return text, removed_names
