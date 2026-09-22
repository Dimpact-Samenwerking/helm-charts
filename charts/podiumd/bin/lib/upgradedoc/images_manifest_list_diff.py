"""compute_changed_components (the top-level values.yaml/Chart.yaml
keys that actually changed since the baseline) and find_images_
manifest_list_diff (the images-manifest.yaml "changes:" list this
diff implies), both diffing against the true git baseline."""

from dataclasses import dataclass
from dataclasses import field

from lib.chart.historical_baselines import historical_app_version_for_repository
from lib.chart.pull_and_subchart_resolution import global_image_paths
from lib.chart.pull_and_subchart_resolution import resolved_digest_pin
from lib.chart.registered_paths import native_components
from lib.chart.repo_and_path_resolution import full_repository_for_path
from lib.chart.values_tree_primitives import version_of
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.app_version_and_image_paths import find_all_image_and_version_paths
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_image_path
from lib.upgradedoc.string_and_parsing_basics import normalize_version


def compute_changed_components(deps, baseline_deps, values, baseline_values):
    """Top-level component keys (Chart.yaml alias, or name if unaliased) that
    actually differ between the baseline and now: dependency added or
    removed, chart version bumped, or any image tag anywhere under that
    key's values.yaml subtree changed VERSION (lib.chart.version_of — the
    tag with any "@sha256:..." digest suffix stripped; see
    find_images_manifest_list_diff's own docstring for why: a chart-wide
    digest-pinning sweep can touch the digest of virtually every image at
    once with no app-version change behind any of it, and -upgrade.md is
    about version changes, never a digest re-pin on its own — that's the
    images-manifest's own concern). This is the ground truth the docs are
    checked against — independent of what they currently say, so it also
    catches a component that changed but was never added to any doc at
    all.

    Also checks every lib.chart.native_components key (a values.yaml top-
    level component with no backing Chart.yaml dependency at all, e.g.
    frankgateway) — for those there's no dep to compare, so only the
    subtree-image-version check applies; without this, such a component's
    own version bump could never register as "changed" here at all, since
    it never appears in current_by_key/baseline_by_key to begin with.

    A subtree path whose OWN tag matches one of global_image_paths' own
    entries (either side — current or baseline) is excluded from the
    subtree comparison: a shared "global.images.<name>" YAML anchor
    (e.g. nginx-unprivileged, redis) aliased into a component's own
    sidecar block is that ONE shared image's own concern (already
    reported as its own bare-basename row/section — see lib.image.docs.
    add_missing_sidecar_rows), never a real change specific to THIS
    component; without this exclusion, a single global image added (or
    bumped) once ripples into every consuming component's own subtree
    at once — real case: a new shared "redis" cache sidecar aliased
    into a dozen unrelated components in the same release, each of
    which then got a spurious, fully "(unchanged)" table row/Changes
    section added of its own, purely because its subtree gained that
    one shared path — confirmed live."""
    current_by_key = {dep.get("alias", dep["name"]): dep for dep in deps}
    baseline_by_key = {dep.get("alias", dep["name"]): dep for dep in baseline_deps}

    current_paths = dict(find_all_image_and_version_paths(values, deps))
    baseline_paths = dict(find_all_image_and_version_paths(baseline_values, deps)) if baseline_values else {}

    global_tags = {tag for _path, tag in global_image_paths(values)}
    if baseline_values:
        global_tags |= {tag for _path, tag in global_image_paths(baseline_values)}

    def subtree_paths(key, paths):
        return {p: version_of(t) for p, t in paths.items() if p[0] == key and t not in global_tags}

    changed = set()
    natives = native_components()
    for key in set(current_by_key) | set(baseline_by_key) | set(natives):
        if key in natives:
            if subtree_paths(key, current_paths) != subtree_paths(key, baseline_paths):
                changed.add(key)
            continue
        cur_dep, base_dep = current_by_key.get(key), baseline_by_key.get(key)
        if (
            cur_dep is None
            or base_dep is None
            or normalize_version(cur_dep["version"]) != normalize_version(base_dep["version"])
            or subtree_paths(key, current_paths) != subtree_paths(key, baseline_paths)
        ):
            changed.add(key)
    return changed


