"""export-confluence-release-table's resolution of a Confluence name to a Chart.yaml dependency."""

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
    """Normalized strings to match for `name`: the whole, and for "... (bracketed part)" each part too.

    E.g. "Platform Autorisatie Beheer Component (PABC)" also tries "pabc".
    Matching parts separately avoids matches spanning the part boundary.
    """
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
    """[(dependency_name, alias_or_empty), ...] in Chart.yaml order; [] without a Chart.yaml."""
    chart_yaml_path = chart_dir / "Chart.yaml"
    if not chart_yaml_path.is_file():
        return []
    return [(dep["name"], dep.get("alias", "")) for dep in load_chart_dependencies(chart_yaml_path)]


def orphan_values_yaml_keys(chart_dir: Path, dependencies: Sequence[DependencyNames]) -> list[DependencyNames]:
    """[(key, ""), ...] for top-level values.yaml keys that aren't a dependency name or alias.

    E.g. frankgateway. component_and_alias tries these last so they never
    outrank a real dependency. [] without a values.yaml.
    """
    values_yaml_path = chart_dir / "values.yaml"
    if not values_yaml_path.is_file():
        return []
    values = load_yaml_mapping(values_yaml_path)
    known = {normalize_name(dependency_name) for dependency_name, _ in dependencies}
    known |= {normalize_name(alias) for _, alias in dependencies if alias}
    return [(key, "") for key in values if normalize_name(key) not in known]


def native_component_keys(chart_dir: Path) -> list[DependencyNames]:
    """[(name, ""), ...] for every native component (e.g. frankgateway, keycloak)."""
    return [(name, "") for name in sorted(native_components(chart_dir))]


def global_image_keys(chart_dir: Path) -> list[str]:
    """Keys of values.yaml's global.images (e.g. nginx, curl); [] if absent.

    These are shared via anchors by construction, so a match means MULTIPLE.
    """
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
    """global_image_keys plus their image basenames: the names a MULTIPLE row may use."""
    return list(dict.fromkeys([*global_image_keys(chart_dir), *global_image_basenames(chart_dir).values()]))


# predicate(candidate, dependency_name, alias) for one _MATCH_TIERS tier.
MatchTier = Callable[[str, str, str | None], bool]


def _tier_matches(
    candidates: list[str], dependencies: Sequence[DependencyNames], predicate: MatchTier
) -> dict[str, str]:
    """{dependency_name: alias} for every dependency matching any candidate at this tier (to detect ambiguity)."""
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
    """(dependency_name, alias) from the first matching tier, ("MULTIPLE", "MULTIPLE") if ambiguous, or None."""
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
    """(component, alias) for `name` (CSV "used_by", else "name"), by exact matching only.

    A name_candidates(name) entry must equal a name or alias after
    normalize_name. Tried in order:
    1. Dependencies and native components: name (e.g. "Keycloak operator"
       -> keycloak-operator), then alias (e.g. "Contact (KISS)" -> kiss).
    2. Orphan values.yaml keys, the same two tiers.
    3. A global.images key or basename (e.g. "Nginx (unprivileged)") ->
       ("MULTIPLE", "MULTIPLE").
    Several matches in one tier also give MULTIPLE; no match gives
    ("UNKNOWN", ""), and the Confluence name must be fixed, e.g. to
    "<readable name> (<chart name or alias>)".
    """
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
    """The one option whose normalize_name is in name_candidates(text); None if none or several."""
    exact = _exact_options(text, options)
    return next(iter(exact)) if len(exact) == 1 else None
