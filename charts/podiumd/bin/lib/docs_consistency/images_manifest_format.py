"""Check docs/images/images-<version>.yaml is consistent with the chart and itself.

Entries must match Chart.yaml/values.yaml; the "# Changes:" items must name a
component or image as its table row does, cover every entry and state the right
versions. Ordering and numbering are fix-doc-consistency's (see its dry-run).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from lib.chart.chart_yaml import ChartDependency
from lib.chart.repo_and_path_resolution import repository_group_key
from lib.chart.values_tree_primitives import dep_for_values_key
from lib.chart.values_tree_primitives import values_key_of
from lib.component_docs.images_manifest_changes_header import covered_display_names
from lib.image.repository_check import find_images_without_repository
from lib.images_manifest import ManifestEntry
from lib.images_manifest import ParsedManifest
from lib.images_manifest import entry_line_indices
from lib.images_manifest import images_manifest_problem
from lib.images_manifest import is_images_manifest
from lib.upgradedoc.app_version_and_image_paths import ImagePath
from lib.upgradedoc.app_version_and_image_paths import actual_app_version
from lib.upgradedoc.app_version_and_image_paths import chart_image_paths
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_image_path
from lib.upgradedoc.chart_image_index import ChartImageIndex
from lib.upgradedoc.consistency_checks import find_wrong_or_duplicate_dependency_claims
from lib.upgradedoc.consistency_checks import resolve_component_identity
from lib.upgradedoc.grouped_comments_and_changes_block import find_grouped_preceding_comment
from lib.upgradedoc.grouped_comments_and_changes_block import parse_changes_block
from lib.upgradedoc.grouped_comments_and_changes_block import path_display_name
from lib.upgradedoc.images_manifest_list_diff import ManifestDiffContext
from lib.upgradedoc.images_manifest_list_diff import ManifestDiffInputs
from lib.upgradedoc.images_manifest_list_diff import find_images_manifest_list_diff
from lib.upgradedoc.images_manifest_ordering import EntryResolution
from lib.upgradedoc.images_manifest_ordering import ManifestSortContext
from lib.upgradedoc.images_manifest_ordering import find_images_manifest_faulty_headers
from lib.upgradedoc.images_manifest_ordering import images_manifest_display_name_positions
from lib.upgradedoc.images_manifest_ordering import images_manifest_entries_share_group
from lib.upgradedoc.images_manifest_ordering import images_manifest_entry_positions
from lib.upgradedoc.string_and_parsing_basics import VersionRow
from lib.upgradedoc.string_and_parsing_basics import extract_source_version
from lib.upgradedoc.string_and_parsing_basics import extract_target_version
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.yaml_types import YamlMapping
from lib.yaml_types import YamlShapeError
from lib.yaml_types import parse_yaml


@dataclass
class ManifestCheckContext:
    """check_images_manifest_format's raw inputs; chart_dir=None skips chart_dir-gated checks."""

    upgrade_docs_baseline: str | None
    podiumd_version: str
    deps: list[ChartDependency]
    values: YamlMapping
    baseline_values: YamlMapping | None
    chart_dir: Path | None = None


@dataclass
class ResolvedManifest:
    """A manifest's parsed entries and how to resolve each to its values-tree path/display name."""

    entries: list[ManifestEntry]
    resolution: EntryResolution
    repo_groups: dict[str, list[ImagePath]]


@dataclass
class ListDiffInputs:
    """find_images_manifest_list_diff's caller-varying inputs (manifest, baseline_paths)."""

    manifest: ResolvedManifest
    baseline_paths: dict[ImagePath, str]


def _uncovered_entry_display_names(
    entries: list[ManifestEntry], entry_positions: dict[str, int], resolution: EntryResolution, covered_names: set[str]
) -> list[str]:
    """First display name of every entry group not in `covered_names`, skipping raw-dotted-path names."""
    missing: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry["name"] not in entry_positions:
            continue
        path = resolve_entry_image_path(entry["name"], resolution.current_paths.keys(), resolution.repo_map)
        if not path:
            continue
        display_name = path_display_name(path, resolution.deps, resolution.canonical_names)
        if display_name in seen or display_name == ".".join(path):
            continue
        seen.add(display_name)
        if display_name not in covered_names:
            missing.append(display_name)
    return missing


