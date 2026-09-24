"""Canonical values.yaml-order sorting for the three upgrade-doc
sections (Component-versions table rows, Changes blocks, values-
deltas sections) plus the shared component_order_key/values_key_
order machinery all three sorts are built on."""

import re

from itertools import pairwise

from lib.chart.registered_paths import native_components
from lib.chart.values_tree_primitives import values_key_of
from lib.upgradedoc.string_and_parsing_basics import match_canonical_sidecar_name
from lib.upgradedoc.string_and_parsing_basics import match_dependency
from lib.upgradedoc.string_and_parsing_basics import match_located_line
from lib.upgradedoc.string_and_parsing_basics import match_native_component
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows

CHANGES_BLOCK_HEADING_RE = re.compile(r"^###\s+(.+)$")


VALUES_DELTA_SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")


def values_key_order(values: dict | None):
    """Top-level keys of values.yaml in the order they appear in the file,
    top to bottom — yaml.safe_load's mapping is a plain dict, which
    preserves insertion order (Python 3.7+); for a top-level mapping that
    IS the file's own line order. Every doc's "Component versions" table
    and "## Changes" section is expected to mirror this same order, so a
    reader scanning one can find a component at roughly the same "place"
    scanning the other."""
    return list(values.keys()) if isinstance(values, dict) else []


def values_tree_position(values: dict, path: tuple[str, ...]) -> tuple[int, ...]:
    """The FULL nested position of a resolved values-tree `path` (a
    tuple) within `values`'s own real structure — one index per path
    segment, each segment's own position among its immediate parent
    dict's OWN keys at that exact nesting level (yaml.safe_load's
    mapping preserves insertion order, see values_key_order) — e.g.
    (0, 0, 3) for ("global", "images", "redis") when "global" is
    values.yaml's own first top-level key, "images" is global's own
    first key, and "redis" is the fourth key under global.images itself
    (nginx, curl, busybox, redis — real chart order). THE one place
    that answers "what index does this occupy in values.yaml's real
    structure", shared by every doc-ordering consumer (component_order_
    key/images_manifest_entry_order_key/images_manifest_order_key) that
    needs to sort by more than just a resolved path's own TOP-LEVEL key
    — see component_order_key's own docstring for the real bug this
    closes: three separately-implemented sort-key functions each only
    ever resolved a path down to its top-level key index, silently
    tying every "global.images.*" entry (nginx/curl/busybox/redis, all
    genuinely different, independently-orderable images) to the exact
    same key and leaving their RELATIVE order to whatever a stable sort
    happened to preserve from each document's own prior, uncorrected
    text — four documents, four different (and each individually WRONG)
    orderings, confirmed live.

    A path segment not found in its own immediate parent dict at all
    (shouldn't happen for an already-resolved path, but never trusted
    blindly) truncates the tuple right there, appending one final
    "never found, sorts after every real sibling at this level"
    sentinel index instead of guessing or crashing.

    A path that is a genuine PREFIX of a longer one (e.g. ("zac",) vs
    ("zac", "opentelemetry-collector", "image")) always compares as
    LESS than it — Python's own tuple-comparison rule (a strictly
    shorter tuple that agrees with a longer one on every shared element
    always sorts first) — exactly the "a dependency's own primary row/
    section sorts before every one of its own nested sidecars"
    guarantee callers rely on, with no separate is-this-a-sidecar bit
    needed at this level: component_order_key's own "dep"/"native"
    branch deliberately keeps returning a bare 1-tuple (never resolving
    down into whichever specific image path the row's app version
    actually came from) for exactly this reason."""
    position = []
    node = values
    for segment in path:
        if not isinstance(node, dict) or segment not in node:
            position.append(len(node) if isinstance(node, dict) else 0)
            break
        position.append(list(node.keys()).index(segment))
        node = node[segment]
    return tuple(position)


