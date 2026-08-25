#!/usr/bin/env python3
"""
Exports the podiumd release-changes table(s) from a Confluence page into
charts/podiumd/release-table.csv.

Only looks at tables sitting directly under one of --heading (repeatable;
defaults to the four standard podiumd sections — see DEFAULT_HEADINGS)
— a page typically has other tables too (release scope/timeline, ...)
that aren't relevant here and are ignored entirely, not just skipped for
missing columns.

From each matching table, extracts: which section it came from (written
to the CSV as "section" — the matched heading with its trailing
SECTION_SUFFIX, " component versies", stripped off — see section_name),
the page's own "Ontwikkelpartij" column (optional — some sections, e.g.
shared/technical tooling, legitimately have no development-partner
column at all — written to the CSV as "vendor"), the page's own "Used
by" column (optional the other way around — only the shared/technical
tooling tables have it, naming which product/Common Ground component
pulls that piece of tooling in — written to the CSV as "used_by"), the
table's own first column (whatever it's labeled — usually the component
name, written to the CSV as "name"), and "App"/"Helm" under each of the table's two
"Versie ..." column groups (required) — written to the CSV as "source
version"/"target version" (first group = source, second = target; see
lib.confluence_tables.find_versie_groups). The version numbers
themselves are never hardcoded, since the page renames these two
headers every release (e.g. "Versie 4.8"/"Versie 4.9" today) — only that
each one's label starts with "Versie" (case-insensitive) matters. A
matching-heading table still missing a required column, or that doesn't
have exactly two such groups, is skipped and reported, not treated as an
error. Rows from every table that has them are concatenated into one
CSV, in page order.

Also writes "component" and "alias", resolved against every
`chart_dir`/Chart.yaml dependency (see chart_dependencies). The text
resolved is "used_by" when the row has one (e.g. "zac" for a Technische
row — that's a much more direct signal than the row's own name, since
"used_by" is often already a literal Chart.yaml alias), otherwise
"name". Resolution compares each of that text's normalized forms — the
whole thing, and, if it has a "... (bracketed part)" shape, the
bracketed part and the rest tried separately (e.g. "Platform
Autorisatie Beheer Component (PABC)" tries
"platformautorisatiebeheercomponent" AND "pabc" on their own) — against
each dependency's own normalized name and alias (see component_and_alias
for the exact match/substring rules and their priority). "component" is
"UNKNOWN" (and "alias" left empty) if nothing matches any dependency at
all — e.g. "Elastic operator", whose dependency "eck-operator" shares no
text with it either way.

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

Prints a large, hard-to-miss warning (not a failure — the CSV is still
written) if the "target" heading's MAJOR.MINOR (patch ignored) doesn't
match charts/podiumd/Chart.yaml's own "version:" — this export is for
whatever release Chart.yaml is currently set to, so a mismatch usually
means either the wrong Confluence page, or Chart.yaml hasn't been bumped
to match the page yet. See check_target_matches_chart_version.

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
        # write elsewhere instead of the default charts/podiumd/release-table.csv
    export-confluence-release-table.py --url <page-url> --user <email> --token-file <path> \\
        --heading "Product component versies" --heading "Technische component versies"
        # only these sections, instead of all four defaults
"""
import argparse
import csv
import getpass
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.chart import load_yaml
from lib.confluence_tables import (
    effective_header_row_count, expand_grid, extract_tables, fetch_page_html,
    find_versie_groups, header_paths, is_semver_compatible, major_minor,
    missing_required_release_columns, select_release_columns, tables_under_headings,
)

CHART_DIR = SCRIPT_DIR.parents[0]
DEFAULT_OUTPUT = CHART_DIR / "release-table.csv"

# The four sections this export exists for, on the podiumd release-notes
# Confluence page — pass --heading (repeatable) to override.
DEFAULT_HEADINGS = [
    "Product component versies",
    "Common Ground component versies",
    "Overige component versies",
    "Technische component versies",
]

CSV_HEADER = ["section", "vendor", "used_by", "name", "component", "alias",
              "source version app", "source version helm", "target version app", "target version helm"]

# Stripped from the end of a matched heading before it goes into the CSV's
# "section" column — "Product component versies" -> "Product", etc. Only
# the CSV value is shortened this way; log/warning output (which quotes
# the heading to help you find it back on the actual page) always uses
# the real, full heading text.
SECTION_SUFFIX = " component versies"

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