def find_images_manifest_entries_missing_changes_mention(
    text: str, entries: list[ManifestEntry], context: ManifestSortContext
) -> list[str]:
    """Display names of every entry group with no "# Changes:" item resolving to it.

    The check counterpart of add_missing_images_manifest_entries' backfill pass:
    list-diff only catches changed images without an entry, not entries missing from
    the header. `context` is a ManifestSortContext.

    Uses covered_display_names, as the fixer does. Compared by display name,
    since one item covers every entry of a multi-image component (e.g. eck-stack's
    elasticsearch + kibana). Raw-dotted-path display names are skipped (no human writes
    those). [] for invalid YAML or fewer than 2 entries.
    """
    entry_positions = images_manifest_entry_positions(text, context)
    if not entry_positions:
        return []
    display_name_positions = images_manifest_display_name_positions(text, context)

    current_paths = chart_image_paths(context.values, context.deps)
    resolution = EntryResolution(context.deps, current_paths, context.repo_map, context.canonical_names)

    covered_names = covered_display_names(text.splitlines(keepends=True), display_name_positions)
    return sorted(_uncovered_entry_display_names(entries, entry_positions, resolution, covered_names))


def _manifest_resolution_context(context: ManifestCheckContext) -> tuple[dict[str, list[ImagePath]], EntryResolution]:
    """(repo_groups, EntryResolution) derived from `context`, computed once up front.

    Needed early: canonical "<key> - <image-basename>" Changes items resolve via their known
    values-tree path, which text-only matching can't do. Empty chart_dir-gated parts
    when context.chart_dir is None.
    """
    index = ChartImageIndex(context.chart_dir, context.deps, context.values)
    if context.chart_dir is None:
        return {}, EntryResolution(context.deps, index.paths, {}, {})
    return index.repo_groups, EntryResolution(context.deps, index.paths, index.repo_map, index.canonical_names)


def _changes_item_version_mismatches(
    name: str, item: VersionRow, actual_app: str | None, actual_chart: str | None, baseline_app: str | None
):
    """One issue per version cell an item claims that disagrees with a known actual value."""
    issues: list[str] = []
    if item["app"] and actual_app and normalize_version(item["app"]) != normalize_version(actual_app):
        issues.append(f'{name}: Changes item "{item["name"]}" target app "{item["app"]}" != values.yaml "{actual_app}"')
    if item["chart"] and actual_chart and normalize_version(item["chart"]) != normalize_version(actual_chart):
        issues.append(
            f'{name}: Changes item "{item["name"]}" target chart "{item["chart"]}" != Chart.yaml "{actual_chart}"'
        )
    if item["app_source"] and baseline_app and normalize_version(item["app_source"]) != normalize_version(baseline_app):
        issues.append(
            f'{name}: Changes item "{item["name"]}" source app '
            f'"{item["app_source"]}" != upgrade_docs_baseline "{baseline_app}"'
        )
    return issues


def _entries_by_path(resolved: ResolvedManifest) -> dict[ImagePath, ManifestEntry]:
    """{values path: entry} for every path of every entry's repository (one entry covers all its paths)."""
    resolution = resolved.resolution
    by_path: dict[ImagePath, ManifestEntry] = {}
    for entry in resolved.entries:
        path = resolve_entry_image_path(entry["name"], resolution.current_paths.keys(), resolution.repo_map)
        for group_path in resolved.repo_groups.get(entry["name"], [path] if path is not None else []):
            by_path.setdefault(group_path, entry)
    return by_path


