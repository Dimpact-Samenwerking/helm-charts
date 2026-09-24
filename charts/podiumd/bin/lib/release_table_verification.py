"""The comparison engine behind verify-release-table-with-podiumd: compares
charts/podiumd/etc/release-table.csv against a ChartState (either the
CURRENT chart, or the release_table baseline resolved at some historical
git ref — see lib.release_baseline.resolve_baseline_chart_state), and
reports version mismatches / missing rows / missing pins. The script's
--help describes the user-facing contract; maintainer notes:

- The component/alias/image_basename columns are already resolved by
  export-confluence-release-table and are read as-is.
- An image is looked up the same way as update-image-version's <key>
  <basename>: first basenames_under_scope_any_tag in the component's own
  values.yaml subtree, then find_matches_any_tag across the whole file,
  since a basename can be pinned under a sibling scope (keycloak-config-
  cli lives under "keycloak", not "keycloak-operator").
- The "_any_tag" variants are deliberate: release-table.csv records a
  version, never a digest, so a chart older than digest pinning
  (podiumd-4.8.5) still compares on version alone.
- A component's primary image without a "repository:" override is
  resolved from the vendored .tgz only (primary_image_repositories); if
  that sub-chart is not vendored at its pinned version, its basename is
  silently unresolved. Nothing is pulled.
- A "MULTIPLE" row without an image_basename (an ambiguous name
  collision at export time) is skipped, like a blank component.

Split out of the script for pylint's too-many-lines threshold (1000)."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lib.chart.pull_and_subchart_resolution import primary_image_repositories
from lib.chart.registered_paths import image_paths_for
from lib.chart.values_tree_primitives import dotted_key_path
from lib.chart.values_tree_primitives import find_dependency
from lib.chart.values_tree_primitives import get_path
from lib.chart.values_tree_primitives import strip_registry_host
from lib.chart.values_tree_primitives import version_of
from lib.image.version import GLOBAL_IMAGES_SCOPE
from lib.image.version import MULTIPLE_KEY
from lib.image.version import basenames_under_scope_any_tag
from lib.image.version import find_matches_any_tag
from lib.image.version import image_basename
from lib.image.version import repository_for_basename_in_scope

UNRESOLVED_COMPONENTS = ("", "UNKNOWN")


@dataclass
class ComponentRef:
    """scope_key/component/dep travel together everywhere a check needs to
    know WHICH component it's checking and where in values.yaml its scope
    lives: `scope_key` is the human-facing values.yaml key (a dependency's
    own alias if it has one, else its name — see compare()); `component`
    is always the stable identity (a Chart.yaml dependency's own "name",
    or the bare values.yaml key for a component with no separate chart),
    used for MULTIPLE_KEY/UNKNOWN comparisons that must never follow an
    alias. `dep` is None for a component with no separate Chart.yaml
    dependency at all (MULTIPLE_KEY, or a bare top-level values.yaml key
    like frankgateway) — every check that actually needs it (a chart
    version, or the subchart-default image fallback) only ever runs where
    it's resolved."""

    scope_key: str
    component: str
    dep: dict | None = None


@dataclass
class ChartState:
    """One point-in-time snapshot of the chart this module reads pins
    from — either the CURRENT working tree (chart_dir/deps/values/lines
    as they are right now) or the release_table baseline (see
    lib.release_baseline.resolve_baseline_chart_state) resolved at some
    historical git ref. `chart_dir` is the same podiumd chart root either
    way — only ever consulted as a last resort, to resolve a component's
    primary image via its vendored subchart's own default repository
    (see primary_image_basename/check_images_source), never re-derived
    per snapshot."""

    chart_dir: Path
    deps: list
    values: dict | None
    lines: list


@dataclass
class Comparison:
    """The CURRENT and release_table-baseline ChartState together — every
    *_source check needs both: the baseline state for what a row's
    source_version_* SHOULD show, and the current state's own `lines` to
    guard the baseline-side unscoped find_matches_any_tag fallback
    against a same-basename-different-repository collision (see
    check_images_source's own docstring)."""

    current: ChartState
    baseline: ChartState | None


@dataclass
class Observed:
    """The compared pair behind one mismatch finding: `target` is
    release-table.csv's own recorded value, `actual` is what's really
    pinned right now (or at the release_table baseline), `source_label`
    names WHERE `actual` came from (e.g. "Chart.yaml", "values.yaml") for
    the finding's own message text — see report_mismatch."""

    target: str
    actual: str
    source_label: str


def split_basenames(value: str):
    """A CSV "basenames" cell (comma-separated, e.g. for a MULTIPLE_KEY
    row) split into its individual basenames, stripped of surrounding
    whitespace with blank entries dropped."""
    return [b.strip() for b in value.split(",") if b.strip()]


def is_verifiable_target(target: str):
    """False for a blank or "UNKNOWN" target column value — nothing to
    compare against (blank means "no planned change", see query-release-
    table.py's own UNCHANGED display logic; "UNKNOWN" means export-
    confluence-release-table.py's own normalize_version couldn't parse
    the source cell as a version at all). True otherwise."""
    return bool(target) and target != "UNKNOWN"


def report_mismatch(findings: dict, tag: str, row: dict, label: str, observed: Observed):
    """Appends a "release-table target != actual" line to
    findings["mismatches"] for `row`, formatted as "[tag] name (label):
    release-table target <target> != <actual_source> <actual>" (see
    Observed) — the shared message shape every mismatch check in this
    module (app version, chart version, etc., each with its own
    `tag`/`observed.source_label`) uses, so findings read consistently
    regardless of which check found them."""
    findings["mismatches"].append(
        f"[{tag}] {row['name']} ({label}): release-table target {observed.target} != "
        f"{observed.source_label} {observed.actual}"
    )


