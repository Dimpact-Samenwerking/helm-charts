"""resolve_component_row: builds a single Component-versions-table
row (and whether its Changes heading needs an app-version segment)
for one dependency/native-component/sidecar, resolving its actual
app version from values.yaml/Chart.yaml/vendored subcharts."""

import re

from lib.chart import (
    baseline_tag_for_sidecar_path,
    historical_app_version_for_path,
    paths_by_repository,
)
from lib.chart_pull_and_subchart_resolution import global_image_paths
from lib.chart_registered_paths import (
    image_paths_for,
    native_components,
)
from lib.chart_values_tree_primitives import get_path
from lib.upgradedoc_app_version_and_image_paths import (
    actual_app_version,
    find_image_tag_paths,
)
from lib.upgradedoc_string_and_parsing_basics import (
    match_dependency_excluding_sidecar_names,
    match_native_component,
)


def changes_heading_has_app_version(heading):
    """Whether a "### ..." Changes heading's own text shows an app-
    version pair at all. make_changes_section's own template writes the
    app version as "<old> → <new>" when it changed, "<new> (unchanged)"
    when old==new, or "<new> (new)" when there's no baseline to compare
    against at all (see make_changes_section's own docstring) —
    immediately after the component name, in all three shapes. The
    "(chart ...)" clause that may follow uses the exact same "X →
    Y"/"X, unchanged"/"X, new" family for the CHART side, independently
    of the app side, so it's stripped before checking: a heading like
    "openbao v2.5.5 (new) (chart 0.28.4, unchanged)" must not read the
    chart clause's own "(... unchanged)" as if it were the app side's.
    A heading with no arrow/"(new)"/"(unchanged)" anywhere outside that
    clause (real case: "### openbao 0.28.4" — add_missing_component_
    rows' own chart-only TODO-stub shape, used when actual_app_version
    couldn't resolve anything at all at the time) reliably signals no
    app version was ever written."""
    without_chart_clause = re.sub(r"\(chart[^)]*\)", "", heading)
    return (
        "→" in without_chart_clause
        or "->" in without_chart_clause
        or "(new)" in without_chart_clause
        or "(unchanged)" in without_chart_clause
    )


def sidecar_tag(values, sidecar_path):
    """The tag pinned at a sidecar's own values-tree path (as returned by
    lib.chart.canonical_sidecar_row_names — already ending in the real
    image key itself, e.g. "initImage", not a hardcoded "image") —
    deliberately NOT actual_app_version, whose default_image_paths
    fallback always appends ".image.tag" regardless of the sidecar's
    real trailing key, silently resolving to an unrelated sibling
    image's tag whenever that key isn't literally "image" (e.g.
    keycloak-operator's own ensurePodiumdAdminUser job pins BOTH
    "image" and "initImage" — stripping the trailing key and re-
    guessing ".image.tag" would compare the row against the wrong one
    of the two)."""
    tag = get_path(values, ".".join(sidecar_path) + ".tag")
    return tag.split("@", 1)[0] if isinstance(tag, str) and tag else None


