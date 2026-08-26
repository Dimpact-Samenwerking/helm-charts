#!/usr/bin/env python3
"""
Query charts/podiumd/release-table.csv (see export-confluence-release-table.py)
for rows whose "section", "vendor", or "component" column contains a given
piece of text, and print each match's name, component, alias,
image_basename, and four version columns as an aligned table — plus a
second table of tooling rows
whose "used_by" relates back to a match (see component_matches and
used_by_rows_for for exactly how "component" and "used by" are resolved).

Usage:
    query-release-table.py <column> <text>

    <column>  one of: section, vendor, component
    <text>    matched as a case-insensitive substring against that column
              (e.g. "zac" matches component "zaakafhandelcomponent"; "open"
              matches both "Open Zaak" and "Open Formulieren")

Examples:
    query-release-table.py component zac
    query-release-table.py vendor maykin
    query-release-table.py section technische
"""
import csv
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CHART_DIR = SCRIPT_DIR.parents[0]
DEFAULT_INPUT = CHART_DIR / "release-table.csv"

COLUMNS = ("section", "vendor", "component")
VERSION_COLUMNS = ("source_version_app", "source_version_helm", "target_version_app", "target_version_helm")
TARGET_VERSION_COLUMNS = ("target_version_app", "target_version_helm")
TARGET_TO_SOURCE_COLUMN = {"target_version_app": "source_version_app", "target_version_helm": "source_version_helm"}


def load_rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def matching_rows(rows, column, text):
    needle = text.lower()
    return [row for row in rows if needle in row[column].lower()]


def component_matches(rows, text):
    """The row(s) a "component" query for `text` should treat as
    matches: rows whose own "component" or "alias" column (both set by
    export-confluence-release-table.py — see its component_and_alias)
    contains `text` as a substring — e.g. "keycloak-operator" or its
    alias find the same row either way. These are the resolved
    Chart.yaml identifiers themselves, so they're tried first, ahead of
    the row's own "name" — e.g. querying component "zac" should find the
    row resolved to component "zaakafhandelcomponent" (alias "zac"), not
    incidentally match some unrelated row whose own display name happens
    to contain "zac". Only falls back to matching_rows(rows, "name",
    text) if NEITHER "component" nor "alias" matches anything at all, so
    a row that never got resolved to a real component (component is
    "UNKNOWN" or "MULTIPLE") can still be found by its own name as a
    last resort."""
    from_component = matching_rows(rows, "component", text)
    from_alias = matching_rows(rows, "alias", text)
    seen = {id(row) for row in from_component}
    combined = from_component + [row for row in from_alias if id(row) not in seen]
    return combined if combined else matching_rows(rows, "name", text)


def used_by_rows_for(rows, matches):
    """Every row in `rows` (excluding `matches` themselves) whose
    non-empty "used_by" value relates to one of `matches`' own "name" or
    "alias" values, so that a Technische-section row comes back
    regardless of which column/text the original query actually matched
    on. Two ways a used_by value can relate to a match:
    - plain substring of its "name" — e.g. "zac" is contained in "Zaak -
      ZAC"
    - exact match of its "alias" column (set by
      export-confluence-release-table.py) — e.g. used_by "ita" equals
      "Interne Taak Afhandeling"'s own alias; "ita" itself is not a
      substring of that name at all."""
    names = [m["name"].lower() for m in matches]
    aliases = {m["alias"].lower() for m in matches if m["alias"]}
    match_ids = {id(m) for m in matches}

    result = []
    for row in rows:
        used_by = row["used_by"]
        if not used_by or id(row) in match_ids:
            continue
        needle = used_by.lower()
        if any(needle in name for name in names) or needle in aliases:
            result.append(row)
    return result


def display_value(row, column):
    """`row[column]` unchanged, except a target version column shows
    "UNCHANGED" instead of the raw value when either there's no target
    value at all (empty cell), or the target equals its own source
    column's value (e.g. target_version_app == source_version_app) —
    both mean nothing actually changed for that app/helm version on this
    release."""
    value = row[column]
    if column in TARGET_VERSION_COLUMNS and (not value or value == row[TARGET_TO_SOURCE_COLUMN[column]]):
        return "UNCHANGED"
    return value


def print_table(rows):
    headers = ["name", "component", "alias", "image_basename"] + list(VERSION_COLUMNS)
    table = [[row["name"], row["component"], row["alias"], row["image_basename"]] +
             [display_value(row, col) for col in VERSION_COLUMNS] for row in rows]
    widths = [max(len(headers[i]), *(len(r[i]) for r in table)) for i in range(len(headers))]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    for r in table:
        print("  ".join(v.ljust(w) for v, w in zip(r, widths)))


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) != 3 or sys.argv[1] not in COLUMNS:
        print(__doc__)
        sys.exit(1)
    column, text = sys.argv[1], sys.argv[2]

    if not DEFAULT_INPUT.is_file():
        print(f"error: {DEFAULT_INPUT} not found")
        print("Create it first with export-confluence-release-table.py, e.g.:")
        print("    export-confluence-release-table.py --url <page-url> --user <email> --token-file <path>")
        sys.exit(1)

    rows = load_rows(DEFAULT_INPUT)
    matches = component_matches(rows, text) if column == "component" else matching_rows(rows, column, text)
    if not matches:
        print(f"no rows found where {column} contains {text!r}")
        sys.exit(1)

    print(f"Matches for {column} {text!r}:")
    print_table(matches)

    used_by_matches = used_by_rows_for(rows, matches)
    if used_by_matches:
        print()
        print("Used by matched component(s):")
        print_table(used_by_matches)


if __name__ == "__main__":
    main()
