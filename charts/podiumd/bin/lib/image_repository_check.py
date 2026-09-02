"""Verifies every "image: {tag: ...}" block in this chart's own
values.yaml (see lib.upgradedoc.find_image_tag_paths) resolves to an
actual, non-empty repository — either podiumd's own override, or the
owning dependency's vendored subchart default (see
lib.chart.repository_path_map). Without one, the shared `podiumd.image`
template helper every image: field must call (see
lib.image_references_check) renders "<empty>:<tag>" — a malformed image
reference Kubernetes rejects outright (InvalidImageName /
ImagePullBackOff) — caught here BEFORE that ever reaches a cluster.

Real case this exists for: kiss.adapter.image's own "repository:" line
is commented out in podiumd's values.yaml, and the vendored kiss-chart
subchart has no "adapter" key in its own defaults either — so the
podiumd-adapter Deployment currently renders "image: :0.6.7@sha256:...",
confirmed both by rendering the podiumd.image helper directly and
against a real `helm template` output already checked into this repo."""
from lib.chart import get_path, load_yaml, repository_path_map
from lib.upgradedoc import find_image_tag_paths


def find_images_without_repository(chart_dir, allow_pull=False):
    """[path, ...] (each as find_image_tag_paths' own tuple form, sorted)
    for every image-tag block whose repository can't be resolved at all.
    A path rooted at a real Chart.yaml dependency's own values-tree key
    is checked via repository_path_map (own override, else the owning
    dependency's vendored subchart default); a path rooted at the shared
    "global" key is checked directly against podiumd's own values.yaml
    only — same two shapes lib.chart.canonical_sidecar_row_names itself
    distinguishes, and for the same reason (a "global.*" anchor's own
    repository is always set explicitly there, never inherited from a
    subchart). A path rooted at neither (an orphan top-level values.yaml
    block with no matching Chart.yaml dependency at all) is reported too
    — there's nothing to resolve it against either way."""
    chart_yaml = load_yaml(chart_dir / "Chart.yaml")
    deps = chart_yaml.get("dependencies", [])
    values = load_yaml(chart_dir / "values.yaml") or {}
    all_paths = [path for path, _tag in find_image_tag_paths(values)]

    global_paths = [path for path in all_paths if path and path[0] == "global"]
    other_paths = [path for path in all_paths if path not in global_paths]

    resolved = set(repository_path_map(chart_dir, deps, values, other_paths, allow_pull=allow_pull).values())
    missing = [path for path in other_paths if path not in resolved]

    for path in global_paths:
        repo = get_path(values, ".".join(path) + ".repository")
        if not isinstance(repo, str) or not repo:
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
