"""export-confluence-release-table's own resolve_image_basenames and its
supporting helpers, split out of that script for pylint's too-many-lines
check."""

from pathlib import Path

from lib.chart.release_baseline_basics import load_yaml
from lib.image.version import basenames_under_scope
from lib.image.version import basenames_under_scope_any_tag
from lib.image.version import image_basename
from lib.release_table.component_resolution import exact_match
from lib.release_table.component_resolution import extra_scope_keys_by_component
from lib.release_table.component_resolution import global_image_keys
from lib.release_table.component_resolution import match_one


def resolve_image_basenames(rows: list, chart_dir: Path):
    """A comma-joined image_basename string per row in `rows` (same
    order, same shape as extract_release_rows' own output — [section,
    vendor, used_by, name, component, alias, ...versions]) — the actual
    values.yaml repository basename(s) each row's version numbers
    describe. Matches each row's own "used by"-tagged sibling images by
    NAME against the candidate basenames found under its component's own
    values.yaml subtree (see basenames_under_scope + match_one) — not
    by values-tree PATH, since a path segment often describes a job's
    ROLE ("ensurePodiumdAdminUser") rather than the image itself
    ("python"), and keys mix kebab-case/camelCase inconsistently, while
    the actual repository basename is exactly the thing a human-curated
    name is written to describe.

    A component's scope isn't only its own top-level values.yaml key —
    it also includes any orphan key that itself resolves to that same
    dependency (see extra_scope_keys_by_component), since a
    component's actual image sometimes lives under a values.yaml block
    that predates/sits outside the Chart.yaml dependency that now
    manages it (e.g. keycloak-operator's own "Keycloak" row resolves its
    image under the separate "keycloak" block, not "keycloak-operator"
    itself). How "available" basenames are gathered for a scope (the
    digest-required scan, then a per-basename digest-optional fallback)
    is documented on _available_basenames_for_component; how they're
    then claimed — primary-exact-match first, then used_by-tagged
    siblings, then whatever's left to any unclaimed primary — is
    documented on _assign_component_basenames. A MULTIPLE row resolves
    independently via which global.images key it actually matches (see
    _assign_multiple_row_basenames/global_image_keys) — never through a
    component's own scope, since by definition it isn't owned by any
    single one. "" wherever nothing can be resolved (component UNKNOWN/
    blank, or a genuinely ambiguous or missing match) — never a
    guess."""
    values_path = chart_dir / "values.yaml"
    if not values_path.is_file():
        return ["" for _ in rows]
    lines = values_path.read_text(encoding="utf-8").splitlines()
    values = load_yaml(values_path) or {}
    global_keys = global_image_keys(chart_dir)
    global_images = (values.get("global") or {}).get("images") or {}

    result = [""] * len(rows)
    extra_scopes = extra_scope_keys_by_component(chart_dir)
    by_component = _by_component_row_indices(rows)

    for component, info in by_component.items():
        scope_keys = [info["alias"] or component, *extra_scopes.get(component, [])]
        available = _available_basenames_for_component(lines, scope_keys)
        _assign_component_basenames(rows, result, info, available)

    _assign_multiple_row_basenames(rows, result, global_keys, global_images)

    return result


def _by_component_row_indices(rows: list):
    """component -> {"alias": ..., "indices": [...]} grouping resolve_
    image_basenames' own per-component pass — a MULTIPLE/UNKNOWN/blank-
    component row is never grouped here, only handled by _assign_
    multiple_row_basenames instead."""
    by_component = {}
    for i, row in enumerate(rows):
        component, alias = row[4], row[5]
        if component in ("MULTIPLE", "UNKNOWN", ""):
            continue
        by_component.setdefault(component, {"alias": alias, "indices": []})["indices"].append(i)
    return by_component


def _available_basenames_for_component(lines: list[str], scope_keys: list[str]):
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
    available = {}
    for scope_key in scope_keys:
        for basename, pins in basenames_under_scope(lines, scope_key).items():
            available.setdefault(basename, []).extend(pins)
    for scope_key in scope_keys:
        for basename, pins in basenames_under_scope_any_tag(lines, scope_key).items():
            if basename not in available:
                available[basename] = pins
    return available


def _assign_component_basenames(rows: list, result: list[str], info: dict, available: dict):
    """Claims `available` basenames into `result` for one component's
    own row indices (info["indices"]) — a primary (used_by-blank) row
    gets first refusal, but ONLY at an EXACT match against its own name
    (see exact_match) — claimed BEFORE any used_by-tagged sibling gets
    a turn, so a component whose own default image basename happens to
    EQUAL its plain display name outright (e.g. frankgateway's own
    "frank-gateway" image) can't be mistakenly grabbed by a sibling row
    instead, just because every "<Component> <Role>"-named sibling's
    text trivially contains that same shared component-name prefix too.
    Deliberately NOT extended to match_one's weaker fuzzy-containment
    tier: a primary row's name merely CONTAINING a basename (e.g. "Redis
    Operator" containing "redis") is exactly the ambiguous case where a
    sibling ("Redis-ha") can be the more specific, correct owner instead
    — letting primary win there too regressed that case while fixing
    frankgateway (verified against real data). Every used_by-tagged
    sibling row then claims its own match via the weaker match_one,
    and finally whatever's left unclaimed is handed to any primary row
    that didn't exactly match anything — e.g. zgw-office-addin's
    frontend AND backend both landing on "Office Add-in"."""
    sub_indices = [i for i in info["indices"] if rows[i][2]]
    primary_indices = [i for i in info["indices"] if not rows[i][2]]

    unclaimed_primary_indices = []
    for i in primary_indices:
        match = exact_match(rows[i][3], available.keys())
        if match is not None:
            result[i] = match
            del available[match]
        else:
            unclaimed_primary_indices.append(i)

    for i in sub_indices:
        match = match_one(rows[i][3], available.keys())
        if match is not None:
            result[i] = match
            del available[match]

    if unclaimed_primary_indices and available:
        basenames = ",".join(sorted(available))
        for i in unclaimed_primary_indices:
            result[i] = basenames


def _assign_multiple_row_basenames(rows: list, result: list[str], global_keys: list, global_images: dict):
    """Resolves every MULTIPLE-component row's own basename
    independently, via which global.images key it actually matches (see
    global_image_keys) — never through any component's own scope, since
    by definition a MULTIPLE row isn't owned by any single one."""
    for i, row in enumerate(rows):
        used_by, name, component = row[2], row[3], row[4]
        if component != "MULTIPLE":
            continue
        matched_key = match_one(used_by or name, global_keys)
        if matched_key is None:
            continue
        repo = (global_images.get(matched_key) or {}).get("repository")
        if repo:
            result[i] = image_basename(repo)
