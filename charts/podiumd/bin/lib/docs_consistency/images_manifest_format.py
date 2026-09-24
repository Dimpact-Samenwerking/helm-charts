"""Checks that docs/images/images-<version>.yaml itself is internally
consistent: entries match Chart.yaml/values.yaml, the "# Changes:"
header/items are well-formed and cover every entry, and everything is
correctly ordered — used by lib.docs_consistency.check_docs_consistency.
match_changes_item_to_entry is also used directly by fix-doc-consistency
to resolve a plain (non-component) Changes item to its own manifest
entry."""

import re

from dataclasses import dataclass
from pathlib import Path

import yaml

from lib.chart.chart_yaml import ChartDependency
from lib.chart.pull_and_subchart_resolution import global_image_paths
from lib.chart.repo_and_path_resolution import canonical_sidecar_row_names
from lib.chart.repo_and_path_resolution import paths_by_repository
from lib.chart.repo_and_path_resolution import repo_group_representative
from lib.chart.values_tree_primitives import values_key_of
from lib.component_docs.images_manifest_changes_header import CHANGES_HEADER_RE
from lib.component_docs.images_manifest_changes_header import CHANGES_ITEM_RE
from lib.component_docs.images_manifest_changes_header import find_images_manifest_changes_header
from lib.component_docs.images_manifest_changes_header import find_images_manifest_changes_items
from lib.component_docs.images_manifest_changes_header import images_manifest_changes_count_word
from lib.component_docs.images_manifest_changes_header import images_manifest_changes_item_spans
from lib.image.repository_check import find_images_without_repository
from lib.images_manifest import ManifestEntry
from lib.images_manifest import images_manifest_problem
from lib.images_manifest import is_images_manifest
from lib.upgradedoc.app_version_and_image_paths import actual_app_version
from lib.upgradedoc.app_version_and_image_paths import find_all_image_and_version_paths
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_image_path
from lib.upgradedoc.consistency_checks import find_wrong_or_duplicate_dependency_claims
from lib.upgradedoc.grouped_comments_and_changes_block import find_grouped_preceding_comment
from lib.upgradedoc.grouped_comments_and_changes_block import parse_changes_block
from lib.upgradedoc.grouped_comments_and_changes_block import path_display_name
from lib.upgradedoc.images_manifest_list_diff import ManifestDiffContext
from lib.upgradedoc.images_manifest_list_diff import ManifestDiffInputs
from lib.upgradedoc.images_manifest_list_diff import find_images_manifest_list_diff
from lib.upgradedoc.images_manifest_ordering import EntryResolution
from lib.upgradedoc.images_manifest_ordering import ManifestSortContext
from lib.upgradedoc.images_manifest_ordering import ParsedManifest
from lib.upgradedoc.images_manifest_ordering import find_images_manifest_faulty_headers
from lib.upgradedoc.images_manifest_ordering import find_images_manifest_out_of_order_names
from lib.upgradedoc.images_manifest_ordering import images_manifest_display_name_positions
from lib.upgradedoc.images_manifest_ordering import images_manifest_entries_share_group
from lib.upgradedoc.images_manifest_ordering import images_manifest_entry_positions
from lib.upgradedoc.images_manifest_ordering import match_changes_item_display_name
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import VersionRow
from lib.upgradedoc.string_and_parsing_basics import best_name_match
from lib.upgradedoc.string_and_parsing_basics import extract_source_version
from lib.upgradedoc.string_and_parsing_basics import extract_target_version
from lib.upgradedoc.string_and_parsing_basics import match_dependency_excluding_sidecar_names
from lib.upgradedoc.string_and_parsing_basics import match_located_line
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.yaml_types import YamlMapping
from lib.yaml_types import YamlShapeError
from lib.yaml_types import parse_yaml


@dataclass
class ManifestCheckContext:
    """upgrade_docs_baseline/podiumd_version/deps/values/baseline_values/
    chart_dir — check_images_manifest_format's own six raw inputs
    (everything except the images-manifest path itself), bundled since
    virtually every one of its many independent sub-checks below needs
    some subset of the same six together. chart_dir=None skips every
    chart_dir-gated sub-check entirely (see each one's own docstring)."""

    upgrade_docs_baseline: str | None
    podiumd_version: str
    deps: list[ChartDependency]
    values: YamlMapping
    baseline_values: YamlMapping | None
    chart_dir: Path | None = None


