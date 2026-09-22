"""The images-manifest's own "# Changes:" (or bare "# Changes:") header
block: finding it (find_images_manifest_changes_header), enumerating its
numbered items (find_images_manifest_changes_items), keeping their
numbers and the header's own leading count word gapless and correct
(renumber_images_manifest_changes_items, images_manifest_changes_count_
word), creating the header from scratch when a manifest has lost it
(ensure_images_manifest_changes_header), ordering a new item against
values.yaml's own component order (images_manifest_order_key), and
inserting one at its correct position (insert_images_manifest_header_
item). Shared by lib.component_docs's own update_images_manifest/
remove_component_from_images_manifest, lib.image.docs, lib.docs_
consistency, and fix-doc-consistency's own add_missing_images_manifest_
entries. Split out of the former flat lib/component_docs.py, now the
lib.component_docs package."""

import re

from lib.upgradedoc.sorting_and_ordering import insertion_index
from lib.upgradedoc.sorting_and_ordering import values_tree_position
from lib.upgradedoc.string_and_parsing_basics import match_dependency_excluding_sidecar_names

NUMBER_WORDS = [
    "Zero",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
]
CHANGES_HEADER_RE = re.compile(r"^(?P<indent>#\s*)(?P<count_word>\w+)\s+changes?:\s*$", re.IGNORECASE)
# A plain "# Changes:" images-manifest header with no leading count word at
# all — CHANGES_HEADER_RE requires one ("# Twenty Two changes:"), but a
# hand-curated header (this chart's own real images-4.9.0.yaml, extensively
# rewritten with rich per-item prose) may never have picked that convention
# up, and IMAGES_STUB_TEMPLATE's own fresh "# Changes:" line never has one
# either. See find_images_manifest_changes_header, the shared "recognize
# either shape" lookup.
BARE_CHANGES_HEADER_RE = re.compile(r"^(?P<indent>#\s*)[Cc]hanges:\s*$")
CHANGES_ITEM_RE = re.compile(r"^#\s*(?P<num>\d+)\.\s+(?P<rest>.+)$")
# The intro line IMAGES_STUB_TEMPLATE's own "# Changes:\n#\n" header
# always follows immediately — see ensure_images_manifest_changes_header,
# which uses this as its own insertion anchor when a file has lost (or
# never had) that header.
IMAGES_MANIFEST_INTRO_RE = re.compile(r"^#\s*Images new or changed in podiumd\b.*$", re.IGNORECASE)


def find_images_manifest_changes_header(lines):
    """(header_idx, header_has_count) for the images-manifest's own "#
    Changes:" header — matching EITHER CHANGES_HEADER_RE's counted form
    ("# Twenty One changes:") or BARE_CHANGES_HEADER_RE's plain "#
    Changes:" (no count word at all — the real, hand-curated images-
    4.9.0.yaml header's own actual shape, and IMAGES_STUB_TEMPLATE's own
    fresh one). (None, False) if neither is found anywhere in the file.
    Shared by fix-doc-consistency's own header-item insertion/reordering
    and update_images_manifest below — before this was factored out,
    update_images_manifest checked CHANGES_HEADER_RE alone, so it never
    recognized (and so never updated) a bare "# Changes:" header — the
    exact shape both the real hand-curated file and a freshly-stubbed
    one actually have."""
    for i, line in enumerate(lines):
        if CHANGES_HEADER_RE.match(line):
            return i, True
        if BARE_CHANGES_HEADER_RE.match(line):
            return i, False
    return None, False


def ensure_images_manifest_changes_header(lines):
    """Create the images-manifest's own bare "# Changes:\n#\n" header
    (see find_images_manifest_changes_header/IMAGES_STUB_TEMPLATE),
    right after the "# Images new or changed in podiumd ... vs ..."
    intro line, for a file that has NO header at all yet — a no-op if
    one already exists (either shape).

    insert_images_manifest_header_item's own docstring documents it as
    a no-op when the file has no header at all — by design, it only
    ever inserts an item INTO an existing header, never creates one from
    scratch. That meant a file that somehow lost its header (or never
    got one in the first place) could never have it added back by any
    later fix-doc-consistency run, silently, with no error or warning —
    real, observed case: images-4.9.1.yaml gained 5 real entries (redis,
    3 openbao sidecars, zac's own otel sidecar) across several runs, each
    with a correct per-entry "#" comment (proving path_display_name's own
    component lookup worked fine), but the file's "# Changes:" header
    itself was simply never there for any of those insertions to land
    in — so none of them ever got a summary-list item either, and
    nothing surfaced that gap until lib.docs_consistency's own "has an
    entry but no mention in the '# Changes:' list" check was pointed at
    it directly.

    Callers should call this before every insert_images_manifest_header_
    item call site (both the per-entry pass and the backfill pass in
    fix-doc-consistency's own add_missing_images_manifest_entries) —
    it's cheap and idempotent, so unconditionally ensuring first is
    simpler than threading "did we already ensure this run" state
    through both call sites.

    Falls through as a no-op (never crashes) if the intro line itself
    isn't found either — a defensive fallback for a manifest shaped
    differently than IMAGES_STUB_TEMPLATE's own convention; nothing
    currently produces that shape, but this must never be where a
    caller's whole run aborts."""
    header_idx, _has_count = find_images_manifest_changes_header(lines)
    if header_idx is not None:
        return
    for i, line in enumerate(lines):
        if IMAGES_MANIFEST_INTRO_RE.match(line.strip()):
            insert_at = i + 1
            if insert_at < len(lines) and lines[insert_at].strip() == "#":
                insert_at += 1
            lines[insert_at:insert_at] = ["# Changes:\n", "#\n"]
            return


