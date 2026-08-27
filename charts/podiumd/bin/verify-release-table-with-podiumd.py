#!/usr/bin/env python3
"""
Compare charts/podiumd/release-table.csv (see
export-confluence-release-table.py) against the CURRENT
charts/podiumd/Chart.yaml + values.yaml, and report:

  - version mismatches: a row's target_version_helm/target_version_app
    disagrees with what's actually pinned right now
  - missing from release-table.csv: a real Chart.yaml dependency with no
    row at all, or an image pinned in values.yaml under a tracked
    component's own scope that no row's image_basename mentions
  - missing from Chart.yaml/values.yaml: a row whose resolved "component"
    isn't a Chart.yaml dependency (or values.yaml top-level key, for a
    component with no separate Helm chart, e.g. frankgateway) anymore, or
    whose image_basename names an image no longer pinned there

A row's "component"/"alias"/"image_basename" columns are already resolved
by export-confluence-release-table.py — this reads them directly rather
than re-deriving anything from free-form text (component is always a
literal Chart.yaml dependency name, or a values.yaml top-level key for a
no-separate-chart component). The image lookup is the exact same two lib.
image_version calls update-image-version.py's own <target> resolution
(lib.image_version.resolve_basename) is built on, tried in the same
order: first basenames_under_scope, scoped to the component's own
values.yaml subtree (fast, and the common case); if that misses, a plain
find_matches search across the WHOLE file, since a basename is a real
repository identity, not a values.yaml path, and can legitimately be
pinned under a sibling scope instead (e.g. keycloak-config-cli lives
under top-level "keycloak", not its own component's "keycloak-operator").
The chart-version lookup is a plain Chart.yaml dependency read, the same
one update-component-version.py's own pre-write gate uses.

A row whose component is "MULTIPLE" is a shared base image hoisted into
values.yaml's top-level global.images map (see export-confluence-release-
table.py's own global_image_keys/component_and_alias — e.g. nginx, curl,
busybox, pinned once and reused via YAML anchor across several unrelated
components) rather than owned by any single component — its image_basename
is still resolved by export time, though, so it's checked here the exact
same way as any other component's images, just scoped to "global" instead
of a Chart.yaml dependency's own values.yaml block (and with no chart-
version check, since it isn't backed by a separate Helm chart at all). A
"MULTIPLE" row export couldn't even resolve an image_basename for (an
ambiguous plain dependency-name collision, not a global image) has nothing
to check either way and is silently skipped, same as blank.

A row whose component is "UNKNOWN" (export-confluence-release-table.py
couldn't resolve it to anything at export time) is listed separately as
unresolved — that's a pre-existing export-time gap, not something this
script can verify either way, so it isn't scored as a failure here.

Purely local and network-free (no `helm pull`, no registry calls): a
"fallback path" component's app image basename can only be discovered by
pulling that specific chart version (see verify-image-version.py) — this
compares release-table.csv's OWN image_basename column against whatever
is ALREADY pinned in values.yaml right now, so nothing needs pulling.

Two images can't be found via the normal digest-pinned "tag:" scan
(lib.image_version.basenames_under_scope, via lib.image_digests.
scan_digest_pins) at all — the exact same two exceptions lib.
digest_pinning_check.EXEMPT_PATHS documents for its own, different check
(whether a tag IS digest-pinned, not what its version is):
  - keycloak-operator's own actual Keycloak SERVER image lives at
    operator.config.keycloakImage as a split "tag:"/"sha:" field pair —
    not a plain "image: {repository, tag}" block, so scan_digest_pins
    can't see it structurally at all, regardless of scope. Its plain
    "tag:" value (already just the version, no digest suffix) is read
    directly instead — see SPECIAL_CASE_BASENAME_TAG_PATHS.
  - omc's own image tag intentionally carries no digest at all (its
    subchart can't handle one), so export-confluence-release-table.py
    itself never resolves an image_basename for its row — checked here
    independently of that blank column, keyed by component instead — see
    SPECIAL_CASE_COMPONENT_TAG_PATHS.

Also compares version text literally, not semantically: a "v" prefix
difference between the two sides (e.g. release-table "1.89.0" vs
values.yaml "v1.89.0") is reported as a mismatch even though the actual
version is the same — the release-table column and the values.yaml pin
are supposed to record the identical string, so a drift there is itself
worth surfacing rather than silently normalized away.

Usage:
    verify-release-table-with-podiumd.py

Exit code is non-zero if any version mismatch, missing-from-release-table,
or missing-from-chart-or-values item was found.
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.chart import get_path, load_yaml
from lib.image_version import basenames_under_scope, find_matches

CHART_DIR = SCRIPT_DIR.parents[0]
CHART_YAML = CHART_DIR / "Chart.yaml"
VALUES_YAML = CHART_DIR / "values.yaml"
RELEASE_TABLE_CSV = CHART_DIR / "release-table.csv"

UNRESOLVED_COMPONENTS = ("", "UNKNOWN")
GLOBAL_IMAGES_SCOPE = "global"

# image_basename -> dotted values.yaml path to its own plain "tag:" value,
# for an image basenames_under_scope can never find via the normal
# digest-pinned tag scan — see module docstring and
# lib.digest_pinning_check.EXEMPT_PATHS (the same underlying exception,
# documented there for a different check).
SPECIAL_CASE_BASENAME_TAG_PATHS = {
    "keycloak": "keycloak-operator.operator.config.keycloakImage.tag",
}

# component (Chart.yaml dependency name) -> dotted values.yaml path to its
# own plain "tag:" value, for a component export-confluence-release-
# table.py could never resolve an image_basename for at all (its row's
# image_basename column is blank) — see module docstring.
SPECIAL_CASE_COMPONENT_TAG_PATHS = {
    "notifynl-omc-nodep": "omc.image.tag",
}


def load_release_table(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def split_basenames(value):
    return [b.strip() for b in value.split(",") if b.strip()]


def is_verifiable_target(target):
    """False for a blank or "UNKNOWN" target column value — nothing to
    compare against (blank means "no planned change", see query-release-
    table.py's own UNCHANGED display logic; "UNKNOWN" means export-
    confluence-release-table.py's own normalize_version couldn't parse
    the source cell as a version at all). True otherwise."""
    return bool(target) and target != "UNKNOWN"


def report_mismatch(findings, tag, row, label, target, actual, actual_source):
    findings["mismatches"].append(
        f"[{tag}] {row['name']} ({label}): release-table target {target} != {actual_source} {actual}"
    )


def check_chart_version(dep, rows, findings):
    actual = str(dep["version"])
    for row in rows:
        target = row["target_version_helm"]
        if is_verifiable_target(target) and target != actual:
            report_mismatch(findings, "CHART", row, dep["name"], target, actual, "Chart.yaml")


def check_special_case_version(row, findings, actual, label):
    """Compares row["target_version_app"] against `actual` (the plain
    "tag:" value already read from a SPECIAL_CASE_BASENAME_TAG_PATHS/
    SPECIAL_CASE_COMPONENT_TAG_PATHS path), for an image
    basenames_under_scope structurally can't see at all. `label` is what
    a mismatch message calls the image (e.g. "keycloak-operator.keycloak"
    or "notifynl-omc-nodep"). No-op if `actual` couldn't be resolved
    (get_path found nothing at that path) or target is blank/UNKNOWN."""
    target = row["target_version_app"]
    if actual is not None and is_verifiable_target(target) and actual != target:
        report_mismatch(findings, "IMAGE", row, label, target, actual, "values.yaml")


def check_images(scope_key, component, rows, lines, findings, values):
    actual_basenames = basenames_under_scope(lines, scope_key)
    csv_basenames = set()
    component_special_path = SPECIAL_CASE_COMPONENT_TAG_PATHS.get(component)

    for row in rows:
        target = row["target_version_app"]
        basenames = split_basenames(row["image_basename"])
        if not basenames:
            if component_special_path:
                check_special_case_version(row, findings, get_path(values, component_special_path), component)
            continue

        for basename in basenames:
            csv_basenames.add(basename)
            pins = actual_basenames.get(basename)
            if pins is None:
                # Not under this component's own scope — same fallback
                # update-image-version.py's own <target> resolution uses
                # (lib.image_version.resolve_basename's first, unscoped
                # find_matches try): a basename is a real repository
                # identity, not a values.yaml path, so it can legitimately
                # be pinned under a sibling scope instead (e.g. keycloak-
                # config-cli lives under top-level "keycloak", not
                # "keycloak-operator").
                pins = find_matches(lines, basename) or None
            if pins is not None:
                if is_verifiable_target(target):
                    versions = {p["version"] for p in pins}
                    if len(versions) > 1:
                        findings["ambiguous"].append(
                            f"[IMAGE] '{basename}' under '{scope_key}' is pinned at {len(versions)} different "
                            f"versions ({', '.join(sorted(versions))}) -- can't compare to release-table "
                            f"target {target}"
                        )
                    else:
                        actual = next(iter(versions))
                        if actual != target:
                            report_mismatch(findings, "IMAGE", row, f"{component}.{basename}", target,
                                             actual, "values.yaml")
                continue

            basename_special_path = SPECIAL_CASE_BASENAME_TAG_PATHS.get(basename)
            if basename_special_path:
                check_special_case_version(row, findings, get_path(values, basename_special_path),
                                            f"{component}.{basename}")
                continue

            findings["missing_from_chart"].append(
                f"[IMAGE] release-table image '{basename}' for component '{component}' "
                f"(row '{row['name']}') is not pinned anywhere under '{scope_key}' in values.yaml"
            )

    for basename in actual_basenames:
        if basename not in csv_basenames:
            findings["missing_from_release_table"].append(
                f"[IMAGE] '{scope_key}' image '{basename}' is pinned in values.yaml but not tracked "
                f"in release-table.csv"
            )


def compare(rows, deps, values, lines):
    """{"mismatches", "ambiguous", "missing_from_release_table",
    "missing_from_chart"}: str -> [str, ...], plus the separate list of
    rows whose component export-confluence-release-table.py never
    resolved at all (see UNRESOLVED_COMPONENTS) — see module docstring."""
    findings = defaultdict(list)
    unresolved = []
    values = values if isinstance(values, dict) else {}

    rows_by_component = defaultdict(list)
    multiple_rows = []
    for row in rows:
        component = row["component"]
        if component == "MULTIPLE":
            multiple_rows.append(row)
        elif component in UNRESOLVED_COMPONENTS:
            unresolved.append(row)
        else:
            rows_by_component[component].append(row)

    # Called unconditionally (even with zero multiple_rows) so a global
    # image nobody's row ever resolved to at all still surfaces as
    # missing-from-release-table, not just silently unchecked.
    check_images(GLOBAL_IMAGES_SCOPE, "MULTIPLE", multiple_rows, lines, findings, values)

    checked_components = set()
    for dep in deps:
        component = dep["name"]
        checked_components.add(component)
        rows_for_component = rows_by_component.get(component, [])
        if not rows_for_component:
            alias_suffix = f" (alias '{dep['alias']}')" if dep.get("alias") else ""
            findings["missing_from_release_table"].append(
                f"[CHART] Chart.yaml dependency '{component}'{alias_suffix} has no release-table.csv row"
            )
            continue
        check_chart_version(dep, rows_for_component, findings)
        check_images(dep.get("alias") or component, component, rows_for_component, lines, findings, values)

    for component, rows_for_component in rows_by_component.items():
        if component in checked_components:
            continue
        if component in values:
            check_images(component, component, rows_for_component, lines, findings, values)
        else:
            for row in rows_for_component:
                findings["missing_from_chart"].append(
                    f"[CHART] release-table row '{row['name']}' resolves to component '{component}', "
                    f"which is not a Chart.yaml dependency or a top-level values.yaml key"
                )

    return dict(findings), unresolved


SECTIONS = [
    ("mismatches", "Version mismatches"),
    ("ambiguous", "Ambiguous pins (can't verify)"),
    ("missing_from_release_table", "Missing from release-table.csv"),
    ("missing_from_chart", "Missing from Chart.yaml / values.yaml"),
]


def print_report(findings, unresolved):
    any_findings = False
    for key, title in SECTIONS:
        items = findings.get(key)
        if not items:
            continue
        any_findings = True
        print(f"\n{title}:")
        for item in sorted(items):
            print(f"  {item}")

    if unresolved:
        print(f"\nSkipped ({len(unresolved)} row(s) with an unresolved component in release-table.csv):")
        for row in unresolved:
            print(f"  - '{row['name']}' (component={row['component'] or '(blank)'})")

    if not any_findings:
        print("OK: release-table.csv matches Chart.yaml / values.yaml")
    return any_findings


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) != 1:
        print(__doc__)
        sys.exit(1)

    if not RELEASE_TABLE_CSV.is_file():
        print(f"error: {RELEASE_TABLE_CSV} not found")
        print("Create it first with export-confluence-release-table.py.")
        sys.exit(1)
    rows = load_release_table(RELEASE_TABLE_CSV)

    chart_yaml = load_yaml(CHART_YAML) if CHART_YAML.is_file() else {}
    deps = (chart_yaml or {}).get("dependencies", [])
    values = load_yaml(VALUES_YAML) if VALUES_YAML.is_file() else {}
    lines = VALUES_YAML.read_text(encoding="utf-8").splitlines() if VALUES_YAML.is_file() else []

    findings, unresolved = compare(rows, deps, values, lines)
    any_findings = print_report(findings, unresolved)
    sys.exit(1 if any_findings else 0)


if __name__ == "__main__":
    main()