@dataclass
class ResolvedManifest:
    """entries/resolution — an images-manifest's own parsed YAML entries
    paired with how to resolve one back to its own values-tree path/
    display name (EntryResolution). Bundled since the Changes-item and
    entry-comment checks below all need both together, and passing them
    separately would put both back over the max-argument threshold this
    split exists to clear."""

    entries: list[ManifestEntry]
    resolution: EntryResolution


@dataclass
class ListDiffInputs:
    """manifest/repo_groups/baseline_paths — find_images_manifest_list_
    diff's own remaining caller-varying inputs (ManifestCheckContext
    already supplies chart_dir/deps/upgrade_docs_baseline/values/
    baseline_values), bundled purely to keep _list_diff_issues under the
    max-argument threshold."""

    manifest: ResolvedManifest
    repo_groups: dict
    baseline_paths: dict


def match_changes_item_to_entry(item_name: str, entries: list[ManifestEntry]):
    """Best-effort match of a Changes-block item's free-form name (e.g.
    "Python (ensurePodiumdAdminUser init image)") to one of this SAME
    images-manifest's own entries — for an item that isn't a component at
    all (a plain image with no Chart.yaml dependency of its own to check
    against), so it isn't wrongly flagged as "no matching Chart.yaml
    dependency" just because it was never going to have one. Deliberately
    self-contained (reads only the file already being validated) rather
    than reaching into release-table.csv's own "used_by" column — that
    file is release_table_baseline-scoped, not upgrade_docs_baseline-
    scoped, and isn't guaranteed to exist or be current for whatever hop
    is being checked here.

    Reuses match_dependency's own word-containment matching, against each
    entry's final name segment (e.g. "python" from "library/python", an
    ACR-mirror-style slug the item's own prose never spells out in full)
    rather than a Chart.yaml dependency's name/alias. None if no entry's
    basename shows up this way.

    A canonical "<key> - <basename>" sidecar name (see
    lib.chart.canonical_sidecar_row_names — the same " - " delimiter
    match_dependency_excluding_sidecar_names already trusts as never
    appearing in a real dependency's own name/alias) is matched on its
    OWN basename specifically, not the whole string: matching the whole
    string risks the LEADING <key> word fuzzy-matching an UNRELATED
    entry that happens to share that word — real case: "keycloak-
    operator - postgres" (the postgres client image bundled with the
    keycloak-operator dependency) wrongly matched the "keycloak" entry
    (keycloak's own, unrelated primary image) instead of "postgres",
    since match_dependency has no reason to prefer the trailing word."""
    search_text = item_name.split(" - ", 1)[1] if " - " in item_name else item_name
    return best_name_match(
        search_text, ((entry, [entry["name"].rsplit("/", 1)[-1]]) for entry in entries if entry.get("name"))
    )


def _images_manifest_changes_items(lines: list[str]):
    """[(rest, start, end), ...] for every "#   N. ..." item in the images-
    manifest's own "# Changes:" header list — `rest` is the item's own
    text (first line only, matching CHANGES_ITEM_RE's own "rest" group;
    a wrapped continuation line is skipped, never needed for either
    caller below), `start`/`end` its own line-index span. [] if the
    header doesn't exist, or has no items at all. Deliberately returns
    even a SINGLE item — unlike fix-doc-consistency's own sort_images_
    manifest_changes_items, which floors at 2 (nothing to reorder with
    just one) — find_images_manifest_entries_missing_changes_mention
    still needs to know about a lone existing item to correctly credit
    it as covering its own entry; find_images_manifest_changes_items_
    out_of_order applies its own >= 2 floor itself, separately, for
    exactly that reordering reason. Factored out so both callers can
    never disagree about which lines make up "the list"."""
    header_idx, _has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return []
    spans, _block_end = images_manifest_changes_item_spans(lines, header_idx)
    return [(match_located_line(CHANGES_ITEM_RE, lines[start]).group("rest"), start, end) for start, end in spans]


