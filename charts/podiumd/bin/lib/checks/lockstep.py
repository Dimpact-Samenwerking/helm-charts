"""Verify lib.chart's lockstep declarations hold in values.yaml/Chart.yaml.

Nothing else re-checks these claims, and this runs without an upgrade doc.

- find_lockstep_mismatches: a component with 2+ registered image/version paths must
  agree on one version (e.g. eck-elasticsearch.version + eck-kibana.version).
- find_chart_version_mismatches: a chart_version_lockstep component's Chart.yaml
  dependency version must equal its app version.
- find_embedded_mismatches: an embedded_version image tag (e.g.
  keycloak-config-cli "6.5.1-26.5.5") must embed a full version with the same major
  as the followed image, no newer than it.

All comparisons stay within one component: unrelated components sharing a version is normal.
"""

import re

from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.registered_paths import chart_lockstep_components
from lib.chart.registered_paths import component_image_paths
from lib.chart.registered_paths import component_version_paths
from lib.chart.registered_paths import embedded_version_images
from lib.chart.registered_paths import pin_paths_for
from lib.chart.values_tree_primitives import find_app_versions
from lib.chart.values_tree_primitives import find_dependency
from lib.chart.values_tree_primitives import text_at
from lib.chart.values_tree_primitives import values_key_of
from lib.chart.values_tree_primitives import version_of
from lib.upgradedoc.app_version_and_image_paths import actual_app_version
from lib.yaml_types import YamlMapping
from lib.yaml_types import load_yaml_mapping

# (component, values_key, [(path, version), ...]) of a group that disagrees.
type LockstepMismatch = tuple[str, str, list[tuple[str, str]]]


def find_lockstep_mismatches(deps: list[ChartDependency], values: YamlMapping | None) -> list[LockstepMismatch]:
    """[(component, values_key, [(path, version), ...])] for multi-path components that disagree.

    Only paths with an explicit value are compared or listed (relying on the vendored
    default is a legitimate choice). Components with fewer than two such paths, or no
    matching Chart.yaml dependency, are skipped.
    """
    findings: list[LockstepMismatch] = []
    components = {**component_image_paths(), **component_version_paths()}
    for component in components:
        dep = find_dependency(deps, component)
        if dep is None:
            continue
        values_key = values_key_of(dep)
        pinned = find_app_versions(values, values_key, pin_paths_for(component))
        resolved = [(path, version_of(tag)) for path, tag in pinned]
        if len({version for _, version in resolved}) > 1:
            findings.append((component, values_key, resolved))
    return findings


def find_chart_version_mismatches(
    deps: list[ChartDependency], values: YamlMapping | None
) -> list[tuple[str, str, str, str]]:
    """[(component, values_key, chart_version, app_version)] where the two disagree.

    The app version is actual_app_version's (image paths, then version paths).
    Components without an app version or dependency are skipped.
    """
    findings: list[tuple[str, str, str, str]] = []
    for component in sorted(chart_lockstep_components()):
        dep = find_dependency(deps, component)
        mismatch = None if dep is None else _chart_version_mismatch(dep, values, component)
        if mismatch is not None:
            findings.append(mismatch)
    return findings


def _chart_version_mismatch(
    dep: ChartDependency, values: YamlMapping | None, component: str
) -> tuple[str, str, str, str] | None:
    """find_chart_version_mismatches' finding for one component, or None."""
    values_key = values_key_of(dep)
    pinned = actual_app_version(values, values_key, component)
    if pinned is None:
        return None
    app_version = version_of(pinned)
    chart_version = str(dep.get("version", ""))
    if chart_version and app_version != chart_version:
        return component, values_key, chart_version, app_version
    return None


