"""Verifies every "image: {tag: ...}" block in this chart's own
values.yaml (see lib.upgradedoc.find_image_tag_paths — structural, finds
a tag regardless of whether it already carries a digest, unlike
lib.image.digests.scan_digest_pins which only ever sees ones that
already do) has its tag digest-pinned ("<version>@sha256:<64-hex>") —
the convention this chart uses everywhere else specifically so a tag can
never silently drift to a different image underneath a floating version
string, and so lib.image.digests' own duplicate/drift check and
release-table.csv's image_basename resolution (both regex/text-based)
can actually see the pin at all.

Four known exceptions:
- keycloak-operator's own "operator.image" field uses the adfinis
  keycloak-operator chart's own convention instead — a separate sibling
  "sha:" field the chart's own template appends onto the tag at render
  time ("repository:tag@sha256:{{ .sha }}"). Embedding @sha256 directly
  in "tag" there would produce an invalid double digest — see the
  values.yaml comment above that field. podiumd doesn't override "sha"
  there at all (inherits the vendored chart's own default, confirmed by
  hand against the live registry manifest to be correct for the
  currently-pinned tag) — the sibling "sha:" only ever gets set in
  podiumd's own values.yaml when overriding a stale default, so a
  follow-up structural check here can't tell "not set, correct default"
  apart from "not set, no default at all" without vendoring the
  sub-chart's own values.yaml (a genuinely different, heavier check than
  this one), so this path is exempted outright instead.
- keycloak-operator's own "operator.config.keycloakImage" field (the
  default Keycloak SERVER image the operator stamps onto CRs that don't
  specify their own — see lib.chart.COMPONENT_IMAGE_PATHS) uses the
  exact same split "tag:"/"sha:" convention, for the same reason — same
  exemption. Confirmed by hand against the real values.yaml: podiumd
  DOES override this one's own "sha:" explicitly (it deliberately runs a
  Keycloak version ahead of whatever the operator chart's own appVersion
  defaults to), unlike operator.image's inherited default above, but the
  same "not set vs. wrong default" ambiguity this check can't resolve
  structurally still applies.
- omc's own image can't be digest-pinned at all — its values.yaml
  comment says the OMC subchart itself can't handle a digest-pinned
  tag; the tag must contain ONLY the version.
- eck-operator's own "image" field uses the upstream elastic chart's
  own separate "tag:"/"digest:" convention instead (confirmed against
  the vendored eck-operator-3.5.0.tgz's own templates/_helpers.tpl:
  "{{ printf "%s:%s@%s" $repo $tag .Values.image.digest }}" when
  "image.digest" is set) — same "embedding @sha256 in tag would
  produce an invalid double digest" reasoning as keycloak-operator's
  two fields above, just a differently-named sibling field ("digest:"
  rather than "sha:").

check_digest_pinning is deliberately a fast, filesystem-only,
no-Dependencies-needed scan — nothing here ever renders or looks past
podiumd's own values.yaml. See check_shared_image_usage (below) for a
SEPARATE, render-based check this module also hosts, and check_
subchart_image_visibility for a third."""

import re

from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.pull_and_subchart_resolution import global_image_paths
from lib.chart.pull_and_subchart_resolution import resolve_subchart_default
from lib.chart.pull_and_subchart_resolution import subchart_values
from lib.chart.repo_and_path_resolution import paths_by_repository
from lib.chart.repo_and_path_resolution import repository_group_key
from lib.chart.repo_and_path_resolution import subchart_template_text
from lib.chart.values_tree_primitives import find_dependency
from lib.chart.values_tree_primitives import get_path
from lib.chart.values_tree_primitives import resolve_values_path_source
from lib.chart.values_tree_primitives import text_at
from lib.chart.values_tree_primitives import values_key_of
from lib.render_scope import CHART_NAME
from lib.render_scope import render_chart
from lib.render_scope import rendered_chart_paths
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.app_version_and_image_paths import find_all_image_and_version_paths
from lib.upgradedoc.app_version_and_image_paths import find_image_tag_paths
from lib.yaml_types import YamlMapping
from lib.yaml_types import load_yaml_mapping

