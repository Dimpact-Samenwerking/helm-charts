"""Upgrade-doc parsing/matching helpers shared by verify-podiumd's
docs-consistency check and fix-doc-consistency's version-correction pass."""
import re

from lib.chart import COMPONENT_IMAGE_PATHS, get_path, image_paths_for, subchart_app_version, version_paths_for


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


def values_key_order(values):
    """Top-level keys of values.yaml in the order they appear in the file,
    top to bottom — yaml.safe_load's mapping is a plain dict, which
    preserves insertion order (Python 3.7+); for a top-level mapping that
    IS the file's own line order. Every doc's "Component versions" table
    and "## Changes" section is expected to mirror this same order, so a
    reader scanning one can find a component at roughly the same "place"
    scanning the other."""
    return list(values.keys()) if isinstance(values, dict) else []


def component_order_key(name, deps, key_order):
    """A doc item's (table row name, or "### ..." Changes heading) sort
    position: (values_key_index, is_sidecar) — values_key_index is the
    values.yaml top-level key match_dependency resolves `name` to, as its
    index in key_order, or len(key_order) (sorts after every real
    component) when `name` doesn't resolve to a single Chart.yaml
    dependency at all (e.g. a row summarizing several shared-image
    components at once, or free-form prose that doesn't name one).
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
    passes, so "what order should this be in" is answered exactly once."""
    dep = match_dependency(name, deps)
    values_key = dep.get("alias", dep["name"]) if dep else None
    is_sidecar = 1 if " - " in name else 0
    if values_key is None:
        return (len(key_order), is_sidecar)
    try:
        return (key_order.index(values_key), is_sidecar)
    except ValueError:
        return (len(key_order), is_sidecar)


def find_out_of_order_names(names, deps, key_order):
    """[(name_a, name_b), ...] for every ADJACENT pair whose relative order
    contradicts values.yaml's own top-level key order (see
    component_order_key) — checking only adjacent pairs is sufficient to
    catch any out-of-order sequence, since a non-monotonic sequence always
    has at least one adjacent inversion. A name that doesn't resolve to any
    dependency sorts after every real one (see component_order_key) and
    never itself causes a violation against another such name, since both
    share the same sentinel key."""
    violations = []
    for a, b in zip(names, names[1:]):
        if component_order_key(b, deps, key_order) < component_order_key(a, deps, key_order):
            violations.append((a, b))
    return violations


def insertion_index(new_key, existing_keys):
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


CHANGES_BLOCK_HEADING_RE = re.compile(r"^###\s+(.+)$")


def parse_upgrade_doc_changes_blocks(text):
    """(heading, start, end) for every "### ..." item directly under the
    "## Changes" section of an upgrade doc — start is the heading line's
    0-based index, end is exclusive (the next "### " heading, the next
    "## " heading, or EOF). A "#### ..." (H4) sub-heading nested inside a
    block (e.g. "#### Action required") is part of that block, not a
    block of its own — the regex requires exactly 3 "#" immediately
    followed by whitespace, which a 4th "#" fails. Returns [] if the doc
    has no "## Changes" section at all."""
    lines = text.splitlines(keepends=True)
    changes_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## Changes":
            changes_idx = i
            break
    if changes_idx is None:
        return []

    section_end = len(lines)
    for i in range(changes_idx + 1, len(lines)):
        if re.match(r"^##\s+\S", lines[i]):
            section_end = i
            break

    heading_indices = [i for i in range(changes_idx + 1, section_end)
                        if CHANGES_BLOCK_HEADING_RE.match(lines[i])]
    blocks = []
    for j, start in enumerate(heading_indices):
        end = heading_indices[j + 1] if j + 1 < len(heading_indices) else section_end
        blocks.append({
            "heading": CHANGES_BLOCK_HEADING_RE.match(lines[start]).group(1),
            "start": start,
            "end": end,
        })
    return blocks


