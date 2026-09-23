"""Checks that component versions in Chart.yaml + values.yaml match the
matching docs/_UPGRADE_PATHS/*-to-<version>-upgrade.md and
docs/images/images-<version>.yaml — and, given upgrade_docs_baseline
(see lib.chart.upgrade_docs_baseline), that every component that
actually changed vs. that baseline has a row/mention/entry in the right
doc, even if no doc mentions it yet. Only ever this one baseline —
lib.chart.release_table_baseline never flows into this file; see that
function's own docstring for why podiumd needs two baselines now."""

import re

from dataclasses import dataclass

from lib.chart.release_baseline_basics import load_yaml
from lib.chart.repo_and_path_resolution import canonical_sidecar_row_names
from lib.chart.values_tree_primitives import version_of
from lib.component_docs.changes_section import ComponentState
from lib.component_docs.changes_section import resolve_component_own_version_change
from lib.component_docs.changes_section import strip_stale_upgrade_placeholders
from lib.component_docs.images_manifest_changes_header import find_images_manifest_changes_header
from lib.component_docs.values_delta_sections import has_stale_gemeente_specific_placeholder
from lib.component_docs.values_delta_sections import strip_stale_values_deltas_todo_stub
from lib.docs_consistency.images_manifest_format import ManifestCheckContext
from lib.docs_consistency.images_manifest_format import check_images_manifest_format
from lib.docs_consistency.markdown_format import check_baseline_doc_set
from lib.docs_consistency.markdown_format import check_companion_doc
from lib.docs_consistency.markdown_format import check_doc_title
from lib.docs_consistency.pointer_consistency import check_pointer_consistency
from lib.docs_consistency.values_diff import ValuesDeltaInputs
from lib.docs_consistency.values_diff import check_values_deltas_content
from lib.image.manifest_entry_pins import current_image_paths
from lib.image.manifest_entry_pins import entry_pin
from lib.image.manifest_entry_pins import image_repo_map
from lib.release_baseline import resolve_baseline_chart_state
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.consistency_checks import find_changes_row_correspondence_gaps
from lib.upgradedoc.consistency_checks import find_wrong_or_duplicate_dependency_claims
from lib.upgradedoc.images_manifest_list_diff import compute_changed_components
from lib.upgradedoc.resolve_component_row import ResolutionContext
from lib.upgradedoc.resolve_component_row import changes_heading_has_app_version
from lib.upgradedoc.resolve_component_row import resolve_component_row
from lib.upgradedoc.sorting_and_ordering import find_out_of_order_names
from lib.upgradedoc.sorting_and_ordering import parse_upgrade_doc_changes_blocks
from lib.upgradedoc.sorting_and_ordering import parse_values_delta_sections
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import changes_heading_identities
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows as _parse_upgrade_doc_rows
from lib.upgradedoc.version_cells_and_key_changes import component_version_cell


def parse_upgrade_doc_rows(doc_path):
    """lib.upgradedoc.string_and_parsing_basics.parse_upgrade_doc_rows
    (aliased here as _parse_upgrade_doc_rows), applied to `doc_path`'s own
    file contents — this module's own callers all have a Path, not
    already-read text, so this thin wrapper saves each of them repeating
    the same read_text() call."""
    return _parse_upgrade_doc_rows(doc_path.read_text(encoding="utf-8"))


@dataclass
class Findings:
    """check_docs_consistency's own running "what got checked" / "what
    mismatched" accumulators, threaded through every phase helper below
    instead of each one returning a pair the caller has to unpack and
    extend by hand -- that unpacking is exactly where this function's
    own local-variable count used to come from."""

    checked: list
    mismatches: list


@dataclass
class ImagePaths:
    """current/baseline image-tag-path maps, bundled since every check
    that compares "the image at this path" always needs both sides at
    once, never just one alone."""

    current: dict
    baseline: dict


@dataclass
class DocQuery:
    """The four values that together pick out WHICH doc set/filenames
    check_docs_consistency is even looking for (podiumd_version/
    upgrade_docs_baseline/is_bare_version) and where (doc_dir) --
    bundled purely to keep DocsCheckContext's own attribute count under
    pylint's too-many-instance-attributes, since these four always
    travel together anyway."""

    doc_dir: object
    podiumd_version: str
    upgrade_docs_baseline: str
    is_bare_version: bool


