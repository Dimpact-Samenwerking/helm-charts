"""Image digest-pinning checks for values.yaml.

check_digest_pinning (filesystem only): every "image: {tag: ...}" in values.yaml must
be "<version>@sha256:<64-hex>", so a tag can't drift and the text-based digest tooling
can see the pin. Exceptions (digest_pinning.exceptions in etc/settings.yaml):
keycloak-operator operator.image and operator.config.keycloakImage (separate "sha:"
field; a digest in "tag" would double it), eck-operator image (separate "digest:"
field), and omc (its subchart can't handle a digest-pinned tag).

check_shared_image_usage and check_subchart_image_visibility are render-based.
"""

import re

from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.pull_and_subchart_resolution import global_image_paths
from lib.chart.pull_and_subchart_resolution import resolve_subchart_default
from lib.chart.pull_and_subchart_resolution import subchart_values
from lib.chart.repo_and_path_resolution import paths_by_repository
from lib.chart.repo_and_path_resolution import repository_group_key
from lib.chart.repo_and_path_resolution import subchart_template_text
from lib.chart.values_tree_primitives import find_dependency
from lib.chart.values_tree_primitives import get_path
from lib.chart.values_tree_primitives import resolve_values_path_source
from lib.chart.values_tree_primitives import text_at
from lib.chart.values_tree_primitives import values_key_of
from lib.render_scope import CHART_NAME
from lib.render_scope import render_chart
from lib.render_scope import rendered_chart_paths
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.app_version_and_image_paths import chart_image_paths
from lib.upgradedoc.app_version_and_image_paths import find_image_tag_paths
from lib.yaml_types import YamlMapping
from lib.yaml_types import load_yaml_mapping

# Suffix form of lib.image.digests.DIGEST_PIN_RE.
DIGEST_SUFFIX_RE = re.compile(r"@sha256:[0-9a-f]{64}$")

# Exempt fields live in etc/settings.yaml "digest_pinning.exceptions".

# A dotted values.yaml path as its keys, and repository -> the paths using it.
ValuesPath = tuple[str, ...]
RepoGroups = dict[str, list[ValuesPath]]
# A find_unresolved_subchart_images finding: (scope_key, subpath, tag, already_pinned).
SubchartImageFinding = tuple[str, str, str, bool]


def _deps_from_chart_yaml(chart_dir: Path):
    """Chart.yaml's "dependencies" list, or [] if Chart.yaml doesn't exist."""
    chart_yaml_path = chart_dir / "Chart.yaml"
    return load_chart_dependencies(chart_yaml_path) if chart_yaml_path.is_file() else []


def _repository_groups(chart_dir: Path, values: YamlMapping, deps: list[ChartDependency]) -> RepoGroups:
    """{stripped_repo: [path, ...]} for every image/version path in values.yaml.

    Static: says nothing about whether the path renders. Never report consumer counts
    from this alone; see _live_repository_groups.
    """
    return paths_by_repository(chart_dir, deps, values, chart_image_paths(values, deps).keys())


def _path_chart_tree_path(chart_dir: Path, deps: list[ChartDependency], path: tuple[str, ...]):
    """The chart-tree path that must render for `path` to be a live consumer.

    A path whose top-level key isn't a Chart.yaml dependency (apiproxy, keycloak,
    global.images.*) belongs to podiumd itself and is always live.
    """
    dep = find_dependency(deps, path[0])
    if dep is None:
        return CHART_NAME
    chart_tree_path, _version = resolve_subchart_default(chart_dir, dep, CHART_NAME, path[1:])
    return chart_tree_path


def _live_repository_groups(
    chart_dir: Path, deps: list[ChartDependency], values: YamlMapping, rendered_paths: set[str]
) -> RepoGroups:
    """_repository_groups(...) with every path whose chart-tree path didn't render removed.

    Needed because e.g. every Maykin "<name>.redis.image" configures a nested redis
    disabled via "tags: {redis: false}"; counted statically they inflate
    global.images.redis to 10 consumers instead of 0. Repositories left with no live
    path are dropped.
    """
    raw = _repository_groups(chart_dir, values, deps)
    live: RepoGroups = {}
    for repo, paths in raw.items():
        live_paths = [p for p in paths if _path_chart_tree_path(chart_dir, deps, p) in rendered_paths]
        if live_paths:
            live[repo] = live_paths
    return live