# "@sha256:<64 hex chars>" at the end of a tag value — the same shape
# lib.image.digests.DIGEST_PIN_RE requires, checked here as a suffix
# match since we already have the tag value in hand rather than a raw
# line to regex.
DIGEST_SUFFIX_RE = re.compile(r"@sha256:[0-9a-f]{64}$")

# The set of fields that intentionally does NOT embed a digest in its own
# "tag" (see this module's docstring for why) now lives in charts/podiumd/
# etc/settings.yaml's own "digest_pinning.exceptions" section — see
# lib.settings.digest_pinning_exceptions, resolved fresh in check_digest_
# pinning below.

# A dotted values.yaml path as its keys, and repository -> the paths using it.
ValuesPath = tuple[str, ...]
RepoGroups = dict[str, list[ValuesPath]]
# A find_unresolved_subchart_images finding: (scope_key, subpath, tag, already_pinned).
SubchartImageFinding = tuple[str, str, str, bool]


def _deps_from_chart_yaml(chart_dir: Path):
    """Chart.yaml's own "dependencies" list, read fresh (chart_dir is all
    this module has handy) — [] if Chart.yaml doesn't exist yet, same
    "nothing to fall back to" tolerance paths_by_repository's own
    per-dependency subchart-default tier already has."""
    chart_yaml_path = chart_dir / "Chart.yaml"
    return load_chart_dependencies(chart_yaml_path) if chart_yaml_path.is_file() else []


def _repository_groups(chart_dir: Path, values: YamlMapping, deps: list[ChartDependency]) -> RepoGroups:
    """{stripped_repo: [path, ...]} for every image/version path in the
    chart — built from the exact same full path enumeration lib.image.
    docs.regenerate_images_baseline_manifest already uses for
    images-baseline.yaml (find_all_image_and_version_paths(values,
    deps) + global_image_paths(values)), fed into lib.chart.paths_by_
    repository. A purely STATIC scan — every path values.yaml
    structurally pins, with no idea whether Helm's own condition:/tags:
    mechanism actually renders it right now or not. See
    _live_repository_groups (check_shared_image_usage's own caller) for
    the render-gated version this static grouping alone is never safe
    to report consumer counts from."""
    all_paths = dict(find_all_image_and_version_paths(values, deps))
    all_paths.update(global_image_paths(values))
    return paths_by_repository(chart_dir, deps, values, all_paths.keys())


def _path_chart_tree_path(chart_dir: Path, deps: list[ChartDependency], path: tuple[str, ...]):
    """The chart-tree path (see lib.render_scope.rendered_chart_paths)
    that would need to have rendered for `path` to be a genuinely LIVE
    consumer — reuses lib.chart.resolve_subchart_default's own
    alias-keyed, nested-dependency-aware resolution (the exact same one
    find_unresolved_subchart_images/check_subchart_image_visibility
    already use above), rather than re-deriving it. A path whose
    top-level key is NOT a real Chart.yaml dependency at all (a native
    podiumd top-level block — apiproxy, frankgateway, keycloak — or the
    "global.images.*" anchor itself) is always considered live: it's
    part of podiumd's own top-level chart-tree path (CHART_NAME itself),
    which trivially renders whenever anything does."""
    dep = find_dependency(deps, path[0])
    if dep is None:
        return CHART_NAME
    chart_tree_path, _version = resolve_subchart_default(chart_dir, dep, CHART_NAME, path[1:])
    return chart_tree_path


def _live_repository_groups(
    chart_dir: Path, deps: list[ChartDependency], values: YamlMapping, rendered_paths: set[str]
) -> RepoGroups:
    """_repository_groups(...), with every consuming path whose own
    chart-tree path never actually rendered filtered out entirely —
    both from the count AND from the printed list, never just one or
    the other. The real bug this fixes (confirmed empirically against
    the real chart): every Maykin chart's own "<name>.redis.image"
    override (e.g. openzaak.redis.image) configures that chart's OWN
    NESTED bitnami/redis sub-dependency, globally disabled via "tags:
    {redis: false}" — zero resources ever render from any of their own
    charts/redis/. A purely static values.yaml scan (_repository_
    groups alone) can never tell that apart from a genuinely live
    consumer, silently inflating global.images.redis's own reported
    consumer count from its TRUE value (zero — nothing aliases it
    live) up to 10 dead paths. A repository left with zero live paths
    at all (even its own global.images.* definition, in principle) is
    dropped entirely — nothing left worth reporting."""
    raw = _repository_groups(chart_dir, values, deps)
    live: RepoGroups = {}
    for repo, paths in raw.items():
        live_paths = [p for p in paths if _path_chart_tree_path(chart_dir, deps, p) in rendered_paths]
        if live_paths:
            live[repo] = live_paths
    return live


