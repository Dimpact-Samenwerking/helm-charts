"""Check that every image block and registered version field in values.yaml resolves to a repository.

Without one, the podiumd.image helper renders "<empty>:<tag>", which
Kubernetes rejects (e.g. kiss.adapter.image: repository commented out and
no subchart default). Checked per path, unlike repository_path_map, which
collapses paths that share a repository.
"""

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.nested_subchart_identity import nested_subchart_documented_image_repository
from lib.chart.nested_subchart_identity import nested_subchart_name_for
from lib.chart.nested_subchart_identity import version_repository_path_for
from lib.chart.pull_and_subchart_resolution import resolve_chart_values
from lib.chart.repo_and_path_resolution import SubchartValuesCache
from lib.chart.values_tree_primitives import text_at
from lib.chart.values_tree_primitives import values_key_of
from lib.upgradedoc.app_version_and_image_paths import find_all_image_and_version_paths
from lib.yaml_types import YamlMapping
from lib.yaml_types import load_yaml_mapping


@dataclass
class _RepositoryResolutionContext:
    """Per-call config and subchart-lookup caches of find_images_without_repository."""

    chart_dir: Path
    allow_pull: bool
    nested_subchart_cache: dict[tuple[str, str], str | None] = field(default_factory=dict)
    subchart_cache: SubchartValuesCache = field(default_factory=dict)


def _path_has_repository(
    path: tuple[str, ...], values: YamlMapping, dep: ChartDependency | None, ctx: _RepositoryResolutionContext
):
    """Whether `path` resolves to a repository: own override, sibling field, nested subchart, subchart default."""
    own_repo = text_at(values, ".".join(path) + ".repository")
    if isinstance(own_repo, str) and own_repo:
        return True

    if dep is None:
        # No owning dependency: podiumd's own value (checked above) is the only source.
        return False

    sibling_rel = version_repository_path_for(dep["name"], ctx.chart_dir)
    if sibling_rel:
        sibling_repo = text_at(values, f"{path[0]}.{sibling_rel}")
        if isinstance(sibling_repo, str) and sibling_repo:
            return True

    nested_rel = ".".join(path[1:])
    nested_chart_name = nested_subchart_name_for(dep["name"], nested_rel, ctx.chart_dir)
    if nested_chart_name:
        cache_key = (dep["name"], nested_chart_name)
        if cache_key not in ctx.nested_subchart_cache:
            ctx.nested_subchart_cache[cache_key] = nested_subchart_documented_image_repository(
                ctx.chart_dir, dep, nested_chart_name
            )
        if ctx.nested_subchart_cache[cache_key]:
            return True

    if dep["name"] not in ctx.subchart_cache:
        sub_values, _source, _err = resolve_chart_values(ctx.chart_dir, dep, dep["version"], allow_pull=ctx.allow_pull)
        ctx.subchart_cache[dep["name"]] = sub_values
    sub_values = ctx.subchart_cache[dep["name"]]
    sub_repo = text_at(sub_values, ".".join(path[1:]) + ".repository") if sub_values is not None else None
    return isinstance(sub_repo, str) and bool(sub_repo)


def find_images_without_repository(chart_dir: Path, *, allow_pull: bool = False) -> list[tuple[str, ...]]:
    """Sorted image-tag paths whose repository can't be resolved.

    A dependency's path: podiumd's override, else the vendored subchart
    default (resolved once per dependency). Any other path (global,
    keycloak, apiproxy, ...) is rendered by podiumd's own templates, so only
    podiumd's values.yaml is checked; lacking a dependency is not "missing".
    """
    deps = load_chart_dependencies(chart_dir / "Chart.yaml")
    values = load_yaml_mapping(chart_dir / "values.yaml")
    by_values_key = {values_key_of(dep): dep for dep in deps}
    ctx = _RepositoryResolutionContext(chart_dir, allow_pull)

    missing: list[tuple[str, ...]] = []
    for path, _tag in find_all_image_and_version_paths(values, deps):
        if not path:
            continue
        dep = by_values_key.get(path[0])
        if not _path_has_repository(path, values, dep, ctx):
            missing.append(path)

    return sorted(missing)


def check_image_repository(chart_dir: Path):
    """verify-podiumd check: print each path with no resolvable repository; fail if any.

    Passes when chart_dir has no values.yaml.
    """
    if not (chart_dir / "values.yaml").is_file():
        print("OK: no values.yaml found — nothing to check")
        return True, "0 missing repository"

    missing = find_images_without_repository(chart_dir)

    if not missing:
        print("OK: every image tag block resolves to a repository")
        return True, "0 missing repository"

    print(
        f"Found {len(missing)} image tag block(s) with no resolvable repository "
        f"(neither podiumd's own values.yaml nor the owning dependency's vendored "
        f"subchart default) — the podiumd.image helper would render an empty "
        f"repository, an invalid image reference:"
    )
    for path in missing:
        print(f"  {'.'.join(path)}")

    return False, f"{len(missing)} image(s) with no resolvable repository"