def _global_image_usage(values: YamlMapping, repo_groups: RepoGroups) -> dict[ValuesPath, list[ValuesPath]]:
    """{def_path: [consumer_path, ...]} for every global.images.* entry.

    Consumers are other paths with the same repository, excluding the definition itself.
    """
    usage: dict[ValuesPath, list[ValuesPath]] = {}
    for def_path, _tag in global_image_paths(values):
        repo = text_at(values, ".".join(def_path) + ".repository")
        stripped = repository_group_key(repo) if isinstance(repo, str) and repo else None
        consumers = [p for p in repo_groups.get(stripped, []) if p != def_path] if stripped else []
        usage[def_path] = consumers
    return usage


def _non_global_shared_repo_groups(
    values: YamlMapping, repo_groups: RepoGroups, global_usage: dict[ValuesPath, list[ValuesPath]]
) -> RepoGroups:
    """repo_groups minus global.images.* repositories and single-path repositories.

    The rest are incidentally shared: always informational.
    """
    claimed: set[str] = set()
    for def_path in global_usage:
        repo = text_at(values, ".".join(def_path) + ".repository")
        if isinstance(repo, str) and repo:
            claimed.add(repository_group_key(repo))
    return {repo: paths for repo, paths in repo_groups.items() if repo not in claimed and len(paths) > 1}


def _print_path_list(chart_dir: Path, deps: list[ChartDependency], paths: list[ValuesPath]):
    for path in sorted(paths):
        source = resolve_values_path_source(chart_dir, deps, path)
        print(f"    {'.'.join(path)}  [{source}]")


def _print_shared_image_usage(
    chart_dir: Path,
    deps: list[ChartDependency],
    values: YamlMapping,
    repo_groups: RepoGroups,
    global_usage: dict[ValuesPath, list[ValuesPath]],
) -> dict[ValuesPath, list[ValuesPath]]:
    """Print shared-image usage; return the failing global.images.* entries.

    Sections: failing global.images.* entries (0-1 consumers: inline them instead),
    genuinely shared global.images.* entries, and other repositories shared across 2+
    paths (informational). Each path is annotated with resolve_values_path_source.
    Inputs must already be render-gated.
    """
    underused = {p: c for p, c in global_usage.items() if len(c) <= 1}
    well_used = {p: c for p, c in global_usage.items() if len(c) >= 2}
    plain_shared = _non_global_shared_repo_groups(values, repo_groups, global_usage)

    if not underused and not well_used and not plain_shared:
        print("OK: no shared-image concerns found")
        return underused

    if underused:
        print()
        noun = "entry" if len(underused) == 1 else "entries"
        print(
            f"FAILING: {len(underused)} global.images.* {noun} registered as a shared image "
            f"but with 0 or 1 real consumer(s) — inline it directly instead of maintaining it "
            f"as a shared anchor:"
        )
        for def_path in sorted(underused):
            consumers = underused[def_path]
            print(f"  {'.'.join(def_path)} ({len(consumers)} real consumer(s)):")
            _print_path_list(chart_dir, deps, consumers)

    if well_used:
        print()
        noun = "entry" if len(well_used) == 1 else "entries"
        print(f"{len(well_used)} global.images.* {noun} genuinely shared (2+ real consumers) — report only:")
        for def_path in sorted(well_used):
            consumers = well_used[def_path]
            print(f"  {'.'.join(def_path)} ({len(consumers)} real consumers):")
            _print_path_list(chart_dir, deps, consumers)

    if plain_shared:
        print()
        print(
            f"{len(plain_shared)} other image(s) incidentally shared across 2+ values.yaml "
            f"paths (not a declared global.images.* anchor — report only, bumping one still "
            f"affects every path listed under it):"
        )
        for repo in sorted(plain_shared):
            paths = plain_shared[repo]
            print(f"  {repo} ({len(paths)} consumers):")
            _print_path_list(chart_dir, deps, paths)

    return underused


