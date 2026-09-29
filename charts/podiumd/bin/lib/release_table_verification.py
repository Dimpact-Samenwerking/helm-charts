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
  collision at export time) is skipped, like a blank component."""

from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from lib.chart.chart_yaml import ChartDependency
from lib.chart.pull_and_subchart_resolution import primary_image_repositories
from lib.chart.registered_paths import image_paths_for
from lib.chart.repo_and_path_resolution import repository_group_key
from lib.chart.values_tree_primitives import dotted_key_path
from lib.chart.values_tree_primitives import find_dependency
from lib.chart.values_tree_primitives import text_at
from lib.chart.values_tree_primitives import version_of
from lib.image.digests import DigestPin
from lib.image.digests import VersionPin
from lib.image.version import GLOBAL_IMAGES_SCOPE
from lib.image.version import MULTIPLE_KEY
from lib.image.version import basenames_under_scope_any_tag
from lib.image.version import find_matches_any_tag
from lib.image.version import image_basename
from lib.image.version import repository_for_basename_in_scope
from lib.release_table.csv_rows import ReleaseTableRow
from lib.release_table.state import ChartState
from lib.release_table.state import Comparison
from lib.release_table.state import ComponentRef
from lib.release_table.state import Observed
from lib.upgradedoc.app_version_and_image_paths import actual_app_version
from lib.upgradedoc.string_and_parsing_basics import normalize_version

UNRESOLVED_COMPONENTS = ("", "UNKNOWN")

# Finding category ("mismatches", "ambiguous", "missing_from_release_table",
# "missing_from_chart") -> its finding lines, as compare() collects them.
Findings = defaultdict[str, list[str]]
# What _SourceResolver.resolve_at_baseline found for one basename.
BaselineResolution = tuple[Literal["found"], str, str] | tuple[Literal["ambiguous"], str] | tuple[Literal["absent"]]


def split_basenames(value: str):
    """A comma-separated CSV basenames cell as a list, stripped, blanks dropped."""
    return [b.strip() for b in value.split(",") if b.strip()]


def is_verifiable_target(target: str):
    """False for a blank ("no planned change") or "UNKNOWN" (unparsable) target value."""
    return bool(target) and target != "UNKNOWN"


def report_mismatch(findings: Findings, tag: str, row: ReleaseTableRow, label: str, observed: Observed):
    """Append "[tag] name (label): release-table target <target> != <source> <actual>" to mismatches."""
    findings["mismatches"].append(
        f"[{tag}] {row['name']} ({label}): release-table target {observed.target} != "
        f"{observed.source_label} {observed.actual}"
    )


# Second line of a "missing_from_release_table" finding with no inferable section (e.g. a new dependency).
GENERIC_TABLE_HINT = "whichever table fits (Product/Common Ground/Overige/Technische component versies)"


TECHNISCHE_TABLE_HINT = '"Technische component versies"'


def confluence_table_hint(rows: list[ReleaseTableRow], component: str):
    """The Confluence table a missing row belongs in, read from the "section" of any of `rows`.

    Without rows: "Technische" for MULTIPLE_KEY (global.images entries go
    there by convention), else GENERIC_TABLE_HINT.
    """
    if rows:
        return f'"{rows[0]["section"]} component versies"'
    if component == MULTIPLE_KEY:
        return TECHNISCHE_TABLE_HINT
    return GENERIC_TABLE_HINT


def is_primary_image(component: str, lines: list[str], pin: DigestPin | VersionPin, chart_dir: Path | None = None):
    """Whether `pin` sits at one of `component`'s registered primary image paths.

    The same paths update-component-version's <app-version> writes
    (default ["image"]; multi-image components like zgw-office-addin
    register more). Anything else is a sidecar, which belongs on
    "Technische component versies" with "Used by". Not used for MULTIPLE_KEY.
    """
    path = dotted_key_path(lines, pin["line"] - 1).split(".")
    relative = ".".join(path[1:-1])
    return relative in image_paths_for(component, chart_dir)


def primary_image_basename(ref: ComponentRef, state: ChartState):
    """The basename of `ref.component`'s primary image (e.g. "openbao" for server.image), or None.

    Digest-pin text scan first; if empty and `ref.dep` is set, the
    subchart-default repository (primary_image_repositories,
    allow_pull=False) for images like openzaak's. None when unresolved or
    ambiguous; the "[IMAGE] ... not tracked" finding covers that case.
    """
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


def find_primary_row(ref: ComponentRef, state: ChartState, rows: list[ReleaseTableRow]):
    """The row whose image_basename is the component's primary basename, or None.

    The only row a chart version belongs next to (e.g. "OpenBao", not
    "OpenBao Schema Job (postgres)").
    """
    basename = primary_image_basename(ref, state)
    if basename is None:
        return None
    for row in rows:
        if basename in split_basenames(row["image_basename"]):
            return row
    return None


def chart_version_ever_tracked(rows: list[ReleaseTableRow]):
    """Whether any row has a verifiable target_version_helm or a non-blank source_version_helm.

    False means the chart version was never recorded, not merely unchanged.
    """
    return any(is_verifiable_target(row["target_version_helm"]) or row["source_version_helm"] for row in rows)


def row_app_version(row: ReleaseTableRow):
    """`row`'s verifiable target app version, else its source one, else ""."""
    target = row["target_version_app"]
    return target if is_verifiable_target(target) else row["source_version_app"]


