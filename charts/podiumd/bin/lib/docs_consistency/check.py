"""check_docs_consistency: the verify-podiumd step that runs every docs check and reports."""

from collections.abc import Sequence
from pathlib import Path

from lib.chart.chart_state import BaselineState
from lib.chart.chart_state import ComponentState
from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.release_baseline_basics import chart_version
from lib.chart.values_tree_primitives import ValuesPath
from lib.cli import noun_for
from lib.component_docs.images_manifest_changes_header import find_changes_header
from lib.component_docs.values_delta_sections import has_stale_gemeente_placeholder
from lib.docs_consistency.check_context import DocQuery
from lib.docs_consistency.check_context import DocsCheckContext
from lib.docs_consistency.check_context import Findings
from lib.docs_consistency.check_context import ManifestEntryScan
from lib.docs_consistency.check_context import StateImages
from lib.docs_consistency.component_versions_table import check_component_versions_table
from lib.docs_consistency.dry_run import MAX_DIFF_LINES
from lib.docs_consistency.dry_run import DocChange
from lib.docs_consistency.dry_run import fix_docs_dry_run
from lib.docs_consistency.images_manifest_format import ManifestCheckContext
from lib.docs_consistency.images_manifest_format import check_images_manifest_format
from lib.docs_consistency.markdown_format import check_baseline_doc_set
from lib.docs_consistency.markdown_format import check_companion_doc
from lib.docs_consistency.pointer_consistency import check_pointer_consistency
from lib.docs_consistency.values_diff import ValuesDeltaInputs
from lib.docs_consistency.values_diff import check_empty_delta_sections
from lib.docs_consistency.values_diff import check_rowless_delta_headings
from lib.image.manifest_entry_pins import entry_pin
from lib.images_manifest import ManifestEntry
from lib.images_manifest import parse_images_manifest
from lib.release_baseline import BaselineChartState
from lib.release_baseline import resolve_baseline_chart_state
from lib.settings import DigestPinningException
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.chart_image_index import ChartImageIndex
from lib.upgradedoc.doc_names import STANDARD_SUFFIXES
from lib.upgradedoc.doc_names import doc_name
from lib.upgradedoc.doc_names import images_manifest_path
from lib.upgradedoc.images_manifest_list_diff import compute_changed_components
from lib.version_numbers import is_bare_version
from lib.yaml_types import load_yaml_mapping


def _pointer_row_mismatches(doc_dir: Path, upgrade_docs_baseline: str, podiumd_version: str, *, side: bool):
    """Stale sibling-doc/images-manifest reference findings for the caller's `mismatches`.

    Returned rather than returning early, so one stale link doesn't hide every other finding.
    """
    images_dir = doc_dir.parent / "images"
    pointer_docs = [doc_dir / doc_name(upgrade_docs_baseline, podiumd_version, suffix) for suffix in STANDARD_SUFFIXES]
    images_path_for_pointers = images_manifest_path(images_dir, podiumd_version)
    if images_path_for_pointers.is_file() and not side:
        pointer_docs.append(images_path_for_pointers)
    side_path = upgrade_docs_baseline if side else None
    return [
        issue
        for doc in pointer_docs
        for issue in check_pointer_consistency(doc, podiumd_version, doc_dir, images_dir, side_path)
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
            if suffix == "gemeente-specific" and has_stale_gemeente_placeholder(companion_text):
                findings.mismatches.append(
                    f'{companion_name}: still has its own stale "_None recorded yet._" placeholder '
                    f'stranded alongside a real "## <gemeente> (<env>)" section — clear it by hand '
                    f"(nothing auto-fixes this one)"
                )


def _resolve_baseline(chart_dir: Path, upgrade_docs_baseline: str | None) -> tuple[BaselineChartState, str | None]:
    """resolve_baseline_chart_state plus the mismatch a baseline_error produces.

    An empty state without a ref when no upgrade_docs_baseline was given.
    """
    if not upgrade_docs_baseline:
        return BaselineChartState(None, [], {}, [], None), None
    state = resolve_baseline_chart_state(chart_dir, upgrade_docs_baseline)
    mismatch = f'upgrade_docs_baseline "{upgrade_docs_baseline}": {state.error}' if state.error else None
    return state, mismatch


def _build_docs_check_context(
    chart_dir: Path, doc_dir: Path, podiumd_version: str, upgrade_docs_baseline: str | None, *, side: bool
):
    """Load the chart, resolve the baseline and derived image maps into a DocsCheckContext.

    Returns (ctx, baseline_mismatch); the caller adds baseline_mismatch to `findings`.
    """
    deps = load_chart_dependencies(chart_dir / "Chart.yaml")
    values = load_yaml_mapping(chart_dir / "values.yaml")
    baseline, baseline_mismatch = _resolve_baseline(chart_dir, upgrade_docs_baseline)
    baseline_ref, baseline_deps, baseline_values = baseline.ref, baseline.deps, baseline.values
    # Ground truth, independent of the docs, so a changed component missing from every doc is caught.
    actual_changed_keys: set[str] = (
        compute_changed_components(deps, baseline_deps, values, baseline_values, chart_dir=chart_dir)
        if baseline_ref
        else set()
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
            owns_images_manifest=not side,
        ),
        images=StateImages(
            ChartImageIndex(chart_dir, deps, values),
            ChartImageIndex(chart_dir, baseline_deps or [], baseline_values if baseline_ref else None),
        ),
        actual_changed_keys=actual_changed_keys,
    )
    return ctx, baseline_mismatch


