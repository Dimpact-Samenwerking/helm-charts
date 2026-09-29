"""fix-doc-consistency's images-manifest entry-comment version verification/repair."""

import re

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.historical_baselines import baseline_lookup
from lib.chart.historical_baselines import baseline_tag_for_sidecar_path
from lib.chart.historical_baselines import historical_app_version_for_path
from lib.chart.pull_and_subchart_resolution import global_image_paths
from lib.chart.pull_and_subchart_resolution import resolved_digest_pin
from lib.chart.repo_and_path_resolution import paths_by_repository
from lib.images_manifest import ManifestEntry
from lib.images_manifest import try_parse_images_manifest
from lib.settings import DigestPinningException
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.app_version_and_image_paths import ImagePath
from lib.upgradedoc.app_version_and_image_paths import find_all_image_and_version_paths
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_image_path
from lib.upgradedoc.grouped_comments_and_changes_block import find_grouped_preceding_comment_line
from lib.upgradedoc.images_manifest_ordering import images_manifest_entries_share_group
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.version_cells_and_key_changes import image_manifest_version_text
from lib.upgradedoc.version_cells_and_key_changes import replace_version_spec
from lib.yaml_types import YamlMapping


@dataclass
class ManifestEntriesContext:
    """Resolution inputs shared by fix_images_manifest_entries' per-entry helpers."""

    chart_dir: Path | None
    deps: list[ChartDependency]
    target_values: YamlMapping
    baseline_values: YamlMapping | None
    repo_map: dict[str, ImagePath] | None = None
    upgrade_docs_baseline: str | None = None


@dataclass
class _BaselineSetup:
    """Baseline paths and repo groups; nested only to stay under pylint's max-instance-attributes."""

    baseline_paths: dict[ImagePath, str]
    baseline_repo_groups: dict[str, list[ImagePath]]


@dataclass
class _ManifestEntriesSetup:
    """Per-run state computed once by _manifest_entries_setup and shared by every entry."""

    lines: list[str]
    entries: list[ManifestEntry]
    entry_line_indices: list[int]
    current_paths: dict[ImagePath, str]
    baseline: _BaselineSetup
    sibling_fields: dict[ImagePath, DigestPinningException]
    same_group: Callable[[ManifestEntry, ManifestEntry], bool]


@dataclass
class _ManifestFixState:
    """Per-run accumulators each _process_manifest_entry call appends to."""

    changed_entries: list[tuple[str, str | None, str]]
    unresolved_names: list[str]
    # comment line index -> the (baseline, target) versions written there
    fixed_comment_versions: dict[int, tuple[str | None, str]]


def resolve_entry_version(
    entry: ManifestEntry, paths: Mapping[ImagePath, str | None], repo_map: dict[str, ImagePath] | None = None
) -> str | None:
    """App version at the values-tree path this entry resolves to, or None."""
    path = resolve_entry_image_path(entry["name"], paths.keys(), repo_map)
    tag = paths.get(path) if path else None
    return tag.split("@")[0] if tag else None


def _manifest_entries_setup(text: str, context: ManifestEntriesContext) -> _ManifestEntriesSetup | None:
    """None when text isn't a parsable list (caller returns text unchanged)."""
    lines = text.splitlines(keepends=True)
    entries = try_parse_images_manifest(text)
    if entries is None:
        return None

    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    current_paths = dict(find_all_image_and_version_paths(context.target_values, context.deps))
    current_paths.update(global_image_paths(context.target_values))
    baseline_values = context.baseline_values
    baseline_paths = dict(find_all_image_and_version_paths(baseline_values, context.deps)) if baseline_values else {}
    baseline_paths.update(global_image_paths(baseline_values) if baseline_values else [])
    # Grouped once for the baseline_tag_for_sidecar_path fallback.
    baseline_repo_groups = (
        paths_by_repository(context.chart_dir, context.deps, baseline_values, baseline_paths.keys())
        if baseline_values
        else {}
    )
    # chart_dir may be None (some callers/tests).
    sibling_fields = digest_pinning_exceptions(context.chart_dir) if context.chart_dir is not None else {}

    def same_group(entry_a: ManifestEntry, entry_b: ManifestEntry) -> bool:
        return images_manifest_entries_share_group(entry_a, entry_b, current_paths, context.repo_map)

    return _ManifestEntriesSetup(
        lines,
        entries,
        entry_line_indices,
        current_paths,
        _BaselineSetup(baseline_paths, baseline_repo_groups),
        sibling_fields,
        same_group,
    )