def find_images_manifest_changes_items_out_of_order(
    text: str, entries: list[ManifestEntry], entry_positions: dict, display_name_positions: dict
):
    """[(item_a_text, item_b_text), ...] for every ADJACENT pair of "#
    Changes:" items whose relative order contradicts entry_positions/
    display_name_positions' own order (lib.upgradedoc.images_manifest_
    entry_positions/images_manifest_display_name_positions — the SAME
    final order sort_images_manifest_entries itself applies to the
    manifest's own entry list) — same "adjacent pairs are sufficient to
    catch any non-monotonic sequence" reasoning find_images_manifest_
    out_of_order_names already uses for the entry list itself. That
    check only ever covers the ENTRIES, never this header list — a real
    gap: a manifest can have its entries perfectly grouped/ordered while
    the "# Changes:" list above them is scrambled relative to it (real
    case: "kiss"/"kiss-eck" items landing far from their own sidecars'
    items purely because match_changes_item_to_entry's fuzzy basename
    search can't resolve a display name sharing no word with its own
    entry's repository basename), and nothing previously reported that.

    Resolves each item via the EXACT same two-tier match fix-doc-
    consistency's own sort_images_manifest_changes_items applies —
    match_changes_item_display_name's exact prefix match first,
    match_changes_item_to_entry's fuzzy basename match as fallback — so
    checker and fixer can never disagree about what "in order" means.
    An item resolving via NEITHER sorts last, same as the fixer — never
    flagged as out of place relative to a resolvable neighbor just
    because it's free-form prose with nothing to match against."""
    lines = text.splitlines(keepends=True)
    items = _images_manifest_changes_items(lines)
    if len(items) < 2:
        return []

    keys = []
    for rest, _start, _end in items:
        display_name = match_changes_item_display_name(rest, display_name_positions)
        if display_name is not None:
            keys.append(display_name_positions[display_name])
        else:
            entry = match_changes_item_to_entry(rest, entries)
            keys.append(entry_positions.get(entry["name"], len(entry_positions)) if entry else len(entry_positions))

    return [(items[i][0], items[i + 1][0]) for i in range(len(items) - 1) if keys[i + 1] < keys[i]]


def _covered_changes_display_names(
    lines: list[str], entries: list[ManifestEntry], display_name_positions: dict, resolution: EntryResolution
):
    """The set of every images-manifest entry/group display name a "#
    Changes:" item in `lines` already resolves back to — the SAME two-
    tier match find_images_manifest_changes_items_out_of_order/fix-doc-
    consistency's own sort_images_manifest_changes_items apply:
    match_changes_item_display_name's exact prefix match first,
    match_changes_item_to_entry's fuzzy basename match as fallback."""

    def entry_display_name(entry: ManifestEntry):
        path = resolve_entry_image_path(entry["name"], resolution.current_paths.keys(), resolution.repo_map)
        return path_display_name(path, resolution.deps, resolution.canonical_names) if path else None

    covered_names = set()
    for rest, _start, _end in _images_manifest_changes_items(lines):
        display_name = match_changes_item_display_name(rest, display_name_positions)
        if display_name is not None:
            covered_names.add(display_name)
            continue
        entry = match_changes_item_to_entry(rest, entries)
        matched_name = entry_display_name(entry) if entry is not None else None
        if matched_name is not None:
            covered_names.add(matched_name)
    return covered_names


def _uncovered_entry_display_names(
    entries: list[ManifestEntry], entry_positions: dict, resolution: EntryResolution, covered_names: set
):
    """Display names of every entry GROUP (present in entry_positions)
    not already in `covered_names` — one display name per group, first
    entry only, skipping an entry whose display name is path_display_
    name's raw-dotted-path fallback (see find_images_manifest_entries_
    missing_changes_mention's own docstring for why)."""
    missing, seen = [], set()
    for entry in entries:
        if entry["name"] not in entry_positions:
            continue
        path = resolve_entry_image_path(entry["name"], resolution.current_paths.keys(), resolution.repo_map)
        if not path:
            continue
        display_name = path_display_name(path, resolution.deps, resolution.canonical_names)
        if display_name is None or display_name in seen or display_name == ".".join(path):
            continue
        seen.add(display_name)
        if display_name not in covered_names:
            missing.append(display_name)
    return missing


