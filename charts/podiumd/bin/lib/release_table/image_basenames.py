"""export-confluence-release-table's own resolve_image_basenames and its
supporting helpers, split out of that script for pylint's too-many-lines
check."""

from pathlib import Path
from typing import TypedDict

from lib.chart.registered_paths import image_paths_for
from lib.chart.values_tree_primitives import dotted_key_path
from lib.image.digests import DigestPin
from lib.image.digests import VersionPin
from lib.image.version import basenames_under_scope
from lib.image.version import basenames_under_scope_any_tag
from lib.release_table.component_resolution import exact_match
from lib.release_table.component_resolution import global_image_basenames


class ComponentRows(TypedDict):
    """One component's rows in resolve_image_basenames: the alias its
    rows name ("" for none) and their indices."""

    alias: str
    indices: list[int]


def resolve_image_basenames(rows: list[list[str]], chart_dir: Path) -> list[str]:
    """A comma-joined image_basename string per row in `rows` (same
    order, same shape as extract_release_rows' own output — [section,
    vendor, used_by, name, component, alias, ...versions]) — the actual
    values.yaml repository basename(s) each row's version numbers
    describe, resolved by EXACT matching only (see lib.release_table.
    component_resolution.exact_match) against the basenames found under
    the component's own values.yaml key (see
    _available_basenames_for_component):
    - a "used by"-tagged row names its image exactly, e.g. "Frank
      Gateway Etcd (etcd)";
    - a component's own row (no "used by") gets the basename its name
      matches exactly (e.g. "Keycloak"), else every basename on one of
      the component's registered primary image paths (image_paths_for)
      that no "used by" row claimed — see _assign_component_basenames;
    - a MULTIPLE row names a global.images key or its image basename
      exactly, e.g. "Nginx (unprivileged)" — see
      _assign_multiple_row_basenames.
    "" wherever nothing resolves exactly — never a guess."""
    values_path = chart_dir / "values.yaml"
    if not values_path.is_file():
        return ["" for _ in rows]
    lines = values_path.read_text(encoding="utf-8").splitlines()

    result = [""] * len(rows)
    by_component = _by_component_row_indices(rows)

    for component, info in by_component.items():
        scope_key = info["alias"] or component
        available = _available_basenames_for_component(lines, [scope_key])
        primary = _registered_primary_basenames(lines, scope_key, image_paths_for(component, chart_dir), available)
        _assign_component_basenames(rows, result, info, available, primary)

    _assign_multiple_row_basenames(rows, result, global_image_basenames(chart_dir))

    return result


def _by_component_row_indices(rows: list[list[str]]) -> dict[str, ComponentRows]:
    """component -> {"alias": ..., "indices": [...]} grouping resolve_
    image_basenames' own per-component pass — a MULTIPLE/UNKNOWN/blank-
    component row is never grouped here, only handled by _assign_
    multiple_row_basenames instead."""
    by_component: dict[str, ComponentRows] = {}
    for i, row in enumerate(rows):
        component, alias = row[4], row[5]
        if component in ("MULTIPLE", "UNKNOWN", ""):
            continue
        by_component.setdefault(component, {"alias": alias, "indices": []})["indices"].append(i)
    return by_component


