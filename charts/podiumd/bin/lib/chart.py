"""Chart.yaml/values.yaml helpers shared by every script that resolves a
podiumd dependency, pulls a specific chart version, or walks a values tree
for image references."""

import re
import tarfile

import yaml

from lib.chart_nested_subchart_identity import (
    nested_subchart_documented_image_repository,
    nested_subchart_name_for,
    version_repository_path_for,
)
from lib.chart_pull_and_subchart_resolution import resolve_chart_values, subchart_values
from lib.chart_registered_paths import image_paths_for, is_primary_image_path, native_components
from lib.chart_values_tree_primitives import (
    dotted_key_path,
    find_app_versions,
    find_dependency,
    get_path,
    strip_registry_host,
)
from lib.registry import parse_repo
from lib.release_baseline import resolve_baseline_chart_state

# A bare MAJOR.MINOR.PATCH version, exactly — e.g. podiumd's own Chart.yaml
# "version:", or a --baseline/target argument. Anything else (a suffix, a
# git ref, a flag) is rejected up front by every caller, rather than
# silently being treated as a literal version.
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def component_state_at_baseline(chart_dir, chart_dir_relpath, baseline, component):
    """(baseline_ref, dep, values_key, image_paths, app_versions, error)
    for `component`'s Chart.yaml dependency entry + declared image
    tag(s) at release-baseline.yaml value `baseline`, resolved against
    chart_dir's own git history — the shared lookup show-component-
    baseline-version needs (show-image-baseline-version resolves a
    single image pin directly instead, straight off lib.release_
    baseline.resolve_baseline_chart_state's own baseline_lines — see
    find_app_versions' own docstring for why it has no need for THIS
    function at all).

    Wraps lib.release_baseline.resolve_baseline_chart_state for the
    actual ref-resolution + git-show work (the part every baseline-
    reading caller now shares — see that module's own docstring), then
    does the component-specific dependency/app-version lookup on top of
    the baseline_deps/baseline_values it returns. `chart_dir_relpath`
    is only ever used for this function's OWN "no dependency" message
    below (e.g. "charts/podiumd") — resolve_baseline_chart_state derives
    its own equivalent internally from chart_dir, never exposed back out.

    On failure, error is a ready-to-print reason (no "error: " prefix —
    callers format that themselves) and the other five are None;
    baseline_ref is None whenever error is set too (matches resolve_
    baseline_chart_state's own "None on ANY failure" convention). error
    is resolve_baseline_chart_state's own message verbatim for a
    ref-resolution/Chart.yaml-read failure, or this function's own "no
    dependency named or aliased ...' message once the baseline itself
    resolved fine but `component` doesn't match anything there. Never
    raises: a caller-facing lookup like this treats "not found" as an
    ordinary, reportable outcome, not an exceptional one."""
    baseline_ref, baseline_deps, baseline_values, _baseline_lines, error = resolve_baseline_chart_state(
        chart_dir, baseline
    )
    if error:
        return None, None, None, None, None, error
    dep = find_dependency(baseline_deps, component)
    if not dep:
        return (
            None,
            None,
            None,
            None,
            None,
            (f"no dependency named or aliased '{component}' in {chart_dir_relpath}/Chart.yaml at {baseline_ref}"),
        )
    values_key = dep.get("alias", dep["name"])
    image_paths = image_paths_for(component, chart_dir)
    app_versions = find_app_versions(baseline_values, values_key, image_paths)
    return baseline_ref, dep, values_key, image_paths, app_versions, None


