"""Check Chart.yaml/values.yaml component versions against the release's upgrade docs.

Covers docs/_UPGRADE_PATHS/*-to-<version>-upgrade.md and docs/images/images-<version>.yaml;
given upgrade_docs_baseline, every component changed since it must appear in the right
doc. Uses only upgrade_docs_baseline, never release_table_baseline.
"""

import re

from collections.abc import Sequence
from pathlib import Path

from lib.chart.chart_state import BaselineState
from lib.chart.chart_state import ComponentState
from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.release_baseline_basics import chart_version
from lib.chart.values_tree_primitives import image_version_changed
from lib.component_docs.changes_section import DocContext
from lib.component_docs.changes_section import edited_changes_lines
from lib.component_docs.changes_section import pointer_issues
from lib.component_docs.changes_section import resolve_component_own_version_change
from lib.component_docs.images_manifest_changes_header import find_images_manifest_changes_header
from lib.component_docs.images_manifest_entries import expected_changes_items
from lib.component_docs.images_manifest_entries import stale_changes_items
from lib.component_docs.values_delta_sections import edited_values_delta_lines
from lib.component_docs.values_delta_sections import has_stale_gemeente_specific_placeholder
from lib.docs_consistency.check_context import ComponentRowsResult
from lib.docs_consistency.check_context import DocQuery
from lib.docs_consistency.check_context import DocScanState
from lib.docs_consistency.check_context import DocsCheckContext
from lib.docs_consistency.check_context import Findings
from lib.docs_consistency.check_context import ManifestEntryScan
from lib.docs_consistency.check_context import RowContext
from lib.docs_consistency.check_context import RowLookup
from lib.docs_consistency.check_context import StateImages
from lib.docs_consistency.dry_run import MAX_DIFF_LINES
from lib.docs_consistency.dry_run import DocChange
from lib.docs_consistency.dry_run import fix_docs_dry_run
from lib.docs_consistency.images_manifest_format import ManifestCheckContext
from lib.docs_consistency.images_manifest_format import check_images_manifest_format
from lib.docs_consistency.markdown_format import check_baseline_doc_set
from lib.docs_consistency.markdown_format import check_companion_doc
from lib.docs_consistency.markdown_format import check_doc_title
from lib.docs_consistency.pointer_consistency import check_pointer_consistency
from lib.docs_consistency.values_diff import ValuesDeltaInputs
from lib.docs_consistency.values_diff import check_values_deltas_content
from lib.image.docs import changes_sections_contradicting_rows
from lib.image.manifest_entry_pins import entry_pin
from lib.images_manifest import ManifestEntry
from lib.images_manifest import parse_images_manifest
from lib.release_baseline import resolve_baseline_chart_state
from lib.settings import DigestPinningException
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.app_version_and_image_paths import ImagePath
from lib.upgradedoc.baseline_intro import baseline_intro_mismatches
from lib.upgradedoc.chart_image_index import ChartImageIndex
from lib.upgradedoc.consistency_checks import find_changes_duplicate_identities
from lib.upgradedoc.consistency_checks import find_changes_row_correspondence_gaps
from lib.upgradedoc.consistency_checks import find_wrong_or_duplicate_dependency_claims
from lib.upgradedoc.consistency_checks import rowed_component_keys
from lib.upgradedoc.consistency_checks import rowed_sidecar_paths
from lib.upgradedoc.doc_names import STANDARD_SUFFIXES
from lib.upgradedoc.doc_names import doc_name
from lib.upgradedoc.doc_names import images_manifest_path
from lib.upgradedoc.images_manifest_list_diff import compute_changed_components
from lib.upgradedoc.removed_items import RemovedItem
from lib.upgradedoc.removed_items import removed_item_named
from lib.upgradedoc.removed_items import removed_items
from lib.upgradedoc.resolve_component_row import ResolutionContext
from lib.upgradedoc.resolve_component_row import ResolvedRow
from lib.upgradedoc.resolve_component_row import changes_heading_has_app_version
from lib.upgradedoc.resolve_component_row import resolve_component_row
from lib.upgradedoc.resolve_component_row import resolved_row_unchanged
from lib.upgradedoc.sorting_and_ordering import OrderingContext
from lib.upgradedoc.sorting_and_ordering import parse_upgrade_doc_changes_blocks
from lib.upgradedoc.string_and_parsing_basics import TableRow
from lib.upgradedoc.string_and_parsing_basics import VersionRow
from lib.upgradedoc.string_and_parsing_basics import changes_heading_identities
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows as _parse_upgrade_doc_rows
from lib.upgradedoc.version_cells_and_key_changes import component_version_cell
from lib.version_numbers import is_bare_version
from lib.yaml_types import YamlMapping
from lib.yaml_types import load_yaml_mapping