@dataclass
class DocsCheckContext:
    """check_docs_consistency's own chart_dir/deps/values/baseline/
    image-path state, resolved once by _build_docs_check_context and
    read (never mutated) by every phase helper below -- the "Component
    versions" table section, the images-manifest section and the
    values-deltas section all need some subset of exactly this, never
    anything else from the outer function. `current`/`baseline` are
    ComponentState (see lib.component_docs.changes_section) -- the same
    deps/values pairing resolve_component_row's own ResolutionContext
    already uses."""

    chart_dir: object
    current: object
    baseline: object
    baseline_ref: str
    doc_query: DocQuery
    image_paths: ImagePaths
    actual_changed_keys: set


@dataclass
class DocScanState:
    """Everything derived from the one selected upgrade doc itself (its
    path, parsed "Component versions" rows, and canonical sidecar/
    shared-image names) -- bundled since the missing-row, ordering and
    Changes-heading checks below all need the same three, just to
    compare them against each other and against the doc's own text in
    different ways."""

    doc_path: object
    rows: list
    canonical_names: dict


@dataclass
class RowContext:
    """_check_component_rows' own doc_path/baseline_ref pair, threaded
    into each per-row sub-check purely to keep argument counts down."""

    doc_path: object
    baseline_ref: str


@dataclass
class RowLookup:
    """_check_component_rows' own canonical_names/stale_names pair --
    bundled purely to keep that function's own argument count down.
    `stale_names` is duplicate_names | wrong_fuzzy_names (see
    find_wrong_or_duplicate_dependency_claims): rows already reported
    as wrong-or-stale there, skipped here so resolve_component_row
    doesn't ALSO report them as "does not match a dependency"."""

    canonical_names: dict
    stale_names: set


@dataclass
class ComponentRowsResult:
    """_check_component_rows' own five outputs, bundled since every one
    of them is consumed by a LATER check in the same "Component
    versions" table section (missing-row-for-changed-key, missing-
    sidecar-row, and Changes-heading checks) -- never by the row loop
    itself, so returning five separate values would just make every
    caller unpack all five immediately anyway."""

    mismatches: list
    changed_component_keys: set
    # (kind, values_key) identity -> its resolved, real app version (see
    # resolve_component_identity) — populated for every "dep" row whose
    # own actual_app_version resolves to something. Used by the Changes-
    # heading checks to catch a heading whose own text never shows an
    # app-version pair at all for a component that DOES have one.
    resolved_app_by_identity: dict
    # Same identity keying as resolved_app_by_identity, holding the
    # BASELINE side instead (None when the component is genuinely new at
    # the baseline). Used, together with resolved_app_by_identity, to
    # catch a Changes heading whose own "(new)"/"(unchanged)"/"X -> Y"
    # wording DISAGREES with what the row itself would render there — a
    # real, observed bug: a heading can show the CORRECT current version
    # yet the WRONG transition wording (e.g. "(unchanged)" for a
    # component that's actually new), which changes_heading_has_app_
    # version's own "is some version shown at all" check can never catch.
    baseline_app_by_identity: dict
    matched_sidecar_paths: set


@dataclass
class ManifestEntryScan:
    """_check_images_manifest_entry's own images_path/repo_map/
    sibling_fields triple -- bundled purely to keep that function's own
    argument count down."""

    images_path: object
    repo_map: dict
    sibling_fields: object


def _pointer_consistency_mismatches(chart_dir, doc_dir, upgrade_docs_baseline, podiumd_version):
    """Unlike check_baseline_doc_set, a stale sibling-doc/images-manifest
    reference is a pure content finding about a doc that DOES exist and
    IS well-formed — nothing downstream needs to read or parse the
    reference itself, so there's no crash risk in still running every
    other check. Returned for the caller to fold into `mismatches`
    (reported together with everything else at the end) rather than an
    early return, so a single stale link can no longer hide every other
    finding this function would otherwise have made (e.g. missing
    "Component versions" rows, missing values-deltas mentions, images-
    manifest content mismatches) — the exact bug class fixed for check_
    images_manifest_format's own early return, just here for a precheck
    that had NOTHING already computed to lose, so it was invisible
    until a real doc set tripped it."""
    images_dir = chart_dir / "docs" / "images"
    pointer_docs = [
        doc_dir / f"{upgrade_docs_baseline}-to-{podiumd_version}-{suffix}.md"
        for suffix in ("upgrade", "gemeente-specific", "values-deltas")
    ]
    images_path_for_pointers = images_dir / f"images-{podiumd_version}.yaml"
    if images_path_for_pointers.is_file():
        pointer_docs.append(images_path_for_pointers)
    return [
        issue
        for doc in pointer_docs
        for issue in check_pointer_consistency(doc, upgrade_docs_baseline, podiumd_version, doc_dir, images_dir)
    ]


