"""Verifies every "image: {tag: ...}" block, plus every registered bare
tag/version field (see lib.upgradedoc.find_all_image_and_version_paths),
in this chart's own values.yaml resolves to an actual, non-empty
repository — either podiumd's own override, or the owning dependency's
vendored subchart default (the same own-vs-subchart-default resolution
lib.chart.repository_path_map uses, but
checked PER PATH here — repository_path_map's own output is keyed by
the repository string, which silently collapses down to one survivor
whenever more than one path shares the same repository, e.g. several
"<component>.nginx.image" sidecars all aliasing the same
global.images.nginx YAML anchor; that's fine for repository_path_map's
own actual purpose — images-manifest entry -> values-tree path, a
repository is exactly its own lookup key there — but it's wrong for
this check, which needs a real answer for every single path). Without a
resolvable repository, the shared `podiumd.image` template helper
every image: field must call (see lib.image.references_check) renders
"<empty>:<tag>" — a malformed image reference Kubernetes rejects
outright (InvalidImageName / ImagePullBackOff) — caught here BEFORE
that ever reaches a cluster.

Real case this exists for: kiss.adapter.image's own "repository:" line
is commented out in podiumd's values.yaml, and the vendored kiss-chart
subchart has no "adapter" key in its own defaults either — so the
podiumd-adapter Deployment currently renders "image: :0.6.7@sha256:...",
confirmed both by rendering the podiumd.image helper directly and
against a real `helm template` output already checked into this repo."""

from dataclasses import dataclass
from dataclasses import field

from lib.chart.nested_subchart_identity import nested_subchart_documented_image_repository
from lib.chart.nested_subchart_identity import nested_subchart_name_for
from lib.chart.nested_subchart_identity import version_repository_path_for
from lib.chart.pull_and_subchart_resolution import resolve_chart_values
from lib.chart.release_baseline_basics import load_yaml
from lib.chart.values_tree_primitives import get_path
from lib.chart.values_tree_primitives import values_key_of
from lib.upgradedoc.app_version_and_image_paths import find_all_image_and_version_paths


@dataclass
class _RepositoryResolutionContext:
    """find_images_without_repository's own per-call config (chart_dir,
    allow_pull) plus the two subchart-lookup caches _path_has_repository
    fills in across paths, bundled since every one of its 4 params is
    threaded unchanged through every call in the same loop."""

    chart_dir: object
    allow_pull: bool
    nested_subchart_cache: dict = field(default_factory=dict)
    subchart_cache: dict = field(default_factory=dict)


def _path_has_repository(path, values, dep, ctx):
    """True if `path`'s image-tag block resolves to a non-empty
    repository, per find_images_without_repository's own resolution
    rules (own override, sibling repository field, documented nested
    subchart, then vendored subchart default) — see that function's
    docstring for why each fallback exists."""
    own_repo = get_path(values, ".".join(path) + ".repository")
    if isinstance(own_repo, str) and own_repo:
        return True

    if dep is None:
        # No Chart.yaml dependency owns this key — nothing to fall
        # back to, so podiumd's own (already-checked-above) value is
        # the only possible answer.
        return False

    sibling_rel = version_repository_path_for(dep["name"], ctx.chart_dir)
    if sibling_rel:
        sibling_repo = get_path(values, f"{path[0]}.{sibling_rel}")
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
    sub_repo = get_path(sub_values, ".".join(path[1:]) + ".repository") if sub_values is not None else None
    return isinstance(sub_repo, str) and bool(sub_repo)


def find_images_without_repository(chart_dir, *, allow_pull=False):
    """[path, ...] (each as find_image_tag_paths' own tuple form, sorted)
    for every image-tag block whose repository can't be resolved at all.
    A path rooted at a real Chart.yaml dependency's own values-tree key
    is checked against podiumd's own override first, else the owning
    dependency's vendored subchart default (resolved at most once per
    dependency and reused across every one of its paths, same caching
    lib.chart.repository_path_map/primary_image_repositories use).

    A path rooted at anything else — the shared "global" anchor, or one
    of podiumd's own directly-templated top-level blocks with no
    Chart.yaml dependency of its own at all (e.g. "adapter"'s own
    siblings "keycloak", "apiproxy", "frankgateway" — real Deployments
    this chart's OWN templates/*.yaml render straight from podiumd's own
    values.yaml, never a vendored subchart) — is checked directly
    against podiumd's own values.yaml ONLY: there is no subchart to fall
    back to either way, so "no owning dependency" must never by itself
    mean "missing" the way it first did here (that treated every one of
    these orphan blocks as broken even though each has a perfectly real
    repository of its own — confirmed live against the real chart, 9 of
    the first 10 findings this way were exactly this false positive)."""
    chart_yaml = load_yaml(chart_dir / "Chart.yaml")
    deps = chart_yaml.get("dependencies", [])
    values = load_yaml(chart_dir / "values.yaml") or {}
    by_values_key = {values_key_of(dep): dep for dep in deps}
    ctx = _RepositoryResolutionContext(chart_dir, allow_pull)

    missing = []
    for path, _tag in find_all_image_and_version_paths(values, deps):
        if not path:
            continue
        dep = by_values_key.get(path[0])
        if not _path_has_repository(path, values, dep, ctx):
            missing.append(path)

    return sorted(missing)


def check_image_repository(chart_dir):
    """The verify-podiumd check itself: every image-tag block in
    chart_dir's values.yaml must resolve to a non-empty repository (see
    find_images_without_repository for the resolution rules). Prints each
    dotted path with no resolvable repository and fails if any are found
    — an unresolvable repository means the podiumd.image helper would
    render a malformed "<empty>:<tag>" image reference. Passes trivially
    (True, "0 missing repository") if chart_dir has no values.yaml at
    all."""
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
