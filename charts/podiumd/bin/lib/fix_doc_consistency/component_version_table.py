"""fix-doc-consistency's own "Component versions" table and Changes/
values-deltas heading app-version repair, split out of that script for
pylint's too-many-lines check — the last of its 6 planned groups."""

import re

from dataclasses import dataclass

from lib.chart.historical_baselines import historical_app_version_for_path
from lib.chart.pull_and_subchart_resolution import global_image_paths
from lib.chart.registered_paths import image_paths_for
from lib.chart.repo_and_path_resolution import canonical_sidecar_row_names
from lib.upgradedoc.app_version_and_image_paths import find_image_tag_paths
from lib.upgradedoc.images_manifest_ordering import header_name_segment
from lib.upgradedoc.resolve_component_row import ResolutionContext
from lib.upgradedoc.resolve_component_row import changes_heading_has_app_version
from lib.upgradedoc.resolve_component_row import resolve_component_row
from lib.upgradedoc.sorting_and_ordering import parse_upgrade_doc_changes_blocks
from lib.upgradedoc.sorting_and_ordering import parse_values_delta_sections
from lib.upgradedoc.string_and_parsing_basics import changes_heading_identities
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows
from lib.upgradedoc.version_cells_and_key_changes import canonical_version_cell
from lib.upgradedoc.version_cells_and_key_changes import component_version_cell


@dataclass
class HeadingFixInputs:
    """resolved_by_values_key/canonical_names/blocks/heading_marker —
    _fix_heading_app_versions' own four caller-varying inputs, bundled
    since fix_changes_heading_app_versions and fix_values_delta_
    heading_app_versions each build all four together and pass them
    through unchanged (only their own VALUES differ — "###" vs "##"
    blocks/marker — never their shape)."""

    resolved_by_values_key: dict
    canonical_names: dict
    blocks: list
    heading_marker: str


def _dep_old_app_for_new_dependency(resolution: ResolutionContext, resolved: dict):
    """The APP cell's own "old" version for a Chart.yaml dependency with
    NO baseline value at all (resolved["baseline_resolved"] is False,
    resolved["dep"] is not None, resolved["target_app"] is not None) —
    before concluding "genuinely new", checks whether this repository
    already appears in any of this chart's own PAST images-<version>.yaml
    manifests (real, already-committed per-release documents, never a
    fallback to the removed images-baseline.yaml side-file). None when
    nothing is found there either (a real "(new)" component) — shared by
    fix_component_version_table's own row loop and fix_changes_heading_
    app_versions (see its own docstring) so the two can never disagree
    on what a brand-new dependency's own "old" app version is."""
    if resolved["dep"] is None or resolved["target_app"] is None:
        return None
    old_app = None
    for path in image_paths_for(resolved["dep"]["name"], resolution.chart_dir):
        old_app = historical_app_version_for_path(
            resolution.chart_dir,
            resolution.target.deps,
            resolution.target.values,
            (resolved["values_key"], *tuple(path.split("."))),
            resolution.upgrade_docs_baseline,
        )
        if old_app is not None:
            break
    return old_app


def _new_dependency_row_update(lines: list[str], row: dict, resolved: dict, resolution: ResolutionContext):
    """The baseline_resolved=False row-rewrite mechanics for
    fix_component_version_table's own row loop — a genuinely brand-new
    component (or a sidecar whose current tag can't even be resolved,
    see the caller's own guard before this is ever invoked) gets
    "<target> (new)" cells instead of a source/target transition.
    Returns (row_name, app_cell, chart_cell) when the row text actually
    changed, None otherwise — the caller decides what to do with either
    outcome."""
    actual_target_chart, actual_target_app = resolved["target_chart"], resolved["target_app"]

    # A brand-new Chart.yaml dependency (resolved["dep"] not None) with
    # no baseline value at all — before concluding "genuinely new" for
    # the APP cell (the CHART cell still correctly reads "(new)"
    # regardless — that dependency line really is new), check whether
    # this repository already appears in any of this chart's own PAST
    # images-<version>.yaml manifests (real, already-committed
    # per-release documents, not the removed images-baseline.yaml
    # side-file).
    old_app_for_cell = _dep_old_app_for_new_dependency(resolution, resolved)

    row_changed = False
    line = lines[row["line_index"]]
    cells = [c.strip() for c in line.strip().strip("|").split("|")]

    if actual_target_app is not None:
        new_app_cell = component_version_cell(old_app_for_cell, actual_target_app)
        if cells[1] != new_app_cell:
            cells[1] = new_app_cell
            row_changed = True
    if actual_target_chart is not None:
        new_chart_cell = component_version_cell(None, actual_target_chart)
        if cells[2] != new_chart_cell:
            cells[2] = new_chart_cell
            row_changed = True
    elif cells[2] != "-":
        # A native component or a sidecar has no chart of its own
        # (resolve_component_row's target_chart is None), so its chart
        # cell is "-", the value check_docs_consistency expects.
        cells[2] = "-"
        row_changed = True

    if not row_changed:
        return None
    suffix = "\n" if line.endswith("\n") else ""
    lines[row["line_index"]] = "| " + " | ".join(cells) + " |" + suffix
    return (row["name"], cells[1], cells[2])


