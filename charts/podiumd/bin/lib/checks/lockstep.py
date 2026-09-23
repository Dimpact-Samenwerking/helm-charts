"""Verifies two independent "lockstep" declarations lib.chart makes
about a component actually hold in values.yaml/Chart.yaml right now.
Registering either is a purely declarative claim; nothing else in this
codebase ever re-checks it holds — see each check function's own
docstring below for exactly what that means downstream. Both are
checked directly against values.yaml/Chart.yaml, independent of any
upgrade doc, so this also runs (and catches drift) on a branch with no
upgrade doc pair at all.

find_lockstep_mismatches — every lib.chart.component_image_paths()/
component_version_paths() entry registered with 2+ paths (lib.chart's
signal that those paths are co-equal images/versions meant to move
together, see either accessor's own docstring — e.g. kiss-chart's
frontend "image" + its own settings.syncJobs.image, eck-stack's
eck-elasticsearch.version + eck-kibana.version) must agree on ONE
version.

find_chart_version_mismatches — every lib.chart.chart_version_lockstep_
components() entry (settings.yaml's own signal that a component's
Chart.yaml dependency version and its own resolved app image version
are released as the SAME number) must agree with each other.

These are genuinely different things being checked, not two flavors of
the same one: find_lockstep_mismatches compares several values-tree
PATHS against EACH OTHER; find_chart_version_mismatches compares ONE
path against the Chart.yaml dependency's own "version:" field. Neither
ever compares across two different COMPONENTS, and neither ever uses a
dotted PATH STRING itself (or a shared version number between unrelated
components) as a group key — that's a different, weaker signal (lib.
upgradedoc's own same_group/images_manifest_entries_share_group) this
module has nothing to do with: two unrelated components coincidentally
sharing a version number is normal and not a mismatch — the exact
opposite mistake same_group's own docstring already warns against (the
kiss/kiss-elastic-sync precedent)."""

from pathlib import Path

from lib.chart.registered_paths import chart_version_lockstep_components
from lib.chart.registered_paths import component_image_paths
from lib.chart.registered_paths import component_version_paths
from lib.chart.registered_paths import image_paths_for
from lib.chart.registered_paths import version_paths_for
from lib.chart.release_baseline_basics import load_yaml
from lib.chart.values_tree_primitives import find_dependency
from lib.chart.values_tree_primitives import get_path
from lib.chart.values_tree_primitives import values_key_of
from lib.chart.values_tree_primitives import version_of


def find_lockstep_mismatches(deps: list, values: dict | None):
    """[(component, values_key, [(path, version), ...])] for every
    multi-path component_image_paths()/component_version_paths() entry
    whose resolved paths disagree on version. `resolved` only ever lists the
    paths that actually resolved to a version — the culprit(s) worth
    showing, not every registered path regardless of whether it even
    carries a value.

    A path with no explicit value at all (values.yaml relies entirely
    on the vendored chart's own default) is skipped, not treated as a
    mismatch — comparing "no override" against an explicit override
    would flag a legitimate config choice, not a real drift. A
    component where fewer than two of its registered paths carry an
    explicit value has nothing left to compare, so it's never reported
    either. A registered component with no matching Chart.yaml
    dependency (shouldn't happen — every current entry names a real
    dependency — but nothing here assumes it) is skipped the same way,
    rather than raising."""
    entries = [(name, paths, True) for name, paths in component_image_paths().items() if len(paths) >= 2] + [
        (name, paths, False) for name, paths in component_version_paths().items() if len(paths) >= 2
    ]

    findings = []
    for component, paths, is_image_paths in entries:
        dep = find_dependency(deps, component)
        if dep is None:
            continue
        values_key = values_key_of(dep)
        base = values.get(values_key, {}) if isinstance(values, dict) else {}

        resolved = []
        for path in paths:
            raw = get_path(base, f"{path}.tag" if is_image_paths else path)
            if isinstance(raw, str) and raw:
                resolved.append((path, version_of(raw)))

        if len({version for _, version in resolved}) > 1:
            findings.append((component, values_key, resolved))
    return findings


def find_chart_version_mismatches(deps: list, values: dict | None):
    """[(component, values_key, chart_version, app_version)] for every
    lib.chart.chart_version_lockstep_components() entry whose Chart.yaml
    dependency "version:" disagrees with its own resolved app version. Resolution
    order — first image_paths_for(component) candidate with a real tag,
    else first version_paths_for(component) candidate with a real value
    — is the exact same "first candidate wins" order lib.upgradedoc.
    actual_app_version itself uses, so this never disagrees with what
    that call already treats as the component's current app version.

    A component with no resolvable app version at all (relies entirely
    on its vendored chart's own appVersion default) has nothing to
    compare, so it's skipped, not reported. Same for a registered
    component with no matching Chart.yaml dependency at all."""
    findings = []
    for component in sorted(chart_version_lockstep_components()):
        dep = find_dependency(deps, component)
        if dep is None:
            continue
        values_key = values_key_of(dep)
        base = values.get(values_key, {}) if isinstance(values, dict) else {}

        app_version = None
        for path in image_paths_for(component):
            tag = get_path(base, f"{path}.tag")
            if tag:
                app_version = version_of(tag)
                break
        if app_version is None:
            for path in version_paths_for(component):
                version = get_path(base, path)
                if isinstance(version, str) and version:
                    app_version = version_of(version)
                    break
        if app_version is None:
            continue

        chart_version = str(dep.get("version", ""))
        if chart_version and app_version != chart_version:
            findings.append((component, values_key, chart_version, app_version))
    return findings


def check_lockstep_versions(chart_dir: Path):
    """Runs find_lockstep_mismatches and find_chart_version_mismatches
    against chart_dir's own Chart.yaml/values.yaml and reports every
    mismatch found."""
    chart_yaml = load_yaml(chart_dir / "Chart.yaml")
    deps = chart_yaml.get("dependencies", [])
    values = load_yaml(chart_dir / "values.yaml") or {}

    path_mismatches = find_lockstep_mismatches(deps, values)
    chart_version_mismatches = find_chart_version_mismatches(deps, values)
    total = len(path_mismatches) + len(chart_version_mismatches)

    if not total:
        print("OK: every registered lockstep group agrees on one version")
        return True, "0 mismatch(es)"

    if path_mismatches:
        print(
            f"Found {len(path_mismatches)} co-equal image/version group(s) that disagree on version "
            f"(see lib.chart.component_image_paths()/component_version_paths()):"
        )
        for component, values_key, resolved in path_mismatches:
            print(f"  {component} ({values_key}):")
            for path, version in resolved:
                print(f"    {values_key}.{path}: {version}")

    if chart_version_mismatches:
        print(
            f"Found {len(chart_version_mismatches)} component(s) whose Chart.yaml version disagrees with its "
            f"own image version (see lib.chart.chart_version_lockstep_components()):"
        )
        for component, values_key, chart_version, app_version in chart_version_mismatches:
            print(f"  {component}: Chart.yaml version {chart_version} != {values_key} image version {app_version}")

    return False, f"{total} mismatch(es)"
