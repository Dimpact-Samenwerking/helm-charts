"""Upgrade-doc parsing/matching helpers shared by verify-podiumd.py's
docs-consistency check and bump-doc-baseline.py's version-correction pass."""
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


def actual_app_version(values, values_key):
    """The app version currently pinned for a component, trying the
    single-image ("<key>.image.tag") and the frontend/backend lockstep
    shape in turn — the two conventions seen across podiumd's components."""
    for suffix in ((), ("frontend",), ("backend",)):
        tag = image_tag(values, values_key, *suffix, "image", "tag")
        if tag:
            return tag.split("@")[0]
    return None