def section_name(heading):
    """`heading` with SECTION_SUFFIX stripped off the end, if present —
    "Product component versies" -> "Product". Unchanged if it doesn't end
    with that exact suffix (e.g. a custom --heading), rather than
    corrupting text this didn't anticipate."""
    return heading[:-len(SECTION_SUFFIX)] if heading.endswith(SECTION_SUFFIX) else heading


def check_target_matches_chart_version(target_labels, chart_dir):
    """Prints a large warning to stderr for every distinct label in
    `target_labels` (see find_versie_groups — the second, "target",
    "Versie ..." group found per table) whose MAJOR.MINOR doesn't match
    chart_dir/Chart.yaml's own "version:" (patch ignored). Never raises —
    a mismatch is worth a human's attention, not a reason to stop
    exporting whatever the page actually says."""
    chart_yaml_path = chart_dir / "Chart.yaml"
    if not chart_yaml_path.is_file():
        return
    chart_version = str(load_yaml(chart_yaml_path).get("version", ""))
    chart_major_minor = major_minor(chart_version)
    if chart_major_minor is None:
        return

    mismatched = sorted({label for label in target_labels if major_minor(label) != chart_major_minor})
    if not mismatched:
        return

    border = "!" * 72
    print(border, file=sys.stderr)
    print("!! WARNING: Confluence target version does NOT match Chart.yaml !!", file=sys.stderr)
    print(f"!!   Chart.yaml version:        {chart_version}  (major.minor {chart_major_minor})", file=sys.stderr)
    for label in mismatched:
        print(f"!!   Confluence target heading: {label!r}  (major.minor {major_minor(label)})", file=sys.stderr)
    print(border, file=sys.stderr)


NOT_ALNUM_RE = re.compile(r"[^a-z0-9]")
BRACKETED_RE = re.compile(r"\(([^)]*)\)")


def normalize_name(text):
    """`text` lowercased with every non-alphanumeric character (spaces,
    dashes, slashes, parentheses, ...) removed — needed because
    Chart.yaml dependency names are plain lowercase-no-punctuation
    (e.g. "zgw-office-addin", "internetaakafhandeling") while the page's
    own component names use all sorts of separators ("Office Add-in",
    "OMC / Notify")."""
    return NOT_ALNUM_RE.sub("", text.lower())


def name_candidates(name):
    """Every normalized string worth matching against a Chart.yaml
    dependency for `name`: the whole thing, and — if `name` has a
    "... (bracketed part)" shape — the bracketed part and the rest of
    the string, tried separately as well (e.g. "Platform Autorisatie
    Beheer Component (PABC)" tries "platformautorisatiebeheercomponentpabc",
    "platformautorisatiebeheercomponent", AND "pabc" — the last of which
    is what actually resolves it cleanly, against Chart.yaml dependency
    "pabc"'s own alias "pabc"). Matching each part on its own (rather
    than only ever the whole, punctuation-stripped string) avoids a
    false match spanning the boundary between the two parts, and lets an
    exact match fire for a part that's short/generic enough that it
    would only ever relate to something by substring as part of the
    whole string."""
    candidates = [normalize_name(name)]
    match = BRACKETED_RE.search(name)
    if match:
        rest = name[:match.start()] + name[match.end():]
        candidates += [normalize_name(rest), normalize_name(match.group(1))]
    return list(dict.fromkeys(c for c in candidates if c))


def _related(a, b):
    """True if `a` and `b` (both already normalized) are the same
    string, or either contains the other whole — the single relation
    every match rule in component_and_alias reduces to."""
    return bool(a) and bool(b) and (a in b or b in a)


def chart_dependencies(chart_dir):
    """[(dependency_name, alias_or_empty), ...], in Chart.yaml order,
    for every chart_dir/Chart.yaml dependency — e.g.
    [("internetaakafhandeling", "ita"), ("openzaak", ""), ...]. [] if
    chart_dir has no Chart.yaml."""
    chart_yaml_path = chart_dir / "Chart.yaml"
    if not chart_yaml_path.is_file():
        return []
    chart_yaml = load_yaml(chart_yaml_path)
    return [(dep["name"], dep.get("alias", "")) for dep in chart_yaml.get("dependencies", [])]


