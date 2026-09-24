"""fix-doc-consistency's own images-manifest entry-comment version
verification/repair, split out of that script for pylint's too-many-
lines check."""

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
    """chart_dir/deps/target_values/baseline_values/repo_map/
    upgrade_docs_baseline — fix_images_manifest_entries' own six raw
    resolution inputs (everything but the manifest text itself),
    bundled since every per-entry helper below needs some subset of
    the same six together."""

    chart_dir: Path | None
    deps: list[ChartDependency]
    target_values: YamlMapping
    baseline_values: YamlMapping | None
    repo_map: dict[str, ImagePath] | None = None
    upgrade_docs_baseline: str | None = None


@dataclass
class _BaselineSetup:
    """baseline_paths/baseline_repo_groups — grouped together since
    _manifest_entries_setup computes both from baseline_values in one
    pass (same shape as lib.fix_doc_consistency.manifest_entries_new_
    and_urls.BaselineResolution). Nested inside _ManifestEntriesSetup
    rather than living there directly, purely to stay under pylint's
    max-instance-attributes."""

    baseline_paths: dict[ImagePath, str]
    baseline_repo_groups: dict[str, list[ImagePath]]


@dataclass
class _ManifestEntriesSetup:
    """Everything _manifest_entries_setup computes once, up front, from
    text/context — reused by every per-entry helper below (mirrors
    lib.chart.repo_and_path_resolution's own setup-once-share-
    everywhere shape)."""

    lines: list[str]
    entries: list[ManifestEntry]
    entry_line_indices: list[int]
    current_paths: dict[ImagePath, str]
    baseline: _BaselineSetup
    sibling_fields: dict[ImagePath, DigestPinningException]
    same_group: Callable[[ManifestEntry, ManifestEntry], bool]


@dataclass
class _ManifestFixState:
    """changed_entries/unresolved_names/fixed_comment_versions —
    fix_images_manifest_entries' own three per-run accumulators,
    threaded into _process_manifest_entry so each entry can append
    directly rather than returning results back up for the loop to
    merge."""

    changed_entries: list[tuple[str, str | None, str]]
    unresolved_names: list[str]
    # comment line index -> the (baseline, target) versions written there
    fixed_comment_versions: dict[int, tuple[str | None, str]]


def resolve_entry_version(
    entry: ManifestEntry, paths: Mapping[ImagePath, str | None], repo_map: dict[str, ImagePath] | None = None
) -> str | None:
    """The app version pinned at the values-tree path this images-manifest
    entry resolves to, or None if it can't be resolved (no matching
    path, or that path has no version, e.g. the component didn't exist yet)."""
    path = resolve_entry_image_path(entry["name"], paths.keys(), repo_map)
    tag = paths.get(path) if path else None
    return tag.split("@")[0] if tag else None