def _available_basenames_for_component(
    lines: list[str], scope_keys: list[str]
) -> dict[str, list[DigestPin | VersionPin]]:
    """basename -> pins available under scope_keys: the digest-required
    scan (basenames_under_scope) first, then, before concluding a
    basename genuinely isn't resolvable, falling back per-basename to
    the digest-OPTIONAL sibling scan (basenames_under_scope_any_tag)
    for any basename the digest-required scan alone didn't find under
    ANY of these scope_keys — two independent real cases need this:
    omc's own image tag genuinely has no digest at all (its subchart
    can't handle one), so ALL of its basenames only ever show up here;
    keycloak-operator's own operator.config.keycloakImage is genuinely
    digest-pinned (a separate sibling "sha:" field, not embedded in
    "tag:"), so only THAT ONE basename ("keycloak") needs this
    fallback, while its sibling "python"/"keycloak-config-cli"
    basenames already resolve via the digest-required scan. A per-
    basename fallback (never a whole-scope "if not available" gate,
    which left keycloak-operator's own case unresolved even though its
    scope wasn't otherwise empty) handles both the same way,
    deliberately only ADDING a basename the digest-required scan
    missed, never overriding one it already found (so a component
    that's fully digest-pinned, the normal case, is completely
    unaffected — this scan is strictly additive)."""
    available: dict[str, list[DigestPin | VersionPin]] = {}
    for scope_key in scope_keys:
        for basename, pins in basenames_under_scope(lines, scope_key).items():
            available.setdefault(basename, []).extend(pins)
    for scope_key in scope_keys:
        for basename, pins in basenames_under_scope_any_tag(lines, scope_key).items():
            if basename not in available:
                available[basename] = [*pins]
    return available


def _registered_primary_basenames(
    lines: list[str], scope_key: str, primary_paths: list[str], available: dict[str, list[DigestPin | VersionPin]]
) -> set[str]:
    """The `available` basenames with a pin on one of the component's
    registered primary image paths (`primary_paths`, from
    image_paths_for, relative to `scope_key`) — e.g. pabc's "pabc-api"
    and "pabc-migrations" for ["image", "migrations.image"]."""
    registered = {f"{scope_key}.{path}.tag" for path in primary_paths}
    return {
        basename
        for basename, pins in available.items()
        if any(dotted_key_path(lines, pin["line"] - 1) in registered for pin in pins)
    }


def _assign_component_basenames(
    rows: list[list[str]],
    result: list[str],
    info: ComponentRows,
    available: dict[str, list[DigestPin | VersionPin]],
    primary: set[str],
) -> None:
    """Claims `available` basenames into `result` for one component's
    own row indices (info["indices"]), exact matches only (see
    exact_match):
    1. a component row (no "used by") whose name matches a basename
       exactly claims it — first, so a "<Component> <Role>" sibling can
       never take the component's own image (real case: frankgateway's
       own "frank-gateway" image, and openbao's server image, which has
       no tag pin of its own and only shows up as "openbao");
    2. every "used by" row claims the basename its name matches exactly;
    3. every still-unclaimed component row gets the remaining `primary`
       basenames (the registered primary image paths, see
       _registered_primary_basenames) — e.g. zgw-office-addin's frontend
       AND backend both landing on "ZGW Office Add-in"."""
    sub_indices = [i for i in info["indices"] if rows[i][2]]
    primary_indices = [i for i in info["indices"] if not rows[i][2]]

    unclaimed_primary_indices: list[int] = []
    for i in primary_indices:
        match = exact_match(rows[i][3], available.keys())
        if match is not None:
            result[i] = match
            del available[match]
        else:
            unclaimed_primary_indices.append(i)

    for i in sub_indices:
        match = exact_match(rows[i][3], available.keys())
        if match is not None:
            result[i] = match
            del available[match]

    remaining = sorted(basename for basename in available if basename in primary)
    if unclaimed_primary_indices and remaining:
        for i in unclaimed_primary_indices:
            result[i] = ",".join(remaining)


def _assign_multiple_row_basenames(rows: list[list[str]], result: list[str], basename_by_key: dict[str, str]) -> None:
    """Resolves every MULTIPLE-component row's own basename
    independently, via the global.images entry it names exactly — by
    its key ("Nginx (unprivileged)" -> "nginx"), else by its image
    basename ("... (nginx-unprivileged)") — never through any component's own
    scope, since by definition a MULTIPLE row isn't owned by any single
    one."""
    for i, row in enumerate(rows):
        used_by, name, component = row[2], row[3], row[4]
        if component != "MULTIPLE":
            continue
        key = exact_match(used_by or name, basename_by_key.keys())
        if key is not None:
            result[i] = basename_by_key[key]
        else:
            result[i] = exact_match(used_by or name, basename_by_key.values()) or ""
