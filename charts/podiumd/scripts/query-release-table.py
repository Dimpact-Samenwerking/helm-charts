#!/usr/bin/env python3
"""
Query charts/podiumd/release-table.csv (see export-confluence-release-table.py)
for rows whose "section", "vendor", or "component" column contains a given
piece of text, and print each match's component plus its four version columns
as an aligned table.

Usage:
    query-release-table.py <column> <text>

    <column>  one of: section, vendor, component
    <text>    matched as a case-insensitive substring against that column
              (e.g. "zac" matches a component named "ZAC"; "open" matches
              both "Open Zaak" and "Open Formulieren")

A target version column that's empty (nothing changed for that app/helm
version on this release) prints as "UNCHANGED" rather than blank.

When <column> is "component", also prints a second table of every row
whose "used_by" column contains <text> — e.g. querying "zac" additionally
lists the Technische-section tooling (Solr, Zookeeper, ...) that row says
ZAC pulls in, since those rows aren't found by the main component match.

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
VERSION_COLUMNS = ("source version app", "source version helm", "target version app", "target version helm")
TARGET_VERSION_COLUMNS = ("target version app", "target version helm")


def load_rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def matching_rows(rows, column, text):
    needle = text.lower()
    return [row for row in rows if needle in row[column].lower()]


def display_value(row, column):
    value = row[column]
    if not value and column in TARGET_VERSION_COLUMNS:
        return "UNCHANGED"
    return value


def print_table(rows):
    headers = ["component"] + list(VERSION_COLUMNS)
    table = [[row["component"]] + [display_value(row, col) for col in VERSION_COLUMNS] for row in rows]
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
    matches = matching_rows(rows, column, text)
    if not matches:
        print(f"no rows found where {column} contains {text!r}")
        sys.exit(1)

    print(f"Matches for {column} {text!r}:")
    print_table(matches)

    if column == "component":
        used_by_matches = matching_rows(rows, "used_by", text)
        if used_by_matches:
            print()
            print(f"Used by {text!r}:")
            print_table(used_by_matches)


if __name__ == "__main__":
    main()
