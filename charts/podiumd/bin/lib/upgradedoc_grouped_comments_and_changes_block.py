"""Preceding-comment lookup (plain and dependency-grouped), a
Changes block's own "### <name> <version>" parsing, the generic
baseline/current key-diff primitives (diff_keys/flatten_leaf_keys/
pair_renames) they're built from, and path_display_name."""

import re

from lib.chart.registered_paths import is_primary_image_path
from lib.upgradedoc_string_and_parsing_basics import (
    extract_source_version,
    extract_target_version,
)

BARE_CHART_CLAUSE_RE = re.compile(
    r"\bchart\s+`?[A-Za-z0-9][\w.\-]*`?\s*(?:→|->)\s*`?[A-Za-z0-9][\w.\-]*`?", re.IGNORECASE
)


VERSION_SPEC_RE = re.compile(
    r"[A-Za-z0-9][\w.\-]*\s*(?:→|->)\s*[A-Za-z0-9][\w.\-]*"
    r"|[A-Za-z0-9][\w.\-]*\s*\((?:new|unchanged|digest changed)\)"
)


def find_preceding_comment(lines, entry_line_index):
    """The comment line(s) immediately above a "- name: ..." line, e.g.
    "# ZAC OPA sidecar — 1.17.1-static -> 1.19.0-static" right above the opa
    entry — stops at the first blank/non-comment line, so it doesn't reach
    back into the previous entry's comment."""
    comment_lines = []
    j = entry_line_index - 1
    while j >= 0 and lines[j].strip().startswith("#"):
        comment_lines.insert(0, lines[j].strip())
        j -= 1
    return " ".join(comment_lines)


def find_preceding_comment_line(lines, entry_line_index):
    """Index of the closest comment line above entry_line_index that
    states a version spec — a "<source> -> <target>" pair, OR a bare
    "<version> (new)"/"(unchanged)"/"(digest changed)" (see VERSION_
    SPEC_RE) — or None. Stops at the first blank/non-comment line, so it
    doesn't reach into the previous entry's comment.

    Real bug this closes: only recognizing an ARROW pair used to mean a
    comment ALREADY correctly written in the bracketed "(new)"/
    "(unchanged)"/"(digest changed)" form (no arrow at all) was never
    even recognized as a comment here in the first place — confirmed
    live: images-4.9.1.yaml's own keycloak-operator - python sidecar,
    already correctly reading "(digest changed)", was reported
    "unresolved" by every caller here forever, not because its own
    version was actually wrong, but because this function itself could
    never even SEE it to compare against."""
    j = entry_line_index - 1
    while j >= 0 and lines[j].strip().startswith("#"):
        if VERSION_SPEC_RE.search(lines[j]):
            return j
        j -= 1
    return None


def find_grouped_preceding_comment(lines, entries, entry_line_indices, index, same_group):
    """The comment describing entries[index]'s version bump: its own
    directly-preceding comment if it has one, else — when a component's
    images are listed as one contiguous block sharing a single comment
    (e.g. zgw-office-addin's frontend + backend entries, separated by a
    blank line, both under one "# ZGW Office Add-in — ..." comment) — the
    immediately preceding entry's comment, but only when that entry is in
    the same group as this one. A sibling with its own distinct comment
    (e.g. ZAC's main entry vs. its OPA sidecar entry — both under the same
    top-level "zac" values key, but independently versioned and each with
    its own comment) is never overridden by this fallback, since
    find_preceding_comment already finds an entry's own comment before
    this fallback is even considered.

    same_group(entry, other_entry) -> True when the two entries are part
    of one shared-comment block — same top-level component AND the same
    declared "version" (evidence of one lockstep bump across images, not
    just a coincidentally-shared values-tree prefix like zac vs zac.opa)."""
    comment = find_preceding_comment(lines, entry_line_indices[index])
    if comment or index == 0:
        return comment
    if not same_group(entries[index], entries[index - 1]):
        return ""
    return find_grouped_preceding_comment(lines, entries, entry_line_indices, index - 1, same_group)


def find_grouped_preceding_comment_line(lines, entries, entry_line_indices, index, same_group):
    """Same grouping rule as find_grouped_preceding_comment, for callers
    that need the matched comment's line index (to rewrite it in place)
    rather than its text — built on find_preceding_comment_line's
    arrow-bearing-line convention instead of find_preceding_comment's."""
    comment_idx = find_preceding_comment_line(lines, entry_line_indices[index])
    if comment_idx is not None or index == 0:
        return comment_idx
    if not same_group(entries[index], entries[index - 1]):
        return None
    return find_grouped_preceding_comment_line(lines, entries, entry_line_indices, index - 1, same_group)


