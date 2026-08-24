#!/usr/bin/env python3
"""
Exports the podiumd release-changes table(s) from a Confluence page into
charts/podiumd/release-changes.csv.

Only looks at tables sitting directly under one of --heading (repeatable;
defaults to the four standard podiumd sections — see DEFAULT_HEADINGS)
— a page typically has other tables too (release scope/timeline, ...)
that aren't relevant here and are ignored entirely, not just skipped for
missing columns.

From each matching table, extracts: which section it came from, the
table's own first column (whatever it's labeled — usually the component
name), "Ontwikkelpartij" (optional — some sections, e.g. shared/technical
tooling, legitimately have no development-partner column at all), and
"App"/"Helm" under each of the table's two "Versie ..." column groups
(required) — written to the CSV as "source version"/"target version"
(first group = source, second = target; see
lib.confluence_tables.find_versie_groups). The version numbers
themselves are never hardcoded, since the page renames these two
headers every release (e.g. "Versie 4.8"/"Versie 4.9" today) — only that
each one's label starts with "Versie" (case-insensitive) matters. A
matching-heading table still missing a required column, or that doesn't
have exactly two such groups, is skipped and reported, not treated as an
error. Rows from every table that has them are concatenated into one
CSV, in page order.

Each of the four version values is replaced with "UNKNOWN" if it isn't
semver-compatible (see lib.confluence_tables.is_semver_compatible — a
deliberately looser check than strict semver.org, allowing an omitted
patch component and a stray "." after a leading "v") — catches two
values run together with no separator ("5.4.3 5.4.4", from adjacent
Confluence content blocks the page itself never actually joined), or a
placeholder like "?". An empty cell (no version at all for that component/version
combination) is left empty, not replaced — it isn't a malformed value,
there's just nothing there.

Column/row spans in the header (e.g. "Versie 4.8" spanning two sub-columns
via colspan, or "Ontwikkelpartij" spanning both header rows via rowspan)
are expanded automatically — see lib.confluence_tables.expand_grid.

Auth: HTTP Basic with your Atlassian account email + an API token
(https://id.atlassian.com/manage-profile/security/api-tokens — must be a
*classic* token; the newer "API token with scopes" kind doesn't work with
Basic auth against the site directly, and Confluence rejects it with a
plain 403). Prefer --token-file or the CONFLUENCE_API_TOKEN env var over
--token — a token passed as a bare CLI argument shows up in shell history
and `ps` output. Omitting all three prompts for it (hidden input, not
echoed).

Usage:
    export-confluence-release-table.py --url <page-url> --user <email> --token-file <path>
    export-confluence-release-table.py --url <page-url> --user <email>
        # prompts for the token, or reads CONFLUENCE_API_TOKEN if set
    export-confluence-release-table.py --url <page-url> --user <email> --token-file <path> --output /tmp/out.csv
        # write elsewhere instead of the default charts/podiumd/release-changes.csv
    export-confluence-release-table.py --url <page-url> --user <email> --token-file <path> \\
        --heading "Product component versies" --heading "Technische component versies"
        # only these sections, instead of all four defaults
"""
import argparse
import csv
import getpass
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.confluence_tables import (
    effective_header_row_count, expand_grid, extract_tables, fetch_page_html,
    header_paths, is_semver_compatible, missing_required_release_columns,
    select_release_columns, tables_under_headings,
)

CHART_DIR = SCRIPT_DIR.parents[0]
DEFAULT_OUTPUT = CHART_DIR / "release-changes.csv"

# The four sections this export exists for, on the podiumd release-notes
# Confluence page — pass --heading (repeatable) to override.
DEFAULT_HEADINGS = [
    "Product component versies",
    "Common Ground component versies",
    "Overige component versies",
    "Technische component versies",
]

CSV_HEADER = ["sectie", "component", "ontwikkelpartij",
              "source version app", "source version helm", "target version app", "target version helm"]

# How many extra rows beyond effective_header_row_count()'s own guess to
# try as the header block — see resolve_header_row_count. Confluence
# doesn't always tag a sub-header row (e.g. "App"/"Helm" under a <th>
# "Versie 4.8") as <th> itself; seen in practice on the real podiumd page,
# where the top header row uses <th> but its own sub-header row uses
# plain <td>, undercounting the header block by exactly one row.
MAX_HEADER_ROW_PROBE = 2