def parse_upgrade_doc_rows(doc_path: Path) -> list[TableRow]:
    """parse_upgrade_doc_rows applied to the text of `doc_path`."""
    return _parse_upgrade_doc_rows(doc_path.read_text(encoding="utf-8"))


def _pointer_consistency_mismatches(doc_dir: Path, upgrade_docs_baseline: str, podiumd_version: str):
    """Stale sibling-doc/images-manifest reference findings for the caller's `mismatches`.

    Returned rather than returning early, so one stale link doesn't hide every other finding.
    """
    images_dir = doc_dir.parent / "images"
    pointer_docs = [doc_dir / doc_name(upgrade_docs_baseline, podiumd_version, suffix) for suffix in STANDARD_SUFFIXES]
    images_path_for_pointers = images_manifest_path(images_dir, podiumd_version)
    if images_path_for_pointers.is_file():
        pointer_docs.append(images_path_for_pointers)
    return [
        issue for doc in pointer_docs for issue in check_pointer_consistency(doc, podiumd_version, doc_dir, images_dir)
    ]


def _check_companion_docs(doc_dir: Path, upgrade_docs_baseline: str, podiumd_version: str, findings: Findings):
    """Append gemeente-specific/values-deltas companion-doc findings to `findings`.

    Only the gemeente-specific placeholder, which nothing auto-fixes, is
    checked; fix-doc-consistency clears the values-deltas one.
    """
    if not is_bare_version(upgrade_docs_baseline):
        print(
            f'WARNING: upgrade_docs_baseline "{upgrade_docs_baseline}" is not a bare version — cannot check '
            f"for matching gemeente-specific / values-deltas docs"
        )
        return

    for suffix in ("gemeente-specific", "values-deltas"):
        companion_name, doc_mismatches = check_companion_doc(doc_dir, upgrade_docs_baseline, podiumd_version, suffix)
        findings.checked.append(companion_name)
        findings.mismatches.extend(doc_mismatches)

        companion_path = doc_dir / companion_name
        if companion_path.is_file():
            companion_text = companion_path.read_text(encoding="utf-8")
            if suffix == "gemeente-specific" and has_stale_gemeente_specific_placeholder(companion_text):
                findings.mismatches.append(
                    f'{companion_name}: still has its own stale "_None recorded yet._" placeholder '
                    f'stranded alongside a real "## <gemeente> (<env>)" section — clear it by hand '
                    f"(nothing auto-fixes this one)"
                )


def _resolve_baseline(
    chart_dir: Path, upgrade_docs_baseline: str | None
) -> tuple[str | None, list[ChartDependency], YamlMapping, str | None]:
    """resolve_baseline_chart_state plus the mismatch a baseline_error produces.

    Returns (None, [], {}, None) when no upgrade_docs_baseline was given.
    """
    if not upgrade_docs_baseline:
        return None, [], {}, None
    baseline_ref, baseline_deps, baseline_values, _baseline_lines, baseline_error = resolve_baseline_chart_state(
        chart_dir, upgrade_docs_baseline
    )
    mismatch = f'upgrade_docs_baseline "{upgrade_docs_baseline}": {baseline_error}' if baseline_error else None
    return baseline_ref, baseline_deps, baseline_values, mismatch