def find_images_manifest_changes_items(lines):
    """(header_idx, header_has_count, item_indices) — item_indices is
    every "#   N. ..." line's own index (see CHANGES_ITEM_RE), in
    current top-to-bottom document order, scoped to the "# Changes:"
    header's own block (see find_images_manifest_changes_header). (None,
    False, []) if the header doesn't exist. Shared by every function
    that needs to enumerate this list's own items without re-deriving
    the same block-scanning loop each time."""
    header_idx, header_has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return None, False, []
    item_indices = []
    for i in range(header_idx + 1, len(lines)):
        if lines[i].rstrip("\n") == "#" or not lines[i].startswith("#"):
            break
        if CHANGES_ITEM_RE.match(lines[i]):
            item_indices.append(i)
    return header_idx, header_has_count, item_indices


def images_manifest_changes_count_word(total):
    """The header's own leading count word for `total` items — a single
    NUMBER_WORDS entry (Zero..Fifteen) when it has one, else the bare
    numeral string; CHANGES_HEADER_RE's own count_word group is a single
    \\w+ token, so a two-word compound like "Twenty Six" is never
    produced — paired with "change"/"changes" for the trailing noun.
    Shared by every function that rewrites this header line so the
    "what word for what count" rule is never reimplemented twice."""
    count_word = NUMBER_WORDS[total] if total < len(NUMBER_WORDS) else str(total)
    noun = "change" if total == 1 else "changes"
    return count_word, noun


def renumber_images_manifest_changes_items(lines):
    """Renumber the images-manifest's own "# Changes:" numbered item
    list to a gapless 1..N sequence matching CURRENT top-to-bottom
    document order, and update the header's own leading count word (see
    images_manifest_changes_count_word) to match — regardless of
    whether anything else about the list changed. insert_images_
    manifest_header_item/dedupe_images_manifest_changes_items/sort_
    images_manifest_changes_items each already renumber correctly as a
    side effect of their OWN specific operation (inserting one item,
    removing a duplicate, reordering) — but none of them fires at all
    when the list is already duplicate-free and already in the right
    RELATIVE order, yet still has the wrong ABSOLUTE numbers (real case:
    a human hand-removes a stale item's own block without renumbering
    everything after it, leaving a gap like "...6. ... 8. ..." with no
    "7." at all). This is the one pass that always fixes that, on its
    own, independent of anything else. Mutates `lines` in place. Returns
    True if anything was renumbered (either an item's own number, or
    the header's count word), False if the list was already exactly
    1..N (or the header/list doesn't exist at all)."""
    header_idx, header_has_count, item_indices = find_images_manifest_changes_items(lines)
    if header_idx is None or not item_indices:
        return False

    changed = False
    for slot, idx in enumerate(item_indices):
        expected = slot + 1
        m = CHANGES_ITEM_RE.match(lines[idx])
        if int(m.group("num")) != expected:
            lines[idx] = CHANGES_ITEM_RE.sub(lambda mm, n=expected: f"#   {n}. {mm.group('rest')}", lines[idx])
            changed = True

    if header_has_count:
        count_word, noun = images_manifest_changes_count_word(len(item_indices))
        header_m = CHANGES_HEADER_RE.match(lines[header_idx])
        new_header = f"{header_m.group('indent')}{count_word} {noun}:\n"
        if lines[header_idx] != new_header:
            lines[header_idx] = new_header
            changed = True

    return changed