def _existing_row_update(lines: list[str], row: dict, resolved: dict):
    """The baseline_resolved=True row-rewrite mechanics for
    fix_component_version_table's own row loop — a component that
    existed at both the baseline and target ref gets a real
    source-to-target transition cell. Returns (row_name, app_cell,
    chart_cell) when the row text actually changed, None otherwise."""
    actual_target_chart, actual_target_app = resolved["target_chart"], resolved["target_app"]
    actual_baseline_chart, actual_baseline_app = resolved["baseline_chart"], resolved["baseline_app"]

    row_changed = False
    line = lines[row["line_index"]]
    cells = [c.strip() for c in line.strip().strip("|").split("|")]

    if actual_target_app is not None:
        # component_version_cell, not canonical_version_cell directly:
        # baseline_resolved=True here only means the dependency's own
        # Chart.yaml LINE existed at the baseline ref — its own APP
        # VERSION can still fail to resolve there (real bug, real case:
        # mi — the Chart.yaml dependency line predates this release, but
        # its own "image:" block was only pinned this hop, so actual_
        # baseline_app is None even though baseline_resolved is True).
        # component_version_cell already renders "(new)" for that case,
        # the exact same wording fix_changes_heading_app_versions' own
        # heading correction already uses — before this fix, the row
        # silently kept its stale, wrong "<old> → <new>" transition
        # forever, disagreeing with an already-correct heading right
        # below it. Also compared as the full rendered CELL TEXT, not
        # just the two numeric endpoints (row["app_source"]/row["app"])
        # — a row whose numbers already match but whose "(new)"/
        # "(unchanged)" annotation is stale must still be corrected;
        # comparing only the numbers would silently leave a wrong
        # annotation in place forever, since they'd already "match".
        new_app_cell = component_version_cell(actual_baseline_app, actual_target_app)
        if cells[1] != new_app_cell:
            cells[1] = new_app_cell
            row_changed = True

    if actual_target_chart is not None and actual_baseline_chart is not None:
        new_chart_cell = canonical_version_cell(actual_baseline_chart, actual_target_chart)
        if cells[2] != new_chart_cell:
            cells[2] = new_chart_cell
            row_changed = True
    elif actual_target_chart is None and cells[2] != "-":
        # See the identical branch in _new_dependency_row_update.
        cells[2] = "-"
        row_changed = True

    if not row_changed:
        return None
    suffix = "\n" if line.endswith("\n") else ""
    lines[row["line_index"]] = "| " + " | ".join(cells) + " |" + suffix
    return (row["name"], cells[1], cells[2])


