"""Update the docs for a shared image basename's version bump — the
"Component versions" table row, "## Changes" section, values-deltas
bullet, and images-<target>.yaml entry, all keyed by the basename/
repository itself rather than any one consuming component's values-tree
path. Used only when a basename bump (lib.image.version.
update_image_version) actually touches more than one Chart.yaml
component — a bump resolving to exactly one component (e.g. via a
dependency alias like "openklant") gets the SAME full-fidelity treatment
update-component-version itself uses (lib.component_docs, real chart
version), not this module.

Convention confirmed against docs/_UPGRADE_PATHS/4.8.1-to-4.8.2-
upgrade.md: curl/nginx-unprivileged/busybox each got their own table row
(Helm chart column "-") and a "### <name> ..." Changes block listing
every place they're pinned. The row naturally sorts after every real
component — lib.upgradedoc.component_order_key's own "unmatched sorts
last" rule already produces that with no special-casing needed here,
since a bare basename never matches a Chart.yaml dependency by name."""

import re

from dataclasses import dataclass
from pathlib import Path

from lib.chart.historical_baselines import baseline_lookup
from lib.chart.historical_baselines import baseline_tag_for_sidecar_path
from lib.chart.historical_baselines import historical_app_version_for_path
from lib.chart.pull_and_subchart_resolution import global_image_paths
from lib.chart.pull_and_subchart_resolution import resolved_digest_pin
from lib.chart.registered_paths import image_paths_for
from lib.chart.registered_paths import version_paths_for
from lib.chart.repo_and_path_resolution import canonical_sidecar_row_names
from lib.chart.repo_and_path_resolution import full_repository_for_path
from lib.chart.repo_and_path_resolution import paths_by_repository
from lib.chart.repo_and_path_resolution import repo_group_representative
from lib.chart.values_tree_primitives import dep_for_values_key
from lib.chart.values_tree_primitives import get_path
from lib.chart.values_tree_primitives import replace_scalar_value
from lib.chart.values_tree_primitives import version_of
from lib.checks.digest_pinning import find_unresolved_subchart_images
from lib.component_docs.changes_section import ComponentIdentity
from lib.component_docs.changes_section import ComponentState
from lib.component_docs.changes_section import DocContext
from lib.component_docs.changes_section import OrderingContext
from lib.component_docs.changes_section import VersionChange
from lib.component_docs.changes_section import insert_changes_section
from lib.component_docs.changes_section import make_changes_section
from lib.component_docs.changes_section import remove_changes_block
from lib.component_docs.changes_section import remove_changes_section
from lib.component_docs.changes_section import update_component_table
from lib.component_docs.images_manifest_changes_header import CHANGES_ITEM_RE
from lib.component_docs.images_manifest_changes_header import find_changes_item
from lib.component_docs.images_manifest_changes_header import find_images_manifest_changes_header
from lib.component_docs.images_manifest_changes_header import images_manifest_changes_block
from lib.component_docs.images_manifest_changes_header import insert_images_manifest_header_item
from lib.component_docs.images_manifest_changes_header import remove_changes_item
from lib.registry import parse_repo
from lib.registry import registry_tag_exists
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.app_version_and_image_paths import actual_app_version
from lib.upgradedoc.app_version_and_image_paths import find_all_image_and_version_paths
from lib.upgradedoc.app_version_and_image_paths import find_image_tag_paths
from lib.upgradedoc.consistency_checks import find_changes_row_correspondence_gaps
from lib.upgradedoc.consistency_checks import resolve_component_identity
from lib.upgradedoc.grouped_comments_and_changes_block import find_preceding_comment_line
from lib.upgradedoc.images_manifest_ordering import images_manifest_entry_order_key
from lib.upgradedoc.resolve_component_row import changes_heading_has_app_version
from lib.upgradedoc.sorting_and_ordering import component_order_key
from lib.upgradedoc.sorting_and_ordering import parse_upgrade_doc_changes_blocks
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import changes_heading_identities
from lib.upgradedoc.string_and_parsing_basics import extract_source_version
from lib.upgradedoc.string_and_parsing_basics import match_located_line
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows
from lib.upgradedoc.version_cells_and_key_changes import image_manifest_version_text
from lib.upgradedoc.version_cells_and_key_changes import replace_version_pair
from lib.upgradedoc.version_cells_and_key_changes import version_change_suffix


def make_image_changes_section(
    basename: str, target: str, old_version: str | None, new_version: str | None, pinned: list
):
    """The "### <basename> <old> → <new>" Changes block for a shared
    image basename bump. `pinned` is [(dotted_path, old_version), ...]
    for every values.yaml tag pin actually bumped (see
    lib.image.version.update_image_version's own return value) — listed
    individually rather than assuming one uniform "old" version, since a
    basename's various pins aren't guaranteed to have all started at the
    exact same one.

    `old_version` (and, independently, each pin's own `path_old_version`)
    is None when that specific pin never had a prior value to diff
    against at all (genuinely new — real case: a brand-new shared
    "redis" cache sidecar aliased into a dozen components at once) —
    renders "(new)" there instead of a nonsensical "None → <new>".
    `old_version`/`path_old_version` already equal to `new_version`
    (already resolved as "unchanged" by the caller — e.g. the images-
    baseline.yaml fallback matching a digest-only re-pin, or a
    genuinely new path pinned to an already-known image) renders
    "(unchanged)" instead of an equally nonsensical "<version> →
    <version>" self-transition — same reasoning throughout: this doc is
    about version changes, and there isn't one to report in either
    case."""
    suffix = version_change_suffix(old_version, new_version)
    if old_version is None:
        heading_suffix = f"{new_version} {suffix}"
        intro = f"PodiumD {target} introduces the shared **{basename}** image at {new_version},\n"
    elif suffix:
        heading_suffix = f"{new_version} {suffix}"
        intro = f"PodiumD {target} keeps the shared **{basename}** image at {new_version},\n"
    else:
        heading_suffix = f"{old_version} → {new_version}"
        intro = f"PodiumD {target} upgrades the shared **{basename}** image to {new_version},\n"
    lines = [f"### {basename} {heading_suffix}\n\n", intro, "pinned at:\n\n"]
    for path, path_old_version in pinned:
        path_suffix = version_change_suffix(path_old_version, new_version)
        if path_suffix:
            lines.append(f"- `{path}` `{new_version}` {path_suffix}\n")
        else:
            lines.append(f"- `{path}` `{path_old_version}` → `{new_version}`\n")
    lines.append(f"\n- Image / digest: see [`images-{target}.yaml`](../images/images-{target}.yaml).\n\n")
    return "".join(lines)


