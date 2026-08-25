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
text with it either way — or "MULTIPLE" (both fields) if the text
relates to more than one distinct dependency at the SAME priority tier
(e.g. two dependencies that genuinely share one alias) — rather than
silently picking whichever dependency happens to come first in
Chart.yaml. An exact alias match is its own tier ahead of the looser
substring-relation tier specifically so a case like "kiss" — which
exactly equals dependency "kiss-chart"'s own alias "kiss", but is also
a substring of "eck-stack"'s unrelated alias "kiss-eck" — resolves
outright instead of registering as ambiguous.

If nothing matches any real dependency at all, falls back to
`chart_dir`/values.yaml's own top-level keys that AREN'T tied to any
Chart.yaml dependency (see orphan_values_yaml_keys) — e.g. "Frank
Gateway" resolves to component "frankgateway", a block templated
directly by podiumd's own templates rather than backed by a separate
sub-chart, so it never appears in Chart.yaml's dependency list. This is
strictly a last resort, so an orphan key can never hijack a name that
already resolves through a real dependency.

If NEITHER of those matches anything either, checks `chart_dir`/
values.yaml's own global.images keys (see global_image_keys) — e.g.
"nginx", "curl", "busybox" — base images hoisted out of any single
component's own block specifically because they're shared, via YAML
anchor, across multiple unrelated components. A match here is never
resolved to a single component: it always comes back as "MULTIPLE" (see
below) — e.g. "Nginx unprivileged" relates to global.images key "nginx",
which is aliased under nine distinct, unrelated components (openzaak,
opennotificaties, openformulieren, frankgateway, apiproxy, ...), so
there's no single owner to report.

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
plain 403). To create one: open that URL, click "Create API token", pick
"Create classic API token" specifically (not the default "scoped" kind),
give it a label (e.g. "podiumd-release-table"), then copy the token
immediately — it's only ever shown once. Prefer --token-file or the
CONFLUENCE_API_TOKEN env var over --token — a token passed as a bare CLI
argument shows up in shell history and `ps` output. Omitting all three
prompts for it (hidden input, not echoed).

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
              "source_version_app", "source_version_helm", "target_version_app", "target_version_helm"]

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


def orphan_values_yaml_keys(chart_dir, dependencies):
    """[(key, ""), ...] for every top-level key of chart_dir/values.yaml
    that isn't already a Chart.yaml dependency's own name or alias (see
    `dependencies`, from chart_dependencies) — e.g. "frankgateway", a
    values.yaml block templated directly by podiumd's own templates
    rather than backed by a separate Helm sub-chart, so it never appears
    in Chart.yaml's dependency list at all. [] if chart_dir has no
    values.yaml. component_and_alias only ever tries these as a last
    resort, after every real dependency, so an orphan key can never
    outrank (and thus never regress) a resolution that already works
    through a real dependency — e.g. values.yaml's own "keycloak" block
    (the Keycloak instance's own config, separate from the
    "keycloak-operator" dependency that manages it) must not hijack
    "Keycloak" away from correctly resolving to "keycloak-operator"."""
    values_yaml_path = chart_dir / "values.yaml"
    if not values_yaml_path.is_file():
        return []
    values = load_yaml(values_yaml_path)
    if not isinstance(values, dict):
        return []
    known = {normalize_name(dependency_name) for dependency_name, _ in dependencies}
    known |= {normalize_name(alias) for _, alias in dependencies if alias}
    return [(key, "") for key in values if normalize_name(key) not in known]


def global_image_keys(chart_dir):
    """Every key under chart_dir/values.yaml's top-level global.images map
    (e.g. "nginx", "curl", "busybox") — base images hoisted out of any
    single component's own block specifically because they're shared via
    YAML anchor across multiple, unrelated components (see e.g. the
    &nginxImage anchor aliased under openzaak, opennotificaties,
    openformulieren, frankgateway, apiproxy, ... — nine call sites across
    distinct top-level values.yaml blocks). A key living here at all is
    proof by construction that it belongs to more than one component, so
    component_and_alias treats any match against one as MULTIPLE outright
    rather than guessing which single component "owns" it. [] if
    chart_dir has no values.yaml, or values.yaml has no global.images
    map."""
    values_yaml_path = chart_dir / "values.yaml"
    if not values_yaml_path.is_file():
        return []
    values = load_yaml(values_yaml_path)
    if not isinstance(values, dict):
        return []
    images = (values.get("global") or {}).get("images")
    return list(images) if isinstance(images, dict) else []


def _tier_matches(candidates, dependencies, predicate):
    """{dependency_name: alias} for every dependency in `dependencies`
    where `predicate(candidate, dependency_name, alias)` holds for at
    least one of `candidates` — every distinct dependency that matches
    at this priority tier, not just the first, so component_and_alias
    can tell a clean single match from a genuine ambiguity."""
    found = {}
    for candidate in candidates:
        for dependency_name, alias in dependencies:
            if dependency_name not in found and predicate(candidate, dependency_name, alias):
                found[dependency_name] = alias
    return found


