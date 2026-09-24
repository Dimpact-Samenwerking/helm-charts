"""images-manifest.yaml entry grouping, canonical ordering, and
the sort/out-of-order-detection built on that grouping -- entries
sharing one dependency/sidecar group move and stay together."""

import re

from dataclasses import dataclass
from itertools import pairwise

from lib.chart.chart_yaml import ChartDependency
from lib.chart.pull_and_subchart_resolution import global_image_paths
from lib.chart.registered_paths import is_primary_image_path
from lib.images_manifest import ManifestEntry
from lib.images_manifest import try_parse_images_manifest
from lib.upgradedoc.app_version_and_image_paths import find_all_image_and_version_paths
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_image_path
from lib.upgradedoc.grouped_comments_and_changes_block import find_grouped_preceding_comment_line
from lib.upgradedoc.grouped_comments_and_changes_block import path_display_name
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.sorting_and_ordering import values_tree_position
from lib.upgradedoc.string_and_parsing_basics import normalize_name
from lib.upgradedoc.version_cells_and_key_changes import VERSION_PAIR_RE
from lib.yaml_types import YamlMapping

SIDECAR_HEADER_RE = re.compile(r"^#\s{2,}sidecar:\s*(?P<text>.*)$", re.IGNORECASE)


@dataclass
class ParsedManifest:
    """entries/entry_line_indices/lines, kept in lockstep -- the images-
    manifest's own parsed YAML entries, their corresponding "- name:"
    line indices, and the raw text lines they were parsed from.
    find_images_manifest_faulty_headers/_images_manifest_groups/find_
    images_manifest_out_of_order_names all need the same three kept in
    sync, so bundling them keeps that plumbing from dominating each
    function's own argument count."""

    entries: list[ManifestEntry]
    entry_line_indices: list
    lines: list


@dataclass
class EntryResolution:
    """deps/current_paths/repo_map/canonical_names -- how to resolve an
    images-manifest entry back to its own values-tree path/display name
    (see entry_component/path_display_name), bundled since find_images_
    manifest_faulty_headers/_images_manifest_groups/find_images_manifest_
    out_of_order_names all need the same four together, with `current_
    paths` ALREADY computed by the caller (unlike ManifestSortContext
    below, whose own `values` a caller hands over instead, for a
    function that computes current_paths itself)."""

    deps: list[ChartDependency]
    current_paths: dict
    repo_map: dict
    canonical_names: dict


@dataclass
class ManifestSortContext:
    """deps/values/repo_map/canonical_names -- sort_images_manifest_
    entries/images_manifest_entry_positions/images_manifest_display_
    name_positions' own shared inputs. Unlike EntryResolution, this
    carries `values` instead of a pre-computed `current_paths`: these
    three functions each need current_paths freshly derived from `values`
    + `deps` together (find_all_image_and_version_paths + global_image_
    paths combined, see _images_manifest_sorted_groups), never whatever a
    caller happened to precompute for something else."""

    deps: list[ChartDependency]
    values: YamlMapping
    repo_map: dict
    canonical_names: dict


def entry_component(entry: ManifestEntry, current_paths: dict, repo_map: dict | None):
    """The top-level values-tree component an images-manifest entry
    resolves to (path[0], via resolve_entry_image_path), or None when it
    doesn't resolve to any real path at all."""
    path = resolve_entry_image_path(entry["name"], current_paths.keys(), repo_map)
    return path[0] if path else None


def images_manifest_entries_share_group(
    entry_a: ManifestEntry, entry_b: ManifestEntry, current_paths: dict, repo_map: dict | None
):
    """True when entry_a and entry_b are part of ONE shared-comment
    group in the images manifest — same top-level component AND the
    same declared manifest "version" (evidence of one lockstep bump
    across images, not just a coincidentally-shared values-tree
    prefix — see find_images_manifest_faulty_headers for why this is
    only ever a proxy, never a guarantee). Shared by check_images_
    manifest_format, fix_images_manifest_entries, and sort_images_
    manifest_entries so the three can never disagree about which
    entries move/get validated/get fixed together — before this was
    factored out, it was duplicated as an identical closure in both
    lib.docs_consistency and fix-doc-consistency."""
    component_a = entry_component(entry_a, current_paths, repo_map)
    return (
        component_a is not None
        and component_a == entry_component(entry_b, current_paths, repo_map)
        and entry_a.get("version") == entry_b.get("version")
    )