def find_images_manifest_entries_missing_changes_mention(
    text: str, entries: list[ManifestEntry], context: ManifestSortContext
):
    """Display names (lib.upgradedoc.path_display_name) of every images-
    manifest entry GROUP (lib.upgradedoc.images_manifest_entry_positions'
    own group-level position) that has no "# Changes:" item resolving
    back to it at all — the gap fix-doc-consistency's own add_missing_
    images_manifest_entries' second ("backfill") pass exists to patch,
    with no check counterpart until now: find_images_manifest_list_diff's
    own missing_paths only ever catches a changed image with no ENTRY,
    never an entry that exists (and is otherwise perfectly correct) but
    was simply never added to the header list — e.g. a component added
    by hand straight into the body, or a manifest edited before header-
    list items existed for it at all. `context` is a ManifestSortContext.

    "Resolving back to it" means the SAME two-tier match find_images_
    manifest_changes_items_out_of_order/fix-doc-consistency's own sort_
    images_manifest_changes_items apply (see _covered_changes_display_
    names) — deliberately NOT a literal string search for the display
    name inside the header, which would wrongly demand every item spell
    out that one exact phrase.

    Compared by DISPLAY NAME, not by entry_positions' own per-entry
    position — a multi-image "lockstep" component (zgw-office-addin's
    frontend + backend, eck-stack's elasticsearch + kibana, ita's web +
    poller) has SEVERAL entries, each its own distinct position, but ALL
    sharing one display name; one Changes item naming that shared
    display name (the dedupe_images_manifest_changes_items-fixed shape —
    see fix-doc-consistency) legitimately covers every one of them, not
    just whichever single entry happens to sit at display_name_
    positions' own lowest-position pick.

    A group whose own display name is path_display_name's raw-dotted-
    path fallback (no real dependency/canonical-sidecar name resolves it
    at all — rare) is skipped entirely, same reasoning as the fixer's
    own backfill pass: never a phrase a human would write in prose, so
    it's not a gap worth reporting. [] under the same guards images_
    manifest_entry_positions applies (invalid YAML, or fewer than 2
    entries) — nothing to cross-check with just 0 or 1 entries."""
    entry_positions = images_manifest_entry_positions(text, context)
    if not entry_positions:
        return []
    display_name_positions = images_manifest_display_name_positions(text, context)

    current_paths = dict(find_all_image_and_version_paths(context.values, context.deps))
    current_paths.update(global_image_paths(context.values))
    resolution = EntryResolution(context.deps, current_paths, context.repo_map, context.canonical_names)

    lines = text.splitlines(keepends=True)
    covered_names = _covered_changes_display_names(lines, entries, display_name_positions, resolution)
    return sorted(_uncovered_entry_display_names(entries, entry_positions, resolution, covered_names))


def check_images_manifest_changes_numbering(images_path_name: str, text: str):
    """The images-manifest's own "# Changes:" numbered item list must be
    a gapless 1..N sequence matching its own current top-to-bottom
    document order, and the header's own leading count word (if it has
    one — see find_images_manifest_changes_header) must equal the
    actual item count. sort_images_manifest_changes_items/dedupe_
    images_manifest_changes_items each already renumber correctly as a
    side effect of their OWN operation (reordering, removing a
    duplicate) — but neither fires, and so neither catches, a list
    that's already duplicate-free and already in the right RELATIVE
    order yet still has the wrong ABSOLUTE numbers (real case: a human
    hand-removes a stale item's own block without renumbering
    everything after it, leaving a gap like "...6. ... 8. ..." with no
    "7." at all). See lib.component_docs.renumber_images_manifest_
    changes_items, fix-doc-consistency's own fix for exactly this."""
    lines = text.splitlines(keepends=True)
    header_idx, header_has_count, item_indices = find_images_manifest_changes_items(lines)
    if header_idx is None or not item_indices:
        return []

    issues = []
    for slot, idx in enumerate(item_indices):
        expected = slot + 1
        actual = int(match_located_line(CHANGES_ITEM_RE, lines[idx]).group("num"))
        if actual != expected:
            issues.append(
                f'{images_path_name}: "# Changes:" item numbered {actual} should be {expected} '
                f"(item #{expected} in the list, top to bottom)"
            )

    if header_has_count:
        count_word, noun = images_manifest_changes_count_word(len(item_indices))
        header_m = CHANGES_HEADER_RE.match(lines[header_idx])
        if header_m and header_m.group("count_word").lower() != count_word.lower():
            issues.append(
                f'{images_path_name}: header says "{header_m.group("count_word")} {noun}" but there '
                f"are actually {len(item_indices)}"
            )
    return issues