def repo_group_representative(repo_paths, deps):
    """The single path a shared-repository group (see paths_by_
    repository) should be treated as "the" path for — ranking each
    candidate and returning the LAST (values.yaml's own top-level key
    traversal order — the historical "repo_paths[-1]" convention every
    caller of paths_by_repository used to inline separately) among
    whichever rank tier actually has a member:
    1. (highest) a path rooted at "global" (see global_image_paths) —
       the one true source EVERY other candidate in a group like this
       can only ever be an ALIAS of (a YAML anchor, not a coincidence),
       so it always wins outright regardless of what else is in the
       group. Real case: "nginxinc/nginx-unprivileged" is aliased by
       apiproxy's own top-level image AND by 8+ real dependencies' own
       nginx sidecars alike — every one of them is genuinely the exact
       same pinned image, so there is exactly one right "component" to
       attribute a version change to: "global" itself, not whichever
       alias site happened to sort first/last among the others.
    2. a REAL Chart.yaml dependency's own registered PRIMARY image path
       (is_primary_image_path AND it has an owning dependency) — the
       SAME thing -upgrade.md's own actual_app_version-based resolution
       (dependency-first, never routed through a repository-group tie-
       break at all) already prefers.
    3. a path with no owning Chart.yaml dependency at all (podiumd's
       own directly-templated top-level block — is_primary_image_path
       is ALSO True for these, per its own "no parent to be a sidecar
       of" rule, but that's a much weaker claim than tier 2's real
       ownership) — correct as the group's representative on its own
       when NO tier-2 (or tier-1 "global") member exists.
    4. (lowest) a real dependency's own SIDECAR path.

    Real case tier 2 exists for: "keycloak.image" (tier 3 — podiumd's
    own directly-templated top-level override) and "keycloak-operator.
    operator.config.keycloakImage" (tier 2 — keycloak-operator's own
    component_image_paths()-registered primary image) share the exact
    same repository, kept in sync by convention (see the real hand-
    written comment above the images-manifest entry). Both count as
    "primary" under is_primary_image_path's own rule, so ranking by
    that alone still landed on whichever was discovered LAST during
    values.yaml's own top-level traversal (keycloak, since it sorts
    after keycloak-operator there) — the tier split here is what
    actually prefers real ownership over "no parent at all"."""
    by_values_key = {(dep.get("alias") or dep["name"]): dep for dep in deps}

    def rank(path):
        if path[0] == "global":
            return 3
        dep = by_values_key.get(path[0])
        if dep is not None and is_primary_image_path(path, deps):
            return 2
        if dep is None:
            return 1
        return 0

    best = max(rank(path) for path in repo_paths)
    return [path for path in repo_paths if rank(path) == best][-1]


def paths_by_repository(chart_dir, deps, values, paths, allow_pull=False):
    """{strip_registry_host(repository): [path, ...]} for every path in
    `paths` (e.g. lib.upgradedoc.find_image_tag_paths(values)'s own
    keys) that resolves to a repository — not just each dependency's
    own "primary" image (image_paths_for / primary_image_repositories)
    but every nested sidecar under it too. ZAC's own opa/office_
    converter sidecars are the motivating case: their real repository
    lives in ZAC's OWN vendored subchart values.yaml (a plain top-level
    "opa.image.repository" key there), not podiumd's — podiumd's own
    values.yaml only overrides their "tag:", leaving "repository:"
    commented out for documentation.

    Resolution per path: podiumd's OWN explicit "repository:" override
    at that exact nested location wins if present (get_path(values,
    ".".join(path) + ".repository")) — checked FIRST and regardless of
    whether path[0] is even a known Chart.yaml dependency, same
    resolution order lib.image_repository_check.find_images_without_
    repository already uses, and for the same reason: podiumd's own
    values.yaml answers this directly, no dependency needed to ask it.
    Next, for a path from lib.upgradedoc.find_component_version_tags (a
    component_version_paths()-registered bare tag/version field, never
    nested under an "image:"/"...Image:" dict with its own
    "repository:" sibling in the first place) — two more sources, in
    order: version_repository_path_for(dep["name"])'s own sibling field
    when that component registers one (redis-operator's own
    "imageName:", sibling to "imageTag:"); else nested_subchart_name_
    for(dep["name"], ...)'s own nested sub-subchart's documented
    default (eck-stack's own three — see
    nested_subchart_documented_image_repository), for a field with no
    override anywhere in podiumd's own values.yaml at all.
    Real case this matters for: "apiproxy"/"frankgateway"/"keycloak" are
    podiumd's own directly-templated top-level blocks with no Chart.yaml
    dependency of their own at all, yet several of them alias the very
    same shared global.images.nginx anchor a real dependency's own
    "<component>.nginx.image" sidecar does — excluding them here would
    silently split one shared-image group into "the dependencies' own
    usages" (correctly grouped) plus "everyone else" (each wrongly on
    its own), the exact opposite of this function's whole purpose.

    Only once there's no own override does a known dependency matter at
    all — its vendored subchart's own default at the same relative
    location (get_path(subchart_values, ".".join(path[1:]) +
    ".repository"), via resolve_chart_values) — resolved AT MOST ONCE
    per dependency and reused across every one of its paths, the same
    caching primary_image_repositories does for its own narrower
    curated-path case. A path whose repository can't be resolved either
    way (no own override, AND either no known dependency or its
    subchart doesn't set one either) is silently skipped — not every
    image belongs to a Chart.yaml dependency at all, and not every
    image, dependency or not, has an explicit repository set anywhere
    this function can see.

    More than one path landing under the same repository is the normal,
    expected shape for a base image shared across several unrelated
    components via values.yaml's global.images anchor block (nginx,
    curl, busybox, redis — pinned once, aliased everywhere else via a
    YAML anchor/alias — see lib.image_version's own MULTIPLE_KEY
    convention for the same "one shared image, many usage sites" idea)
    — e.g. every "<component>.nginx.image" sidecar aliasing the same
    global.images.nginx anchor lands together here, all under
    "nginxinc/nginx-unprivileged".

    allow_pull defaults to False (offline-only, matching primary_image_
    repositories' own default) — a doc-consistency check has no
    business making a network pull; whatever's already vendored is what
    it works with."""
    by_values_key = {(dep.get("alias") or dep["name"]): dep for dep in deps}
    subchart_cache = {}  # dep name -> (values_or_None, error_or_None)
    nested_subchart_cache = {}  # (dep name, nested chart name) -> repository_or_None
    groups = {}
    for path in paths:
        own_repo = get_path(values, ".".join(path) + ".repository")
        if isinstance(own_repo, str) and own_repo:
            groups.setdefault(strip_registry_host(own_repo), []).append(path)
            continue

        dep = by_values_key.get(path[0]) if path else None
        if dep is None:
            continue

        sibling_rel = version_repository_path_for(dep["name"], chart_dir)
        if sibling_rel:
            sibling_repo = get_path(values, f"{path[0]}.{sibling_rel}")
            if isinstance(sibling_repo, str) and sibling_repo:
                groups.setdefault(strip_registry_host(sibling_repo), []).append(path)
                continue

        nested_rel = ".".join(path[1:])
        nested_chart_name = nested_subchart_name_for(dep["name"], nested_rel, chart_dir)
        if nested_chart_name:
            cache_key = (dep["name"], nested_chart_name)
            if cache_key not in nested_subchart_cache:
                nested_subchart_cache[cache_key] = (
                    nested_subchart_documented_image_repository(chart_dir, dep, nested_chart_name)
                    if chart_dir is not None
                    else None
                )
            nested_repo = nested_subchart_cache[cache_key]
            if nested_repo:
                groups.setdefault(strip_registry_host(nested_repo), []).append(path)
                continue

        if dep["name"] not in subchart_cache:
            if chart_dir is None:
                subchart_cache[dep["name"]] = (
                    None,
                    f"no chart_dir given — can't resolve {dep['name']}'s subchart default",
                )
            else:
                sub_values, _source, err = resolve_chart_values(chart_dir, dep, dep["version"], allow_pull=allow_pull)
                subchart_cache[dep["name"]] = (sub_values, err)
        sub_values, _error = subchart_cache[dep["name"]]
        if sub_values is None:
            continue
        repo = get_path(sub_values, ".".join(path[1:]) + ".repository")
        if isinstance(repo, str) and repo:
            groups.setdefault(strip_registry_host(repo), []).append(path)
    return groups