# Tried in this order (first tier with any match wins) so a precise
# match always beats a fuzzier one — see component_and_alias. An EXACT
# alias match is its own tier, ahead of the looser alias *relation* tier
# below it: e.g. "kiss" exactly equals dependency "kiss-chart"'s own
# alias "kiss", and that must resolve outright rather than being treated
# as ambiguous with "eck-stack" (alias "kiss-eck") just because
# "kiss-eck" also happens to *contain* "kiss" as a substring.
_MATCH_TIERS = [
    lambda candidate, dependency_name, alias: candidate == normalize_name(dependency_name),
    lambda candidate, dependency_name, alias: bool(alias) and candidate == normalize_name(alias),
    lambda candidate, dependency_name, alias: bool(alias) and _related(candidate, normalize_name(alias)),
    lambda candidate, dependency_name, alias: _related(candidate, normalize_name(dependency_name)),
]


def _resolve_against(candidates, dependencies):
    """(dependency_name, alias) from the first tier in _MATCH_TIERS with
    exactly one distinct match against `dependencies`, ("MULTIPLE",
    "MULTIPLE") from the first tier with more than one, or None if no
    tier matches anything at all (caller decides what None means)."""
    for tier in _MATCH_TIERS:
        found = _tier_matches(candidates, dependencies, tier)
        if len(found) == 1:
            return next(iter(found.items()))
        if len(found) > 1:
            return ("MULTIPLE", "MULTIPLE")
    return None


def component_and_alias(name, dependencies, orphan_keys=(), global_image_keys=()):
    """(component, alias) for `name` (the CSV "name" column value),
    resolved against `dependencies` (see chart_dependencies) by trying
    each of name_candidates(name) against every dependency's own
    normalized name and alias, in this priority order (first tier with
    any match wins):
    1. a candidate exactly equals the dependency's name — e.g. "Interne
       Taak Afhandeling" -> dependency "internetaakafhandeling"
    2. a candidate exactly equals the dependency's alias — e.g. "kiss"
       (used_by, or the bracketed part of "Contact (KISS)") exactly
       equals alias "kiss", or "PABC" (the bracketed part of "Platform
       Autorisatie Beheer Component (PABC)") exactly equals alias "pabc"
    3. a candidate relates (see _related, a looser substring-either-way
       check) to the dependency's alias — e.g. alias "zac" is contained
       in "Zaak - ZAC" (as "zaakzac")
    4. a candidate relates to the dependency's name — e.g. dependency
       name "openzaak" exactly equals "Open Zaak", or "openinwoner" is
       contained in "Open Inwoner platform" (the bracketed part of
       "Portaal (Open Inwoner platform)")
    Tiers 2 and 3 are both about the alias, split apart specifically so
    an exact alias match (tier 2) never loses to a same-tier ambiguity
    that only exists because some OTHER dependency's alias happens to
    contain the candidate as a substring (tier 3) — see _MATCH_TIERS.

    If nothing matches any real dependency at all, falls back to trying
    the exact same tiers against `orphan_keys` (see
    orphan_values_yaml_keys) — values.yaml top-level blocks that aren't
    backed by any Chart.yaml dependency, like "frankgateway". This is
    strictly a last resort: a real dependency always wins first, so an
    orphan key can never hijack a name that already resolves correctly.

    If NEITHER of those matches anything either, checks whether a
    candidate relates to one of `global_image_keys` (see
    global_image_keys) — e.g. "Nginx unprivileged" relates to key
    "nginx". Unlike the two pools above, a match here is never resolved
    to a single component: a key living under global.images exists
    specifically because it's shared, via YAML anchor, across multiple
    unrelated components, so it always resolves as ("MULTIPLE",
    "MULTIPLE") outright rather than guessing an owner.

    ("UNKNOWN", "") if nothing matches at all, in any of the three pools
    — e.g. "Elastic operator", whose dependency "eck-operator" shares no
    text with it either way, or a component (like "Solr") that isn't a
    top-level podiumd Chart.yaml dependency, orphan values.yaml key, or
    global image key at all. ("MULTIPLE", "MULTIPLE") if a single tier
    matches more than one distinct dependency (or, in the orphan-key
    pool, more than one distinct orphan key), or if anything at all
    matches a global image key — rather than silently picking whichever
    came first."""
    candidates = name_candidates(name)
    resolved = _resolve_against(candidates, dependencies) or _resolve_against(candidates, orphan_keys)
    if resolved:
        return resolved
    if any(_related(candidate, normalize_name(key)) for candidate in candidates for key in global_image_keys):
        return ("MULTIPLE", "MULTIPLE")
    return ("UNKNOWN", "")


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
    component, alias, source_version_app/helm, target_version_app/helm)
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
    orphan_keys = orphan_values_yaml_keys(chart_dir, dependencies)
    global_keys = global_image_keys(chart_dir)
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
            component, alias = component_and_alias(used_by or name, dependencies, orphan_keys, global_keys)
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