def component_order_key(
    name: str, deps: list, key_order: list, canonical_names: dict | None = None, values: dict | None = None
) -> tuple[int, ...]:
    """A doc item's (table row name, or "### ..." Changes heading) sort
    position: (values_key_index, is_sidecar) — values_key_index is the
    values.yaml top-level key match_dependency resolves `name` to (falling
    back to match_native_component — see lib.chart.native_components — for
    a component with no Chart.yaml dependency at all, e.g. frankgateway),
    as its index in key_order, or len(key_order) (sorts after every real
    component) when `name` doesn't resolve to either at all (e.g. a row
    summarizing several shared-image components at once, or free-form
    prose that doesn't name one).
    is_sidecar (0 or 1) is a secondary tie-break: a canonical sidecar/
    shared-image name always contains " - " (see lib.chart.
    canonical_sidecar_row_names — "<parent> - <basename>", the only shape
    that ever does), so it always sorts right AFTER its owning
    dependency's own row/section even though match_dependency's fuzzy
    word-containment resolves BOTH to the very same values_key_index —
    without this bit, two same-key items keep whatever relative order
    they already happened to have in the doc (Python's sort is stable),
    which silently tolerated a sidecar appearing BEFORE its own parent.
    A tuple compares lexicographically, so this is a drop-in replacement
    for the plain int this used to return. Shared by the docs-consistency
    out-of-order check and fix-doc-consistency's own reordering/insertion
    passes, so "what order should this be in" is answered exactly once.

    canonical_names (canonical_sidecar_row_names' own {name: path} map,
    optional) is consulted ONLY when match_dependency finds no real
    dependency at all — a bare "global" shared-image name (e.g. "nginx-
    unprivileged") never embeds any dependency's own name/alias as a
    substring the way "<dep> - <basename>" sidecar names do, so match_
    dependency's fuzzy word-containment has nothing to find and this
    used to always fall to the "unmatched sorts last" sentinel — even
    though "global:" is values.yaml's own FIRST top-level key. Matched
    via match_canonical_sidecar_name (exact bare-name hit for a table
    row, text_names for a "### ..." Changes heading whose name is
    followed by version/arrow text) rather than a raw dict lookup, so
    both doc shapes resolve the same way. Omit (or pass
    None) wherever a canonical_names lookup isn't available/relevant —
    behaves exactly as before, real dependency names and their own "<dep>
    - <basename>" sidecars are entirely unaffected either way.

    `values` (the real parsed values.yaml dict, optional) fixes a real
    bug this "is_sidecar" bit alone never could: EVERY canonical sidecar/
    shared-image name resolved via canonical_names ties at the exact
    SAME (values_key_index, is_sidecar) — e.g. "nginx-unprivileged",
    "curl", "busybox", and "redis" (all four peers under values.yaml's
    own "global.images.*") all resolve to (0, 0), leaving their own
    RELATIVE order entirely to Python's stable sort preserving whatever
    the document already happened to have — confirmed live: four
    different doc/manifest locations, four different (individually
    WRONG) orderings, no two agreeing with each other OR with values.
    yaml's own real order (nginx, curl, busybox, redis). When `values`
    is given and the sidecar path resolves (via canonical_names), this
    returns (values_key_index,) + values_tree_position(values, path)[1:]
    instead — the path's FULL real nested position, walking all the way
    down through values.yaml's own actual structure, not just its
    top-level key. A "dep"/"native" identity's own key deliberately
    stays a bare 1-tuple (values_key_index,) in that case (never resolved
    down into whichever specific image path the row's app version
    actually came from) — see values_tree_position's own docstring for
    why a strict tuple PREFIX always sorts first, giving "a dependency's
    own row/section sorts before every one of its own sidecars" for
    free, with no separate is_sidecar bit needed once `values` is given.
    Omitting `values` (or passing None) preserves the exact prior
    (values_key_index, is_sidecar) behavior unchanged — a caller with no
    values.yaml dict handy is never worse off than before."""
    dep = match_dependency(name, deps)
    values_key = values_key_of(dep) if dep else None
    is_sidecar = 1 if " - " in name else 0
    sidecar_path = None
    if values_key is None:
        values_key = match_native_component(name, native_components())
    if values_key is None and canonical_names is not None:
        sidecar_path = match_canonical_sidecar_name(name, canonical_names)
        if sidecar_path:
            values_key = sidecar_path[0]
    if values_key is None:
        return (len(key_order), is_sidecar)
    try:
        idx = key_order.index(values_key)
    except ValueError:
        return (len(key_order), is_sidecar)
    if sidecar_path is not None and values is not None:
        return (idx, *values_tree_position(values, sidecar_path)[1:])
    return (idx, is_sidecar)


def find_out_of_order_names(
    names: list, deps: list, key_order: list[str], canonical_names: dict | None = None, values: dict | None = None
):
    """[(name_a, name_b), ...] for every ADJACENT pair whose relative order
    contradicts values.yaml's own top-level key order (see
    component_order_key) — checking only adjacent pairs is sufficient to
    catch any out-of-order sequence, since a non-monotonic sequence always
    has at least one adjacent inversion. A name that doesn't resolve to any
    dependency (and, given canonical_names, doesn't resolve to a "global"
    shared-image path either) sorts after every real one (see component_
    order_key) and never itself causes a violation against another such
    name, since both share the same sentinel key.

    `values`, passed straight through to component_order_key, is what
    actually distinguishes two different canonical sidecar/shared-image
    names sharing the same top-level key (e.g. "curl" vs "nginx-
    unprivileged", both under "global") — omitted, every such pair ties
    and is never flagged as out of order against each other, exactly as
    before."""
    violations = []
    # names[1:] is deliberately one element shorter than names -- this pairs
    # each name with its immediate successor (len(names) - 1 pairs), not a
    # same-length zip -- strict=True would raise on every real call.
    for a, b in pairwise(names):
        if component_order_key(b, deps, key_order, canonical_names, values) < component_order_key(
            a, deps, key_order, canonical_names, values
        ):
            violations.append((a, b))
    return violations