def component_and_alias(name, dependencies):
    """(component, alias) for `name` (the CSV "name" column value),
    resolved against `dependencies` (see chart_dependencies) by trying
    each of name_candidates(name) against every dependency's own
    normalized name and alias, in this priority order (first hit wins):
    1. a candidate exactly equals the dependency's name — e.g. "Interne
       Taak Afhandeling" -> dependency "internetaakafhandeling"
    2. a candidate relates (see _related) to the dependency's alias —
       e.g. alias "zac" is contained in "Zaak - ZAC" (as "zaakzac"), or
       "PABC" (the bracketed part of "Platform Autorisatie Beheer
       Component (PABC)") exactly equals alias "pabc"
    3. a candidate relates to the dependency's name — e.g. dependency
       name "openzaak" exactly equals "Open Zaak", or "openinwoner" is
       contained in "Open Inwoner platform" (the bracketed part of
       "Portaal (Open Inwoner platform)")
    Tried in that order (exact name match, then alias relation, then the
    looser name relation) so a precise match always wins over a fuzzier
    one. ("UNKNOWN", "") if nothing matches any dependency at all — e.g.
    "Elastic operator", whose dependency "eck-operator" shares no text
    with it either way, or a component (like "Solr") that isn't a
    top-level podiumd Chart.yaml dependency at all."""
    candidates = name_candidates(name)
    for candidate in candidates:
        for dependency_name, alias in dependencies:
            if candidate == normalize_name(dependency_name):
                return dependency_name, alias
    for candidate in candidates:
        for dependency_name, alias in dependencies:
            if alias and _related(candidate, normalize_name(alias)):
                return dependency_name, alias
    for candidate in candidates:
        for dependency_name, alias in dependencies:
            if _related(candidate, normalize_name(dependency_name)):
                return dependency_name, alias
    return "UNKNOWN", ""


def resolve_token(args):
    if args.token_file:
        return Path(args.token_file).read_text(encoding="utf-8").strip()
    if args.token:
        return args.token
    env_token = os.environ.get("CONFLUENCE_API_TOKEN")
    if env_token:
        return env_token
    return getpass.getpass("Confluence API token: ")


def extract_release_rows(html, headings=None, chart_dir=None):
    """Return the CSV data rows (section, vendor, used_by, name,
    component, alias, source version app/helm, target version app/helm)
    across every table directly under one of `headings` (default
    DEFAULT_HEADINGS) that has the required App/Helm columns —
    "section" is the matched heading with SECTION_SUFFIX stripped (see
    section_name). Prints a one-line report
    per matching-heading table (rows matched, or which required column
    it's missing) — using the real, full heading text, not the
    shortened "section" value — and a large warning (see
    check_target_matches_chart_version) if any table's target heading
    doesn't match `chart_dir` (default CHART_DIR) Chart.yaml's version."""
    headings = headings or DEFAULT_HEADINGS
    chart_dir = chart_dir or CHART_DIR
    dependencies = chart_dependencies(chart_dir)
    all_tables = extract_tables(html)
    if not all_tables:
        raise SystemExit("error: no <table> found on that page")

    matching = tables_under_headings(all_tables, headings)
    print(f"Found {len(all_tables)} table(s) on the page, {len(matching)} under a matching heading")
    if not matching:
        raise SystemExit(f"error: no table found directly under any of: {', '.join(headings)}")

    rows_out = []
    unknown_count = 0
    target_labels = []
    for heading, rows in matching:
        grid = expand_grid(rows)
        header_row_count = resolve_header_row_count(rows, grid)
        paths = header_paths(grid, header_row_count)
        groups = find_versie_groups(paths)
        if len(groups) == 2:
            target_labels.append(groups[1][0])
        columns = select_release_columns(paths)
        missing = missing_required_release_columns(columns)
        if missing:
            print(f'"{heading}": skipped (missing required column(s): {", ".join(missing)})')
            continue

        matched = 0
        for data_row in grid[header_row_count:]:
            if not any(cell.strip() for cell in data_row):
                continue
            vendor = data_row[columns["vendor"]] if columns["vendor"] is not None else ""
            used_by = data_row[columns["used_by"]] if columns["used_by"] is not None else ""
            name = data_row[columns["first"]]
            # used_by (when set) is a much better resolution signal than
            # the row's own name — it's often already a literal
            # Chart.yaml alias (e.g. "zac"), whereas a Technische row's
            # own name (e.g. "Solr") usually shares no text with the
            # component that uses it at all.
            component, alias = component_and_alias(used_by or name, dependencies)
            versions = [normalize_version(data_row[columns[key]]) for key in
                        ("source_app", "source_helm", "target_app", "target_helm")]
            unknown_count += sum(1 for v in versions if v == "UNKNOWN")
            rows_out.append([section_name(heading), vendor, used_by, name, component, alias] + versions)
            matched += 1
        print(f'"{heading}": {matched} row(s) matched')

    check_target_matches_chart_version(target_labels, chart_dir)

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