@dataclass
class _SidecarScanState:
    """add_missing_sidecar_rows' own precomputed values.yaml-derived
    tables its per-path loop reads from — computed once up front
    (identical for every candidate path, not per-path) rather than
    recomputed on every iteration."""

    canonical_names: dict
    current_paths: dict
    baseline_paths: dict
    baseline_repo_groups: dict
    matched_paths: set


@dataclass
class _SidecarRowContext:
    """_SidecarScanState + the target_state/baseline_values/doc_context
    a single sidecar row's own resolution needs, bundled purely to keep
    _add_sidecar_row's own argument count down."""

    state: _SidecarScanState
    target_state: ComponentState
    baseline_values: dict | None
    doc_context: DocContext


def _sidecar_scan_state(text: str, doc_context: DocContext, target_state: ComponentState, baseline_values: dict | None):
    """Builds _SidecarScanState — split out of add_missing_sidecar_rows
    purely to keep its own local-variable count down."""
    current_paths = dict(find_image_tag_paths(target_state.values))
    current_paths.update(global_image_paths(target_state.values))
    baseline_paths = dict(find_image_tag_paths(baseline_values)) if baseline_values else {}
    baseline_paths.update(global_image_paths(baseline_values) if baseline_values else [])
    canonical_names = canonical_sidecar_row_names(
        doc_context.chart_dir, target_state.deps, target_state.values, current_paths.keys()
    )
    # Grouped once, up front, against baseline_values (NOT target_state.
    # values -- this is "where did this repository already live in the
    # baseline tree", not a current-tree question) and reused across
    # every path below rather than recomputed per path.
    baseline_repo_groups = (
        paths_by_repository(doc_context.chart_dir, target_state.deps, baseline_values, baseline_paths.keys())
        if baseline_values
        else {}
    )
    matched_paths = {
        path for row in parse_upgrade_doc_rows(text) for path in [canonical_names.get(row["name"])] if path is not None
    }
    return _SidecarScanState(canonical_names, current_paths, baseline_paths, baseline_repo_groups, matched_paths)


def _resolve_sidecar_old_app(path: tuple[str, ...], ctx: _SidecarRowContext):
    """A sidecar path's own prior app version when there's no EXACT
    match in ctx.state.baseline_paths (baseline_tag is None) — not
    immediately treated as genuinely new. Two fallback tiers, in order:
    1. lib.chart.baseline_tag_for_sidecar_path — does this same
       repository already live somewhere else in baseline_values, under
       a different values-tree path? Real case: podiumd 4.9.1
       consolidated two separate postgres pins (keycloak-operator's own
       ensurePodiumdAdminUser job and openbao's own schemaJob) into one
       new shared global.images.postgres anchor — that exact path never
       existed in the 4.9.1 baseline, but the same "postgres" repository
       already did, at openbao.database.schemaJob.image; that path's own
       baseline tag is the true prior version, even though this exact
       path is new.
    2. Only once that also finds nothing: does this repository appear in
       any of this chart's own PAST images-<version>.yaml manifests
       (real, already-committed per-release documents)? Never a fallback
       to the removed images-baseline.yaml side-file (ACR-mirror digest
       provenance, a genuinely different, unrelated question)."""
    old_app = baseline_tag_for_sidecar_path(
        baseline_lookup(
            ctx.doc_context.chart_dir, ctx.target_state.deps, ctx.target_state.values, ctx.baseline_values, ctx.state
        ),
        path,
    )
    if old_app is None and ctx.baseline_values:
        old_app = historical_app_version_for_path(
            ctx.doc_context.chart_dir,
            ctx.target_state.deps,
            ctx.target_state.values,
            path,
            ctx.doc_context.upgrade_docs_baseline,
        )
    return old_app


def _add_sidecar_row(text: str, name: str, path: tuple[str, ...], ctx: _SidecarRowContext):
    """Insert `name`'s own missing sidecar/shared-image row + Changes
    section into `text` for values-tree path `path`, or (text, False)
    unchanged if it's already matched, unchanged since baseline (a
    digest-only re-pin never counts — -upgrade.md documents version
    changes only), or the doc has no table to insert into at all. Split
    out of add_missing_sidecar_rows' own per-path loop purely to keep
    ITS own local-variable count down."""
    if path in ctx.state.matched_paths:
        return text, False
    current_tag = ctx.state.current_paths.get(path)
    baseline_tag = ctx.state.baseline_paths.get(path)
    if current_tag is None or (baseline_tag is not None and version_of(current_tag) == version_of(baseline_tag)):
        return text, False
    new_app = current_tag.split("@", 1)[0]
    old_app = _resolve_sidecar_old_app(path, ctx)

    ordering = OrderingContext(ctx.target_state.deps, ctx.target_state.values, ctx.state.canonical_names)
    text, table_action = update_component_table(text, name, VersionChange(old_app, new_app, None, "-"), ordering)
    if table_action is None:
        return text, False  # doc has no "Component versions" table at all to insert into

    text, _ = remove_changes_section(text, name, ordering)
    dotted_path = ".".join(path) + ".tag"
    section = make_image_changes_section(name, ctx.doc_context.target, old_app, new_app, [(dotted_path, old_app)])
    text = insert_changes_section(text, section, name, ordering)
    return text, True


