"""Grouping/resolving a dependency's own repository(ies) across the
whole values tree: component_state_at_baseline, repo_group_
representative, paths_by_repository, full_repository_for_path,
repository_path_map (a values-tree {path: repository} resolver built
on those), canonical_sidecar_row_names (the same resolution, grouped
into human-facing row names), and the vendored-subchart digest-pin
helpers (subchart_template_text, _dependency_for_pin, subchart_
default_repository, subchart_needs_vendoring)."""

import tarfile
from dataclasses import dataclass

from lib.chart.nested_subchart_identity import nested_subchart_documented_image_repository
from lib.chart.nested_subchart_identity import nested_subchart_name_for
from lib.chart.nested_subchart_identity import version_repository_path_for
from lib.chart.pull_and_subchart_resolution import resolve_chart_values
from lib.chart.pull_and_subchart_resolution import subchart_values
from lib.chart.registered_paths import image_paths_for
from lib.chart.registered_paths import is_primary_image_path
from lib.chart.registered_paths import native_components
from lib.chart.values_tree_primitives import dotted_key_path
from lib.chart.values_tree_primitives import find_app_versions
from lib.chart.values_tree_primitives import find_dependency
from lib.chart.values_tree_primitives import get_path
from lib.chart.values_tree_primitives import strip_registry_host
from lib.registry import parse_repo
from lib.release_baseline import resolve_baseline_chart_state


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
    resolution order lib.image.repository_check.find_images_without_
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
    YAML anchor/alias — see lib.image.version's own MULTIPLE_KEY
    convention for the same "one shared image, many usage sites" idea)
    — e.g. every "<component>.nginx.image" sidecar aliasing the same
    global.images.nginx anchor lands together here, all under
    "nginxinc/nginx-unprivileged".

    allow_pull defaults to False (offline-only, matching primary_image_
    repositories' own default) — a doc-consistency check has no
    business making a network pull; whatever's already vendored is what
    it works with."""
    by_values_key = {(dep.get("alias") or dep["name"]): dep for dep in deps}
    state = _RepoResolutionState(chart_dir, allow_pull, {}, {})
    groups = {}
    for path in paths:
        dep = by_values_key.get(path[0]) if path else None
        repo = _grouped_repository_for_path(values, path, dep, state)
        if repo:
            groups.setdefault(repo, []).append(path)
    return groups


@dataclass
class _RepoResolutionState:
    """Per-paths_by_repository-call state: chart_dir/allow_pull (used by
    every tier's own subchart/nested-subchart lookup) plus the two
    mutable caches (dep name -> (values_or_None, error_or_None); (dep
    name, nested chart name) -> repository_or_None) every path in the
    same call shares, so a component's own .tgz/nested-subchart lookup
    happens at most once regardless of how many of its paths need
    resolving."""

    chart_dir: object
    allow_pull: bool
    subchart_cache: dict
    nested_subchart_cache: dict


def _grouped_repository_for_path(values, path, dep, state):
    """paths_by_repository's own resolution chain for a single path,
    stripped to its group key (see that function's own docstring for
    the tier order) — podiumd's own explicit override checked first,
    regardless of whether `dep` is even known; every other tier needs a
    real `dep` to resolve anything at all."""
    own_repo = get_path(values, ".".join(path) + ".repository")
    if isinstance(own_repo, str) and own_repo:
        return strip_registry_host(own_repo)
    if dep is None:
        return None
    return _grouped_repository_from_dependency(dep, path, values, state)


def _grouped_repository_from_dependency(dep, path, values, state):
    """The sibling-tag-field / nested-subchart / vendored-subchart-
    default tiers of _grouped_repository_for_path — only ever reached
    once `dep` is known and podiumd's own values.yaml has no explicit
    override at `path` itself."""
    sibling_rel = version_repository_path_for(dep["name"], state.chart_dir)
    if sibling_rel:
        sibling_repo = get_path(values, f"{path[0]}.{sibling_rel}")
        if isinstance(sibling_repo, str) and sibling_repo:
            return strip_registry_host(sibling_repo)

    nested_repo = _cached_nested_subchart_repository(dep, path, state)
    if nested_repo:
        return strip_registry_host(nested_repo)

    sub_values = _cached_subchart_values(dep, state)
    if sub_values is None:
        return None
    repo = get_path(sub_values, ".".join(path[1:]) + ".repository")
    return strip_registry_host(repo) if isinstance(repo, str) and repo else None


def _cached_nested_subchart_repository(dep, path, state):
    """state.nested_subchart_cache-backed lookup of dep's own registered
    nested sub-subchart's documented default repository at `path` (e.g.
    eck-stack's own three — see nested_subchart_documented_image_
    repository), resolved at most once per (dep, nested chart name)
    pair across the whole paths_by_repository call."""
    nested_rel = ".".join(path[1:])
    nested_chart_name = nested_subchart_name_for(dep["name"], nested_rel, state.chart_dir)
    if not nested_chart_name:
        return None
    cache_key = (dep["name"], nested_chart_name)
    if cache_key not in state.nested_subchart_cache:
        state.nested_subchart_cache[cache_key] = (
            nested_subchart_documented_image_repository(state.chart_dir, dep, nested_chart_name)
            if state.chart_dir is not None
            else None
        )
    return state.nested_subchart_cache[cache_key]


def _cached_subchart_values(dep, state):
    """state.subchart_cache-backed resolve_chart_values(dep) lookup,
    resolved at most once per dependency across the whole paths_by_
    repository call — the same caching primary_image_repositories does
    for its own narrower curated-path case."""
    if dep["name"] not in state.subchart_cache:
        if state.chart_dir is None:
            state.subchart_cache[dep["name"]] = (
                None,
                f"no chart_dir given — can't resolve {dep['name']}'s subchart default",
            )
        else:
            sub_values, _source, err = resolve_chart_values(
                state.chart_dir, dep, dep["version"], allow_pull=state.allow_pull
            )
            state.subchart_cache[dep["name"]] = (sub_values, err)
    sub_values, _error = state.subchart_cache[dep["name"]]
    return sub_values


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
    own_repo = _full_repo_from_own_override(values, path)
    if own_repo is not None:
        return own_repo

    by_values_key = {(dep.get("alias") or dep["name"]): dep for dep in deps}
    dep = by_values_key.get(path[0]) if path else None
    if dep is None:
        return None
    return _full_repo_from_dependency(chart_dir, dep, path, values, allow_pull)


def _formatted_repo(repo):
    """A "repository:" string as-read, resolved to its full host-
    qualified form via parse_repo (Docker Hub inferred when no host is
    embedded, a no-op when one already is)."""
    host, repo_path = parse_repo(repo)
    return f"{host}/{repo_path}"


def _full_repo_from_own_override(values, path):
    """full_repository_for_path's own "podiumd values.yaml override"
    tier (see that function's own docstring for the registry-sibling /
    Docker-Hub-inference rules), or None when there's no own override
    at `path` at all."""
    own_repo = get_path(values, ".".join(path) + ".repository")
    if not (isinstance(own_repo, str) and own_repo):
        return None
    registry = get_path(values, ".".join(path) + ".registry")
    if isinstance(registry, str) and registry:
        registry_head = registry.partition("/")[0]
        if "." in registry_head or ":" in registry_head or registry_head == "localhost":
            return f"{registry}/{own_repo}"
        return _formatted_repo(f"{registry}/{own_repo}")
    return _formatted_repo(own_repo)


def _full_repo_from_dependency(chart_dir, dep, path, values, allow_pull):
    """full_repository_for_path's own sibling-tag-field / nested-
    subchart / vendored-subchart-default tiers — only ever reached once
    `dep` is known and podiumd's own values.yaml has no explicit
    override at `path` itself."""
    sibling_rel = version_repository_path_for(dep["name"], chart_dir)
    if sibling_rel:
        sibling_repo = get_path(values, f"{path[0]}.{sibling_rel}")
        if isinstance(sibling_repo, str) and sibling_repo:
            return _formatted_repo(sibling_repo)

    nested_rel = ".".join(path[1:])
    nested_chart_name = nested_subchart_name_for(dep["name"], nested_rel, chart_dir)
    if nested_chart_name and chart_dir is not None:
        nested_repo = nested_subchart_documented_image_repository(chart_dir, dep, nested_chart_name)
        if nested_repo:
            return _formatted_repo(nested_repo)

    if chart_dir is None:
        return None
    sub_values, _source, _err = resolve_chart_values(chart_dir, dep, dep["version"], allow_pull=allow_pull)
    if sub_values is None:
        return None
    repo = get_path(sub_values, ".".join(path[1:]) + ".repository")
    return _formatted_repo(repo) if isinstance(repo, str) and repo else None


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
    sidecar_paths, global_paths = _classify_sidecar_and_global_paths(chart_dir, deps, paths)
    global_repos = _global_repository_set(values, global_paths)

    names = {}
    for repo, path in repository_path_map(chart_dir, deps, values, sidecar_paths, allow_pull=allow_pull).items():
        if repo in global_repos:
            continue
        row_name = _sidecar_row_name(repo, path)
        if row_name is not None:
            names[row_name] = path
    for path in global_paths:
        repo = get_path(values, ".".join(path) + ".repository")
        if isinstance(repo, str) and repo:
            names[strip_registry_host(repo).rsplit("/", 1)[-1]] = path
    return names


def _classify_sidecar_and_global_paths(chart_dir, deps, paths):
    """(sidecar_paths, global_paths) split of `paths` for canonical_
    sidecar_row_names — a path pinned under the shared "global" top-
    level key is handled entirely separately from one nested under a
    real dependency or native_components component's own subtree."""
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
    return sidecar_paths, global_paths


def _global_repository_set(values, global_paths):
    """Every global_paths entry's own resolved, stripped repository —
    canonical_sidecar_row_names' own exclusion set for a sidecar whose
    repository is ALSO reachable via the shared "global" key (see that
    function's own docstring for why registering both would give the
    same version bump two separate canonical names)."""
    global_repos = set()
    for path in global_paths:
        repo = get_path(values, ".".join(path) + ".repository")
        if isinstance(repo, str) and repo:
            global_repos.add(strip_registry_host(repo))
    return global_repos


def _sidecar_row_name(repo, path):
    """The "<values_key> - <basename>" canonical row name for one
    sidecar path, or None when there's genuinely no useful distinct name
    to register at all (see canonical_sidecar_row_names' own docstring
    for the self-referential-name fallback and its own "nothing to fall
    back to" case)."""
    basename = repo.rsplit("/", 1)[-1]
    if basename.lower() != path[0].lower():
        return f"{path[0]} - {basename}"
    if len(path) >= 3 and path[-2].lower() != path[0].lower():
        return f"{path[0]} - {path[-2]}"
    return None


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
    resolve_pin_repo in lib.image.digests/fix-image-digests) — the same
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