# Printed as a "missing_from_release_table" finding's own second line
# (see verify-release-table-with-podiumd's print_report) whenever no
# Confluence section could be inferred for it — a brand-new Chart.yaml
# dependency has no existing release-table.csv row at all to read a
# "section" value from.
GENERIC_TABLE_HINT = "whichever table fits (Product/Common Ground/Overige/Technische component versies)"


TECHNISCHE_TABLE_HINT = '"Technische component versies"'


def confluence_table_hint(rows: list, component: str):
    """Which Confluence table (e.g. '"Technische component versies"') a
    "missing from release-table.csv" finding should actually be added
    to — read off the "section" column (see export-confluence-release-
    table's CSV_HEADER) of any one of `rows`, since every row for the
    same component/MULTIPLE_KEY is exported under the same table. Falls
    back to GENERIC_TABLE_HINT when `rows` is empty and no better guess
    applies — except MULTIPLE_KEY, where every values.yaml global.images
    entry is, by convention, exported under "Technische" (see verify-
    release-table-with-podiumd's own module docstring), a safe guess even
    with zero existing "MULTIPLE" rows to read a section from at all."""
    if rows:
        return f'"{rows[0]["section"]} component versies"'
    if component == MULTIPLE_KEY:
        return TECHNISCHE_TABLE_HINT
    return GENERIC_TABLE_HINT


def is_primary_image(component: str, lines: list[str], pin: dict, chart_dir: Path | None = None):
    """True if `pin` (one of basenames_under_scope_any_tag()'s own pins, with its
    own "line") sits at one of `component`'s own primary application
    image path(s) — see lib.chart.image_paths_for / settings.yaml's
    component_resolution.image_paths/default_image_paths, the EXACT SAME
    registry update-component-version's own <app-version> argument
    targets (via update_values_yaml's "{values_key}.{path}.tag" — the
    same shape reconstructed here from `pin`'s own line).
    default_image_paths (["image"]) covers the common single-image case;
    component_resolution.image_paths overrides it for a multi-image
    component like zgw-office-addin's own frontend+backend (both
    primary), or keycloak-operator's own non-standard split-path SERVER
    image.

    Anything NOT in that list — a sidecar/init-container image nested
    elsewhere, e.g. "zac.opentelemetry-collector.image.tag" or
    "zac.opa.image.tag" — is never that component's primary image, no
    matter how deep or shallow the nesting: it's exactly what update-
    image-version's own <basename> targets instead of update-component-
    version's <app-version>, and belongs on "Technische component
    versies", with "Used by" naming the component that pulls it in (see
    missing_image_hint). Meaningless for MULTIPLE_KEY (values.yaml
    global.images.* entries never have a "primary" component at all) —
    never checked for it."""
    path = dotted_key_path(lines, pin["line"] - 1).split(".")
    relative = ".".join(path[1:-1])
    return relative in image_paths_for(component, chart_dir)


def primary_image_basename(ref: ComponentRef, state: ChartState):
    """The basename of `ref.component`'s own primary application image
    (see is_primary_image) — e.g. "openbao" for openbao's own
    "server.image" path. Tries the plain digest-pin text scan first
    (basenames_under_scope — the common case, whenever the primary path
    has its own explicit "repository:" in podiumd's values.yaml); if
    that finds nothing at all AND `ref.dep` is a real Chart.yaml
    dependency (None for a bare top-level values.yaml key with no
    separate chart, e.g. frankgateway — nothing to resolve a subchart
    default against), falls back to lib.chart.primary_image_repositories
    instead — the fix for a primary image whose repository comes
    entirely from its subchart's own default (e.g. openzaak,
    openformulieren), invisible to the text scan since basenames_under_
    scope can only compute a basename from a pin with a resolvable
    repository of its own. Network-free either way: primary_image_
    repositories is called with allow_pull=False — a subchart that
    isn't vendored under `state.chart_dir` yet just can't be resolved
    this way until it is; `state.chart_dir` may itself be None (the
    test-only "no vendored charts available at all" case) without ever
    raising, as long as no path actually needs the subchart fallback
    (an own explicit override is enough on its own).

    None if neither approach resolves a unique basename: no pin at any
    of image_paths_for(ref.component)'s own path(s) under this scope yet
    AND (no dep to fall back on, or the subchart doesn't default one
    either, or isn't resolvable at all without a real `state.chart_dir`)
    — see the companion "[IMAGE] ... not tracked" finding for that
    basename itself in that case; or, in principle, more than one
    distinct basename claiming to be primary, which shouldn't happen
    given image_paths_for's own paths are always distinct, but is never
    guessed at regardless."""
    primaries = {
        basename
        for basename, pins in basenames_under_scope_any_tag(state.lines, ref.scope_key).items()
        if any(is_primary_image(ref.component, state.lines, pin, state.chart_dir) for pin in pins)
    }
    if primaries:
        return next(iter(primaries)) if len(primaries) == 1 else None
    if ref.dep is None:
        return None
    repos, _error = primary_image_repositories(state.chart_dir, ref.dep, state.values, allow_pull=False)
    resolved = {image_basename(repo) for repo in repos.values() if repo}
    return next(iter(resolved)) if len(resolved) == 1 else None


def find_primary_row(ref: ComponentRef, state: ChartState, rows: list):
    """The one row in `rows` whose own image_basename column claims
    `ref.component`'s own primary application image basename (see
    primary_image_basename) — the ONLY row a chart's own Helm version
    genuinely belongs next to, e.g. openbao's own "OpenBao" row, never
    its sibling "OpenBao Schema Job (postgres)" row, even though both
    share the same component. None if the primary basename can't be
    resolved, or no existing row claims it yet."""
    basename = primary_image_basename(ref, state)
    if basename is None:
        return None
    for row in rows:
        if basename in split_basenames(row["image_basename"]):
            return row
    return None