def check_digest_pinning(chart_dir: Path):
    """Fail if any non-exempt values.yaml image tag lacks an "@sha256:<64 hex>" suffix."""
    values_path = chart_dir / "values.yaml"
    if not values_path.is_file():
        print("OK: no values.yaml found — nothing to check")
        return True, "0 pin(s), 0 unpinned"

    values = load_yaml_mapping(values_path)
    images = list(find_image_tag_paths(values))
    exceptions = digest_pinning_exceptions(chart_dir)

    missing = [(path, tag) for path, tag in images if path not in exceptions and not DIGEST_SUFFIX_RE.search(tag)]

    if not missing:
        print(f"OK: all {len(images)} image tag(s) in values.yaml are digest-pinned ({len(exceptions)} exempt)")
        return True, f"{len(images)} pin(s), 0 unpinned"

    print(f'Found {len(missing)} image tag(s) not digest-pinned (missing "@sha256:<64 hex chars>"):')
    for path, tag in sorted(missing):
        print(f"  {'.'.join(path)}.tag: {tag!r}")

    return False, f"{len(missing)}/{len(images)} image(s) not digest-pinned"


def check_shared_image_usage(chart_dir: Path, extra_args: list[str]):
    """Report every repository shared across 2+ live values.yaml paths.

    Paths are render-gated (see _live_repository_groups); a render failure fails the step.
    Fails only for a global.images.* entry with 0 or 1 live consumers (the shared anchor
    is pointless, inline it). Other shared repositories are informational.
    """
    values_path = chart_dir / "values.yaml"
    if not values_path.is_file():
        print("OK: no values.yaml found — nothing to check")
        return True, "nothing to check"

    result = render_chart(chart_dir, extra_args)
    if result.returncode != 0:
        return False, "helm template failed to render"
    rendered_paths = rendered_chart_paths(result.stdout)

    values = load_yaml_mapping(values_path)
    deps = _deps_from_chart_yaml(chart_dir)
    repo_groups = _live_repository_groups(chart_dir, deps, values, rendered_paths)
    global_usage = _global_image_usage(values, repo_groups)
    underused = _print_shared_image_usage(chart_dir, deps, values, repo_groups, global_usage)

    if underused:
        noun = "entry" if len(underused) == 1 else "entries"
        return False, f"{len(underused)} global.images.* {noun} under-used (failing)"
    return True, "every global.images.* entry has 2+ real consumers"


def find_unresolved_subchart_images(
    chart_dir: Path, deps: list[ChartDependency], own_values: YamlMapping, rendered_paths: set[str]
) -> list[SubchartImageFinding]:
    """(scope_key, subpath, tag, already_pinned) for every subchart-default image podiumd doesn't override.

    Looks for "<key>: {tag: ...}" blocks in each vendored dependency's own values.yaml
    absent from `own_values`. `scope_key` is the dependency alias (or name); `subpath`
    ends in the image key. Unvendored dependencies and unreadable defaults are skipped.

    A block with a null tag but a repository resolves `tag` to the owning chart's
    appVersion (Helm's ".tag | default .Chart.AppVersion"); skipped if unresolvable.

    Every finding is gated on its owning chart-tree path appearing in `rendered_paths`,
    since condition:/tags: can leave a vendored default inert. Findings whose top-level
    key no dependency template references are dropped (inert); this filter is skipped
    when templates/ is unreadable and for nested dependencies, whose templates live
    elsewhere.

    digest_pinning_exceptions need no cross-check: those fields are overridden by podiumd.
    """
    findings: list[SubchartImageFinding] = []
    for dep in deps:
        findings.extend(_findings_for_dependency(chart_dir, dep, own_values, rendered_paths))
    return findings