def full_repository_for_path(chart_dir, deps, values, path, allow_pull=False):
    """The FULLY host-qualified repository for `path` (e.g. "docker.io/
    curlimages/curl", "mcr.microsoft.com/azure-cli") — the same per-path
    resolution chain paths_by_repository uses internally (podiumd's own
    explicit override first, then a registered component_version_paths()
    sibling field, then a registered nested subchart's own documented
    default, then the dependency's own vendored subchart default), but
    returning the REAL, un-stripped value a registry call (parse_repo/
    registry_tag_exists) or a manifest entry's own "url:" field needs —
    paths_by_repository's own strip_registry_host'd groups are only
    ever safe for repo-GROUP matching, never this: stripping first and
    reconstructing a host from the stripped remainder via parse_repo
    would silently assume Docker Hub for any image actually hosted
    elsewhere (real bug, confirmed live: images-4.9.1.yaml's own
    newly-added entries for curl/nginx-unprivileged/zac's own
    opentelemetry-collector-contrib sidecar/openbao's own csi-
    provider/vault-k8s/snapshot-agent sidecars all got a "url:" with no
    registry host at all, written straight from paths_by_repository's
    own stripped grouping key instead of through this resolution).

    A "repository:" value with no registry host embedded in the string
    at all (Docker Hub's own convention — "curlimages/curl") is
    resolved via parse_repo (adds the implicit "docker.io/"), UNLESS a
    sibling "registry:" key exists at that exact same values-tree
    location AND actually looks like a real DNS host itself — the same
    "." / ":" / "localhost" test strip_registry_host/parse_repo already
    use elsewhere for the identical question, applied here to the
    registry value rather than a combined ref string (real case: mi's
    own "image.registry: mcr.microsoft.com" alongside "image.repository:
    azure-cli" — Azure Container Registry's own convention of a bare
    image name with the host given separately, which parse_repo has no
    way to know about on its own) — that sibling, when it looks like a
    real host, is authoritative and used directly instead of parse_
    repo's own Docker Hub inference.

    A sibling "registry:" that does NOT look like a real host (real
    case: zaakbrug's own vendored chart sets "image.registry: wearefrank"
    alongside "image.repository: zaakbrug" — the upstream chart's own
    inconsistent convention, storing a bare Docker Hub NAMESPACE in the
    same field mi's own real ACR host lives in; its OWN sidecar image,
    staging.apiProxy.image, uses the "registry: ''" / full-namespace-in-
    repository shape instead) is treated as a namespace segment, not a
    host — routed through parse_repo (as "<registry>/<own_repo>") the
    same as if it had been written directly into "repository:" as one
    string, so Docker Hub is still correctly inferred underneath it.

    Every other tier already yields a real, self-describing repository
    string (a nested/vendored subchart's own documented default), so
    parse_repo alone is enough there — it's a safe no-op once a real
    host is already embedded (the "." in "docker.elastic.co" is
    detected exactly the same way a raw values.yaml override's own real
    host would be).

    None when `path` doesn't resolve to a repository at all — same
    "nothing to fall back to" cases as paths_by_repository's own
    docstring."""
    own_repo = get_path(values, ".".join(path) + ".repository")
    if isinstance(own_repo, str) and own_repo:
        registry = get_path(values, ".".join(path) + ".registry")
        if isinstance(registry, str) and registry:
            registry_head = registry.partition("/")[0]
            if "." in registry_head or ":" in registry_head or registry_head == "localhost":
                return f"{registry}/{own_repo}"
            host, repo_path = parse_repo(f"{registry}/{own_repo}")
            return f"{host}/{repo_path}"
        host, repo_path = parse_repo(own_repo)
        return f"{host}/{repo_path}"

    by_values_key = {(dep.get("alias") or dep["name"]): dep for dep in deps}
    dep = by_values_key.get(path[0]) if path else None
    if dep is None:
        return None

    sibling_rel = version_repository_path_for(dep["name"], chart_dir)
    if sibling_rel:
        sibling_repo = get_path(values, f"{path[0]}.{sibling_rel}")
        if isinstance(sibling_repo, str) and sibling_repo:
            host, repo_path = parse_repo(sibling_repo)
            return f"{host}/{repo_path}"

    nested_rel = ".".join(path[1:])
    nested_chart_name = nested_subchart_name_for(dep["name"], nested_rel, chart_dir)
    if nested_chart_name and chart_dir is not None:
        nested_repo = nested_subchart_documented_image_repository(chart_dir, dep, nested_chart_name)
        if nested_repo:
            host, repo_path = parse_repo(nested_repo)
            return f"{host}/{repo_path}"

    if chart_dir is None:
        return None
    sub_values, _source, _err = resolve_chart_values(chart_dir, dep, dep["version"], allow_pull=allow_pull)
    if sub_values is None:
        return None
    repo = get_path(sub_values, ".".join(path[1:]) + ".repository")
    if isinstance(repo, str) and repo:
        host, repo_path = parse_repo(repo)
        return f"{host}/{repo_path}"
    return None