def _check_companion_docs(doc_dir, upgrade_docs_baseline, podiumd_version, is_bare_version, findings):
    """gemeente-specific/values-deltas companion-doc checks, appended
    straight onto `findings` — including the stale-placeholder findings
    (see lib.component_docs' own strip_stale_values_deltas_todo_stub/
    has_stale_gemeente_specific_placeholder) reported here even for a
    doc fix-doc-consistency's own retroactive pass would already auto-
    fix (values-deltas), since a doc can carry this between being
    written and that script next running; gemeente-specific has no
    fixer at all, only ever this finding."""
    if not is_bare_version:
        print(
            f'WARNING: upgrade_docs_baseline "{upgrade_docs_baseline}" is not a bare version — cannot check '
            f"for matching gemeente-specific / values-deltas docs"
        )
        return

    for suffix in ("gemeente-specific", "values-deltas"):
        doc_name, doc_mismatches = check_companion_doc(doc_dir, upgrade_docs_baseline, podiumd_version, suffix)
        findings.checked.append(doc_name)
        findings.mismatches.extend(doc_mismatches)

        companion_path = doc_dir / doc_name
        if companion_path.is_file():
            companion_text = companion_path.read_text(encoding="utf-8")
            if suffix == "values-deltas" and strip_stale_values_deltas_todo_stub(companion_text)[1]:
                findings.mismatches.append(
                    f"{doc_name}: still has its own stale TODO placeholder stranded alongside a "
                    f'real "## ..." section — run fix-doc-consistency to clear it'
                )
            elif suffix == "gemeente-specific" and has_stale_gemeente_specific_placeholder(companion_text):
                findings.mismatches.append(
                    f'{doc_name}: still has its own stale "_None recorded yet._" placeholder '
                    f'stranded alongside a real "## <gemeente> (<env>)" section — clear it by hand '
                    f"(nothing auto-fixes this one)"
                )


def _resolve_baseline(chart_dir, upgrade_docs_baseline):
    """Wraps resolve_baseline_chart_state (shared with lib.component_docs'
    own load_baseline_state/load_baseline_values and verify-release-
    table-with-podiumd's own release_table_baseline lookup — see its
    own docstring for why: a real bug in this exact resolution used to
    need fixing in three places at once) plus the one mismatch a
    baseline_error produces, so check_docs_consistency doesn't thread
    its five-value return through by hand. Returns (None, [], {}, None)
    unchanged when no upgrade_docs_baseline was given at all — the same
    "nothing to resolve" shape the original inline default had."""
    if not upgrade_docs_baseline:
        return None, [], {}, None
    baseline_ref, baseline_deps, baseline_values, _baseline_lines, baseline_error = resolve_baseline_chart_state(
        chart_dir, upgrade_docs_baseline
    )
    mismatch = f'upgrade_docs_baseline "{upgrade_docs_baseline}": {baseline_error}' if baseline_error else None
    return baseline_ref, baseline_deps, baseline_values, mismatch


def _resolve_image_paths(chart_dir, deps, values, baseline_ref, baseline_values):
    """current/baseline image-tag-path maps plus the shared-image
    repository-group representative map — bundled since every
    downstream check that compares "the image at this path" needs all
    three, and none of them differ in how they're derived (lib.image.
    manifest_entry_pins, gated on baseline_ref the same way
    check_docs_consistency's own baseline_deps/baseline_values default
    to []/{} when there's no baseline at all)."""
    current_paths = current_image_paths(values)
    baseline_paths = current_image_paths(baseline_values) if baseline_ref else {}
    repo_map = image_repo_map(chart_dir, deps, values, current_paths) if chart_dir is not None else {}
    return current_paths, baseline_paths, repo_map


def _build_docs_check_context(chart_dir, deps, values, podiumd_version, upgrade_docs_baseline):
    """Resolves the baseline and every image-tag-path map derived from
    it, and bundles all of it into the DocsCheckContext every later
    phase helper reads from — one place doing this resolution instead
    of it being threaded, unpacked and rebuilt by hand at every call
    site. Returns (ctx, repo_map, baseline_mismatch); the caller folds
    baseline_mismatch into `findings` itself (this function has no
    `findings` of its own to append onto)."""
    baseline_ref, baseline_deps, baseline_values, baseline_mismatch = _resolve_baseline(
        chart_dir, upgrade_docs_baseline
    )
    # Ground truth for "did this component actually change" — independent of
    # what the docs currently say, so it also catches a component that
    # changed but was never added to any doc at all.
    actual_changed_keys = (
        compute_changed_components(deps, baseline_deps, values, baseline_values) if baseline_ref else set()
    )
    current_paths, baseline_paths, repo_map = _resolve_image_paths(
        chart_dir, deps, values, baseline_ref, baseline_values
    )

    ctx = DocsCheckContext(
        chart_dir=chart_dir,
        current=ComponentState(deps, values),
        baseline=ComponentState(baseline_deps, baseline_values),
        baseline_ref=baseline_ref,
        doc_query=DocQuery(
            chart_dir / "docs" / "_UPGRADE_PATHS",
            podiumd_version,
            upgrade_docs_baseline,
            bool(upgrade_docs_baseline and re.match(r"^\d+\.\d+\.\d+", upgrade_docs_baseline)),
        ),
        image_paths=ImagePaths(current_paths, baseline_paths),
        actual_changed_keys=actual_changed_keys,
    )
    return ctx, repo_map, baseline_mismatch


