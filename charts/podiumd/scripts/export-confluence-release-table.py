#!/usr/bin/env python3
"""
Exports the podiumd release-changes table(s) from a Confluence page into
charts/podiumd/release-changes.csv.

Scans every <table> on the page (a page can have more than one — e.g. one
per section) and, from each table that has all of the expected columns,
extracts: the table's own first column (whatever it's labeled — usually
the component name), "Ontwikkelpartij", and "App"/"Helm" under each of
"Versie 4.8" and "Versie 4.9" (matched by case-insensitive substring, so
"versie 4.8"/"Versie 4.8"/"V4.8" etc. all work — see
lib.confluence_tables.RELEASE_COLUMN_SPECS). A table missing any of those
columns is skipped and reported, not treated as an error — a page
typically has other, unrelated tables too. Rows from every matching table
are concatenated into one CSV, in page order.

Column/row spans in the header (e.g. "Versie 4.8" spanning two sub-columns
via colspan, or "Ontwikkelpartij" spanning both header rows via rowspan)
are expanded automatically — see lib.confluence_tables.expand_grid.

Auth: HTTP Basic with your Atlassian account email + an API token
(https://id.atlassian.com/manage-profile/security/api-tokens). Prefer
--token-file or the CONFLUENCE_API_TOKEN env var over --token — a token
passed as a bare CLI argument shows up in shell history and `ps` output.
Omitting all three prompts for it (hidden input, not echoed).

Usage:
    export-confluence-release-table.py --url <page-url> --user <email> --token-file <path>
    export-confluence-release-table.py --url <page-url> --user <email>
        # prompts for the token, or reads CONFLUENCE_API_TOKEN if set
    export-confluence-release-table.py --url <page-url> --user <email> --token-file <path> --output /tmp/out.csv
        # write elsewhere instead of the default charts/podiumd/release-changes.csv
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
    expand_grid, extract_tables, fetch_page_html, header_paths,
    leading_header_row_count, select_release_columns,
)

CHART_DIR = SCRIPT_DIR.parents[0]
DEFAULT_OUTPUT = CHART_DIR / "release-changes.csv"

CSV_HEADER_SUFFIX = ["ontwikkelpartij", "versie 4.8 app", "versie 4.8 helm", "versie 4.9 app", "versie 4.9 helm"]


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", required=True, help="Confluence page URL")
    parser.add_argument("--user", required=True, help="Atlassian account email")
    parser.add_argument("--token", help="API token (prefer --token-file or CONFLUENCE_API_TOKEN instead)")
    parser.add_argument("--token-file", help="path to a file containing just the API token")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help=f"CSV output path (default: {DEFAULT_OUTPUT})")
    return parser.parse_args()


def resolve_token(args):
    if args.token_file:
        return Path(args.token_file).read_text(encoding="utf-8").strip()
    if args.token:
        return args.token
    env_token = os.environ.get("CONFLUENCE_API_TOKEN")
    if env_token:
        return env_token
    return getpass.getpass("Confluence API token: ")


def extract_release_rows(html):
    """Return (header_label_for_first_column, rows) across every table on
    the page that has all the expected release-changes columns. Prints a
    one-line report per table (matched row count, or why it was skipped)."""
    tables = extract_tables(html)
    if not tables:
        raise SystemExit("error: no <table> found on that page")

    first_label = None
    rows_out = []
    for i, rows in enumerate(tables, start=1):
        if not rows:
            continue
        grid = expand_grid(rows)
        header_row_count = leading_header_row_count(rows) or 1
        paths = header_paths(grid, header_row_count)
        columns = select_release_columns(paths)
        missing = [key for key, idx in columns.items() if idx is None]
        if missing:
            print(f"Table {i}/{len(tables)}: skipped (missing column(s): {', '.join(missing)})")
            continue

        if first_label is None:
            first_path = paths[columns["first"]]
            first_label = first_path[-1] if first_path else "component"

        matched = 0
        for data_row in grid[header_row_count:]:
            if not any(cell.strip() for cell in data_row):
                continue
            rows_out.append([data_row[columns[key]] for key in
                              ("first", "ontwikkelpartij", "v48_app", "v48_helm", "v49_app", "v49_helm")])
            matched += 1
        print(f"Table {i}/{len(tables)}: {matched} row(s) matched")

    if first_label is None:
        raise SystemExit("error: no table on that page had all the expected columns "
                          "(first column, Ontwikkelpartij, Versie 4.8/4.9 App+Helm)")
    return first_label, rows_out


def main():
    args = parse_args()
    token = resolve_token(args)

    html = fetch_page_html(args.url, args.user, token)
    first_label, rows = extract_release_rows(html)

    output_path = Path(args.output)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([first_label] + CSV_HEADER_SUFFIX)
        writer.writerows(rows)

    print(f"Wrote {len(rows)} row(s) to {output_path}")


if __name__ == "__main__":
    main()