def _global_image_usage(values: YamlMapping, repo_groups: RepoGroups) -> dict[ValuesPath, list[ValuesPath]]:
    """{def_path: [consumer_path, ...]} for every global.images.*
    registered entry (see lib.chart.global_image_paths — the deliberate
    "this is meant to be shared" mechanism: nginx, curl, busybox, redis
    today). A consumer is every OTHER path repo_groups (see
    _repository_groups) groups under the SAME repository, EXCLUDING the
    "global.images.<name>" definition path itself — that's the
    declaration, not a usage. An entry with 0 or 1 real consumers means
    the shared-anchor mechanism itself is pointless there (nothing
    aliases it at all, or exactly one thing does — the same as just
    setting the value directly at that one site)."""
    usage: dict[ValuesPath, list[ValuesPath]] = {}
    for def_path, _tag in global_image_paths(values):
        repo = text_at(values, ".".join(def_path) + ".repository")
        stripped = repository_group_key(repo) if isinstance(repo, str) and repo else None
        consumers = [p for p in repo_groups.get(stripped, []) if p != def_path] if stripped else []
        usage[def_path] = consumers
    return usage


def _non_global_shared_repo_groups(
    values: YamlMapping, repo_groups: RepoGroups, global_usage: dict[ValuesPath, list[ValuesPath]]
) -> RepoGroups:
    """repo_groups, minus every repository a global.images.* entry
    already claims (see _global_image_usage — those are reported
    separately, split into failing/report-only by real consumer count)
    and minus every repository with only a single consuming path (not
    "shared" in any interesting sense). What's left is a repository
    shared across 2+ paths PURELY incidentally — nobody declared it a
    shared anchor, it just happens to be reused — so it's never a
    failure, only ever informational, regardless of consumer count."""
    claimed: set[str] = set()
    for def_path in global_usage:
        repo = text_at(values, ".".join(def_path) + ".repository")
        if isinstance(repo, str) and repo:
            claimed.add(repository_group_key(repo))
    return {repo: paths for repo, paths in repo_groups.items() if repo not in claimed and len(paths) > 1}


def _print_path_list(chart_dir: Path, deps: list[ChartDependency], paths: list[ValuesPath]):
    for path in sorted(paths):
        source = resolve_values_path_source(chart_dir, deps, path)
        print(f"    {'.'.join(path)}  [{source}]")