def sort_upgrade_doc_rows(text, deps, values):
    """Reorder the "Component versions" table's rows (physically, in the
    text) to match values.yaml's own top-level key order — see
    values_key_order/component_order_key. Returns (new_text, moved) where
    moved is [(name, old_position, new_position)] (1-based, among just the
    table's own rows) for every row whose position actually changed —
    empty (and text returned unchanged) if the table already matches, or
    has fewer than 2 rows to meaningfully order. Row CONTENT is never
    touched, only which physical line slot it occupies."""
    rows = parse_upgrade_doc_rows(text)
    if len(rows) < 2:
        return text, []

    key_order = values_key_order(values)
    names = [row["name"] for row in rows]
    order = sorted(range(len(names)), key=lambda i: component_order_key(names[i], deps, key_order))
    moved = [(names[i], i + 1, slot + 1) for slot, i in enumerate(order) if i != slot]
    if not moved:
        return text, []

    lines = text.splitlines(keepends=True)
    slots = [row["line_index"] for row in rows]
    original_lines = [lines[slot] for slot in slots]
    for slot, i in zip(slots, order):
        lines[slot] = original_lines[i]
    return "".join(lines), moved


def sort_changes_blocks(text, deps, values):
    """Reorder the "## Changes" section's "### ..." blocks (each block's
    full text, heading through its last line before the next block) to
    match values.yaml's own top-level key order — the same rule
    sort_upgrade_doc_rows applies to table rows. Returns (new_text, moved)
    — moved is [(heading, old_position, new_position)] (1-based) for every
    block that moved; empty (text unchanged) if already in order or fewer
    than 2 blocks exist."""
    blocks = parse_upgrade_doc_changes_blocks(text)
    if len(blocks) < 2:
        return text, []

    key_order = values_key_order(values)
    headings = [b["heading"] for b in blocks]
    order = sorted(range(len(headings)), key=lambda i: component_order_key(headings[i], deps, key_order))
    moved = [(headings[i], i + 1, slot + 1) for slot, i in enumerate(order) if i != slot]
    if not moved:
        return text, []

    lines = text.splitlines(keepends=True)
    original_texts = ["".join(lines[b["start"]:b["end"]]) for b in blocks]
    new_texts = [original_texts[i] for i in order]

    first_start, last_end = blocks[0]["start"], blocks[-1]["end"]
    prefix = "".join(lines[:first_start])
    suffix = "".join(lines[last_end:])
    return prefix + "".join(new_texts) + suffix, moved


COMPONENT_VERSIONS_HEADING_RE = re.compile(r"^##\s+Component versions\b")