def chart_version_ever_tracked(rows: list):
    """True if ANY of `rows` has ever recorded a Helm chart version for
    this component — either a verifiable target_version_helm (a bump is
    planned, or was already made and is just waiting for the next
    baseline advance), or a non-blank source_version_helm (recorded at
    some past baseline, even if this cycle plans no change). False only
    when EVERY row's Helm columns are blank across the board — this
    dependency's chart version was never captured in release-table.csv
    at all, not merely "no change planned this cycle" (which
    is_verifiable_target's own blank-target convention is for)."""
    return any(is_verifiable_target(row["target_version_helm"]) or row["source_version_helm"] for row in rows)


def row_app_version(row: dict):
    """The already-known app version for `row` — its own target if a
    bump is planned/verifiable (see is_verifiable_target), else its own
    previously-recorded source — the value missing_chart_version_hint
    carries over into a relocated/new row alongside the chart version,
    so a human doesn't have to go look it up again. "" if neither is
    known yet (a row that has never been exported with a real app
    version at all)."""
    target = row["target_version_app"]
    return target if is_verifiable_target(target) else row["source_version_app"]


def missing_chart_version_hint(ref: ComponentRef, state: ChartState, rows: list):
    """Second line for a "[CHART] ... never recorded a Helm chart
    version" finding — naming the SPECIFIC row this chart's own version
    belongs next to (see find_primary_row), not just whichever table
    happens to hold some row for this component: a component can have
    several rows (its own primary image, plus one per sidecar — e.g.
    openbao's own "OpenBao" row vs its sibling "OpenBao Schema Job
    (postgres)" row), and only the PRIMARY one is where a chart version
    ever belongs.

    Called out explicitly when that row's own table structurally has no
    Helm sub-column at all (see lib.confluence_tables.
    select_release_columns — true for "Technische component versies"
    since 2026-09, see verify-release-table-with-podiumd's own module
    docstring) — tracking this dependency's chart version at all then
    needs a row on one of the other three tables instead, not just
    filling in a cell that doesn't exist here. Spells out the exact
    remove/add actions and field values (Name, Helm version, App version
    — see row_app_version) rather than just naming the row and leaving
    the rest to be worked out by hand: WHICH of the other three tables
    fits is still a human judgment call this module can't make (see
    GENERIC_TABLE_HINT), but everything else about the new row is
    already fully known from the existing one. If the primary row can't
    even be identified yet (no existing row claims that basename — see
    the companion "[IMAGE] ... not tracked" finding for it), says so
    instead of guessing which row to point at."""
    primary_row = find_primary_row(ref, state, rows)
    if primary_row is None:
        return (
            "Confluence: none of the existing row(s) is this chart's own primary-image row yet "
            "(see the companion [IMAGE] finding for its own basename, if listed) — add the Helm "
            "version to that row once it exists"
        )
    name = primary_row["name"]
    where = f'"{primary_row["section"]} component versies"'
    chart_version = str(ref.dep["version"]) if ref.dep else ""
    if where == TECHNISCHE_TABLE_HINT:
        app_version = row_app_version(primary_row)
        app_version_suffix = f", App version {app_version}" if app_version else ""
        return (
            f'Confluence: remove "{name}" from {where} and add it instead to whichever of '
            f'"Product/Common Ground/Overige component versies" fits — Name "{name}", '
            f"Helm version {chart_version}{app_version_suffix}"
        )
    return f'Confluence: fill in the Helm version cell on "{name}" ({where}) with {chart_version}'


def check_chart_version(ref: ComponentRef, rows: list, state: ChartState, findings: dict):
    """The TARGET-side counterpart to check_chart_version_source: for every
    release-table.csv row belonging to `ref.dep`, compares its verifiable
    target_version_helm against ref.dep["version"] (Chart.yaml's actual
    current pin), recording a mismatch via report_mismatch when they
    disagree. A blank target isn't skipped outright — its own recorded
    source_version_helm is still checked against the current Chart.yaml
    version, the same gap check_images' own blank-target branch guards
    against (release-table.csv can silently drift even without ever
    filling in a "planned" target). Also records a "missing_from_release_
    table" finding, with a fix-it hint from missing_chart_version_hint,
    when no row for this dependency has EVER recorded a Helm chart
    version at all (see chart_version_ever_tracked)."""
    actual = str(ref.dep["version"]) if ref.dep else ""
    for row in rows:
        target = row["target_version_helm"]
        if is_verifiable_target(target):
            if target != actual:
                report_mismatch(findings, "CHART", row, ref.component, Observed(target, actual, "Chart.yaml"))
        else:
            # Same gap as check_images' own blank-target branch: a blank
            # target_version_helm ("no planned change") must not excuse
            # never checking this row again — if its own previously-
            # recorded source has since drifted from Chart.yaml's real
            # current version, that's a real change release-table.csv
            # never caught up to, not a legitimate "unchanged".
            source = row["source_version_helm"]
            if is_verifiable_target(source) and source != actual:
                findings["mismatches"].append(
                    f"[CHART] {row['name']} ({ref.component}): release-table target is blank (recorded "
                    f"source {source}) but Chart.yaml is now {actual} — target_version_helm was never "
                    f"filled in for this change"
                )
    if not chart_version_ever_tracked(rows):
        hint = missing_chart_version_hint(ref, state, rows)
        findings["missing_from_release_table"].append(
            f"[CHART] Chart.yaml dependency '{ref.component}' has release-table.csv row(s), but none "
            f"records a Helm chart version\n      {hint}"
        )


