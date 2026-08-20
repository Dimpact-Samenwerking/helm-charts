"""Upgrade-doc parsing/matching helpers shared by verify-podiumd.py's
docs-consistency check and set-doc-baseline.py's version-correction pass."""
import re


def normalize_version(v):
    return v.lstrip("vV") if v else v


def normalize_name(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def words_of(s):
    return [w for w in re.split(r"[^a-zA-Z0-9]+", s.lower()) if w]


def extract_target_version(cell):
    """Pull the target (right-hand) version out of a markdown table cell like
    "5.0.2 → 5.4.3" or "1.0.297 (unchanged)" or "`0.0.92`"."""
    cell = cell.strip()
    m = re.search(r"(?:→|->)\s*`?([A-Za-z0-9][\w.\-]*)", cell)
    if m:
        return m.group(1)
    m = re.match(r"`?([A-Za-z0-9][\w.\-]*)", cell)
    return m.group(1) if m else None


def extract_source_version(cell):
    """Pull the source (left-hand) version out of the same kind of cell —
    equal to the target when the cell has no arrow (e.g. "1.0.297 (unchanged)")."""
    cell = cell.strip()
    m = re.search(r"`?([A-Za-z0-9][\w.\-]*)`?\s*(?:→|->)", cell)
    if m:
        return m.group(1)
    m = re.match(r"`?([A-Za-z0-9][\w.\-]*)", cell)
    return m.group(1) if m else None


def parse_upgrade_doc_rows(text):
    """Every row of the "Component versions" table — whichever components
    that release actually changed, not a fixed list. Each row carries its
    0-based `line_index` in `text` for callers that need to rewrite it."""
    rows = []
    for i, line in enumerate(text.splitlines()):
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0].lower() == "component":
            continue
        if all(re.match(r"^:?-+:?$", c) for c in cells):
            continue
        rows.append({
            "line_index": i,
            "name": cells[0],
            "app_source": extract_source_version(cells[1]),
            "app": extract_target_version(cells[1]),
            "chart_source": extract_source_version(cells[2]),
            "chart": extract_target_version(cells[2]),
        })
    return rows


def match_dependency(text, deps):
    """Fuzzy-match a doc's free-form component name (e.g. "ZAC
    (Zaakafhandelcomponent)") against Chart.yaml dependencies by name/alias,
    ignoring case and punctuation — so any component the doc mentions is
    matched, not just a hardcoded set."""
    norm_text = normalize_name(text)
    best = None
    for dep in deps:
        for candidate in filter(None, [dep.get("name"), dep.get("alias")]):
            norm_c = normalize_name(candidate)
            if norm_c and norm_c in norm_text and (best is None or len(norm_c) > len(best[1])):
                best = (dep, norm_c)
    return best[0] if best else None


def image_tag(values, *path):
    node = values
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def canonical_version_cell(actual_source, actual_target):
    """A "Component versions" table cell in the established style:
    "<target> (unchanged)" when source==target, else "<source> → <target>"."""
    if normalize_version(actual_source) == normalize_version(actual_target):
        return f"{actual_target} (unchanged)"
    return f"{actual_source} → {actual_target}"


VERSION_PAIR_RE = re.compile(
    r"(?P<source>[A-Za-z0-9][\w.\-]*)\s*(?P<arrow>→|->)\s*(?P<target>[A-Za-z0-9][\w.\-]*)"
)


def find_preceding_comment_line(lines, entry_line_index):
    """Index of the closest comment line above entry_line_index that states
    a "<source> -> <target>" version pair, or None — stops at the first
    blank/non-comment line, so it doesn't reach into the previous entry's
    comment."""
    j = entry_line_index - 1
    while j >= 0 and lines[j].strip().startswith("#"):
        if VERSION_PAIR_RE.search(lines[j]):
            return j
        j -= 1
    return None


def replace_version_pair(line, new_source, new_target):
    """Replace the first "<source> -> <target>" (or "→") pair in line with
    new_source/new_target, preserving everything else (the "# <Name> — "
    prefix, arrow style, trailing newline)."""
    def repl(m):
        return f"{new_source} {m.group('arrow')} {new_target}"
    new_line, count = VERSION_PAIR_RE.subn(repl, line, count=1)
    return new_line if count else line


def actual_app_version(values, values_key):
    """The app version currently pinned for a component, trying the
    single-image ("<key>.image.tag") and the frontend/backend lockstep
    shape in turn — the two conventions seen across podiumd's components."""
    for suffix in ((), ("frontend",), ("backend",)):
        tag = image_tag(values, values_key, *suffix, "image", "tag")
        if tag:
            return tag.split("@")[0]
    return None


def find_image_tag_paths(node, path=()):
    """Yield (path, tag) for every "image: {tag: ...}" block anywhere in a
    values tree, keyed by its full path — e.g. ("zac", "opa") for
    zac.opa.image.tag. Structural, so it finds sidecars too, not just
    top-level Chart.yaml dependencies."""
    if isinstance(node, dict):
        image = node.get("image")
        if isinstance(image, dict) and image.get("tag"):
            yield path, image["tag"]
        for key, value in node.items():
            if key == "image":
                continue
            yield from find_image_tag_paths(value, path + (str(key),))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from find_image_tag_paths(item, path + (str(i),))


def resolve_entry_path(entry_name, paths):
    """Match an images-manifest entry name (e.g. "zgw-office-addin-frontend")
    to a values-tree path (e.g. ("zgw-office-addin", "frontend")) by comparing
    word-split, concatenated path segments — no hardcoded name list.

    The innermost path segment must match the entry's last word: without that,
    sibling paths sharing a coincidental prefix (e.g. zac.solr-operator.solr
    vs zac.solr-operator.zookeeper-operator.zookeeper — both start with
    "zac"+"solr"+"operator") are indistinguishable by substring matching alone."""
    entry_words = words_of(entry_name)
    if not entry_words:
        return None
    norm_entry = "".join(entry_words)

    best = None
    for path in paths:
        path_words = [w for segment in path for w in words_of(segment)]
        if not path_words or path_words[-1] != entry_words[-1]:
            continue
        norm_path = "".join(path_words)
        if norm_path == norm_entry:
            return path
        if norm_path in norm_entry or norm_entry in norm_path:
            # closest length = least unrelated extra text pulled in by the
            # containment match
            diff = abs(len(norm_path) - len(norm_entry))
            if best is None or diff < best[1]:
                best = (path, diff)
    return best[0] if best else None


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
            similar = bool(add_keys and rem_keys and
                            len(add_keys & rem_keys) / len(add_keys | rem_keys) >= 0.3)
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
    the same helpers."""
    items = []
    in_changes = False
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
        if not m:
            continue
        rest = m.group(1)
        app_source = extract_source_version(rest)
        app_target = extract_target_version(rest)
        chart_m = re.search(r"\(chart\s+([^)]+)\)", rest)
        chart_source = extract_source_version(chart_m.group(1)) if chart_m else None
        chart_target = extract_target_version(chart_m.group(1)) if chart_m else None
        name = rest
        if app_source:
            idx = rest.find(app_source)
            if idx > 0:
                name = rest[:idx].strip()
        items.append({"name": name, "app_source": app_source, "app": app_target,
                      "chart_source": chart_source, "chart": chart_target})
    return items
