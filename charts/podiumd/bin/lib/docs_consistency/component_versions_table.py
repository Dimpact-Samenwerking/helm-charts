"""check_docs_consistency's checks of an upgrade guide's "Component versions" table and its Changes sections."""

from collections.abc import Sequence
from pathlib import Path

from lib.chart.chart_state import BaselineState
from lib.component_docs.changes_section import DocContext
from lib.component_docs.changes_section import edited_changes_lines
from lib.component_docs.changes_section import pointer_issues
from lib.component_docs.images_manifest_entries import expected_changes_items
from lib.component_docs.images_manifest_entries import stale_changes_items
from lib.docs_consistency.check_context import ComponentRowsResult
from lib.docs_consistency.check_context import DocScanState
from lib.docs_consistency.check_context import DocsCheckContext
from lib.docs_consistency.check_context import Findings
from lib.docs_consistency.check_context import RowContext
from lib.docs_consistency.check_context import RowLookup
from lib.docs_consistency.markdown_format import check_doc_title
from lib.image.docs import changes_sections_contradicting_rows
from lib.upgradedoc.baseline_intro import baseline_intro_mismatches
from lib.upgradedoc.consistency_checks import find_changes_duplicate_identities
from lib.upgradedoc.consistency_checks import find_changes_row_correspondence_gaps
from lib.upgradedoc.consistency_checks import find_wrong_or_duplicate_dependency_claims
from lib.upgradedoc.consistency_checks import rowed_component_keys
from lib.upgradedoc.consistency_checks import rowed_sidecar_paths
from lib.upgradedoc.doc_names import doc_name
from lib.upgradedoc.doc_names import images_manifest_path
from lib.upgradedoc.removed_items import removed_item_named
from lib.upgradedoc.resolve_component_row import ResolutionContext
from lib.upgradedoc.resolve_component_row import ResolvedRow
from lib.upgradedoc.resolve_component_row import changes_heading_has_app_version
from lib.upgradedoc.resolve_component_row import is_resolved_row_unchanged
from lib.upgradedoc.resolve_component_row import resolve_component_own_version_change
from lib.upgradedoc.resolve_component_row import resolve_component_row
from lib.upgradedoc.resolve_component_row import strip_chart_clause
from lib.upgradedoc.sorting_and_ordering import OrderingContext
from lib.upgradedoc.sorting_and_ordering import parse_upgrade_doc_changes_blocks
from lib.upgradedoc.string_and_parsing_basics import TableRow
from lib.upgradedoc.string_and_parsing_basics import VersionRow
from lib.upgradedoc.string_and_parsing_basics import changes_heading_identities
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows as _parse_upgrade_doc_rows
from lib.upgradedoc.version_cells import component_version_cell


def parse_upgrade_doc_rows(doc_path: Path) -> list[TableRow]:
    """parse_upgrade_doc_rows applied to the text of `doc_path`."""
    return _parse_upgrade_doc_rows(doc_path.read_text(encoding="utf-8"))


def doc_header_mismatches(doc_path: Path, ctx: DocsCheckContext) -> list[str]:
    """Title and intro checks on the selected upgrade doc (fix-doc-consistency clears stale TODO placeholders)."""
    baseline = ctx.doc_query.upgrade_docs_baseline
    if ctx.doc_query.is_bare_version and baseline:
        return check_doc_title(doc_path, baseline, ctx.doc_query.podiumd_version) + baseline_intro_mismatches(
            doc_path.name, doc_path.read_text(encoding="utf-8"), baseline
        )
    return []


def _record_row_identity(resolved: ResolvedRow, result: ComponentRowsResult):
    """Record one resolved row's bookkeeping on `result`; return (values_key, actual_app)."""
    values_key = resolved["values_key"]
    actual_app = resolved["target_app"]

    if resolved["kind"] != "sidecar" and actual_app:
        # Native components resolve to ("dep", values_key) too, so keys match
        # resolve_component_identity/changes_heading_identities.
        result.resolved_app_by_identity[("dep", values_key)] = actual_app

    return values_key, actual_app


