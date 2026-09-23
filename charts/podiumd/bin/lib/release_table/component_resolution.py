"""export-confluence-release-table's own name/alias -> Chart.yaml
dependency resolution (component_and_alias) and its supporting helpers,
split out of that script for pylint's too-many-lines check."""

import re

from collections.abc import Callable
from collections.abc import Collection
from pathlib import Path

from lib.chart.release_baseline_basics import load_yaml
from lib.upgradedoc.string_and_parsing_basics import normalize_name
from lib.upgradedoc.string_and_parsing_basics import word_contains

BRACKETED_RE = re.compile(r"\(([^)]*)\)")


def name_candidates(name: str):
    """Every normalized string worth matching against a Chart.yaml
    dependency for `name`: the whole thing, and — if `name` has a
    "... (bracketed part)" shape — the bracketed part and the rest of
    the string, tried separately as well (e.g. "Platform Autorisatie
    Beheer Component (PABC)" tries "platformautorisatiebeheercomponentpabc",
    "platformautorisatiebeheercomponent", AND "pabc" — the last of which
    is what actually resolves it cleanly, against Chart.yaml dependency
    "pabc"'s own alias "pabc"). Matching each part on its own (rather
    than only ever the whole, punctuation-stripped string) avoids a
    false match spanning the boundary between the two parts, and lets an
    exact match fire for a part that's short/generic enough that it
    would only ever relate to something by substring as part of the
    whole string."""
    return list(dict.fromkeys(normalize_name(part) for part in _candidate_parts(name)))


def _candidate_parts(name: str) -> list[str]:
    """name_candidates, before normalizing: `name` itself and, for a
    "... (bracketed part)" name, the rest and the bracketed part. Parts
    that normalize to "" are dropped."""
    parts = [name]
    match = BRACKETED_RE.search(name)
    if match:
        parts += [name[: match.start()] + name[match.end() :], match.group(1)]
    return [part for part in parts if normalize_name(part)]


def _related(a: str, b: str):
    """True if either of `a` and `b` contains the other as a run of whole
    words (lib.upgradedoc.string_and_parsing_basics.word_contains, the
    same matching the doc scripts use) — the single relation every
    loose match rule in component_and_alias reduces to. "Zaak - ZAC"
    relates to "zac", "Office Add-in" to "zgw-office-addin", but "mi"
    never to "AdminUser"."""
    return word_contains(a, b) or word_contains(b, a)


def chart_dependencies(chart_dir: Path):
    """[(dependency_name, alias_or_empty), ...], in Chart.yaml order,
    for every chart_dir/Chart.yaml dependency — e.g.
    [("internetaakafhandeling", "ita"), ("openzaak", ""), ...]. [] if
    chart_dir has no Chart.yaml."""
    chart_yaml_path = chart_dir / "Chart.yaml"
    if not chart_yaml_path.is_file():
        return []
    chart_yaml = load_yaml(chart_yaml_path)
    return [(dep["name"], dep.get("alias", "")) for dep in chart_yaml.get("dependencies", [])]


def orphan_values_yaml_keys(chart_dir: Path, dependencies: list):
    """[(key, ""), ...] for every top-level key of chart_dir/values.yaml
    that isn't already a Chart.yaml dependency's own name or alias (see
    `dependencies`, from chart_dependencies) — e.g. "frankgateway", a
    values.yaml block templated directly by podiumd's own templates
    rather than backed by a separate Helm sub-chart, so it never appears
    in Chart.yaml's dependency list at all. [] if chart_dir has no
    values.yaml. component_and_alias only ever tries these as a last
    resort, after every real dependency, so an orphan key can never
    outrank (and thus never regress) a resolution that already works
    through a real dependency — e.g. values.yaml's own "keycloak" block
    (the Keycloak instance's own config, separate from the
    "keycloak-operator" dependency that manages it) must not hijack
    "Keycloak" away from correctly resolving to "keycloak-operator"."""
    values_yaml_path = chart_dir / "values.yaml"
    if not values_yaml_path.is_file():
        return []
    values = load_yaml(values_yaml_path)
    if not isinstance(values, dict):
        return []
    known = {normalize_name(dependency_name) for dependency_name, _ in dependencies}
    known |= {normalize_name(alias) for _, alias in dependencies if alias}
    return [(key, "") for key in values if normalize_name(key) not in known]


