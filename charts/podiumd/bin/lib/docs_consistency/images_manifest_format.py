"""Checks that docs/images/images-<version>.yaml itself is internally
consistent: entries match Chart.yaml/values.yaml, the "# Changes:"
header/items are well-formed and cover every entry, and everything is
correctly ordered — used by lib.docs_consistency.check_docs_consistency.
match_changes_item_to_entry is also used directly by fix-doc-consistency
to resolve a plain (non-component) Changes item to its own manifest
entry."""

import re

import yaml

from lib.chart.pull_and_subchart_resolution import global_image_paths
from lib.chart.repo_and_path_resolution import (
    canonical_sidecar_row_names,
    paths_by_repository,
    repo_group_representative,
)
from lib.component_docs.images_manifest_changes_header import (
    CHANGES_HEADER_RE,
    CHANGES_ITEM_RE,
    find_images_manifest_changes_header,
    find_images_manifest_changes_items,
    images_manifest_changes_count_word,
)
from lib.image_repository_check import find_images_without_repository
from lib.upgradedoc.app_version_and_image_paths import (
    actual_app_version,
    find_all_image_and_version_paths,
    resolve_entry_image_path,
)
from lib.upgradedoc.consistency_checks import find_wrong_or_duplicate_dependency_claims
from lib.upgradedoc.grouped_comments_and_changes_block import (
    find_grouped_preceding_comment,
    parse_changes_block,
    path_display_name,
)
from lib.upgradedoc.images_manifest_list_diff import find_images_manifest_list_diff
from lib.upgradedoc.images_manifest_ordering import (
    find_images_manifest_faulty_headers,
    find_images_manifest_out_of_order_names,
    images_manifest_display_name_positions,
    images_manifest_entries_share_group,
    images_manifest_entry_positions,
    match_changes_item_display_name,
)
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import (
    extract_source_version,
    extract_target_version,
    match_dependency,
    match_dependency_excluding_sidecar_names,
    normalize_version,
)


def match_changes_item_to_entry(item_name, entries):
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
    candidates = [{"name": entry["name"].rsplit("/", 1)[-1], "_entry": entry} for entry in entries if entry.get("name")]
    search_text = item_name.split(" - ", 1)[1] if " - " in item_name else item_name
    match = match_dependency(search_text, candidates)
    return match["_entry"] if match else None


def _images_manifest_changes_items(lines):
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
    item_starts = []
    block_end = header_idx + 1
    for i in range(header_idx + 1, len(lines)):
        if lines[i].rstrip("\n") == "#" or not lines[i].startswith("#"):
            break
        block_end = i + 1
        if CHANGES_ITEM_RE.match(lines[i]):
            item_starts.append(i)
    if not item_starts:
        return []
    item_ends = item_starts[1:] + [block_end]
    return [
        (CHANGES_ITEM_RE.match(lines[start]).group("rest"), start, end)
        for start, end in zip(item_starts, item_ends, strict=True)
    ]


def find_images_manifest_changes_items_out_of_order(text, entries, entry_positions, display_name_positions):
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


def find_images_manifest_entries_missing_changes_mention(text, entries, deps, values, repo_map, canonical_names):
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
    list items existed for it at all.

    "Resolving back to it" means the SAME two-tier match find_images_
    manifest_changes_items_out_of_order/fix-doc-consistency's own sort_
    images_manifest_changes_items apply — match_changes_item_display_
    name's exact prefix match against the entry's own canonical display
    name, OR match_changes_item_to_entry's fuzzy basename match against
    the entry's own raw "name:" — a free-form item using neither form
    (real case: a bare "redis-ha ..." item for what canonical_sidecar_
    row_names would call "redis-operator - redis") still counts as
    covering it, exactly as it already does for ordering/sorting; this
    is deliberately NOT a literal string search for the display name
    inside the header, which would wrongly demand every item spell out
    that one exact phrase.

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
    entry_positions = images_manifest_entry_positions(text, deps, values, repo_map, canonical_names)
    if not entry_positions:
        return []
    display_name_positions = images_manifest_display_name_positions(text, deps, values, repo_map, canonical_names)

    current_paths = dict(find_all_image_and_version_paths(values, deps))
    current_paths.update(global_image_paths(values))

    def entry_display_name(entry):
        path = resolve_entry_image_path(entry, current_paths.keys(), repo_map)
        return path_display_name(path, deps, canonical_names) if path else None

    lines = text.splitlines(keepends=True)
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

    missing, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("name") not in entry_positions:
            continue
        path = resolve_entry_image_path(entry, current_paths.keys(), repo_map)
        display_name = path_display_name(path, deps, canonical_names) if path else None
        if display_name is None or display_name in seen or display_name == ".".join(path):
            continue
        seen.add(display_name)
        if display_name not in covered_names:
            missing.append(display_name)
    return sorted(missing)