def _changes_item_issues(
    name: str, item: VersionRow, resolved: ResolvedManifest, context: ManifestCheckContext
) -> list[str]:
    """Issues for one "# Changes:" item: naming nothing it can be checked against, or a version mismatch.

    The item resolves as its table row does (resolve_component_identity): a canonical
    sidecar/shared-image name to its entry, a dependency to its versions, a native
    component to its entry. Never by a word it merely mentions.
    """
    identity = resolve_component_identity(item["name"], context.deps, resolved.resolution.canonical_names)
    dep = dep_for_values_key(context.deps, identity[1]) if identity and identity[0] == "dep" else None
    if dep is not None:
        values_key = values_key_of(dep)
        actual_app = actual_app_version(context.values, values_key, dep["name"], chart_dir=context.chart_dir, dep=dep)
        baseline_app = (
            actual_app_version(context.baseline_values, values_key, dep["name"]) if context.baseline_values else None
        )
        return _changes_item_version_mismatches(name, item, actual_app, str(dep["version"]), baseline_app)
    entries = _entries_by_path(resolved)
    entry = None
    if identity is not None and identity[0] == "sidecar":
        entry = entries.get(identity[1])
    elif identity is not None:
        entry = next((e for path, e in entries.items() if path[0] == identity[1]), None)
    if entry is None:
        return [
            (
                f'{name}: Changes item "{item["name"]}" — no matching Chart.yaml dependency or images-manifest entry; '
                "start it with the row name, as fix-doc-consistency writes it"
            )
        ]
    # A sidecar, shared or native image: its entry has the version, and there is no chart.
    return _changes_item_version_mismatches(name, item, entry.get("version"), None, None)


def _changes_block_item_issues(name: str, text: str, resolved: ResolvedManifest, context: ManifestCheckContext):
    """One issue per "# Changes:" item whose versions disagree with reality or that names nothing.

    Also flags free-form items word-matching a dependency another item already claims
    exactly (e.g. "Kiss's ECK-managed Elasticsearch ..." matching "kiss").
    """
    items = list(parse_changes_block(text))
    duplicate_names, wrong_fuzzy_names = find_wrong_or_duplicate_dependency_claims(
        [item["name"] for item in items], context.deps
    )
    issues: list[str] = []
    for item in items:
        if item["name"] in duplicate_names | wrong_fuzzy_names:
            issues.append(
                f'{name}: Changes item "{item["name"]}" is wrong or stale — not found in Chart.yaml or values.yaml'
            )
        else:
            issues.extend(_changes_item_issues(name, item, resolved, context))
    return issues


def _entry_comment_version_mismatches(
    name: str, entry: ManifestEntry, comment: str, resolution: EntryResolution, baseline_paths: dict[ImagePath, str]
):
    """Issues for one entry's preceding comment: target vs actual, source vs baseline."""
    issues: list[str] = []
    target = extract_target_version(comment)
    version = entry.get("version", "")  # present: check_images_manifest_format checked completeness first
    if target and normalize_version(target) != normalize_version(version):
        issues.append(f'{name}: entry "{entry["name"]}" comment says target "{target}", entry version is "{version}"')

    if baseline_paths:
        path = resolve_entry_image_path(entry["name"], resolution.current_paths.keys(), resolution.repo_map)
        baseline_tag = baseline_paths.get(path) if path else None
        baseline_version = baseline_tag.split("@")[0] if baseline_tag else None
        source = extract_source_version(comment)
        if source and baseline_version and normalize_version(source) != normalize_version(baseline_version):
            issues.append(
                f'{name}: entry "{entry["name"]}" comment says source '
                f'"{source}", upgrade_docs_baseline actually has "{baseline_version}"'
            )
    return issues