def global_image_keys(chart_dir: Path):
    """Every key under chart_dir/values.yaml's top-level global.images map
    (e.g. "nginx", "curl", "busybox") — base images hoisted out of any
    single component's own block specifically because they're shared via
    YAML anchor across multiple, unrelated components (see e.g. the
    &nginxImage anchor aliased under openzaak, opennotificaties,
    openformulieren, frankgateway, apiproxy, ... — nine call sites across
    distinct top-level values.yaml blocks). A key living here at all is
    proof by construction that it belongs to more than one component, so
    component_and_alias treats any match against one as MULTIPLE outright
    rather than guessing which single component "owns" it. [] if
    chart_dir has no values.yaml, or values.yaml has no global.images
    map."""
    values_yaml_path = chart_dir / "values.yaml"
    if not values_yaml_path.is_file():
        return []
    values = load_yaml(values_yaml_path)
    if not isinstance(values, dict):
        return []
    images = (values.get("global") or {}).get("images")
    return list(images) if isinstance(images, dict) else []


def _tier_matches(candidates: list[str], dependencies: list | tuple, predicate: Callable):
    """{dependency_name: alias} for every dependency in `dependencies`
    where `predicate(candidate, dependency_name, alias)` holds for at
    least one of `candidates` — every distinct dependency that matches
    at this priority tier, not just the first, so component_and_alias
    can tell a clean single match from a genuine ambiguity."""
    found = {}
    for candidate in candidates:
        for dependency_name, alias in dependencies:
            if dependency_name not in found and predicate(candidate, dependency_name, alias):
                found[dependency_name] = alias
    return found


# Tried in this order (first tier with any match wins) so a precise
# match always beats a fuzzier one — see component_and_alias. An EXACT
# alias match is its own tier, ahead of the looser alias *relation* tier
# below it: e.g. "kiss" exactly equals dependency "kiss-chart"'s own
# alias "kiss", and that must resolve outright rather than being treated
# as ambiguous with "eck-stack" (alias "kiss-eck") just because
# "kiss-eck" also happens to *contain* "kiss" as a substring.
_MATCH_TIERS = [
    lambda candidate, dependency_name, _alias: normalize_name(candidate) == normalize_name(dependency_name),
    lambda candidate, _dependency_name, alias: bool(alias) and normalize_name(candidate) == normalize_name(alias),
    lambda candidate, _dependency_name, alias: bool(alias) and _related(candidate, alias),
    lambda candidate, dependency_name, _alias: _related(candidate, dependency_name),
]

# The two EXACT-match tiers (candidate == dependency name/alias, no
# substring guessing) vs. the two looser RELATION tiers (candidate is a
# substring of, or contains, the dependency's name/alias) — split out so
# component_and_alias can check global_image_keys in between them: a
# global.images key is a much stronger "this is genuinely shared" signal
# than a coincidental loose substring hit (e.g. "redis" is a substring of
# the UNRELATED "redis-operator" dependency's own name — see
# component_and_alias's own docstring), so it must outrank the loose
# tiers, but an EXACT match to a real dependency/alias is even stronger
# still and must keep outranking everything.
_EXACT_TIERS = _MATCH_TIERS[:2]
_RELATION_TIERS = _MATCH_TIERS[2:]