def add_missing_sidecar_rows(
    text: str, doc_context: DocContext, target_state: ComponentState, baseline_values: dict | None
):
    """Insert a new "Component versions" table row + matching "### ..."
    Changes section for every canonical sidecar/shared-image name (see
    lib.chart.canonical_sidecar_row_names — "<values_key> - <basename>"
    for a sidecar nested under a real dependency, bare "<basename>" for
    a shared "global" image) whose VERSION (lib.chart.version_of — the
    tag with any "@sha256:..." digest suffix stripped) changed vs
    baseline but doesn't already have a row of its own. A digest-only
    re-pin with the same version is deliberately NOT enough on its own
    to add a row/section here — -upgrade.md documents version changes,
    never a digest re-pin alone (that's the images-manifest's own
    concern; see find_images_manifest_list_diff's docstring for the
    same reasoning). The sidecar/shared-image counterpart
    to lib.component_docs.add_missing_component_rows, which only ever
    covers a real Chart.yaml dependency's own row — this closes exactly
    the "sidecar/shared image ... changed vs ... but has no row" gap
    lib.docs_consistency.check_docs_consistency's own canonical_names
    loop reports.

    Always uses make_image_changes_section's own "shared image" prose/
    heading shape (chart column "-", no Helm-chart mention at all) —
    even for a sidecar nested under a real dependency — since that's the
    shape this chart's own docs actually use for every canonical sidecar
    row today (a sidecar's "chart version" is really just its owning
    dependency's, which is exactly what lib.docs_consistency's own row
    check deliberately never compares for these rows either — see its
    `actual_chart = None` for the sidecar branch). global_image_paths is
    folded into current_paths/baseline_paths so a shared global.images.*
    anchor (e.g. nginx-unprivileged, aliased by 10+ components' own
    sidecars at once) resolves to canonical_sidecar_row_names' own bare-
    basename "global" row — ONE row for the whole chart — rather than
    each aliasing component's own dependency independently qualifying
    for its OWN "<dep> - <basename>" row for the exact same image bump
    (real case: "zac - nginx-unprivileged" and "frankgateway - nginx-
    unprivileged" both showing up as separate rows for what is, via the
    shared anchor, the identical version change).

    A path with no EXACT match in baseline_paths (baseline_tag is None)
    is not immediately treated as genuinely new — see the old_app
    resolution below for the two fallback tiers tried first: lib.chart.
    baseline_tag_for_sidecar_path (this same repository elsewhere in
    baseline_values — the SAME function lib.upgradedoc.
    resolve_component_row's own sidecar branch now also uses for its
    "### ..." Changes heading, so the two can never resolve a different
    baseline version for the same path again), then, only once that
    finds nothing either, a past images-<version>.yaml manifest. Real
    case: podiumd 4.9.1 consolidated two separate postgres pins
    (keycloak-operator's own ensurePodiumdAdminUser job and openbao's
    own schemaJob) into one new shared global.images.postgres anchor —
    that exact path never existed in the baseline, but the same
    "postgres" repository already did, elsewhere in the tree.

    Returns (new_text, added_names)."""
    state = _sidecar_scan_state(text, doc_context, target_state, baseline_values)
    ctx = _SidecarRowContext(state, target_state, baseline_values, doc_context)
    added_names = []
    for name, path in sorted(state.canonical_names.items()):
        text, added = _add_sidecar_row(text, name, path, ctx)
        if added:
            added_names.append(name)
    return text, added_names


def build_changes_section_for_row(row: dict, ident: tuple, deps: list, target: str):
    """The "### ..." Changes section for a single table row + its already-
    resolved identity (see resolve_component_identity) — make_changes_
    section for a real Chart.yaml dependency, make_image_changes_section
    for a canonical sidecar/shared-image. Always built from the row's OWN
    app/chart cells verbatim, never recomputed from actual_app_version or
    a git baseline — the generated section can never disagree with what
    the row right above it already visibly says. A row whose own app
    cell has no resolvable target version at all (e.g. "-") gets a short
    TODO-stub section instead of guessing at prose, the same fallback
    add_missing_component_rows uses for the same reason. None if `ident`
    names a "dep" identity whose Chart.yaml dependency can't be found
    (shouldn't happen — ident was itself resolved against `deps`)."""
    kind, value = ident
    if row["app"] is None:
        chart_bit = row["chart"] or row["chart_source"] or "-"
        return (
            f"### {row['name']} {chart_bit}\n\n"
            f"TODO: describe this component's changes — its app version could not be "
            f"resolved from the table row.\n\n"
        )
    if kind == "dep":
        dep = dep_for_values_key(deps, value)
        if dep is None:
            return None
        # version_paths_for wins outright when registered — a component
        # listed there (e.g. eck-stack's bare "...version:" fields, the
        # ECK operator's own CRD convention) has no "{repository, tag}"
        # block at all, so falling back to image_paths_for's generic
        # DEFAULT_IMAGE_PATHS guess (the ordinary "<key>.image.tag"
        # shape) would point the bullet at a path that doesn't exist.
        version_paths = version_paths_for(dep["name"])
        image_paths = [] if version_paths else image_paths_for(dep["name"])
        identity = ComponentIdentity(row["name"], dep["name"], value)
        change = VersionChange(
            row["app_source"] or row["app"],
            row["app"],
            row["chart_source"] or row["chart"] or str(dep["version"]),
            row["chart"] or str(dep["version"]),
        )
        return make_changes_section(identity, target, change, image_paths, version_paths)
    dotted_path = ".".join(value) + ".tag"
    return make_image_changes_section(
        row["name"],
        target,
        row["app_source"] or row["app"],
        row["app"],
        [(dotted_path, row["app_source"] or row["app"])],
    )