def _doc_header_mismatches(doc_path, ctx):
    """Title + stale-TODO-placeholder checks on the selected upgrade doc
    itself — both read the doc's own text/title, nothing else, so
    bundled here together rather than as two separate one-line callers.
    The stale-placeholder finding is reported even when fix-doc-
    consistency's own retroactive pass would already auto-fix it, since
    it can be stranded between a doc being written and that script next
    running (see lib.component_docs.strip_stale_upgrade_placeholders,
    reused here unapplied — its own `changed` flag doubles as this
    finding, no separate detector to drift)."""
    mismatches = []
    if ctx.doc_query.is_bare_version:
        mismatches.extend(check_doc_title(doc_path, ctx.doc_query.upgrade_docs_baseline, ctx.doc_query.podiumd_version))
    if strip_stale_upgrade_placeholders(doc_path.read_text(encoding="utf-8"))[1]:
        mismatches.append(
            f'{doc_path.name}: still has a stale "TODO" placeholder stranded alongside real content '
            f"— run fix-doc-consistency to clear it"
        )
    return mismatches


def _record_row_identity(resolved, result):
    """Extracts one resolved row's own sidecar_path/values_key/top_
    level_key/actual_app and records the bookkeeping every later check
    (in this row, and in later phases via ComponentRowsResult) needs —
    matched_sidecar_paths, resolved_app_by_identity, changed_
    component_keys — directly onto `result`. Returns (values_key,
    actual_app) for the caller's own target/baseline version checks."""
    sidecar_path = resolved["sidecar_path"]
    values_key, top_level_key = resolved["values_key"], resolved["top_level_key"]
    actual_app = resolved["target_app"]

    if resolved["kind"] == "sidecar":
        result.matched_sidecar_paths.add(sidecar_path)
    elif actual_app:
        # "dependency" and "native" (see lib.chart.native_components)
        # share this identity shape — resolve_component_identity/
        # changes_heading_identities both resolve a native
        # component to ("dep", values_key) too, so this dict's own
        # keys must match theirs.
        result.resolved_app_by_identity[("dep", values_key)] = actual_app

    result.changed_component_keys.add(top_level_key)
    return values_key, actual_app


def _check_row_target_versions(row, row_ctx, resolved, values_key, result):
    """One row's own current chart/app-version cells vs. Chart.yaml/
    values.yaml reality."""
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


def _check_row_baseline_versions(row, row_ctx, resolved, values_key, result):
    """One row's own source chart/app-version cells vs. row_ctx.
    baseline_ref reality — only called once row_ctx.baseline_ref is
    set (the caller's own loop already gates this)."""
    actual_app = resolved["target_app"]
    if resolved["baseline_resolved"] is False:
        # A warning, not a mismatch — most commonly a brand-new
        # component with no baseline version to compare against at
        # all (fix-doc-consistency's own fix_component_version_
        # table writes "(new)" cells for exactly this row shape),
        # not a doc/reality disagreement this check exists to catch.
        print(
            f'WARNING: {row_ctx.doc_path.name}: doc row "{row["name"]}" source version could not '
            f"be verified against {row_ctx.baseline_ref} — the component didn't exist there yet, "
            f"or its version isn't resolvable there; source cells left unchecked"
        )
        if resolved["kind"] != "sidecar" and actual_app:
            result.baseline_app_by_identity[("dep", values_key)] = None
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
    if baseline_app_actual and normalize_version(row["app_source"]) != normalize_version(baseline_app_actual):
        result.mismatches.append(
            f'{values_key} ("{row["name"]}") source app: {row_ctx.baseline_ref} has '
            f'"{baseline_app_actual}", {row_ctx.doc_path.name} says "{row["app_source"] or "-"}"'
        )