def _print_shared_image_usage(
    chart_dir: Path,
    deps: list[ChartDependency],
    values: YamlMapping,
    repo_groups: RepoGroups,
    global_usage: dict[ValuesPath, list[ValuesPath]],
) -> dict[ValuesPath, list[ValuesPath]]:
    """Prints up to three sections, in order, after check_shared_image_
    usage's own render:
    1. FAILING — a global.images.* entry with 0 or 1 real consumer(s):
       the shared-anchor mechanism itself is pointless there, inline it
       instead. Changes check_shared_image_usage's own ok computation
       (the one exception to this whole check otherwise being purely
       informational).
    2. Report only — a global.images.* entry genuinely shared (2+ real
       consumers): working as intended, still worth seeing the full
       consumer list for.
    3. Report only — any OTHER repository shared across 2+ paths that
       is NOT a global.images.* registration at all (e.g. keycloak/
       keycloak, alpine/k8s) — an incidental reuse, never a failure
       regardless of consumer count (see _non_global_shared_repo_groups).

    Every consuming path is annotated with resolve_values_path_source
    (the real Chart.yaml dependency chart+version it belongs to, or
    which of podiumd's own local template file(s) reference it) so a
    reader knows exactly where to look. Returns the FAILING dict (used
    by check_shared_image_usage to fold this into its own ok/detail).
    `repo_groups`/`global_usage` are expected to already be render-gated
    (see _live_repository_groups) — this function itself does no
    render-gating of its own, only presentation."""
    underused = {p: c for p, c in global_usage.items() if len(c) <= 1}
    well_used = {p: c for p, c in global_usage.items() if len(c) >= 2}
    plain_shared = _non_global_shared_repo_groups(values, repo_groups, global_usage)

    if not underused and not well_used and not plain_shared:
        print("OK: no shared-image concerns found")
        return underused

    if underused:
        print()
        noun = "entry" if len(underused) == 1 else "entries"
        print(
            f"FAILING: {len(underused)} global.images.* {noun} registered as a shared image "
            f"but with 0 or 1 real consumer(s) — inline it directly instead of maintaining it "
            f"as a shared anchor:"
        )
        for def_path in sorted(underused):
            consumers = underused[def_path]
            print(f"  {'.'.join(def_path)} ({len(consumers)} real consumer(s)):")
            _print_path_list(chart_dir, deps, consumers)

    if well_used:
        print()
        noun = "entry" if len(well_used) == 1 else "entries"
        print(f"{len(well_used)} global.images.* {noun} genuinely shared (2+ real consumers) — report only:")
        for def_path in sorted(well_used):
            consumers = well_used[def_path]
            print(f"  {'.'.join(def_path)} ({len(consumers)} real consumers):")
            _print_path_list(chart_dir, deps, consumers)

    if plain_shared:
        print()
        print(
            f"{len(plain_shared)} other image(s) incidentally shared across 2+ values.yaml "
            f"paths (not a declared global.images.* anchor — report only, bumping one still "
            f"affects every path listed under it):"
        )
        for repo in sorted(plain_shared):
            paths = plain_shared[repo]
            print(f"  {repo} ({len(paths)} consumers):")
            _print_path_list(chart_dir, deps, paths)

    return underused


def check_digest_pinning(chart_dir: Path):
    """Fast, filesystem-only check that every image tag in values.yaml
    (per find_image_tag_paths) is digest-pinned (has a trailing
    "@sha256:<64 hex chars>"), unless its path is listed in
    digest_pinning_exceptions. Unlike check_shared_image_usage below, this
    does no rendering at all — a plain text scan of values.yaml. Fails if
    any non-exempt tag is missing its digest suffix, printing each
    offending dotted path and its current tag value."""
    values_path = chart_dir / "values.yaml"
    if not values_path.is_file():
        print("OK: no values.yaml found — nothing to check")
        return True, "0 pin(s), 0 unpinned"

    values = load_yaml_mapping(values_path)
    images = list(find_image_tag_paths(values))
    exceptions = digest_pinning_exceptions(chart_dir)

    missing = [(path, tag) for path, tag in images if path not in exceptions and not DIGEST_SUFFIX_RE.search(tag)]

    if not missing:
        print(f"OK: all {len(images)} image tag(s) in values.yaml are digest-pinned ({len(exceptions)} exempt)")
        return True, f"{len(images)} pin(s), 0 unpinned"

    print(f'Found {len(missing)} image tag(s) not digest-pinned (missing "@sha256:<64 hex chars>"):')
    for path, tag in sorted(missing):
        print(f"  {'.'.join(path)}.tag: {tag!r}")

    return False, f"{len(missing)}/{len(images)} image(s) not digest-pinned"


