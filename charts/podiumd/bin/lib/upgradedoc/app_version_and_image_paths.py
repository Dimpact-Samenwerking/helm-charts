"""Resolving a component's real app version (values.yaml override,
Chart.yaml dependency version, or vendored-subchart fallback) and
walking a values tree for every image-tag/version path a
dependency or native component actually pins."""

from lib.chart.nested_subchart_identity import nested_subchart_registered_paths
from lib.chart.pull_and_subchart_resolution import subchart_app_version
from lib.chart.registered_paths import (
    component_image_paths,
    image_paths_for,
    version_paths_for,
)
from lib.chart.values_tree_primitives import get_path
from lib.upgradedoc.string_and_parsing_basics import (
    normalize_version,
    words_of,
)


def actual_app_version(values, values_key, component=None, chart_dir=None, dep=None):
    """The app version currently pinned for a component — tries each of
    lib.chart.image_paths_for(component)'s own dotted path(s) in turn:
    the plain "<key>.image.tag" shape for the common case
    (component_resolution_default_image_paths), or a component-specific
    override from component_image_paths() for one with a non-standard
    primary-image location — e.g. keycloak-operator's own split "operator.config.
    keycloakImage.tag" path, openbao's "server.image", or zgw-office-
    addin's frontend+backend pair (the first of those two with a real
    tag wins; there's no single "the" app version for a two-image
    component, so this picks one rather than reporting both).

    If none of those resolve, falls back to lib.chart.version_paths_for
    (component)'s own dotted path(s), read DIRECTLY (no ".tag" suffix
    appended) — for a component whose real app version isn't expressed
    as an "image: {repository, tag}" block at all, e.g. eck-stack's own
    bare "eck-elasticsearch.version" CRD field, or redis-operator's own
    split "redisOperator.imageTag" (sibling to "imageName", not nested
    under a common "image:" key). Without this fallback, a real app-
    version change on one of these components was invisible to every
    caller of this function — the doc-consistency row/Changes-item check
    silently skipped comparing it at all (its own "actual_app and ..."
    guard short-circuits on None), so a wrong OR MISSING app-version cell
    for kiss-eck's own real 8.19.3 -> 8.19.19 Elastic-stack bump went
    uncaught; confirmed live.

    If THAT still doesn't resolve, and both `chart_dir` and `dep` (the
    full Chart.yaml dependency dict — needs its own "version" too, not
    just its name) are given, falls back to lib.chart.subchart_app_
    version — but ONLY for a component with its own component_image_
    paths() entry, never the generic default_image_paths guess. A
    registered path with an explicit but deliberately BLANK "tag:"
    override (e.g. openbao's own "server.image.tag" — the repository is
    pinned, but the tag is left for the chart's own pinned appVersion to
    supply) is a DELIBERATE design signal that a human already vouched
    for; the same blank tag on an UNREGISTERED component could just as
    easily mean "not actually running this image at all," which nothing
    here can tell apart — so this never applies to eck-operator or any
    other component that merely happens to also float on its own
    chart's appVersion without being explicitly registered for it.

    `component` is the Chart.yaml dependency's own NAME (component_
    image_paths()/component_version_paths() are both keyed by name, not
    alias) — defaults to `values_key` when omitted, since name and
    alias/values_key coincide for every currently-registered entry; pass
    the real name explicitly once a registered component ever has a
    distinct alias, so the registry lookup still finds it."""
    resolved_component = component or values_key
    for path in image_paths_for(resolved_component, chart_dir):
        tag = get_path(values, f"{values_key}.{path}.tag")
        if tag:
            return tag.split("@")[0]
    for path in version_paths_for(resolved_component, chart_dir):
        version = get_path(values, f"{values_key}.{path}")
        if isinstance(version, str) and version:
            return version.split("@")[0]
    if chart_dir is not None and dep is not None and resolved_component in component_image_paths(chart_dir):
        return subchart_app_version(chart_dir, dep)
    return None