def _check_row_target_versions(
    row: VersionRow, row_ctx: RowContext, resolved: ResolvedRow, values_key: str, result: ComponentRowsResult
):
    """One row's current chart/app-version cells vs. Chart.yaml/values.yaml."""
    actual_chart, actual_app = resolved["target_chart"], resolved["target_app"]
    if row["chart"] and normalize_version(row["chart"]) != normalize_version(actual_chart):
        result.mismatches.append(
            f'{values_key} ("{row["name"]}") target chart: Chart.yaml has "{actual_chart}", '
            f'{row_ctx.doc_path.name} says "{row["chart"]}"'
        )
    if actual_app and normalize_version(row["app"]) != normalize_version(actual_app):
        result.mismatches.append(
            f'{values_key} ("{row["name"]}") target app: values.yaml image tag is "{actual_app}", '
            f'{row_ctx.doc_path.name} says "{row["app"] or "-"}"'
        )


def check_row_baseline_versions(
    row: VersionRow, row_ctx: RowContext, resolved: ResolvedRow, values_key: str, result: ComponentRowsResult
):
    """One row's source chart/app-version cells vs. row_ctx.baseline_ref (which must be set)."""
    actual_app = resolved["target_app"]
    if resolved["baseline_resolved"] is False:
        # A warning, not a mismatch: usually a new component with no baseline version
        # (fix-doc-consistency writes "(new)" cells for it).
        print(
            f'WARNING: {row_ctx.doc_path.name}: doc row "{row["name"]}" source version could not '
            f"be verified against {row_ctx.baseline_ref} — the component didn't exist there yet, "
            f"or its version isn't resolvable there; source cells left unchecked"
        )
        if resolved["kind"] != "sidecar" and actual_app:
            # A past images manifest can still know the image (see _dependency_baseline_result).
            result.baseline_app_by_identity[("dep", values_key)] = resolved["baseline_app"]
        return

    baseline_chart_actual, baseline_app_actual = resolved["baseline_chart"], resolved["baseline_app"]
    if resolved["kind"] != "sidecar" and actual_app:
        result.baseline_app_by_identity[("dep", values_key)] = baseline_app_actual

    if (
        row["chart_source"]
        and baseline_chart_actual
        and normalize_version(row["chart_source"]) != normalize_version(baseline_chart_actual)
    ):
        result.mismatches.append(
            f'{values_key} ("{row["name"]}") source chart: {row_ctx.baseline_ref} has '
            f'"{baseline_chart_actual}", {row_ctx.doc_path.name} says "{row["chart_source"]}"'
        )
    if baseline_app_actual:
        expected_app_source, baseline_app_label = baseline_app_actual, f'"{baseline_app_actual}"'
    elif actual_app:
        # Dependency existed at baseline but its app version didn't: the fixer writes
        # "<target> (new)", so a stale "<old> → <target>" cell is flagged.
        expected_app_source = None
        baseline_app_label = "no app version (new)"
    else:
        return
    if normalize_version(row["app_source"]) != normalize_version(expected_app_source):
        result.mismatches.append(
            f'{values_key} ("{row["name"]}") source app: {row_ctx.baseline_ref} has '
            f'{baseline_app_label}, {row_ctx.doc_path.name} says "{row["app_source"] or "-"}"'
        )


def _check_component_rows(
    rows: Sequence[VersionRow], row_ctx: RowContext, row_lookup: RowLookup, resolution: ResolutionContext
):
    """Check every "Component versions" row's current and source cells, and flag unchanged rows.

    Rows resolve via resolve_component_row, shared with fix-doc-consistency so checker
    and fixer agree on what's correct.
    """
    result = ComponentRowsResult([], {}, {})

    for row in rows:
        if row["name"] in row_lookup.stale_names:
            continue

        resolved = resolve_component_row(row["name"], row_lookup.canonical_names, resolution)
        if resolved["kind"] == "unmatched":
            result.mismatches.append(
                f'{row_ctx.doc_path.name}: doc row "{row["name"]}" does not match a Chart.yaml '
                f'dependency or a canonical sidecar/shared-image name ("<component> - '
                f'<image-basename>" or "<image-basename>", the exact form fix-doc-consistency writes) '
                f"— wrong phrasing, or a stale row"
            )
            continue

        values_key, _actual_app = _record_row_identity(resolved, result)
        _check_row_target_versions(row, row_ctx, resolved, values_key, result)
        if row_ctx.baseline_ref:
            check_row_baseline_versions(row, row_ctx, resolved, values_key, result)
            if is_resolved_row_unchanged(resolved):
                result.mismatches.append(
                    f'{row_ctx.doc_path.name}: doc row "{row["name"]}" is unchanged vs {row_ctx.baseline_ref} '
                    f'(app and chart) — remove the row and its "### ..." Changes section'
                )

    return result