def _fallback_actual_baseline(
    context: ManifestEntriesContext, setup: _ManifestEntriesSetup, path: tuple[str, ...]
) -> str | None:
    """Baseline fallback when baseline_paths has no direct match.

    First the same repository under another path in baseline_values, then
    this chart's past images-<version>.yaml manifests."""
    actual_baseline = baseline_tag_for_sidecar_path(
        baseline_lookup(
            context.chart_dir, context.deps, context.target_values, context.baseline_values, setup.baseline
        ),
        path,
    )
    if actual_baseline is not None:
        return actual_baseline
    return historical_app_version_for_path(
        context.chart_dir, context.deps, context.target_values, path, context.upgrade_docs_baseline
    )


def _manifest_entry_digest_only_change(
    context: ManifestEntriesContext,
    setup: _ManifestEntriesSetup,
    path: tuple[str, ...],
    actual_baseline: str | None,
    actual_target: str,
):
    """Whether this entry is a same-version, changed-digest re-pin."""
    if actual_baseline is None or normalize_version(actual_baseline) != normalize_version(actual_target):
        return False
    current_tag, baseline_tag = setup.current_paths.get(path), setup.baseline.baseline_paths.get(path)
    if not (current_tag and baseline_tag):
        return False
    current_digest = resolved_digest_pin(context.target_values, path, current_tag, setup.sibling_fields)
    baseline_digest = resolved_digest_pin(context.baseline_values, path, baseline_tag, setup.sibling_fields)
    if not (current_digest and baseline_digest):
        return False
    return current_digest.split("@", 1)[1] != baseline_digest.split("@", 1)[1]


def _process_manifest_entry(
    index: int,
    entry: ManifestEntry,
    context: ManifestEntriesContext,
    setup: _ManifestEntriesSetup,
    state: _ManifestFixState,
):
    """Resolve and, if needed, rewrite the comment for entries[index], recording results in state."""
    name = entry["name"]
    comment_idx = find_grouped_preceding_comment_line(
        setup.lines, setup.entries, setup.entry_line_indices, index, setup.same_group
    )
    if comment_idx is None:
        state.unresolved_names.append(name)
        return

    path = resolve_entry_image_path(entry["name"], setup.current_paths.keys(), context.repo_map)
    actual_target = resolve_entry_version(entry, setup.current_paths, context.repo_map)
    if path is None or actual_target is None:
        state.unresolved_names.append(name)
        return

    actual_baseline = resolve_entry_version(entry, setup.baseline.baseline_paths, context.repo_map)
    if actual_baseline is None:
        if not context.baseline_values:
            state.unresolved_names.append(name)
            return
        actual_baseline = _fallback_actual_baseline(context, setup, path)

    digest_only_change = _manifest_entry_digest_only_change(context, setup, path, actual_baseline, actual_target)

    if comment_idx in state.fixed_comment_versions:
        prev_baseline, prev_target = state.fixed_comment_versions[comment_idx]
        if normalize_version(prev_baseline) != normalize_version(actual_baseline) or normalize_version(
            prev_target
        ) != normalize_version(actual_target):
            state.unresolved_names.append(name)
        return
    state.fixed_comment_versions[comment_idx] = (actual_baseline, actual_target)

    new_spec = image_manifest_version_text(actual_baseline, actual_target, digest_only_change=digest_only_change)
    new_comment_line = replace_version_spec(setup.lines[comment_idx], new_spec)
    if new_comment_line != setup.lines[comment_idx]:
        setup.lines[comment_idx] = new_comment_line
        state.changed_entries.append((name, actual_baseline, actual_target))


def fix_images_manifest_entries(
    text: str, context: ManifestEntriesContext
) -> tuple[str, list[tuple[str, str | None, str]], list[str]]:
    """Rewrite each entry's preceding comment to the actual baseline -> target versions.

    Rewritten only when both ends are verifiable; otherwise reported. A
    comment shared by several entries (e.g. zgw-office-addin) is fixed once;
    later entries must agree or are reported. context.repo_map lets entries
    match their path by repository instead of fuzzy name matching.

    Without a direct baseline value, and only when baseline_values is a real
    resolved state, _fallback_actual_baseline is tried before concluding
    "new". The version spec is recomputed with image_manifest_version_text,
    so stale "(digest changed)"/"(new)"/"(unchanged)" claims are corrected
    too. Only the version-spec substring is replaced; the comment's name
    text is left as written.

    Returns (new_text, changed_entries, unresolved_names)."""
    setup = _manifest_entries_setup(text, context)
    if setup is None:
        return text, [], []

    state = _ManifestFixState([], [], {})
    for index, (entry, _line_idx) in enumerate(zip(setup.entries, setup.entry_line_indices, strict=False)):
        _process_manifest_entry(index, entry, context, setup, state)

    return "".join(setup.lines), state.changed_entries, state.unresolved_names