def _findings_for_dependency(
    chart_dir: Path, dep: ChartDependency, own_values: YamlMapping, rendered_paths: set[str]
) -> list[SubchartImageFinding]:
    """find_unresolved_subchart_images' findings for one dependency."""
    scope_key = values_key_of(dep)
    sub_values = subchart_values(chart_dir, dep)
    if sub_values is None:
        return []
    template_text = subchart_template_text(chart_dir, dep)
    own_tree_path = f"{CHART_NAME}/charts/{scope_key}"

    findings: list[SubchartImageFinding] = []
    for path, tag in find_image_tag_paths(sub_values, include_null_tags=True):
        subpath = ".".join(path)
        own_image_tag_path = f"{scope_key}.{subpath}.tag"
        if get_path(own_values, own_image_tag_path) is not None:
            continue
        chart_tree_path, resolved_version = resolve_subchart_default(chart_dir, dep, CHART_NAME, path)
        # A nested dependency's templates live under dep's charts/, not dep's templates/;
        # the render-gate below decides those.
        if (
            chart_tree_path == own_tree_path
            and template_text is not None
            and not re.search(rf"\b{re.escape(path[0])}\b", template_text)
        ):
            continue
        if chart_tree_path not in rendered_paths:
            continue

        if tag is None:
            if resolved_version is None:
                continue
            findings.append((scope_key, subpath, resolved_version, False))
        else:
            findings.append((scope_key, subpath, tag, bool(DIGEST_SUFFIX_RE.search(tag))))
    return findings


def _print_subchart_image_finding(chart_dir: Path, deps: list[ChartDependency], finding: SubchartImageFinding):
    """Print one find_unresolved_subchart_images finding, annotated with resolve_values_path_source."""
    scope_key, subpath, tag, pinned = finding
    own_image_tag_path = f"{scope_key}.{subpath}.tag"
    marker = "pinned" if pinned else "FLOATING"
    source = resolve_values_path_source(chart_dir, deps, (scope_key,))
    print(f"  {own_image_tag_path}: {tag!r} ({marker} in the sub-chart's own default)  [{source}]")


def check_subchart_image_visibility(chart_dir: Path, extra_args: list[str]):
    """List every subchart-default image podiumd doesn't override.

    FLOATING findings (no digest in the subchart default either) fail the step: they
    are unreproducible. PINNED findings are report-only, a per-case judgment call.
    A render failure fails the step.
    """
    result = render_chart(chart_dir, extra_args)
    if result.returncode != 0:
        return False, "helm template failed to render"
    rendered_paths = rendered_chart_paths(result.stdout)

    own_values = load_yaml_mapping(chart_dir / "values.yaml")
    deps = load_chart_dependencies(chart_dir / "Chart.yaml")
    findings = find_unresolved_subchart_images(chart_dir, deps, own_values, rendered_paths)
    floating = [f for f in findings if not f[3]]
    pinned = [f for f in findings if f[3]]

    if floating:
        print(
            f"FAILING: {len(floating)} image(s) with a floating, unpinned tag and no podiumd "
            f"override.\nInvisible to the digest-pinning check above — add a digest-pinned "
            f"override for each:"
        )
        for finding in sorted(floating):
            _print_subchart_image_finding(chart_dir, deps, finding)

    if pinned:
        print(
            f"Report only, NOT failing: {len(pinned)} image(s) defined only in a vendored "
            f"sub-chart's own default values.yaml, but already digest-pinned there (already "
            f"reproducible) — decide per image whether it still warrants an explicit podiumd "
            f"override:"
        )
        for finding in sorted(pinned):
            _print_subchart_image_finding(chart_dir, deps, finding)

    if not findings:
        print("OK: no sub-chart-default images found without a podiumd override")

    if floating:
        suffix = f", {len(pinned)} pinned (report only)" if pinned else ""
        return False, f"{len(floating)} floating (failing){suffix}"
    if pinned:
        return True, f"0 floating, {len(pinned)} pinned (report only)"
    return True, "0 unresolved"