def fix_component_version_table(text: str, resolution: ResolutionContext):
    """Rewrite each "Component versions" table row's App/Helm-chart cells to
    the actual baseline (source) and target versions found in git/Chart.yaml/
    values.yaml. A row is only rewritten when both its source and target are
    independently verifiable — EXCEPT a component that genuinely doesn't
    exist at the baseline ref yet (a brand-new dependency, or a sidecar
    whose own tag isn't pinned there), which gets "<target> (new)" cells
    instead (see lib.upgradedoc.component_version_cell) rather than being
    left untouched; a row whose CURRENT version can't be resolved either
    is left as-is and reported, same as before.

    A row using the canonical sidecar/shared-image name (see
    lib.chart.canonical_sidecar_row_names — "<values_key> - <basename>" or
    bare "<basename>") is corrected against ITS OWN resolved tag instead of
    match_dependency's real-dependency lookup — that fuzzy match would
    otherwise collide with an unrelated real dependency sharing the row's
    leading word (e.g. "redis-operator - redis" silently corrected against
    the real "redis-operator" dependency's own actual chart/app version,
    which happened here before this guard existed). Its Helm-chart cell is
    set to "-", same as add_missing_sidecar_rows writes, since a sidecar
    has no Helm chart version of its own. `resolution` is a
    ResolutionContext. Returns (new_text, changed_rows, unmatched_names,
    unresolved_names)."""
    lines = text.splitlines(keepends=True)
    rows = parse_upgrade_doc_rows(text)
    changed_rows, unmatched_names, unresolved_names = [], [], []

    current_paths = dict(find_image_tag_paths(resolution.target.values))
    current_paths.update(global_image_paths(resolution.target.values))
    canonical_names = canonical_sidecar_row_names(
        resolution.chart_dir, resolution.target.deps, resolution.target.values, current_paths.keys()
    )

    for row in rows:
        # resolve_component_row is shared with lib.docs_consistency's own
        # row-checker (check_docs_consistency) — see its docstring for why
        # (a checker/fixer that resolve a row two different ways can
        # silently drift apart on what "correct" even means).
        resolved = resolve_component_row(row["name"], canonical_names, resolution)
        if resolved["kind"] == "unmatched":
            # A row shaped like the canonical sidecar form ("<key> -
            # <basename>") with no resolvable repository (e.g. "kiss -
            # podiumd-adapter", commented out in real life) is reported as
            # unresolved rather than unmatched — never fall through to
            # match_dependency and get "corrected" against an unrelated
            # real dependency's own actual version just because it shares
            # a leading word.
            if " - " in row["name"]:
                unresolved_names.append(row["name"])
            else:
                unmatched_names.append(row["name"])
            continue

        if resolved["baseline_resolved"] is None:
            unresolved_names.append(row["name"])
            continue

        if resolved["baseline_resolved"] is False:
            # A dependency's own target chart/app resolve independently of
            # the baseline entirely, so False here unambiguously means "no
            # such dependency at the baseline ref yet" — brand new. A
            # sidecar's False also covers "the CURRENT tag itself couldn't
            # be resolved either" (a genuinely broken row, not a new one)
            # — target_app being present is what tells the two apart.
            if resolved["dep"] is None and resolved["target_app"] is None:
                unresolved_names.append(row["name"])
                continue
            changed = _new_dependency_row_update(lines, row, resolved, resolution)
        else:
            changed = _existing_row_update(lines, row, resolved)

        if changed:
            changed_rows.append(changed)

    return "".join(lines), changed_rows, unmatched_names, unresolved_names


def _resolved_rows_by_values_key(upgrade_doc_text: str, resolution: ResolutionContext, canonical_names: dict):
    """{values_key: (row_name, resolved)} for every resolvable row (see
    resolve_component_row - "dependency", "native", AND "sidecar" kind
    alike; only "unmatched" or a row with no resolvable target_app at
    all is excluded) in -upgrade.md's own "Component versions" table
    (`upgrade_doc_text`) - the SINGLE source both fix_changes_heading_
    app_versions (the SAME doc) and fix_values_delta_heading_app_
    versions (a DIFFERENT doc, -values-deltas.md, which has no table of
    its own at all) key their own heading correction against, so the
    row's own display name (see add_missing_component_rows' own
    docstring - the same "friendly" value passed to both the table row
    and its own Changes heading when freshly written together) is
    authoritative for BOTH docs' own headings, not just whichever one
    happens to share a file with the table. `upgrade_doc_text` is "" -
    parse_upgrade_doc_rows("") is [] - when -upgrade.md itself doesn't
    exist yet; there is nothing to resolve against in that case, same
    as any other row this table doesn't (yet) have.

    A "sidecar"-kind row's own resolved["values_key"] is already the
    SAME dotted-string shape (".".join(sidecar_path), see resolve_
    component_row's own sidecar branch) real bug, real data proved this
    map must include too: a sidecar/MULTIPLE-scope Changes heading (e.g.
    "### redis 8.0 → 8.10.1") CAN go stale exactly the same way a "dep"
    heading can - confirmed live when today's redis/redis-operator
    historical-manifest collision fix changed what resolve_component_row
    itself now resolves for "redis", but nothing had ever revisited its
    own already-written heading. _fix_heading_app_versions is the one
    that reconciles a sidecar heading's own dotted-tuple identity (from
    changes_heading_identities) against this dotted-STRING key - see its
    own docstring."""
    resolved_by_values_key = {}
    for row in parse_upgrade_doc_rows(upgrade_doc_text):
        resolved = resolve_component_row(row["name"], canonical_names, resolution)
        if resolved["kind"] != "unmatched" and resolved["target_app"] is not None:
            resolved_by_values_key[resolved["values_key"]] = (row["name"], resolved)
    return resolved_by_values_key