def resolve_component_row(
    row_name,
    chart_dir,
    canonical_names,
    deps,
    values,
    baseline_deps=None,
    baseline_values=None,
    upgrade_docs_baseline=None,
):
    """Resolve a "Component versions" table row's name to the real
    component it identifies, and its actual target (and, if requested,
    source) versions — the one place both fix-doc-consistency's row-
    rewriter (fix_component_version_table) and lib.docs_consistency's
    row-checker (check_docs_consistency) resolve a row, so the two can't
    quietly drift apart on what a row's real versions are again — they
    already had: the checker used to call plain match_dependency for the
    baseline-side lookup instead of match_dependency_excluding_sidecar_
    names, and had no way to flag a row whose baseline version simply
    couldn't be resolved at all (no matching Chart.yaml dependency at
    that ref, or a sidecar tag missing there) — the fixer already
    tracked that itself (as its own "unresolved" bucket, left the row
    untouched, and told the operator to review by hand), but the
    checker silently reported such a row as clean, since it never
    compares against a baseline value it never got.

    canonical_names is lib.chart.canonical_sidecar_row_names(...)'s own
    {row name: values-tree path} map — computed once by the caller,
    since both callers already need it for other rows too.

    Pass `baseline_deps=None` (the default) to skip baseline resolution
    entirely — `baseline_resolved` then stays None, not False, so a
    caller that deliberately isn't checking a baseline (no
    upgrade_docs_baseline given) can tell that apart from a baseline
    that was requested but couldn't be resolved for this one component.

    A kind's own baseline-app lookup can resolve to None because
    there's simply nothing for it in baseline_values (sidecar_path/
    values_key didn't exist there at all — real cases: redis-operator's
    own "k8s" sidecar and brppersonenmock's own "image:" block, both
    absent from baseline_values despite brppersonenmock's Chart.yaml
    dependency line predating this release) — that's the correct,
    authoritative "(new)" signal; the source version comes strictly
    from this direct git-baseline read, never a fallback to images-
    baseline.yaml (which only ever tracks ACR-mirror digest provenance,
    a genuinely different, unrelated question).

    The sidecar kind's own baseline_app isn't immediately "(new)" just
    because sidecar_path has no EXACT match in baseline_values, though —
    see the sidecar branch below for the two fallback tiers tried first:
    lib.chart.baseline_tag_for_sidecar_path (this same repository
    elsewhere in baseline_values — the SAME function lib.image_docs.
    add_missing_sidecar_rows' own "Component versions" table row uses,
    so the two can never resolve a different baseline version for the
    same path again — they already had: this heading kept rendering
    "(new)" for a row whose table cell already correctly showed the
    real prior version), then, only once that finds nothing either, a
    past images-<version>.yaml manifest.

    Returns a dict:
      {"kind": "unmatched"}
          row_name matches neither a Chart.yaml dependency, a
          canonical sidecar/shared-image name, nor a native_components
          component (see lib.chart.native_components) — nothing else to
          resolve. Deliberately NOT resolved any further here: a row
          shaped like the canonical sidecar form ("<key> - <basename>")
          but with no matching entry in canonical_names must never fall
          through to a fuzzy match_dependency lookup and get treated as
          the unrelated real dependency its leading word happens to
          share — see match_dependency_excluding_sidecar_names.
      {"kind": "sidecar" | "dependency" | "native",
       "dep": <Chart.yaml dependency dict> or None (sidecar/native case),
       "sidecar_path": <tuple> or None (dependency/native case),
       "values_key": ..., "top_level_key": ...,
       "target_chart": ... or None (sidecar/native: always None — no
           chart version of its own to verify against),
       "target_app": ... or None,
       "baseline_resolved": None (baseline_deps was None) | bool,
       "baseline_chart": ... or None,
       "baseline_app": ... or None}"""
    sidecar_path = canonical_names.get(row_name)
    dep = None if sidecar_path is not None else match_dependency_excluding_sidecar_names(row_name, deps)
    # native_components component (see lib.chart.native_components) — no
    # Chart.yaml dependency at all, checked only once neither of the above
    # matched, same precedence match_native_component's other callers use.
    native_key = (
        None
        if (sidecar_path is not None or dep is not None)
        else match_native_component(row_name, native_components(chart_dir))
    )

    if sidecar_path is None and dep is None and native_key is None:
        return {"kind": "unmatched"}

    result = {"dep": dep, "sidecar_path": sidecar_path}

    if sidecar_path is not None:
        result["kind"] = "sidecar"
        result["values_key"] = ".".join(sidecar_path)
        result["top_level_key"] = sidecar_path[0]
        result["target_chart"] = None
        result["target_app"] = sidecar_tag(values, sidecar_path)
    elif dep is not None:
        values_key = dep.get("alias", dep["name"])
        result["kind"] = "dependency"
        result["values_key"] = values_key
        result["top_level_key"] = values_key
        result["target_chart"] = str(dep["version"])
        result["target_app"] = actual_app_version(values, values_key, dep["name"], chart_dir=chart_dir, dep=dep)
    else:
        # No chart at all to verify against (never even attempted) — same
        # "-" not-applicable convention a sidecar's own chart-less cell
        # already uses (see component_version_cell), just via a different
        # kind here since a native component's TARGET APP still needs
        # resolving (a sidecar's target_app comes from sidecar_tag, a real
        # dependency's from actual_app_version — a native component is
        # its own top-level key, so it's the latter, keyed on itself).
        result["kind"] = "native"
        result["values_key"] = native_key
        result["top_level_key"] = native_key
        result["target_chart"] = None
        result["target_app"] = actual_app_version(values, native_key, native_key)

    result["baseline_resolved"] = None
    result["baseline_chart"] = None
    result["baseline_app"] = None

    if baseline_deps is not None:
        baseline_values = baseline_values or {}
        if sidecar_path is not None:
            # baseline_tag_for_sidecar_path's own tier-1 (exact-path,
            # via baseline_paths below) resolves to the exact same value
            # sidecar_tag(baseline_values, sidecar_path) would — called
            # through the shared function here, tier 2 included, rather
            # than a bare sidecar_tag call, so this heading's own "old
            # app version" and lib.image_docs.add_missing_sidecar_rows'
            # own "Component versions" table row can never diverge on
            # the same path again.
            baseline_paths = dict(find_image_tag_paths(baseline_values)) if baseline_values else {}
            baseline_paths.update(global_image_paths(baseline_values) if baseline_values else [])
            baseline_repo_groups = (
                paths_by_repository(chart_dir, deps, baseline_values, baseline_paths.keys()) if baseline_values else {}
            )
            baseline_app = baseline_tag_for_sidecar_path(
                chart_dir, deps, values, baseline_values, baseline_paths, baseline_repo_groups, sidecar_path
            )
            if baseline_app is None and baseline_values:
                # Neither an exact match nor this same repository
                # elsewhere in baseline_values (real case: redis-
                # operator's own "k8s" sidecar, added in 4.9.0) —
                # before concluding "genuinely new", check whether this
                # repository already appears in any of this chart's own
                # PAST images-<version>.yaml manifests (real, already-
                # committed per-release documents, not the removed
                # images-baseline.yaml side-file).
                baseline_app = historical_app_version_for_path(
                    chart_dir, deps, values, sidecar_path, upgrade_docs_baseline
                )
            result["baseline_app"] = baseline_app
            result["baseline_resolved"] = result["target_app"] is not None and baseline_app is not None
        elif dep is not None:
            baseline_dep = match_dependency_excluding_sidecar_names(row_name, baseline_deps)
            if baseline_dep is None:
                result["baseline_resolved"] = False
            else:
                result["baseline_resolved"] = True
                result["baseline_chart"] = str(baseline_dep["version"])
                # The Chart.yaml dependency line itself already existed at
                # the baseline ref (baseline_dep found — that's what got
                # us into this branch), but its own values.yaml section
                # may not have (real case: brppersonenmock's Chart.yaml
                # entry predates 4.9.0, but its "image:" block was only
                # added to podiumd's own values.yaml this release) —
                # before concluding "genuinely new", check the same
                # historical images-<version>.yaml search the sidecar
                # branch above uses.
                baseline_app = actual_app_version(baseline_values, result["values_key"], dep["name"])
                if baseline_app is None and baseline_values:
                    for path in image_paths_for(dep["name"], chart_dir):
                        baseline_app = historical_app_version_for_path(
                            chart_dir,
                            deps,
                            values,
                            (result["values_key"],) + tuple(path.split(".")),
                            upgrade_docs_baseline,
                        )
                        if baseline_app is not None:
                            break
                result["baseline_app"] = baseline_app
        else:
            # Same "no existence check possible, just compare both app
            # versions" shape as the sidecar branch above — there's no
            # dep to ask "did this exist at the baseline ref", only
            # whether native_key's own image tag was resolvable there too.
            baseline_app = actual_app_version(baseline_values, native_key, native_key)
            if baseline_app is None and baseline_values:
                for path in image_paths_for(native_key, chart_dir):
                    baseline_app = historical_app_version_for_path(
                        chart_dir, deps, values, (native_key,) + tuple(path.split(".")), upgrade_docs_baseline
                    )
                    if baseline_app is not None:
                        break
            result["baseline_app"] = baseline_app
            result["baseline_resolved"] = result["target_app"] is not None and baseline_app is not None

    return result