def images_manifest_order_key(key_order, values_key, is_sidecar, values=None):
    """(index-in-key_order, 0-or-1-for-sidecar) sort key for an images-
    manifest "# Changes:" item belonging to `values_key` — an unknown
    values_key (not in key_order at all) sorts LAST, never crashes.
    Shared by every caller that inserts/positions a header item relative
    to values.yaml's own top-level component order (update_images_
    manifest below, lib.image.docs.update_image_manifest, fix-doc-
    consistency's own add_missing_images_manifest_entries) so they can
    never independently drift on what "in order" means.

    `values_key` may ALSO be a full values-tree PATH TUPLE, not just its
    own bare top-level-key string — when it is, and `values` (the real
    parsed values.yaml dict) is also given, this resolves the item's own
    FULL nested position (see lib.upgradedoc.values_tree_position) once
    it's past its own top-level index, rather than tying every non-
    primary item under the same top-level key to one identical key —
    real bug this fixes: every "global.images.*" item (nginx/curl/
    busybox/redis, all genuinely different, independently-orderable
    images) used to tie at the exact same (values_key_index, is_
    sidecar), leaving their own relative order to whatever a stable
    sort happened to preserve. A bare STRING values_key (the historical
    shape), or values=None, keeps the exact prior top-level-only
    behavior unchanged — every existing caller not yet passing a real
    path/values is never worse off than before."""
    path = values_key if isinstance(values_key, tuple) else (values_key,)
    try:
        idx = key_order.index(path[0])
    except ValueError:
        return (len(key_order), 1 if is_sidecar else 0)
    if values is not None and len(path) > 1:
        return (idx, *values_tree_position(values, path)[1:])
    return (idx, 1 if is_sidecar else 0)


def _images_manifest_changes_block_end(lines, header_idx):
    """First index right after the "# Changes:" block's own last comment
    line, scanning from header_idx (same block-scan condition find_
    images_manifest_changes_items uses for its own item_indices scan)."""
    block_end = header_idx + 1
    for i in range(header_idx + 1, len(lines)):
        if lines[i].rstrip("\n") == "#" or not lines[i].startswith("#"):
            break
        block_end = i + 1
    return block_end


def insert_images_manifest_header_item(lines, deps, key_order, new_key, item_text):
    """Insert "#   N. <item_text>" into the images-manifest's own "#
    Changes:" header list (see find_images_manifest_changes_header) at
    the position matching new_key relative to what's already there (see
    lib.upgradedoc.component_order_key/insertion_index — the SAME
    ordering convention upgrade.md's own table rows/Changes sections
    use, via images_manifest_order_key above), renumbering every
    subsequent item. An existing item that can't be resolved to a real
    dependency (free-form prose, matched via match_dependency_excluding_
    sidecar_names the same way check_images_manifest_format's own
    Changes-item check does) sorts last for THIS purpose only — never
    causes it to move. Mutates `lines` in place; a no-op if the file has
    no header at all. Only rewrites the header line's own leading count
    word if it already had one (see header_has_count) — never invents
    one for a bare "# Changes:" label.

    Renumbering after the raw insert goes through renumber_images_
    manifest_changes_items rather than a relative "+1 to every existing
    item's OWN current number" shift — the latter silently preserves
    (just shifted) any gap or wrong number the list already had before
    this call, since it never computes each item's correct ABSOLUTE
    position from scratch; the former always does, fixing a pre-existing
    drift as a side effect of this insert instead of just adding to it.

    Shared by update_images_manifest below (a real component's own app+
    chart bump — the common case update-component-version/update-image-
    version write) and fix-doc-consistency's own add_missing_images_
    manifest_entries (a changed image with no entry/header item at all
    yet) — before this was factored out here, update_images_manifest had
    its OWN separate, append-only version (new items always landed at
    the very end, out of values.yaml's own order, only ever fixed by a
    LATER fix-doc-consistency run), which could silently drift from this
    one on what "correct" position even means."""
    header_idx, _header_has_count, item_indices = find_images_manifest_changes_items(lines)
    if header_idx is None:
        return

    block_end = _images_manifest_changes_block_end(lines, header_idx)

    item_keys = []
    for idx in item_indices:
        m = CHANGES_ITEM_RE.match(lines[idx])
        item_dep = match_dependency_excluding_sidecar_names(m.group("rest"), deps) if m else None
        if item_dep is None:
            item_keys.append((len(key_order), 0))
            continue
        item_keys.append(images_manifest_order_key(key_order, item_dep.get("alias", item_dep["name"]), False))

    insert_slot = insertion_index(new_key, item_keys)
    insert_line = item_indices[insert_slot] if insert_slot < len(item_indices) else block_end
    # The number here is only ever a placeholder — renumber_images_
    # manifest_changes_items (below) overwrites it, and every OTHER
    # item's own number, with each one's correct final position.
    lines.insert(insert_line, f"#   0. {item_text}\n")

    renumber_images_manifest_changes_items(lines)