def _baseline_and_vs_line_issues(name: str, text: str, context: ManifestCheckContext):
    """The images-manifest's own two header-comment lines — "Baseline:
    podiumd <version>" and "podiumd <target> vs <upgrade_docs_baseline>"
    — checked against context.podiumd_version/context.upgrade_docs_
    baseline."""
    issues = []
    baseline_m = re.search(r"Baseline:\s*podiumd\s+([\w.\-]+)", text)
    if not baseline_m:
        issues.append(f'{name}: no "Baseline: podiumd <version>" line found')
    else:
        # .rstrip(".") — the stub template writes "Baseline: podiumd 4.9.0."
        # (trailing sentence period), and "." is inside the capture class;
        # same handling as the "... vs ..." line just below.
        baseline_str = baseline_m.group(1).rstrip(".")
        if normalize_version(baseline_str) != normalize_version(context.upgrade_docs_baseline):
            issues.append(
                f'{name}: upgrade_docs_baseline line says "{baseline_str}", expected "{context.upgrade_docs_baseline}"'
            )

    vs_m = re.search(r"podiumd\s+([\w.\-]+)\s+vs\s+([\w.\-]+)", text)
    if not vs_m:
        issues.append(f'{name}: no "podiumd <target> vs <upgrade_docs_baseline>" line found')
    else:
        vs_target, vs_baseline = vs_m.group(1).rstrip("."), vs_m.group(2).rstrip(".")
        if normalize_version(vs_target) != normalize_version(context.podiumd_version):
            issues.append(f'{name}: "... vs ..." line says target "{vs_target}", expected "{context.podiumd_version}"')
        if normalize_version(vs_baseline) != normalize_version(context.upgrade_docs_baseline):
            issues.append(
                f'{name}: "... vs ..." line says upgrade_docs_baseline "{vs_baseline}", '
                f'expected "{context.upgrade_docs_baseline}"'
            )
    return issues


def _manifest_resolution_context(context: ManifestCheckContext):
    """(repo_groups, resolution) — repo_groups (see paths_by_repository,
    needed only by the list-diff check) and an EntryResolution bundling
    deps/current_paths/repo_map/canonical_names, both derived from
    `context` the same way every entry-resolving check below needs them.
    Computed once, early — a canonical "<key> - <basename>" sidecar item
    name (see canonical_sidecar_row_names) needs repo_map/canonical_names
    to resolve back to its own real entry directly via its known values-
    tree path, needed as early as the Changes-item loop — match_changes_
    item_to_entry's own text-only basename-word matching has no way to
    resolve that on its own. {}/EntryResolution(..., {}, {}) for the
    chart_dir-gated pieces when context.chart_dir is None."""
    current_paths = dict(find_all_image_and_version_paths(context.values, context.deps))
    current_paths.update(global_image_paths(context.values))
    repo_groups = (
        paths_by_repository(context.chart_dir, context.deps, context.values, current_paths.keys())
        if context.chart_dir is not None
        else {}
    )
    repo_map = {repo: repo_group_representative(paths, context.deps) for repo, paths in repo_groups.items()}
    canonical_names = (
        canonical_sidecar_row_names(context.chart_dir, context.deps, context.values, current_paths.keys())
        if context.chart_dir is not None
        else {}
    )
    return repo_groups, EntryResolution(context.deps, current_paths, repo_map, canonical_names)