@dataclass
class ManifestDiffContext:
    """chart_dir/deps/upgrade_docs_baseline/values/baseline_values —
    the optional extra context _digest_changed/_pin_changed need
    beyond ManifestDiffInputs' own required core diff inputs (see its
    docstring for why these are split into a nested object rather than
    eleven flat fields). All optional, same as before splitting; every
    real caller passes all five — see find_images_manifest_list_diff's
    own docstring for what each one means."""

    chart_dir: object = None
    deps: object = None
    upgrade_docs_baseline: object = None
    values: object = None
    baseline_values: object = None


@dataclass
class ManifestDiffInputs:
    """entries/current_paths/baseline_paths/repo_map/repo_groups/
    unresolvable_paths bundled with a ManifestDiffContext (the same
    five optional values find_images_manifest_list_diff always took as
    keyword args — see ManifestDiffContext's own docstring) since every
    step of find_images_manifest_list_diff (representative/path_to_repo
    setup, _digest_changed, _pin_changed, entry matching) needs a
    different subset of these together. See find_images_manifest_list_
    diff's own docstring for what each field means."""

    entries: list
    current_paths: dict
    baseline_paths: dict
    repo_map: dict
    repo_groups: dict
    unresolvable_paths: object
    context: ManifestDiffContext = field(default_factory=ManifestDiffContext)


def _digest_changed(inputs, sibling_fields, path, tag, baseline_tag):
    # Only fires when BOTH sides have a resolvable digest of their own
    # to compare (see find_images_manifest_list_diff's own docstring) —
    # a bare tag with no stored digest on either side yields None here
    # and is deliberately left alone, not treated as "changed".
    if inputs.context.values is None or inputs.context.baseline_values is None:
        return False
    current_digest = resolved_digest_pin(inputs.context.values, path, tag, sibling_fields)
    baseline_digest = resolved_digest_pin(inputs.context.baseline_values, path, baseline_tag, sibling_fields)
    if not current_digest or not baseline_digest:
        return False
    return current_digest.split("@", 1)[1] != baseline_digest.split("@", 1)[1]


def _pin_changed(inputs, path_to_repo, sibling_fields, path, tag):
    baseline_tag = inputs.baseline_paths.get(path)
    if baseline_tag is not None:
        return version_of(tag) != version_of(baseline_tag) or _digest_changed(
            inputs, sibling_fields, path, tag, baseline_tag
        )
    # No prior value for this path at all (a component that didn't
    # exist in Chart.yaml/values.yaml until this release) — the git
    # baseline genuinely has nothing to diff against. Before
    # concluding "changed", check whether this repository already
    # appears in any of this chart's own PAST images-<version>.yaml
    # manifests (see find_images_manifest_list_diff's own docstring) —
    # never a fallback to images-baseline.yaml, an unrelated concern.
    repo = path_to_repo.get(path)
    if repo is None:
        return True
    if inputs.context.deps is not None:
        # See find_images_manifest_list_diff's own docstring:
        # cross-check against `path`'s CURRENT fully-qualified
        # repository, the same collision guard lib.chart.historical_
        # app_version_for_path already applies — never fall back to
        # the unsafe name-only match below just because THIS path's
        # own repository can't be resolved.
        expected_url = full_repository_for_path(
            inputs.context.chart_dir, inputs.context.deps, inputs.context.values, path
        )
        if expected_url is None:
            return True
        historical_version = historical_app_version_for_repository(
            inputs.context.chart_dir, repo, inputs.context.upgrade_docs_baseline, expected_url=expected_url
        )
    else:
        historical_version = historical_app_version_for_repository(
            inputs.context.chart_dir, repo, inputs.context.upgrade_docs_baseline
        )
    if historical_version is None:
        return True
    return version_of(tag) != version_of(historical_version)


def _match_entries(inputs, representative_of, changed_paths):
    """(matched_paths, stale_entry_names, unmatched_entry_names) — every
    manifest entry resolved to its values-tree path (collapsed to its
    shared-repository group's representative, same as changed_paths
    already is — see find_images_manifest_list_diff's own docstring)
    and classified against changed_paths."""
    matched_paths = set()
    stale_entry_names, unmatched_entry_names = [], []
    for entry in inputs.entries:
        path = resolve_entry_image_path(entry, inputs.current_paths.keys(), inputs.repo_map)
        # An entry can resolve to ANY path in a shared-repository group —
        # repo_map's own exact "name: is a stripped repository" hit
        # always lands on repo_map's chosen representative already, but
        # resolve_entry_path's fuzzy name-word fallback (e.g. manifest
        # name "redis-ha" fuzzy-matching the literal path segment
        # ("redis-operator", "redis-ha", "image")) can land on any OTHER
        # member instead — collapsed the same way changed_paths already
        # is, so the two sides can never disagree about which path
        # "counts" for a shared image.
        path = representative_of.get(path, path) if path is not None else None
        if path is None:
            unmatched_entry_names.append(entry["name"])
            continue
        matched_paths.add(path)
        if path not in changed_paths:
            stale_entry_names.append(entry["name"])
    return matched_paths, stale_entry_names, unmatched_entry_names