def _own_header_top_line(lines: list[str], entry_line_index: int):
    """The raw (whitespace-preserving) text of the TOPMOST line in this
    entry's own directly-preceding comment block, or None when there's
    no comment directly above it at all (a blank/non-comment line sits
    there instead — the entry either shares a preceding entry's header
    via the legacy same-group convention find_grouped_preceding_comment
    (_line) still supports, or has no header whatsoever). Unlike find_
    preceding_comment(_line), this never requires the line to state a
    version pair — a header can legitimately have none (a brand-new
    component, or free-form context prose) and the sidecar/primary shape
    check this feeds only cares about the line's own leading "#"/indent,
    never its content."""
    j = entry_line_index - 1
    top = None
    while j >= 0 and lines[j].strip().startswith("#"):
        top = lines[j]
        j -= 1
    return top


def images_manifest_block_start(lines: list[str], entry_line_idx: int):
    """The line index where this entry's own preceding comment block
    begins (or the entry line itself if it has none) — walks upward
    through contiguous "#"-prefixed lines directly above. When the
    comment is actually shared with an earlier entry (see find_grouped_
    preceding_comment), this naturally lands on that earlier entry's own
    comment start too — inserting a new block right before it never
    splits an existing group, and sort_images_manifest_entries relies on
    this same landing to move a whole shared-comment group as one
    physical unit. Unlike _own_header_top_line (which returns None when
    there's no comment at all, for a caller that needs to tell "no
    header" apart from "has one"), this always returns a usable line
    index — the entry's own line itself when there's nothing above it —
    for callers that need "where does this entry's physical block, with
    or without a header, begin" instead."""
    i = entry_line_idx
    while i > 0 and lines[i - 1].lstrip().startswith("#"):
        i -= 1
    return i


def header_name_segment(text: str):
    """A header's own component-name portion — everything before its
    version pair (or before a trailing "(...)" aside, or the whole text
    when neither is present), with a trailing dash/em-dash separator
    stripped. Public (no longer underscore-prefixed): originally just
    find_images_manifest_faulty_headers' own private helper for a "#
    sidecar: ..." comment's name segment, but the exact same "<name>
    <version-info>(optional paren clause)" shape also describes a "###
    ..." Changes-section heading — fix-doc-consistency's own fix_
    changes_heading_app_versions reuses this directly to isolate an
    EXISTING heading's own name portion before rewriting just its
    app-version portion, rather than re-deriving a (potentially
    DIFFERENT-looking, e.g. the table row's own longer "mi-data (MI-data
    exports)" vs the heading's own shorter "mi") name from the row.

    Comparing only this isolated segment (not the header's full text)
    for EXACT equality — never a "startswith" check against the full
    text — matters because one canonical sidecar name can be a literal
    text-prefix of another's ("redis-operator - redis" is a prefix of
    "redis-operator - redis-exporter" once punctuation is stripped by
    normalize_name); a startswith check would silently
    accept the wrong sidecar's header as long as it named the RIGHT
    parent and happened to start with the right basename's own letters.

    A header with NO version pair anywhere (real case: fix-doc-
    consistency's own "<name> <version> (digest changed)" shape for a
    same-version/changed-digest re-pin, e.g. "keycloak-operator - python
    3.14.7-slim (digest changed)" — the first sidecar header shape with
    no arrow at all) still has a trailing BARE version token stuck right
    before its "(...)" aside — VERSION_PAIR_RE finds nothing to search
    for there, so it must be stripped separately, the same atom shape
    VERSION_PAIR_RE's own source/target groups use. Only attempted when
    a trailing "(...)" aside is actually present: nothing in this
    codebase ever writes a bare "<name> <version>" header with no arrow
    AND no aside, so requiring one here is what keeps this from ever
    mistaking a real bare-name-only header's own last word (no version
    at all) for a version token and truncating a real basename by
    mistake.

    Trailing aside(s) are stripped from the very END of the string —
    repeatedly, since there can be more than one back to back (an
    app-side "(new)"/"(unchanged)"/"(digest changed)" aside AND a
    "(chart ...)" one) — never by truncating at wherever the FIRST "("
    happens to appear anywhere in the text: a real component's own
    display name can itself embed a parenthetical nowhere near the
    trailing aside (real bug, real docs: "mi-data (MI-data exports)",
    "Keycloak Operator (server)" — truncating at the first "(" turned
    both into a bare "mi-data"/"Keycloak Operator", silently losing
    the rest of the name)."""
    m = VERSION_PAIR_RE.search(text)
    if m:
        return text[: m.start()].rstrip(" \t—-")
    without_trailing_asides = re.sub(r"(\s*\([^)]*\))+$", "", text)
    if without_trailing_asides == text:
        return text.rstrip(" \t—-")
    bare_version = re.search(r"\s[A-Za-z0-9][\w.\-]*$", without_trailing_asides)
    name = without_trailing_asides[: bare_version.start()] if bare_version else text
    return name.rstrip(" \t—-")


