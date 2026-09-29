"""Verify lib.chart's lockstep declarations hold in values.yaml/Chart.yaml.

Nothing else re-checks these claims, and this runs without an upgrade doc.

- find_lockstep_mismatches: a component with 2+ registered image/version paths must
  agree on one version (e.g. eck-elasticsearch.version + eck-kibana.version).
- find_chart_version_mismatches: a chart_version_lockstep component's Chart.yaml
  dependency version must equal its app version.
- find_embedded_version_mismatches: an embedded_version image tag (e.g.
  keycloak-config-cli "6.5.1-26.5.5") must embed a full version with the same major
  as the followed image, no newer than it.

All comparisons stay within one component: unrelated components sharing a version is normal.
"""

import re

from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.registered_paths import chart_version_lockstep_components
from lib.chart.registered_paths import component_image_paths
from lib.chart.registered_paths import component_version_paths
from lib.chart.registered_paths import embedded_version_images
from lib.chart.registered_paths import image_paths_for
from lib.chart.registered_paths import version_paths_for
from lib.chart.values_tree_primitives import find_dependency
from lib.chart.values_tree_primitives import text_at
from lib.chart.values_tree_primitives import values_key_of
from lib.chart.values_tree_primitives import version_of
from lib.yaml_types import YamlMapping
from lib.yaml_types import load_yaml_mapping


def find_lockstep_mismatches(
    deps: list[ChartDependency], values: YamlMapping | None
) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """[(component, values_key, [(path, version), ...])] for multi-path components that disagree.

    Only paths with an explicit value are compared or listed (relying on the vendored
    default is a legitimate choice). Components with fewer than two such paths, or no
    matching Chart.yaml dependency, are skipped.
    """
    entries = [(name, paths, True) for name, paths in component_image_paths().items() if len(paths) >= 2] + [
        (name, paths, False) for name, paths in component_version_paths().items() if len(paths) >= 2
    ]

    findings: list[tuple[str, str, list[tuple[str, str]]]] = []
    for component, paths, is_image_paths in entries:
        dep = find_dependency(deps, component)
        if dep is None:
            continue
        values_key = values_key_of(dep)
        base = values.get(values_key, {}) if isinstance(values, dict) else {}

        resolved: list[tuple[str, str]] = []
        for path in paths:
            raw = text_at(base, f"{path}.tag" if is_image_paths else path)
            if isinstance(raw, str) and raw:
                resolved.append((path, version_of(raw)))

        if len({version for _, version in resolved}) > 1:
            findings.append((component, values_key, resolved))
    return findings


def find_chart_version_mismatches(
    deps: list[ChartDependency], values: YamlMapping | None
) -> list[tuple[str, str, str, str]]:
    """[(component, values_key, chart_version, app_version)] where the two disagree.

    App version resolves like lib.upgradedoc.actual_app_version (image paths, then
    version paths). Components without an app version or dependency are skipped.
    """
    findings: list[tuple[str, str, str, str]] = []
    for component in sorted(chart_version_lockstep_components()):
        dep = find_dependency(deps, component)
        if dep is None:
            continue
        values_key = values_key_of(dep)
        base = values.get(values_key, {}) if isinstance(values, dict) else {}

        app_version = None
        for path in image_paths_for(component):
            tag = text_at(base, f"{path}.tag")
            if tag:
                app_version = version_of(tag)
                break
        if app_version is None:
            for path in version_paths_for(component):
                version = text_at(base, path)
                if isinstance(version, str) and version:
                    app_version = version_of(version)
                    break
        if app_version is None:
            continue

        chart_version = str(dep.get("version", ""))
        if chart_version and app_version != chart_version:
            findings.append((component, values_key, chart_version, app_version))
    return findings


EMBEDDED_VERSION_RE = re.compile(r"-(\d+)\.(\d+)\.(\d+)$")
PLAIN_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _version_parts(match: re.Match[str] | None) -> tuple[int, int, int] | None:
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def find_embedded_version_mismatches(values: YamlMapping | None) -> list[tuple[str, str]]:
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
        own = version_of(tag)
        followed = version_of(followed_tag)
        embedded_parts = _version_parts(EMBEDDED_VERSION_RE.search(own))
        followed_parts = _version_parts(PLAIN_VERSION_RE.match(followed))
        if embedded_parts is None:
            problem = f"tag {own} embeds no full MAJOR.MINOR.PATCH version"
        elif followed_parts is None:
            problem = f"{followed_path} version {followed} is not a plain MAJOR.MINOR.PATCH"
        elif embedded_parts[0] != followed_parts[0]:
            problem = f"tag {own} is built for major {embedded_parts[0]}, {followed_path} runs {followed}"
        elif embedded_parts > followed_parts:
            problem = f"tag {own} is built for a newer version than {followed_path} {followed}"
        else:
            continue
        findings.append((path, problem))
    return findings


def check_lockstep_versions(chart_dir: Path):
    """Report every lockstep, chart-version and embedded-version mismatch."""
    deps = load_chart_dependencies(chart_dir / "Chart.yaml")
    values = load_yaml_mapping(chart_dir / "values.yaml")

    path_mismatches = find_lockstep_mismatches(deps, values)
    chart_version_mismatches = find_chart_version_mismatches(deps, values)
    embedded_mismatches = find_embedded_version_mismatches(values)
    total = len(path_mismatches) + len(chart_version_mismatches) + len(embedded_mismatches)

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

    if embedded_mismatches:
        print(
            f"Found {len(embedded_mismatches)} image(s) whose tag embeds a version that disagrees with the "
            f"image it is built against (see lib.chart.embedded_version_images()):"
        )
        for path, problem in embedded_mismatches:
            print(f"  {path}: {problem}")

    return False, f"{total} mismatch(es)"