def check_images_manifest_entry(
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
    # A path exempt from digest pinning without a digest field (omc.image) pins the
    # tag only; its entry still records the registry digest of that tag.
    exception = scan.sibling_fields.get(path)
    tag_only = exception is not None and exception["sibling_field"] is None
    if actual_tag != expected_tag and not (tag_only and actual_tag == version):
        findings.mismatches.append(
            f'{name}: values.yaml tag is "{actual_tag}", {scan.images_path.name} says "{expected_tag}"'
        )

    if ctx.baseline_ref and ctx.images.baseline.paths.get(path) == expected_tag:
        findings.mismatches.append(
            f"{name}: listed in {scan.images_path.name} as new/changed, but {ctx.baseline_ref} "
            f'already has this exact tag ("{expected_tag}") — did it actually change?'
        )


def _has_no_format_issues(ctx: DocsCheckContext, images_path: Path, findings: Findings) -> bool:
    """Record the manifest's format issues; False when there are any. Checked only for a bare-version baseline."""
    if not ctx.doc_query.is_bare_version:
        return True
    manifest_check_context = ManifestCheckContext(
        ctx.doc_query.upgrade_docs_baseline,
        ctx.doc_query.podiumd_version,
        ctx.current.deps,
        ctx.current.values,
        ctx.baseline.values if ctx.baseline_ref else {},
        chart_dir=ctx.chart_dir,
    )
    format_issues = check_images_manifest_format(images_path, manifest_check_context)
    if not format_issues:
        return True
    findings.checked.append(images_path.name)
    findings.mismatches.extend(format_issues)
    return False


def _check_changes_header_present(images_path: Path, entry_count: int, findings: Findings) -> None:
    """A manifest with entries needs a "# Changes:" header."""
    if not entry_count:
        return
    manifest_lines = images_path.read_text(encoding="utf-8").splitlines(keepends=True)
    header_idx, _has_count = find_changes_header(manifest_lines)
    if header_idx is None:
        noun = noun_for(entry_count, "entry", "entries")
        findings.mismatches.append(
            f'{images_path.name}: has {entry_count} {noun} but no "# Changes:" header '
            f"at all — every real change is undocumented in the summary list"
        )


def _check_images_manifest(
    ctx: DocsCheckContext,
    sibling_fields: dict[ValuesPath, DigestPinningException],
    findings: Findings,
):
    """The images-manifest section: format, "# Changes:" header presence, and per-entry checks.

    Appends onto `findings`. Entry checks are skipped when the format isn't
    interpretable, but earlier findings are kept (no early return on findings).
    """
    images_path = images_manifest_path(ctx.doc_query.doc_dir.parent / "images", ctx.doc_query.podiumd_version)
    images_format_ok = _has_no_format_issues(ctx, images_path, findings)

    if not images_path.is_file():
        print(f"WARNING: no images manifest at {images_path.name} — skipping images-manifest check")
        return
    if not images_format_ok:
        return  # format issues recorded above; entries aren't interpretable until fixed

    findings.checked.append(images_path.name)
    entries_list = parse_images_manifest(images_path.read_text(encoding="utf-8"), str(images_path))
    _check_changes_header_present(images_path, len(entries_list), findings)

    scan = ManifestEntryScan(images_path, ctx.images.current.repo_map, sibling_fields)
    for entry in entries_list:
        check_images_manifest_entry(ctx, scan, entry, findings)


def _check_values_deltas(ctx: DocsCheckContext, upgrade_docs_baseline: str, findings: Findings):
    """Empty values-deltas sections, and generated headings without an upgrade-doc row."""
    query = ctx.doc_query
    values_deltas_path = query.doc_dir / doc_name(upgrade_docs_baseline, query.podiumd_version, "values-deltas")
    if not values_deltas_path.is_file():
        return
    findings.mismatches.extend(check_empty_delta_sections(values_deltas_path))
    findings.mismatches.extend(
        check_rowless_delta_headings(
            values_deltas_path,
            query.doc_dir / doc_name(upgrade_docs_baseline, query.podiumd_version, "upgrade"),
            _values_delta_inputs(ctx),
        )
    )


def _values_delta_inputs(ctx: DocsCheckContext) -> ValuesDeltaInputs:
    return ValuesDeltaInputs(ctx.current.deps, ctx.images.current.canonical_names)


def _check_baseline_docs(
    doc_dir: Path, upgrade_docs_baseline: str | None, podiumd_version: str, findings: Findings, *, side: bool
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
    findings.mismatches.extend(_pointer_row_mismatches(doc_dir, upgrade_docs_baseline, podiumd_version, side=side))
    return None


def _check_docs(
    chart_dir: Path, doc_dir: Path, upgrade_docs_baseline: str | None, *, side: bool = False
) -> Findings | tuple[bool, str]:
    """Every finding about the docs in doc_dir; an early (ok, detail) result when the doc set itself is malformed.

    `side`: the docs of a side path, whose images manifest is the main path's and is not checked here.
    """
    podiumd_version = chart_version(chart_dir / "Chart.yaml")
    sibling_fields = digest_pinning_exceptions(chart_dir)
    findings = Findings([], [])

    precheck_result = _check_baseline_docs(doc_dir, upgrade_docs_baseline, podiumd_version, findings, side=side)
    if precheck_result is not None:
        return precheck_result

    if upgrade_docs_baseline:
        _check_companion_docs(doc_dir, upgrade_docs_baseline, podiumd_version, findings)

    ctx, baseline_mismatch = _build_docs_check_context(
        chart_dir, doc_dir, podiumd_version, upgrade_docs_baseline, side=side
    )
    if baseline_mismatch:
        findings.mismatches.append(baseline_mismatch)

    check_component_versions_table(ctx, findings)
    if not side:
        _check_images_manifest(ctx, sibling_fields, findings)

    if is_bare_version(upgrade_docs_baseline):
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


def check_docs_consistency(chart_dir: Path, upgrade_docs_baseline: str | None = None, side_paths: Sequence[str] = ()):
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

    Each of `side_paths` (release-baseline.yaml's side_paths) whose docs exist
    is checked as one more upgrade path to the same target, and reported on its own.

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
    target = chart_version(chart_dir / "Chart.yaml")
    with fix_docs_dry_run(chart_dir, target, upgrade_docs_baseline, side_paths) as dry:
        if dry.error is not None:
            print(f"fix-doc-consistency can't run on these docs:\n{dry.error}")
            return False, "fix-doc-consistency refused to run"
        doc_dir = dry.docs_dir / "_UPGRADE_PATHS"
        hops = [(upgrade_docs_baseline, _check_docs(chart_dir, doc_dir, upgrade_docs_baseline))]
        hops += [
            (side, _check_docs(chart_dir, doc_dir, side, side=True))
            for side in side_paths
            if side != upgrade_docs_baseline and any(doc_dir.glob(doc_name(side, target, "*")))
        ]
    if len(hops) == 1:
        result = hops[0][1]
        return result if isinstance(result, tuple) else _report(dry.changes, result)
    results = [
        (f"{baseline} → {target}", result if isinstance(result, tuple) else _report(None, result))
        for baseline, result in hops
    ]
    if dry.changes:
        _print_doc_changes(dry.changes)
        results.insert(0, ("", (False, f"{len(dry.changes)} doc(s) fix-doc-consistency would change")))
    return all(ok for _hop, (ok, _detail) in results), "; ".join(
        f"{hop}: {detail}" if hop else detail for hop, (_ok, detail) in results
    )


def _report(changes: list[DocChange] | None, findings: Findings):
    """Print the two lists; (ok, detail) for verify-podiumd. changes is None when no dry-run ran."""
    if not findings.checked and not changes:
        return True, "no matching docs found — skipped"
    if changes:
        _print_doc_changes(changes)
    if findings.mismatches:
        header = "fix by hand (found in the docs as fix-doc-consistency would leave them)" if changes else "fix by hand"
        print(f"{header}, {len(findings.mismatches)} issue(s) vs {', '.join(findings.checked)}:")
        for mismatch in sorted(findings.mismatches):
            print(" ", mismatch)
    by_hand = f"{len(findings.mismatches)} to fix by hand"
    if changes:
        return False, f"{len(changes)} doc(s) fix-doc-consistency would change, {by_hand}"
    if findings.mismatches:
        return False, by_hand
    print(f"OK: chart versions match {', '.join(findings.checked)}")
    return True, f"matches {', '.join(findings.checked)}"