def find_images_manifest_faulty_headers(manifest: ParsedManifest, resolution: EntryResolution):
    """[(entry_name, expected_display_name, problem), ...] for every
    SIDECAR entry (see is_primary_image_path — a co-equal primary image
    like zgw-office-addin's frontend/backend is exempt, expected and
    fine to keep sharing one plain header) whose own header doesn't
    correctly, unambiguously identify it. `manifest` is a ParsedManifest,
    `resolution` an EntryResolution. problem is:
    - "missing": no own indented "#   sidecar: ..." header directly
      above the entry at all — it may be silently sharing a PRECEDING
      entry's plain header instead (the exact ambiguity that once let
      one shared "# KISS — 2.2.4 -> 3.0.0" header wrongly stand in for
      kiss-elastic-sync's own, genuinely different 0.3.3 -> 3.0.0 bump,
      since same_group's "same component + same declared version" test
      is only ever a proxy for "these two entries bumped in lockstep",
      not a guarantee. That specific pair no longer even reaches this
      check: kiss-elastic-sync (settings.syncJobs.image) is now listed
      alongside kiss's own "image" in lib.chart.component_image_paths(),
      so is_primary_image_path exempts it here the same way it already
      exempted zgw-office-addin's frontend/backend, and lib.checks.
      lockstep.check_lockstep_versions now guards its actual version
      agreement directly against values.yaml instead. This "missing"
      check still protects every OTHER, not-yet-registered sidecar
      against the same same_group misfire).
    - "wrong_name": it HAS its own indented sidecar header, but that
      header's own name segment (see header_name_segment — everything
      before the version pair) doesn't EXACTLY equal "<parent> -
      <basename>" (see path_display_name) — the same canonical sidecar-
      naming convention -upgrade.md's own "### <parent> - <basename>
      ..." Changes headings already use, the indent and "sidecar:"
      keyword aside. Exact equality, not a prefix check: "redis-operator
      - redis" is a literal text-prefix of "redis-operator - redis-
      exporter" once normalize_name strips punctuation, so a startswith
      comparison would wrongly accept the redis-exporter sidecar's own
      header as if it named plain "redis".

    An entry that doesn't resolve to any values-tree path at all is
    skipped entirely — already reported elsewhere (see find_images_
    manifest_list_diff's unmatched_entry_names), and there's no real
    "expected name" to check a header against for something that isn't
    a real image. Likewise skipped: a path rooted at anything with no
    Chart.yaml dependency of its own at all (podiumd's own directly-
    templated top-level blocks — "keycloak", "apiproxy", "frankgateway",
    the shared "global" anchor — see lib.image.repository_check's own
    docstring for the real cases) — there's no PARENT for such an entry
    to be a "sidecar OF", so the "#   sidecar: <parent> - ..." shape
    doesn't apply to it; its own free-form header (explaining WHY it's
    listed, not whose sidecar it is) is exactly the right shape already
    (see is_primary_image_path, which treats "no owning dependency" as
    primary/standalone for exactly this reason)."""
    problems = []
    for entry, line_idx in zip(manifest.entries, manifest.entry_line_indices, strict=True):
        path = resolve_entry_image_path(entry["name"], resolution.current_paths.keys(), resolution.repo_map)
        if path is None or is_primary_image_path(path, resolution.deps):
            continue
        display_name = path_display_name(path, resolution.deps, resolution.canonical_names)
        top_line = _own_header_top_line(manifest.lines, line_idx)
        match = SIDECAR_HEADER_RE.match(top_line) if top_line is not None else None
        if match is None:
            problems.append((entry["name"], display_name, "missing"))
        elif normalize_name(header_name_segment(match.group("text"))) != normalize_name(display_name):
            problems.append((entry["name"], display_name, "wrong_name"))
    return problems