def _chart_clause(heading: str):
    """The trailing " (chart ...)" clause of a Changes/values-delta
    heading, verbatim, or "" when the heading has none — split out only
    to keep _heading_replacement's own local-variable count down."""
    match = re.search(r"\s*\(chart[^)]*\)", heading)
    return match.group(0) if match else ""


def _heading_resolved_row(
    heading: str, resolution: ResolutionContext, inputs: HeadingFixInputs, canonical_path_to_name: dict
):
    """The (row_name, resolved, old_app, expected_bare_name) tuple
    _heading_replacement needs to decide whether/how to rewrite
    `heading`, or None when the heading names something this whole
    mechanism doesn't apply to (an ambiguous/orphaned identity, or one
    with no row data to compare against) — see _fix_heading_app_
    versions' own docstring for the full identity-resolution rationale
    (the sidecar-vs-dep lookup_key distinction, canonical_path_to_name's
    own reverse lookup)."""
    idents = changes_heading_identities(heading, resolution.target.deps, inputs.canonical_names)
    if len(idents) != 1:
        return None
    kind, values_key = next(iter(idents))
    if kind == "sidecar":
        lookup_key = ".".join(values_key)
        expected_bare_name = canonical_path_to_name.get(values_key)
    elif kind == "dep":
        lookup_key = values_key
        expected_bare_name = values_key
    else:
        return None
    if lookup_key not in inputs.resolved_by_values_key:
        return None
    row_name, resolved = inputs.resolved_by_values_key[lookup_key]

    if resolved["baseline_resolved"] is False:
        old_app = _dep_old_app_for_new_dependency(resolution, resolved)
    elif resolved["baseline_resolved"] is True:
        old_app = resolved["baseline_app"]
    else:
        return None
    return row_name, resolved, old_app, expected_bare_name


def _heading_replacement(
    block: dict, resolution: ResolutionContext, inputs: HeadingFixInputs, canonical_path_to_name: dict
):
    """The rewritten heading LINE text (marker + name + app-version +
    chart clause, no trailing newline) and the block's ORIGINAL heading
    text, when `block` needs correcting, or None when it's already
    correct or doesn't apply — see _fix_heading_app_versions' own
    docstring for the full rationale, in particular the name-correction
    and "already correct" comparisons below."""
    heading = block["heading"]
    # A heading with NO version marker at all (arrow/"(new)"/
    # "(unchanged)"/"(digest changed)" — see changes_heading_has_
    # app_version) was never meant to carry a machine-verifiable
    # version in the first place — real docs: values-deltas.md's own
    # bare "## zaakbrug" and free-form "## Breaking — Frank!Gateway
    # (only when `frankgateway.enabled: true`)" — never touched here,
    # same precondition update_stale_app_version_headings' own
    # "missing entirely" case already requires.
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
    # The name is corrected ONLY when it's precisely the bare,
    # uncustomized name add_missing_component_rows' own auto-write
    # convention uses (see its own docstring: the same "friendly"
    # value passed to BOTH the row and its own heading when freshly
    # written together) — unambiguously stale once a human later
    # hand-edits the ROW to something friendlier (real bug, real
    # doc: mi's own row became "mi-data (MI-data exports)", but its
    # heading was left as bare "mi"). A DIFFERENT, already-
    # customized name (real cases, confirmed live: "Keycloak
    # Operator (server)" vs its own row's longer "Keycloak Operator
    # (server + operator images)"; "FrankGateway image" vs the row's
    # plain "FrankGateway") is a deliberate editorial choice this
    # must never overwrite just because it happens to differ from
    # the row's own text — a first version of this fix did exactly
    # that, silently clobbering real, hand-written doc content.
    corrected_name = row_name if current_name == expected_bare_name else current_name
    if expected_app_heading in without_chart_clause and corrected_name == current_name:
        return None
    return f"{inputs.heading_marker} {corrected_name} {expected_app_heading}{_chart_clause(heading)}", heading