def _check_missing_component_rows(ctx: DocsCheckContext, scan: DocScanState, resolution: ResolutionContext):
    """Flag components changed vs baseline that have no row at all.

    Covers own primary rows (resolve_component_own_version_change, shared with
    add_missing_component_rows) and sidecar images under an already-rowed dependency
    (e.g. redis-ha under redis-operator), resolved like their rows
    (resolve_component_row, shared with add_missing_sidecar_rows' baseline). Only
    called when ctx.baseline_ref is set.
    """
    mismatches: list[str] = []
    # fix-doc-consistency writes a removed component's row (sync_removed_items).
    rowed_keys = rowed_component_keys(scan.rows, ctx.current.deps, scan.canonical_names)
    for key in sorted(ctx.actual_changed_keys - rowed_keys - set(scan.removed)):
        resolved = resolve_component_own_version_change(
            key,
            ctx.current,
            ctx.baseline,
            ctx.chart_dir,
            ctx.doc_query.upgrade_docs_baseline,
        )
        if resolved is not None and resolved[-1]:
            continue
        mismatches.append(
            f'{scan.doc_path.name}: component "{key}" changed vs {ctx.baseline_ref} but has no row '
            f'in the "Component versions" table'
        )

    rowed_paths = rowed_sidecar_paths(scan.rows, ctx.current.deps, scan.canonical_names)
    for name, path in sorted(scan.canonical_names.items()):
        if path in rowed_paths:
            continue
        # A digest-only re-pin needs no row.
        resolved = resolve_component_row(name, scan.canonical_names, resolution)
        if resolved["kind"] != "unmatched" and not is_resolved_row_unchanged(resolved):
            mismatches.append(
                f'{scan.doc_path.name}: sidecar/shared image "{name}" changed vs {ctx.baseline_ref} '
                f'but has no row in the "Component versions" table'
            )
    return mismatches


def _duplicate_identity_mismatches(ctx: DocsCheckContext, scan: DocScanState, changes_headings: list[str]):
    """One mismatch per find_changes_duplicate_identities group."""
    duplicate_rows, duplicate_headings = find_changes_duplicate_identities(
        scan.rows, changes_headings, ctx.current.deps, scan.canonical_names
    )
    mismatches: list[str] = []
    for group in duplicate_rows:
        quoted = ", ".join(f'"{name}"' for name in group)
        mismatches.append(
            f"{scan.doc_path.name}: table rows {quoted} all name the same component — "
            f"keep exactly one row per component"
        )
    for group in duplicate_headings:
        quoted = ", ".join(f'"### {heading}"' for heading in group)
        mismatches.append(
            f'{scan.doc_path.name}: "## Changes" sections {quoted} all name the same component — '
            f"keep exactly one section per component"
        )
    return mismatches