def images_manifest_entry_order_key(
    path: tuple[str, ...] | None, deps: list[ChartDependency], key_order: list, values: YamlMapping | None = None
) -> tuple[int, ...]:
    """An images-manifest entry's own sort key — (values_key_index,
    is_sidecar), the SAME shape and meaning component_order_key already
    uses for -upgrade.md's own rows/Changes headings — computed from the
    entry's own RESOLVED values-tree path (see resolve_entry_image_path)
    rather than component_order_key's fuzzy name-word matching: the
    images manifest already has a deterministic path for every entry,
    so falling back to fuzzy matching here would be a regression (see
    is_primary_image_path/path_display_name for the same primary/
    sidecar split, reused here rather than re-derived). path=None (an
    entry that doesn't resolve to any real values-tree path at all —
    see find_images_manifest_list_diff's unmatched_entry_names) sorts
    after every real one, the same sentinel component_order_key uses
    for a name that doesn't resolve to any dependency at all.

    `values` (the real parsed values.yaml dict, optional) fixes a real
    bug this "is_sidecar" bit alone never could: is_primary_image_path
    is ALSO True for a shared "global.images.*" path (nginx/curl/
    busybox/redis) — deemed "primary" itself since it has no owning
    dependency to be a SIDECAR of at all (see is_primary_image_path's
    own docstring) — so every one of those four independently-orderable
    peers used to tie at the exact same (values_key_index, 0), their
    own relative order left to whatever a stable sort happened to
    preserve (confirmed live: real bug, four different documents
    disagreeing on this exact order). The identical tie exists for a
    real dependency's own several CO-EQUAL primary paths too (e.g.
    zgw-office-addin's frontend + backend, both "primary", both landing
    on (idx, 0) before this fix), and for two DIFFERENT sidecars of the
    very same parent (both landing on (idx, 1)).

    Given `values`, EVERY real path's own FULL nested position (see
    values_tree_position) is appended as a further tie-break — (idx,
    is_sidecar) + values_tree_position(values, path)[1:] — never
    disturbing the primary-vs-sidecar boundary itself: (idx, 0, ...) is
    always < (idx, 1, ...) regardless of what follows, so a real
    dependency's own registered primary path still always sorts before
    every one of its own sidecars (is_primary_image_path is completely
    unaffected either way — it stays exactly what it always was, a
    separate "does this need a '#   sidecar: ...' header" question) —
    only items that ALREADY tied at the same (idx, is_sidecar) gain a
    real, distinct order instead of an arbitrary stable-sort one.
    Omitting `values` preserves the exact prior (values_key_index, is_
    sidecar) behavior unchanged — a caller with no values.yaml dict
    handy is never worse off than before."""
    if path is None:
        return (len(key_order), 1)
    try:
        idx = key_order.index(path[0])
    except ValueError:
        idx = len(key_order)
    is_sidecar = 0 if is_primary_image_path(path, deps) else 1
    if values is not None:
        return (idx, is_sidecar, *values_tree_position(values, path)[1:])
    return (idx, is_sidecar)


def _images_manifest_groups(manifest: ParsedManifest, resolution: EntryResolution):
    """[(indices, path, display_name), ...] — one entry per physical
    GROUP of consecutive entries sharing a single preceding comment
    (see find_grouped_preceding_comment_line/images_manifest_entries_
    share_group), in the manifest's current top-to-bottom order. `path`/
    `display_name` are the group's FIRST entry's own resolved values-
    tree path (see resolve_entry_image_path) and path_display_name (or
    the raw entry name when unresolvable). `manifest` is a
    ParsedManifest, `resolution` an EntryResolution. Shared by sort_
    images_manifest_entries (which physically reorders these) and find_
    images_manifest_out_of_order_names (which only compares adjacent
    keys) so the two can never disagree about what counts as one group."""
    n = len(manifest.entries)

    def same_group(entry_a: ManifestEntry, entry_b: ManifestEntry):
        return images_manifest_entries_share_group(entry_a, entry_b, resolution.current_paths, resolution.repo_map)

    comment_idx_for = [
        find_grouped_preceding_comment_line(
            manifest.lines, manifest.entries, manifest.entry_line_indices, i, same_group
        )
        for i in range(n)
    ]
    index_groups = []
    for i in range(n):
        if i > 0 and comment_idx_for[i] is not None and comment_idx_for[i] == comment_idx_for[i - 1]:
            index_groups[-1].append(i)
        else:
            index_groups.append([i])

    groups = []
    for indices in index_groups:
        path = resolve_entry_image_path(
            manifest.entries[indices[0]]["name"], resolution.current_paths.keys(), resolution.repo_map
        )
        name = (
            path_display_name(path, resolution.deps, resolution.canonical_names)
            if path
            else manifest.entries[indices[0]]["name"]
        )
        groups.append((indices, path, name))
    return groups


