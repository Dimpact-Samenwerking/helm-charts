"""Cross-checks between an upgrade doc's prose (Changes headings, dependency
names) and real Chart.yaml/native-component identities; mismatches are
flagged, never guessed."""

from collections.abc import Mapping
from collections.abc import Sequence

from lib.chart.chart_yaml import ChartDependency
from lib.chart.registered_paths import native_components
from lib.chart.values_tree_primitives import values_key_of
from lib.upgradedoc.string_and_parsing_basics import ComponentRef
from lib.upgradedoc.string_and_parsing_basics import VersionRow
from lib.upgradedoc.string_and_parsing_basics import changes_heading_identities
from lib.upgradedoc.string_and_parsing_basics import match_canonical_sidecar_name
from lib.upgradedoc.string_and_parsing_basics import match_dependency_excluding_sidecar_names
from lib.upgradedoc.string_and_parsing_basics import match_native_component
from lib.upgradedoc.string_and_parsing_basics import normalize_name


def resolve_component_identity(
    text: str, deps: list[ChartDependency], canonical_names: Mapping[str, tuple[str, ...]] | None
) -> ComponentRef | None:
    """The single component `text` names, ("sidecar", path) or ("dep", values_key), or None.

    Sidecar names are checked first because
    match_dependency_excluding_sidecar_names rejects anything containing
    " - ". Native components also return ("dep", key): callers only compare
    identities, so no separate shape is needed."""
    sidecar_path = match_canonical_sidecar_name(text, canonical_names)
    if sidecar_path is not None:
        return ("sidecar", sidecar_path)
    dep = match_dependency_excluding_sidecar_names(text, deps)
    if dep is not None:
        return ("dep", values_key_of(dep))
    native_key = match_native_component(text, native_components())
    if native_key is not None:
        return ("dep", native_key)
    return None


def _named_row_identities(
    rows: Sequence[VersionRow], deps: list[ChartDependency], canonical_names: Mapping[str, tuple[str, ...]] | None
) -> list[tuple[str, ComponentRef]]:
    """(row name, identity) of each "Component versions" row that resolve_component_identity resolves."""
    return [
        (row["name"], identity)
        for row in rows
        if (identity := resolve_component_identity(row["name"], deps, canonical_names)) is not None
    ]


def _single_heading_identities(
    headings: list[str], deps: list[ChartDependency], canonical_names: Mapping[str, tuple[str, ...]]
) -> list[ComponentRef | None]:
    """Per heading, the one component it names, or None when it names none or several."""
    identities = [changes_heading_identities(h, deps, canonical_names) for h in headings]
    return [next(iter(idents)) if len(idents) == 1 else None for idents in identities]


def row_identities(
    rows: Sequence[VersionRow], deps: list[ChartDependency], canonical_names: Mapping[str, tuple[str, ...]] | None
) -> set[ComponentRef]:
    """The component or sidecar/shared image each "Component versions" row names (resolve_component_identity)."""
    return {identity for _name, identity in _named_row_identities(rows, deps, canonical_names)}


def rowed_component_keys(
    rows: Sequence[VersionRow], deps: list[ChartDependency], canonical_names: Mapping[str, tuple[str, ...]] | None
) -> set[str]:
    """Top-level keys of the components with a "Component versions" row of their own.

    A sidecar row ("redis-operator - redis") does not count for its parent.
    Shared by add_missing_component_rows and the checker's "changed but has no
    row" finding, so they agree on which components still need a row.
    """
    return {ref for kind, ref in row_identities(rows, deps, canonical_names) if kind == "dep" and isinstance(ref, str)}


def rowed_sidecar_paths(
    rows: Sequence[VersionRow], deps: list[ChartDependency], canonical_names: Mapping[str, tuple[str, ...]] | None
) -> set[tuple[str, ...]]:
    """Values paths of the sidecar/shared images with a row; shared by add_missing_sidecar_rows and the checker."""
    return {
        ref for kind, ref in row_identities(rows, deps, canonical_names) if kind == "sidecar" and isinstance(ref, tuple)
    }