def _check_changes_heading_correspondence(
    ctx: DocsCheckContext,
    scan: DocScanState,
    rows_result: ComponentRowsResult,
    changes_headings: list[str],
    doc_text: str,
) -> list[str]:
    """Check "## Changes" headings against the table rows; skipped when the doc has none.

    Every row needs a matching "### ..." section and vice versa, and no component may
    appear twice. A heading for one "dep" component with a resolved app version must
    show it, with the transition wording from component_version_cell (shared with the
    row cell), e.g. "openbao v2.5.5 (unchanged)" that should be "(new)".
    fix-doc-consistency rewrites only the generated parts of a section; text a
    user added is never changed.
    """
    has_changes_section = any(line.strip() == "## Changes" for line in doc_text.splitlines())
    if not has_changes_section:
        return []

    mismatches: list[str] = []
    # fix-doc-consistency writes a removed item's row and section (sync_removed_items).
    rows_without_heading, headings_without_row = find_changes_row_correspondence_gaps(
        scan.rows, changes_headings, ctx.current.deps, scan.canonical_names, scan.removed
    )
    mismatches.extend(
        f'{scan.doc_path.name}: table row "{name}" has no matching "### ..." section under "## Changes"'
        for name in rows_without_heading
    )
    mismatches.extend(
        f'{scan.doc_path.name}: "## Changes" section "### {heading}" has no matching row in the '
        f'"Component versions" table'
        for heading in headings_without_row
    )
    mismatches.extend(_duplicate_identity_mismatches(ctx, scan, changes_headings))

    for heading in changes_headings:
        idents = changes_heading_identities(heading, ctx.current.deps, scan.canonical_names)
        if len(idents) != 1:
            continue
        identity = next(iter(idents))
        actual_app = rows_result.resolved_app_by_identity.get(identity)
        if actual_app and not changes_heading_has_app_version(heading):
            mismatches.append(
                f'{scan.doc_path.name}: "## Changes" section "### {heading}" is missing the '
                f'primary-image app version in its own heading — values.yaml shows "{actual_app}"'
            )
            continue

        if ctx.baseline_ref and identity in rows_result.baseline_app_by_identity:
            expected_app_heading = component_version_cell(rows_result.baseline_app_by_identity[identity], actual_app)
            without_chart_clause = strip_chart_clause(heading)
            if expected_app_heading is not None and expected_app_heading not in without_chart_clause:
                mismatches.append(
                    f'{scan.doc_path.name}: "## Changes" section "### {heading}" shows the wrong '
                    f'app-version transition in its own heading — expected "{expected_app_heading}" '
                    f"(values.yaml/{ctx.baseline_ref} show {rows_result.baseline_app_by_identity[identity]!r} -> "
                    f"{actual_app!r})"
                )
    return mismatches


def _select_upgrade_doc(ctx: DocsCheckContext, findings: Findings):
    """Select the upgrade doc to check and add its title/placeholder findings and "checked" entry.

    Warns (never fails) on zero or multiple matches; None when there is no doc.
    """
    baseline = ctx.doc_query.upgrade_docs_baseline
    doc_glob = doc_name(
        baseline if ctx.doc_query.is_bare_version and baseline else "*", ctx.doc_query.podiumd_version, "upgrade"
    )
    doc_matches = sorted(ctx.doc_query.doc_dir.glob(doc_glob))
    if not doc_matches:
        print(f"WARNING: no upgrade doc matches {doc_glob} — skipping doc check")
        return None
    if len(doc_matches) > 1:
        print(
            f"WARNING: multiple upgrade docs match {doc_glob}: "
            f"{', '.join(doc_match.name for doc_match in doc_matches)} — using {doc_matches[-1].name}"
        )
    doc_path = doc_matches[-1]
    findings.checked.append(doc_path.name)
    findings.mismatches.extend(doc_header_mismatches(doc_path, ctx))
    if ctx.baseline_ref:
        findings.checked.append(f"upgrade_docs_baseline {ctx.baseline_ref}")
    return doc_path


def _stale_changes_item_mismatches(
    ctx: DocsCheckContext, scan: DocScanState, resolution: ResolutionContext
) -> list[str]:
    """An images-manifest "# Changes:" item contradicts its upgrade-doc table row."""
    images_path = images_manifest_path(ctx.doc_query.doc_dir.parent / "images", ctx.doc_query.podiumd_version)
    if not ctx.doc_query.owns_images_manifest or not images_path.is_file():
        return []
    text = images_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    expected = expected_changes_items([row["name"] for row in scan.rows], text, scan.canonical_names, resolution)
    return [
        f"{images_path.name}: '# Changes:' item \"{current}\" contradicts the {scan.doc_path.name} table row "
        f'(expected "{wanted}"); run fix-doc-consistency to correct it'
        for _idx, current, wanted in stale_changes_items(lines, expected)
    ]