def historical_images_manifest_paths(chart_dir, at_or_before=None):
    """This chart's own docs/images/images-<version>.yaml files, most-
    recent-first — every past release's own real, already-committed
    "what changed that hop" manifest (each one lists ONLY that hop's own
    changes, never the cumulative state — see any one of their own
    header comments), the chronological search order for "did this
    repository ever appear in an earlier release's own manifest".
    `at_or_before` (a bare "X.Y.Z" string, e.g. upgrade_docs_baseline) —
    when given, excludes any file whose own version sorts AFTER it,
    since a component's baseline-fallback search only ever wants
    releases at or before the release being compared against, never a
    later one (including the in-progress target's own images-
    <target>.yaml, which is exactly what a "changed vs baseline but has
    no entry" finding is checking in the first place — feeding IT back
    into this search would be circular). Files whose own name doesn't
    parse as "images-X.Y.Z.yaml" (images-baseline.yaml itself included)
    are silently skipped — never mistaken for a real release version."""
    if chart_dir is None:
        return []
    images_dir = chart_dir / "docs" / "images"
    if not images_dir.is_dir():
        return []
    limit = tuple(int(p) for p in at_or_before.split(".")) if at_or_before and SEMVER_RE.match(at_or_before) else None
    dated = []
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


def historical_app_version_for_repository(chart_dir, repo, at_or_before=None, expected_url=None):
    """The most recent version this EXACT repository (already stripped,
    see strip_registry_host) was pinned to in any of this chart's own
    past images-<version>.yaml manifests (historical_images_manifest_
    paths, most-recent-first) — or None if it never appears in any of
    them. The correct replacement for the removed images-baseline.yaml
    fallback: "was this image ever tracked by this project before, even
    though the Chart.yaml dependency/values.yaml block referencing it
    now is brand new" (real case: brppersonenmock, added in 4.9.0,
    whose own image had already been mirrored/used by an unrelated,
    earlier hop) — matched by repository alone (not version+digest),
    since the question is "has this repository ever been part of this
    project's own release history at all," not "is this exact pin
    already known" — the match's own historical `version` field (not
    necessarily equal to the CURRENT version) is the real answer, a
    genuine prior version to render an "X → Y" transition against,
    never forced to "(unchanged)".

    expected_url (see lib.chart.full_repository_for_path — the CURRENT
    path's own fully-qualified repository), when given, cross-checks
    each candidate entry's own "url:" field too, not just its stripped
    "name:" — real bug, real data: two genuinely DIFFERENT images can
    share the exact same stripped name purely by historical accident.
    Confirmed live: global.images.redis (added in 4.9.1, repository
    bare "redis") and redis-operator's own quay.io/opstree/redis both
    strip to "redis" — but images-4.6.4.yaml's own "redis" entry
    (url: quay.io/opstree/redis) is redis-operator's OWN old version,
    recorded under a bare "name:" from before this repo's own strip-
    registry naming convention was consistently applied everywhere (see
    docs/images/acr-mirror-naming.md's own header) — an exact `name:`
    match alone wrongly returned it as if it were global.images.redis's
    own history. An entry whose own "url:" doesn't match expected_url
    is never a match, even though its "name:" does; an entry missing
    "url:" entirely (shouldn't happen in a real manifest — every entry
    checked has one — but never trusted blindly) is likewise never
    treated as a match once expected_url is given, the same "can't
    verify, skip this candidate" convention used elsewhere rather than
    guessing it's fine. expected_url=None (the default) preserves the
    exact previous name-only behavior, for a caller with no path/deps/
    values of its own to resolve one from — still a fully deterministic,
    exact comparison either way, never a heuristic."""
    for path in historical_images_manifest_paths(chart_dir, at_or_before):
        entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("name") != repo:
                continue
            if expected_url is not None and entry.get("url") != expected_url:
                continue
            return str(entry.get("version"))
    return None