def check_images_manifest_changes_numbering(images_path_name, text):
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
        actual = int(CHANGES_ITEM_RE.match(lines[idx]).group("num"))
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


def check_images_manifest_format(
    images_path, upgrade_docs_baseline, podiumd_version, deps, values, baseline_values, chart_dir=None
):
    """Existence + YAML-validity + header-comment-accuracy precheck for the
    images manifest, run BEFORE the entry-by-entry content checks — mirrors
    check_baseline_doc_set for the three markdown docs. Also checks the
    manifest's own entry LIST against the full, actual set of images that
    changed vs upgrade_docs_baseline (see find_images_manifest_list_diff)
    — every changed image must have an entry, and every entry must
    correspond to a real change, once chart_dir is given."""
    if not images_path.is_file():
        return [f'expected "{images_path.name}" does not exist']

    text = images_path.read_text(encoding="utf-8")
    try:
        entries = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return [f"{images_path.name} is not valid YAML: {e}"]
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        return [f"{images_path.name} does not contain a YAML list of mappings"]
    for i, entry in enumerate(entries):
        missing = [k for k in ("name", "url", "version", "digest") if k not in entry]
        if missing:
            return [f"{images_path.name} entry #{i + 1} is missing key(s): {', '.join(missing)}"]

    issues = []

    baseline_m = re.search(r"Baseline:\s*podiumd\s+([\w.\-]+)", text)
    if not baseline_m:
        issues.append(f'{images_path.name}: no "Baseline: podiumd <version>" line found')
    else:
        # .rstrip(".") — the stub template writes "Baseline: podiumd 4.9.0."
        # (trailing sentence period), and "." is inside the capture class;
        # same handling as the "... vs ..." line just below.
        baseline_str = baseline_m.group(1).rstrip(".")
        if normalize_version(baseline_str) != normalize_version(upgrade_docs_baseline):
            issues.append(
                f'{images_path.name}: upgrade_docs_baseline line says "{baseline_str}", '
                f'expected "{upgrade_docs_baseline}"'
            )

    vs_m = re.search(r"podiumd\s+([\w.\-]+)\s+vs\s+([\w.\-]+)", text)
    if not vs_m:
        issues.append(f'{images_path.name}: no "podiumd <target> vs <upgrade_docs_baseline>" line found')
    else:
        vs_target, vs_baseline = vs_m.group(1).rstrip("."), vs_m.group(2).rstrip(".")
        if normalize_version(vs_target) != normalize_version(podiumd_version):
            issues.append(
                f'{images_path.name}: "... vs ..." line says target "{vs_target}", expected "{podiumd_version}"'
            )
        if normalize_version(vs_baseline) != normalize_version(upgrade_docs_baseline):
            issues.append(
                f'{images_path.name}: "... vs ..." line says upgrade_docs_baseline "{vs_baseline}", '
                f'expected "{upgrade_docs_baseline}"'
            )

    issues.extend(check_images_manifest_changes_numbering(images_path.name, text))

    # Computed early (moved up from below, where the per-entry checks
    # further down also need them) so the Changes-item loop right below
    # can ALSO resolve a canonical "<key> - <basename>" sidecar item name
    # (see canonical_sidecar_row_names) back to its own real entry
    # directly via its known values-tree path — needed for a canonical
    # name whose own "basename" isn't a real image-repository basename
    # at all (e.g. "keycloak-operator - operator", the values-tree path
    # SEGMENT fallback canonical_sidecar_row_names uses for a sidecar
    # whose repo basename would otherwise self-referentially collide
    # with its own dependency's key — see that function's own
    # docstring): match_changes_item_to_entry's own text-only basename-
    # word matching has no way to resolve that, since there's no real
    # entry whose own name/repository is "operator" to word-match against.
    current_paths = dict(find_all_image_and_version_paths(values, deps))
    current_paths.update(global_image_paths(values))
    repo_groups = paths_by_repository(chart_dir, deps, values, current_paths.keys()) if chart_dir is not None else {}
    repo_map = {repo: repo_group_representative(paths, deps) for repo, paths in repo_groups.items()}
    canonical_names = (
        canonical_sidecar_row_names(chart_dir, deps, values, current_paths.keys()) if chart_dir is not None else {}
    )

    items = list(parse_changes_block(text))
    # Same two deterministic gaps as lib.docs_consistency's own upgrade-doc
    # row loop (see find_wrong_or_duplicate_dependency_claims) — a
    # free-form Changes item fuzzy-matching a dependency another item
    # already exactly claims. Real, live case this catches: item "Kiss's
    # ECK-managed Elasticsearch/Kibana/Enterprise Search 8.19.3 ->
    # 8.19.19" fuzzy-matches the real "kiss" dependency on the word
    # "kiss" (there's also an exact "KISS 2.2.4 -> 3.0.0" item) and was
    # being compared against kiss's own unrelated actual app version —
    # same for "clamav_exporter (metrics sidecar) ..." vs the exact
    # "ClamAV ..." item.
    duplicate_names, wrong_fuzzy_names = find_wrong_or_duplicate_dependency_claims(
        [item["name"] for item in items], deps
    )

    for item in items:
        if item["name"] in duplicate_names or item["name"] in wrong_fuzzy_names:
            issues.append(
                f'{images_path.name}: Changes item "{item["name"]}" is wrong or stale — '
                f"not found in Chart.yaml or values.yaml"
            )
            continue

        # match_dependency_excluding_sidecar_names, not match_dependency
        # directly — a canonical sidecar/shared-image Changes item like
        # "keycloak-operator - python 3.14-slim -> 3.14.7-slim." must
        # never fuzzy-match the real "keycloak-operator" dependency on
        # its leading word and get compared against ITS OWN unrelated
        # actual app version; it falls through to the "plain image"
        # entry-matching branch below instead, same as any other
        # non-component Changes item.
        dep = match_dependency_excluding_sidecar_names(item["name"], deps)
        if dep:
            values_key = dep.get("alias", dep["name"])
            actual_app = actual_app_version(values, values_key, dep["name"], chart_dir=chart_dir, dep=dep)
            actual_chart = dep["version"]
            baseline_app = actual_app_version(baseline_values, values_key, dep["name"]) if baseline_values else None
        else:
            # Not every Changes item is a component — a plain image (e.g. an
            # init-container image with no subchart/dependency of its own)
            # has nothing in Chart.yaml to match against at all; fall back
            # to this same manifest's own entries instead of treating that
            # as an error (see match_changes_item_to_entry).
            #
            # A KNOWN canonical sidecar name (see canonical_names above)
            # is tried FIRST, resolved directly via its own real values-
            # tree path — never guessed at from the item's own free-form
            # text — since match_changes_item_to_entry's basename-word
            # matching can't resolve one whose "basename" is a values-
            # tree path segment, not a real image-repository basename
            # (see the comment where canonical_names is computed above).
            entry = None
            path = canonical_names.get(item["name"])
            if path is not None:
                entry = next(
                    (e for e in entries if resolve_entry_image_path(e, current_paths.keys(), repo_map) == path), None
                )
            if entry is None:
                entry = match_changes_item_to_entry(item["name"], entries)
            if entry is None:
                issues.append(
                    f'{images_path.name}: Changes item "{item["name"]}" — no matching '
                    f"Chart.yaml dependency or images-manifest entry"
                )
                continue
            actual_app = entry.get("version")
            actual_chart = None  # a plain image has no chart version to check
            baseline_app = None  # no baseline lookup available without a component scope

        if item["app"] and actual_app and normalize_version(item["app"]) != normalize_version(actual_app):
            issues.append(
                f'{images_path.name}: Changes item "{item["name"]}" target app '
                f'"{item["app"]}" != values.yaml "{actual_app}"'
            )
        if item["chart"] and actual_chart and normalize_version(item["chart"]) != normalize_version(actual_chart):
            issues.append(
                f'{images_path.name}: Changes item "{item["name"]}" target chart '
                f'"{item["chart"]}" != Chart.yaml "{actual_chart}"'
            )
        if (
            item["app_source"]
            and baseline_app
            and normalize_version(item["app_source"]) != normalize_version(baseline_app)
        ):
            issues.append(
                f'{images_path.name}: Changes item "{item["name"]}" source app '
                f'"{item["app_source"]}" != upgrade_docs_baseline "{baseline_app}"'
            )

    lines = text.splitlines()
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    baseline_paths = dict(find_all_image_and_version_paths(baseline_values, deps)) if baseline_values else {}
    baseline_paths.update(global_image_paths(baseline_values) if baseline_values else [])

    # current_paths/repo_map/canonical_names: computed early, above the
    # Changes-item loop — see the comment there for why. repo_map (see
    # lib.chart.repository_path_map) is reused everywhere an entry needs
    # matching to its values-tree path below — the SAME deterministic,
    # exact "name: is a repository" lookup a doc row's own sidecar name
    # resolves through (see canonical_sidecar_row_names, also repo_map-
    # based) — never resolve_entry_path's fuzzy word-matching alone,
    # which two entries sharing one comment (see same_group) need to be
    # able to trust: word-matching a group's own free-form header prose
    # to a component is exactly the kind of guess that stays wrong until
    # the header itself is fixed to name that component properly.

    def same_group(entry_a, entry_b):
        return images_manifest_entries_share_group(entry_a, entry_b, current_paths, repo_map)

    for index, (entry, _line_idx) in enumerate(zip(entries, entry_line_indices, strict=True)):
        comment = find_grouped_preceding_comment(lines, entries, entry_line_indices, index, same_group)
        if not comment:
            issues.append(f'{images_path.name}: entry "{entry["name"]}" has no preceding comment')
            continue

        target = extract_target_version(comment)
        if target and normalize_version(target) != normalize_version(entry["version"]):
            issues.append(
                f'{images_path.name}: entry "{entry["name"]}" comment says target '
                f'"{target}", entry version is "{entry["version"]}"'
            )

        if baseline_paths:
            path = resolve_entry_image_path(entry, current_paths.keys(), repo_map)
            baseline_tag = baseline_paths.get(path) if path else None
            baseline_version = baseline_tag.split("@")[0] if baseline_tag else None
            source = extract_source_version(comment)
            if source and baseline_version and normalize_version(source) != normalize_version(baseline_version):
                issues.append(
                    f'{images_path.name}: entry "{entry["name"]}" comment says source '
                    f'"{source}", upgrade_docs_baseline actually has "{baseline_version}"'
                )

    # Structural, independent of upgrade_docs_baseline: a sidecar image
    # (see is_primary_image_path) needs its OWN indented "#   sidecar:
    # <parent> - <basename> ..." header, never a plain header borrowed
    # from a preceding entry via same_group's "same component, same
    # declared version" heuristic — that heuristic is only ever a proxy
    # for "these two entries genuinely bumped in lockstep", and a
    # sidecar whose real version history diverges from its parent's
    # (kiss-elastic-sync: 0.3.3 -> 3.0.0, sharing "# KISS — 2.2.4 ->
    # 3.0.0" purely because both happen to land on 3.0.0 this release)
    # silently inherits a header that doesn't describe it at all.
    if chart_dir is not None:
        for name, expected, problem in find_images_manifest_faulty_headers(
            entries, entry_line_indices, lines, deps, current_paths, repo_map, canonical_names
        ):
            if problem == "missing":
                issues.append(
                    f'{images_path.name}: entry "{name}" is a sidecar of "{expected.split(" - ")[0]}" '
                    f'but has no own "#   sidecar: {expected} ..." header — it may be sharing a '
                    f"preceding entry's header, which only describes THAT entry's own version bump"
                )
            else:
                issues.append(
                    f'{images_path.name}: entry "{name}" has its own sidecar header, but it does not name "{expected}"'
                )

    # Also structural, independent of upgrade_docs_baseline: entries
    # (or shared-header groups) should follow values.yaml's own top-
    # level component order — the same rule find_out_of_order_names
    # already enforces for -upgrade.md's own rows/Changes headings.
    if chart_dir is not None:
        key_order = values_key_order(values)
        for name_a, name_b in find_images_manifest_out_of_order_names(
            entries, entry_line_indices, lines, deps, current_paths, repo_map, canonical_names, key_order, values
        ):
            issues.append(
                f'{images_path.name}: entry "{name_b}" is listed right after "{name_a}", but '
                f"values.yaml lists {name_b} before {name_a} — entries should follow values.yaml's "
                f"own component order"
            )

    # Also structural, independent of upgrade_docs_baseline: the "#
    # Changes:" header's OWN numbered item list should follow the SAME
    # order as the entry list just checked above — the two can silently
    # disagree (entries correctly grouped/ordered, header list scrambled
    # relative to them) with nothing else here to catch it.
    if chart_dir is not None:
        entry_positions = images_manifest_entry_positions(text, deps, values, repo_map, canonical_names)
        display_name_positions = images_manifest_display_name_positions(text, deps, values, repo_map, canonical_names)
        for item_a, item_b in find_images_manifest_changes_items_out_of_order(
            text, entries, entry_positions, display_name_positions
        ):
            issues.append(
                f'{images_path.name}: "# Changes:" list has "{item_b}" right after "{item_a}", but '
                f"the entry list has them in the opposite order — Changes items should follow the "
                f"same order as the entries below them"
            )

        for name in find_images_manifest_entries_missing_changes_mention(
            text, entries, deps, values, repo_map, canonical_names
        ):
            issues.append(f'{images_path.name}: image "{name}" has an entry but no mention in the "# Changes:" list')

    # Only checked once there's something real to diff against — without
    # a resolvable upgrade_docs_baseline, "changed" can't be computed at
    # all (baseline_values is {} in that case, so baseline_paths is too).
    if baseline_paths and chart_dir is not None:
        unresolvable_paths = set(find_images_without_repository(chart_dir))
        missing_paths, stale_entry_names, unmatched_entry_names = find_images_manifest_list_diff(
            entries,
            current_paths,
            baseline_paths,
            repo_map,
            repo_groups,
            unresolvable_paths,
            chart_dir=chart_dir,
            deps=deps,
            upgrade_docs_baseline=upgrade_docs_baseline,
            values=values,
            baseline_values=baseline_values,
        )
        for path in missing_paths:
            name = path_display_name(path, deps, canonical_names)
            issues.append(f'{images_path.name}: image "{name}" changed vs {upgrade_docs_baseline} but has no entry')
        for name in stale_entry_names:
            issues.append(
                f'{images_path.name}: entry "{name}" is listed but its image did not change vs {upgrade_docs_baseline}'
            )
        for name in unmatched_entry_names:
            issues.append(
                f'{images_path.name}: entry "{name}" is wrong or stale — not found in Chart.yaml or values.yaml'
            )

    return issues