def find_images_manifest_out_of_order_names(
    manifest: ParsedManifest, resolution: EntryResolution, key_order: list[str], values: YamlMapping | None = None
):
    """[(name_a, name_b), ...] for every ADJACENT pair of images-
    manifest GROUPS (see _images_manifest_groups) whose relative order
    contradicts values.yaml's own top-level key order (see images_
    manifest_entry_order_key) — same "adjacent pairs are sufficient to
    catch any non-monotonic sequence" reasoning find_out_of_order_names
    already uses for -upgrade.md's own rows/Changes headings. `manifest`
    is a ParsedManifest, `resolution` an EntryResolution.

    `values`, passed straight through to images_manifest_entry_order_
    key, is what actually distinguishes two different non-primary
    entries sharing the same top-level key (e.g. two "global.images.*"
    entries) — omitted, every such pair ties and is never flagged as
    out of order against each other, exactly as before."""
    groups = _images_manifest_groups(manifest, resolution)
    violations = []
    # groups[1:] is deliberately one element shorter than groups -- same
    # adjacent-pairs shape as find_out_of_order_names' own zip(names,
    # names[1:]) above -- not a same-length zip.
    for (_, path_a, name_a), (_, path_b, name_b) in pairwise(groups):
        if images_manifest_entry_order_key(
            path_b, resolution.deps, key_order, values
        ) < images_manifest_entry_order_key(path_a, resolution.deps, key_order, values):
            violations.append((name_a, name_b))
    return violations


def _collapse_group_internal_blank_lines(group_text: str):
    """Within one multi-entry group's own captured text, drop every
    blank line that separates two of the group's own entries — a shared
    header's entries sit directly below one another, no blank line
    between them, matching the convention every OTHER multi-entry group
    in the real manifest already follows (e.g. eck-stack's elasticsearch/
    kibana/enterprise-search trio). Only the chunk's own TRAILING blank
    line(s) — the separator before the NEXT group — are preserved: this
    strips a line only when further non-blank content still follows it
    within this same chunk, never the chunk's own tail."""
    lines = group_text.splitlines(keepends=True)
    last_content = len(lines)
    while last_content > 0 and lines[last_content - 1].strip() == "":
        last_content -= 1
    body = [line for line in lines[:last_content] if line.strip() != ""]
    return "".join(body + lines[last_content:])


def _images_manifest_sorted_groups(manifest: ParsedManifest, context: ManifestSortContext):
    """(groups, order) — groups from _images_manifest_groups; order is
    the permutation (list of original group indices, in their NEW
    sorted sequence) sort_images_manifest_entries physically applies,
    computed via values_key_order/images_manifest_entry_order_key.
    `manifest` is a ParsedManifest, `context` a ManifestSortContext.
    Shared with images_manifest_entry_positions so any caller needing
    "what position does entry X end up at" (see sort_images_manifest_
    changes_items, which mirrors the entry list's own final order
    rather than computing a second, independent one) never re-derives
    the grouping/sort-key logic on its own.

    current_paths includes global_image_paths(values) alongside the
    ordinary scan — without it, an entry naming a shared base image
    (e.g. "curlimages/curl") can't resolve back to its own repo_map hit
    at all (resolve_entry_image_path's own "path in paths" guard fails
    for a path this dict doesn't contain), falls through to fuzzy name-
    word matching, and sorts as if unresolved — landing at the very END
    of the manifest instead of under "global" 's own values.yaml
    position (first, since "global:" is the file's own first top-level
    key)."""
    current_paths = dict(find_all_image_and_version_paths(context.values, context.deps))
    current_paths.update(global_image_paths(context.values))
    resolution = EntryResolution(context.deps, current_paths, context.repo_map, context.canonical_names)
    groups = _images_manifest_groups(manifest, resolution)
    key_order = values_key_order(context.values)
    order = (
        sorted(
            range(len(groups)),
            key=lambda gi: images_manifest_entry_order_key(groups[gi][1], context.deps, key_order, context.values),
        )
        if len(groups) >= 2
        else list(range(len(groups)))
    )
    return groups, order