def _manifest_entries_setup(text: str, context: ManifestEntriesContext) -> _ManifestEntriesSetup | None:
    """None when text isn't parsable/isn't a list — the "nothing to do,
    hand caller-visible text back unchanged" case fix_images_manifest_
    entries itself used to return early for."""
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
    # Same up-front grouping (against baseline_values, reused across
    # every entry below) add_missing_images_manifest_entries already
    # computes for the identical lib.chart.baseline_tag_for_sidecar_path
    # fallback.
    baseline_repo_groups = (
        paths_by_repository(context.chart_dir, context.deps, baseline_values, baseline_paths.keys())
        if baseline_values
        else {}
    )
    # chart_dir is optional here (some callers/tests pass None) — see
    # lib.upgradedoc.find_images_manifest_list_diff's own identical
    # None-safe handling.
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
    """Two-tier fallback used only when no direct baseline_paths match
    exists (see fix_images_manifest_entries' own docstring): whether
    this same repository already lives somewhere else in
    baseline_values, under a different values-tree path, then, only
    once that finds nothing either, whether the repository appears in
    any of this chart's own PAST images-<version>.yaml manifests."""
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
    """Whether this entry is a same-version, changed-digest re-pin (see
    find_images_manifest_list_diff's own digest-comparison branch,
    which this mirrors)."""
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
    """Resolves and, if needed, rewrites the one images-manifest entry
    at `entries[index]` — appending to state.changed_entries/
    unresolved_names/fixed_comment_versions in place, same shared-
    accumulator shape as _RepoResolutionState's mutable caches."""
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
    """Rewrite each images-manifest entry's preceding comment to state the
    actual source (baseline) and target versions for the image at its
    matched values-tree path. An entry is only rewritten when both ends are
    independently verifiable (a resolvable baseline, and the component
    existed there); anything else is reported, not guessed at. A component
    whose images share one comment across several entries (e.g.
    zgw-office-addin's frontend + backend) has that comment fixed once,
    from whichever entry reaches it first — later entries sharing the same
    comment line just confirm they agree, or are reported as unresolved if
    they don't (never silently overwritten twice). Returns (new_text,
    changed_entries, unresolved_names).

    context (a ManifestEntriesContext) carries chart_dir/deps/
    target_values/baseline_values/repo_map/upgrade_docs_baseline.
    context.repo_map (see lib.chart.repository_path_map) lets an entry
    match its values-tree path exactly via its own "name:"/repository,
    rather than resolve_entry_path's fuzzy name-word matching alone —
    the difference that matters for a component whose current strip-
    registry-shaped manifest name (e.g. "infonl/zaakafhandelcomponent")
    no longer resembles its values.yaml key ("zac") the way the old
    hand-translated slug did.

    Real bug this closes: a path with NO baseline value at all (no
    matching entry in baseline_paths) used to always report the entry as
    unresolved and leave its comment untouched, FOREVER — there was no
    verifier/fixer that ever re-checked an EXISTING entry's own comment
    for staleness once written, the same structural gap already found
    and fixed for -upgrade.md/-values-deltas.md HEADINGS (_resolved_
    rows_by_values_key/_fix_heading_app_versions) but never extended to
    images-<version>.yaml's own per-entry comments. Confirmed live:
    images-4.9.1.yaml's own zac otel sidecar comment read "0.158.0 ->
    0.158.0" (and three of openbao's own sidecars similarly) — a
    nonsensical arrow self-transition an earlier, now-superseded
    reordering pass wrote, never corrected since. Now, when actual_
    baseline can't be resolved directly AND context.baseline_values is a
    REAL, resolved baseline state (never when it's falsy — see resolve_
    component_row's own sidecar branch for the identical "genuinely
    resolved but empty at this path" vs "couldn't resolve a baseline at
    all" distinction), _fallback_actual_baseline tries two fallback
    tiers before concluding "genuinely new" (see its own docstring) —
    either way, the comment's own version-spec portion (see lib.
    upgradedoc.replace_version_spec) is now recomputed via image_
    manifest_version_text (also detecting a same-version, changed-
    digest re-pin the same way find_images_manifest_list_diff's own
    digest-comparison branch does) — correctly downgrading a stale
    "(digest changed)"/"(new)"/"(unchanged)" claim back to whatever it
    should actually say too, not just a stale arrow pair. Deliberately
    replaces ONLY that version-spec substring, same as before — the
    comment's own name/prefix text (which may be hand-styled, e.g. "#
    ZAC — ...", not necessarily the auto-written "# <canonical name>
    ..." convention) is never touched or re-derived; verifying THAT is a
    different, not-yet-built check."""
    setup = _manifest_entries_setup(text, context)
    if setup is None:
        return text, [], []

    state = _ManifestFixState([], [], {})
    for index, (entry, _line_idx) in enumerate(zip(setup.entries, setup.entry_line_indices, strict=False)):
        _process_manifest_entry(index, entry, context, setup, state)

    return "".join(setup.lines), state.changed_entries, state.unresolved_names