def check_shared_image_usage(chart_dir: Path, extra_args: list[str]):
    """A SEPARATE, render-based check (unlike check_digest_pinning
    above, which is a fast, filesystem-only scan): every values.yaml
    repository shared across 2+ paths, with the full list of paths
    aliasing it — the real blast radius of bumping that one shared
    image — built from the exact same path enumeration + grouping lib.
    image.docs.regenerate_images_baseline_manifest already uses
    (find_all_image_and_version_paths + global_image_paths, fed into
    lib.chart.paths_by_repository) rather than re-deriving it. Every
    consuming path annotated with lib.chart.resolve_values_path_source
    (which real Chart.yaml dependency it belongs to, or which of
    podiumd's own local template file(s) reference it).

    Renders via lib.render_scope.render_chart (same pattern as check_
    subchart_image_visibility) to gate every consuming path on whether
    its own owning chart-tree path (see _path_chart_tree_path, reusing
    lib.chart.resolve_subchart_default rather than re-deriving that
    resolution) actually rendered right now — a real, confirmed bug in
    an earlier, purely-static version of this check: every Maykin
    chart's own "<name>.redis.image" override configures that chart's
    OWN nested bitnami/redis sub-dependency, globally disabled via
    "tags: {redis: false}" (zero resources ever render from any of
    their own charts/redis/), yet a static values.yaml scan counted
    all 10 of those as real consumers of global.images.redis — its
    TRUE live consumer count is zero. A render failure here fails the
    step outright, same as check_subchart_image_visibility.

    Mostly purely informational, with ONE real pass/fail consequence:
    - a global.images.* entry (see lib.chart.global_image_paths — the
      deliberate "this is meant to be shared" mechanism: nginx, curl,
      busybox, redis today) with 0 or 1 real ALIASING consumer (any
      OTHER live path resolving to the same repository, excluding the
      global.images.* definition path itself) FAILS the check — the
      shared-anchor mechanism itself is pointless there, and should be
      inlined directly instead. 2+ real consumers stays report only.
    - any OTHER repository incidentally shared across 2+ live paths
      that is NOT a global.images.* registration at all (e.g.
      keycloak/keycloak, alpine/k8s — nobody declared these "meant to
      be shared", they just happen to be reused) never fails,
      regardless of consumer count — purely informational."""
    values_path = chart_dir / "values.yaml"
    if not values_path.is_file():
        print("OK: no values.yaml found — nothing to check")
        return True, "nothing to check"

    result = render_chart(chart_dir, extra_args)
    if result.returncode != 0:
        return False, "helm template failed to render"
    rendered_paths = rendered_chart_paths(result.stdout)

    values = load_yaml_mapping(values_path)
    deps = _deps_from_chart_yaml(chart_dir)
    repo_groups = _live_repository_groups(chart_dir, deps, values, rendered_paths)
    global_usage = _global_image_usage(values, repo_groups)
    underused = _print_shared_image_usage(chart_dir, deps, values, repo_groups, global_usage)

    if underused:
        noun = "entry" if len(underused) == 1 else "entries"
        return False, f"{len(underused)} global.images.* {noun} under-used (failing)"
    return True, "every global.images.* entry has 2+ real consumers"


