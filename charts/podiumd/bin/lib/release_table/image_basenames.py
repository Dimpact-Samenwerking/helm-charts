"""export-confluence-release-table's resolution of each row's image basename(s)."""

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
    """A comma-joined image_basename per row of `rows`, by exact matching only; "" if unresolved.

    - A "used by" row names its image exactly, e.g. "Frank Gateway Etcd (etcd)".
    - A component row gets the basename its name matches, else the
      unclaimed basenames on its registered primary image paths.
    - A MULTIPLE row names a global.images key or basename exactly.
    """
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
    """component -> {"alias", "indices"}; MULTIPLE/UNKNOWN/blank rows are left out."""
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
    """basename -> pins under scope_keys: digest-pinned first, plus bare-tag pins for missing basenames.

    The per-basename fallback covers omc (no digests at all) and
    keycloak-operator's keycloakImage (digest in a sibling "sha:" field)
    without changing fully digest-pinned components.
    """
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
    """The `available` basenames pinned on a registered primary image path (relative to `scope_key`)."""
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
    """Assign `available` basenames to one component's rows, exact matches only.

    1. A component row whose name matches a basename claims it first, so a
       "<Component> <Role>" row can't take the component's own image.
    2. Each "used by" row claims the basename its name matches.
    3. Remaining component rows get the unclaimed primary basenames (e.g.
       zgw-office-addin's frontend and backend).
    """
    sub_indices = [i for i in info["indices"] if rows[i][2]]
    primary_indices = [i for i in info["indices"] if not rows[i][2]]

    def claim(indices: list[int]) -> list[int]:
        """Give each row the available basename its name matches exactly; returns the rows left without one."""
        unclaimed: list[int] = []
        for i in indices:
            match = exact_match(rows[i][3], available.keys())
            if match is None:
                unclaimed.append(i)
                continue
            result[i] = match
            del available[match]
        return unclaimed

    unclaimed_primary_indices = claim(primary_indices)
    claim(sub_indices)

    remaining = sorted(basename for basename in available if basename in primary)
    if unclaimed_primary_indices and remaining:
        for i in unclaimed_primary_indices:
            result[i] = ",".join(remaining)


def _assign_multiple_row_basenames(rows: list[list[str]], result: list[str], basename_by_key: dict[str, str]) -> None:
    """Resolve each MULTIPLE row's basename via the global.images key or basename it names exactly."""
    for i, row in enumerate(rows):
        used_by, name, component = row[2], row[3], row[4]
        if component != "MULTIPLE":
            continue
        key = exact_match(used_by or name, basename_by_key.keys())
        if key is not None:
            result[i] = basename_by_key[key]
        else:
            result[i] = exact_match(used_by or name, basename_by_key.values()) or ""