def missing_chart_version_hint(ref: ComponentRef, state: ChartState, rows: list[ReleaseTableRow]):
    """Second line for a "[CHART] ... never recorded a Helm chart version" finding.

    Names the primary row (see find_primary_row). If that row's table has
    no Helm column ("Technische component versies"), spells out moving it
    to another table with its Name, Helm and App version; which table is
    left to a human. Says so if no primary row exists yet.
    """
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


def check_chart_version(ref: ComponentRef, rows: list[ReleaseTableRow], state: ChartState, findings: Findings):
    """Compare each row's target_version_helm (or, when blank, source) with Chart.yaml's current version.

    Also reports "missing_from_release_table" when no row ever recorded a
    chart version.
    """
    actual = str(ref.dep["version"]) if ref.dep else ""
    for row in rows:
        target = row["target_version_helm"]
        if is_verifiable_target(target):
            if target != actual:
                report_mismatch(findings, "CHART", row, ref.component, Observed(target, actual, "Chart.yaml"))
        else:
            # A blank target doesn't excuse a stale source: that's unrecorded drift.
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
    dep: ChartDependency,
    rows: list[ReleaseTableRow],
    baseline_deps: list[ChartDependency],
    findings: Findings,
    *,
    strict_presence: bool = False,
):
    """Compare each verifiable source_version_helm with `dep`'s version at the release_table baseline.

    A source version for a dependency absent at the baseline is its own
    finding. With `strict_presence` (--baseline-only), a dependency present
    at the baseline with no verifiable source on any row gets one
    "-PRESENCE" finding (per dependency: sidecar rows carry no chart version).
    """
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


def missing_image_hint(
    rows: list[ReleaseTableRow], ref: ComponentRef, basename: str, versions: set[str], *, primary: bool
):
    """Second line for an "[IMAGE] ... not tracked" finding: which table, and how to name the row.

    The export matches the bracketed part exactly: "<name> (<image
    basename>)" for a sidecar or MULTIPLE row (e.g. "ZAC Gotenberg
    (gotenberg)"), "<name> (<scope key>)" for a component's own row.

    A component's primary image goes on its existing row's table, without
    "Used by". A sidecar always goes on "Technische component versies"
    with "Used by" `ref.scope_key`: the only column that scopes a basename
    to a component, and only that table has it. MULTIPLE rows need no
    "Used by". `versions` are labelled App versions, since other tables
    split App/Helm sub-columns.
    """
    version_text = ", ".join(sorted(versions))
    if ref.component != MULTIPLE_KEY and not primary:
        where = TECHNISCHE_TABLE_HINT
        what = f'"Used by": "{ref.scope_key}", Name "<name> ({basename})"'
    else:
        where = confluence_table_hint(rows, ref.component)
        what = f'Name "<name> ({ref.scope_key if primary else basename})"'
    return f"Confluence: add row to {where} — {what}, App version (currently) {version_text}"


def _record_image_result(ref: ComponentRef, row: ReleaseTableRow, basename: str, actual: str, findings: Findings):
    """Compare one basename's single resolved version with the row (split out to limit nesting)."""
    target = row["target_version_app"]
    if is_verifiable_target(target):
        if actual != target:
            report_mismatch(
                findings, "IMAGE", row, f"{ref.component}.{basename}", Observed(target, actual, "values.yaml")
            )
        return
    # A blank target must not hide drift: compare the resolved pin against the recorded source.
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