def check_chart_version_source(
    dep: dict, rows: list, baseline_deps: list, findings: dict, *, strict_presence: bool = False
):
    """The SOURCE-side sibling of check_chart_version: for every row with
    a verifiable source_version_helm (see is_verifiable_target — never
    just "blank, no prior value recorded yet"), compares it against
    what `dep` (matched by its own stable Chart.yaml "name", not the
    alias, which check_chart_version's own `ref.scope_key` already is)
    ACTUALLY was in Chart.yaml at the release_table baseline (see
    lib.chart.release_table_baseline/lib.release_baseline.resolve_
    baseline_chart_state). A row claiming a real source version for a
    dependency that didn't exist in baseline_deps AT ALL (a brand-new
    Chart.yaml dependency this release) is a distinct finding — that
    source value can't be right no matter what it says, since there was
    nothing to record a source FROM at the baseline release_table itself
    was written against.

    `strict_presence` (only ever True under --baseline-only — see verify-
    release-table-with-podiumd's own module docstring) additionally
    verifies the OTHER direction: a Helm chart version only ever belongs
    on ONE of a dependency's own rows (its primary row — see
    chart_version_ever_tracked, the exact same per-DEPENDENCY, not
    per-row, granularity this mirrors), so instead of checking each
    row's own source_version_helm in isolation, this checks whether ANY
    row recorded a verifiable one at all (never "UNKNOWN" — that's a
    value that WAS recorded but couldn't be parsed, a different problem,
    not "nothing recorded"). That blank-across-every-row case is only
    left silent (the default, every-invocation behavior) if `dep`
    genuinely didn't exist yet at the release_table baseline; if
    baseline_dep resolves anyway, the blank is NOT justified —
    release-table.csv should have recorded a source version for this
    dependency somewhere but never did, reported as its own single
    "-PRESENCE" finding (never one per sidecar row, which structurally
    never carries a chart version at all — see is_primary_image)."""
    baseline_dep = find_dependency(baseline_deps, dep["name"])
    any_source_recorded = False
    for row in rows:
        source = row["source_version_helm"]
        if not is_verifiable_target(source):
            continue
        any_source_recorded = True
        if baseline_dep is None:
            findings["mismatches"].append(
                f"[CHART-SOURCE] {row['name']} ({dep['name']}): release-table claims source chart version "
                f"{source}, but this dependency didn't exist at the release_table baseline yet"
            )
            continue
        actual = str(baseline_dep["version"])
        if source != actual:
            findings["mismatches"].append(
                f"[CHART-SOURCE] {row['name']} ({dep['name']}): release-table source {source} != "
                f"baseline Chart.yaml {actual}"
            )
    if strict_presence and not any_source_recorded and baseline_dep is not None:
        findings["mismatches"].append(
            f"[CHART-SOURCE-PRESENCE] Chart.yaml dependency '{dep['name']}' has release-table.csv row(s), but "
            f"none records a source_version_helm, even though it already existed at the release_table baseline "
            f"(version {baseline_dep['version']})"
        )


def missing_image_hint(rows: list, ref: ComponentRef, basename: str, versions: set[str], *, primary: bool):
    """Second line for an "[IMAGE] ... not tracked" finding: which
    Confluence table to add a row to, and what that row needs to say so
    export-confluence-release-table's own resolve_image_basenames/
    component_and_alias resolve it right back to this same component/
    basename on the next export — a human is free to phrase the row's
    actual "Name" however reads best (e.g. "ZAC Gotenberg", not
    literally "gotenberg"); the one hard requirement, spelled out here
    so a re-export doesn't silently leave it unresolved again, is that
    the text contain `basename` (matched by substring — see lib
    "_related" in export-confluence-release-table).

    A real (non-MULTIPLE) component's own PRIMARY image (see
    is_primary_image) goes on whichever table its own existing row is
    already on (see confluence_table_hint) — no "Used by" needed there,
    since it's that row's own Name doing the resolving. Every other
    image — a sidecar/init-container, never the component's primary one
    — always goes on "Technische component versies" instead, WITH "Used
    by" naming `ref.scope_key` (already the human-facing identifier used
    everywhere else, e.g. "zac"), regardless of which table the
    component's own primary row lives on: "Used by" is the one thing
    that actually scopes a sibling row's basename match to this
    component (see resolve_image_basenames) — the ONLY column that does,
    and the ONLY table ("Technische component versies") that has a "Used
    by" column at all (see export-confluence-release-table's own module
    docstring: Product/Common Ground/Overige use "Ontwikkelpartij"
    instead, which this export never derives a component from — see
    component_and_alias's own used_by-or-name fallback). A MULTIPLE row
    (a values.yaml global.images.* image, shared across components)
    resolves purely from its own Name relating to the image key itself,
    so it never needs "Used by" either, even there.

    `versions` are the image's own tag(s) — always an App version (see
    CSV_HEADER's own source/target_version_APP), never a Helm chart
    version (a component's chart version is a whole different, already-
    separately-checked thing — see check_chart_version). Said so
    explicitly here, not just "version", since every table but
    "Technische component versies" still splits its "Versie ..." column
    into separate App/Helm sub-columns (see lib.confluence_tables.
    select_release_columns) — without naming which one, a human has no
    way to tell which sub-column this value actually belongs in."""
    version_text = ", ".join(sorted(versions))
    if ref.component != MULTIPLE_KEY and not primary:
        where = TECHNISCHE_TABLE_HINT
        what = f'"Used by": "{ref.scope_key}", Name containing "{basename}"'
    else:
        where = confluence_table_hint(rows, ref.component)
        what = f'Name containing "{basename}"'
    return f"Confluence: add row to {where} — {what}, App version (currently) {version_text}"