EMBEDDED_VERSION_RE = re.compile(r"-(\d+)\.(\d+)\.(\d+)$")
PLAIN_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _version_parts(match: re.Match[str] | None) -> tuple[int, int, int] | None:
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def find_embedded_mismatches(values: YamlMapping | None) -> list[tuple[str, str]]:
    """[(path, problem)] for every embedded_version_images() tag that doesn't embed a full
    version (e.g. floating "6.5.1-26"), embeds a different major, or a newer one.
    Entries without a tag are skipped."""
    findings: list[tuple[str, str]] = []
    base = values if isinstance(values, dict) else {}
    for path, followed_path in sorted(embedded_version_images().items()):
        tag = text_at(base, f"{path}.tag")
        followed_tag = text_at(base, f"{followed_path}.tag")
        if not tag or not followed_tag:
            continue
        problem = _embedded_version_problem(version_of(tag), followed_path, version_of(followed_tag))
        if problem is not None:
            findings.append((path, problem))
    return findings


def _embedded_version_problem(own: str, followed_path: str, followed: str) -> str | None:
    """What is wrong with the version the tag `own` embeds, given the followed image's version."""
    embedded_parts = _version_parts(EMBEDDED_VERSION_RE.search(own))
    followed_parts = _version_parts(PLAIN_VERSION_RE.match(followed))
    if embedded_parts is None:
        return f"tag {own} embeds no full MAJOR.MINOR.PATCH version"
    if followed_parts is None:
        return f"{followed_path} version {followed} is not a plain MAJOR.MINOR.PATCH"
    if embedded_parts[0] != followed_parts[0]:
        return f"tag {own} is built for major {embedded_parts[0]}, {followed_path} runs {followed}"
    if embedded_parts > followed_parts:
        return f"tag {own} is built for a newer version than {followed_path} {followed}"
    return None


def check_lockstep_versions(chart_dir: Path):
    """Report every lockstep, chart-version and embedded-version mismatch."""
    deps = load_chart_dependencies(chart_dir / "Chart.yaml")
    values = load_yaml_mapping(chart_dir / "values.yaml")

    path_mismatches = find_lockstep_mismatches(deps, values)
    chart_version_mismatches = find_chart_version_mismatches(deps, values)
    embedded_mismatches = find_embedded_mismatches(values)
    total = len(path_mismatches) + len(chart_version_mismatches) + len(embedded_mismatches)

    if not total:
        print("OK: every registered lockstep group agrees on one version")
        return True, "0 mismatch(es)"

    if path_mismatches:
        _print_path_mismatches(path_mismatches)
    if chart_version_mismatches:
        _print_chart_mismatches(chart_version_mismatches)
    if embedded_mismatches:
        _print_embedded_mismatches(embedded_mismatches)
    return False, f"{total} mismatch(es)"


def _print_path_mismatches(path_mismatches: list[LockstepMismatch]) -> None:
    print(
        f"Found {len(path_mismatches)} co-equal image/version group(s) that disagree on version "
        f"(see lib.chart.component_image_paths()/component_version_paths()):"
    )
    for component, values_key, resolved in path_mismatches:
        print(f"  {component} ({values_key}):")
        for path, version in resolved:
            print(f"    {values_key}.{path}: {version}")


def _print_chart_mismatches(chart_version_mismatches: list[tuple[str, str, str, str]]) -> None:
    print(
        f"Found {len(chart_version_mismatches)} component(s) whose Chart.yaml version disagrees with its "
        f"own image version (component_resolution.chart_version_lockstep_components in etc/settings.yaml):"
    )
    for component, values_key, chart_version, app_version in chart_version_mismatches:
        print(f"  {component}: Chart.yaml version {chart_version} != {values_key} image version {app_version}")


def _print_embedded_mismatches(embedded_mismatches: list[tuple[str, str]]) -> None:
    print(
        f"Found {len(embedded_mismatches)} image(s) whose tag embeds a version that disagrees with the "
        f"image it is built against (see lib.chart.embedded_version_images()):"
    )
    for path, problem in embedded_mismatches:
        print(f"  {path}: {problem}")