def _unscoped_fallback_pins(
    ref: ComponentRef, state: ChartState, basename: str, findings: Findings
) -> tuple[list[VersionPin] | None, bool]:
    """(pins, ambiguous) for check_images' unscoped fallback: a basename is a
    repository identity, so it may be pinned under a sibling scope (e.g.
    keycloak-config-cli under "keycloak"). Ambiguous, with a finding
    recorded, when the matches span several repositories."""
    pins = find_matches_any_tag(state.lines, basename) or None
    repos = {repository_group_key(p["repository"]) for p in pins or [] if p["repository"]}
    if len(repos) > 1:
        findings["ambiguous"].append(
            f"[IMAGE] '{basename}' matches {len(repos)} different repositories outside "
            f"'{ref.scope_key}' own scope ({', '.join(sorted(repos))}) -- can't tell which one "
            f"this row means"
        )
        return pins, True
    return pins, False


def _check_primary_row_without_basename(
    ref: ComponentRef, rows: list[ReleaseTableRow], state: ChartState, findings: Findings, primary_basename: str | None
) -> None:
    """Compare the single blank-image_basename row with actual_app_version, if no other row claims the primary.

    Only when the row records an app version ("v" ignored).
    """
    if ref.component == MULTIPLE_KEY:
        return
    blank_rows = [row for row in rows if not split_basenames(row["image_basename"])]
    if len(blank_rows) != 1:
        return
    if primary_basename is not None and any(primary_basename in split_basenames(r["image_basename"]) for r in rows):
        return
    actual = actual_app_version(state.values, ref.scope_key, ref.component, state.chart_dir, ref.dep)
    row = blank_rows[0]
    target = row["target_version_app"]
    recorded = target if is_verifiable_target(target) else row["source_version_app"]
    if not actual or not is_verifiable_target(recorded):
        return
    if normalize_version(actual) == normalize_version(recorded):
        actual = recorded
    _record_image_result(ref, row, primary_basename or "primary image", actual, findings)


def check_images(ref: ComponentRef, rows: list[ReleaseTableRow], state: ChartState, findings: Findings):
    """Compare each row's target app version with the pinned version of its basenames.

    Basenames resolve scoped first, then unscoped (a sibling scope such as
    keycloak-config-cli under "keycloak"). Several versions or repositories
    give "ambiguous". Then every pinned basename under the scope that no row
    claims gets a "missing_from_release_table" finding with a hint.
    """
    actual_basenames = basenames_under_scope_any_tag(state.lines, ref.scope_key)
    csv_basenames: set[str] = set()
    # Resolved once per component (not per pin) — see primary_image_basename.
    primary_basename = None if ref.component == MULTIPLE_KEY else primary_image_basename(ref, state)

    for row in rows:
        basenames = split_basenames(row["image_basename"])
        if not basenames:
            continue

        for basename in basenames:
            csv_basenames.add(basename)
            pins = actual_basenames.get(basename)
            if pins is None:
                pins, ambiguous = _unscoped_fallback_pins(ref, state, basename, findings)
                if ambiguous:
                    continue
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

    _check_primary_row_without_basename(ref, rows, state, findings, primary_basename)

    for basename, pins in actual_basenames.items():
        if basename not in csv_basenames:
            versions = {p["version"] for p in pins}
            primary = ref.component != MULTIPLE_KEY and basename == primary_basename
            hint = missing_image_hint(rows, ref, basename, versions, primary=primary)
            findings["missing_from_release_table"].append(
                f"[IMAGE] '{ref.scope_key}' image '{basename}' is pinned in values.yaml but not tracked "
                f"in release-table.csv\n      {hint}"
            )


def _check_image_source_pin(
    ref: ComponentRef,
    row: ReleaseTableRow,
    basename: str,
    resolve_at_baseline: Callable[[str], BaselineResolution],
    findings: Findings,
):
    """Compare one basename with the release_table baseline (split out to limit locals and nesting)."""
    source = row["source_version_app"]
    verifiable_source = is_verifiable_target(source)
    result = resolve_at_baseline(basename)
    if result[0] == "ambiguous":
        findings["ambiguous"].append(f"[IMAGE-SOURCE] {result[1]}")
        return
    if not verifiable_source:
        # strict_presence: "found" means the blank source is unjustified; "absent" stays silent.
        if result[0] == "found":
            _, actual, label = result
            findings["mismatches"].append(
                f"[IMAGE-SOURCE-PRESENCE] {row['name']} ({ref.component}.{basename}): release-table "
                f"source_version_app is blank, but '{basename}' already existed at the release_table "
                f"baseline ({label} {actual}) — source_version_app was never filled in for this image"
            )
        return
    if result[0] == "found":
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