def _entry_comment_issues(
    name: str,
    lines: list[str],
    resolved: ResolvedManifest,
    entry_starts: list[int],
    baseline_paths: dict[ImagePath, str],
):
    """One issue per entry whose preceding comment is missing or disagrees on versions.

    A single issue instead when parsed entries and "- name:" lines differ in count, since
    they can't then be paired.
    """

    if len(resolved.entries) != len(entry_starts):
        return [
            (
                f"{name}: found {len(resolved.entries)} manifest entries but "
                f'{len(entry_starts)} lines matched by "^-\\s*name:" -- cannot '
                f"reliably match entries to their preceding comments"
            )
        ]

    def same_group(entry_a: ManifestEntry, entry_b: ManifestEntry) -> bool:
        return images_manifest_entries_share_group(
            entry_a, entry_b, resolved.resolution.current_paths, resolved.resolution.repo_map
        )

    issues: list[str] = []
    for index, (entry, _line_idx) in enumerate(zip(resolved.entries, entry_starts, strict=True)):
        comment = find_grouped_preceding_comment(lines, resolved.entries, entry_starts, index, same_group)
        if not comment:
            issues.append(f'{name}: entry "{entry["name"]}" has no preceding comment')
            continue
        issues.extend(_entry_comment_version_mismatches(name, entry, comment, resolved.resolution, baseline_paths))
    return issues


def _sidecar_header_issues(name: str, parsed: ParsedManifest, resolution: EntryResolution):
    """One issue per sidecar entry lacking its own "# sidecar: <parent> - <image-basename> ..." header.

    Borrowing a preceding entry's header via same_group is wrong when versions merely
    coincide (kiss-elastic-sync 0.3.3 -> 3.0.0 under "# KISS — 2.2.4 -> 3.0.0").
    """
    issues: list[str] = []
    for entry_name, expected, problem in find_images_manifest_faulty_headers(parsed, resolution):
        if problem == "missing":
            issues.append(
                f'{name}: entry "{entry_name}" is a sidecar of "{expected.split(" - ")[0]}" '
                f'but has no own "#   sidecar: {expected} ..." header — it may be sharing a '
                f"preceding entry's header, which only describes THAT entry's own version bump"
            )
        else:
            issues.append(f'{name}: entry "{entry_name}" has its own sidecar header, but it does not name "{expected}"')
    return issues


def _missing_changes_mention_issues(
    name: str, text: str, entries: list[ManifestEntry], sort_context: ManifestSortContext
):
    """One issue per entry with no "# Changes:" mention at all (see
    find_images_manifest_entries_missing_changes_mention)."""
    return [
        f'{name}: image "{entry_name}" has an entry but no mention in the "# Changes:" list'
        for entry_name in find_images_manifest_entries_missing_changes_mention(text, entries, sort_context)
    ]


def _structural_issues(
    name: str, text: str, parsed: ParsedManifest, resolution: EntryResolution, context: ManifestCheckContext
):
    """chart_dir-gated structural checks: sidecar headers and Changes coverage.

    fix-doc-consistency orders the entries and "# Changes:" items and numbers the items.
    """
    issues = _sidecar_header_issues(name, parsed, resolution)
    sort_context = ManifestSortContext(context.deps, context.values, resolution.repo_map, resolution.canonical_names)
    issues.extend(_missing_changes_mention_issues(name, text, parsed.entries, sort_context))
    return issues


def expected_entry_name(entry: ManifestEntry) -> str | None:
    """The expected "name:" for `entry`: its "url:" minus the registry host (the ACR mirror
    name), or None without a "url:". Same key fix_images_manifest_entry_names uses."""
    url = entry.get("url")
    return repository_group_key(url) if isinstance(url, str) else None


def _renamable_entry_names(entries: list[ManifestEntry], repo_map: Mapping[str, ImagePath]) -> set[str]:
    """Names that differ from expected_entry_name but are known repositories.

    Renaming would make them resolve, so _entry_name_issues already reports them.
    """
    return {
        str(entry["name"])
        for entry in entries
        if (expected := expected_entry_name(entry)) is not None
        and str(entry["name"]) != expected
        and expected in repo_map
    }


