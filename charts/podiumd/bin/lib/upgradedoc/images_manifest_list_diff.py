"""Diff against the git baseline: which top-level components changed, and
which images the images-manifest "changes:" list should contain."""

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.historical_baselines import historical_app_version_for_repository
from lib.chart.pull_and_subchart_resolution import global_image_paths
from lib.chart.pull_and_subchart_resolution import resolved_digest_pin
from lib.chart.registered_paths import native_components
from lib.chart.repo_and_path_resolution import full_repository_for_path
from lib.chart.values_tree_primitives import values_key_of
from lib.chart.values_tree_primitives import version_of
from lib.images_manifest import ManifestEntry
from lib.settings import DigestPinningException
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.app_version_and_image_paths import ImagePath
from lib.upgradedoc.app_version_and_image_paths import find_all_image_and_version_paths
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_image_path
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.yaml_types import YamlMapping


def compute_changed_components(
    deps: list[ChartDependency],
    baseline_deps: list[ChartDependency],
    values: YamlMapping,
    baseline_values: YamlMapping | None,
) -> set[str]:
    """Top-level component keys (alias or name) that differ from the
    baseline: dependency added/removed, chart version bumped, or an image
    VERSION (digest ignored) under the key's values subtree changed. Ground
    truth for the docs, so it also catches components no doc mentions.

    Native components (no Chart.yaml dependency) are compared on subtree
    image versions only. Paths whose tag equals a global_image_paths tag
    are excluded: a shared global image is reported once on its own, not
    as a change in every component aliasing it."""
    current_by_key = {values_key_of(dep): dep for dep in deps}
    baseline_by_key = {values_key_of(dep): dep for dep in baseline_deps}

    current_paths = dict(find_all_image_and_version_paths(values, deps))
    baseline_paths = dict(find_all_image_and_version_paths(baseline_values, deps)) if baseline_values else {}

    global_tags = {tag for _path, tag in global_image_paths(values)}
    if baseline_values:
        global_tags |= {tag for _path, tag in global_image_paths(baseline_values)}

    def subtree_paths(key: str, paths: dict[ImagePath, str]):
        return {p: version_of(t) for p, t in paths.items() if p[0] == key and t not in global_tags}

    changed: set[str] = set()
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
    """Optional context for the digest and historical-manifest checks; see
    find_images_manifest_list_diff. Real callers pass all fields."""

    chart_dir: Path | None = None
    deps: list[ChartDependency] | None = None
    upgrade_docs_baseline: str | None = None
    values: YamlMapping | None = None
    baseline_values: YamlMapping | None = None


@dataclass
class ManifestDiffInputs:
    """Inputs of find_images_manifest_list_diff (see there for each
    field)."""

    entries: list[ManifestEntry]
    current_paths: dict[tuple[str, ...], str]
    baseline_paths: dict[ImagePath, str]
    repo_map: dict[str, tuple[str, ...]]
    repo_groups: dict[str, list[ImagePath]]
    unresolvable_paths: set[ImagePath]
    context: ManifestDiffContext = field(default_factory=ManifestDiffContext)


def _digest_changed(
    inputs: ManifestDiffInputs,
    sibling_fields: dict[ImagePath, DigestPinningException],
    path: tuple[str, ...],
    tag: str,
    baseline_tag: str,
) -> bool:
    # Only when both sides have a stored digest; a missing digest is not a
    # change.
    if inputs.context.values is None or inputs.context.baseline_values is None:
        return False
    current_digest = resolved_digest_pin(inputs.context.values, path, tag, sibling_fields)
    baseline_digest = resolved_digest_pin(inputs.context.baseline_values, path, baseline_tag, sibling_fields)
    if not current_digest or not baseline_digest:
        return False
    return current_digest.split("@", 1)[1] != baseline_digest.split("@", 1)[1]


def _pin_changed(
    inputs: ManifestDiffInputs,
    path_to_repo: dict[ImagePath, str],
    sibling_fields: dict[ImagePath, DigestPinningException],
    path: tuple[str, ...],
    tag: str,
) -> bool:
    baseline_tag = inputs.baseline_paths.get(path)
    if baseline_tag is not None:
        return version_of(tag) != version_of(baseline_tag) or _digest_changed(
            inputs, sibling_fields, path, tag, baseline_tag
        )
    # New path: check past images-<version>.yaml manifests for this
    # repository before calling it changed.
    repo = path_to_repo.get(path)
    if repo is None:
        return True
    if inputs.context.deps is not None:
        # Require a matching full repository URL, so a same-named legacy
        # entry never counts; unresolvable URL means changed.
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


def _match_entries(
    inputs: ManifestDiffInputs, representative_of: dict[ImagePath, ImagePath], changed_paths: set[ImagePath]
) -> tuple[set[ImagePath], list[str], list[str]]:
    """(matched_paths, stale_entry_names, unmatched_entry_names): each entry
    resolved to its (group-representative) values path and classified
    against changed_paths."""
    matched_paths: set[ImagePath] = set()
    stale_entry_names: list[str] = []
    unmatched_entry_names: list[str] = []
    for entry in inputs.entries:
        path = resolve_entry_image_path(entry["name"], inputs.current_paths.keys(), inputs.repo_map)
        # The fuzzy fallback can land on any member of a shared-repository
        # group; collapse to the representative like changed_paths.
        path = representative_of.get(path, path) if path is not None else None
        if path is None:
            unmatched_entry_names.append(entry["name"])
            continue
        matched_paths.add(path)
        if path not in changed_paths:
            stale_entry_names.append(entry["name"])
    return matched_paths, stale_entry_names, unmatched_entry_names


def find_images_manifest_list_diff(inputs: ManifestDiffInputs) -> tuple[list[ImagePath], list[str], list[str]]:
    """(missing_paths, stale_entry_names, unmatched_entry_names): the
    manifest's entries checked against every image pin whose version, or
    digest, differs between current_paths and baseline_paths. All empty
    means the manifest lists exactly the changed images.

    Digest changes count only when both sides have a resolvable digest
    (embedded "@sha256:" or a digest_pinning.exceptions sibling field) and
    they differ. Bare tags have nothing stored to diff; flagging them would
    report every image on every run. Without context.values/baseline_values
    the comparison is version-only.

    Entries resolve via resolve_entry_image_path (repo_map exact match, then
    fuzzy name words). repo_groups: paths sharing one repository are one
    image, represented and decided solely by repo_map's representative
    path, so a new alias of an unchanged shared image is not a change.

    unresolvable_paths (no resolvable repository) never need an entry;
    another check reports them.

    A path absent from the baseline is checked against past
    images-<version>.yaml manifests before counting as changed. With
    context.deps the match also requires the full repository URL;
    without, it matches on name alone, which can collide (e.g.
    global.images.redis vs. a legacy "name: redis" entry).

    missing_paths: changed, but no entry. stale_entry_names: entry resolves
    but the image didn't change (drop it). unmatched_entry_names: entry
    resolves to no values path (fix its name/repository or registries)."""
    representative_of = {
        path: inputs.repo_map[repo]
        for repo, paths in inputs.repo_groups.items()
        for path in paths
        if repo in inputs.repo_map
    }
    path_to_repo = {path: repo for repo, paths in inputs.repo_groups.items() for path in paths}
    # Resolved once, None-safe, instead of per _digest_changed call.
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