def _record_image_result(ref: ComponentRef, row: dict, basename: str, actual: str, findings: dict):
    """Per-basename comparison once `actual` has resolved to exactly one
    version (see check_images) — split out so the row/basename double
    loop above it never nests deeper than a plain "for/for/if" itself."""
    target = row["target_version_app"]
    if is_verifiable_target(target):
        if actual != target:
            report_mismatch(
                findings, "IMAGE", row, f"{ref.component}.{basename}", Observed(target, actual, "values.yaml")
            )
        return
    # target_version_app blank ("no planned change" — see
    # is_verifiable_target) must never mean "nothing left to check": a
    # real pin was JUST resolved above, so compare it against whatever
    # this row's own source last recorded instead — the exact gap a
    # blank target can otherwise hide behind indefinitely (real case,
    # confirmed live: mi-data's own azure-cli pin moved to 2.90.0 in
    # values.yaml while its release-table row never recorded ANY app
    # version at all, source or target — "OK: matches" regardless).
    source = row["source_version_app"]
    if is_verifiable_target(source):
        if actual != source:
            findings["mismatches"].append(
                f"[IMAGE] {row['name']} ({ref.component}.{basename}): release-table target is "
                f"blank (recorded source {source}) but values.yaml is now {actual} — "
                f"target_version_app was never filled in for this change"
            )
        return
    findings["missing_from_release_table"].append(
        f"[IMAGE] '{basename}' under '{ref.scope_key}' is pinned at {actual} in values.yaml, "
        f"but release-table.csv's row for it has never recorded an app version "
        f"(source and target both blank)"
    )


def check_images(ref: ComponentRef, rows: list, state: ChartState, findings: dict):
    """The TARGET-side counterpart to check_images_source: resolves every
    basename release-table.csv's rows for `ref.component` list under
    `ref.scope_key` (via basenames_under_scope_any_tag, falling back to
    an unscoped find_matches_any_tag search — a basename is a real
    repository identity, not a values.yaml path, so it can legitimately
    live under a sibling scope, e.g. keycloak-config-cli under top-level
    "keycloak") and compares each resolved version against that row's own
    verifiable target_version_app, recording a mismatch (see
    _record_image_result) when they disagree. A pin resolving to more
    than one distinct version is reported as "ambiguous" instead of
    compared. After the per-row pass, a second pass walks every ACTUAL
    basename pinned under `ref.scope_key` that no row claimed at all,
    recording a "missing_from_release_table" finding (with a fix-it hint
    from missing_image_hint, which also needs to know whether it's this
    component's own primary image — see primary_image_basename — since
    only a sidecar needs "Used by")."""
    actual_basenames = basenames_under_scope_any_tag(state.lines, ref.scope_key)
    csv_basenames = set()
    # Resolved once per component (not per pin) — see primary_image_basename;
    # only ever consulted below for a basename release-table.csv doesn't
    # track yet, to decide whether it's this component's own primary image
    # (no "Used by" needed) or a sidecar (always needs one).
    primary_basename = None if ref.component == MULTIPLE_KEY else primary_image_basename(ref, state)

    for row in rows:
        basenames = split_basenames(row["image_basename"])
        if not basenames:
            continue

        for basename in basenames:
            csv_basenames.add(basename)
            pins = actual_basenames.get(basename)
            if pins is None:
                # Not under this component's own scope — a plain,
                # unscoped find_matches fallback (unlike update-image-
                # version/verify-image-version/show-image-baseline-
                # version's own required <key> <basename>, which would
                # reject this): a basename is a real repository identity,
                # not a values.yaml path, so it can legitimately be
                # pinned under a sibling scope instead (e.g. keycloak-
                # config-cli lives under top-level "keycloak", not
                # "keycloak-operator").
                pins = find_matches_any_tag(state.lines, basename) or None
            if pins is None:
                findings["missing_from_chart"].append(
                    f"[IMAGE] release-table image '{basename}' for component '{ref.component}' "
                    f"(row '{row['name']}') is not pinned anywhere under '{ref.scope_key}' in values.yaml"
                )
                continue

            versions = {p["version"] for p in pins}
            if len(versions) > 1:
                findings["ambiguous"].append(
                    f"[IMAGE] '{basename}' under '{ref.scope_key}' is pinned at {len(versions)} different "
                    f"versions ({', '.join(sorted(versions))}) -- can't compare to release-table"
                )
                continue
            _record_image_result(ref, row, basename, next(iter(versions)), findings)

    for basename, pins in actual_basenames.items():
        if basename not in csv_basenames:
            versions = {p["version"] for p in pins}
            primary = ref.component != MULTIPLE_KEY and basename == primary_basename
            hint = missing_image_hint(rows, ref, basename, versions, primary=primary)
            findings["missing_from_release_table"].append(
                f"[IMAGE] '{ref.scope_key}' image '{basename}' is pinned in values.yaml but not tracked "
                f"in release-table.csv\n      {hint}"
            )


def _check_image_source_pin(ref: ComponentRef, row: dict, basename: str, resolve_at_baseline: Callable, findings: dict):
    """Per-basename comparison against the release_table baseline (see
    check_images_source) — split out so the row/basename double loop
    above it stays flat, and its own several intermediate names (the
    resolved tier result, its unpacked version/label) never count toward
    check_images_source's own local-variable budget."""
    source = row["source_version_app"]
    verifiable_source = is_verifiable_target(source)
    result = resolve_at_baseline(basename)
    tag = result[0]
    if tag == "ambiguous":
        findings["ambiguous"].append(f"[IMAGE-SOURCE] {result[1]}")
        return
    if not verifiable_source:
        # strict_presence blank-source check: "found" means the blank
        # wasn't justified; "absent" means stay silent (genuinely absent
        # at the release_table baseline).
        if tag == "found":
            _, actual, label = result
            findings["mismatches"].append(
                f"[IMAGE-SOURCE-PRESENCE] {row['name']} ({ref.component}.{basename}): release-table "
                f"source_version_app is blank, but '{basename}' already existed at the release_table "
                f"baseline ({label} {actual}) — source_version_app was never filled in for this image"
            )
        return
    if tag == "found":
        _, actual, label = result
        if actual != source:
            findings["mismatches"].append(
                f"[IMAGE-SOURCE] {row['name']} ({ref.component}.{basename}): release-table source {source} "
                f"!= baseline {label} {actual}"
            )
        return
    findings["mismatches"].append(
        f"[IMAGE-SOURCE] {row['name']} ({ref.component}.{basename}): release-table claims source version "
        f"{source}, but this image wasn't pinned anywhere under '{ref.scope_key}' at the release_table "
        f"baseline yet"
    )