def _build_docs_check_context(chart_dir: Path, doc_dir: Path, podiumd_version: str, upgrade_docs_baseline: str | None):
    """Load the chart, resolve the baseline and derived image maps into a DocsCheckContext.

    Returns (ctx, baseline_mismatch); the caller adds baseline_mismatch to `findings`.
    """
    deps = load_chart_dependencies(chart_dir / "Chart.yaml")
    values = load_yaml_mapping(chart_dir / "values.yaml")
    baseline_ref, baseline_deps, baseline_values, baseline_mismatch = _resolve_baseline(
        chart_dir, upgrade_docs_baseline
    )
    # Ground truth, independent of the docs, so a changed component missing from every doc is caught.
    actual_changed_keys: set[str] = (
        compute_changed_components(deps, baseline_deps, values, baseline_values) if baseline_ref else set()
    )
    ctx = DocsCheckContext(
        chart_dir=chart_dir,
        current=ComponentState(deps, values),
        baseline=BaselineState(baseline_deps, baseline_values),
        baseline_ref=baseline_ref,
        doc_query=DocQuery(
            doc_dir,
            podiumd_version,
            upgrade_docs_baseline,
            is_bare_version(upgrade_docs_baseline),
        ),
        images=StateImages(
            ChartImageIndex(chart_dir, deps, values),
            ChartImageIndex(chart_dir, baseline_deps or [], baseline_values if baseline_ref else None),
        ),
        actual_changed_keys=actual_changed_keys,
    )
    return ctx, baseline_mismatch


def _doc_header_mismatches(doc_path: Path, ctx: DocsCheckContext) -> list[str]:
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