def add_missing_changes_sections(text: str, deps: list, target_values: dict, target: str, canonical_names: dict):
    """Insert a "### ..." Changes section (see build_changes_section_for_
    row) for every "Component versions" table row that already exists
    but has no matching section of its own yet (see lib.upgradedoc.
    find_changes_row_correspondence_gaps's own rows_without_heading, the
    same gap lib.docs_consistency.check_docs_consistency's "table row
    ... has no matching "### ..." section" finding reports). A row
    resolving to neither a real dependency nor a canonical sidecar is
    skipped (already reported elsewhere as wrong/stale — see find_
    wrong_or_duplicate_dependency_claims). Returns (new_text,
    added_names)."""
    rows = parse_upgrade_doc_rows(text)
    headings = [b["heading"] for b in parse_upgrade_doc_changes_blocks(text)]
    rows_without_heading, _ = find_changes_row_correspondence_gaps(rows, headings, deps, canonical_names)
    if not rows_without_heading:
        return text, []
    missing = set(rows_without_heading)

    added_names = []
    for row in rows:
        if row["name"] not in missing:
            continue
        ident = resolve_component_identity(row["name"], deps, canonical_names)
        if ident is None:
            continue
        section = build_changes_section_for_row(row, ident, deps, target)
        if section is None:
            continue
        text = insert_changes_section(text, section, row["name"], OrderingContext(deps, target_values, canonical_names))
        added_names.append(row["name"])

    return text, added_names


def _remove_changes_block_by_exact_heading(text: str, heading: str):
    """remove_changes_section, but matched by EXACT heading text instead
    of component identity — used for replacing a specific,
    already-identified stale heading (see update_stale_app_version_
    headings), where a fuzzy match risks hitting the wrong block if some
    OTHER heading happens to share words with this one. Returns
    (new_text, removed)."""
    blocks = parse_upgrade_doc_changes_blocks(text)
    block = next((b for b in blocks if b["heading"] == heading), None)
    return remove_changes_block(text, block)


@dataclass
class _StaleHeadingContext:
    """doc_context (chart_dir/target) + ordering (deps/target_values/
    canonical_names), bundled since every one of update_stale_app_
    version_headings' own helpers needs some subset of both."""

    doc_context: DocContext
    ordering: OrderingContext


def _rows_by_identity(text: str, ctx: _StaleHeadingContext):
    """{identity: row} for every "Component versions" table row in
    `text` that resolves to a real identity (see resolve_component_
    identity) — update_stale_app_version_headings' own way of looking up
    a stale heading's matching row. Split out purely to keep its own
    local-variable count down."""
    rows_by_identity = {}
    for row in parse_upgrade_doc_rows(text):
        ident = resolve_component_identity(row["name"], ctx.ordering.deps, ctx.ordering.canonical_names)
        if ident is not None:
            rows_by_identity[ident] = row
    return rows_by_identity


def _stale_app_version_headings(text: str, ctx: _StaleHeadingContext):
    """[(heading, ident), ...] for every "### ..." Changes heading in
    `text` that's missing its own primary-image app version (see
    changes_heading_has_app_version) AND resolves to exactly one real
    "dep" identity (never a sidecar — see update_stale_app_version_
    headings' own docstring for why). Split out purely to keep its own
    local-variable count down."""
    stale = []
    for heading in [b["heading"] for b in parse_upgrade_doc_changes_blocks(text)]:
        if changes_heading_has_app_version(heading):
            continue
        idents = changes_heading_identities(heading, ctx.ordering.deps, ctx.ordering.canonical_names)
        if len(idents) != 1:
            continue
        ident = next(iter(idents))
        if ident[0] != "dep":
            continue
        stale.append((heading, ident))
    return stale


def _rewrite_stale_heading(
    text: str, heading: str, ident: tuple[str, ...], rows_by_identity: dict, ctx: _StaleHeadingContext
):
    """Rewrites `heading`'s own "### ..." block in `text` from its
    matching table row (see build_changes_section_for_row), if its
    actual_app_version resolves at all — (new_text, True) if rewritten,
    (text, False) unchanged otherwise (unresolvable dep/app version, no
    matching row, or the heading couldn't be found to remove). Split out
    of update_stale_app_version_headings' own per-heading loop purely to
    keep ITS own local-variable count down."""
    _, values_key = ident
    dep = dep_for_values_key(ctx.ordering.deps, values_key)
    if dep is None:
        return text, False
    actual_app = actual_app_version(
        ctx.ordering.values, values_key, dep["name"], chart_dir=ctx.doc_context.chart_dir, dep=dep
    )
    if not actual_app:
        return text, False
    row = rows_by_identity.get(ident)
    if row is None:
        return text, False
    section = build_changes_section_for_row(row, ident, ctx.ordering.deps, ctx.doc_context.target)
    if section is None:
        return text, False

    text, removed = _remove_changes_block_by_exact_heading(text, heading)
    if not removed:
        return text, False
    text = insert_changes_section(text, section, row["name"], ctx.ordering)
    return text, True