def _parsed_manifest_from_text(text: str):
    """(ParsedManifest, ok) for `text` — ok is False (ParsedManifest is
    then meaningless/unused) when `text` isn't valid YAML, isn't a list,
    or has fewer than 2 entries — the same three guards images_manifest_
    entry_positions/images_manifest_display_name_positions/sort_images_
    manifest_entries all apply before there's anything meaningful to
    group/sort/position at all."""
    lines = text.splitlines(keepends=True)
    entries = try_parse_images_manifest(text)
    if entries is None:
        return None, False

    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    n = min(len(entries), len(entry_line_indices))
    entries, entry_line_indices = entries[:n], entry_line_indices[:n]
    if n < 2:
        return None, False
    return ParsedManifest(entries, entry_line_indices, lines), True


def images_manifest_entry_positions(text: str, context: ManifestSortContext):
    """{entry_name: 0-based final position} for every entry in the
    images manifest, after applying the SAME group-level reordering
    sort_images_manifest_entries itself performs — for a caller that
    needs to mirror the entry list's own final order (see sort_images_
    manifest_changes_items) rather than compute a second, independently-
    sorted order via free-form text matching, which can disagree with
    where the entry list itself puts something (real case: a Changes
    item mentioning "keycloak-operator" only incidentally, inside its
    own parenthetical aside, fuzzy-matched that dependency and landed
    ahead of its real sidecars instead of following its actual entry's
    own position). Every entry sharing one group gets that group's own
    single position. `context` is a ManifestSortContext. {} if the
    manifest isn't valid YAML or has fewer than 2 entries — same guards
    sort_images_manifest_entries applies."""
    manifest, ok = _parsed_manifest_from_text(text)
    if not ok or manifest is None:
        return {}

    groups, order = _images_manifest_sorted_groups(manifest, context)
    position_of_group = {orig_i: slot for slot, orig_i in enumerate(order)}
    positions = {}
    for group_index, (indices, _path, _name) in enumerate(groups):
        for entry_index in indices:
            positions[manifest.entries[entry_index]["name"]] = position_of_group[group_index]
    return positions


def images_manifest_display_name_positions(text: str, context: ManifestSortContext):
    """{display_name: 0-based final position} — the SAME group-level
    positions images_manifest_entry_positions computes, keyed by each
    group's own path_display_name instead of its entries' raw YAML
    "name:" fields. `context` is a ManifestSortContext. Exists for
    matching a "# Changes:" item's own text by EXACT prefix (see
    fix-doc-consistency's sort_images_manifest_changes_items) rather
    than match_changes_item_to_entry's fuzzy basename-in-text search —
    which only ever works when an entry's own repository basename
    happens to appear in the item's own display name (true for a
    "global" shared image, whose display name IS its basename, and true
    by coincidence for a dependency like "keycloak-operator" whose alias
    happens to start with its own image's basename "keycloak") but is
    never true in general: "kiss" (the dependency's own alias) shares no
    word at all with "kiss-frontend" (its own image's repository
    basename), and "kiss-eck" shares nothing with "elasticsearch"/
    "kibana" either — every auto-inserted item's own text is built as
    f"{name} {old} -> {new}." (see add_missing_images_manifest_entries'
    own version_text) using this EXACT display name, so matching against
    it directly is never a guess for anything the tooling itself wrote.

    More than one group can legitimately share one display name (real
    case: kiss-eck's own eck-elasticsearch and eck-kibana version
    fields are two SEPARATE groups — each has its own distinct "###"
    comment, no single header covers both — but path_display_name gives
    both the same bare "kiss-eck", since neither is registered as more
    "the" primary than the other). The FIRST (lowest) position among
    same-named groups wins — they're adjacent either way (both resolve
    to the exact same values-tree top-level key, so images_manifest_
    entry_order_key never separates them), so either position places a
    matching Changes item correctly alongside the rest of that family.

    {} under the exact same guards images_manifest_entry_positions
    applies (invalid YAML, or fewer than 2 entries)."""
    manifest, ok = _parsed_manifest_from_text(text)
    if not ok or manifest is None:
        return {}

    groups, order = _images_manifest_sorted_groups(manifest, context)
    position_of_group = {orig_i: slot for slot, orig_i in enumerate(order)}
    positions = {}
    for group_index, (_indices, _path, name) in enumerate(groups):
        position = position_of_group[group_index]
        if name not in positions or position < positions[name]:
            positions[name] = position
    return positions


