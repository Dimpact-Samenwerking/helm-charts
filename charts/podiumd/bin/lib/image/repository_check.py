"""Check that every image block and registered version field in values.yaml resolves to a repository.

Without one, the podiumd.image helper renders "<empty>:<tag>", which
Kubernetes rejects (e.g. kiss.adapter.image: repository commented out and
no subchart default). Checked per path, unlike repository_path_map, which
collapses paths that share a repository.
"""

from pathlib import Path

from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.repo_and_path_resolution import RepositoryResolver
from lib.upgradedoc.app_version_and_image_paths import find_all_image_and_version_paths
from lib.yaml_types import load_yaml_mapping


def find_images_without_repository(chart_dir: Path, *, allow_pull: bool = False) -> list[tuple[str, ...]]:
    """Sorted image-tag paths whose repository can't be resolved.

    Resolved through RepositoryResolver. A path without a dependency (global,
    keycloak, apiproxy, ...) is rendered by podiumd's own templates, so only
    podiumd's values.yaml is checked; lacking a dependency is not "missing".
    """
    deps = load_chart_dependencies(chart_dir / "Chart.yaml")
    values = load_yaml_mapping(chart_dir / "values.yaml")
    resolver = RepositoryResolver(chart_dir, deps, values, allow_pull=allow_pull)
    return sorted(
        path
        for path, _tag in find_all_image_and_version_paths(values, deps)
        if path and resolver.full_repository(path) is None
    )


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
