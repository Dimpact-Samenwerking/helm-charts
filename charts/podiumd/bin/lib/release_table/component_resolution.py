"""export-confluence-release-table's own name/alias -> Chart.yaml
dependency resolution (component_and_alias) and its supporting helpers,
split out of that script for pylint's too-many-lines check."""

import re

from collections.abc import Callable
from collections.abc import Collection
from collections.abc import Sequence
from pathlib import Path

from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.registered_paths import native_components
from lib.chart.values_tree_primitives import mapping_at
from lib.chart.values_tree_primitives import text_at
from lib.image.version import image_basename
from lib.upgradedoc.string_and_parsing_basics import normalize_name
from lib.yaml_types import load_yaml_mapping

BRACKETED_RE = re.compile(r"\(([^)]*)\)")


def name_candidates(name: str) -> list[str]:
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


# (dependency name, alias or "") for one Chart.yaml dependency, or
# (values.yaml key, "") for an orphan top-level key.
DependencyNames = tuple[str, str]


def chart_dependencies(chart_dir: Path) -> list[DependencyNames]:
    """[(dependency_name, alias_or_empty), ...], in Chart.yaml order,
    for every chart_dir/Chart.yaml dependency — e.g.
    [("internetaakafhandeling", "ita"), ("openzaak", ""), ...]. [] if
    chart_dir has no Chart.yaml."""
    chart_yaml_path = chart_dir / "Chart.yaml"
    if not chart_yaml_path.is_file():
        return []
    return [(dep["name"], dep.get("alias", "")) for dep in load_chart_dependencies(chart_yaml_path)]


def orphan_values_yaml_keys(chart_dir: Path, dependencies: Sequence[DependencyNames]) -> list[DependencyNames]:
    """[(key, ""), ...] for every top-level key of chart_dir/values.yaml
    that isn't already a Chart.yaml dependency's own name or alias (see
    `dependencies`, from chart_dependencies) — e.g. "frankgateway", a
    values.yaml block templated directly by podiumd's own templates
    rather than backed by a separate Helm sub-chart, so it never appears
    in Chart.yaml's dependency list at all. [] if chart_dir has no
    values.yaml. component_and_alias only ever tries these as a last
    resort, after every real dependency, so an orphan key can never
    outrank (and thus never regress) a resolution that already works
    through a real dependency. A native component's key (see
    native_component_keys) is an orphan key too, but component_and_alias
    tries it together with the real dependencies."""
    values_yaml_path = chart_dir / "values.yaml"
    if not values_yaml_path.is_file():
        return []
    values = load_yaml_mapping(values_yaml_path)
    known = {normalize_name(dependency_name) for dependency_name, _ in dependencies}
    known |= {normalize_name(alias) for _, alias in dependencies if alias}
    return [(key, "") for key in values if normalize_name(key) not in known]


def native_component_keys(chart_dir: Path) -> list[DependencyNames]:
    """[(name, ""), ...] for every lib.chart.registered_paths.
    native_components entry (e.g. "frankgateway", "keycloak"): a real
    component without a Chart.yaml dependency, which component_and_alias
    matches exactly just like a dependency's own name."""
    return [(name, "") for name in sorted(native_components(chart_dir))]


def global_image_keys(chart_dir: Path) -> list[str]:
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
    return list(mapping_at(load_yaml_mapping(values_yaml_path), "global.images"))


def global_image_basenames(chart_dir: Path) -> dict[str, str]:
    """{global.images key: its image basename} for every global_image_keys
    entry with a repository — e.g. {"nginx": "nginx-unprivileged"}."""
    values_yaml_path = chart_dir / "values.yaml"
    if not values_yaml_path.is_file():
        return {}
    global_images = mapping_at(load_yaml_mapping(values_yaml_path), "global.images")
    basenames: dict[str, str] = {}
    for key in global_images:
        repo = text_at(global_images, f"{key}.repository")
        if repo:
            basenames[key] = image_basename(repo)
    return basenames


def global_image_names(chart_dir: Path) -> list[str]:
    """global_image_keys plus each entry's own image basename (see
    global_image_basenames), e.g. "nginx" and "nginx-unprivileged" — the
    names a MULTIPLE row may use to name a shared image exactly (see
    component_and_alias)."""
    return list(dict.fromkeys([*global_image_keys(chart_dir), *global_image_basenames(chart_dir).values()]))