def match_changes_item_display_name(rest: str, display_name_positions: dict):
    """The longest key of display_name_positions that `rest` starts with
    (followed by a space, or an exact match) — every auto-inserted
    Changes item's own text is always built as f"{name} {old} -> {new}."
    (see fix-doc-consistency's add_missing_images_manifest_entries' own
    version_text), so this is an EXACT match for anything the tooling
    itself wrote, never a guess — unlike lib.docs_consistency.match_
    changes_item_to_entry's fuzzy basename-in-text search, which has no
    way to resolve a name like "kiss" or "kiss-eck" that shares no word
    at all with its own entry's repository basename ("kiss-frontend",
    "elasticsearch"/"kibana"). A hand-written free-form item (e.g.
    "Keycloak app image 26.6.4 -> 26.7.2 (...)") simply won't start with
    any known display name, and the caller falls back to match_changes_
    item_to_entry for that case instead. Longest match wins so a
    primary's own display name ("keycloak-operator") is never chosen
    over its own sidecar's longer, " - "-suffixed one ("keycloak-
    operator - postgres") sharing the same prefix. None if nothing
    matches. Shared by fix-doc-consistency's own sort_images_manifest_
    changes_items (the fixer) and lib.docs_consistency's own out-of-
    order/missing-mention checks — the SAME resolution, so checker and
    fixer can never disagree about what a Changes item "is"."""
    best = None
    for name in display_name_positions:
        if (rest == name or rest.startswith(name + " ")) and (best is None or len(name) > len(best)):
            best = name
    return best


def _group_texts_and_components(lines: list[str], groups: list, starts: list[int]):
    """(per_group_texts, components) — each group's own captured text
    span (with an already-multi-entry group's OWN internal blank lines
    collapsed first, see _collapse_group_internal_blank_lines) and its
    own top-level values-tree component (for the cross-group run-
    collapsing _merge_ordered_groups does next)."""
    ends = [*starts[1:], len(lines)]
    original_texts = ["".join(lines[s:e]) for s, e in zip(starts, ends, strict=True)]
    # A single GROUP already spanning more than one entry (a literal
    # shared header, e.g. zgw-office-addin's own frontend+backend) needs
    # its own internal collapse first — the broader cross-group merge
    # in _merge_ordered_groups only ever looks at whole groups, so this
    # is the only place that removes a blank line hand-inserted BETWEEN
    # two entries that already share one comment line.
    per_group_texts = [
        _collapse_group_internal_blank_lines(t) if len(indices) > 1 else t
        for (indices, _, _), t in zip(groups, original_texts, strict=True)
    ]
    components = [path[0] if path else None for _, path, _ in groups]
    return per_group_texts, components


def _merge_ordered_groups(per_group_texts: list[str], components: list, order: list[int]):
    """Runs of consecutive same-component groups (in the NEW, post-sort
    `order`) merged into one text block each — collapsing blank lines
    within a multi-group run (see _collapse_group_internal_blank_lines)
    and normalizing exactly one blank line between different-component
    runs, per sort_images_manifest_entries' own docstring. Never merges
    two groups whose component can't be resolved at all (None) even if
    they happen to sit next to each other — only a real, matching
    component identifies one family."""
    ordered_texts = [per_group_texts[i] for i in order]
    ordered_components = [components[i] for i in order]

    merged_texts = []
    run_start = 0
    for i in range(1, len(ordered_texts) + 1):
        at_end = i == len(ordered_texts)
        if at_end or ordered_components[i] is None or ordered_components[i] != ordered_components[run_start]:
            run_text = "".join(ordered_texts[run_start:i])
            run_text = _collapse_group_internal_blank_lines(run_text) if i - run_start > 1 else run_text
            if not at_end:
                # Exactly one blank line before the NEXT run — never
                # zero (a group's own captured span never includes a
                # LEADING blank line, so a pre-existing "no separator at
                # all" defect otherwise survives forever once spliced
                # next to a new neighbor — see sort_images_manifest_
                # entries' own docstring) and never more than one (a
                # run's own INTERNAL blanks are already handled above;
                # this is purely its own trailing edge).
                run_text = run_text.rstrip("\n") + "\n\n"
            merged_texts.append(run_text)
            run_start = i
    return merged_texts