def update_stale_app_version_headings(text: str, doc_context: DocContext, ordering: OrderingContext):
    """Regenerate a "### ..." Changes section whose own heading is
    missing the primary-image app version (see lib.upgradedoc.changes_
    heading_has_app_version) for a component that DOES have one
    resolvable now (real case: "### openbao 0.28.4" — add_missing_
    component_rows' own chart-only TODO-stub shape, written back before
    actual_app_version could resolve anything — fixed later by
    registering openbao in COMPONENT_IMAGE_PATHS/adding the vendored-
    chart appVersion fallback, but the already-written heading never
    gets touched just because resolution got smarter). Built the exact
    same way add_missing_changes_sections builds a genuinely missing
    section (see build_changes_section_for_row), from that component's
    OWN table row — the stale heading's entire old body is discarded
    (there's no reliable way to tell which part of its own prose is
    still accurate once the heading itself was already wrong, same
    reasoning as a freshly-added section).

    Only ever touches a heading naming EXACTLY ONE real "dep" component
    (never a sidecar — a canonical sidecar heading is only ever written
    once its own tag is already known, so this gap doesn't apply to
    it — see canonical_sidecar_row_names) whose actual_app_version DOES
    resolve; a heading that's ambiguous, orphaned, or genuinely has no
    resolvable app version yet is left exactly as-is, matching the same
    finding lib.docs_consistency.check_docs_consistency's own "is
    missing the primary-image app version" check reports. Returns
    (new_text, updated_headings) — updated_headings is the ORIGINAL
    (pre-fix) heading text for every section actually rewritten."""
    ctx = _StaleHeadingContext(doc_context, ordering)
    rows_by_identity = _rows_by_identity(text, ctx)
    updated_headings = []
    for heading, ident in _stale_app_version_headings(text, ctx):
        text, updated = _rewrite_stale_heading(text, heading, ident, rows_by_identity, ctx)
        if updated:
            updated_headings.append(heading)
    return text, updated_headings


def resolve_basename_baseline_version(baseline_values: dict | None, full_paths: list):
    """The single version every one of this basename's touched pins
    actually started at in baseline_values (the true git-resolved release
    baseline, see lib.component_docs.load_baseline_values) — None if they
    didn't all agree, or any of them isn't found there at all. A basename
    bump always targets every matching pin to the same new_version (see
    lib.image.version.update_image_version), so a uniform baseline is the
    only case update_docs_shared_image can cleanly treat as "back to
    baseline" or use as the one true "old" for a bump reconsidered more
    than once in the same release cycle (baseline -> 3, then baseline ->
    2, rather than each documenting the other's intermediate hop).
    `full_paths` is [(dotted "...tag" path, old_version), ...] as returned
    by group_changes_by_component."""
    versions = set()
    for dotted_path, _old_version in full_paths:
        tag = get_path(baseline_values, dotted_path)
        if not isinstance(tag, str) or not tag:
            return None
        versions.add(tag.split("@", 1)[0])
    return next(iter(versions)) if len(versions) == 1 else None


@dataclass
class ImageBump:
    """A shared image basename's own version-bump facts, bundled since
    update_image_manifest/remove_image_manifest_entry both need all
    four to locate and rewrite the same images-manifest entry."""

    basename: str
    repository: str
    old_version: str | None
    new_version: str
    digest: str


def _find_manifest_entry(lines: list[str], repository: str):
    """(entry_line, block_end) for the first images-manifest "- name:
    ..." entry block whose own "url:" (host-stripped) matches
    `repository` — (None, None) if none does. Shared by update_image_
    manifest/remove_image_manifest_entry, which both need to locate the
    SAME entry before doing two different things to it."""
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    url_re = re.compile(r"^\s*url:\s*(\S+)\s*$")
    for idx in entry_line_indices:
        block_end = len(lines)
        for j in range(idx + 1, len(lines)):
            if re.match(r"^-\s*name:", lines[j]) or not lines[j].strip():
                block_end = j
                break
        for j in range(idx, block_end):
            m = url_re.match(lines[j])
            if m and m.group(1).rstrip("/").endswith(repository):
                return idx, block_end
    return None, None


def _update_manifest_entry_scalars(
    lines: list[str], entry_line: int | None, block_end: int | None, new_version: str, digest: str
):
    """Rewrites lines[entry_line:block_end]'s own "version:"/"digest:"
    scalars to new_version/digest in place. Returns True if entry_line
    is a real match (something was updated), False (a no-op) if
    entry_line is None. Shared by update_image_manifest/remove_image_
    manifest_entry — their own source-comment handling differs
    (rewritten vs deleted) and stays separate in each."""
    if entry_line is None or block_end is None:
        return False
    entry_updated = False
    for i in range(entry_line, block_end):
        m = re.match(r"^\s*(version|digest):", lines[i])
        if not m:
            continue
        new_value = new_version if m.group(1) == "version" else digest
        lines[i] = replace_scalar_value(lines[i], new_value)
        entry_updated = True
    return entry_updated