def historical_app_version_for_path(chart_dir, deps, values, path, at_or_before=None):
    """historical_app_version_for_repository, for `path`'s own resolved
    repository (see paths_by_repository's own per-path resolution
    chain) — a single-path convenience wrapper, not a separate
    resolution rule. None when `path` doesn't resolve to a repository
    at all.

    Cross-checks each candidate historical entry's own "url:" against
    `path`'s own CURRENT fully-qualified repository (lib.chart.full_
    repository_for_path) — see historical_app_version_for_repository's
    own docstring for why (a stripped "name:" alone can collide between
    two genuinely different images purely by historical accident).
    Returns None outright — never silently falling back to the old
    name-only behavior — when full_repository_for_path itself can't
    resolve a fully-qualified repository for `path` at all: there's
    nothing safe to cross-check a candidate against in that case."""
    repo_groups = paths_by_repository(chart_dir, deps, values, [path])
    repo = next(iter(repo_groups), None)
    if repo is None:
        return None
    expected_url = full_repository_for_path(chart_dir, deps, values, path)
    if expected_url is None:
        return None
    return historical_app_version_for_repository(chart_dir, repo, at_or_before, expected_url=expected_url)


def baseline_tag_for_sidecar_path(
    chart_dir, deps, target_values, baseline_values, baseline_paths, baseline_repo_groups, path
):
    """The baseline (pre-upgrade) tag for a sidecar/shared-image (or
    registered bare-version, see below) values-tree `path`, tried in two
    tiers — the one place lib.image_docs.add_missing_sidecar_rows' own
    "Component versions" table row, lib.upgradedoc.resolve_component_
    row's own "### ..." Changes heading, and fix-doc-consistency's own
    add_missing_images_manifest_entries (the images-<target>.yaml entry
    comment) all resolve a path's baseline tag, so the three can't
    quietly drift apart on what a path's real baseline version is again
    — they already had: add_missing_sidecar_rows grew this same two-tier
    lookup inline first (podiumd 4.9.1's postgres consolidation, below),
    while the other two still only ever tried an exact-path lookup
    before falling through to historical_app_version_for_path — so the
    "Component versions" table row for a moved shared image resolved a
    real prior version, but that same row's own Changes heading and its
    images-manifest entry comment (each generated from a SEPARATE
    resolution) still rendered "(new)" for the exact same path.

    1. EXACT path match: `baseline_paths` (the caller's OWN {path: tag}
       map — see below) still pins `path` itself.
    2. SAME REPOSITORY, different path: `path`'s own resolved repository
       (against target_values — the CURRENT tree, since that's the
       repository this path actually names today) already lives
       somewhere else in baseline_values, under a different values-tree
       path entirely. Real case: podiumd 4.9.1 consolidated two separate
       postgres pins (keycloak-operator's own ensurePodiumdAdminUser job
       and openbao's own schemaJob) into one new shared global.images.
       postgres anchor — that exact path never existed in the baseline,
       but the same "postgres" repository already did, elsewhere in the
       tree (openbao.database.schemaJob.image).

       Cross-checked against `path`'s own CURRENT fully-qualified
       repository (lib.chart.full_repository_for_path) — never a bare
       stripped-name coincidence, see that function's own docstring for
       why. More than one baseline path can share the exact same
       repository (several components' own sidecars all aliasing one
       shared anchor) — picked via repo_group_representative, the same
       tie-break every other repository-group caller here already uses.

    `baseline_paths` ({path: tag}) and `baseline_repo_groups`
    ({repository: [path, ...]}, i.e. paths_by_repository(chart_dir,
    deps, baseline_values, baseline_paths.keys())) are the caller's own,
    computed once up front and passed in here rather than re-derived per
    path/per call — chart.py has no repository-agnostic "every image tag
    path in this values tree" walk of its own (that's lib.upgradedoc.
    find_image_tag_paths'/find_all_image_and_version_paths' job, one
    layer up, alongside global_image_paths, already used by every
    caller to build these). `baseline_paths` is deliberately used for
    the EXACT match too (tier 1), rather than a fresh get_path call on
    baseline_values here — the one lookup shape that works unchanged
    whether `path` ends in an ordinary "...Image" tag key (get_path +
    ".tag" would apply) or is one of fix-doc-consistency's own
    registered bare component_version_paths() fields (find_component_
    version_tags — a flat scalar sibling field, no ".tag" to append at
    all), since both already collapse to the exact same {path: value}
    shape in the caller's own current_paths/baseline_paths maps.

    Returns None when NEITHER tier finds anything — the caller's own
    historical_app_version_for_path (past images-<version>.yaml
    manifest) fallback is a deliberately separate, subsequent step, not
    folded in here: an unrelated question ("did this repository ever
    appear in a past RELEASED document") from "does baseline_values'
    CURRENT tree already pin it elsewhere)."""
    if not baseline_values:
        return None
    exact_tag = baseline_paths.get(path)
    if isinstance(exact_tag, str) and exact_tag:
        return exact_tag.split("@", 1)[0]
    repo_groups = paths_by_repository(chart_dir, deps, target_values, [path])
    repo = next(iter(repo_groups), None)
    candidates = baseline_repo_groups.get(repo) if repo is not None else None
    if not candidates:
        return None
    # Cross-checked against the CURRENT path's own fully-qualified
    # repository — never trusting the raw, possibly-collided stripped
    # name alone — the same "don't trust a stripped-name coincidence"
    # reasoning historical_app_version_for_repository's own expected_url
    # cross-check uses, just applied against baseline_values here
    # instead of a past images-<version>.yaml manifest.
    expected_url = full_repository_for_path(chart_dir, deps, target_values, path)
    matching = [
        p
        for p in candidates
        if expected_url is not None and full_repository_for_path(chart_dir, deps, baseline_values, p) == expected_url
    ]
    if not matching:
        return None
    representative = repo_group_representative(matching, deps)
    representative_tag = baseline_paths.get(representative)
    return representative_tag.split("@", 1)[0] if representative_tag else None