def parse_upgrade_doc_rows(text):
    """Every row of the "## Component versions (... vs ...)" table
    SPECIFICALLY — scoped to that one section (the heading through the
    next "## " heading, or EOF), never any OTHER pipe-table that happens
    to appear elsewhere in the doc (e.g. a component's own subsection
    listing an unrelated settings-migration table, whose own header cell
    like "Setting" isn't literally "Component" either, so an unscoped
    scan would treat it — and every data row under it — as a real
    Component-versions row too, matching nothing in match_dependency and
    getting reported as such). [] if the doc has no such heading at all.
    Each row carries its 0-based `line_index` in `text` for callers that
    need to rewrite it — whichever components that release actually
    changed, not a fixed list."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if COMPONENT_VERSIONS_HEADING_RE.match(line.strip()):
            start = i + 1
            break
    if start is None:
        return []

    end = len(lines)
    for i in range(start, len(lines)):
        if re.match(r"^##\s+\S", lines[i]):
            end = i
            break

    rows = []
    for i in range(start, end):
        line = lines[i]
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


def _word_aligned_spans(text):
    """Every contiguous run of words in `text`, concatenated and normalized
    — e.g. "ZGW Office Add-in (frontend)" -> {"zgw", "zgwoffice",
    "zgwofficeadd", "zgwofficeaddin", ..., "frontend"}. A substring check
    against this set can only ever match whole words, never a coincidental
    mid-word fragment — e.g. alias "mi" is a literal substring of
    "ensurePodiumdAdminUser" (inside "ad-mi-n"), which a raw
    normalize_name(text) containment check can't tell apart from a real
    word-level match."""
    words = words_of(text)
    spans = set()
    for i in range(len(words)):
        acc = ""
        for j in range(i, len(words)):
            acc += words[j]
            spans.add(acc)
    return spans


def match_dependency(text, deps):
    """Fuzzy-match a doc's free-form component name (e.g. "ZAC
    (Zaakafhandelcomponent)") against Chart.yaml dependencies by name/alias,
    ignoring case and punctuation — so any component the doc mentions is
    matched, not just a hardcoded set. Matches only at word boundaries (see
    _word_aligned_spans) — a name/alias short enough to coincidentally
    appear mid-word in unrelated text (e.g. "mi" inside "AdminUser") can
    never falsely match."""
    spans = _word_aligned_spans(text)
    best = None
    for dep in deps:
        for candidate in filter(None, [dep.get("name"), dep.get("alias")]):
            norm_c = normalize_name(candidate)
            if norm_c and norm_c in spans and (best is None or len(norm_c) > len(best[1])):
                best = (dep, norm_c)
    return best[0] if best else None


def match_dependency_excluding_sidecar_names(text, deps):
    """match_dependency, but refuses to match at all when `text` contains
    " - " — the canonical sidecar/shared-image delimiter (see
    lib.chart.canonical_sidecar_row_names) — since that shape never
    appears in a real Chart.yaml dependency's own name/alias. Without
    this guard, a canonical name like "redis-operator - redis" fuzzy-
    matches the real "redis-operator" dependency on its leading word
    (match_dependency's whole point is exactly this kind of loose
    word-containment match), silently corrupting or suppressing
    whatever the caller does with that match — e.g. fix-doc-consistency's
    own table-row correction once overwrote a sidecar row's app/chart
    cells with its unrelated owning dependency's own actual versions
    this way.

    Use this everywhere match_dependency is asked "is this really
    talking about a real Chart.yaml component" (row/bullet/Changes-item
    matching, mention detection) — NOT in component_order_key, which
    deliberately wants that same fuzzy containment so a canonical
    sidecar row still sorts near its owning dependency in the doc."""
    return None if " - " in text else match_dependency(text, deps)


def match_canonical_sidecar_name(text, canonical_names):
    """canonical_names.get(text) for an exact hit (a table row's own bare
    name, with no trailing text) — falling back to a fuzzy word-span
    containment match (see _word_aligned_spans/match_dependency) for a
    "### ..." Changes heading, whose canonical sidecar name is always
    followed by version/arrow text the exact lookup can't see past (e.g.
    "redis-operator - k8s 1.36.2 → 1.36.2" vs the table row's own bare
    "redis-operator - k8s"). Longest name wins on overlap, the same
    tie-break match_dependency itself uses. None if nothing matches."""
    exact = canonical_names.get(text)
    if exact is not None:
        return exact
    spans = _word_aligned_spans(text)
    best = None
    for name, path in canonical_names.items():
        norm_c = normalize_name(name)
        if norm_c and norm_c in spans and (best is None or len(norm_c) > len(best[1])):
            best = (path, norm_c)
    return best[0] if best else None


def resolve_component_identity(text, deps, canonical_names):
    """The single component `text` names — ("sidecar", path) or ("dep",
    values_key) — or None if it names no real Chart.yaml dependency or
    canonical sidecar/shared-image at all. The same two-step resolution
    docs_consistency.py's own table-row loop applies inline (sidecar
    name checked first, since match_dependency_excluding_sidecar_names
    refuses anything containing " - " on purpose), generalized here so
    changes_heading_identities can apply it to free-form Changes-heading
    text too, not just a table row's own bare name."""
    sidecar_path = match_canonical_sidecar_name(text, canonical_names)
    if sidecar_path is not None:
        return ("sidecar", sidecar_path)
    dep = match_dependency_excluding_sidecar_names(text, deps)
    if dep is not None:
        return ("dep", dep.get("alias", dep["name"]))
    return None


