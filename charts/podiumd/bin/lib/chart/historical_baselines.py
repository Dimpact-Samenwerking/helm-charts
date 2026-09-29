"""Past-release images-manifest lookups and the shared two-tier baseline-tag resolution."""

import re

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lib.chart.chart_yaml import ChartDependency
from lib.chart.repo_and_path_resolution import full_repository_for_path
from lib.chart.repo_and_path_resolution import paths_by_repository
from lib.chart.repo_and_path_resolution import repo_group_representative
from lib.chart.repo_and_path_resolution import repository_group_key
from lib.images_manifest import try_parse_images_manifest
from lib.yaml_types import YamlMapping

# A bare MAJOR.MINOR.PATCH version; callers reject anything else up front.
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def historical_images_manifest_paths(chart_dir: Path | None, at_or_before: str | None = None) -> list[Path]:
    """This chart's docs/images/images-X.Y.Z.yaml files, most recent first.

    Each lists only that release's changes. `at_or_before` excludes later
    versions, including the in-progress target's own manifest (feeding it
    back in would be circular). Non-release names such as
    images-baseline.yaml are skipped.
    """
    if chart_dir is None:
        return []
    images_dir = chart_dir / "docs" / "images"
    if not images_dir.is_dir():
        return []
    limit = tuple(int(p) for p in at_or_before.split(".")) if at_or_before and SEMVER_RE.match(at_or_before) else None
    dated: list[tuple[tuple[int, ...], Path]] = []
    for path in images_dir.glob("images-*.yaml"):
        m = re.match(r"^images-(\d+\.\d+\.\d+)\.yaml$", path.name)
        if not m:
            continue
        version_tuple = tuple(int(p) for p in m.group(1).split("."))
        if limit is not None and version_tuple > limit:
            continue
        dated.append((version_tuple, path))
    dated.sort(key=lambda pair: pair[0], reverse=True)
    return [path for _version_tuple, path in dated]


def historical_app_version_for_repository(
    chart_dir: Path | None, repo: str, at_or_before: str | None = None, expected_url: str | None = None
) -> str | None:
    """The most recent version `repo` (a group key) was pinned to in a past manifest, or None.

    An entry matches on its "name:" or on its "url:"'s group key, so an older
    "python" entry matches "library/python". Matching on repository alone
    lets an image that is new to Chart.yaml/values.yaml but was used in an
    earlier release render a real "X -> Y" transition.

    expected_url, when given, must equal the entry's "url:": different
    images can strip to the same name (bare "redis" vs quay.io/opstree/redis).
    An entry without "url:" then never matches.
    """
    for path in historical_images_manifest_paths(chart_dir, at_or_before):
        for entry in try_parse_images_manifest(path.read_text(encoding="utf-8")) or []:
            url = entry.get("url")
            if entry["name"] != repo and not (isinstance(url, str) and repository_group_key(url) == repo):
                continue
            if expected_url is not None and entry.get("url") != expected_url:
                continue
            return str(entry.get("version"))
    return None


def historical_app_version_for_path(
    chart_dir: Path | None,
    deps: list[ChartDependency],
    values: YamlMapping,
    path: tuple[str, ...],
    at_or_before: str | None = None,
) -> str | None:
    """historical_app_version_for_repository for `path`'s resolved repository.

    Cross-checks against `path`'s current fully-qualified repository; None
    (no name-only fallback) when that can't be resolved.
    """
    repo_groups = paths_by_repository(chart_dir, deps, values, [path])
    repo = next(iter(repo_groups), None)
    if repo is None:
        return None
    expected_url = full_repository_for_path(chart_dir, deps, values, path)
    if expected_url is None:
        return None
    return historical_app_version_for_repository(chart_dir, repo, at_or_before, expected_url=expected_url)


# Read-only properties so a dict attribute matches; pylint counts a Protocol
# as a class and wants docstrings on the stubs.
class BaselineSetup(Protocol):  # pylint: disable=too-few-public-methods
    """What baseline_lookup reads from a caller's baseline bundle."""

    @property
    def baseline_paths(self) -> Mapping[tuple[str, ...], str | None]: ...  # pylint: disable=missing-function-docstring

    @property
    def baseline_repo_groups(self) -> Mapping[str, list[tuple[str, ...]]]: ...  # pylint: disable=missing-function-docstring


@dataclass
class BaselineLookup:
    """The per-run inputs of baseline_tag_for_sidecar_path, computed once rather than per path."""

    chart_dir: Path | None
    deps: list[ChartDependency]
    target_values: YamlMapping
    baseline_values: YamlMapping | None
    baseline_paths: Mapping[tuple[str, ...], str | None]
    baseline_repo_groups: Mapping[str, list[tuple[str, ...]]]


def baseline_lookup(
    chart_dir: Path | None,
    deps: list[ChartDependency],
    target_values: YamlMapping,
    baseline_values: YamlMapping | None,
    baseline_setup: BaselineSetup,
) -> BaselineLookup:
    """A BaselineLookup from the chart context plus a caller's baseline_paths/baseline_repo_groups bundle."""
    return BaselineLookup(
        chart_dir,
        deps,
        target_values,
        baseline_values,
        baseline_setup.baseline_paths,
        baseline_setup.baseline_repo_groups,
    )


def baseline_tag_for_sidecar_path(lookup: BaselineLookup, path: tuple[str, ...]) -> str | None:
    """The baseline (pre-upgrade) tag for a sidecar/shared-image or bare-version values-tree `path`.

    Shared by the "Component versions" table, the upgrade doc's Changes
    headings and the images-manifest entry comments so they cannot disagree.

    1. Exact path: `baseline_paths` pins `path` itself. Uses the caller's
       {path: tag} map rather than get_path, so it also works for bare
       version fields that have no ".tag" key.
    2. Same repository, different path: `path`'s current repository is
       pinned elsewhere in baseline_values (e.g. two postgres pins merged
       into one global.images.postgres anchor). The fully-qualified
       repository must match; several candidates are resolved with
       repo_group_representative.

    None when neither tier matches; the past-manifest fallback
    (historical_app_version_for_path) is the caller's separate next step.
    """
    if not lookup.baseline_values:
        return None
    exact_tag = lookup.baseline_paths.get(path)
    if isinstance(exact_tag, str) and exact_tag:
        return exact_tag.split("@", 1)[0]
    repo_groups = paths_by_repository(lookup.chart_dir, lookup.deps, lookup.target_values, [path])
    repo = next(iter(repo_groups), None)
    candidates = lookup.baseline_repo_groups.get(repo) if repo is not None else None
    if not candidates:
        return None
    # Compare fully-qualified repositories: stripped names can collide.
    expected_url = full_repository_for_path(lookup.chart_dir, lookup.deps, lookup.target_values, path)
    matching = [
        p
        for p in candidates
        if expected_url is not None
        and full_repository_for_path(lookup.chart_dir, lookup.deps, lookup.baseline_values, p) == expected_url
    ]
    if not matching:
        return None
    representative = repo_group_representative(matching, lookup.deps)
    representative_tag = lookup.baseline_paths.get(representative)
    return representative_tag.split("@", 1)[0] if representative_tag else None