def _sorted_manifest_text(lines: list[str], entry_line_indices: list[int], groups: list, order: list[int]):
    """The manifest's own full text after physically applying `order` to
    `groups` — see sort_images_manifest_entries' own docstring for the
    blank-line collapse/normalize rules this also applies. Restores the
    manifest's own leading prefix (whatever precedes the very first
    group — never itself part of any group's own captured span)."""
    starts = [images_manifest_block_start(lines, entry_line_indices[indices[0]]) for indices, _, _ in groups]
    per_group_texts, components = _group_texts_and_components(lines, groups, starts)
    merged_texts = _merge_ordered_groups(per_group_texts, components, order)
    prefix = "".join(lines[: starts[0]])
    return prefix + "".join(merged_texts)


def sort_images_manifest_entries(text: str, context: ManifestSortContext):
    """Reorder the images manifest's own entry GROUPS (physically, in
    the text) to match values.yaml's own top-level key order — see
    values_key_order/images_manifest_entry_order_key, the same rule
    sort_upgrade_doc_rows/sort_changes_blocks already apply to
    -upgrade.md's own rows/Changes blocks. A group (see _images_
    manifest_groups) is moved as ONE physical unit, never split, so a
    shared header always stays directly above every entry it actually
    covers. `context` is a ManifestSortContext.

    Also collapses blank lines between entries belonging to the SAME
    top-level component (see _collapse_group_internal_blank_lines) — a
    broader notion than _images_manifest_groups' own "shares one literal
    comment line" grouping: a component's own sidecars almost always
    have their own separate header each (different versions bumped
    independently, e.g. keycloak-operator's own postgres/python job
    images), yet the whole family — primary plus every sidecar — is
    still meant to read as ONE visual block, blank-line-separated only
    from the NEXT component, not internally. Computed on the manifest's
    FINAL (post-sort) order, over RUNS of consecutive same-component
    groups — the sort above already guarantees every such run sits
    together (stable sort: entries sharing one component always compare
    equal by images_manifest_entry_order_key, so their original relative
    order survives untouched, and no other component's own tied key can
    wedge between them) — never merging two groups whose component can't
    be resolved at all (path is None) even if they happen to sit next to
    each other; only a real, matching component identifies one family.
    Applied regardless of whether anything moved, since it's a separate
    formatting concern from ordering.

    Also NORMALIZES the blank-line separator BETWEEN two different-
    component runs to exactly one, whether or not anything actually
    moved — a group's own captured span (images_manifest_block_start)
    never includes a LEADING blank line (that's the PRECEDING group's
    own trailing space instead — see that function's own docstring),
    so a group that originally had NO trailing blank line at all (a
    real pre-existing formatting defect, not something reordering
    caused) previously stayed permanently separator-less once spliced
    next to whatever new neighbor it landed beside — this function only
    ever COLLAPSED an excess (see _collapse_group_internal_blank_lines),
    never inserted a missing one. Real bug, real doc: images-4.9.1.yaml
    had zero blank lines between its own redis entry and keycloak-
    operator's, and between frankgateway's and zaakbrug's — confirmed
    live, traced to a historical (now-superseded) reordering commit that
    spliced blocks together without ever re-establishing this separator,
    and never caught since because nothing ever re-normalized it
    afterward, only ever collapsed a run's own INTERNAL blanks.

    Returns (new_text, moved) where moved is [(display_name, old_
    position, new_position)] (1-based, among just the manifest's own
    groups) for every group whose position actually changed — empty
    list, but new_text may still differ from text if only blank lines
    were collapsed/normalized; both text and moved are exactly (text,
    []) only when NEITHER changed anything — e.g. isn't valid YAML, or
    has fewer than 2 entries total."""
    manifest, ok = _parsed_manifest_from_text(text)
    if not ok or manifest is None:
        return text, []

    groups, order = _images_manifest_sorted_groups(manifest, context)
    moved = [(groups[i][2], i + 1, slot + 1) for slot, i in enumerate(order) if i != slot]

    new_text = _sorted_manifest_text(manifest.lines, manifest.entry_line_indices, groups, order)
    if new_text == text:
        return text, []
    return new_text, moved