def _update_manifest_changes_header(lines: list[str], bump: ImageBump, ordering: OrderingContext):
    """Insert or update `bump.basename`'s own "#   N. ..." changes-
    header item in `lines` (the images-manifest's own "# Changes:"/"#
    <N> changes:" list) — None (nothing found to touch) if the manifest
    has no header at all, else "updated" (an existing item for this
    basename was found and rewritten) or "added" (a brand-new item was
    inserted, in `ordering`'s own values.yaml order via component_
    order_key when `ordering.values` is given, else appended at the
    end). Split out of update_image_manifest purely to keep its own
    local-variable count down."""
    # find_images_manifest_changes_header (not a bare CHANGES_HEADER_RE
    # scan) — the real, hand-curated images-manifest header is the plain
    # "# Changes:" form (no count word at all), which CHANGES_HEADER_RE
    # alone never recognizes. Silently finding no header at all meant
    # this whole block — and so the header-list item — was skipped
    # outright for every MULTIPLE-scope basename bump against a real
    # manifest, never even reaching the "no existing entry" case a human
    # could act on.
    header_idx, _header_has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return None

    item_indices, block_end = images_manifest_changes_block(lines, header_idx)
    match_idx = find_changes_item(lines, item_indices, bump.basename)
    item_text = f"{bump.basename} {image_manifest_version_text(bump.old_version, bump.new_version)}."

    if match_idx is not None:
        m = match_located_line(CHANGES_ITEM_RE, lines[match_idx])
        lines[match_idx] = f"#   {m.group('num')}. {item_text}\n"
        return "updated"
    if ordering.values is not None:
        # insert_images_manifest_header_item never rewrites the header's
        # own wording into a counted form ("# Three changes:") — same
        # bare "# Changes:" convention this function already matched
        # before this fix.
        key_order = values_key_order(ordering.values)
        new_key = component_order_key(
            bump.basename, ordering.deps, key_order, ordering.canonical_names, ordering.values
        )
        insert_images_manifest_header_item(lines, ordering.deps, key_order, new_key, item_text)
        return "added"
    # No ordering context given at all — fall back to the previous
    # always-append behavior rather than guessing.
    new_num = len(item_indices) + 1
    insert_at = block_end if item_indices else header_idx + 1
    lines.insert(insert_at, f"#   {new_num}. {item_text}\n")
    return "added"


def update_image_manifest(images_path: Path, bump: ImageBump, ordering: OrderingContext | None = None):
    """Update the "# <N> changes:" header list and the images-manifest
    entry for a shared image basename bump — keyed by `bump.repository`
    (an entry's "url:" resolving to it, host-stripped same as the
    "name:" convention docs/images/acr-mirror-naming.md documents), not
    a values-tree path. Returns (changes_action, entry_updated) —
    entry_updated is False (not an error) when no existing entry's
    "url:" matches this repository; the caller reports the correct
    name/url to add by hand instead, same convention as
    lib.component_docs.update_images_manifest's own missing_entries.

    `ordering` (see _update_manifest_changes_header) positions a
    BRAND-NEW header item at this basename's own real values.yaml order
    slot (lib.upgradedoc.component_order_key — the SAME convention
    update-image-version's own update_docs_shared_image already uses to
    position this exact basename's "Component versions" table row/
    "### ..." Changes section in the upgrade doc, via ordering.
    canonical_names' "global" shared-image fallback) — real bug this
    fixes: this function used to always APPEND a new item at the very
    end of the existing list regardless of where it really belongs,
    while lib.component_docs.update_images_manifest (the sibling
    function for a real Chart.yaml dependency's own bump) already
    positioned ITS new items by values.yaml order — the two disagreeing
    on ordering convention meant a component bumped through THIS
    function (e.g. a shared "global.images" anchor) could land its
    header item in a position that contradicted another component's own
    item bumped through the OTHER function in the very same run,
    scrambling the header list's order relative to the entries below it
    even though neither individual insert was wrong on its own
    (confirmed live: images-4.9.1.yaml's own "redis 8.0 (new)." item,
    always appended last here, ended up AFTER "mi ...unchanged."'s own
    values.yaml-order-positioned item even though redis's real entry
    sits earlier). Omit `ordering` entirely only where no real ordering
    context is available at all — falls back to appending at the end,
    same as before, never crashes."""
    ordering = ordering or OrderingContext([], None)
    original_text = images_path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)

    changes_action = _update_manifest_changes_header(lines, bump, ordering)

    entry_line, block_end2 = _find_manifest_entry(lines, bump.repository)
    entry_updated = _update_manifest_entry_scalars(lines, entry_line, block_end2, bump.new_version, bump.digest)
    if entry_line is not None:
        comment_idx = find_preceding_comment_line(lines, entry_line)
        if comment_idx is not None:
            current_source = extract_source_version(lines[comment_idx])
            if current_source:
                lines[comment_idx] = replace_version_pair(lines[comment_idx], current_source, bump.new_version)

    new_text = "".join(lines)
    if new_text != original_text:
        images_path.write_text(new_text, encoding="utf-8")
    return changes_action, entry_updated


def _remove_manifest_changes_header_item(lines: list[str], basename: str):
    """Deletes `basename`'s own "#   N. ..." changes-header item from
    `lines` (renumbering the ones after it) — returns "removed", or None
    if there was no header, or no matching item, to touch. Split out of
    remove_image_manifest_entry purely to keep its own local-variable
    count down. Never rewrites the header's own wording — same as
    update_image_manifest."""
    header_idx, _header_has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return None
    item_indices, _block_end = images_manifest_changes_block(lines, header_idx)
    match_idx = find_changes_item(lines, item_indices, basename)
    if match_idx is None:
        return None

    remove_changes_item(lines, item_indices, match_idx)
    return "removed"