def _row_needs_source_check(row: dict, *, strict_presence: bool):
    """True if check_images_source should compare this row's own
    basenames against the release_table baseline at all — a verifiable
    source_version_app always does; a blank one only does under
    `strict_presence` (see check_images_source's own docstring), never
    "UNKNOWN" (a value that WAS recorded but couldn't be parsed)."""
    source = row["source_version_app"]
    return is_verifiable_target(source) or (strict_presence and source == "")


def check_images_source(
    ref: ComponentRef, rows: list, comparison: Comparison, findings: dict, *, strict_presence: bool = False
):
    """The SOURCE-side sibling of check_images — mirrors its own two-tier
    resolution (basenames_under_scope, falling back to a plain find_
    matches search) exactly, but against `comparison.baseline` (see
    lib.release_baseline.resolve_baseline_chart_state) instead of
    `comparison.current`, comparing against each row's own
    source_version_app (see _check_image_source_pin). Only ever checks
    rows with a verifiable source (see is_verifiable_target) — a blank/
    UNKNOWN source means "nothing recorded yet at the release_table
    baseline", not a failure, so a genuinely-new-at-baseline image with a
    blank source is silently skipped, never flagged (unless
    `strict_presence` — see below). Never reports the "pinned but not
    tracked" direction check_images' own second loop does — that's
    inherently a target-side-only concept (a baseline snapshot has no
    release-table.csv row of its own to compare a whole CSV against).

    `strict_presence` (only ever True under --baseline-only — see verify-
    release-table-with-podiumd's own module docstring) widens the
    blank-source case specifically (never "UNKNOWN" — an unparseable
    value that WAS recorded, a different problem, not "nothing
    recorded"): instead of skipping it outright, runs the exact SAME
    resolve_at_baseline tier resolution the verifiable-source case
    already uses, and reports a new "-PRESENCE" finding if the basename
    resolves anyway (release-table.csv should have recorded a source
    version for it but never did) — silent only when it genuinely
    doesn't resolve at baseline (the correctly-justified blank) OR
    resolution itself couldn't be confirmed either way (the
    ambiguous-pull-failure tier below — "can't verify" is never treated
    as "confirmed justified").

    `comparison.current.lines` (the CURRENT values.yaml text, same as
    check_images' own) guards the baseline-side UNSCOPED fallback
    specifically: unlike the scoped tier (genuinely scoped to this
    component, never ambiguous across components), a bare find_matches_
    any_tag search is a whole-file basename search with no scope at all
    — legitimate for a real image that simply lives under a sibling
    scope at the baseline too (e.g. keycloak-config-cli, always under
    top-level "keycloak"), but NOT a license to accept any repository
    sharing that basename by coincidence (real bug, real data:
    global.images.redis, genuinely absent from values.yaml at
    podiumd-4.8.5, used to wrongly resolve to redis-operator's own,
    completely unrelated quay.io/opstree/redis pin at that same
    baseline, purely because both reduce to bare basename "redis" — see
    lib.image.version.repository_for_basename_in_scope's own
    docstring). Before accepting an unscoped baseline match, this
    resolves <ref.scope_key, basename>'s own real repository in the
    CURRENT chart (repository_for_basename_in_scope, the same
    scoped-then-unscoped tier, against `comparison.current.lines`
    instead of baseline lines) and only keeps a baseline candidate whose
    OWN repository matches it (stripped, see lib.chart.
    strip_registry_host — same convention historical_app_version_for_
    path's own expected_url cross-check uses, applied here to two raw
    values.yaml pins instead of a values-tree path and a historical
    manifest entry). No trustworthy CURRENT-side repository to check
    against at all (nothing resolves, or more than one distinct
    repository does) rejects the fallback outright — never falls back to
    the old, unguarded whole-file match, the same "can't verify, don't
    guess" discipline the other two collision fixes already apply.

    `ref.dep` (None by default — a caller with no Chart.yaml dependency
    at all, e.g. a MULTIPLE row or a bare top-level values.yaml key,
    simply never needs this) enables ONE more fallback, after both the
    scoped and unscoped tiers above have found nothing: real cases
    confirmed live at podiumd-4.8.5 (brp-personen-mock, clamav, kiss's
    own crawler, objecten, open-klant, zaakbrug) had only an explicit
    "tag:" for their own primary image at that baseline, no
    "repository:" override at all — relying entirely on their vendored
    subchart's own default repository (the exact same fallback primary_
    image_basename already uses on the CURRENT side, via lib.chart.
    primary_image_repositories) — so neither basenames_under_scope_
    any_tag nor find_matches_any_tag can compute a basename for that pin
    at all (both require a resolvable "repository:" to derive one from
    — see find_matches' own docstring), even though a real, comparable
    version genuinely is sitting right there in comparison.baseline.
    values's own text. Before concluding "wasn't pinned anywhere", this
    resolves the baseline dependency's own primary image repositories at
    ITS OWN historical chart version (resolved by primary_image_
    repositories via resolve_chart_values — allow_pull=True, UNLIKE the
    current-side lookup: the baseline's own historical chart version
    usually isn't vendored under chart_dir/charts any more, so a live
    `helm pull` is the only way to ever resolve it, same as update-
    component-version's own pre-write verification gate); if one of
    those paths' own repository resolves to this exact `basename`, the
    ACTUAL version comes from PODIUMD's OWN comparison.baseline.values
    at that same path's "tag" field (never the subchart's own default
    tag — that's not what was actually pinned). A pull failure (no
    network, or the version genuinely doesn't exist any more) is
    reported as its own "ambiguous" finding — can't verify, never
    silently forced into "wasn't pinned anywhere" (which would be
    actively wrong: something WAS pinned, this just couldn't confirm
    what) and never a crash."""
    if comparison.baseline is None:
        return  # no baseline, nothing to verify against (every caller already checks)
    resolver = _BaselineSourceResolver(ref, comparison.baseline, comparison.current)
    for row in rows:
        basenames = split_basenames(row["image_basename"])
        if not basenames:
            continue
        if not _row_needs_source_check(row, strict_presence=strict_presence):
            continue

        for basename in basenames:
            _check_image_source_pin(ref, row, basename, resolver.resolve_at_baseline, findings)