def _plain_image_entry_for_item(item_name: str, resolved: ResolvedManifest):
    """The images-manifest entry a non-component Changes item resolves
    to — a KNOWN canonical sidecar name (see resolved.resolution.
    canonical_names) tried FIRST, resolved directly via its own real
    values-tree path — never guessed at from the item's own free-form
    text — then match_changes_item_to_entry's fuzzy basename match as
    fallback. None if neither resolves anything."""
    path = resolved.resolution.canonical_names.get(item_name)
    if path is not None:
        entry = next(
            (
                e
                for e in resolved.entries
                if resolve_entry_image_path(
                    e["name"], resolved.resolution.current_paths.keys(), resolved.resolution.repo_map
                )
                == path
            ),
            None,
        )
        if entry is not None:
            return entry
    return match_changes_item_to_entry(item_name, resolved.entries)


def _changes_item_version_mismatches(
    name: str, item: VersionRow, actual_app: str | None, actual_chart: str | None, baseline_app: str | None
):
    """One issue per version cell (target app, target chart, source app)
    a single Changes item claims that disagrees with the actual value —
    a cell is only ever checked when the item actually claims one AND
    the corresponding actual value is known."""
    issues = []
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


def _changes_item_issues(
    name: str, item: VersionRow, resolved: ResolvedManifest, context: ManifestCheckContext, invalid_names: set
):
    """The issue(s) for a single "# Changes:" block item — wrong/stale
    (see find_wrong_or_duplicate_dependency_claims), unresolvable, or a
    version-cell mismatch against its resolved actual state."""
    if item["name"] in invalid_names:
        return [f'{name}: Changes item "{item["name"]}" is wrong or stale — not found in Chart.yaml or values.yaml']

    # match_dependency_excluding_sidecar_names, not match_dependency
    # directly — a canonical sidecar/shared-image Changes item like
    # "keycloak-operator - python 3.14-slim -> 3.14.7-slim." must
    # never fuzzy-match the real "keycloak-operator" dependency on
    # its leading word and get compared against ITS OWN unrelated
    # actual app version; it falls through to the "plain image"
    # entry-matching branch below instead, same as any other
    # non-component Changes item.
    dep = match_dependency_excluding_sidecar_names(item["name"], context.deps)
    if dep:
        values_key = values_key_of(dep)
        actual_app = actual_app_version(context.values, values_key, dep["name"], chart_dir=context.chart_dir, dep=dep)
        actual_chart = dep["version"]
        baseline_app = (
            actual_app_version(context.baseline_values, values_key, dep["name"]) if context.baseline_values else None
        )
    else:
        # Not every Changes item is a component — a plain image (e.g. an
        # init-container image with no subchart/dependency of its own)
        # has nothing in Chart.yaml to match against at all; fall back
        # to this same manifest's own entries instead of treating that
        # as an error (see match_changes_item_to_entry).
        entry = _plain_image_entry_for_item(item["name"], resolved)
        if entry is None:
            return [
                f'{name}: Changes item "{item["name"]}" — no matching Chart.yaml dependency or images-manifest entry'
            ]
        actual_app = entry.get("version")
        actual_chart = None  # a plain image has no chart version to check
        baseline_app = None  # no baseline lookup available without a component scope

    return _changes_item_version_mismatches(name, item, actual_app, actual_chart, baseline_app)


def _changes_block_item_issues(name: str, text: str, resolved: ResolvedManifest, context: ManifestCheckContext):
    """One issue per "# Changes:" block item (see parse_changes_block)
    whose target/source app or chart version disagrees with the actual
    Chart.yaml/values.yaml/images-manifest state it claims to describe —
    or that doesn't resolve to anything real at all. Same two
    deterministic gaps as lib.docs_consistency's own upgrade-doc row loop
    (see find_wrong_or_duplicate_dependency_claims) — a free-form Changes
    item fuzzy-matching a dependency another item already exactly
    claims. Real, live case this catches: item "Kiss's ECK-managed
    Elasticsearch/Kibana/Enterprise Search 8.19.3 -> 8.19.19" fuzzy-
    matches the real "kiss" dependency on the word "kiss" (there's also
    an exact "KISS 2.2.4 -> 3.0.0" item) and was being compared against
    kiss's own unrelated actual app version — same for "clamav_exporter
    (metrics sidecar) ..." vs the exact "ClamAV ..." item."""
    items = list(parse_changes_block(text))
    duplicate_names, wrong_fuzzy_names = find_wrong_or_duplicate_dependency_claims(
        [item["name"] for item in items], context.deps
    )
    invalid_names = duplicate_names | wrong_fuzzy_names

    issues = []
    for item in items:
        issues.extend(_changes_item_issues(name, item, resolved, context, invalid_names))
    return issues