def _fix_heading_app_versions(text: str, resolution: ResolutionContext, inputs: HeadingFixInputs):
    """Shared implementation for fix_changes_heading_app_versions
    (-upgrade.md's own "### ..." Changes-section headings) and fix_
    values_delta_heading_app_versions (-values-deltas.md's own "## ..."
    section headings) - see either one's own docstring for the full
    rationale; this just does the actual compare+rewrite once, given the
    row data ALREADY resolved (see _resolved_rows_by_values_key - the
    SAME map both callers pass in, so the two docs' own headings can
    never independently disagree on the same component's own correct
    name/wording) and `inputs`, a HeadingFixInputs, parameterized only by
    which already-parsed section list (`blocks` - parse_upgrade_doc_
    changes_blocks or parse_values_delta_sections) and heading marker
    ("###" or "##") apply. Returns (new_text, updated_headings) -
    updated_headings is the ORIGINAL (pre-fix) heading text for every
    heading actually rewritten (a wrong name, a wrong app-version
    transition, or both at once).

    A "sidecar"-identity heading (changes_heading_identities' own
    ("sidecar", sidecar_path) - sidecar_path a values-tree path TUPLE,
    e.g. ("global", "images", "redis")) is looked up in resolved_by_
    values_key via ".".join(sidecar_path) - the exact dotted-STRING form
    resolve_component_row's own sidecar branch already uses as its own
    values_key, so no restructuring of that map's own key convention is
    needed, just a matching join on this side. Real bug this closes:
    a sidecar/MULTIPLE-scope heading (e.g. bare "redis", or "redis-
    operator - redis" for a real sidecar under a real dependency) was
    previously NEVER revisited here at all - the deliberate design this
    replaces assumed such a heading is "only ever written once its own
    tag is already known," proven wrong live (today's redis/redis-
    operator collision fix changed what resolve_component_row now
    resolves for "redis", and the already-written heading was never
    updated to match).

    canonical_names' own {name: path} map also gives this the CORRECT
    "is this still the bare, uncustomized name" comparison for a sidecar
    heading - see corrected_name below: unlike "dep" kind (whose
    resolved["values_key"] IS its own bare/uncustomized name, e.g. "mi"),
    a sidecar's resolved["values_key"] is a dotted VALUES-TREE PATH
    ("global.images.redis") that a real heading's own name is never
    going to equal - the real bare/uncustomized comparison for a sidecar
    is against ITS OWN canonical name (canonical_names' own dict KEY
    for this exact path, e.g. "redis" or "redis-operator - redis"),
    found via a reverse lookup, never the dotted path itself."""
    canonical_path_to_name = {path: name for name, path in inputs.canonical_names.items()}
    lines = text.splitlines(keepends=True)
    updated_headings = []
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
    """Rewrite a "### ..." Changes section heading's own name and app-
    version portions (never the "(chart ...)" clause, or the body below
    it, both left untouched) to match what fix_component_version_table's
    own row loop ALREADY verifies and rewrites for the table row every
    single run - see _fix_heading_app_versions for the full mechanism.
    `resolution` is a ResolutionContext.

    Real bug, real doc: mi's own "### mi 2.71.0 -> 2.90.0 (chart 1.1.0, unchanged)"
    heading, written by an earlier, buggy tool run before this chart's
    baseline-resolution bugs were fixed. mi is actually a BRAND NEW
    dependency this hop - no 2.71.0 baseline value exists at all - so
    the correct heading is "### mi-data (MI-data exports) 2.90.0 (new)
    (chart 1.1.0, unchanged)" (mi-data (MI-data exports) being the
    table row's own, later hand-edited display name - see _fix_heading_
    app_versions' own docstring for why that one wins). fix_component_
    version_table's own row loop DOES re-verify and rewrite the table
    ROW's own cells every run against whatever baseline resolution is
    current now, bugs fixed or not - but nothing else ever revisited the
    heading once it already existed; this closes exactly that gap. Run
    this AFTER fix_component_version_table (order matters only for the
    printed diff being intuitive to read top-to-bottom; this function
    re-resolves its own old/new versions independently, so it doesn't
    actually depend on the row text having been rewritten first).

    Deliberately does NOT reconstruct old/new from the table row's own
    RENDERED cell text (extract_source_version/extract_target_version) -
    that round-trip is lossy: a "<version> (new)" cell and a "<version>
    (unchanged)" cell both extract to the exact same (source, target)
    pair once the annotation itself is stripped, so there is no way to
    tell a genuinely brand-new component's cell apart from an unchanged
    one just from those two numbers (confirmed live: this WAS the first
    approach tried here, and it silently turned mi's heading into the
    equally-wrong "(unchanged)" instead of "(new)"). Independently
    re-resolves via resolve_component_row instead - the SAME shared
    function fix_component_version_table's own row loop and lib.docs_
    consistency.check_docs_consistency's own row-checker already use
    (see its own docstring for why: a checker/fixer that resolves a
    row/heading pair different ways can silently drift apart on what
    "correct" even means) - and _dep_old_app_for_new_dependency, the
    exact same brand-new-dependency historical-manifest fallback fix_
    component_version_table's own row loop uses for its APP cell, so a
    freshly-fixed row and its own heading can never disagree.

    Only ever touches a heading naming EXACTLY ONE real identity (see
    resolve_component_identity/changes_heading_identities - a real
    Chart.yaml dependency, a lib.chart.native_components component, OR a
    canonical sidecar/MULTIPLE-scope image, e.g. "redis" or "redis-
    operator - redis") whose row resolves to a real, non-None target app
    version; a heading that's ambiguous, orphaned, whose row has no
    resolvable app version at all, whose baseline genuinely can't be
    checked (upgrade_docs_baseline itself doesn't resolve to a git ref),
    or that's already correct (name AND app-version wording both agree)
    is left exactly as-is - never a spurious rewrite when nothing is
    actually wrong. (A canonical sidecar heading was previously assumed
    to never need this at all - "only ever written once its own tag is
    already known" - proven wrong live: today's redis/redis-operator
    historical-manifest collision fix changed what resolve_component_row
    now resolves for "redis" itself, and nothing had ever revisited the
    already-written heading to match; see _fix_heading_app_versions'
    own docstring for the mechanism.) Returns (new_text, updated_
    headings) - updated_headings is the ORIGINAL (pre-fix) heading text
    for every heading actually rewritten."""
    current_paths = dict(find_image_tag_paths(resolution.target.values))
    current_paths.update(global_image_paths(resolution.target.values))
    canonical_names = canonical_sidecar_row_names(
        resolution.chart_dir, resolution.target.deps, resolution.target.values, current_paths.keys()
    )
    resolved_by_values_key = _resolved_rows_by_values_key(text, resolution, canonical_names)
    blocks = parse_upgrade_doc_changes_blocks(text)
    return _fix_heading_app_versions(
        text, resolution, HeadingFixInputs(resolved_by_values_key, canonical_names, blocks, "###")
    )