def _contradicting_section_mismatches(ctx: DocsCheckContext, scan: DocScanState, doc_text: str) -> list[str]:
    """A "### ..." Changes section's chart part or intro contradicts its table row."""
    sections = changes_sections_contradicting_rows(
        doc_text,
        DocContext(ctx.chart_dir, ctx.doc_query.podiumd_version),
        OrderingContext(ctx.current.deps, ctx.current.values, scan.canonical_names),
    )
    return [
        f"{scan.doc_path.name}: '### {section.heading}' contradicts its table row "
        f"(expected '### {section.expected_heading}'); {_repair_advice(repairable=section.repairable)}"
        for section in sections
    ]


def _repair_advice(*, repairable: bool) -> str:
    return "run fix-doc-consistency to rebuild it" if repairable else "fix it by hand"


def _pointer_mismatches(doc_path: Path, doc_text: str) -> list[str]:
    """A Changes section with more than one pointer; fix-doc-consistency adds a missing one, not removes one."""
    return [
        f"{doc_path.name}: '### {issue.heading}' has {issue.count} \"- Image / digest\" pointers; keep one"
        for issue in pointer_issues(doc_text)
        if issue.kind == "duplicate"
    ]


def _warn_edited_generated_lines(doc_path: Path, heading_marker: str, edited: list[tuple[str, str]]):
    """A warning, not a mismatch: the doc is still correct, but the edited line can go stale."""
    for heading, line in edited:
        print(
            f"WARNING: {doc_path.name}: '{heading_marker} {heading}' has a hand-edited generated line, "
            f'which fix-doc-consistency no longer updates: "{line}"; '
            f"restore the generated line and put the remark on a line of its own"
        )


def check_component_versions_table(ctx: DocsCheckContext, findings: Findings):
    """The "Component versions" section: per-row, missing-row and Changes-heading checks.

    Appends onto `findings`; does nothing when no doc matches.
    """
    doc_path = _select_upgrade_doc(ctx, findings)
    if doc_path is None:
        return

    resolution = ResolutionContext(
        ctx.chart_dir,
        ctx.current,
        ctx.baseline if ctx.baseline_ref else BaselineState(None, ctx.baseline.values),
        ctx.doc_query.upgrade_docs_baseline if ctx.baseline_ref else None,
    )
    scan = DocScanState(
        doc_path,
        list(parse_upgrade_doc_rows(doc_path)),
        ctx.images.current.canonical_names,
        ctx.removed_items_by_name,
    )

    # Matched like sync_removed_items matches them, so a hand-written "KISS" row is kiss's.
    removed_row_names = {row["name"] for row in scan.rows if removed_item_named(row["name"], scan.removed)}
    # Duplicate row names, and free-form rows fuzzy-matching a dependency another row claims.
    duplicate_names, wrong_fuzzy_names = find_wrong_or_duplicate_dependency_claims(
        [row["name"] for row in scan.rows if row["name"] not in removed_row_names], ctx.current.deps
    )
    findings.mismatches.extend(
        f'{doc_path.name}: doc row "{name}" is wrong or stale — not found in Chart.yaml or values.yaml'
        for name in sorted(duplicate_names | wrong_fuzzy_names)
    )

    # fix-doc-consistency writes removed items' rows (sync_removed_items).
    row_lookup = RowLookup(scan.canonical_names, duplicate_names | wrong_fuzzy_names | removed_row_names)
    rows_result = _check_component_rows(scan.rows, RowContext(doc_path, ctx.baseline_ref), row_lookup, resolution)
    findings.mismatches.extend(rows_result.mismatches)

    if ctx.baseline_ref:
        findings.mismatches.extend(_check_missing_component_rows(ctx, scan, resolution))

    doc_text = doc_path.read_text(encoding="utf-8")
    changes_headings = [block["heading"] for block in parse_upgrade_doc_changes_blocks(doc_text)]
    findings.mismatches.extend(
        _check_changes_heading_correspondence(ctx, scan, rows_result, changes_headings, doc_text)
    )
    findings.mismatches.extend(_stale_changes_item_mismatches(ctx, scan, resolution))
    findings.mismatches.extend(_contradicting_section_mismatches(ctx, scan, doc_text))
    findings.mismatches.extend(_pointer_mismatches(doc_path, doc_text))
    _warn_edited_generated_lines(doc_path, "###", edited_changes_lines(doc_text))