def find_unresolved_subchart_images(
    chart_dir: Path, deps: list[ChartDependency], own_values: YamlMapping, rendered_paths: set[str]
) -> list[SubchartImageFinding]:
    """(scope_key, subpath, tag, already_pinned) for every "<key>: {tag:
    ...}" block ("image", or an "...Image"-suffixed sibling — see
    lib.upgradedoc.find_image_tag_paths) found in a vendored dependency's
    OWN default values.yaml (see lib.chart.subchart_values) that podiumd's
    own values.yaml (`own_values`) does NOT override at the corresponding
    path — i.e. an image the check above can never see, since it only
    ever walks podiumd's own values.yaml, not a sub-chart's. `deps` is
    the chart's own Chart.yaml "dependencies" list (a caller that already
    has both `deps`/`own_values` in hand — e.g. lib.image.docs.
    regenerate_images_baseline_manifest — passes them straight through
    rather than this function re-reading Chart.yaml/values.yaml itself;
    check_subchart_image_visibility below reads them fresh from
    `chart_dir` since it has nothing else handy). `scope_key` is the
    dependency's alias (or name) as used in podiumd's own values.yaml;
    `subpath` is the dotted path within that scope, always ending in the
    image key itself (just "image" for the sub-chart's own top-level
    "image:"). A dependency not yet vendored (no .tgz under
    chart_dir/charts/ — see the "Dependencies" step) is silently skipped,
    since there's nothing on disk yet to read; a genuinely un-findable
    default counts the same as no default at all rather than a hard
    error, since Helm itself would fall back to whatever's actually
    vendored at render time regardless of what this scan can parse.

    ALSO includes a block whose own "tag:" is null/missing but which DOES
    have a "repository:" (lib.upgradedoc.find_image_tag_paths's own
    include_null_tags mode) — resolved to `tag`=the dependency's (or, for
    a NESTED dependency, that nested dependency's own — see lib.chart.
    resolve_subchart_default) Chart.yaml "appVersion", the exact version
    Helm's own ".tag | default .Chart.AppVersion" template convention
    would use. Skipped outright if that can't be resolved to anything
    real (never fabricated).

    `rendered_paths` (see lib.render_scope.rendered_chart_paths, from a
    real `helm template` render) gates EVERY finding — real tag or
    resolved-default alike — on whether its own owning chart-tree path
    (lib.chart.resolve_subchart_default's own first half; usually dep's
    own top-level path, but a NESTED dependency's own path when the
    field actually belongs to one of dep's OWN declared Chart.yaml
    dependencies instead) actually rendered at least one resource right
    now. A genuinely-vendored default sitting in a sub-chart's own
    values.yaml doesn't mean Helm ever installs it — Helm's own
    condition:/tags: mechanism (directly on dep, or transitively on one
    of ITS OWN nested dependencies) can leave it entirely inert, e.g.
    openinwoner's own bundled eck-operator (globally disabled via ITS
    OWN Chart.yaml "tags:", set in podiumd's own top-level values.yaml)
    or zaakbrug's own condition-disabled "staging" block.

    Also silently drops a finding whose top-level values key is never
    referenced anywhere in that same sub-chart's own templates/ (see
    subchart_template_text) -- e.g. pabc's own "web"/"poller" keys, which
    no template in the pabc chart reads at all: setting a podiumd override
    there would be structurally inert regardless of value, so it isn't
    even a judgment call. Only applied when templates/ was actually readable (non-None) -- a
    dependency with no readable templates/ at all (an unusually-shaped
    chart, or a test fixture that only vendors values.yaml) can't be told
    apart from "genuinely unreferenced" by an empty haystack, so every
    finding for it is kept instead of silently swallowed (subject to the
    render-gate above either way).

    Deliberately NOT cross-checked against digest_pinning_exceptions
    above — those exempt fields (keycloak-operator.operator, omc) are
    ones podiumd DOES
    override in its own values.yaml (that's the whole reason they need an
    exemption from the check above), so they already have an own_tag here
    and never show up as unresolved in the first place."""
    findings: list[SubchartImageFinding] = []
    for dep in deps:
        findings.extend(_findings_for_dependency(chart_dir, dep, own_values, rendered_paths))
    return findings


def _findings_for_dependency(
    chart_dir: Path, dep: ChartDependency, own_values: YamlMapping, rendered_paths: set[str]
) -> list[SubchartImageFinding]:
    """find_unresolved_subchart_images's own per-dependency body, split out
    purely to keep that function's own local count down — one dependency's
    worth of (scope_key, subpath, tag, already_pinned) findings, using the
    exact same rules its own docstring describes."""
    scope_key = values_key_of(dep)
    sub_values = subchart_values(chart_dir, dep)
    if sub_values is None:
        return []
    template_text = subchart_template_text(chart_dir, dep)

    findings: list[SubchartImageFinding] = []
    for path, tag in find_image_tag_paths(sub_values, include_null_tags=True):
        subpath = ".".join(path)
        own_image_tag_path = f"{scope_key}.{subpath}.tag"
        if get_path(own_values, own_image_tag_path) is not None:
            continue
        top_level_key = path[0]
        if template_text is not None and not re.search(rf"\b{re.escape(top_level_key)}\b", template_text):
            continue

        chart_tree_path, resolved_version = resolve_subchart_default(chart_dir, dep, CHART_NAME, path)
        if chart_tree_path not in rendered_paths:
            continue

        if tag is None:
            if resolved_version is None:
                continue
            findings.append((scope_key, subpath, resolved_version, False))
        else:
            findings.append((scope_key, subpath, tag, bool(DIGEST_SUFFIX_RE.search(tag))))
    return findings