def _check_row_baseline_versions(
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
            _check_row_baseline_versions(row, row_ctx, resolved, values_key, result)
            if resolved_row_unchanged(resolved):
                result.mismatches.append(
                    f'{row_ctx.doc_path.name}: doc row "{row["name"]}" is unchanged vs {row_ctx.baseline_ref} '
                    f'(app and chart) — remove the row and its "### ..." Changes section'
                )

    return result


def _check_missing_component_rows(ctx: DocsCheckContext, scan: DocScanState):
    """Flag components changed vs baseline that have no row at all.

    Covers own primary rows (resolve_component_own_version_change, shared with
    add_missing_component_rows) and sidecar images under an already-rowed dependency
    (e.g. redis-ha under redis-operator). Only called when ctx.baseline_ref is set.
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
        if image_version_changed(ctx.images.baseline.paths.get(path), ctx.images.current.paths.get(path)):
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
        scan.rows,
        [heading for heading in changes_headings if removed_item_named(heading, scan.removed) is None],
        ctx.current.deps,
        scan.canonical_names,
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
            without_chart_clause = re.sub(r"\(chart[^)]*\)", "", heading)
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
            f"{', '.join(p.name for p in doc_matches)} — using {doc_matches[-1].name}"
        )
    doc_path = doc_matches[-1]
    findings.checked.append(doc_path.name)
    findings.mismatches.extend(_doc_header_mismatches(doc_path, ctx))
    if ctx.baseline_ref:
        findings.checked.append(f"upgrade_docs_baseline {ctx.baseline_ref}")
    return doc_path


def _stale_changes_item_mismatches(
    ctx: DocsCheckContext, scan: DocScanState, resolution: ResolutionContext
) -> list[str]:
    """An images-manifest "# Changes:" item contradicts its upgrade-doc table row."""
    images_path = images_manifest_path(ctx.doc_query.doc_dir.parent / "images", ctx.doc_query.podiumd_version)
    if not images_path.is_file():
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
    return [
        f"{scan.doc_path.name}: '### {s.heading}' contradicts its table row (expected '### {s.expected_heading}'); "
        + ("run fix-doc-consistency to rebuild it" if s.repairable else "fix it by hand")
        for s in changes_sections_contradicting_rows(
            doc_text,
            DocContext(ctx.chart_dir, ctx.doc_query.podiumd_version),
            OrderingContext(ctx.current.deps, ctx.current.values, scan.canonical_names),
        )
    ]


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


def _removed_items_by_name(ctx: DocsCheckContext) -> dict[str, RemovedItem]:
    """The components and images removed vs the baseline; none without a baseline_ref."""
    if not ctx.baseline_ref:
        return {}
    return {item.name: item for item in removed_items(ctx.images.current, ctx.images.baseline)}


def _check_component_versions_table(ctx: DocsCheckContext, findings: Findings):
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
        _removed_items_by_name(ctx),
    )

    # Duplicate row names, and free-form rows fuzzy-matching a dependency another row claims.
    duplicate_names, wrong_fuzzy_names = find_wrong_or_duplicate_dependency_claims(
        [row["name"] for row in scan.rows if row["name"] not in scan.removed], ctx.current.deps
    )
    findings.mismatches.extend(
        f'{doc_path.name}: doc row "{name}" is wrong or stale — not found in Chart.yaml or values.yaml'
        for name in sorted(duplicate_names | wrong_fuzzy_names)
    )

    # fix-doc-consistency writes removed items' rows (sync_removed_items).
    row_lookup = RowLookup(scan.canonical_names, duplicate_names | wrong_fuzzy_names | set(scan.removed))
    rows_result = _check_component_rows(scan.rows, RowContext(doc_path, ctx.baseline_ref), row_lookup, resolution)
    findings.mismatches.extend(rows_result.mismatches)

    if ctx.baseline_ref:
        findings.mismatches.extend(_check_missing_component_rows(ctx, scan))

    doc_text = doc_path.read_text(encoding="utf-8")
    changes_headings = [b["heading"] for b in parse_upgrade_doc_changes_blocks(doc_text)]
    findings.mismatches.extend(
        _check_changes_heading_correspondence(ctx, scan, rows_result, changes_headings, doc_text)
    )
    findings.mismatches.extend(_stale_changes_item_mismatches(ctx, scan, resolution))
    findings.mismatches.extend(_contradicting_section_mismatches(ctx, scan, doc_text))
    findings.mismatches.extend(_pointer_mismatches(doc_path, doc_text))
    _warn_edited_generated_lines(doc_path, "###", edited_changes_lines(doc_text))


def _check_images_manifest_entry(
    ctx: DocsCheckContext, scan: ManifestEntryScan, entry: ManifestEntry, findings: Findings
):
    """One images-manifest entry's version/digest/already-in-baseline checks."""
    name = entry.get("name")
    if not name:
        return
    path, actual_tag = entry_pin(
        entry, ctx.current.values, ctx.images.current.paths, scan.repo_map, scan.sibling_fields
    )
    if not path:
        print(f'  ({scan.images_path.name}: entry "{name}" — no matching image in values.yaml, skipped)')
        return

    version, digest = entry.get("version"), entry.get("digest")
    if not version or not digest:
        findings.mismatches.append(f'{name}: entry in {scan.images_path.name} is missing "version" or "digest"')
        return
    expected_tag = f"{version}@{digest}"
    if actual_tag != expected_tag:
        findings.mismatches.append(
            f'{name}: values.yaml tag is "{actual_tag}", {scan.images_path.name} says "{expected_tag}"'
        )

    if ctx.baseline_ref and ctx.images.baseline.paths.get(path) == expected_tag:
        findings.mismatches.append(
            f"{name}: listed in {scan.images_path.name} as new/changed, but {ctx.baseline_ref} "
            f'already has this exact tag ("{expected_tag}") — did it actually change?'
        )


def _check_images_manifest(
    ctx: DocsCheckContext,
    sibling_fields: dict[ImagePath, DigestPinningException],
    findings: Findings,
):
    """The images-manifest section: format, "# Changes:" header presence, and per-entry checks.

    Appends onto `findings`. Entry checks are skipped when the format isn't
    interpretable, but earlier findings are kept (no early return on findings).
    """
    images_path = images_manifest_path(ctx.doc_query.doc_dir.parent / "images", ctx.doc_query.podiumd_version)

    images_format_ok = True
    if ctx.doc_query.is_bare_version:
        manifest_check_context = ManifestCheckContext(
            ctx.doc_query.upgrade_docs_baseline,
            ctx.doc_query.podiumd_version,
            ctx.current.deps,
            ctx.current.values,
            ctx.baseline.values if ctx.baseline_ref else {},
            chart_dir=ctx.chart_dir,
        )
        format_issues = check_images_manifest_format(images_path, manifest_check_context)
        if format_issues:
            images_format_ok = False
            findings.checked.append(images_path.name)
            findings.mismatches.extend(format_issues)

    if not images_path.is_file():
        print(f"WARNING: no images manifest at {images_path.name} — skipping images-manifest check")
        return
    if not images_format_ok:
        return  # format issues recorded above; entries aren't interpretable until fixed

    findings.checked.append(images_path.name)
    entries_list = parse_images_manifest(images_path.read_text(encoding="utf-8"), str(images_path))

    if entries_list:
        manifest_lines = images_path.read_text(encoding="utf-8").splitlines(keepends=True)
        header_idx, _has_count = find_images_manifest_changes_header(manifest_lines)
        if header_idx is None:
            noun = "entry" if len(entries_list) == 1 else "entries"
            findings.mismatches.append(
                f'{images_path.name}: has {len(entries_list)} {noun} but no "# Changes:" header '
                f"at all — every real change is undocumented in the summary list"
            )

    scan = ManifestEntryScan(images_path, ctx.images.current.repo_map, sibling_fields)
    for entry in entries_list:
        _check_images_manifest_entry(ctx, scan, entry, findings)


def _check_values_deltas(ctx: DocsCheckContext, upgrade_docs_baseline: str, findings: Findings):
    """The values-deltas doc's content checks (see caller's guard); fix-doc-consistency orders its sections."""
    values_deltas_path = ctx.doc_query.doc_dir / doc_name(
        upgrade_docs_baseline, ctx.doc_query.podiumd_version, "values-deltas"
    )
    findings.mismatches.extend(
        check_values_deltas_content(
            values_deltas_path,
            # Removed components are listed in the upgrade doc only.
            ctx.actual_changed_keys - set(_removed_items_by_name(ctx)),
            ValuesDeltaInputs(
                ctx.baseline.values, ctx.current.values, ctx.current.deps, ctx.images.current.canonical_names
            ),
        )
    )

    deltas_text = values_deltas_path.read_text(encoding="utf-8")
    _warn_edited_generated_lines(values_deltas_path, "##", edited_values_delta_lines(deltas_text))


def _check_baseline_doc_set_and_pointers(
    doc_dir: Path, upgrade_docs_baseline: str | None, podiumd_version: str, findings: Findings
):
    """Baseline doc-set precheck and pointer-consistency checks for a bare-version baseline.

    Returns an early-return result the caller must propagate when the doc set is
    malformed; otherwise None (pointer findings go into `findings`).
    """
    if not is_bare_version(upgrade_docs_baseline):
        return None
    precheck_issues = check_baseline_doc_set(doc_dir, upgrade_docs_baseline, podiumd_version)
    if precheck_issues:
        print(
            f"FOUND {len(precheck_issues)} issue(s) with the upgrade_docs_baseline doc set "
            f"(checked before any other check on these documents):"
        )
        for issue in sorted(precheck_issues):
            print(" ", issue)
        return False, f"{len(precheck_issues)} upgrade_docs_baseline doc issue(s)"
    findings.mismatches.extend(_pointer_consistency_mismatches(doc_dir, upgrade_docs_baseline, podiumd_version))
    return None


def _check_docs(chart_dir: Path, doc_dir: Path, upgrade_docs_baseline: str | None) -> Findings | tuple[bool, str]:
    """Every finding about the docs in doc_dir; an early (ok, detail) result when the doc set itself is malformed."""
    podiumd_version = chart_version(chart_dir / "Chart.yaml")
    sibling_fields = digest_pinning_exceptions(chart_dir)
    findings = Findings([], [])

    precheck_result = _check_baseline_doc_set_and_pointers(doc_dir, upgrade_docs_baseline, podiumd_version, findings)
    if precheck_result is not None:
        return precheck_result

    if upgrade_docs_baseline:
        _check_companion_docs(doc_dir, upgrade_docs_baseline, podiumd_version, findings)

    ctx, baseline_mismatch = _build_docs_check_context(chart_dir, doc_dir, podiumd_version, upgrade_docs_baseline)
    if baseline_mismatch:
        findings.mismatches.append(baseline_mismatch)

    _check_component_versions_table(ctx, findings)
    _check_images_manifest(ctx, sibling_fields, findings)

    if ctx.baseline_ref and is_bare_version(upgrade_docs_baseline) and ctx.actual_changed_keys:
        _check_values_deltas(ctx, upgrade_docs_baseline, findings)
    return findings


def _print_doc_changes(changes: list[DocChange]) -> None:
    print("fix-doc-consistency would change:")
    for change in changes:
        print(f"  {change.name} ({change.status}, {change.changed_lines} line(s)):")
        for line in change.diff[:MAX_DIFF_LINES]:
            print(f"    {line}")
        if len(change.diff) > MAX_DIFF_LINES:
            print(f"    ... {len(change.diff) - MAX_DIFF_LINES} more diff line(s)")
    print("  run fix-doc-consistency")


def check_docs_consistency(chart_dir: Path, upgrade_docs_baseline: str | None = None):
    """Check the upgrade doc set and images manifest against Chart.yaml, values.yaml and the baseline.

    With a bare MAJOR.MINOR.PATCH `upgrade_docs_baseline`, fix-doc-consistency
    first runs on a copy of the docs: what it would change is one list, and
    every other check runs on the copy, so the second list holds only what
    must be fixed by hand. Without one, the checks run on the docs as they are
    and nothing is compared with a baseline.

    The order, missing pin-bullet and pointer checks are then skipped
    with a WARNING rather than re-implemented here: they exist only as
    fix-doc-consistency's writer logic, which refuses such a baseline, and a
    checker-side copy would drift from it. Nothing passes unnoticed, because
    verify-podiumd's release-baseline step already fails on a missing or
    unresolvable upgrade_docs baseline.

    Returns (True, "no matching docs found — skipped") when there's nothing to check,
    (False, "<detail>") with findings printed, or (True, "matches ...").
    """
    if not is_bare_version(upgrade_docs_baseline):
        print(
            f'WARNING: upgrade_docs_baseline "{upgrade_docs_baseline}" is missing or not a bare version — '
            "order, missing pin-bullet and pointer checks skipped (fix-doc-consistency can't run)"
        )
        result = _check_docs(chart_dir, chart_dir / "docs" / "_UPGRADE_PATHS", upgrade_docs_baseline)
        return result if isinstance(result, tuple) else _report(None, result)
    with fix_docs_dry_run(chart_dir, chart_version(chart_dir / "Chart.yaml"), upgrade_docs_baseline) as dry:
        if dry.error is not None:
            print(f"fix-doc-consistency can't run on these docs:\n{dry.error}")
            return False, "fix-doc-consistency refused to run"
        result = _check_docs(chart_dir, dry.docs_dir / "_UPGRADE_PATHS", upgrade_docs_baseline)
    if isinstance(result, tuple):
        return result
    return _report(dry.changes, result)


def _report(changes: list[DocChange] | None, findings: Findings):
    """Print the two lists; (ok, detail) for verify-podiumd. changes is None when no dry-run ran."""
    if not findings.checked and not changes:
        return True, "no matching docs found — skipped"
    if changes:
        _print_doc_changes(changes)
    if findings.mismatches:
        header = "fix by hand" + (" (found in the docs as fix-doc-consistency would leave them)" if changes else "")
        print(f"{header}, {len(findings.mismatches)} issue(s) vs {', '.join(findings.checked)}:")
        for m in sorted(findings.mismatches):
            print(" ", m)
    by_hand = f"{len(findings.mismatches)} to fix by hand"
    if changes:
        return False, f"{len(changes)} doc(s) fix-doc-consistency would change, {by_hand}"
    if findings.mismatches:
        return False, by_hand
    print(f"OK: chart versions match {', '.join(findings.checked)}")
    return True, f"matches {', '.join(findings.checked)}"