def fix_values_delta_heading_app_versions(
    upgrade_doc_text: str, values_deltas_text: str, resolution: ResolutionContext
):
    """The SAME stale-heading gap fix_changes_heading_app_versions closes
    for -upgrade.md's own "### ..." Changes-section headings, but for
    -values-deltas.md's own "## ..." section headings instead (see
    lib.component_docs.values_delta_section_heading/sync_values_delta_
    sections - a genuinely SEPARATE, parallel implementation, not the
    same function shared between the two doc types: sync_values_delta_
    sections' own docstring already states "Existing content is only
    ever ADDED to, never reordered or rewritten" - an existing section's
    own heading is never revisited there either, the identical gap).
    Real bug, real doc: mi's own "## mi 2.71.0 -> 2.90.0 (chart 1.1.0,
    unchanged)" section heading in 4.9.0-to-4.9.1-values-deltas.md, same
    wrong wording, same root cause, confirmed live. `resolution` is a
    ResolutionContext.

    `upgrade_doc_text` (the CURRENT -upgrade.md text, already corrected
    by fix_component_version_table/fix_changes_heading_app_versions by
    the time main() gets here) is where the row data this keys its own
    correction against actually lives - values-deltas.md has no
    "Component versions" table of its own at all, so its own row's
    authoritative display name (see _resolved_rows_by_values_key) can
    only ever come from -upgrade.md's. See _fix_heading_app_versions
    for the shared compare+rewrite mechanism both this and fix_changes_
    heading_app_versions actually use."""
    current_paths = dict(find_image_tag_paths(resolution.target.values))
    current_paths.update(global_image_paths(resolution.target.values))
    canonical_names = canonical_sidecar_row_names(
        resolution.chart_dir, resolution.target.deps, resolution.target.values, current_paths.keys()
    )
    resolved_by_values_key = _resolved_rows_by_values_key(upgrade_doc_text, resolution, canonical_names)
    blocks = parse_values_delta_sections(values_deltas_text)
    return _fix_heading_app_versions(
        values_deltas_text, resolution, HeadingFixInputs(resolved_by_values_key, canonical_names, blocks, "##")
    )