def _check_component_rows(rows, row_ctx, row_lookup, resolution):
    """The per-row loop of the "Component versions" table section —
    resolves each row via resolve_component_row (shared with fix-doc-
    consistency's own row-rewriter, fix_component_version_table — see
    its docstring for why a checker/fixer that resolve a row two
    different ways can silently drift apart on what "correct" even
    means) and checks its chart/app-version cells, both current and
    (when row_ctx.baseline_ref is given) source, against reality."""
    result = ComponentRowsResult([], set(), {}, {}, set())

    for row in rows:
        if row["name"] in row_lookup.stale_names:
            continue

        resolved = resolve_component_row(row["name"], row_lookup.canonical_names, resolution)
        if resolved["kind"] == "unmatched":
            result.mismatches.append(
                f'{row_ctx.doc_path.name}: doc row "{row["name"]}" does not match a Chart.yaml '
                f'dependency or a canonical sidecar/shared-image name ("<component> - '
                f'<basename>" or "<basename>", the exact form update-image-version writes) '
                f"— wrong phrasing, or a stale row"
            )
            continue

        values_key, _actual_app = _record_row_identity(resolved, result)
        _check_row_target_versions(row, row_ctx, resolved, values_key, result)
        if row_ctx.baseline_ref:
            _check_row_baseline_versions(row, row_ctx, resolved, values_key, result)

    return result


def _check_missing_component_rows(ctx, scan, rows_result):
    """The two "changed vs baseline but has no row at all" checks — one
    for a dependency/native component's own primary row (358-380's
    original shape: a key whose own chart+app both resolve unchanged
    never needed a row of its own, since resolve_component_own_version_
    change is shared with fix-doc-consistency's own add_missing_
    component_rows, so the two can never drift on which keys actually
    need one), one for a sidecar/shared image nested under an already-
    rowed dependency (e.g. redis-operator's own row exists, but its
    nested redis-ha image bump has never been added at all — a true
    omission the row-matching above can't see, since no row even claims
    to be about it). Only called when ctx.baseline_ref is set."""
    mismatches = []
    for key in sorted(ctx.actual_changed_keys - rows_result.changed_component_keys):
        resolved = resolve_component_own_version_change(
            key,
            ComponentState(ctx.current.deps, ctx.current.values),
            ComponentState(ctx.baseline.deps, ctx.baseline.values),
            ctx.chart_dir,
            ctx.doc_query.upgrade_docs_baseline,
        )
        if resolved is not None and resolved[-1]:
            continue
        mismatches.append(
            f'{scan.doc_path.name}: component "{key}" changed vs {ctx.baseline_ref} but has no row '
            f'in the "Component versions" table'
        )

    for name, path in sorted(scan.canonical_names.items()):
        if path in rows_result.matched_sidecar_paths:
            continue
        baseline_tag, current_tag = ctx.image_paths.baseline.get(path), ctx.image_paths.current.get(path)
        # Compared by VERSION (lib.chart.version_of — the tag with any
        # "@sha256:..." digest suffix stripped), never the raw tag
        # string — a digest-only re-pin (same version, e.g. a chart-wide
        # digest-pinning sweep) is not a "changed vs baseline" case
        # -upgrade.md needs a row for. Real bug: this comparison used to
        # be raw-tag equality, so nginx-unprivileged (version unchanged,
        # only its digest moved) was flagged forever — the exact same
        # class of bug already fixed in lib.upgradedoc.compute_changed_
        # components and lib.image.docs.add_missing_sidecar_rows, just
        # never ported to this one, independent copy of the same check.
        if (version_of(baseline_tag) if baseline_tag is not None else None) != (
            version_of(current_tag) if current_tag is not None else None
        ):
            mismatches.append(
                f'{scan.doc_path.name}: sidecar/shared image "{name}" changed vs {ctx.baseline_ref} '
                f'but has no row in the "Component versions" table'
            )
    return mismatches


def _check_row_and_heading_order(ctx, scan):
    """ "Component versions" table rows and "## Changes" headings should
    both follow values.yaml's own component order (see find_out_of_
    order_names) — checked here together since both use the same key_
    order/canonical_names, just against a different name list. Returns
    (mismatches, changes_headings, doc_text): the latter two are re-
    used by _check_changes_heading_correspondence right after, so it
    doesn't have to re-read/re-parse the same doc a second time."""
    mismatches = []
    key_order = values_key_order(ctx.current.values)
    row_names = [row["name"] for row in scan.rows]
    for name_a, name_b in find_out_of_order_names(
        row_names, ctx.current.deps, key_order, scan.canonical_names, ctx.current.values
    ):
        mismatches.append(
            f'{scan.doc_path.name}: "Component versions" table lists "{name_b}" right after "{name_a}", '
            f"but values.yaml lists {name_b} before {name_a} — rows should follow values.yaml's "
            f"own component order"
        )

    doc_text = scan.doc_path.read_text(encoding="utf-8")
    changes_headings = [b["heading"] for b in parse_upgrade_doc_changes_blocks(doc_text)]
    for name_a, name_b in find_out_of_order_names(
        changes_headings, ctx.current.deps, key_order, scan.canonical_names, ctx.current.values
    ):
        mismatches.append(
            f'{scan.doc_path.name}: "## Changes" section has "### {name_b}" right after "### {name_a}", '
            f"but values.yaml lists the {name_b} component before {name_a} — Changes blocks should "
            f"follow values.yaml's own component order"
        )
    return mismatches, changes_headings, doc_text