def repository_path_map(chart_dir, deps, values, paths, allow_pull=False):
    """{strip_registry_host(repository): values-tree path} — paths_by_
    repository's own per-repository groups, collapsed to each group's
    single representative path (see repo_group_representative). Exists
    because an images-manifest entry's "name:" is, under the current
    strip-registry convention, exactly a repository in this same
    stripped form (docs/images/acr-mirror-naming.md) — so this map gives
    an exact entry -> values-tree-path match, where resolve_entry_path's
    fuzzy name-word matching breaks down: a manifest name like
    "infonl/zaakafhandelcomponent" no longer resembles the values.yaml
    key ("zac") the way the old hand-translated slugs (name: "zac")
    did. A single survivor per repository is exactly right for THIS
    purpose (one entry, one path, done) — see paths_by_repository's own
    docstring for why a caller needing every path a shared repository
    covers (not just one) should use that function directly instead."""
    return {
        repo: repo_group_representative(repo_paths, deps)
        for repo, repo_paths in paths_by_repository(chart_dir, deps, values, paths, allow_pull=allow_pull).items()
    }


def canonical_sidecar_row_names(chart_dir, deps, values, paths, allow_pull=False):
    """{canonical doc-row name: values-tree path} for every image path
    that isn't a Chart.yaml dependency's own name/alias directly — the
    two other shapes update-image-version actually writes a doc row
    under (see its own update_docs_single_component/
    update_docs_shared_image):
    - "<values_key> - <basename>" for a sidecar nested under a real
      dependency (e.g. "redis-operator - redis", "redis-operator -
      redis-exporter") — `basename` is that image's own repository's
      last "/"-segment, resolved via repository_path_map (own
      override in `values` if present, else the owning dependency's
      vendored subchart default).
    - bare "<basename>" for an image pinned under the shared "global"
      top-level key (update-image-version's MULTIPLE_KEY convention —
      no single dependency owns it, so there's no "<values_key> -"
      prefix at all; its own repository is always set explicitly
      there, never a subchart-default fallback).

    A dependency's own PRIMARY image (image_paths_for) is deliberately
    excluded — match_dependency already covers that case by the
    dependency's plain name/alias, and this function exists
    specifically for what match_dependency can't reach.

    Exists so a doc row that doesn't match a real dependency can still
    be checked against a real, deterministically-computed canonical
    name — never guessed at from free-form prose (see
    resolve_entry_path's own fuzzy word-matching, which this
    deliberately does NOT reuse).

    A sidecar path whose OWN repository matches one of `global_paths`'
    own resolved repositories (real case: several real dependencies'
    own nginx sidecars, each aliasing the exact same global.images.
    nginx anchor) is excluded from the "<values_key> - <basename>"
    registration entirely — the bare "global" name below already covers
    it, and registering BOTH would give the same version bump two
    independent, equally-valid-looking canonical names (real bug: "zac
    - nginx-unprivileged" and "frankgateway - nginx-unprivileged" both
    showing up as separate rows for what is, via the shared anchor, the
    identical change) rather than the one true "global" row every OTHER
    caller of this same shared image already expects.

    A settings.yaml component_resolution.native_components component's
    own nested images (e.g. frankgateway's etcd/apisix-dashboard/oauth2-
    proxy) are registered the exact same "<values_key> - <basename>"
    way — it has no Chart.yaml dependency at all, but it's still the
    real owner of its own subordinate images, the same as any dependency
    is of its own."""
    by_values_key = {(dep.get("alias") or dep["name"]): dep for dep in deps}
    natives = native_components(chart_dir)
    sidecar_paths, global_paths = [], []
    for path in paths:
        if not path:
            continue
        if path[0] == "global":
            global_paths.append(path)
            continue
        dep = by_values_key.get(path[0])
        # A native_components component (e.g. frankgateway) owns its own
        # nested sidecars the same way a real Chart.yaml dependency does —
        # path[0] itself IS the component's name here (no alias possible;
        # it isn't in Chart.yaml at all), so image_paths_for(path[0])
        # excludes its own primary image the same way image_paths_for(dep
        # ["name"]) does for a real dependency just below.
        owner_name = dep["name"] if dep is not None else (path[0] if path[0] in natives else None)
        if owner_name is not None and ".".join(path[1:]) not in set(image_paths_for(owner_name, chart_dir)):
            sidecar_paths.append(path)

    global_repos = set()
    for path in global_paths:
        repo = get_path(values, ".".join(path) + ".repository")
        if isinstance(repo, str) and repo:
            global_repos.add(strip_registry_host(repo))

    names = {}
    for repo, path in repository_path_map(chart_dir, deps, values, sidecar_paths, allow_pull=allow_pull).items():
        if repo in global_repos:
            continue
        basename = repo.rsplit("/", 1)[-1]
        if basename.lower() == path[0].lower():
            # A self-referential name ("keycloak-operator - keycloak-
            # operator" — real case: keycloak-operator.operator.image,
            # the operator's own container, whose repo basename happens
            # to equal the dependency's own values key) reads as a
            # confusing repeat, not a real distinct-image name. Fall
            # back to the values-tree path's own second-to-last segment
            # instead (e.g. "operator" for keycloak-operator.operator.
            # image — "keycloak-operator - operator"), when that's
            # actually distinct from the top-level key too. A path with
            # nothing but the top-level key and the final image key
            # itself (no segment in between — e.g. a hypothetical bare
            # "keycloak-operator.image" case) has no useful fallback at
            # all, so it's skipped entirely, same as before: never
            # auto-documented under the wrong template; register it in
            # settings.yaml's own component_resolution.image_paths (or
            # document it by hand) instead if
            # it ever needs its own row.
            if len(path) >= 3 and path[-2].lower() != path[0].lower():
                basename = path[-2]
            else:
                continue
        names[f"{path[0]} - {basename}"] = path
    for path in global_paths:
        repo = get_path(values, ".".join(path) + ".repository")
        if isinstance(repo, str) and repo:
            names[strip_registry_host(repo).rsplit("/", 1)[-1]] = path
    return names