def _entry_comment_version_mismatches(
    name: str, entry: ManifestEntry, comment: str, resolution: EntryResolution, baseline_paths: dict
):
    """The issue(s) for a single entry's own preceding comment — its
    target version cell vs. the entry's own actual version, and its
    source version cell vs. upgrade_docs_baseline's actual value."""
    issues = []
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
    name: str, lines: list[str], resolved: ResolvedManifest, entry_line_indices: list, baseline_paths: dict
):
    """One issue per images-manifest entry whose own preceding comment
    is missing, or whose target/source app version disagrees with the
    entry's own actual version / upgrade_docs_baseline's actual value."""

    def same_group(entry_a: ManifestEntry, entry_b: ManifestEntry):
        return images_manifest_entries_share_group(
            entry_a, entry_b, resolved.resolution.current_paths, resolved.resolution.repo_map
        )

    issues = []
    for index, (entry, _line_idx) in enumerate(zip(resolved.entries, entry_line_indices, strict=True)):
        comment = find_grouped_preceding_comment(lines, resolved.entries, entry_line_indices, index, same_group)
        if not comment:
            issues.append(f'{name}: entry "{entry["name"]}" has no preceding comment')
            continue
        issues.extend(_entry_comment_version_mismatches(name, entry, comment, resolved.resolution, baseline_paths))
    return issues


def _sidecar_header_issues(name: str, parsed: ParsedManifest, resolution: EntryResolution):
    """One issue per SIDECAR entry (see is_primary_image_path) whose own
    header doesn't correctly, unambiguously identify it — a sidecar
    (see find_images_manifest_faulty_headers) needs its OWN indented "#
    sidecar: <parent> - <basename> ..." header, never a plain header
    borrowed from a preceding entry via same_group's "same component,
    same declared version" heuristic — that heuristic is only ever a
    proxy for "these two entries genuinely bumped in lockstep", and a
    sidecar whose real version history diverges from its parent's
    (kiss-elastic-sync: 0.3.3 -> 3.0.0, sharing "# KISS — 2.2.4 ->
    3.0.0" purely because both happen to land on 3.0.0 this release)
    silently inherits a header that doesn't describe it at all."""
    issues = []
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


def _out_of_order_entry_issues(
    name: str, parsed: ParsedManifest, resolution: EntryResolution, key_order: list[str], values: YamlMapping
):
    """One issue per adjacent pair of entries (or shared-header groups)
    that don't follow values.yaml's own top-level component order — the
    same rule find_out_of_order_names already enforces for -upgrade.md's
    own rows/Changes headings."""
    issues = []
    for name_a, name_b in find_images_manifest_out_of_order_names(parsed, resolution, key_order, values):
        issues.append(
            f'{name}: entry "{name_b}" is listed right after "{name_a}", but '
            f"values.yaml lists {name_b} before {name_a} — entries should follow values.yaml's "
            f"own component order"
        )
    return issues