def diff_keys(baseline_node, current_node, path=()):
    """Yield ("added"|"removed", path) for the SHALLOWEST differing keys
    between two values subtrees — if a whole block is new or gone, report it
    once at that level rather than recursing into every leaf underneath it.
    This matches how values-deltas.md docs actually document changes (e.g.
    "the whole zac.brpApi.protocollering block was redesigned", not a
    leaf-by-leaf listing). Scalar-vs-scalar value changes (same key, new
    value) are not add/remove/rename and are not reported."""
    if not isinstance(baseline_node, dict) or not isinstance(current_node, dict):
        return
    baseline_keys = set(baseline_node.keys())
    current_keys = set(current_node.keys())
    for key in current_keys - baseline_keys:
        yield "added", path + (key,)
    for key in baseline_keys - current_keys:
        yield "removed", path + (key,)
    for key in baseline_keys & current_keys:
        yield from diff_keys(baseline_node[key], current_node[key], path + (key,))


def flatten_leaf_keys(node):
    """All leaf key names anywhere under a subtree, used to measure how
    similar two blocks are (for rename detection) — not full paths, just the
    set of innermost key names, so "host"/"user"/"password" overlapping
    between an old and new block is a strong rename signal."""
    keys = set()
    if isinstance(node, dict):
        for key, value in node.items():
            keys.add(key)
            keys |= flatten_leaf_keys(value)
    elif isinstance(node, list):
        for item in node:
            keys |= flatten_leaf_keys(item)
    return keys


def pair_renames(added, removed, baseline_node, current_node):
    """Pair an added and a removed key at the same parent path into a rename
    candidate when their subtrees share enough leaf key names (e.g.
    mi.sftp -> mi.transfer, both containing host/user/password) — otherwise
    they're reported as an unrelated add and remove."""
    renamed, added_left, removed_left = [], list(added), list(removed)

    def get(node, path):
        for key in path:
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node

    for add_path in list(added_left):
        for rem_path in list(removed_left):
            if add_path[:-1] != rem_path[:-1]:
                continue
            add_val = get(current_node, add_path)
            rem_val = get(baseline_node, rem_path)
            add_keys, rem_keys = flatten_leaf_keys(add_val), flatten_leaf_keys(rem_val)
            similar = bool(add_keys and rem_keys and len(add_keys & rem_keys) / len(add_keys | rem_keys) >= 0.3)
            same_scalar = not isinstance(add_val, (dict, list)) and add_val == rem_val
            if similar or same_scalar:
                renamed.append((rem_path, add_path))
                added_left.remove(add_path)
                removed_left.remove(rem_path)
                break
    return renamed, added_left, removed_left


def parse_changes_block(text):
    """Parse the "# Changes:" numbered-list block in an images manifest's
    header comment, e.g.:
        #   1. ZAC (Zaakafhandelcomponent) 5.0.2 -> 5.4.3 (chart 1.0.297, unchanged).
        #   2. ZGW Office Add-in v0.9.313 -> 0.11.0 (chart 0.0.89 -> 0.0.92).
    into the same shape as parse_upgrade_doc_rows, so it can be checked with
    the same helpers.

    A wrapped continuation line — indented to roughly the same column the
    item's own text starts at (2+ spaces after "#", e.g. "#      nginx
    sidecar...", vs. an ordinary comment's single-space "# See docs/...")
    — is joined onto its own item's text before parsing name/app/chart
    out of it. Not just a cosmetic nicety: an item whose own
    "<source> -> <target>" pair (or "(chart ...)" span) is itself split
    across the wrap, e.g.
        #   21. nginx-unprivileged (shared global.images.nginx anchor, used by every
        #      nginx sidecar in the chart) 1.31.3 -> 1.31.4.
    used to see only line 1 — no arrow pattern there at all, so
    extract_source_version/extract_target_version's own "no arrow found"
    fallback (first word-like token) grabbed the item's own leading word
    "nginx-unprivileged" as a fake version instead, silently truncating
    its name to boot. The 2-space threshold is what actually tells a
    continuation apart from an ordinary single-space "#" comment line
    (a blank "#", or a trailing "# See docs/..." remark right after the
    list with no blank line separating them) — both single-space forms
    end whichever item is currently accumulating, the same way a new
    numbered line does, rather than being swallowed into it."""
    items = []
    in_changes = False
    current = None  # raw text accumulated so far for the item being parsed
    for line in text.splitlines():
        if not line.startswith("#"):
            if in_changes:
                break
            continue
        if re.match(r"^#\s*Changes:\s*$", line):
            in_changes = True
            continue
        if not in_changes:
            continue

        # "\.\s+" (period, then whitespace) — not "\.\s*" — so a version number
        # like "1.17.1-static" (period immediately followed by a digit) on an
        # indented continuation line is never mistaken for a new list item
        m = re.match(r"^#\s*\d+\.\s+(.+)$", line)
        if m:
            if current is not None:
                items.append(_finalize_changes_item(current))
            current = m.group(1)
            continue

        cont_m = re.match(r"^#\s{2,}(\S.*)$", line)
        if cont_m and current is not None:
            current += " " + cont_m.group(1)
        elif current is not None:
            items.append(_finalize_changes_item(current))
            current = None

    if current is not None:
        items.append(_finalize_changes_item(current))
    return items


