"""Verifies every "image: {tag: ...}" block in this chart's own
values.yaml (see lib.upgradedoc.find_image_tag_paths) resolves to an
actual, non-empty repository — either podiumd's own override, or the
owning dependency's vendored subchart default (the same own-vs-
subchart-default resolution lib.chart.repository_path_map uses, but
checked PER PATH here — repository_path_map's own output is keyed by
the repository string, which silently collapses down to one survivor
whenever more than one path shares the same repository, e.g. several
"<component>.nginx.image" sidecars all aliasing the same
global.images.nginx YAML anchor; that's fine for repository_path_map's
own actual purpose — images-manifest entry -> values-tree path, a
repository is exactly its own lookup key there — but it's wrong for
this check, which needs a real answer for every single path). Without a
resolvable repository, the shared `podiumd.image` template helper
every image: field must call (see lib.image_references_check) renders
"<empty>:<tag>" — a malformed image reference Kubernetes rejects
outright (InvalidImageName / ImagePullBackOff) — caught here BEFORE
that ever reaches a cluster.

Real case this exists for: kiss.adapter.image's own "repository:" line
is commented out in podiumd's values.yaml, and the vendored kiss-chart
subchart has no "adapter" key in its own defaults either — so the
podiumd-adapter Deployment currently renders "image: :0.6.7@sha256:...",
confirmed both by rendering the podiumd.image helper directly and
against a real `helm template` output already checked into this repo."""
from lib.chart import get_path, load_yaml, resolve_chart_values
from lib.upgradedoc import find_image_tag_paths


def find_images_without_repository(chart_dir, allow_pull=False):
    """[path, ...] (each as find_image_tag_paths' own tuple form, sorted)
    for every image-tag block whose repository can't be resolved at all.
    A path rooted at a real Chart.yaml dependency's own values-tree key
    is checked against podiumd's own override first, else the owning
    dependency's vendored subchart default (resolved at most once per
    dependency and reused across every one of its paths, same caching
    lib.chart.repository_path_map/primary_image_repositories use); a
    path rooted at the shared "global" key is checked directly against
    podiumd's own values.yaml only — same two shapes lib.chart.
    canonical_sidecar_row_names itself distinguishes, and for the same
    reason (a "global.*" anchor's own repository is always set
    explicitly there, never inherited from a subchart). A path rooted
    at neither (an orphan top-level values.yaml block with no matching
    Chart.yaml dependency at all) is reported too — there's nothing to
    resolve it against either way."""
    chart_yaml = load_yaml(chart_dir / "Chart.yaml")
    deps = chart_yaml.get("dependencies", [])
    values = load_yaml(chart_dir / "values.yaml") or {}
    by_values_key = {(dep.get("alias") or dep["name"]): dep for dep in deps}
    subchart_cache = {}  # dep name -> subchart values or None

    missing = []
    for path, _tag in find_image_tag_paths(values):
        if not path:
            continue

        if path[0] == "global":
            repo = get_path(values, ".".join(path) + ".repository")
            if not isinstance(repo, str) or not repo:
                missing.append(path)
            continue

        dep = by_values_key.get(path[0])
        if dep is None:
            missing.append(path)
            continue

        own_repo = get_path(values, ".".join(path) + ".repository")
        if isinstance(own_repo, str) and own_repo:
            continue

        if dep["name"] not in subchart_cache:
            sub_values, _source, _err = resolve_chart_values(chart_dir, dep, dep["version"], allow_pull=allow_pull)
            subchart_cache[dep["name"]] = sub_values
        sub_values = subchart_cache[dep["name"]]
        sub_repo = get_path(sub_values, ".".join(path[1:]) + ".repository") if sub_values is not None else None
        if isinstance(sub_repo, str) and sub_repo:
            continue

        missing.append(path)

    return sorted(missing)


def check_image_repository(chart_dir):
    if not (chart_dir / "values.yaml").is_file():
        print("OK: no values.yaml found — nothing to check")
        return True, "0 missing repository"

    missing = find_images_without_repository(chart_dir)

    if not missing:
        print("OK: every image tag block resolves to a repository")
        return True, "0 missing repository"

    print(f"Found {len(missing)} image tag block(s) with no resolvable repository "
          f"(neither podiumd's own values.yaml nor the owning dependency's vendored "
          f"subchart default) — the podiumd.image helper would render an empty "
          f"repository, an invalid image reference:")
    for path in missing:
        print(f"  {'.'.join(path)}")

    return False, f"{len(missing)} image(s) with no resolvable repository"