def remove_image_manifest_entry(images_path: Path, basename: str, repository: str, new_version: str, digest: str):
    """Counterpart to update_image_manifest for a shared-image bump that
    nets out to no change from baseline at all: still writes the matching
    entry's final version/digest, but removes the "changes:" list item
    and the entry's own preceding source comment instead of updating
    them, since there is no longer anything to document. Returns
    (changes_action, entry_updated) — same shape as update_image_manifest."""
    original_text = images_path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)

    changes_action = _remove_manifest_changes_header_item(lines, basename)

    entry_line, block_end2 = _find_manifest_entry(lines, repository)
    entry_updated = _update_manifest_entry_scalars(lines, entry_line, block_end2, new_version, digest)
    if entry_line is not None:
        comment_idx = find_preceding_comment_line(lines, entry_line)
        if comment_idx is not None and extract_source_version(lines[comment_idx]):
            del lines[comment_idx]

    new_text = "".join(lines)
    if new_text != original_text:
        images_path.write_text(new_text, encoding="utf-8")
    return changes_action, entry_updated


IMAGES_BASELINE_HEADER = (
    "# Baseline images — the single, complete strip-registry mirror manifest.\n"
    "#\n"
    "# This is a full, CURRENT snapshot of every image PodiumD pulls right now —\n"
    "# every component's own primary image, every sidecar, every MULTIPLE/global-\n"
    "# anchored shared image — under the strip-registry mirror convention:\n"
    "#   name = strip_registry(url): upstream url with the registry host removed,\n"
    "#   full <namespace>/<repo> path kept.\n"
    "# Versions are the tags currently pinned in charts/podiumd/values.yaml (or the\n"
    '# owning subchart). Digests are the tag\'s own embedded "@sha256:..." suffix\n'
    "# when it has one, else resolved live against the source registry\n"
    "# (Docker-Content-Digest / manifest_digest).\n"
    "#\n"
    "# Fully regenerated by fix-doc-consistency, update-component-version and\n"
    "# update-image-version on every run (lib.image.docs.\n"
    "# regenerate_images_baseline_manifest) — always a complete, wholesale\n"
    "# snapshot, never incremental patching: no hand-maintained gap-fillers, no\n"
    '# "NOT INCLUDED" exclusion notes, no stale dual-version entries. Editing this\n'
    "# file by hand is pointless — the next run overwrites it entirely.\n"
)


@dataclass
class _BaselineManifestContext:
    """chart_dir/deps/values + the key_order/sibling_fields derived from
    them, bundled since regenerate_images_baseline_manifest's own per-
    repo resolution helper needs all five together, computed once up
    front rather than per repository."""

    chart_dir: Path
    deps: list
    values: dict
    key_order: list
    sibling_fields: dict


def _current_image_paths(chart_dir: Path, deps: list, values: dict, rendered_paths: set):
    """Every currently-pinned image path in the chart (find_all_image_
    and_version_paths + global_image_paths), PLUS every genuinely-live-
    but-unpinned vendored-subchart-default image find_unresolved_
    subchart_images finds (see regenerate_images_baseline_manifest's own
    docstring for why). Split out purely to keep ITS own local-variable
    count down."""
    current_paths = dict(find_all_image_and_version_paths(values, deps))
    current_paths.update(global_image_paths(values))
    for scope_key, subpath, tag, _already_pinned in find_unresolved_subchart_images(
        chart_dir, deps, values, rendered_paths
    ):
        current_paths.setdefault((scope_key, *subpath.split(".")), tag)
    return current_paths


# (sort_key, repo, full_repo, new_version, digest) -- see _resolve_baseline_entry.
BaselineEntry = tuple[tuple[int, ...], str, str, str, str | None]


def _resolve_baseline_entry(
    ctx: _BaselineManifestContext, current_paths: dict, repo: str, group_paths: list
) -> BaselineEntry | None:
    """(sort_key, repo, full_repo, new_version, digest) for one
    repository group's own baseline entry, or None if it should be
    skipped (unresolvable full_repo, or unresolvable digest) — the
    caller appends `repo` to its own skipped list in that case. Split
    out of regenerate_images_baseline_manifest's own per-repo loop
    purely to keep ITS own local-variable count down."""
    representative = repo_group_representative(group_paths, ctx.deps)
    tag = current_paths[representative]
    full_repo = full_repository_for_path(ctx.chart_dir, ctx.deps, ctx.values, representative)
    if full_repo is None:
        return None

    pinned = resolved_digest_pin(ctx.values, representative, tag, ctx.sibling_fields)
    if pinned is not None:
        new_version, digest = pinned.split("@", 1)
    else:
        new_version = tag.split("@", 1)[0]
        host, repo_path = parse_repo(full_repo)
        exists, digest = registry_tag_exists(host, repo_path, new_version)
        if not exists or not digest:
            return None

    sort_key = images_manifest_entry_order_key(representative, ctx.deps, ctx.key_order, ctx.values)
    return sort_key, repo, full_repo, new_version, digest


def _resolve_baseline_entries(ctx: _BaselineManifestContext, current_paths: dict, repo_groups: dict):
    """(resolved, skipped) for every repository group in repo_groups —
    resolved is [(sort_key, repo, full_repo, new_version, digest), ...]
    sorted by sort_key, skipped is [repo, ...] for every group _resolve_
    baseline_entry couldn't resolve. Split out of regenerate_images_
    baseline_manifest purely to keep its own local-variable count
    down."""
    resolved: list[BaselineEntry] = []
    skipped: list[str] = []
    for repo, group_paths in repo_groups.items():
        entry = _resolve_baseline_entry(ctx, current_paths, repo, group_paths)
        if entry is None:
            skipped.append(repo)
        else:
            resolved.append(entry)
    resolved.sort(key=lambda e: e[0])
    return resolved, skipped