def _print_subchart_image_finding(chart_dir: Path, deps: list[ChartDependency], finding: SubchartImageFinding):
    """Prints one finding (scope_key, subpath, tag, pinned) — the same
    4-tuple shape find_unresolved_subchart_images returns, taken here as
    one value instead of 4 separate params purely to stay under pylint's
    own max-args. Annotated with resolve_values_path_source (chart_dir/
    deps) the same way _print_shared_image_usage annotates its own
    consuming paths — a single shared resolver, one place deciding how to
    describe "where a values-tree path comes from", reused by both.
    `scope_key` here is always a real Chart.yaml dependency's own
    alias-or-name by construction (find_unresolved_subchart_images only
    ever iterates chart_yaml["dependencies"]), so this call site can only
    ever hit the resolver's "chart X@Y" branch in practice — routed
    through the shared function anyway rather than hand-writing "just show
    scope_key" here, for one consistent description regardless of call
    site."""
    scope_key, subpath, tag, pinned = finding
    own_image_tag_path = f"{scope_key}.{subpath}.tag"
    marker = "pinned" if pinned else "FLOATING"
    source = resolve_values_path_source(chart_dir, deps, (scope_key,))
    print(f"  {own_image_tag_path}: {tag!r} ({marker} in the sub-chart's own default)  [{source}]")


def check_subchart_image_visibility(chart_dir: Path, extra_args: list[str]):
    """Lists every image find_unresolved_subchart_images() finds, so a
    NEW one introduced by a dependency bump doesn't silently stay
    invisible to the pinning discipline the rest of this chart follows.

    A real pass/fail split, not report-only across the board: a
    FLOATING finding — a subchart-default image with no podiumd
    override AND no digest pin in the subchart's own default either —
    is genuinely unpinned and non-reproducible (the exact risk the
    rest of this chart's digest-pinning discipline exists to prevent),
    so it FAILS the step. A PINNED finding — the subchart's own default
    already embeds a real digest, podiumd just doesn't override it —
    is already reproducible as-is; whether it still warrants an
    explicit podiumd override (vs. being fine left as dead config, a
    permanently-disabled feature, or a generic default nobody needs to
    touch) is a per-case judgment call this scan can't make on its own,
    so it stays report-only and never fails the run by itself. Printed
    under two clearly separate headings so a reader can tell which
    category is which without cross-referencing this docstring.

    Renders via lib.render_scope.render_chart (this check's OWN need
    for a render — see rendered_chart_paths) to compute the render-gate
    find_unresolved_subchart_images requires; a render failure here
    fails the step outright too (unlike a pinned finding, which is
    genuinely report-only) — this check structurally depends on a
    working render."""
    result = render_chart(chart_dir, extra_args)
    if result.returncode != 0:
        return False, "helm template failed to render"
    rendered_paths = rendered_chart_paths(result.stdout)

    own_values = load_yaml_mapping(chart_dir / "values.yaml")
    deps = load_chart_dependencies(chart_dir / "Chart.yaml")
    findings = find_unresolved_subchart_images(chart_dir, deps, own_values, rendered_paths)
    floating = [f for f in findings if not f[3]]
    pinned = [f for f in findings if f[3]]

    if floating:
        print(
            f"FAILING: {len(floating)} image(s) with a floating, unpinned tag and no podiumd "
            f"override.\nInvisible to the digest-pinning check above — add a digest-pinned "
            f"override for each:"
        )
        for finding in sorted(floating):
            _print_subchart_image_finding(chart_dir, deps, finding)

    if pinned:
        print(
            f"Report only, NOT failing: {len(pinned)} image(s) defined only in a vendored "
            f"sub-chart's own default values.yaml, but already digest-pinned there (already "
            f"reproducible) — decide per image whether it still warrants an explicit podiumd "
            f"override:"
        )
        for finding in sorted(pinned):
            _print_subchart_image_finding(chart_dir, deps, finding)

    if not findings:
        print("OK: no sub-chart-default images found without a podiumd override")

    if floating:
        suffix = f", {len(pinned)} pinned (report only)" if pinned else ""
        return False, f"{len(floating)} floating (failing){suffix}"
    if pinned:
        return True, f"0 floating, {len(pinned)} pinned (report only)"
    return True, "0 unresolved"