def resolve_baseline_component_versions(
    baseline_values, baseline_dep, values_key, image_path, chart_name, new_chart, chart_dir=None
):
    """(old_app, old_chart) resolved against the TRUE release baseline —
    the single source of truth update-image-version's own update_docs_
    single_component and update-component-version's own main() both
    call, instead of each maintaining its own slightly-different version
    of this same resolution (the real gap behind #1/#5: update_docs_
    single_component's old_app used to fall back to whatever the image
    was pinned at immediately before THIS run when the true baseline
    genuinely had no override — that None is authoritative, not a
    resolution failure, once baseline_values itself resolved at all).

    baseline_dep is this component's own Chart.yaml dependency dict AS
    IT WAS AT THE BASELINE (None if it didn't exist there at all yet —
    a brand-new dependency this cycle, or a lib.chart.native_components
    component with no chart at all). `image_path` is the SPECIFIC dotted
    path (under values_key) this bump actually touched — e.g. a
    sidecar's own path ("redis-ha.image"), not always chart_name's
    registered PRIMARY path (lib.chart.image_paths_for(chart_name)[0]),
    which is why this reads baseline_values at that exact path directly
    rather than re-deriving it via actual_app_version(baseline_values,
    values_key, chart_name) (that call is only safe for a component's
    own primary image, never a sidecar's).

    old_app: the raw baseline_values tag at values_key.image_path first;
    if that's blank AND chart_dir is given AND this component's chart
    version hasn't moved since baseline (baseline_dep's own version ==
    new_chart — the same vendored .tgz backs both baseline and current
    in that case) also tries actual_app_version's own vendored-subchart
    fallback, against a dep dict synthesized as {"name": chart_name,
    "version": new_chart} — deliberately NOT the caller's own current
    Chart.yaml dependency dict, whose "version" field is whatever this
    run found on disk BEFORE any Chart.yaml rewrite, whether that
    happens to be new_chart or not (safe example: a basename bump never
    touches Chart.yaml at all, so it always coincides; unsafe example: a
    component bumped 1.0 -> 1.2 earlier this cycle then reconsidered
    1.2 -> 1.0 this run, landing back on a baseline_dep version that
    equals new_chart even though the on-disk dep dict momentarily read
    1.2 — passing THAT would read the wrong vendored artifact's
    appVersion as if it were the baseline's own). Never attempted when
    the chart DID change, since that would read a mismatched artifact.

    old_chart: baseline_dep's own version, but ONLY when old_app resolved
    to a real value above — a component with no real baseline app
    version at all (verifiably never captured in any prior baseline doc,
    even though Chart.yaml itself always lists a dependency's own chart
    version regardless of whether it was ever really tracked, e.g. mi-
    data's own baseline "1.0.0") gets old_chart forced to None too, so
    BOTH fields render "(new)" together rather than a misleading
    "old → new" transition implying a real prior baseline value existed
    and moved. None outright when baseline_dep is None (no Chart.yaml
    dependency at the baseline at all)."""
    raw_old_chart = str(baseline_dep["version"]) if baseline_dep is not None else None
    baseline_tag = get_path(baseline_values, f"{values_key}.{image_path}.tag") or ""
    old_app = baseline_tag.split("@", 1)[0] or None
    if (
        old_app is None
        and chart_dir is not None
        and raw_old_chart is not None
        and normalize_version(raw_old_chart) == normalize_version(new_chart)
    ):
        old_app = actual_app_version(
            baseline_values, values_key, chart_name, chart_dir=chart_dir, dep={"name": chart_name, "version": new_chart}
        )
    old_chart = raw_old_chart if old_app is not None else None
    return old_app, old_chart


def find_image_tag_paths(node, path=(), include_null_tags=False):
    """Yield (path, tag) for every "<key>: {tag: ...}" block anywhere in a
    values tree, where <key> is "image" or ends with "Image" (e.g.
    "initImage", alongside "image" in the very same job, for a component
    that needs more than one distinctly-named image — a single "image"
    key can't serve both). Keyed by its full path INCLUDING that key
    itself — e.g. ("zac", "opa", "image") for zac.opa.image.tag, or
    ("keycloak-operator", "jobs", "ensurePodiumdAdminUser", "initImage")
    for that job's own init-container image. Structural, so it finds
    sidecars too, not just top-level Chart.yaml dependencies.

    Deliberately keyed on the "...Image" suffix specifically, not "any
    dict shaped like {tag, repository}" — a reusable template like
    global.images.nginx/curl/busybox/redis (itself never rendered
    anywhere on its own, just aliased into real "image:"/"...Image:"
    sites via a YAML anchor) would otherwise be double-counted as its
    own separate, spurious usage location; "images" (plural, the
    container dict those templates live under) doesn't itself end in
    "Image" (capital I), so this excludes it correctly.

    NOTE: the yielded path now always ends in the image key itself
    (unlike this function's earlier "image"-only shape, which omitted
    it since every caller could safely assume ".image.tag") — a caller
    reconstructing a dotted values.yaml reference must use path[-1],
    not a hardcoded ".image.tag" suffix.

    include_null_tags=True (default False, so every existing caller's
    behavior is exactly unchanged) ALSO yields (path, None) for a block
    whose own "tag:" is missing or explicit YAML null, but which DOES
    have a truthy "repository:" — Helm's own template convention for an
    image relying entirely on its OWN chart's "appVersion" default
    (".tag | default .Chart.AppVersion") instead of an explicit
    override (e.g. eck-operator's own vendored default — podiumd has no
    override for it at all). This function stays purely structural (no
    I/O) either way — resolving None into a real, effective version is
    a SEPARATE step a caller does itself (see lib.chart.
    resolve_subchart_default, the one place both real consumers —
    lib.checks.digest_pinning.find_unresolved_subchart_images and
    lib.image.docs.regenerate_images_baseline_manifest — do that
    resolution, so it's never re-derived twice).

    Deliberately does NOT relax an explicit blank-string "tag: ''" the
    same way — a different, already-handled case elsewhere (e.g.
    openbao's own "server.image.tag", resolved via lib.chart.
    subchart_app_version through lib.upgradedoc.actual_app_version's own
    values.yaml lookup) that must keep behaving exactly as it does
    today; only a tag that's None (missing key, or explicit YAML "null")
    ever counts as a candidate here."""
    if isinstance(node, dict):
        for key, value in node.items():
            if (key == "image" or key.endswith("Image")) and isinstance(value, dict):
                tag = value.get("tag")
                if tag:
                    yield path + (key,), tag
                elif include_null_tags and tag is None and value.get("repository"):
                    yield path + (key,), None
        for key, value in node.items():
            if key == "image" or key.endswith("Image"):
                continue
            yield from find_image_tag_paths(value, path + (str(key),), include_null_tags)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from find_image_tag_paths(item, path + (str(i),), include_null_tags)


