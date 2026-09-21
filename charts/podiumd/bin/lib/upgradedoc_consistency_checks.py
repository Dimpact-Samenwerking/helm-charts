"""Cross-checks between an upgrade doc's own prose (Changes
headings, dependency-name mentions) and the real Chart.yaml
dependency/native-component identities -- flags a heading that
corresponds to no real row, or text claiming a dependency that
doesn't exist, rather than ever guessing a match."""

from lib.chart_registered_paths import native_components
from lib.upgradedoc_string_and_parsing_basics import (
    changes_heading_identities,
    match_canonical_sidecar_name,
    match_dependency_excluding_sidecar_names,
    match_native_component,
    normalize_name,
)


def resolve_component_identity(text, deps, canonical_names):
    """The single component `text` names — ("sidecar", path) or ("dep",
    values_key) — or None if it names no real Chart.yaml dependency,
    canonical sidecar/shared-image, or native_components component (see
    lib.chart.native_components) at all. The same two-step resolution
    docs_consistency.py's own table-row loop applies inline (sidecar
    name checked first, since match_dependency_excluding_sidecar_names
    refuses anything containing " - " on purpose), generalized here so
    changes_heading_identities can apply it to free-form Changes-heading
    text too, not just a table row's own bare name.

    A native_components match is returned as ("dep", values_key) too —
    same identity shape as a real dependency, deliberately: every caller
    here only ever asks "does this row/heading's identity match that
    OTHER row/heading's identity", never "is this backed by a real
    Chart.yaml dependency", so a native component needs no third,
    parallel identity shape of its own."""
    sidecar_path = match_canonical_sidecar_name(text, canonical_names)
    if sidecar_path is not None:
        return ("sidecar", sidecar_path)
    dep = match_dependency_excluding_sidecar_names(text, deps)
    if dep is not None:
        return ("dep", dep.get("alias", dep["name"]))
    native_key = match_native_component(text, native_components())
    if native_key is not None:
        return ("dep", native_key)
    return None


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

    headings_without_row = [
        heading
        for heading, idents in zip(headings, heading_identity_sets, strict=True)
        if len(idents) != 1 or idents.isdisjoint(row_identities)
    ]

    return rows_without_heading, headings_without_row


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
