"""Component/version/native-component path registration lookups,
sourced from settings.yaml's own component_resolution.* config --
a component's registered image-tag/version paths, whether it's a
lockstep dependency, and whether a given values-tree path is that
component's own PRIMARY image path (as opposed to a sidecar)."""

from pathlib import Path

from lib.chart.values_tree_primitives import values_key_of
from lib.settings import component_resolution_chart_version_lockstep_components
from lib.settings import component_resolution_default_image_paths
from lib.settings import component_resolution_image_paths
from lib.settings import component_resolution_native_components
from lib.settings import component_resolution_version_paths


def component_image_paths(chart_dir=None):
    """Self-resolving wrapper around lib.settings.component_resolution_
    image_paths — same "callable from anywhere with no chart_dir
    ceremony" property as chart_version_lockstep_components above (see
    its own docstring); needed here because lib.checks.lockstep.find_
    lockstep_mismatches iterates this WHOLE dict directly (not per-
    component), so it needs a whole-dict self-resolving wrapper too, not
    just the per-component image_paths_for below."""
    chart_dir = chart_dir or Path(__file__).resolve().parents[2]
    return component_resolution_image_paths(chart_dir)


def image_paths_for(component, chart_dir=None):
    """component's own registered image path(s) (component_image_paths),
    or component_resolution_default_image_paths' generic ["image"] guess
    for anything unregistered. Self-resolving the same way component_
    image_paths is — most callers already have chart_dir in scope and
    thread it through explicitly (see e.g. component_state_at_baseline,
    primary_image_repositories, canonical_sidecar_row_names below), but
    a few (e.g. lib.chart._is_dependency_primary_rel_path, lib.
    checks.lockstep.find_chart_version_mismatches) don't, several levels
    removed from any chart_dir-bearing function — same mixed shape as
    version_paths_for below."""
    paths = component_image_paths(chart_dir)
    if component in paths:
        return paths[component]
    resolved = chart_dir or Path(__file__).resolve().parents[2]
    return component_resolution_default_image_paths(resolved)


# component (name, not alias — same convention as component_image_paths) ->
# dotted values.yaml path(s), each pointing DIRECTLY at a bare version
# string — not the "<path>.image.tag" shape image_paths_for/
# default_image_paths assume (see lib.upgradedoc.actual_app_version, which
# tries these as a second pass, unsuffixed, only once every image_paths_for
# candidate has failed to resolve a tag). Now lives in charts/podiumd/etc/
# settings.yaml's own "component_resolution.version_paths" (see lib.
# settings.component_resolution_version_paths and that file's own comment
# for the eck-stack/redis-operator reasoning). component_version_paths/
# version_paths_for below resolve it.


def component_version_paths(chart_dir=None):
    """Self-resolving wrapper around lib.settings.component_resolution_
    version_paths — same whole-dict shape as component_image_paths above,
    needed for the exact same reason (lib.checks.lockstep.find_lockstep_
    mismatches iterates this whole dict too)."""
    chart_dir = chart_dir or Path(__file__).resolve().parents[2]
    return component_resolution_version_paths(chart_dir)


def version_paths_for(component, chart_dir=None):
    """component's own registered bare-version path(s) (component_version_
    paths), or [] for anything unregistered — no generic fallback exists
    for this one (unlike image_paths_for's default_image_paths), since
    there's no equivalent "assume a plain image: block" guess that makes
    sense for a bare scalar field. Self-resolving the same mixed shape as
    image_paths_for above."""
    return component_version_paths(chart_dir).get(component, [])


# values.yaml top-level keys that are real, documentable components — with
# their own app version, own image(s), own upgrade-doc row — but have NO
# backing Chart.yaml dependency at all: implemented directly via podiumd's
# own templates, not vendored as a sub-chart. Every doc-generation/change-
# detection helper that otherwise enumerates components by walking Chart.
# yaml's dependencies (lib.upgradedoc.compute_changed_components,
# component_order_key) must also consult this registry, or such a
# component's own image-tag changes silently never register as "changed"
# at all (see lib.chart.values_tree_primitives.dep_for_values_key's own docstring, which
# already anticipated exactly this gap). Now lives in charts/podiumd/etc/
# settings.yaml's own "component_resolution.native_components" (see
# lib.settings.component_resolution_native_components and that file's own
# comment for the frankgateway reasoning) — native_components below
# resolves it.


def native_components(chart_dir=None):
    """Self-resolving wrapper around lib.settings.component_resolution_
    native_components — same shape as chart_version_lockstep_components
    below."""
    chart_dir = chart_dir or Path(__file__).resolve().parents[2]
    return component_resolution_native_components(chart_dir)


# Chart.yaml dependency NAMEs (not alias) whose own declared "version:" is
# expected to equal the resolved app version at image_paths_for(component)/
# version_paths_for(component) — a DIFFERENT lockstep signal than either
# registry above, which are both about several values-tree PATHS agreeing
# with EACH OTHER; this is about the Chart.yaml dependency's own chart
# version agreeing with the image it ships. Now lives in charts/podiumd/
# etc/settings.yaml's own "component_resolution.chart_version_lockstep_
# components" (see lib.settings.component_resolution_chart_version_
# lockstep_components and that file's own comment for the kiss-chart/
# pabc/eck-operator vs. keycloak-operator/eck-stack reasoning) —
# chart_version_lockstep_components below resolves it.