def find_component_version_tags(values, deps):
    """(path, value) for every lib.chart.component_version_paths()- or
    lib.settings.component_resolution_version_path_nested_subcharts-
    registered bare tag/version field that's actually pinned in `values`
    — the ONE shape find_image_tag_paths' own generic "<key ending in
    Image>: {tag: ...}" structural scan can never see, since these are
    flat scalar sibling fields (e.g. redis-operator's own "redisOperator.
    imageTag", not nested under an "image:"/"...Image:" dict with a
    "tag:" key at all — see component_version_paths()' own docstring for
    why). The two registries' own field lists are unioned — version_
    path_nested_subcharts registers a few fields component_version_paths()
    deliberately excludes from ITS narrower "pick ONE representative
    app version" list (eck-stack's own "eck-enterprise-search.version",
    disabled by default) that are still real, matchable images here.
    Use find_all_image_and_version_paths for a chart-wide scan that
    includes both this and find_image_tag_paths; this on its own only
    when just the registered paths are wanted."""
    for dep in deps:
        values_key = dep.get("alias", dep["name"])
        rels = set(version_paths_for(dep["name"])) | set(nested_subchart_registered_paths(dep["name"]))
        for rel in rels:
            value = get_path(values, f"{values_key}.{rel}")
            if isinstance(value, str) and value:
                yield tuple(values_key.split(".")) + tuple(rel.split(".")), value


def find_all_image_and_version_paths(values, deps):
    """find_image_tag_paths(values) plus find_component_version_tags(values,
    deps) — every image tag AND registered bare-version pin in one
    combined [(path, value), ...] list. Use this (not find_image_tag_
    paths alone) anywhere the FULL, exhaustive set of what's actually
    pinned matters — detecting whether a component's image changed vs
    baseline, most notably — never just the ordinary "image:"/
    "...Image:" dict shape."""
    return list(find_image_tag_paths(values)) + list(find_component_version_tags(values, deps))


def resolve_entry_path(entry_name, paths):
    """Match an images-manifest entry name (e.g. "zgw-office-addin-frontend")
    to a values-tree path (e.g. ("zgw-office-addin", "frontend")) by comparing
    word-split, concatenated path segments — no hardcoded name list.

    The innermost path segment must match the entry's last word: without that,
    sibling paths sharing a coincidental prefix (e.g. zac.solr-operator.solr
    vs zac.solr-operator.zookeeper-operator.zookeeper — both start with
    "zac"+"solr"+"operator") are indistinguishable by substring matching alone.

    A path's own trailing "image"/"...Image" segment (see
    find_image_tag_paths — the generic marker for which key under that
    parent actually holds the tag, not a meaningful descriptor on its
    own) is excluded from matching, the same way a path built this
    function's original way (before more than one image-key name became
    possible) never had it there to begin with. The full path, trailing
    segment included, is still what gets returned — callers use it
    as-is for a dict lookup back into whatever produced it."""
    entry_words = words_of(entry_name)
    if not entry_words:
        return None
    norm_entry = "".join(entry_words)

    best = None
    for path in paths:
        descriptive = path[:-1] if path and (path[-1] == "image" or path[-1].endswith("Image")) else path
        path_words = [w for segment in descriptive for w in words_of(segment)]
        if not path_words or path_words[-1] != entry_words[-1]:
            continue
        norm_path = "".join(path_words)
        if norm_path == norm_entry:
            return path
        if norm_path in norm_entry or norm_entry in norm_path:
            # closest length = least unrelated extra text pulled in by the
            # containment match
            diff = abs(len(norm_path) - len(norm_entry))
            if best is None or diff < best[1]:
                best = (path, diff)
    return best[0] if best else None


def resolve_entry_image_path(entry, paths, repo_map=None):
    """Match an images-manifest entry (the full {"name", "url", ...}
    mapping) to a values-tree path — an exact repo_map lookup first
    (see lib.chart.repository_path_map: under the current strip-
    registry convention an entry's "name:" IS the repository in that
    same stripped form, so this is a direct dict hit, not a guess),
    falling back to resolve_entry_path's fuzzy name-word matching when
    repo_map has nothing for it (no repo_map given, an older manifest
    entry still under the legacy hand-translated slug convention, or a
    nested image with no Chart.yaml dependency of its own — e.g. a
    component's bundled sidecar — that repo_map doesn't cover at all)."""
    if repo_map:
        path = repo_map.get(entry["name"])
        if path is not None and path in paths:
            return path
    return resolve_entry_path(entry["name"], paths)