def insertion_index(new_key: int | tuple[int, ...], existing_keys: list):
    """The index into `existing_keys` (each a component_order_key result,
    in their current order) where an item with new_key should be inserted
    to keep the sequence in non-decreasing key order: the first position
    whose existing key is strictly greater, or the end if there is none
    (also what happens when every existing item shares the same
    "unmatched" sentinel key — a genuinely new component is never shoved
    ahead of them without evidence it belongs there)."""
    for i, k in enumerate(existing_keys):
        if k > new_key:
            return i
    return len(existing_keys)


def changes_section_bounds(lines: list[str]) -> tuple[int | None, int]:
    """(changes_idx, section_end) for the "## Changes" heading in
    `lines` — changes_idx is None (with section_end == len(lines)) if
    the heading doesn't exist yet at all; otherwise section_end is the
    index of the next "## " heading after it, or len(lines) if "##
    Changes" is the last section in the doc."""
    changes_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## Changes":
            changes_idx = i
            break
    if changes_idx is None:
        return None, len(lines)
    section_end = len(lines)
    for i in range(changes_idx + 1, len(lines)):
        if re.match(r"^##\s+\S", lines[i]):
            section_end = i
            break
    return changes_idx, section_end


def parse_upgrade_doc_changes_blocks(text: str):
    """(heading, start, end) for every "### ..." item directly under the
    "## Changes" section of an upgrade doc — start is the heading line's
    0-based index, end is exclusive (the next "### " heading, the next
    "## " heading, or EOF). A "#### ..." (H4) sub-heading nested inside a
    block (e.g. "#### Action required") is part of that block, not a
    block of its own — the regex requires exactly 3 "#" immediately
    followed by whitespace, which a 4th "#" fails. Returns [] if the doc
    has no "## Changes" section at all."""
    lines = text.splitlines(keepends=True)
    changes_idx, section_end = changes_section_bounds(lines)
    if changes_idx is None:
        return []

    heading_indices = [i for i in range(changes_idx + 1, section_end) if CHANGES_BLOCK_HEADING_RE.match(lines[i])]
    blocks = []
    for j, start in enumerate(heading_indices):
        end = heading_indices[j + 1] if j + 1 < len(heading_indices) else section_end
        blocks.append(
            {
                "heading": match_located_line(CHANGES_BLOCK_HEADING_RE, lines[start]).group(1),
                "start": start,
                "end": end,
            }
        )
    return blocks


def sort_upgrade_doc_rows(text: str, deps: list, values: dict, canonical_names: dict | None = None):
    """Reorder the "Component versions" table's rows (physically, in the
    text) to match values.yaml's own top-level key order — see
    values_key_order/component_order_key. canonical_names, when given,
    lets a bare "global" shared-image row (e.g. "nginx-unprivileged")
    sort by its own real values.yaml position instead of always last —
    see component_order_key's own docstring. Returns (new_text, moved)
    where moved is [(name, old_position, new_position)] (1-based, among
    just the table's own rows) for every row whose position actually
    changed — empty (and text returned unchanged) if the table already
    matches, or has fewer than 2 rows to meaningfully order. Row CONTENT
    is never touched, only which physical line slot it occupies."""
    rows = parse_upgrade_doc_rows(text)
    if len(rows) < 2:
        return text, []

    key_order = values_key_order(values)
    names = [row["name"] for row in rows]
    order = sorted(
        range(len(names)), key=lambda i: component_order_key(names[i], deps, key_order, canonical_names, values)
    )
    moved = [(names[i], i + 1, slot + 1) for slot, i in enumerate(order) if i != slot]
    if not moved:
        return text, []

    lines = text.splitlines(keepends=True)
    slots = [row["line_index"] for row in rows]
    original_lines = [lines[slot] for slot in slots]
    for slot, i in zip(slots, order, strict=True):
        lines[slot] = original_lines[i]
    return "".join(lines), moved


