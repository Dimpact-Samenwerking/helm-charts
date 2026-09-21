"""fix-doc-consistency's own images-manifest entry-comment version
verification/repair, split out of that script for pylint's too-many-
lines check."""

import re

import yaml

from lib.chart.historical_baselines import baseline_tag_for_sidecar_path
from lib.chart.historical_baselines import historical_app_version_for_path
from lib.chart.pull_and_subchart_resolution import global_image_paths
from lib.chart.pull_and_subchart_resolution import resolved_digest_pin
from lib.chart.repo_and_path_resolution import paths_by_repository
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.app_version_and_image_paths import find_all_image_and_version_paths
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_image_path
from lib.upgradedoc.grouped_comments_and_changes_block import find_grouped_preceding_comment_line
from lib.upgradedoc.images_manifest_ordering import images_manifest_entries_share_group
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.version_cells_and_key_changes import image_manifest_version_text
from lib.upgradedoc.version_cells_and_key_changes import replace_version_spec


def resolve_entry_version(entry, paths, repo_map=None):
    """The app version pinned at the values-tree path this images-manifest
    entry resolves to, or None if it can't be resolved (no matching
    path, or that path has no version, e.g. the component didn't exist yet)."""
    path = resolve_entry_image_path(entry, paths.keys(), repo_map)
    tag = paths.get(path) if path else None
    return tag.split("@")[0] if tag else None