# predicate(candidate, dependency_name, alias) for one _MATCH_TIERS tier.
MatchTier = Callable[[str, str, str | None], bool]


def _tier_matches(
    candidates: list[str], dependencies: Sequence[DependencyNames], predicate: MatchTier
) -> dict[str, str]:
    """{dependency_name: alias} for every dependency in `dependencies`
    where `predicate(candidate, dependency_name, alias)` holds for at
    least one of `candidates` — every distinct dependency that matches
    at this priority tier, not just the first, so component_and_alias
    can tell a clean single match from a genuine ambiguity."""
    found: dict[str, str] = {}
    for candidate in candidates:
        for dependency_name, alias in dependencies:
            if dependency_name not in found and predicate(candidate, dependency_name, alias):
                found[dependency_name] = alias
    return found


# Tried in this order (first tier with any match wins): a candidate
# exactly equals the dependency's name, then its alias. Only exact
# matches, never a substring relation: a Confluence name that doesn't
# name its component exactly must be fixed there, not guessed at here.
_MATCH_TIERS: list[MatchTier] = [
    lambda candidate, dependency_name, _alias: normalize_name(candidate) == normalize_name(dependency_name),
    lambda candidate, _dependency_name, alias: bool(alias) and normalize_name(candidate) == normalize_name(alias),
]


def _resolve_against(candidates: list[str], dependencies: Sequence[DependencyNames]) -> DependencyNames | None:
    """(dependency_name, alias) from the first _MATCH_TIERS tier with
    exactly one distinct match against `dependencies`, ("MULTIPLE",
    "MULTIPLE") from the first tier with more than one, or None if no
    tier matches anything at all (caller decides what None means)."""
    for tier in _MATCH_TIERS:
        found = _tier_matches(candidates, dependencies, tier)
        if len(found) == 1:
            return next(iter(found.items()))
        if len(found) > 1:
            return ("MULTIPLE", "MULTIPLE")
    return None


def component_and_alias(
    name: str,
    dependencies: Sequence[DependencyNames],
    orphan_keys: Sequence[DependencyNames] = (),
    global_image_key_names: Sequence[str] = (),
    native_keys: Sequence[DependencyNames] = (),
) -> DependencyNames:
    """(component, alias) for `name` (the CSV "used_by" value, else its
    "name"), resolved by EXACT matching only: one of name_candidates(name)
    — the whole text, or for "... (bracketed part)" either part — must
    equal a name or alias after normalize_name. Tried in this order:
    1. `dependencies` (see chart_dependencies) and `native_keys` (see
       native_component_keys) together: a candidate equals a Chart.yaml
       dependency's or native component's name — e.g. "Interne Taak
       Afhandeling" -> "internetaakafhandeling", "Keycloak" ->
       native "keycloak", "Keycloak operator" -> "keycloak-operator" —
       else a dependency's alias — e.g. "Contact (KISS)" -> alias
       "kiss", "Zaak - ZAC (zaakafhandelcomponent)" -> via either part.
    2. `orphan_keys` (see orphan_values_yaml_keys), the same two tiers.
    3. `global_image_key_names` (see global_image_names): a candidate
       equals a global.images key or its image basename — e.g. "Nginx
       (unprivileged)" -> ("MULTIPLE", "MULTIPLE"), an image shared
       across components.
    ("MULTIPLE", "MULTIPLE") too when one tier matches more than one
    distinct name; ("UNKNOWN", "") when nothing matches exactly — the
    export warns, and the Confluence name needs an exact part (e.g.
    "<readable name> (<chart name or alias>)")."""
    candidates = _candidate_parts(name)
    resolved = _resolve_against(candidates, [*dependencies, *native_keys]) or _resolve_against(candidates, orphan_keys)
    if resolved:
        return resolved
    if _exact_options(name, global_image_key_names):
        return ("MULTIPLE", "MULTIPLE")
    return ("UNKNOWN", "")


def _exact_options(text: str, options: Collection[str]) -> set[str]:
    """{o for o in options if normalize_name(o) is one of name_candidates(text)}."""
    candidates = name_candidates(text)
    return {o for o in options if normalize_name(o) in candidates}


def exact_match(text: str, options: Collection[str]) -> str | None:
    """The single option in `options` whose own normalize_name is exactly
    one of name_candidates(text) — None if none do, or more than one
    ties (an ambiguity, never a guess)."""
    exact = _exact_options(text, options)
    return next(iter(exact)) if len(exact) == 1 else None