class _BaselineSourceResolver:
    """check_images_source's tier resolution of one ref's basenames at the
    release_table baseline (see that function's docstring). Pulls the
    baseline dependency's primary image repositories at most once."""

    def __init__(self, ref: ComponentRef, baseline: ChartState, current: ChartState):
        self.ref = ref
        self.baseline = baseline
        self.current = current
        self.baseline_basenames = basenames_under_scope_any_tag(baseline.lines, ref.scope_key)
        self.baseline_dep = (
            find_dependency(baseline.deps, ref.dep["name"]) if ref.dep is not None and baseline.deps else None
        )
        self._subchart_repos_state = None  # lazily filled: (repos, error) from primary_image_repositories

    def resolve_subchart_source(self, basename: str):
        """(version, None) from the subchart-default fallback, (None, error)
        when it can't be verified, (None, None) when it doesn't apply."""
        baseline = self.baseline
        if self.baseline_dep is None:
            return None, None
        if self._subchart_repos_state is None:
            self._subchart_repos_state = primary_image_repositories(
                baseline.chart_dir, self.baseline_dep, baseline.values, allow_pull=True
            )
        repos, error = self._subchart_repos_state
        matching_paths = [p for p, repo in repos.items() if repo and image_basename(repo) == basename]
        if matching_paths:
            tag = get_path(baseline.values, f"{self.ref.scope_key}.{matching_paths[0]}.tag")
            return (version_of(tag) if isinstance(tag, str) and tag else None), None
        if error and all(
            not get_path(baseline.values, f"{self.ref.scope_key}.{p}.repository")
            for p in image_paths_for(self.baseline_dep["name"], baseline.chart_dir)
        ):
            # No path resolved to `basename`, but the resolution itself
            # failed AND this dependency has no explicit override for
            # ANY of its own primary paths at this baseline — plausibly
            # THIS basename, genuinely unverifiable, never silently
            # treated as "confirmed absent".
            return None, error
        return None, None

    def _unscoped_fallback_pins(self, basename: str):
        """find_matches_any_tag pins for basename at the baseline, kept only
        when their repository matches basename's CURRENT scoped repository."""
        fallback_pins = find_matches_any_tag(self.baseline.lines, basename)
        if not fallback_pins:
            return fallback_pins
        current_repo = repository_for_basename_in_scope(self.current.lines, self.ref.scope_key, basename)
        return [
            p
            for p in fallback_pins
            if current_repo is not None
            and p["repository"]
            and strip_registry_host(p["repository"]) == strip_registry_host(current_repo)
        ]

    def resolve_at_baseline(self, basename: str):
        """The full tier resolution for `basename` at the release_table
        baseline, shared by both the verifiable-source comparison and the
        strict_presence blank-source check (so the two can never drift
        apart on what "resolves at baseline" means): ("found", version,
        source_label) once a real value is confirmed pinned somewhere
        (source_label distinguishes a real values.yaml pin from the
        subchart-default fallback, only for the mismatch message's own
        wording — see _check_image_source_pin); ("ambiguous", message)
        when resolution itself couldn't be confirmed either way (more
        than one distinct version pinned, or a subchart `helm pull`
        failure) — never treated as "confirmed absent" by either caller;
        ("absent",) only once every tier — scoped scan, cross-scope
        find_matches_any_tag with the repo cross-check, and the
        subchart-default fallback — has come up with nothing at all."""
        pins = self.baseline_basenames.get(basename)
        if pins is None:
            pins = self._unscoped_fallback_pins(basename) or None
        if pins is not None:
            versions = {p["version"] for p in pins}
            if len(versions) > 1:
                return (
                    "ambiguous",
                    (
                        f"'{basename}' under '{self.ref.scope_key}' is pinned at {len(versions)} different versions at "
                        f"the release_table baseline ({', '.join(sorted(versions))}) -- can't compare"
                    ),
                )
            return ("found", next(iter(versions)), "values.yaml")

        subchart_actual, subchart_error = self.resolve_subchart_source(basename)
        if subchart_error and self.baseline_dep is not None:
            return (
                "ambiguous",
                (
                    f"'{basename}' under '{self.ref.scope_key}' relies entirely on its vendored subchart's own "
                    f"default repository at the release_table baseline (no override in values.yaml there), but "
                    f"its historical chart version {self.baseline_dep['version']} couldn't be resolved to verify: "
                    f"{subchart_error}"
                ),
            )
        if subchart_actual is not None:
            return ("found", subchart_actual, "subchart-default values.yaml")
        return ("absent",)