def sort_changes_blocks(text: str, deps: list, values: dict, canonical_names: dict | None = None):
    """Reorder the "## Changes" section's "### ..." blocks (each block's
    full text, heading through its last line before the next block) to
    match values.yaml's own top-level key order — the same rule
    sort_upgrade_doc_rows applies to table rows (see canonical_names'
    own docstring there for the "global" shared-image case this also
    fixes). Returns (new_text, moved) — moved is [(heading, old_position,
    new_position)] (1-based) for every block that moved; empty (text
    unchanged) if already in order or fewer than 2 blocks exist."""
    blocks = parse_upgrade_doc_changes_blocks(text)
    if len(blocks) < 2:
        return text, []

    key_order = values_key_order(values)
    headings = [b["heading"] for b in blocks]
    order = sorted(
        range(len(headings)), key=lambda i: component_order_key(headings[i], deps, key_order, canonical_names, values)
    )
    moved = [(headings[i], i + 1, slot + 1) for slot, i in enumerate(order) if i != slot]
    if not moved:
        return text, []

    lines = text.splitlines(keepends=True)
    original_texts = ["".join(lines[b["start"] : b["end"]]) for b in blocks]
    new_texts = [original_texts[i] for i in order]

    prefix = "".join(lines[: blocks[0]["start"]])
    suffix = "".join(lines[blocks[-1]["end"] :])
    return prefix + "".join(new_texts) + suffix, moved


def parse_values_delta_sections(text: str):
    """(heading, start, end) for every top-level "## ..." heading in a
    values-deltas.md doc — start is the heading line's 0-based index,
    end is exclusive (the next "## " heading, or EOF). Unlike parse_
    upgrade_doc_changes_blocks (which only looks INSIDE one umbrella
    "## Changes" heading for its own "### ..." sub-blocks), values-
    deltas.md has no such umbrella — every component's own section is
    already a top-level "## " heading (e.g. "## KISS 2.2.4 → 3.0.0 —
    required edits", "## PABC 1.1.0 → 1.1.1 no values changes") — so
    this scans the whole document. Content before the first "## "
    heading (the doc's own "# Values deltas — ..." H1 title, and any
    intro prose) is never part of any section this returns."""
    lines = text.splitlines(keepends=True)
    heading_indices = [i for i, line in enumerate(lines) if VALUES_DELTA_SECTION_HEADING_RE.match(line)]
    sections = []
    for j, start in enumerate(heading_indices):
        end = heading_indices[j + 1] if j + 1 < len(heading_indices) else len(lines)
        sections.append(
            {
                "heading": match_located_line(VALUES_DELTA_SECTION_HEADING_RE, lines[start]).group(1),
                "start": start,
                "end": end,
            }
        )
    return sections


def sort_values_delta_sections(text: str, deps: list, values: dict, canonical_names: dict | None = None):
    """Reorder values-deltas.md's own top-level "## ..." sections (each
    section's full text, heading through its last line before the next
    section) to match values.yaml's own top-level key order — the same
    rule sort_upgrade_doc_rows/sort_changes_blocks apply to -upgrade.md's
    own rows/Changes blocks (see canonical_names' own docstring there
    for the "global" shared-image case this also fixes). A hand-written
    section is reordered exactly like an auto-generated one — its own
    CONTENT is never touched, only which physical position it occupies,
    the same guarantee sort_changes_blocks already gives -upgrade.md's
    own hand-written "### ..." blocks. Returns (new_text, moved) — moved
    is [(heading, old_position, new_position)] (1-based) for every
    section that moved; empty (text unchanged) if already in order or
    fewer than 2 sections exist."""
    sections = parse_values_delta_sections(text)
    if len(sections) < 2:
        return text, []

    key_order = values_key_order(values)
    headings = [s["heading"] for s in sections]
    order = sorted(
        range(len(headings)), key=lambda i: component_order_key(headings[i], deps, key_order, canonical_names, values)
    )
    moved = [(headings[i], i + 1, slot + 1) for slot, i in enumerate(order) if i != slot]
    if not moved:
        return text, []

    lines = text.splitlines(keepends=True)
    # Normalized to a single trailing newline (no blank line) before
    # rejoining — a section's own ORIGINAL trailing blank-line count is
    # meaningless once reordered (the very last section in the file, in
    # particular, always originally had none, since there's nothing
    # after it to separate from); "\n".join below reinstates exactly one
    # blank line between every section regardless of slot.
    original_texts = ["".join(lines[s["start"] : s["end"]]).rstrip("\n") + "\n" for s in sections]
    new_texts = [original_texts[i] for i in order]

    prefix = "".join(lines[: sections[0]["start"]])
    suffix = "".join(lines[sections[-1]["end"] :])
    body = "\n".join(new_texts)
    if suffix:
        body += "\n"
    return prefix + body + suffix, moved