def _entry_name_issues(name: str, entries: list[ManifestEntry]) -> list[str]:
    """One issue per entry whose "name:" is not its expected_entry_name."""
    return [
        f'{name}: entry "{entry["name"]}" should be named "{expected}" (its url minus the registry host)'
        for entry in entries
        if (expected := expected_entry_name(entry)) is not None and str(entry["name"]) != expected
    ]


def _list_diff_issues(name: str, inputs: ListDiffInputs, context: ManifestCheckContext) -> list[str]:
    """The list-diff check: every changed image needs an entry and every entry a real change.

    Only called with non-empty baseline_paths and a chart_dir.
    """
    if context.chart_dir is None:
        return []
    unresolvable_paths = set(find_images_without_repository(context.chart_dir))
    missing_paths, stale_entry_names, unmatched_entry_names = find_images_manifest_list_diff(
        ManifestDiffInputs(
            inputs.manifest.entries,
            inputs.manifest.resolution.current_paths,
            inputs.baseline_paths,
            inputs.manifest.resolution.repo_map,
            inputs.manifest.repo_groups,
            unresolvable_paths,
            context=ManifestDiffContext(
                chart_dir=context.chart_dir,
                deps=context.deps,
                upgrade_docs_baseline=context.upgrade_docs_baseline,
                values=context.values,
                baseline_values=context.baseline_values,
            ),
        )
    )
    resolution = inputs.manifest.resolution
    issues = [
        f'{name}: image "{path_display_name(path, resolution.deps, resolution.canonical_names)}" '
        f"changed vs {context.upgrade_docs_baseline} but has no entry"
        for path in missing_paths
    ]
    issues.extend(
        f'{name}: entry "{entry_name}" is listed but its image did not change vs {context.upgrade_docs_baseline}'
        for entry_name in stale_entry_names
    )
    renamable = _renamable_entry_names(inputs.manifest.entries, inputs.manifest.resolution.repo_map)
    issues.extend(
        f'{name}: entry "{entry_name}" is wrong or stale — not found in Chart.yaml or values.yaml'
        for entry_name in unmatched_entry_names
        if entry_name not in renamable
    )
    return issues


def check_images_manifest_format(images_path: Path, context: ManifestCheckContext) -> list[str]:
    """Existence, YAML, header, entry-name and list-diff checks for the images manifest.

    The manifest counterpart of check_baseline_doc_set. `context` is a ManifestCheckContext.
    """
    if not images_path.is_file():
        return [f'expected "{images_path.name}" does not exist']

    text = images_path.read_text(encoding="utf-8")
    try:
        entries = parse_yaml(text, images_path.name)
    except yaml.YAMLError as e:
        return [f"{images_path.name} is not valid YAML: {e}"]
    except YamlShapeError as e:
        return [str(e)]
    problem = images_manifest_problem(entries)
    if problem is not None or not is_images_manifest(entries):
        return [f"{images_path.name} {problem}"]

    # fix-doc-consistency writes the "Baseline:" and "... vs ..." header lines.
    issues = _entry_name_issues(images_path.name, entries)

    repo_groups, resolution = _manifest_resolution_context(context)
    resolved = ResolvedManifest(entries, resolution, repo_groups)
    issues.extend(_changes_block_item_issues(images_path.name, text, resolved, context))

    lines = text.splitlines()
    line_indices = entry_line_indices(lines)
    baseline_paths = chart_image_paths(context.baseline_values, context.deps)
    issues.extend(_entry_comment_issues(images_path.name, lines, resolved, line_indices, baseline_paths))

    if context.chart_dir is not None:
        parsed = ParsedManifest(entries, line_indices, lines)
        issues.extend(_structural_issues(images_path.name, text, parsed, resolution, context))

    # baseline_paths is empty without a resolvable baseline, so "changed" can't be computed.
    if baseline_paths and context.chart_dir is not None:
        list_diff_inputs = ListDiffInputs(resolved, baseline_paths)
        issues.extend(_list_diff_issues(images_path.name, list_diff_inputs, context))

    return issues