def changes_heading_identities(heading, deps, canonical_names):
    """The set of component identities (see resolve_component_identity)
    found anywhere in a "### ..." Changes heading's text, assessed as a
    whole — never split on "+" or any other separator, since a doc could
    join two components with any wording at all ("and", a comma, ...);
    what matters is what the text actually names, not which character
    joins it. A canonical sidecar match (checked first, same precedence
    as resolve_component_identity) is always returned alone — its own
    "<parent> - <basename>" shape necessarily contains the parent
    dependency's name too (e.g. "redis-operator - redis"), which is
    expected and correct, not a second, competing identity.

    Otherwise every real Chart.yaml dependency whose own name/alias
    matches a contiguous word-range of the heading is collected — usually
    exactly one, but a heading naming two components at once (real case:
    "### ECK Operator 3.4.0 → 3.5.0 + ECK Stack (kiss-eck) 0.19.0 →
    0.20.0") returns both; see find_changes_row_correspondence_gaps for
    what happens to a heading resolving to anything other than exactly
    one identity. Unlike match_dependency's own word-SPAN (unordered
    concatenation) check, matches here are tracked by exact word
    position, so a match whose own range is entirely contained within
    another, strictly longer match at the SAME position never counts as
    a second, independent mention — real case: eck-stack's own alias
    "kiss-eck" tokenizes to the words "kiss"+"eck", and the standalone
    "kiss" word inside it is ALSO, coincidentally, the real KISS
    dependency's own alias; without this containment filter, any heading
    mentioning "kiss-eck" would wrongly also count as separately naming
    KISS. This generalizes match_dependency's own "longest match wins"
    tie-break (built for picking a single winner) to a multi-match scan
    where several genuinely different matches can legitimately coexist
    side by side. Empty if the heading names no real component at all —
    including when it LOOKS like a canonical sidecar reference (contains
    " - ", the shape's own literal delimiter — never a real dependency's
    own name/alias, nor any other legitimate punctuation in a heading;
    same rule match_dependency_excluding_sidecar_names already applies
    for a table row's own name) but doesn't actually match one (real
    case: "### openbao - openbao 2.5.5 → 2.5.5" — self-referential,
    canonical_sidecar_row_names refuses to name a sidecar after its own
    parent, see that function's own docstring). Without this guard, the
    word "openbao" appearing plainly in that broken heading would still
    resolve it to the REAL "openbao" dependency, silently crediting a
    row that this heading doesn't actually, correctly document at all."""
    sidecar_path = match_canonical_sidecar_name(heading, canonical_names)
    if sidecar_path is not None:
        return {("sidecar", sidecar_path)}
    if " - " in heading:
        return set()
    words = words_of(heading)
    matches = []  # [(start, end, values_key), ...], end exclusive
    for dep in deps:
        for candidate in filter(None, [dep.get("name"), dep.get("alias")]):
            norm_c = normalize_name(candidate)
            if not norm_c:
                continue
            for start in range(len(words)):
                acc = ""
                for end in range(start, len(words)):
                    acc += words[end]
                    if len(acc) > len(norm_c):
                        break
                    if acc == norm_c:
                        matches.append((start, end + 1, dep.get("alias", dep["name"])))
                        break
    kept = [key for start, end, key in matches
            if not any(o_start <= start and end <= o_end and (o_start, o_end) != (start, end)
                       for o_start, o_end, _ in matches)]
    return {("dep", key) for key in kept}


def find_changes_row_correspondence_gaps(rows, headings, deps, canonical_names):
    """Cross-check the "Component versions" table against the "## Changes"
    section: every row naming a real component should have exactly one
    Changes heading naming that same component, and vice versa — a real
    omission neither side's own internal checks (out-of-order, missing-
    vs-baseline) can see, since each only ever looks at one of the two
    lists at a time, never asking whether the OTHER list agrees a given
    component's row/section exists at all (e.g. a row added without ever
    writing its narrative Changes section, or a Changes section written
    for a component whose table row was forgotten, renamed, or never
    added).

    A heading only ever credits a row when changes_heading_identities
    finds EXACTLY one component in it — a heading naming zero (an
    orphan, real case: "Keycloak app image 26.6.4 → 26.7.2", which never
    says "keycloak-operator" or even "operator") or two-or-more (real
    case: the ECK Operator/ECK Stack example above) never credits any
    component's row, and is itself always reported as having no matching
    row, exactly like a heading naming the wrong component would be —
    "assess the text as a whole" cuts both ways: a heading either
    unambiguously names one row, or it's wrong, never a shortcut to
    satisfying two rows at once.

    A row/heading-side that doesn't resolve to any real component at all
    (free-form prose, or a row already flagged elsewhere as wrong/stale
    — see find_wrong_or_duplicate_dependency_claims) is silently skipped
    on ITS OWN side. Returns (rows_without_heading, headings_without_row),
    each a list of the original row name / heading text, in their
    original order."""
    heading_identity_sets = [changes_heading_identities(h, deps, canonical_names) for h in headings]
    all_heading_identities = set()
    for idents in heading_identity_sets:
        if len(idents) == 1:
            all_heading_identities |= idents

    row_identities = set()
    rows_without_heading = []
    for row in rows:
        ident = resolve_component_identity(row["name"], deps, canonical_names)
        if ident is None:
            continue
        row_identities.add(ident)
        if ident not in all_heading_identities:
            rows_without_heading.append(row["name"])

    headings_without_row = [heading for heading, idents in zip(headings, heading_identity_sets)
                             if len(idents) != 1 or idents.isdisjoint(row_identities)]

    return rows_without_heading, headings_without_row