def _changes_items_out_of_order_issues(
    name: str, text: str, entries: list[ManifestEntry], entry_positions: dict, display_name_positions: dict
):
    """One issue per adjacent pair of "# Changes:" items whose order
    contradicts the entry list's own final order — the two can silently
    disagree (entries correctly grouped/ordered, header list scrambled
    relative to them) with nothing else here to catch it."""
    issues = []
    for item_a, item_b in find_images_manifest_changes_items_out_of_order(
        text, entries, entry_positions, display_name_positions
    ):
        issues.append(
            f'{name}: "# Changes:" list has "{item_b}" right after "{item_a}", but '
            f"the entry list has them in the opposite order — Changes items should follow the "
            f"same order as the entries below them"
        )
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
    """Every chart_dir-gated structural check that's independent of
    upgrade_docs_baseline — sidecar headers, values.yaml component
    order, and the "# Changes:" list's own order/coverage relative to
    the entry list. Only called by check_images_manifest_format when
    context.chart_dir is not None."""
    issues = _sidecar_header_issues(name, parsed, resolution)

    key_order = values_key_order(context.values)
    issues.extend(_out_of_order_entry_issues(name, parsed, resolution, key_order, context.values))

    sort_context = ManifestSortContext(context.deps, context.values, resolution.repo_map, resolution.canonical_names)
    entry_positions = images_manifest_entry_positions(text, sort_context)
    display_name_positions = images_manifest_display_name_positions(text, sort_context)
    issues.extend(
        _changes_items_out_of_order_issues(name, text, parsed.entries, entry_positions, display_name_positions)
    )
    issues.extend(_missing_changes_mention_issues(name, text, parsed.entries, sort_context))
    return issues


def _list_diff_issues(name: str, inputs: ListDiffInputs, context: ManifestCheckContext):
    """The list-diff check (find_images_manifest_list_diff) — every
    changed image must have an entry, and every entry must correspond to
    a real change. Only called by check_images_manifest_format once
    there's something real to diff against (baseline_paths is non-empty
    and context.chart_dir is not None) — without a resolvable upgrade_
    docs_baseline, "changed" can't be computed at all."""
    if context.chart_dir is None:
        return []
    unresolvable_paths = set(find_images_without_repository(context.chart_dir))
    missing_paths, stale_entry_names, unmatched_entry_names = find_images_manifest_list_diff(
        ManifestDiffInputs(
            inputs.manifest.entries,
            inputs.manifest.resolution.current_paths,
            inputs.baseline_paths,
            inputs.manifest.resolution.repo_map,
            inputs.repo_groups,
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
    issues.extend(
        f'{name}: entry "{entry_name}" is wrong or stale — not found in Chart.yaml or values.yaml'
        for entry_name in unmatched_entry_names
    )
    return issues


def check_images_manifest_format(images_path: Path, context: ManifestCheckContext):
    """Existence + YAML-validity + header-comment-accuracy precheck for the
    images manifest, run BEFORE the entry-by-entry content checks — mirrors
    check_baseline_doc_set for the three markdown docs. Also checks the
    manifest's own entry LIST against the full, actual set of images that
    changed vs context.upgrade_docs_baseline (see find_images_manifest_
    list_diff) — every changed image must have an entry, and every entry
    must correspond to a real change, once context.chart_dir is given.
    `context` is a ManifestCheckContext."""
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

    issues = _baseline_and_vs_line_issues(images_path.name, text, context)
    issues.extend(check_images_manifest_changes_numbering(images_path.name, text))

    repo_groups, resolution = _manifest_resolution_context(context)
    resolved = ResolvedManifest(entries, resolution)
    issues.extend(_changes_block_item_issues(images_path.name, text, resolved, context))

    lines = text.splitlines()
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    baseline_paths = (
        dict(find_all_image_and_version_paths(context.baseline_values, context.deps)) if context.baseline_values else {}
    )
    baseline_paths.update(global_image_paths(context.baseline_values) if context.baseline_values else [])
    issues.extend(_entry_comment_issues(images_path.name, lines, resolved, entry_line_indices, baseline_paths))

    # Also structural, independent of upgrade_docs_baseline (see
    # _structural_issues): sidecar headers, values.yaml component order,
    # and the "# Changes:" list's own order/coverage.
    if context.chart_dir is not None:
        parsed = ParsedManifest(entries, entry_line_indices, lines)
        issues.extend(_structural_issues(images_path.name, text, parsed, resolution, context))

    # Only checked once there's something real to diff against — without
    # a resolvable upgrade_docs_baseline, "changed" can't be computed at
    # all (baseline_values is {} in that case, so baseline_paths is too).
    if baseline_paths and context.chart_dir is not None:
        list_diff_inputs = ListDiffInputs(resolved, repo_groups, baseline_paths)
        issues.extend(_list_diff_issues(images_path.name, list_diff_inputs, context))

    return issues