def subchart_template_text(chart_dir, dep):
    """Every file under a vendored dependency's own templates/ directory
    (same .tgz/vendoring mechanics as subchart_values), concatenated into
    one blob — a plain-text haystack for "is this values.yaml key ever
    referenced by the sub-chart's own templates at all", not a real
    template parse. None if the .tgz isn't vendored, or has no
    templates/ directory at all (an unusually-shaped chart, or a minimal
    test fixture) — callers must treat that as "can't tell" and NOT as
    "definitely unreferenced", since an empty haystack would otherwise
    make every key look unreferenced."""
    tgz_path = chart_dir / "charts" / f"{dep['name']}-{dep['version']}.tgz"
    if not tgz_path.is_file():
        return None
    prefix = f"{dep['name']}/templates/"
    try:
        with tarfile.open(tgz_path) as tar:
            members = [m for m in tar.getmembers() if m.isfile() and m.name.startswith(prefix)]
            if not members:
                return None
            parts = []
            for member in members:
                f = tar.extractfile(member)
                if f is not None:
                    parts.append(f.read().decode("utf-8", errors="replace"))
            return "\n".join(parts)
    except tarfile.TarError:
        return None


def _dependency_for_pin(lines, pin_line, deps):
    """The Chart.yaml dependency + within-component subpath (e.g. "image",
    "frontend.image") for a digest pin's "tag:" line at pin_line (1-based),
    or (None, None) if the path can't be resolved to a component at all
    (fewer than "<component>.<...>.tag" segments) or that component has no
    matching Chart.yaml dependency."""
    path = dotted_key_path(lines, pin_line - 1)
    segments = path.split(".")
    if len(segments) < 3:
        return None, None
    component, subpath = segments[0], ".".join(segments[1:-1])
    dep = find_dependency(deps, component)
    if dep is None:
        return None, None
    return dep, subpath