def find_changes_row_correspondence_gaps(
    rows: Sequence[VersionRow],
    headings: list[str],
    deps: list[ChartDependency],
    canonical_names: Mapping[str, tuple[str, ...]],
) -> tuple[list[str], list[str]]:
    """Cross-check "Component versions" rows against "## Changes" headings.

    Each resolvable row needs a heading naming exactly that component and
    vice versa. A heading naming zero or several components credits no row
    and is itself reported. Unresolvable rows are skipped. Returns
    (rows_without_heading, headings_without_row) in original order."""
    heading_idents = _single_heading_identities(headings, deps, canonical_names)
    named_rows = _named_row_identities(rows, deps, canonical_names)
    rows_without_heading = [name for name, ident in named_rows if ident not in heading_idents]
    rowed = {ident for _name, ident in named_rows}
    headings_without_row = [
        heading for heading, ident in zip(headings, heading_idents, strict=True) if ident is None or ident not in rowed
    ]

    return rows_without_heading, headings_without_row


def _group_by_identity(texts_and_identities: Sequence[tuple[str, ComponentRef]]) -> list[tuple[str, ...]]:
    """Every group of texts sharing one identity with at least one other
    text, in order of each group's first text."""
    groups: dict[ComponentRef, list[str]] = {}
    for text, ident in texts_and_identities:
        groups.setdefault(ident, []).append(text)
    return [tuple(texts) for texts in groups.values() if len(texts) > 1]


def find_changes_duplicate_identities(
    rows: Sequence[VersionRow],
    headings: list[str],
    deps: list[ChartDependency],
    canonical_names: Mapping[str, tuple[str, ...]],
) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]]]:
    """(duplicate_row_groups, duplicate_heading_groups) naming the same component more than once.

    E.g. rows "KISS" and "Kiss". Only single-identity headings count; others
    are already reported by find_changes_row_correspondence_gaps."""
    heading_idents = [
        (heading, ident)
        for heading, ident in zip(headings, _single_heading_identities(headings, deps, canonical_names), strict=True)
        if ident is not None
    ]
    row_idents = _named_row_identities(rows, deps, canonical_names)
    return _group_by_identity(row_idents), _group_by_identity(heading_idents)


def is_exact_dependency_match(name: str, dep: ChartDependency) -> bool:
    """True if normalized `name` equals dep's name or alias exactly, not just by word containment.

    Separates "KISS" (is the dependency) from "Kiss Elasticsearch" (merely
    mentions it)."""
    norm = normalize_name(name)
    return any(normalize_name(c) == norm for c in (dep.get("name"), dep.get("alias")) if c)


def find_wrong_or_duplicate_dependency_claims(
    names: list[str], deps: list[ChartDependency]
) -> tuple[set[str], set[str]]:
    """(duplicate_names, wrong_fuzzy_names) for free-form names claiming Chart.yaml dependencies.

    - duplicate_names: names appearing more than once.
    - wrong_fuzzy_names: names that only fuzzy-match a dependency another
      name already claims exactly (e.g. "Kiss Elasticsearch" next to "KISS");
      a version check alone can't catch these when the numbers agree.

    Callers should report names in either set as wrong/stale and skip their
    normal resolution. Exact claims use two sets, not a {key: name} dict, so
    two names exactly claiming one key don't overwrite each other."""
    name_counts: dict[str, int] = {}
    for name in names:
        name_counts[name] = name_counts.get(name, 0) + 1
    duplicate_names = {name for name, count in name_counts.items() if count > 1}

    exactly_claiming_names: set[str] = set()
    exactly_claimed_keys: set[str] = set()
    for name in names:
        dep = match_dependency_excluding_sidecar_names(name, deps)
        if dep is not None and is_exact_dependency_match(name, dep):
            exactly_claiming_names.add(name)
            exactly_claimed_keys.add(values_key_of(dep))

    wrong_fuzzy_names: set[str] = set()
    for name in names:
        if name in duplicate_names or name in exactly_claiming_names:
            continue
        dep = match_dependency_excluding_sidecar_names(name, deps)
        if dep is None:
            continue
        key = values_key_of(dep)
        if key in exactly_claimed_keys:
            wrong_fuzzy_names.add(name)

    return duplicate_names, wrong_fuzzy_names