def _resolve_against(candidates: list[str], dependencies: list | tuple, tiers: list | None = None):
    """(dependency_name, alias) from the first tier in `tiers` (default
    _MATCH_TIERS) with exactly one distinct match against `dependencies`,
    ("MULTIPLE", "MULTIPLE") from the first tier with more than one, or
    None if no tier matches anything at all (caller decides what None
    means)."""
    for tier in tiers if tiers is not None else _MATCH_TIERS:
        found = _tier_matches(candidates, dependencies, tier)
        if len(found) == 1:
            return next(iter(found.items()))
        if len(found) > 1:
            return ("MULTIPLE", "MULTIPLE")
    return None


def component_and_alias(
    name: str, dependencies: list, orphan_keys: list | tuple = (), global_image_key_names: list | tuple = ()
):
    """(component, alias) for `name` (the CSV "name" column value),
    resolved against `dependencies` (see chart_dependencies) by trying
    each of name_candidates(name) against every dependency's own
    normalized name and alias, in this priority order (first tier with
    any match wins):
    1. a candidate exactly equals the dependency's name — e.g. "Interne
       Taak Afhandeling" -> dependency "internetaakafhandeling"
    2. a candidate exactly equals the dependency's alias — e.g. "kiss"
       (used_by, or the bracketed part of "Contact (KISS)") exactly
       equals alias "kiss", or "PABC" (the bracketed part of "Platform
       Autorisatie Beheer Component (PABC)") exactly equals alias "pabc"
    3. a candidate relates (see _related, a looser substring-either-way
       check) to the dependency's alias — e.g. alias "zac" is contained
       in "Zaak - ZAC" (as "zaakzac")
    4. a candidate relates to the dependency's name — e.g. dependency
       name "openzaak" exactly equals "Open Zaak", or "openinwoner" is
       contained in "Open Inwoner platform" (the bracketed part of
       "Portaal (Open Inwoner platform)")
    Tiers 2 and 3 are both about the alias, split apart specifically so
    an exact alias match (tier 2) never loses to a same-tier ambiguity
    that only exists because some OTHER dependency's alias happens to
    contain the candidate as a substring (tier 3) — see _MATCH_TIERS.

    EXCEPTION: a tier-3/4 (loose-relation-only) single-dependency match
    is overridden to ("MULTIPLE", "MULTIPLE") if a candidate ALSO relates
    to one of `global_image_key_names` (see global_image_keys) — e.g. "Redis",
    the global.images.redis anchor, must resolve MULTIPLE even though
    "redis" happens to also be a loose substring of the wholly unrelated
    "redis-operator" dependency's own name (no alias, so it only ever
    matches there via tier 4, never exactly). A key living under
    global.images exists specifically because it's shared, via YAML
    anchor, across multiple unrelated components — a much stronger,
    deliberate "known shared" signal than a coincidental loose-relation
    hit against some other dependency's name, so it must win there. An
    EXACT match (tier 1/2) is stronger still and is never overridden this
    way — only ever a tier-3/4-only resolution is at risk of being a
    false positive like this.

    If nothing matches any real dependency at all (neither exactly nor
    loosely, before any global-image-key override above), falls back to
    trying the exact same tiers against `orphan_keys` (see
    orphan_values_yaml_keys) — values.yaml top-level blocks that aren't
    backed by any Chart.yaml dependency, like "frankgateway". This is
    strictly a last resort: a real dependency (via ANY tier, exact or
    loose) always wins first, so an orphan key can never hijack a name
    that already resolves through a real dependency.

    If NEITHER of those matches anything either, checks whether a
    candidate relates to one of `global_image_key_names` — same check as the
    override above, just as its own fallback tier now that no
    dependency/orphan-key match exists at all to override.

    ("UNKNOWN", "") if nothing matches at all, in any of the three pools
    — e.g. "Elastic operator", whose dependency "eck-operator" shares no
    text with it either way, or a component (like "Solr") that isn't a
    top-level podiumd Chart.yaml dependency, orphan values.yaml key, or
    global image key at all. ("MULTIPLE", "MULTIPLE") if a single tier
    matches more than one distinct dependency (or, in the orphan-key
    pool, more than one distinct orphan key), or if anything at all
    matches a global image key — rather than silently picking whichever
    came first."""
    candidates = _candidate_parts(name)

    def relates_to_global_key():
        return any(_related(candidate, key) for candidate in candidates for key in global_image_key_names)

    exact = _resolve_against(candidates, dependencies, _EXACT_TIERS)
    if exact:
        return exact
    loose = _resolve_against(candidates, dependencies, _RELATION_TIERS)
    if loose:
        if loose[0] != "MULTIPLE" and relates_to_global_key():
            return ("MULTIPLE", "MULTIPLE")
        return loose

    resolved = _resolve_against(candidates, orphan_keys)
    if resolved:
        return resolved

    if relates_to_global_key():
        return ("MULTIPLE", "MULTIPLE")
    return ("UNKNOWN", "")