def _render_baseline_manifest_lines(resolved: list):
    """The full images-baseline.yaml text for `resolved` (see _resolve_
    baseline_entries) — the fixed IMAGES_BASELINE_HEADER followed by one
    "- name/url/version/digest" block per entry, exactly one trailing
    newline (no blank line right before EOF)."""
    lines = [IMAGES_BASELINE_HEADER, "\n"]
    for _sort_key, repo, full_repo, new_version, digest in resolved:
        lines.append(f"- name: {repo}\n")
        lines.append(f"  url: {full_repo}\n")
        lines.append(f'  version: "{new_version}"\n')
        lines.append(f'  digest: "{digest}"\n')
        lines.append("\n")
    text = "".join(lines)
    # A blank line after every entry (including the last) leaves the
    # file ending in "...\n\n" — one syntactic blank line before EOF.
    # Collapsed down to a single trailing newline, the same "exactly one
    # final newline, never a blank line right before EOF" convention
    # collapse_multiple_blank_lines already enforces for the three
    # .md docs this script manages.
    if text.endswith("\n\n"):
        text = text[:-1]
    return text


def regenerate_images_baseline_manifest(
    chart_dir: Path, deps: list, values: dict, images_baseline_path: Path, rendered_paths: set
):
    """Overwrite docs/images/images-baseline.yaml WHOLESALE with a full,
    CURRENT snapshot of every image pinned anywhere in the chart right
    now — every component's own primary image, every sidecar, every
    MULTIPLE/global-anchored shared image (find_all_image_and_version_
    paths(values, deps) + global_image_paths(values), the SAME
    enumeration images-<target>.yaml's own diffing already uses, just
    never filtered down to "changed since baseline" — every path,
    always) PLUS every image find_unresolved_subchart_images(chart_dir,
    rendered_paths) finds: a genuinely-live image defined only in a
    vendored dependency's own default values.yaml, with no podiumd
    override at all (e.g. eck-operator's own top-level "image:", null
    tag, resolved to the dependency's own Chart.yaml appVersion — see
    lib.chart.resolve_subchart_default) — otherwise invisible to this
    regeneration the same way it's invisible to check_digest_pinning,
    since neither one ever looks past podiumd's own values.yaml on its
    own. `rendered_paths` (see lib.render_scope.rendered_chart_paths, a
    real `helm template` render) gates these exactly as check_subchart_
    image_visibility's own findings are gated — a dependency (or one of
    ITS OWN nested dependencies) disabled via condition:/tags: never
    contributes an entry here, e.g. openinwoner's own bundled nested
    eck-operator (globally disabled via tags:) or zaakbrug's own
    condition-disabled "staging" block.

    One entry per distinct repository (paths_by_repository/
    repo_group_representative's own dedup convention — a shared anchor
    like global.images.nginx, aliased by several components, collapses
    to ONE entry, same as images-<target>.yaml already does), sorted by
    images_manifest_entry_order_key — the exact same sort key images-
    <target>.yaml's own entries already use.

    Never incremental: no gap-fillers, no "NOT INCLUDED" exclusion
    notes, no stale dual-version entries (e.g. frankgateway's old
    pre-SemVer "104" alongside its current pin) — a fresh, complete
    regeneration every time this runs, replacing whatever was there
    before entirely.

    `name` is the stripped repo (paths_by_repository's own group key —
    already in the correct strip_registry(url) form, no host); `url` is
    the REAL, fully host-qualified repository (lib.chart.full_
    repository_for_path — the same helper the "url:" host-qualification
    fix added, reused here so the two can never drift on what a
    repository's real url is); `version`/`digest` come from the pin's
    own embedded "@sha256:..." suffix (lib.chart.resolved_digest_pin)
    when it has one, else a live registry lookup (lib.registry.
    registry_tag_exists) — matching the file's own header comment
    ("Digests are ... resolved live against the source registry").

    Repository resolution itself (paths_by_repository/full_repository_
    for_path) stays offline-only (allow_pull=False, their own default) —
    a real chart always has every dependency already vendored, so this
    never needs a fresh `helm pull`; only the DIGEST lookup, when
    needed, ever goes over the network. Never allow_pull=True here: a
    synthetic/test dependency with no real Helm repository behind it
    would otherwise make every run of this attempt one regardless.

    Returns (written, skipped, changed) — written is the number of
    entries in the freshly-computed snapshot (whether or not it was
    actually written to disk this run); skipped is [repo, ...] for
    every repository group whose full url couldn't be resolved, or
    whose digest couldn't be resolved at all (no embedded digest AND
    the live registry lookup failed) — never silently dropped without
    a trace, same "report it, don't guess" convention every other
    entry-writer here uses; changed is True only when the freshly-
    computed content actually differs from what's already on disk (or
    the file doesn't exist yet) — write_text is only ever called in
    that case, the same "no spurious write, no spurious mtime/git-diff
    churn" gating fix-doc-consistency's own main() already applies to
    every OTHER doc it manages (upgrade.md/images-<target>.yaml/
    values-deltas.md's own write_needed-style checks) — this was the
    one exception, confirmed live: every run rewrote (and reported on)
    this file regardless of whether anything about it actually
    changed."""
    current_paths = _current_image_paths(chart_dir, deps, values, rendered_paths)
    repo_groups = paths_by_repository(chart_dir, deps, values, current_paths.keys())
    ctx = _BaselineManifestContext(
        chart_dir, deps, values, values_key_order(values), digest_pinning_exceptions(chart_dir)
    )

    resolved, skipped = _resolve_baseline_entries(ctx, current_paths, repo_groups)
    text = _render_baseline_manifest_lines(resolved)
    current_text = images_baseline_path.read_text(encoding="utf-8") if images_baseline_path.is_file() else None
    changed = text != current_text
    if changed:
        images_baseline_path.write_text(text, encoding="utf-8")
    return len(resolved), skipped, changed
