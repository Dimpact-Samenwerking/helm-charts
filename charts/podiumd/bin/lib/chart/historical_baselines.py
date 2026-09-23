"""Historical images-manifest lookups: what version a repository or a
values-tree path was pinned to in a past release (historical_images_
manifest_paths, historical_app_version_for_repository, historical_
app_version_for_path), and the two-tier baseline-tag resolution
(baseline_tag_for_sidecar_path) shared by lib.image.docs, lib.upgradedoc.
resolve_component_row, and fix-doc-consistency's own images-manifest
entry generation."""

import re

from dataclasses import dataclass

import yaml

from lib.chart.repo_and_path_resolution import full_repository_for_path
from lib.chart.repo_and_path_resolution import paths_by_repository
from lib.chart.repo_and_path_resolution import repo_group_representative
from lib.chart.values_tree_primitives import strip_registry_host

# A bare MAJOR.MINOR.PATCH version, exactly — e.g. podiumd's own Chart.yaml
# "version:", or a --baseline/target argument. Anything else (a suffix, a
# git ref, a flag) is rejected up front by every caller, rather than
# silently being treated as a literal version.
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


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
    names = {repo, strip_registry_host(expected_url)} if expected_url else {repo}
    for path in historical_images_manifest_paths(chart_dir, at_or_before):
        entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("name") not in names:
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


@dataclass
class BaselineLookup:
    """Everything baseline_tag_for_sidecar_path needs that stays fixed
    across every path it's called for: the chart/deps/target_values
    context plus the caller's own pre-computed baseline_values/
    baseline_paths/baseline_repo_groups (see that function's own
    docstring for why these three are computed once up front rather
    than re-derived per path/per call)."""

    chart_dir: object
    deps: object
    target_values: dict
    baseline_values: dict
    baseline_paths: dict
    baseline_repo_groups: dict


def baseline_lookup(chart_dir, deps, target_values, baseline_values, baseline_setup):
    """A BaselineLookup built from chart_dir/deps/target_values/
    baseline_values plus a caller's own baseline_paths/baseline_repo_groups
    bundle (baseline_setup — any object exposing those two attributes,
    e.g. fix-doc-consistency's own _BaselineSetup/BaselineResolution or
    lib.image.docs' own _SidecarScanState) — the one place every caller
    with such a bundle already in hand builds this, so the BaselineLookup
    construction itself isn't independently duplicated at each call site."""
    return BaselineLookup(
        chart_dir,
        deps,
        target_values,
        baseline_values,
        baseline_setup.baseline_paths,
        baseline_setup.baseline_repo_groups,
    )


def baseline_tag_for_sidecar_path(lookup, path):
    """The baseline (pre-upgrade) tag for a sidecar/shared-image (or
    registered bare-version, see below) values-tree `path`, tried in two
    tiers — the one place lib.image.docs.add_missing_sidecar_rows' own
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
    if not lookup.baseline_values:
        return None
    exact_tag = lookup.baseline_paths.get(path)
    if isinstance(exact_tag, str) and exact_tag:
        return exact_tag.split("@", 1)[0]
    repo_groups = paths_by_repository(lookup.chart_dir, lookup.deps, lookup.target_values, [path])
    repo = next(iter(repo_groups), None)
    candidates = lookup.baseline_repo_groups.get(repo) if repo is not None else None
    if not candidates:
        return None
    # Cross-checked against the CURRENT path's own fully-qualified
    # repository — never trusting the raw, possibly-collided stripped
    # name alone — the same "don't trust a stripped-name coincidence"
    # reasoning historical_app_version_for_repository's own expected_url
    # cross-check uses, just applied against baseline_values here
    # instead of a past images-<version>.yaml manifest.
    expected_url = full_repository_for_path(lookup.chart_dir, lookup.deps, lookup.target_values, path)
    matching = [
        p
        for p in candidates
        if expected_url is not None
        and full_repository_for_path(lookup.chart_dir, lookup.deps, lookup.baseline_values, p) == expected_url
    ]
    if not matching:
        return None
    representative = repo_group_representative(matching, lookup.deps)
    representative_tag = lookup.baseline_paths.get(representative)
    return representative_tag.split("@", 1)[0] if representative_tag else None