def _exact_options(text: str, options):
    """{o for o in options if normalize_name(o) is one of name_candidates(text)}
    — the raw exact-tier match set exact_match and match_one both
    build on, factored out so neither recomputes it independently."""
    candidates = name_candidates(text)
    return {o for o in options if normalize_name(o) in candidates}


def exact_match(text: str, options: Collection):
    """The single option in `options` whose own normalize_name is exactly
    one of name_candidates(text) — None if none do, or more than one
    ties (an ambiguity, never a guess). This is match_one's own first,
    strongest tier, exposed separately so a caller can require JUST this
    level of confidence without also accepting its much weaker fuzzy-
    containment fallback (see lib.release_table.image_basenames, which
    lets a component's primary row claim this tier's match before any
    sibling row is even tried — safe only because an EXACT match is
    unambiguous on its own; the fuzzy tier is exactly where two
    textually-overlapping rows can genuinely disagree about which one a
    shared basename really belongs to)."""
    exact = _exact_options(text, options)
    return next(iter(exact)) if len(exact) == 1 else None


def match_one(text: str, options):
    """The single string in `options` that `text` unambiguously identifies
    — an exact match (see exact_match) if there is one, else the single
    option related to it (see _related) if there's exactly one such
    relation; None if nothing matches, or more than one option ties at
    the same tier — this never guesses between two equally-plausible
    options, the same "first tier with exactly one match wins" rule
    component_and_alias itself already applies to Chart.yaml dependencies
    (see _resolve_against), just reused here directly against a small
    set of strings instead of (name, alias) pairs."""
    exact = _exact_options(text, options)
    if exact:
        return next(iter(exact)) if len(exact) == 1 else None
    candidates = _candidate_parts(text)
    related = {o for o in options if any(_related(c, o) for c in candidates)}
    return next(iter(related)) if len(related) == 1 else None


def extra_scope_keys_by_component(chart_dir: Path):
    """{dependency_name: [orphan_key, ...]} for every orphan values.yaml
    key (see orphan_values_yaml_keys) that itself relates to exactly one
    real Chart.yaml dependency — e.g. orphan key "keycloak" (podiumd's
    own Keycloak instance config, values.yaml's separate top-level block
    from "keycloak-operator") relates to dependency "keycloak-operator"
    the exact same way component_and_alias would resolve it from row
    text, so that dependency's own image scan must ALSO look under
    "keycloak" — its actual app image (keycloak.image.tag) lives there,
    not under keycloak-operator's own key at all. Only ever ADDS a scope
    on top of a dependency's own key, mirroring component_and_alias's
    own real-dependency-first priority; an orphan key relating to more
    than one dependency (MULTIPLE) or none at all contributes nothing."""
    dependencies = chart_dependencies(chart_dir)
    orphan_keys = orphan_values_yaml_keys(chart_dir, dependencies)
    extra = {}
    for key, _ in orphan_keys:
        resolved = _resolve_against(_candidate_parts(key), dependencies)
        if resolved and resolved[0] != "MULTIPLE":
            extra.setdefault(resolved[0], []).append(key)
    return extra