def fix_images_manifest_entries(
    text, chart_dir, deps, target_values, baseline_values, repo_map=None, upgrade_docs_baseline=None
):
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

    repo_map (see lib.chart.repository_path_map) lets an entry match its
    values-tree path exactly via its own "name:"/repository, rather than
    resolve_entry_path's fuzzy name-word matching alone — the difference
    that matters for a component whose current strip-registry-shaped
    manifest name (e.g. "infonl/zaakafhandelcomponent") no longer
    resembles its values.yaml key ("zac") the way the old hand-
    translated slug did.

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
    baseline can't be resolved directly AND `baseline_values` is a REAL,
    resolved baseline state (never when it's falsy — see resolve_
    component_row's own sidecar branch for the identical "genuinely
    resolved but empty at this path" vs "couldn't resolve a baseline at
    all" distinction), this tries two fallback tiers before concluding
    "genuinely new": whether this same repository already lives
    somewhere else in baseline_values, under a different values-tree
    path (lib.chart.baseline_tag_for_sidecar_path — real case: podiumd
    4.9.1's postgres consolidation, the same fallback add_missing_
    images_manifest_entries/add_missing_sidecar_rows/resolve_
    component_row already use), then, only once that finds nothing
    either, whether the repository appears in any of this chart's own
    PAST images-<version>.yaml manifests (historical_app_version_for_
    path) — either way, the comment's own version-spec portion
    (see lib.upgradedoc.replace_version_spec) is now recomputed via
    image_manifest_version_text (also detecting a same-version, changed-
    digest re-pin the same way find_images_manifest_list_diff's own
    digest-comparison branch does) — correctly downgrading a stale
    "(digest changed)"/"(new)"/"(unchanged)" claim back to whatever it
    should actually say too, not just a stale arrow pair. Deliberately
    replaces ONLY that version-spec substring, same as before — the
    comment's own name/prefix text (which may be hand-styled, e.g. "#
    ZAC — ...", not necessarily the auto-written "# <canonical name>
    ..." convention) is never touched or re-derived; verifying THAT is a
    different, not-yet-built check."""
    lines = text.splitlines(keepends=True)
    try:
        entries = yaml.safe_load(text)
    except yaml.YAMLError:
        return text, [], []
    if not isinstance(entries, list):
        return text, [], []

    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    current_paths = dict(find_all_image_and_version_paths(target_values, deps))
    current_paths.update(global_image_paths(target_values))
    baseline_paths = dict(find_all_image_and_version_paths(baseline_values, deps)) if baseline_values else {}
    baseline_paths.update(global_image_paths(baseline_values) if baseline_values else [])
    # Same up-front grouping (against baseline_values, reused across
    # every entry below) add_missing_images_manifest_entries already
    # computes for the identical lib.chart.baseline_tag_for_sidecar_path
    # fallback.
    baseline_repo_groups = (
        paths_by_repository(chart_dir, deps, baseline_values, baseline_paths.keys()) if baseline_values else {}
    )
    # chart_dir is optional here (some callers/tests pass None) — see
    # lib.upgradedoc.find_images_manifest_list_diff's own identical
    # None-safe handling.
    sibling_fields = digest_pinning_exceptions(chart_dir) if chart_dir is not None else {}

    def same_group(entry_a, entry_b):
        return images_manifest_entries_share_group(entry_a, entry_b, current_paths, repo_map)

    changed_entries, unresolved_names = [], []
    fixed_comment_versions = {}
    for index, (entry, _line_idx) in enumerate(zip(entries, entry_line_indices, strict=False)):
        name = entry["name"]
        comment_idx = find_grouped_preceding_comment_line(lines, entries, entry_line_indices, index, same_group)
        if comment_idx is None:
            unresolved_names.append(name)
            continue

        path = resolve_entry_image_path(entry, current_paths.keys(), repo_map)
        actual_target = resolve_entry_version(entry, current_paths, repo_map)
        if path is None or actual_target is None:
            unresolved_names.append(name)
            continue

        actual_baseline = resolve_entry_version(entry, baseline_paths, repo_map)
        if actual_baseline is None:
            if not baseline_values:
                unresolved_names.append(name)
                continue
            # Neither an exact match (resolve_entry_version above) nor —
            # before concluding "genuinely new" — this same repository
            # elsewhere in baseline_values (lib.chart.baseline_tag_for_
            # sidecar_path, the SAME fallback add_missing_images_
            # manifest_entries/add_missing_sidecar_rows/resolve_
            # component_row already use for this exact question, so a
            # moved shared image's EXISTING entry comment can never
            # disagree with a freshly-added one). Only once that also
            # finds nothing: this chart's own PAST images-<version>.yaml
            # manifests.
            actual_baseline = baseline_tag_for_sidecar_path(
                chart_dir, deps, target_values, baseline_values, baseline_paths, baseline_repo_groups, path
            )
            if actual_baseline is None:
                actual_baseline = historical_app_version_for_path(
                    chart_dir, deps, target_values, path, upgrade_docs_baseline
                )

        digest_only_change = False
        if actual_baseline is not None and normalize_version(actual_baseline) == normalize_version(actual_target):
            current_tag, baseline_tag = current_paths.get(path), baseline_paths.get(path)
            if current_tag and baseline_tag:
                current_digest = resolved_digest_pin(target_values, path, current_tag, sibling_fields)
                baseline_digest = resolved_digest_pin(baseline_values, path, baseline_tag, sibling_fields)
                if current_digest and baseline_digest:
                    digest_only_change = current_digest.split("@", 1)[1] != baseline_digest.split("@", 1)[1]

        if comment_idx in fixed_comment_versions:
            prev_baseline, prev_target = fixed_comment_versions[comment_idx]
            if normalize_version(prev_baseline) != normalize_version(actual_baseline) or normalize_version(
                prev_target
            ) != normalize_version(actual_target):
                unresolved_names.append(name)
            continue
        fixed_comment_versions[comment_idx] = (actual_baseline, actual_target)

        new_spec = image_manifest_version_text(actual_baseline, actual_target, digest_only_change)
        new_comment_line = replace_version_spec(lines[comment_idx], new_spec)
        if new_comment_line != lines[comment_idx]:
            lines[comment_idx] = new_comment_line
            changed_entries.append((name, actual_baseline, actual_target))

    return "".join(lines), changed_entries, unresolved_names