def _row_needs_source_check(row: ReleaseTableRow, *, strict_presence: bool):
    """Whether to check this row at the baseline: a verifiable source, or a blank one under strict_presence."""
    source = row["source_version_app"]
    return is_verifiable_target(source) or (strict_presence and source == "")


def check_images_source(
    ref: ComponentRef,
    rows: list[ReleaseTableRow],
    comparison: Comparison,
    findings: Findings,
    *,
    strict_presence: bool = False,
):
    """Compare each row's verifiable source_version_app with the pin at the release_table baseline.

    Blank or UNKNOWN sources are skipped, except that `strict_presence`
    (--baseline-only) reports "-PRESENCE" when a blank-source basename does
    resolve at the baseline. Unverifiable resolution is never "justified".

    The unscoped fallback only accepts a baseline pin whose repository
    matches the basename's current scoped repository: basenames collide
    (global.images.redis vs quay.io/opstree/redis). No trustworthy current
    repository rejects the fallback.

    With `ref.dep`, a last tier covers primary images without a
    "repository:" at the baseline (e.g. clamav at podiumd-4.8.5): the
    baseline chart version is pulled (allow_pull=True, rarely still
    vendored) to resolve its default repository; the version comes from
    podiumd's own baseline "tag". A pull failure is reported as
    "ambiguous", never as not pinned.
    """
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
    """Tier resolution of one ref's basenames at the baseline; pulls the subchart at most once."""

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
            tag = text_at(baseline.values, f"{self.ref.scope_key}.{matching_paths[0]}.tag")
            return (version_of(tag) if isinstance(tag, str) and tag else None), None
        if error and all(
            not text_at(baseline.values, f"{self.ref.scope_key}.{p}.repository")
            for p in image_paths_for(self.baseline_dep["name"], baseline.chart_dir)
        ):
            # Resolution failed and no primary path has an override: may be this basename, so unverifiable.
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
            and repository_group_key(p["repository"]) == repository_group_key(current_repo)
        ]

    def resolve_at_baseline(self, basename: str) -> BaselineResolution:
        """Resolve `basename` at the baseline, shared by the source comparison and strict_presence.

        ("found", version, source_label); ("ambiguous", message) when it
        can't be confirmed (several versions, pull failure); ("absent",)
        only when every tier found nothing.
        """
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
    dep: ChartDependency,
    rows_by_component: dict[str, list[ReleaseTableRow]],
    comparison: Comparison,
    findings: Findings,
    *,
    baseline_only: bool,
):
    """Run every check for one Chart.yaml dependency's rows."""
    state, baseline = comparison.current, comparison.baseline
    component = dep["name"]
    rows_for_component = rows_by_component.get(component, [])
    if not rows_for_component:
        alias = dep.get("alias")
        alias_suffix = f" (alias '{alias}')" if alias else ""
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
    component: str,
    rows_for_component: list[ReleaseTableRow],
    comparison: Comparison,
    findings: Findings,
    *,
    baseline_only: bool,
):
    """Check rows whose component isn't a dependency: a bare values.yaml key (images only), or missing."""
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


def compare(
    rows: list[ReleaseTableRow], state: ChartState, baseline: ChartState | None = None, *, baseline_only: bool = False
) -> tuple[dict[str, list[str]], list[ReleaseTableRow]]:
    """(findings by category, rows whose component the export never resolved).

    `state` is the current chart; state.chart_dir None disables only the
    subchart-default fallback. `baseline` None means the release_table
    baseline couldn't be resolved, so source-side checks are skipped rather
    than flooding "didn't exist at baseline" findings. `baseline_only`
    skips target-side checks and enables strict_presence.
    """
    findings: Findings = defaultdict(list)
    unresolved: list[ReleaseTableRow] = []
    state = ChartState(state.chart_dir, state.deps, state.values if isinstance(state.values, dict) else {}, state.lines)
    comparison = Comparison(state, baseline)

    rows_by_component: defaultdict[str, list[ReleaseTableRow]] = defaultdict(list)
    multiple_rows: list[ReleaseTableRow] = []
    for row in rows:
        component = row["component"]
        if component == MULTIPLE_KEY:
            multiple_rows.append(row)
        elif component in UNRESOLVED_COMPONENTS:
            unresolved.append(row)
        else:
            rows_by_component[component].append(row)

    # Even with no MULTIPLE rows, so an untracked global image is still reported.
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
