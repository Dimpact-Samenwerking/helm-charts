#!/usr/bin/env python3
"""
Query charts/podiumd/release-table.csv (see export-confluence-release-table.py)
for rows whose "section", "vendor", or "name" column contains a given piece
of text, and print each match's name plus its four version columns as an
aligned table.

Usage:
    query-release-table.py <column> <text>

    <column>  one of: section, vendor, name
    <text>    matched as a case-insensitive substring against that column
              (e.g. "zac" matches a component named "ZAC"; "open" matches
              both "Open Zaak" and "Open Formulieren")

A target version column that's empty (nothing changed for that app/helm
version on this release) prints as "UNCHANGED" rather than blank.

When <column> is "name", <text> is also resolved as a Chart.yaml alias —
e.g. "ita" is the alias for dependency "internetaakafhandeling", which
equals "Interne Taak Afhandeling" with spaces stripped — so querying the
short alias itself finds the actual product component, not just an
incidental substring match elsewhere (e.g. "ITA Poller"). A row whose own
"used_by" is non-empty (Technische-section tooling) is never treated as
this primary match by itself when a real owning component also matched —
e.g. querying "kiss" returns "Contact (KISS)" alone here, with the tooling
it uses (which also happens to have "kiss" literally in its own name)
appearing in the "used by" table below instead. If no owning component
matches at all, falls back to whatever raw matches exist, so a tooling row
can still be found directly by its own name.

Also prints a second table of every row whose "used_by" column relates to
one of the matched rows' own "name" value — either because the used_by
value is a plain substring of that name (e.g. "zac" is contained in "Zaak
- ZAC"), or because the used_by value is a Chart.yaml alias whose
dependency's full name equals that name with spaces stripped (e.g.
used_by "ita" is the alias for Chart.yaml dependency
"internetaakafhandeling", which is exactly "Interne Taak Afhandeling"
with spaces removed). Either way, this finds rows that aren't matched by
the main query itself.

Examples:
    query-release-table.py name zac
    query-release-table.py vendor maykin
    query-release-table.py section technische
"""
import csv
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.chart import load_yaml

CHART_DIR = SCRIPT_DIR.parents[0]
DEFAULT_INPUT = CHART_DIR / "release-table.csv"

COLUMNS = ("section", "vendor", "name")
VERSION_COLUMNS = ("source version app", "source version helm", "target version app", "target version helm")
TARGET_VERSION_COLUMNS = ("target version app", "target version helm")


def load_rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def matching_rows(rows, column, text):
    needle = text.lower()
    return [row for row in rows if needle in row[column].lower()]


def alias_dependency_names(chart_dir):
    """{alias: dependency_name} for every aliased dependency in
    chart_dir/Chart.yaml — e.g. {"ita": "internetaakafhandeling", "zac":
    "zaakafhandelcomponent", ...}. {} if chart_dir has no Chart.yaml
    (e.g. an isolated test fixture that doesn't care about alias
    resolution)."""
    chart_yaml_path = chart_dir / "Chart.yaml"
    if not chart_yaml_path.is_file():
        return {}
    chart_yaml = load_yaml(chart_yaml_path)
    return {dep["alias"]: dep["name"] for dep in chart_yaml.get("dependencies", []) if dep.get("alias")}


def alias_matched_rows(rows, text, chart_dir):
    """Rows whose "name" value equals the Chart.yaml dependency name that
    `text` resolves to as an alias, with spaces stripped — e.g. text
    "ita" resolves to dependency "internetaakafhandeling" (see
    alias_dependency_names), which equals "Interne Taak Afhandeling"
    with spaces removed. The other direction of the same relationship
    used_by_rows_for resolves — this is what lets querying the alias
    itself find the actual component, not just an incidental substring
    match on some unrelated row (e.g. "ITA Poller" also contains "ita")."""
    dependency_name = alias_dependency_names(chart_dir).get(text.lower())
    if not dependency_name:
        return []
    target = dependency_name.lower()
    return [row for row in rows if row["name"].lower().replace(" ", "") == target]


def name_matches(rows, text, chart_dir):
    """The row(s) a "name" query for `text` should treat as primary
    matches. A row whose own "used_by" is non-empty is tooling belonging
    to some other component (see used_by_rows_for, which is what surfaces
    it instead, tied to whichever owner row matched here) — so once at
    least one "owner" row (used_by empty) matches, by plain substring or
    by Chart.yaml alias (see alias_matched_rows), only owner rows are
    returned; a tooling row that happens to also contain `text` (e.g.
    "Kiss Elastic Sync" containing "kiss") is left for the used_by table
    instead of double-counted here. If no owner row matches at all — e.g.
    querying a Technische row directly by name, like "solr" — falls back
    to the raw substring matches, so it can still be found on its own."""
    raw = matching_rows(rows, "name", text)
    owners = [row for row in raw if not row["used_by"]]
    owner_ids = {id(row) for row in owners}
    owners += [row for row in alias_matched_rows(rows, text, chart_dir)
               if not row["used_by"] and id(row) not in owner_ids]
    return owners if owners else raw


def used_by_rows_for(rows, matches, chart_dir=None):
    """Every row in `rows` (excluding `matches` themselves) whose
    non-empty "used_by" value relates to one of `matches`' own "name"
    values, so that a Technische-section row comes back regardless of
    which column/text the original query actually matched on. Two ways
    a used_by value can relate to a name:
    - plain substring — e.g. "zac" is contained in "Zaak - ZAC"
    - Chart.yaml alias — e.g. used_by "ita" is the alias for dependency
      "internetaakafhandeling" (see alias_dependency_names), which is
      exactly "Interne Taak Afhandeling" with spaces stripped; "ita"
      itself is not a substring of that name at all."""
    chart_dir = chart_dir or CHART_DIR
    alias_names = alias_dependency_names(chart_dir)
    names = [m["name"].lower() for m in matches]
    compact_names = [name.replace(" ", "") for name in names]
    match_ids = {id(m) for m in matches}

    result = []
    for row in rows:
        used_by = row["used_by"]
        if not used_by or id(row) in match_ids:
            continue
        needle = used_by.lower()
        dependency_name = alias_names.get(used_by, "").lower()
        if any(needle in name for name in names) or dependency_name in compact_names:
            result.append(row)
    return result


def display_value(row, column):
    value = row[column]
    if not value and column in TARGET_VERSION_COLUMNS:
        return "UNCHANGED"
    return value


def print_table(rows):
    headers = ["name"] + list(VERSION_COLUMNS)
    table = [[row["name"]] + [display_value(row, col) for col in VERSION_COLUMNS] for row in rows]
    widths = [max(len(headers[i]), *(len(r[i]) for r in table)) for i in range(len(headers))]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    for r in table:
        print("  ".join(v.ljust(w) for v, w in zip(r, widths)))


def main():
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
    matches = name_matches(rows, text, CHART_DIR) if column == "name" else matching_rows(rows, column, text)
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