def _check_changes_heading_correspondence(ctx, scan, rows_result, changes_headings, doc_text):
    """Only checked when the doc actually has a "## Changes" heading at
    all — a fixture/stub doc that never got that far yet (no section to
    compare against) would otherwise have EVERY row reported as missing
    its heading, which isn't the gap this check exists to catch. Then:
    every row has a matching "### ..." section and vice versa (see
    find_changes_row_correspondence_gaps); a heading naming exactly one
    "dep" component that DOES have a real, resolved app version (see
    ComponentRowsResult.resolved_app_by_identity) must actually show it
    — a heading written back when that version wasn't resolvable yet
    (e.g. openbao's own "### openbao 0.28.4" — chart-only, add_missing_
    component_rows' TODO-stub shape) never gets rewritten just because
    actual_app_version later learns how to resolve it (fix-doc-
    consistency never rewrites an EXISTING section's own text), so this
    can silently go stale forever unless checked for directly; and a
    heading can ALREADY show the correct current app version yet still
    get the transition wording wrong (real bug: "openbao v2.5.5
    (unchanged)" when openbao's own baseline app version was actually
    unresolvable — the component is really "(new)" to this doc, per
    component_version_cell's own convention) — this reuses component_
    version_cell directly (the exact function that decides this for
    the table row's own cell) so the row and its own Changes heading
    can never independently drift on what "correct" wording even
    means, the same "shared resolution" principle resolve_component_
    row's own docstring already applies to the row side."""
    has_changes_section = any(line.strip() == "## Changes" for line in doc_text.splitlines())
    if not has_changes_section:
        return []

    mismatches = []
    rows_without_heading, headings_without_row = find_changes_row_correspondence_gaps(
        scan.rows, changes_headings, ctx.current.deps, scan.canonical_names
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
            if expected_app_heading not in without_chart_clause:
                mismatches.append(
                    f'{scan.doc_path.name}: "## Changes" section "### {heading}" shows the wrong '
                    f'app-version transition in its own heading — expected "{expected_app_heading}" '
                    f"(values.yaml/{ctx.baseline_ref} show {rows_result.baseline_app_by_identity[identity]!r} -> "
                    f"{actual_app!r})"
                )
    return mismatches


def _select_upgrade_doc(ctx, findings):
    """Selects the one upgrade doc to check (see check_docs_consistency's
    own docstring for the "<baseline>-to-<target>-upgrade.md" filename
    shape), appends its own title/stale-placeholder findings and its
    "checked" entries, and warns (never fails) on zero or multiple
    matches. Returns None when there's no doc to check at all."""
    doc_glob = (
        f"{ctx.doc_query.upgrade_docs_baseline}-to-{ctx.doc_query.podiumd_version}-upgrade.md"
        if ctx.doc_query.is_bare_version
        else f"*-to-{ctx.doc_query.podiumd_version}-upgrade.md"
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


def _check_component_versions_table(ctx, findings):
    """The "Component versions" table section of check_docs_consistency
    (see that function's own docstring) — doc selection, per-row
    checks, missing-row checks, row/heading ordering checks, and
    Changes-heading checks, all gated on the SAME selected upgrade doc.
    Appends every finding straight onto `findings`; does nothing at all
    when no doc matches (see check_docs_consistency's own "no matching
    docs found" return)."""
    doc_path = _select_upgrade_doc(ctx, findings)
    if doc_path is None:
        return

    canonical_names = canonical_sidecar_row_names(
        ctx.chart_dir, ctx.current.deps, ctx.current.values, ctx.image_paths.current.keys()
    )
    resolution = ResolutionContext(
        ctx.chart_dir,
        ComponentState(ctx.current.deps, ctx.current.values),
        ComponentState(ctx.baseline.deps if ctx.baseline_ref else None, ctx.baseline.values),
        ctx.doc_query.upgrade_docs_baseline if ctx.baseline_ref else None,
    )
    rows = list(parse_upgrade_doc_rows(doc_path))

    # Two more deterministic gaps, checked once up front before the
    # main per-row pass below — see find_wrong_or_duplicate_dependency_
    # claims for exactly what these catch (duplicate row names, and a
    # free-form row fuzzy-matching a dependency another row already
    # exactly claims, e.g. a stale "Kiss Elasticsearch" row).
    duplicate_names, wrong_fuzzy_names = find_wrong_or_duplicate_dependency_claims(
        [row["name"] for row in rows], ctx.current.deps
    )
    findings.mismatches.extend(
        f'{doc_path.name}: doc row "{name}" is wrong or stale — not found in Chart.yaml or values.yaml'
        for name in sorted(duplicate_names | wrong_fuzzy_names)
    )

    row_lookup = RowLookup(canonical_names, duplicate_names | wrong_fuzzy_names)
    row_ctx = RowContext(doc_path, ctx.baseline_ref)
    rows_result = _check_component_rows(rows, row_ctx, row_lookup, resolution)
    findings.mismatches.extend(rows_result.mismatches)

    scan = DocScanState(doc_path, rows, canonical_names)
    if ctx.baseline_ref:
        findings.mismatches.extend(_check_missing_component_rows(ctx, scan, rows_result))

    order_mismatches, changes_headings, doc_text = _check_row_and_heading_order(ctx, scan)
    findings.mismatches.extend(order_mismatches)
    findings.mismatches.extend(
        _check_changes_heading_correspondence(ctx, scan, rows_result, changes_headings, doc_text)
    )


def _check_images_manifest_entry(ctx, scan, entry, findings):
    """One images-manifest entry's own version/digest/already-in-
    baseline checks — split out of the entries loop purely to keep
    that loop's own complexity down."""
    name = entry.get("name")
    if not name:
        return
    path, actual_tag = entry_pin(entry, ctx.current.values, ctx.image_paths.current, scan.repo_map, scan.sibling_fields)
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

    if ctx.baseline_ref and ctx.image_paths.baseline.get(path) == expected_tag:
        findings.mismatches.append(
            f"{name}: listed in {scan.images_path.name} as new/changed, but {ctx.baseline_ref} "
            f'already has this exact tag ("{expected_tag}") — did it actually change?'
        )


def _check_images_manifest(ctx, repo_map, sibling_fields, findings):
    """The images-manifest section of check_docs_consistency (see that
    function's own docstring) — manifest format validation, the "any
    real entries but no '# Changes:' header" catch-all (real bug this
    fixes: images-4.9.1.yaml gained 5 real entries in one session with
    no "# Changes:" header ever created for them to be listed in — see
    lib.component_docs.ensure_images_manifest_changes_header's own
    docstring), and the per-entry version/digest/already-in-baseline
    checks. Appends every finding straight onto `findings`; entry-by-
    entry checks are skipped entirely when the format itself isn't
    safely interpretable (see images_format_ok below) — but that must
    NOT discard mismatches already found above (e.g. a missing
    "Component versions" table row), so this never returns early on
    its own findings, only on preconditions with nothing to check."""
    images_path = ctx.chart_dir / "docs" / "images" / f"images-{ctx.doc_query.podiumd_version}.yaml"

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
        return  # format issue(s) already recorded above; entries aren't safely interpretable until fixed

    findings.checked.append(images_path.name)
    entries_list = load_yaml(images_path) or []

    if entries_list:
        manifest_lines = images_path.read_text(encoding="utf-8").splitlines(keepends=True)
        header_idx, _has_count = find_images_manifest_changes_header(manifest_lines)
        if header_idx is None:
            noun = "entry" if len(entries_list) == 1 else "entries"
            findings.mismatches.append(
                f'{images_path.name}: has {len(entries_list)} {noun} but no "# Changes:" header '
                f"at all — every real change is undocumented in the summary list"
            )

    scan = ManifestEntryScan(images_path, repo_map, sibling_fields)
    for entry in entries_list:
        _check_images_manifest_entry(ctx, scan, entry, findings)


def _check_values_deltas(ctx, findings):
    """The values-deltas doc's own content + section-ordering checks —
    only called when a baseline was resolved, the doc set is a genuine
    bare version, and at least one component actually changed (see
    check_docs_consistency's own guard)."""
    values_deltas_path = (
        ctx.doc_query.doc_dir
        / f"{ctx.doc_query.upgrade_docs_baseline}-to-{ctx.doc_query.podiumd_version}-values-deltas.md"
    )
    canonical_names_for_deltas = canonical_sidecar_row_names(
        ctx.chart_dir, ctx.current.deps, ctx.current.values, ctx.image_paths.current.keys()
    )
    findings.mismatches.extend(
        check_values_deltas_content(
            values_deltas_path,
            ctx.actual_changed_keys,
            ValuesDeltaInputs(ctx.baseline.values, ctx.current.values, ctx.current.deps, canonical_names_for_deltas),
        )
    )

    deltas_key_order = values_key_order(ctx.current.values)
    deltas_headings = [
        s["heading"] for s in parse_values_delta_sections(values_deltas_path.read_text(encoding="utf-8"))
    ]
    for name_a, name_b in find_out_of_order_names(
        deltas_headings, ctx.current.deps, deltas_key_order, canonical_names_for_deltas, ctx.current.values
    ):
        findings.mismatches.append(
            f'{values_deltas_path.name}: "## {name_b}" section comes right after "## {name_a}", '
            f"but values.yaml lists the {name_b} component before {name_a} — sections should follow "
            f"values.yaml's own component order"
        )


def _check_baseline_doc_set_and_pointers(chart_dir, doc_dir, upgrade_docs_baseline, podiumd_version, findings):
    """When upgrade_docs_baseline is a genuine bare version: runs the
    baseline doc-set precheck (returns an early-return result the
    caller must propagate straight out of check_docs_consistency when
    the doc set itself is malformed — see check_baseline_doc_set's own
    docstring) and, if the doc set is fine, the pointer-consistency
    checks (folded into `findings` instead). Returns None both when
    there's nothing to precheck (not a bare version) and when the
    precheck passed clean."""
    if not bool(upgrade_docs_baseline and re.match(r"^\d+\.\d+\.\d+", upgrade_docs_baseline)):
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
    findings.mismatches.extend(
        _pointer_consistency_mismatches(chart_dir, doc_dir, upgrade_docs_baseline, podiumd_version)
    )
    return None


def check_docs_consistency(chart_dir, upgrade_docs_baseline=None):
    """The verify-podiumd check itself (see this module's own docstring for
    what it checks): Chart.yaml/values.yaml's actual component versions
    against docs/_UPGRADE_PATHS/<upgrade_docs_baseline>-to-<version>-
    {upgrade,gemeente-specific,values-deltas}.md and docs/images/images-
    <version>.yaml, plus (when `upgrade_docs_baseline` is given) that
    every component genuinely changed since that baseline has a row/
    section/entry somewhere in that doc set, even one no doc mentions at
    all yet.

    `upgrade_docs_baseline` may be None (doc content is checked against
    current values.yaml only, no "did X actually change" comparison is
    possible) or a non-bare-version ref (e.g. a branch name) — several
    baseline-doc-set/companion-doc checks only run when it's a genuine
    bare MAJOR.MINOR.PATCH (see `is_bare_version` below), since those
    checks assume the standard "<baseline>-to-<target>-<suffix>.md"
    filename shape.

    Returns (True, "no matching docs found — skipped") if no relevant doc
    exists to check against at all (nothing this function is able to
    validate yet, not a pass on the merits). Otherwise (False,
    "<n> mismatch(es)") with every finding printed, or (True, "matches
    ...") when everything checked lines up."""
    chart_yaml = load_yaml(chart_dir / "Chart.yaml")
    podiumd_version = str(chart_yaml["version"])
    deps = chart_yaml.get("dependencies", [])
    values = load_yaml(chart_dir / "values.yaml") or {}
    sibling_fields = digest_pinning_exceptions(chart_dir)
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    is_bare_version = bool(upgrade_docs_baseline and re.match(r"^\d+\.\d+\.\d+", upgrade_docs_baseline))

    findings = Findings([], [])

    precheck_result = _check_baseline_doc_set_and_pointers(
        chart_dir, doc_dir, upgrade_docs_baseline, podiumd_version, findings
    )
    if precheck_result is not None:
        return precheck_result

    if upgrade_docs_baseline:
        _check_companion_docs(doc_dir, upgrade_docs_baseline, podiumd_version, is_bare_version, findings)

    ctx, repo_map, baseline_mismatch = _build_docs_check_context(
        chart_dir, deps, values, podiumd_version, upgrade_docs_baseline
    )
    if baseline_mismatch:
        findings.mismatches.append(baseline_mismatch)

    _check_component_versions_table(ctx, findings)
    _check_images_manifest(ctx, repo_map, sibling_fields, findings)

    if ctx.baseline_ref and is_bare_version and ctx.actual_changed_keys:
        _check_values_deltas(ctx, findings)

    if not findings.checked:
        return True, "no matching docs found — skipped"

    if findings.mismatches:
        print(f"FOUND {len(findings.mismatches)} mismatch(es) vs {', '.join(findings.checked)}:")
        for m in sorted(findings.mismatches):
            print(" ", m)
        return False, f"{len(findings.mismatches)} mismatch(es)"
    print(f"OK: chart versions match {', '.join(findings.checked)}")
    return True, f"matches {', '.join(findings.checked)}"
