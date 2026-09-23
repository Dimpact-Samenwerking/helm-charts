"""upgrade-doc text primitives: version/name normalization, word-
boundary text matching against dependency/native-component/sidecar
names, and the basic Component-versions-table row parser. Pure
string/regex logic, no filesystem or values.yaml access."""

import re

from lib.chart.registered_paths import native_components

COMPONENT_VERSIONS_HEADING_RE = re.compile(r"^##\s+Component versions\b")


def normalize_version(v):
    """`v` with any leading "v"/"V" stripped (e.g. "v1.2.3" -> "1.2.3"), so a
    doc's own "v"-prefixed version and Chart.yaml/values.yaml's bare one
    compare equal. Passes through falsy `v` (None, "") unchanged."""
    return v.lstrip("vV") if v else v


def normalize_name(s):
    """`s` lowercased with every non-alphanumeric character stripped — the
    shared "same name, ignoring case/punctuation/spacing" key used
    throughout this module's fuzzy dependency/sidecar/component-name
    matching (match_dependency, match_canonical_sidecar_name, ...)."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def words_of(s):
    """`s` lowercased and split into its individual alphanumeric words,
    dropping every run of punctuation/whitespace between them (e.g. "ZGW
    Office Add-in (frontend)" -> ["zgw", "office", "add", "in",
    "frontend"]) — the tokenization _word_aligned_spans/changes_heading_
    identities build their own word-boundary-safe matching on top of."""
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
        rows.append(
            {
                "line_index": i,
                "name": cells[0],
                "app_source": extract_source_version(cells[1]),
                "app": extract_target_version(cells[1]),
                "chart_source": extract_source_version(cells[2]),
                "chart": extract_target_version(cells[2]),
            }
        )
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


def text_names(text: str, name: str) -> bool:
    """Whether `text` (a table row's Name cell, a "### ..." heading or a
    "# Changes:" item) names `name`. A plain name matches at word
    boundaries (_word_aligned_spans), so "mi" never matches "AdminUser".
    A canonical "<key> - <basename>" sidecar name (lib.chart.canonical_
    sidecar_row_names) only matches text that starts with exactly its
    words, followed by nothing or a version: "zac - postgres" never
    matches "zac - postgres-exporter 1.0", and a plain name never
    matches a sidecar's text, nor the reverse."""
    if " - " not in text and " - " not in name:
        return normalize_name(name) in _word_aligned_spans(text)
    if " - " not in text or " - " not in name:
        return False
    name_words, words = words_of(name), words_of(text)
    rest = words[len(name_words) :]
    return words[: len(name_words)] == name_words and (not rest or re.match(r"v?\d", rest[0]) is not None)


def match_dependency(text, deps):
    """Fuzzy-match a doc's free-form component name (e.g. "ZAC
    (Zaakafhandelcomponent)") against Chart.yaml dependencies by name/alias,
    ignoring case and punctuation — so any component the doc mentions is
    matched, not just a hardcoded set. Matches only at word boundaries (see
    _word_aligned_spans) — a name/alias short enough to coincidentally
    appear mid-word in unrelated text (e.g. "mi" inside "AdminUser") can
    never falsely match."""
    spans = _word_aligned_spans(text)
    best_dep, best_norm = None, None
    for dep in deps:
        for candidate in filter(None, [dep.get("name"), dep.get("alias")]):
            norm_c = normalize_name(candidate)
            if norm_c and norm_c in spans and (best_norm is None or len(norm_c) > len(best_norm)):
                best_dep, best_norm = dep, norm_c
    return best_dep


def match_native_component(text, native_component_names):
    """match_dependency's own word-boundary-safe fuzzy match, against
    lib.chart.native_components() (a values.yaml top-level component with
    no backing Chart.yaml dependency at all — see that registry's own
    docstring) instead of Chart.yaml's dependencies list. Kept as its own
    function rather than one more fallback branch inside match_dependency
    itself: every existing match_dependency caller already has a
    considered opinion on whether a native component should match too
    (component_order_key: yes, so its own row/section still sorts at its
    real values.yaml position; compute_changed_components: doesn't need
    this at all, since it already iterates native_components() directly).
    Takes the resolved set of names (`native_component_names`), not a
    chart_dir, so a caller with no chart_dir in scope can pass lib.chart.
    native_components()'s own self-resolving default."""
    spans = _word_aligned_spans(text)
    best_key, best_norm = None, None
    for key in native_component_names:
        norm = normalize_name(key)
        if norm and norm in spans and (best_norm is None or len(norm) > len(best_norm)):
            best_key, best_norm = key, norm
    return best_key


def match_canonical_sidecar_name(text, canonical_names):
    """canonical_names.get(text) for an exact hit (a table row's own bare
    name, with no trailing text) — falling back to a fuzzy word-span
    containment match (see _word_aligned_spans/match_dependency) for a
    "### ..." Changes heading, whose canonical sidecar name is always
    followed by version/arrow text the exact lookup can't see past (e.g.
    "redis-operator - k8s 1.36.2 → 1.36.2" vs the table row's own bare
    "redis-operator - k8s"). Longest name wins on overlap, the same
    tie-break match_dependency itself uses. None if nothing matches, or
    if canonical_names itself is None — a caller with no canonical-names
    map handy at all (e.g. values-deltas.md section lookups that don't
    always have one available) rather than every such call site having
    to remember its own "or {}" guard."""
    if canonical_names is None:
        return None
    exact = canonical_names.get(text)
    if exact is not None:
        return exact
    spans = _word_aligned_spans(text)
    best_path, best_norm = None, None
    for name, path in canonical_names.items():
        norm_c = normalize_name(name)
        if norm_c and norm_c in spans and (best_norm is None or len(norm_c) > len(best_norm)):
            best_path, best_norm = path, norm_c
    return best_path


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
    row that this heading doesn't actually, correctly document at all.

    A native_components component (see lib.chart.native_components) is
    matched the exact same word-position way, as its own single
    candidate (it has no separate name/alias pair — it isn't in
    Chart.yaml at all) — same reasoning as resolve_component_identity's
    own native fallback: identity-wise it's indistinguishable from a
    real dependency to every caller of this set."""
    sidecar_path = match_canonical_sidecar_name(heading, canonical_names)
    if sidecar_path is not None:
        return {("sidecar", sidecar_path)}
    if " - " in heading:
        return set()
    words = words_of(heading)
    matches = []  # [(start, end, values_key), ...], end exclusive
    candidates_by_key = [
        (cand, dep.get("alias", dep["name"]))
        for dep in deps
        for cand in filter(None, [dep.get("name"), dep.get("alias")])
    ]
    candidates_by_key += [(key, key) for key in native_components()]
    for candidate, key in candidates_by_key:
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
                    matches.append((start, end + 1, key))
                    break
    kept = [
        key
        for start, end, key in matches
        if not any(
            o_start <= start and end <= o_end and (o_start, o_end) != (start, end) for o_start, o_end, _ in matches
        )
    ]
    return {("dep", key) for key in kept}