def find_images_manifest_list_diff(inputs):
    """(missing_paths, extra_entry_names) — the images-manifest's own
    "list of changed images" checked against the FULL, actual set of
    every image tag pin whose VERSION (lib.chart.version_of — the tag
    with any "@sha256:..." digest suffix stripped) OR resolvable DIGEST
    (lib.chart.resolved_digest_pin) differs between the target
    (current_paths) and upgrade_docs_baseline (baseline_paths) — see
    find_image_tag_paths for what these dicts hold.

    The digest side of this is deliberately narrow: it only fires when
    BOTH the target and upgrade_docs_baseline pin have a resolvable
    digest of their own (an embedded "@sha256:..." in the tag, or — for
    a digest_pinning.exceptions path (lib.settings.digest_pinning_
    exceptions) — the sibling field it names; see resolved_digest_pin)
    AND those two digests differ while the version stayed
    the same. A path where either side has NO resolvable digest at all
    (an ordinary bare-tag pin, digest resolved live against the
    registry rather than stored anywhere in values.yaml/git history) is
    NOT compared on digest — there is nothing stored to diff, and
    treating "no digest recorded" as "digest changed" would flag every
    such image on every run regardless of whether anything really
    changed. This still leaves the routine chart-wide digest-pinning
    sweep (see PR #437) largely out of scope: a sweep touches images
    that didn't carry a digest before, so most of it has no baseline
    digest to compare against and stays version-only exactly as
    before — but a genuine, individually-deliberate re-pin of an image
    that ALREADY carried a digest on both sides (ground-truthed against
    the real 4.9.0 baseline while adding this: only clamav.image and
    keycloak-operator's ensurePodiumdAdminUser initImage qualified, not
    a chart-wide flood) now correctly surfaces as changed instead of
    being silently invisible to this check.

    values/baseline_values (the full values trees resolved_digest_pin
    needs to look up a digest_pinning.exceptions path's own sibling
    field) are optional — omitting either one (or both) just means the digest
    comparison can never fire for ANY path (resolved_digest_pin needs a
    real values tree, not just the bare tag strings current_paths/
    baseline_paths already hold), collapsing this back to the old
    version-only behaviour. Every real caller passes both.

    deps (Chart.yaml's own "dependencies:" list) is likewise optional,
    but for a different reason: without it there's no way to compute
    lib.chart.full_repository_for_path's fully-qualified repository for
    a brand-new path, so the historical-manifest lookup below falls
    back to matching a candidate entry's stripped "name:" alone — the
    exact same collision lib.chart.historical_app_version_for_path's own
    "expected_url" cross-check exists to prevent (real case: global.
    images.redis, added in 4.9.1, colliding with images-4.6.4.yaml's own
    legacy "name: redis" entry for redis-operator's unrelated quay.io/
    opstree/redis). Every real caller passes deps too, so this fallback
    is only ever exercised by a caller with no Chart.yaml dependencies
    of its own to give.

    Each entry is matched to its values-tree path via resolve_entry_
    image_path — repo_map's exact "name: is a stripped repository"
    match first, falling back to fuzzy name-word matching — the SAME
    resolution the rest of this images-manifest check already uses.

    repo_groups: lib.chart.paths_by_repository's own {repository:
    [path, ...]} grouping. A repository shared by more than one path
    (e.g. several "<component>.nginx.image" sidecars all aliasing the
    same global.images.nginx YAML anchor) is ONE image needing at most
    ONE entry between all of them, not one each — resolved through repo_
    map's own single representative path (the same one an entry naming
    that repository resolves to via resolve_entry_image_path) for BOTH
    directions: an existing entry naming that repository always matches
    the representative regardless of which member resolve_entry_path's
    fuzzy fallback happens to land on, and "did this image actually
    change" is decided ONLY by the representative's OWN before/after
    tag — never by whether some OTHER member of the group merely started
    being used somewhere new. Real case: kiss's own indexTemplateImage
    started aliasing curlimages/curl for the first time in 4.9.0 (no
    baseline value for THAT path at all), while global.images.curl
    itself (repo_map's own representative for that repository) has the
    exact same tag before and after — the group must NOT be flagged
    "changed" on the strength of kiss's own brand-new usage alone; the
    manifest lists images whose version or digest actually changed,
    never "is newly used somewhere" on its own.

    unresolvable_paths: lib.image.repository_check.find_images_without_
    repository's own result — a path with no resolvable repository at
    all (real case: kiss.adapter.image, whose "repository:" is
    commented out in podiumd's own values.yaml AND the vendored kiss-
    chart subchart has no "adapter" default either, so it isn't a real,
    referenceable image at all — see that function's own docstring)
    never needs a manifest entry: there is nothing a {name, url,
    version, digest} entry could even correspond to. That check already
    reports it as broken on its own; this one has no business demanding
    a manifest entry for it too.

    A path with NOTHING in baseline_paths at all (baseline_tag is None
    below — a component that didn't exist in Chart.yaml/values.yaml
    until this release, so the git baseline genuinely has nothing to
    diff against) checks lib.chart.historical_app_version_for_repository
    before concluding "changed": this chart's own PAST images-
    <version>.yaml manifests (real, already-committed per-release
    documents — chart_dir/upgrade_docs_baseline, when given) may
    already record this same repository at an earlier release, even
    though THIS path is new (real case: brppersonenmock, added in
    4.9.0, whose image had already been mirrored/used by an unrelated,
    earlier hop) — never a substitute images-baseline.yaml lookup (ACR-
    mirror digest provenance, a genuinely different question), and
    never attempted at all when chart_dir/upgrade_docs_baseline aren't
    given (changed, same as when nothing is ever found).

    missing_paths: every (already-collapsed) path whose tag actually
    changed but no entry resolves to it at all — a real change the
    manifest never mentions. stale_entry_names: every entry's own
    "name:" that DOES resolve to a real values-tree path, but that
    path's tag did NOT actually change — listed without a real reason
    to be there. unmatched_entry_names: every entry's own "name:" that
    doesn't resolve to any real values-tree path AT ALL — same "wrong
    phrasing, or a stale row" gap a -upgrade.md row that names no real
    component reports (see check_docs_consistency's own duplicate_
    names/wrong_fuzzy_names handling), kept SEPARATE from stale_entry_
    names since "this entry's image is unchanged" and "this entry
    doesn't correspond to anything at all" call for two different fixes
    (drop a stale entry outright; a genuinely unmatched one needs its
    own name/repository corrected, or a values-tree lookup this
    function's own registries don't cover yet added — see
    lib.chart.COMPONENT_VERSION_PATH_NESTED_SUBCHARTS for a real
    example of the second kind). All three empty means the manifest
    lists the EXACT set of changed images, nothing more and nothing
    less.

    `inputs` is a ManifestDiffInputs bundling entries/current_paths/
    baseline_paths/repo_map/repo_groups/unresolvable_paths with a
    ManifestDiffContext (chart_dir/deps/upgrade_docs_baseline/values/
    baseline_values) — see both dataclasses' own docstrings. See
    _digest_changed/_pin_changed for the pin-changed logic and
    _match_entries for how entries are matched against it."""
    representative_of = {
        path: inputs.repo_map[repo]
        for repo, paths in inputs.repo_groups.items()
        for path in paths
        if repo in inputs.repo_map
    }
    path_to_repo = {path: repo for repo, paths in inputs.repo_groups.items() for path in paths}
    # chart_dir is optional here (its one real caller always passes it,
    # but this function's own signature allows None) -- resolved,
    # None-safely, once rather than at each _digest_changed call.
    sibling_fields = digest_pinning_exceptions(inputs.context.chart_dir) if inputs.context.chart_dir is not None else {}

    changed_paths = {
        path
        for path, tag in inputs.current_paths.items()
        if representative_of.get(path, path) == path
        and path not in inputs.unresolvable_paths
        and _pin_changed(inputs, path_to_repo, sibling_fields, path, tag)
    }

    matched_paths, stale_entry_names, unmatched_entry_names = _match_entries(inputs, representative_of, changed_paths)

    missing_paths = sorted(changed_paths - matched_paths)
    return missing_paths, stale_entry_names, unmatched_entry_names