def changes_heading_has_app_version(heading):
    """Whether a "### ..." Changes heading's own text shows an app-
    version pair at all. make_changes_section's own template always
    writes the app pair as "<old> → <new>" immediately after the
    component name — even when unchanged, e.g. "openzaak 1.27.4 →
    1.29.3" or "objecten 3.6.2 → 3.6.2" — only the "(chart ...)" portion
    ever uses the arrow-less "X, unchanged" shape for an unchanged
    value. A heading with no arrow anywhere (real case: "### openbao
    0.28.4" — add_missing_component_rows' own chart-only TODO-stub
    shape, used when actual_app_version couldn't resolve anything at
    the time) reliably signals no app version was ever written, not
    just that it happens to equal the source (which would still show
    the arrow)."""
    return "→" in heading or "->" in heading


def is_exact_dependency_match(name, dep):
    """True if `name`, normalized (case/punctuation-insensitive), equals
    `dep`'s own name or alias EXACTLY — not just a fuzzy word-span
    containment match (see match_dependency). Distinguishes "this row
    literally IS the dependency" (e.g. "KISS") from "this row merely
    mentions it somewhere in a longer free-form name" (e.g. "Kiss
    Elasticsearch", which match_dependency also resolves to the same
    dependency via its normal word-containment matching, even though the
    row is actually describing something else entirely — a real doc-
    consistency gap this distinction exists to catch: once one row
    exactly claims a dependency, no other row should be allowed to
    silently claim the same one merely by fuzzy containment)."""
    norm = normalize_name(name)
    return any(normalize_name(c) == norm for c in (dep.get("name"), dep.get("alias")) if c)


def find_wrong_or_duplicate_dependency_claims(names, deps):
    """(duplicate_names, wrong_fuzzy_names) for a list of free-form names
    each purporting to describe a Chart.yaml dependency — a doc row's own
    Name cell, or an images-manifest "# Changes:" item's own free-form
    text. Two deterministic gaps neither ordinary per-row/per-item
    content checking catches on its own:

    - duplicate_names: any name appearing more than once in `names` — a
      leftover/typo'd duplicate, whatever it resolves to.
    - wrong_fuzzy_names: any name that only fuzzy-matches (match_dependency_
      excluding_sidecar_names) a dependency ALREADY exactly claimed (see
      is_exact_dependency_match) by another name in `names`. Real case
      this catches: a stale free-form item/row like "Kiss Elasticsearch"
      or "Kiss's ECK-managed Elasticsearch/Kibana/Enterprise Search"
      fuzzy-matches the real "kiss" dependency on the word "kiss" —
      exactly the same collision the doc's own exact "KISS" row/item
      already legitimately claims — so an ordinary content check comparing
      it against kiss's own actual app/chart version finds nothing wrong
      whenever those numbers happen to already agree, even though the
      free-form one doesn't correspond to anything in Chart.yaml/
      values.yaml as its own tracked item at all.

    Callers should skip their own normal per-name resolution entirely for
    any name in either returned set, reporting it as wrong/stale instead —
    see lib.docs_consistency's own row loop and Changes-block loop for the
    exact pattern."""
    name_counts = {}
    for name in names:
        name_counts[name] = name_counts.get(name, 0) + 1
    duplicate_names = {name for name, count in name_counts.items() if count > 1}

    exact_claims = {}  # values_key -> the name that exactly claims it
    for name in names:
        if name in duplicate_names:
            continue
        dep = match_dependency_excluding_sidecar_names(name, deps)
        if dep is not None and is_exact_dependency_match(name, dep):
            exact_claims[dep.get("alias", dep["name"])] = name

    wrong_fuzzy_names = set()
    for name in names:
        if name in duplicate_names or name in exact_claims.values():
            continue
        dep = match_dependency_excluding_sidecar_names(name, deps)
        if dep is None:
            continue
        key = dep.get("alias", dep["name"])
        if key in exact_claims:
            wrong_fuzzy_names.add(name)

    return duplicate_names, wrong_fuzzy_names


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