def subchart_default_repository(chart_dir, lines, pin_line, deps, cache=None):
    """The `repository:` a digest pin's own component defaults to via its
    subchart's baked-in values.yaml, for a pin whose "tag:" line has no
    resolvable "repository:" of its own in podiumd's values.yaml (see
    resolve_pin_repo in lib.image_digests/fix-image-digests) — the same
    value Helm merges in at render time (see subchart_values). `pin_line`
    is the pin's 1-based "tag:" line number in `lines`; `deps` is
    Chart.yaml's "dependencies" list. `cache`, if passed, is a dict shared
    across calls so multiple pins under one component don't each re-read
    that component's .tgz. Returns None if the path can't be resolved at
    all, the component has no matching Chart.yaml dependency, or the
    subchart doesn't define a default repository at that path either."""
    dep, subpath = _dependency_for_pin(lines, pin_line, deps)
    if dep is None:
        return None
    if cache is None:
        cache = {}
    if dep["name"] not in cache:
        cache[dep["name"]] = subchart_values(chart_dir, dep)
    values = cache[dep["name"]]
    if values is None:
        return None
    return get_path(values, f"{subpath}.repository")


def subchart_needs_vendoring(chart_dir, lines, pin_line, deps):
    """True if a digest pin still unresolved by subchart_default_repository
    could plausibly be resolved after a fresh `helm dependency update`:
    its component matches a Chart.yaml dependency, but the .tgz that
    dependency would vendor at the version Chart.yaml currently pins isn't
    on disk. False for a component with no matching dependency at all
    (vendoring can never help — see fix-image-digests, which uses this
    to decide whether re-vendoring is worth the cost) or one already
    vendored at the current version (nothing to gain from redoing it — it
    simply doesn't default a repository at that path)."""
    dep, _ = _dependency_for_pin(lines, pin_line, deps)
    if dep is None:
        return False
    tgz_path = chart_dir / "charts" / f"{dep['name']}-{dep['version']}.tgz"
    return not tgz_path.is_file()