def _check_dependency(
    dep: dict, rows_by_component: dict, comparison: Comparison, findings: dict, *, baseline_only: bool
):
    """One comparison.current.deps entry's own release-table.csv row(s) —
    the Chart.yaml-dependency-backed half of compare()'s own
    per-component dispatch, split out so compare() itself only ever
    branches on WHICH of its three row groups (multiple/dependency/
    bare-values-key) it's looking at, not on every check inside each
    one too."""
    state, baseline = comparison.current, comparison.baseline
    component = dep["name"]
    rows_for_component = rows_by_component.get(component, [])
    if not rows_for_component:
        alias_suffix = f" (alias '{dep['alias']}')" if dep.get("alias") else ""
        identifier = dep.get("alias") or component
        findings["missing_from_release_table"].append(
            f"[CHART] Chart.yaml dependency '{component}'{alias_suffix} has no release-table.csv row\n"
            f'      Confluence: add row to {GENERIC_TABLE_HINT} — Name or "Used by": "{identifier}" '
            f"(no existing row to read a section from)"
        )
        return
    ref = ComponentRef(dep.get("alias") or component, component, dep)
    if not baseline_only:
        check_chart_version(ref, rows_for_component, state, findings)
        check_images(ref, rows_for_component, state, findings)
    if baseline is not None:
        check_chart_version_source(dep, rows_for_component, baseline.deps, findings, strict_presence=baseline_only)
        check_images_source(ref, rows_for_component, comparison, findings, strict_presence=baseline_only)


def _check_unmatched_component(
    component: str, rows_for_component: list, comparison: Comparison, findings: dict, *, baseline_only: bool
):
    """One rows_by_component entry compare() itself couldn't match to any
    Chart.yaml dependency (see _check_dependency) — either a bare
    top-level values.yaml key with no separate chart (e.g.
    frankgateway), still checked for its own images via the plain text
    scan (see primary_image_basename — only the subchart-default
    fallback is unavailable here, since there's no vendored chart to
    resolve one from), or a component that genuinely doesn't exist
    anywhere in the current chart at all."""
    state, baseline = comparison.current, comparison.baseline
    if component in (state.values or {}):
        ref = ComponentRef(component, component)
        if not baseline_only:
            check_images(ref, rows_for_component, state, findings)
        if baseline is not None:
            check_images_source(ref, rows_for_component, comparison, findings, strict_presence=baseline_only)
        return
    for row in rows_for_component:
        findings["missing_from_chart"].append(
            f"[CHART] release-table row '{row['name']}' resolves to component '{component}', "
            f"which is not a Chart.yaml dependency or a top-level values.yaml key"
        )


def compare(rows: list, state: ChartState, baseline: ChartState | None = None, *, baseline_only: bool = False):
    """{"mismatches", "ambiguous", "missing_from_release_table",
    "missing_from_chart"}: str -> [str, ...], plus the separate list of
    rows whose component export-confluence-release-table never
    resolved at all (see UNRESOLVED_COMPONENTS) — see verify-release-
    table-with-podiumd's own module docstring.

    `state` (see ChartState) is the CURRENT chart — `state.chart_dir` is
    only ever consulted as a last resort, to resolve a component's
    primary image via its vendored subchart's own default repository
    (see primary_image_basename) — None simply disables that one
    fallback, which is all every test in this suite that doesn't care
    about it needs (never touches a real filesystem path either way).

    `baseline` (see ChartState/Comparison) is the SAME chart state, but
    as it actually was at the release_table baseline ref, for the new
    check_chart_version_source/check_images_source checks. None (the
    default) means "the release_table baseline itself couldn't be
    resolved (or was never given) at all, skip the source-side checks
    entirely" (the same None-means-"never attempted" convention
    lib.upgradedoc.resolve_component_row's own baseline_deps already
    uses), so a baseline-resolution FAILURE never gets treated as
    "genuinely empty baseline state" — which would otherwise flood every
    row with a false "didn't exist at baseline"/"wasn't pinned at
    baseline" finding instead of just skipping the new checks, exactly
    the silent-flood main() must never let happen (see verify-release-
    table-with-podiumd's own module docstring).

    `baseline_only` (see verify-release-table-with-podiumd's own module
    docstring --baseline-only) skips every target-side check_chart_
    version/check_images call for all three row groups below, and passes
    strict_presence=True through to check_chart_version_source/
    check_images_source instead of the default False — never changes
    whether those source-side checks run at all (still gated purely on
    `baseline` being resolved), only what they additionally verify once
    they do run."""
    findings = defaultdict(list)
    unresolved = []
    state = ChartState(state.chart_dir, state.deps, state.values if isinstance(state.values, dict) else {}, state.lines)
    comparison = Comparison(state, baseline)

    rows_by_component = defaultdict(list)
    multiple_rows = []
    for row in rows:
        component = row["component"]
        if component == MULTIPLE_KEY:
            multiple_rows.append(row)
        elif component in UNRESOLVED_COMPONENTS:
            unresolved.append(row)
        else:
            rows_by_component[component].append(row)

    # Called unconditionally (even with zero multiple_rows) so a global
    # image nobody's row ever resolved to at all still surfaces as
    # missing-from-release-table, not just silently unchecked.
    multiple_ref = ComponentRef(GLOBAL_IMAGES_SCOPE, MULTIPLE_KEY)
    if not baseline_only:
        check_images(multiple_ref, multiple_rows, state, findings)
    if baseline is not None:
        check_images_source(multiple_ref, multiple_rows, comparison, findings, strict_presence=baseline_only)

    checked_components = {dep["name"] for dep in state.deps}
    for dep in state.deps:
        _check_dependency(dep, rows_by_component, comparison, findings, baseline_only=baseline_only)

    for component, rows_for_component in rows_by_component.items():
        if component not in checked_components:
            _check_unmatched_component(component, rows_for_component, comparison, findings, baseline_only=baseline_only)

    return dict(findings), unresolved