def actual_app_version(values, values_key, component=None, chart_dir=None, dep=None):
    """The app version currently pinned for a component — tries each of
    lib.chart.image_paths_for(component)'s own dotted path(s) in turn:
    the plain "<key>.image.tag" shape for the common case
    (DEFAULT_IMAGE_PATHS), or a component-specific override from
    COMPONENT_IMAGE_PATHS for one with a non-standard primary-image
    location — e.g. keycloak-operator's own split "operator.config.
    keycloakImage.tag" path, openbao's "server.image", or zgw-office-
    addin's frontend+backend pair (the first of those two with a real
    tag wins; there's no single "the" app version for a two-image
    component, so this picks one rather than reporting both).

    If none of those resolve, falls back to lib.chart.version_paths_for
    (component)'s own dotted path(s), read DIRECTLY (no ".tag" suffix
    appended) — for a component whose real app version isn't expressed
    as an "image: {repository, tag}" block at all, e.g. eck-stack's own
    bare "eck-elasticsearch.version" CRD field, or redis-operator's own
    split "redisOperator.imageTag" (sibling to "imageName", not nested
    under a common "image:" key). Without this fallback, a real app-
    version change on one of these components was invisible to every
    caller of this function — the doc-consistency row/Changes-item check
    silently skipped comparing it at all (its own "actual_app and ..."
    guard short-circuits on None), so a wrong OR MISSING app-version cell
    for kiss-eck's own real 8.19.3 -> 8.19.19 Elastic-stack bump went
    uncaught; confirmed live.

    If THAT still doesn't resolve, and both `chart_dir` and `dep` (the
    full Chart.yaml dependency dict — needs its own "version" too, not
    just its name) are given, falls back to lib.chart.subchart_app_
    version — but ONLY for a component with its own COMPONENT_IMAGE_
    PATHS entry, never the generic DEFAULT_IMAGE_PATHS guess. A
    registered path with an explicit but deliberately BLANK "tag:"
    override (e.g. openbao's own "server.image.tag" — the repository is
    pinned, but the tag is left for the chart's own pinned appVersion to
    supply) is a DELIBERATE design signal that a human already vouched
    for; the same blank tag on an UNREGISTERED component could just as
    easily mean "not actually running this image at all," which nothing
    here can tell apart — so this never applies to eck-operator or any
    other component that merely happens to also float on its own
    chart's appVersion without being explicitly registered for it.

    `component` is the Chart.yaml dependency's own NAME (COMPONENT_
    IMAGE_PATHS/COMPONENT_VERSION_PATHS are both keyed by name, not
    alias) — defaults to `values_key` when omitted, since name and
    alias/values_key coincide for every currently-registered entry; pass
    the real name explicitly once a registered component ever has a
    distinct alias, so the registry lookup still finds it."""
    resolved_component = component or values_key
    for path in image_paths_for(resolved_component):
        tag = get_path(values, f"{values_key}.{path}.tag")
        if tag:
            return tag.split("@")[0]
    for path in version_paths_for(resolved_component):
        version = get_path(values, f"{values_key}.{path}")
        if isinstance(version, str) and version:
            return version.split("@")[0]
    if chart_dir is not None and dep is not None and resolved_component in COMPONENT_IMAGE_PATHS:
        return subchart_app_version(chart_dir, dep)
    return None


