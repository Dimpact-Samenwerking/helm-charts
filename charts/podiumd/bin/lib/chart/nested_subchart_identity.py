"""Nested-subchart identity: resolving a component\'s registered
version-path-to-nested-sub-subchart mapping, and reading that nested
sub-subchart\'s own vendored files (raw text / documented image
repository) for a path settings.yaml registers this way."""

import re

from pathlib import Path

from lib.chart.values_tree_primitives import values_key_of
from lib.chart.vendored_files import vendored_chart_file
from lib.settings import component_resolution_version_path_nested_subcharts
from lib.settings import component_resolution_version_repository_paths


def version_repository_path_for(component: str, chart_dir: Path | None):
    """The registered version_paths_for-shaped field settings.yaml's own
    component_resolution.version_repository_paths maps `component` to (see
    lib.settings.component_resolution_version_repository_paths), or None
    if `component` has no such registration, or if chart_dir itself is
    None (some callers tolerate not having one in scope)."""
    if chart_dir is None:
        return None
    return component_resolution_version_repository_paths(chart_dir).get(component)


# component -> {relative version_paths_for-shaped field: nested
# sub-subchart name} — now lives in charts/podiumd/etc/settings.yaml's
# own "component_resolution.version_path_nested_subcharts" (see lib.
# settings.component_resolution_version_path_nested_subcharts and that
# file's own comment for the eck-stack/ECK-operator reasoning).
# nested_subchart_name_for below shares version_repository_path_for's
# own 4 chart_dir-bearing call sites (and its same chart_dir=None
# tolerance — see that function's own docstring), so it's an ordinary
# required parameter too.
def nested_subchart_name_for(component: str, rel_path: str, chart_dir: Path | None):
    """The nested sub-subchart name registered for `component`'s
    `rel_path` (a relative version_paths_for-shaped field) in settings.
    yaml's own component_resolution.version_path_nested_subcharts, or
    None if that exact (component, rel_path) pair isn't registered, or if
    chart_dir itself is None."""
    if chart_dir is None:
        return None
    return component_resolution_version_path_nested_subcharts(chart_dir).get(component, {}).get(rel_path)


def nested_subchart_registered_paths(component: str, chart_dir: Path | None = None):
    """Every relative version_paths_for-shaped field settings.
    yaml's own component_resolution.version_path_nested_subcharts
    registers a nested sub-subchart for, whether or not component_
    version_paths itself ALSO lists it — eck-stack's own "eck-
    enterprise-search.version" is a real, matchable image (see lib.
    upgradedoc.find_component_version_tags) that component_version_
    paths deliberately excludes from its narrower "pick ONE
    representative app version" list (disabled by default), so it's
    registered here but not there.

    Unlike version_repository_path_for/nested_subchart_name_for above
    (whose 4 call sites all already have chart_dir in scope), this
    one's own caller (lib.upgradedoc.find_component_version_tags) has
    no chart_dir at all, itself called from find_all_image_and_version_
    paths — 9+ call sites across 5 files, several levels removed from
    any chart_dir-bearing function. Self-resolves via Path(__file__).
    parents[2] by default (same pattern as lib.chart.chart_version_
    lockstep_components), while still accepting an explicit override
    for tests."""
    chart_dir = chart_dir or Path(__file__).resolve().parents[2]
    return list(component_resolution_version_path_nested_subcharts(chart_dir).get(component, {}))


DOCUMENTED_IMAGE_RE = re.compile(r"^#\s*image:\s*([^\s:@]+)", re.MULTILINE)


def nested_subchart_raw_text(
    chart_dir: Path, dep: dict, nested_chart_name: str, filename: str, version: str | None = None
):
    """Raw text of a file inside a NESTED sub-subchart bundled within
    dep's own vendored .tgz (e.g. eck-stack's own "charts/
    eck-elasticsearch/values.yaml") — same vendored-.tgz-only lookup
    subchart_values uses for a top-level dependency's own file, one
    directory level deeper. None if that exact version isn't vendored,
    or the nested chart/file doesn't exist inside it at that path."""
    raw = vendored_chart_file(chart_dir, dep, f"charts/{nested_chart_name}/{filename}", version)
    if raw is None:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def nested_subchart_documented_image_repository(
    chart_dir: Path, dep: dict, nested_chart_name: str, version: str | None = None
):
    """The repository half of a nested sub-subchart's own commented-out
    "# image: <repo>[:<tag>][@sha256:...]" default — the FIRST such
    comment in its own values.yaml, always right under its own
    "# <Name> Docker image to deploy." header, in every ECK-family
    sub-subchart observed so far. Not a live field (podiumd leaves the
    real "image:" key unset so the ECK operator picks its own internal
    default for the pinned "version:") — this is the chart maintainers'
    own documented example of what that default resolves to, the only
    place the real upstream repository is recorded at all. None if the
    subchart isn't vendored at that path, or has no such comment."""
    text = nested_subchart_raw_text(chart_dir, dep, nested_chart_name, "values.yaml", version=version)
    if text is None:
        return None
    m = DOCUMENTED_IMAGE_RE.search(text)
    return m.group(1) if m else None


def documented_repository_for_path(chart_dir: Path | None, deps: list, path: tuple[str, ...]):
    """The FULL, unstripped repository a COMPONENT_VERSION_PATH_NESTED_
    SUBCHARTS-registered path resolves to (e.g. "docker.elastic.co/
    elasticsearch/elasticsearch") via nested_subchart_documented_image_
    repository — the exact same "nested subchart" resolution paths_by_
    repository's own third fallback branch uses internally, exposed
    here on its own for a caller that needs the repository in a form a
    REAL registry call can use (parse_repo/registry_tag_exists) —
    paths_by_repository/repository_path_map only ever need the
    STRIPPED form (strip_registry_host) for repo-group matching, never
    this. None if `path` doesn't resolve through a registered nested
    subchart at all, or that subchart isn't vendored at chart_dir."""
    if not path:
        return None
    by_values_key = {values_key_of(dep): dep for dep in deps}
    dep = by_values_key.get(path[0])
    if dep is None or chart_dir is None:
        return None
    nested_chart_name = nested_subchart_name_for(dep["name"], ".".join(path[1:]), chart_dir)
    if not nested_chart_name:
        return None
    return nested_subchart_documented_image_repository(chart_dir, dep, nested_chart_name)