def chart_version_lockstep_components(chart_dir=None):
    """Self-resolving wrapper around lib.settings.component_resolution_
    chart_version_lockstep_components — lib/chart.py's own convenience
    functions have always been callable from anywhere with no chart_dir
    ceremony (unlike lib.settings' own accessors, which always take it
    explicitly); this preserves that property for a caller with no
    chart_dir in scope, while still accepting an explicit override for
    tests. bin/lib/chart.py always lives at <chart_dir>/bin/lib/chart.py,
    so parents[2] from this file's own location IS chart_dir when no
    override is given."""
    chart_dir = chart_dir or Path(__file__).resolve().parents[2]
    return component_resolution_chart_version_lockstep_components(chart_dir)


# The set of paths whose "tag:" field never embeds an "@sha256:..."
# digest at all -- a sibling field holds it instead, under whatever NAME
# this component's own upstream chart happens to use -- now lives in
# charts/podiumd/etc/settings.yaml's own "digest_pinning.exceptions"
# section (see lib.settings.digest_pinning_exceptions), unified with
# lib.checks.digest_pinning's own "must every tag be digest-pinned"
# exemption list and update-component-version's own write-side
# allowlist -- three independently-hand-maintained, overlapping
# registries this replaced. resolved_digest_pin below takes that
# resolved table (path -> {"sibling_field": ..., "writable": ...}) as a
# parameter rather than reading a module constant of its own.


def _is_dependency_primary_rel_path(dep, rel_path, chart_dir=None):
    """rel_path (path[1:], dotted) is one of dep's own PRIMARY image/
    version fields — image_paths_for's "image: {tag}" shape first, else
    (same fallback lib.upgradedoc.actual_app_version already uses for
    the -upgrade.md row/Changes-heading's own app-version lookup)
    version_paths_for's own bare-scalar fields for a component whose
    real app version isn't expressed as an "image:" block at all —
    redis-operator's own split "redisOperator.imageTag" (sibling to
    "imageName", not nested under a common "image:" key), or eck-stack's
    "eck-elasticsearch.version"/"eck-kibana.version". Shared by lib.
    upgradedoc.path_display_name and is_primary_image_path so the two
    can never disagree about which path counts as "the" primary."""
    return rel_path in set(image_paths_for(dep["name"], chart_dir)) or rel_path in set(
        version_paths_for(dep["name"], chart_dir)
    )


def is_primary_image_path(path, deps, chart_dir=None):
    """True when path is one of a Chart.yaml dependency's own PRIMARY
    image/version field(s) — see _is_dependency_primary_rel_path (image_
    paths_for's "image: {tag}" shape, or version_paths_for's own bare-
    scalar fallback — either can hold several co-equal fields, e.g.
    zgw-office-addin's frontend + backend, or eck-stack's own eck-
    elasticsearch + eck-kibana version fields) rather than a nested
    sidecar or a shared "global" image — the same primary/sidecar split
    lib.upgradedoc.path_display_name's own branch already makes,
    factored out here so a caller can ask the question on its own,
    without needing a canonical_names mapping too — and so
    repo_group_representative (this module) can use it directly, since
    lib.chart is a dependency of lib.upgradedoc, never the reverse.
    `chart_dir` is optional and self-resolving (see image_paths_for/
    version_paths_for), so every existing bare caller keeps working
    unchanged; thread a real one only where already in scope.

    ALSO True for a path with NO owning Chart.yaml dependency at all
    (podiumd's own directly-templated top-level block — "keycloak",
    "apiproxy", "frankgateway", the shared "global" anchor — see this
    module's own image_repository_check-adjacent docstrings for the
    real cases): there's no PARENT for such a path to be a SIDECAR of,
    so it's treated as its own standalone/primary entity, never subject
    to sidecar-only rules (needing a "#   sidecar: ..." header, sorting
    after its own top-level key's primary slot). NOTE: this is
    deliberately more permissive than verify-release-table-with-
    podiumd's own, separate is_primary_image — a native/no-dep
    component CAN have its own real sidecars (e.g. frankgateway's own
    etcd/dashboard/oauth2-proxy, none of them registered in
    image_paths_for("frankgateway") == ["image"]), which that script's
    own primary/basename resolution must still distinguish from
    frankgateway's own primary image; don't merge the two."""
    if not path:
        return False
    by_values_key = {values_key_of(dep): dep for dep in deps}
    dep = by_values_key.get(path[0])
    if dep is None:
        return True
    return _is_dependency_primary_rel_path(dep, ".".join(path[1:]), chart_dir)


# component (name, not alias) -> the sibling dotted path holding a
# version_paths_for entry's own repository — now lives in
# charts/podiumd/etc/settings.yaml's own "component_resolution.
# version_repository_paths" (see lib.settings.component_resolution_
# version_repository_paths). version_repository_path_for below resolves
# it — its own 4 call sites (documented_repository_for_path,
# paths_by_repository, full_repository_for_path here, and lib.
# image_repository_check.find_images_without_repository) ALL already
# have chart_dir in scope, so this takes it as an ordinary required
# parameter — no self-resolving needed, unlike nested_subchart_
# registered_paths below. Still tolerates chart_dir=None (returns None,
# same as "not registered") rather than raising: some of those 4 call
# sites are themselves reachable with chart_dir=None (see full_
# repository_for_path's own "chart_dir is not None" guard a few lines
# below its own call here) — this must degrade the same tolerant way,
# not crash a report-only check.