def find_image_tag_paths(node, path=()):
    """Yield (path, tag) for every "<key>: {tag: ...}" block anywhere in a
    values tree, where <key> is "image" or ends with "Image" (e.g.
    "initImage", alongside "image" in the very same job, for a component
    that needs more than one distinctly-named image — a single "image"
    key can't serve both). Keyed by its full path INCLUDING that key
    itself — e.g. ("zac", "opa", "image") for zac.opa.image.tag, or
    ("keycloak-operator", "jobs", "ensurePodiumdAdminUser", "initImage")
    for that job's own init-container image. Structural, so it finds
    sidecars too, not just top-level Chart.yaml dependencies.

    Deliberately keyed on the "...Image" suffix specifically, not "any
    dict shaped like {tag, repository}" — a reusable template like
    global.images.nginx/curl/busybox/redis (itself never rendered
    anywhere on its own, just aliased into real "image:"/"...Image:"
    sites via a YAML anchor) would otherwise be double-counted as its
    own separate, spurious usage location; "images" (plural, the
    container dict those templates live under) doesn't itself end in
    "Image" (capital I), so this excludes it correctly.

    NOTE: the yielded path now always ends in the image key itself
    (unlike this function's earlier "image"-only shape, which omitted
    it since every caller could safely assume ".image.tag") — a caller
    reconstructing a dotted values.yaml reference must use path[-1],
    not a hardcoded ".image.tag" suffix."""
    if isinstance(node, dict):
        for key, value in node.items():
            if (key == "image" or key.endswith("Image")) and isinstance(value, dict) and value.get("tag"):
                yield path + (key,), value["tag"]
        for key, value in node.items():
            if key == "image" or key.endswith("Image"):
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
    "zac"+"solr"+"operator") are indistinguishable by substring matching alone.

    A path's own trailing "image"/"...Image" segment (see
    find_image_tag_paths — the generic marker for which key under that
    parent actually holds the tag, not a meaningful descriptor on its
    own) is excluded from matching, the same way a path built this
    function's original way (before more than one image-key name became
    possible) never had it there to begin with. The full path, trailing
    segment included, is still what gets returned — callers use it
    as-is for a dict lookup back into whatever produced it."""
    entry_words = words_of(entry_name)
    if not entry_words:
        return None
    norm_entry = "".join(entry_words)

    best = None
    for path in paths:
        descriptive = path[:-1] if path and (path[-1] == "image" or path[-1].endswith("Image")) else path
        path_words = [w for segment in descriptive for w in words_of(segment)]
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


def resolve_entry_image_path(entry, paths, repo_map=None):
    """Match an images-manifest entry (the full {"name", "url", ...}
    mapping) to a values-tree path — an exact repo_map lookup first
    (see lib.chart.repository_path_map: under the current strip-
    registry convention an entry's "name:" IS the repository in that
    same stripped form, so this is a direct dict hit, not a guess),
    falling back to resolve_entry_path's fuzzy name-word matching when
    repo_map has nothing for it (no repo_map given, an older manifest
    entry still under the legacy hand-translated slug convention, or a
    nested image with no Chart.yaml dependency of its own — e.g. a
    component's bundled sidecar — that repo_map doesn't cover at all)."""
    if repo_map:
        path = repo_map.get(entry["name"])
        if path is not None and path in paths:
            return path
    return resolve_entry_path(entry["name"], paths)


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
    return find_grouped_preceding_comment_line(
        lines, entries, entry_line_indices, index - 1, same_group)


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


BARE_CHART_CLAUSE_RE = re.compile(
    r"\bchart\s+`?[A-Za-z0-9][\w.\-]*`?\s*(?:→|->)\s*`?[A-Za-z0-9][\w.\-]*`?", re.IGNORECASE)


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
        app_search_text = rest[:bare_chart_m.start()] + " " + rest[bare_chart_m.end():]

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
    return {"name": name, "app_source": app_source, "app": app_target,
            "chart_source": chart_source, "chart": chart_target}


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


def compute_changed_components(deps, baseline_deps, values, baseline_values):
    """Top-level component keys (Chart.yaml alias, or name if unaliased) that
    actually differ between the baseline and now: dependency added or
    removed, chart version bumped, or any image tag anywhere under that
    key's values.yaml subtree changed. This is the ground truth the docs
    are checked against — independent of what they currently say, so it
    also catches a component that changed but was never added to any doc
    at all."""
    current_by_key = {dep.get("alias", dep["name"]): dep for dep in deps}
    baseline_by_key = {dep.get("alias", dep["name"]): dep for dep in baseline_deps}

    current_paths = dict(find_image_tag_paths(values))
    baseline_paths = dict(find_image_tag_paths(baseline_values)) if baseline_values else {}

    def subtree_paths(key, paths):
        return {p: t for p, t in paths.items() if p[0] == key}

    changed = set()
    for key in set(current_by_key) | set(baseline_by_key):
        cur_dep, base_dep = current_by_key.get(key), baseline_by_key.get(key)
        if cur_dep is None or base_dep is None:
            changed.add(key)
        elif normalize_version(cur_dep["version"]) != normalize_version(base_dep["version"]):
            changed.add(key)
        elif subtree_paths(key, current_paths) != subtree_paths(key, baseline_paths):
            changed.add(key)
    return changed


FENCED_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)


def strip_fenced_code_blocks(text):
    """`text` with every ```...``` fenced code block blanked out. A single
    backtick or "**" sequence inside example code isn't a real inline-
    code/bold span, but naively pairing delimiters across the WHOLE
    document (see extract_mentioned_dependency_keys/
    missing_key_change_lines/lib.docs_consistency.
    check_values_deltas_content, all of which scan a free-form doc for
    such spans) desyncs every pairing after the first fence — silently
    hiding real, already-mentioned spans later in the doc from an
    "is this already covered" check, which then wrongly reports (or
    re-adds) content that's already there. Scan the stripped text for
    spans, never the original."""
    return FENCED_CODE_BLOCK_RE.sub("", text)


def extract_mentioned_dependency_keys(text, deps):
    """Component keys mentioned via a bold "**Name**" span anywhere in a
    free-form doc (e.g. a values-deltas.md bullet like "- **ZAC** app ..."),
    matched the same fuzzy way as an upgrade-doc table row's name. Uses
    match_dependency_excluding_sidecar_names, not match_dependency
    directly — a canonical sidecar/shared-image bullet like "- **redis-
    operator - redis** app ..." must never register as mentioning the
    real "redis-operator" dependency (see that function's own
    docstring); doing so would wrongly suppress redis-operator's own
    bullet as "already mentioned" if it changed independently."""
    mentioned = set()
    for m in re.finditer(r"\*\*([^*]+)\*\*", strip_fenced_code_blocks(text)):
        dep = match_dependency_excluding_sidecar_names(m.group(1), deps)
        if dep:
            mentioned.add(dep.get("alias", dep["name"]))
    return mentioned


def describe_key_changes(values_key, baseline_subtree, current_subtree):
    """One "- Key `<dotted>` was added/removed/renamed to `<dotted>`." line
    per top-level key change under this component — backtick-quoted,
    matching the convention verify-podiumd's own check looks for.

    Paths passed to diff_keys/pair_renames are relative to the subtree
    itself (path=()), NOT prefixed with values_key — pair_renames's own
    lookups walk baseline_subtree/current_subtree directly, so a
    values_key-prefixed path would never resolve (silently comparing None
    to None, which can pair completely unrelated keys as a false rename)."""
    diffs = list(diff_keys(baseline_subtree, current_subtree))
    added = [p for kind, p in diffs if kind == "added"]
    removed = [p for kind, p in diffs if kind == "removed"]
    renamed, added, removed = pair_renames(added, removed, baseline_subtree, current_subtree)

    def dotted(path):
        return ".".join((values_key,) + path)

    lines = []
    for path in added:
        lines.append(f"- Key `{dotted(path)}` was added.\n")
    for path in removed:
        lines.append(f"- Key `{dotted(path)}` was removed.\n")
    for old_path, new_path in renamed:
        lines.append(f"- Key `{dotted(old_path)}` was renamed to `{dotted(new_path)}`.\n")
    return lines


def missing_key_change_lines(text, changed_component_keys, baseline_values, values):
    """Every describe_key_changes() line for a changed component that isn't
    already mentioned (backtick-quoted, matching verify-podiumd's own
    check_values_deltas_content convention) anywhere in text. A rename line
    carries two backtick spans (old and new key); both must already be
    mentioned for the line to count as covered, else it's reported as
    missing so a partial/stale rename mention still gets caught.

    A line whose exact text is already present verbatim in `text` is
    never reported either way, even if the "mentioned" check above
    somehow missed it — a second, independent backstop against
    re-adding content that's already there (see strip_fenced_code_blocks
    for the one known way the "mentioned" check itself can be fooled)."""
    backtick_spans = re.findall(r"`([^`]+)`", strip_fenced_code_blocks(text))

    def mentioned(span):
        return any(span in other or other in span for other in backtick_spans)

    lines = []
    for values_key in sorted(changed_component_keys):
        baseline_subtree = baseline_values.get(values_key, {}) if isinstance(baseline_values, dict) else {}
        current_subtree = values.get(values_key, {}) if isinstance(values, dict) else {}
        for line in describe_key_changes(values_key, baseline_subtree, current_subtree):
            spans_in_line = re.findall(r"`([^`]+)`", line)
            if line not in text and not all(mentioned(span) for span in spans_in_line):
                lines.append(line)
    return lines


def append_to_doc(text, new_lines):
    """Append new_lines to the end of a doc, blank-line-separated from
    whatever's already there — the shared "just tack this on" convention
    used when a script adds content to an existing markdown doc."""
    if not new_lines:
        return text
    if text and not text.endswith("\n\n"):
        text = text.rstrip("\n") + "\n\n"
    return text + "".join(new_lines)