def resolve_header_row_count(rows, grid):
    """effective_header_row_count(rows, grid), extended by up to
    MAX_HEADER_ROW_PROBE extra rows if that's what it takes for
    select_release_columns to find every required column — see
    MAX_HEADER_ROW_PROBE for why a table's own <th> tagging can't always
    be trusted to mark the full header block. Falls back to the
    untouched base count if no depth in that range resolves everything
    (extract_release_rows will then report it as missing the usual way)."""
    base = effective_header_row_count(rows, grid)
    for extra in range(MAX_HEADER_ROW_PROBE + 1):
        count = base + extra
        if count > len(grid):
            break
        columns = select_release_columns(header_paths(grid, count))
        if not missing_required_release_columns(columns):
            return count
    return base


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", required=True, help="Confluence page URL")
    parser.add_argument("--user", required=True, help="Atlassian account email")
    parser.add_argument("--token", help="API token (prefer --token-file or CONFLUENCE_API_TOKEN instead)")
    parser.add_argument("--token-file", help="path to a file containing just the API token")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help=f"CSV output path (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--heading", action="append",
                         help="only use table(s) directly under this heading (repeatable; "
                              f"default: {', '.join(DEFAULT_HEADINGS)})")
    return parser.parse_args()


def normalize_version(value):
    """`value` unchanged if it's empty (no version at all for that cell —
    not a malformed one) or already semver-compatible; otherwise
    "UNKNOWN", flagging a value this export can't treat as a real version
    (see is_semver_compatible for what that covers)."""
    if not value or is_semver_compatible(value):
        return value
    return "UNKNOWN"


def resolve_token(args):
    if args.token_file:
        return Path(args.token_file).read_text(encoding="utf-8").strip()
    if args.token:
        return args.token
    env_token = os.environ.get("CONFLUENCE_API_TOKEN")
    if env_token:
        return env_token
    return getpass.getpass("Confluence API token: ")


def extract_release_rows(html, headings=None):
    """Return the CSV data rows (sectie, component, ontwikkelpartij,
    source version app/helm, target version app/helm) across every table
    directly under one of `headings` (default DEFAULT_HEADINGS) that has
    the required App/Helm columns. Prints a one-line report per matching-
    heading table (rows matched, or which required column it's missing)."""
    headings = headings or DEFAULT_HEADINGS
    all_tables = extract_tables(html)
    if not all_tables:
        raise SystemExit("error: no <table> found on that page")

    matching = tables_under_headings(all_tables, headings)
    print(f"Found {len(all_tables)} table(s) on the page, {len(matching)} under a matching heading")
    if not matching:
        raise SystemExit(f"error: no table found directly under any of: {', '.join(headings)}")

    rows_out = []
    unknown_count = 0
    for heading, rows in matching:
        grid = expand_grid(rows)
        header_row_count = resolve_header_row_count(rows, grid)
        paths = header_paths(grid, header_row_count)
        columns = select_release_columns(paths)
        missing = missing_required_release_columns(columns)
        if missing:
            print(f'"{heading}": skipped (missing required column(s): {", ".join(missing)})')
            continue

        matched = 0
        for data_row in grid[header_row_count:]:
            if not any(cell.strip() for cell in data_row):
                continue
            ontwikkelpartij = data_row[columns["ontwikkelpartij"]] if columns["ontwikkelpartij"] is not None else ""
            versions = [normalize_version(data_row[columns[key]]) for key in
                        ("source_app", "source_helm", "target_app", "target_helm")]
            unknown_count += sum(1 for v in versions if v == "UNKNOWN")
            rows_out.append([heading, data_row[columns["first"]], ontwikkelpartij] + versions)
            matched += 1
        print(f'"{heading}": {matched} row(s) matched')

    if not rows_out:
        raise SystemExit("error: every matching-heading table was missing a required column "
                          "(source/target Versie ... App+Helm) — see the skip reason(s) above")
    if unknown_count:
        print(f"{unknown_count} version value(s) were not semver-compatible — replaced with UNKNOWN")
    return rows_out


def main():
    args = parse_args()
    token = resolve_token(args)

    html = fetch_page_html(args.url, args.user, token)
    rows = extract_release_rows(html, args.heading)

    output_path = Path(args.output)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        writer.writerows(rows)

    print(f"Wrote {len(rows)} row(s) to {output_path}")


if __name__ == "__main__":
    main()