def _finalize_changes_item(rest):
    # extract_source_version/extract_target_version's own [\w.\-]* token
    # regex treats "." as a valid version character (needed for "1.31.4"
    # itself) — harmless for a table cell, but a Changes item is free-form
    # PROSE that often ends its own sentence with a period right after the
    # version with nothing else in between (e.g. "... 1.31.3 -> 1.31.4."),
    # which the regex greedily swallows as if it were part of the version.
    # A version never legitimately ends in a literal ".", so stripping one
    # trailing period here is always safe.
    chart_m = re.search(r"\(chart\s+([^)]+)\)", rest)
    chart_source = extract_source_version(chart_m.group(1)) if chart_m else None
    chart_target = extract_target_version(chart_m.group(1)) if chart_m else None

    # A "chart <source> -> <target>" mention written WITHOUT the usual
    # "(chart ...)" parens is the same signal — must never be mistaken for
    # the item's own APP version, whether it's the only version pair
    # present at all (a chart-only bump, e.g. "ECK Stack (kiss-eck) chart
    # 0.19.0 -> 0.20.0 (no image change of its own).") or the FIRST of
    # two pairs in one sentence (e.g. "redis-operator chart 0.25.0 ->
    # 0.26.1, operator image 0.25.0 -> 0.26.0" — the real app pair is the
    # SECOND one). Removed from the text searched for the app version
    # below, so a bracketed chart_m match above still wins if both forms
    # somehow appear (unlikely, but chart_source/chart_target already set
    # from it isn't overwritten).
    app_search_text = rest
    bare_chart_m = BARE_CHART_CLAUSE_RE.search(rest)
    if bare_chart_m:
        if chart_source is None:
            chart_source = extract_source_version(bare_chart_m.group(0))
            chart_target = extract_target_version(bare_chart_m.group(0))
        app_search_text = rest[: bare_chart_m.start()] + " " + rest[bare_chart_m.end() :]

    # extract_source_version/extract_target_version's own "no arrow found"
    # fallback (first word-like token) would otherwise grab whatever text
    # is left over (e.g. "no image change of its own" for a genuinely
    # chart-only item like the ECK Stack example above) as a fake app
    # version — only trust a result when there's a REAL arrow left to find.
    if re.search(r"(?:→|->)", app_search_text):
        app_source = extract_source_version(app_search_text)
        app_target = extract_target_version(app_search_text)
    else:
        app_source = app_target = None

    if app_source:
        app_source = app_source.rstrip(".")
    if app_target:
        app_target = app_target.rstrip(".")
    if chart_source:
        chart_source = chart_source.rstrip(".")
    if chart_target:
        chart_target = chart_target.rstrip(".")

    name = rest
    if app_source:
        idx = app_search_text.find(app_source)
        if idx > 0:
            name = app_search_text[:idx].strip()
    return {
        "name": name,
        "app_source": app_source,
        "app": app_target,
        "chart_source": chart_source,
        "chart": chart_target,
    }


def path_display_name(path, deps, canonical_names):
    """The doc-facing name for a values-tree image path — "<values_key>"
    for a dependency's own primary image (same convention as every
    "component "<key>" changed vs ..." message elsewhere in this check),
    else whatever name canonical_names (canonical_sidecar_row_names's own
    {name: path} mapping — "<values_key> - <basename>" for a sidecar,
    bare "<basename>" for a shared "global" image) maps this exact path
    to. Falls back to the raw dotted path only when neither covers it
    (e.g. an image with no Chart.yaml dependency and no vendored/own
    repository to resolve a basename from at all) — this should be rare
    in practice, never the normal case."""
    by_values_key = {(dep.get("alias") or dep["name"]): dep for dep in deps}
    dep = by_values_key.get(path[0])
    if dep is not None and is_primary_image_path(path, deps):
        return path[0]
    for name, candidate_path in canonical_names.items():
        if candidate_path == path:
            return name
    return ".".join(path)
