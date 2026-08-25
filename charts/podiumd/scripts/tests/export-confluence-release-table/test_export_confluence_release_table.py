"""resolve_token, extract_release_rows, check_target_matches_chart_version,
main — with fetch_page_html mocked out, so no network access or real
Confluence page is needed."""
import csv

import pytest


def write_chart_yaml(chart_dir, version):
    (chart_dir / "Chart.yaml").write_text(f"apiVersion: v2\nname: podiumd\nversion: {version}\n", encoding="utf-8")


def write_chart_yaml_with_dependencies(chart_dir, deps):
    """`deps`: [(name, alias_or_None), ...]."""
    lines = ["apiVersion: v2", "name: podiumd", "version: 1.0.0", "dependencies:"]
    for name, alias in deps:
        lines.append(f"  - name: {name}")
        if alias:
            lines.append(f"    alias: {alias}")
        lines += ["    version: 1.0.0", '    repository: "@x"']
    (chart_dir / "Chart.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture(autouse=True)
def isolate_chart_dir(ecrt, tmp_path, monkeypatch):
    """extract_release_rows falls back to the real CHART_DIR (this
    script's actual parent directory) when no chart_dir is passed
    explicitly — tests that don't care about
    check_target_matches_chart_version must not depend on whatever
    charts/podiumd/Chart.yaml happens to say on disk (or which branch is
    checked out) at test-run time."""
    monkeypatch.setattr(ecrt, "CHART_DIR", tmp_path)

PRODUCT_TABLE_HTML = """
<h2>Product component versies</h2>
<table>
<tbody>
<tr>
<th rowspan="2"></th>
<th rowspan="2">Ontwikkelpartij</th>
<th colspan="2">Versie 4.8</th>
<th colspan="2">Versie 4.9</th>
</tr>
<tr>
<th>App</th>
<th>Helm</th>
<th>App</th>
<th>Helm</th>
</tr>
<tr>
<td>ZAC</td>
<td>Info(NL)</td>
<td>5.0.0</td>
<td>1.0.290</td>
<td>5.1.0</td>
<td>1.0.297</td>
</tr>
<tr>
<td>Open Zaak</td>
<td>Maykin</td>
<td>1.27.0</td>
<td>1.14.0</td>
<td>1.27.4</td>
<td>1.14.2</td>
</tr>
</tbody>
</table>
"""

# "Technische component versies" tables don't have a development-partner
# column at all — "Used by" instead (naming the product/Common Ground
# component that pulls this piece of tooling in), which isn't required.
TECHNISCHE_TABLE_HTML = """
<h2>Technische component versies</h2>
<table>
<tbody>
<tr>
<th rowspan="2"></th>
<th rowspan="2">Used by</th>
<th colspan="2">Versie 4.8</th>
<th colspan="2">Versie 4.9</th>
</tr>
<tr>
<th>App</th>
<th>Helm</th>
<th>App</th>
<th>Helm</th>
</tr>
<tr>
<td>Elastic operator</td>
<td>ZAC</td>
<td>3.4.0</td>
<td>3.4.0</td>
<td>3.5.0</td>
<td>3.5.0</td>
</tr>
</tbody>
</table>
"""

# A table with no heading at all above it — not under any of the target
# sections, so it's ignored outright, not merely "skipped for missing
# columns".
UNRELATED_TABLE_HTML = "<table><tr><th>Legend</th></tr><tr><td>n/a</td></tr></table>"

# Under a target heading, but genuinely missing the required App/Helm
# columns — this one SHOULD be reported as skipped.
INCOMPLETE_UNDER_TARGET_HEADING_HTML = (
    "<h2>Overige component versies</h2><table><tr><th>Naam</th></tr><tr><td>iets</td></tr></table>"
)


# --- normalize_version ---

def test_normalize_version_leaves_valid_semver_untouched(ecrt):
    assert ecrt.normalize_version("1.27.4") == "1.27.4"
    assert ecrt.normalize_version("9.10.1-slim") == "9.10.1-slim"


def test_normalize_version_leaves_allowed_variations_untouched(ecrt):
    """Missing patch component and a stray "." after a leading "v" are
    allowed variations, not something to flag — see
    lib.confluence_tables.SEMVER_RE."""
    assert ecrt.normalize_version("3.20") == "3.20"
    assert ecrt.normalize_version("3.14-slim") == "3.14-slim"
    assert ecrt.normalize_version("v.1.25.4") == "v.1.25.4"


def test_normalize_version_leaves_empty_value_untouched(ecrt):
    """No data at all for that cell isn't a malformed version — nothing
    to flag."""
    assert ecrt.normalize_version("") == ""


def test_normalize_version_replaces_non_semver_with_unknown(ecrt):
    assert ecrt.normalize_version("5.4.3 5.4.4") == "UNKNOWN"
    assert ecrt.normalize_version("?") == "UNKNOWN"


# --- resolve_token ---

def make_args(**overrides):
    from types import SimpleNamespace
    defaults = {"token_file": None, "token": None}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_resolve_token_prefers_token_file(ecrt, tmp_path):
    token_file = tmp_path / "token.txt"
    token_file.write_text("  s3cr3t-from-file  \n", encoding="utf-8")
    args = make_args(token_file=str(token_file), token="ignored-since-file-wins")
    assert ecrt.resolve_token(args) == "s3cr3t-from-file"


def test_resolve_token_falls_back_to_token_arg(ecrt):
    args = make_args(token="s3cr3t-from-arg")
    assert ecrt.resolve_token(args) == "s3cr3t-from-arg"


def test_resolve_token_falls_back_to_env_var(ecrt, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "s3cr3t-from-env")
    args = make_args()
    assert ecrt.resolve_token(args) == "s3cr3t-from-env"


def test_resolve_token_prompts_as_last_resort(ecrt, monkeypatch):
    monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
    monkeypatch.setattr(ecrt.getpass, "getpass", lambda prompt: "s3cr3t-from-prompt")
    args = make_args()
    assert ecrt.resolve_token(args) == "s3cr3t-from-prompt"


# Same shape as PRODUCT_TABLE_HTML, but the "App"/"Helm" sub-header row
# is plain <td>, not <th> — seen on the real podiumd page, where
# Confluence's own <th> tagging is inconsistent between a table's header
# rows.
PRODUCT_TABLE_INCONSISTENT_TH_HTML = PRODUCT_TABLE_HTML.replace(
    "<tr>\n<th>App</th>\n<th>Helm</th>\n<th>App</th>\n<th>Helm</th>\n</tr>",
    "<tr>\n<td>App</td>\n<td>Helm</td>\n<td>App</td>\n<td>Helm</td>\n</tr>",
)


# --- resolve_header_row_count ---

def test_resolve_header_row_count_extends_past_inconsistent_th_tagging(ecrt):
    from lib.confluence_tables import expand_grid, extract_tables
    _heading, rows = extract_tables(PRODUCT_TABLE_INCONSISTENT_TH_HTML)[0]
    grid = expand_grid(rows)
    assert ecrt.resolve_header_row_count(rows, grid) == 2


def test_extract_release_rows_handles_inconsistent_th_tagging(ecrt):
    """End-to-end: the same table with a <td>-tagged sub-header row must
    still resolve every required column, not just the ones a strict
    <th>-only header count would catch."""
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_INCONSISTENT_TH_HTML)
    assert rows == [
        ["Product", "Info(NL)", "", "ZAC", "UNKNOWN", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Product", "Maykin", "", "Open Zaak", "UNKNOWN", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]


# --- check_target_matches_chart_version ---

def test_check_target_matches_chart_version_silent_when_major_minor_matches(ecrt, tmp_path, capsys):
    write_chart_yaml(tmp_path, "4.9.0")
    ecrt.check_target_matches_chart_version(["Versie 4.9"], tmp_path)
    assert capsys.readouterr().err == ""


def test_check_target_matches_chart_version_warns_on_mismatch(ecrt, tmp_path, capsys):
    write_chart_yaml(tmp_path, "4.9.0")
    ecrt.check_target_matches_chart_version(["Versie 5.0"], tmp_path)
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "Chart.yaml version:        4.9.0" in err
    assert "'Versie 5.0'" in err


def test_check_target_matches_chart_version_ignores_patch(ecrt, tmp_path, capsys):
    """Chart.yaml at 4.9.3 (a patch release) must not warn just because
    the page still says "Versie 4.9" — only major.minor is compared."""
    write_chart_yaml(tmp_path, "4.9.3")
    ecrt.check_target_matches_chart_version(["Versie 4.9"], tmp_path)
    assert capsys.readouterr().err == ""


def test_check_target_matches_chart_version_dedupes_repeated_labels(ecrt, tmp_path, capsys):
    write_chart_yaml(tmp_path, "4.9.0")
    ecrt.check_target_matches_chart_version(["Versie 5.0", "Versie 5.0", "Versie 5.0"], tmp_path)
    err = capsys.readouterr().err
    assert err.count("'Versie 5.0'") == 1


def test_check_target_matches_chart_version_no_labels_is_silent(ecrt, tmp_path, capsys):
    write_chart_yaml(tmp_path, "4.9.0")
    ecrt.check_target_matches_chart_version([], tmp_path)
    assert capsys.readouterr().err == ""


def test_check_target_matches_chart_version_missing_chart_yaml_is_silent(ecrt, tmp_path, capsys):
    ecrt.check_target_matches_chart_version(["Versie 5.0"], tmp_path)
    assert capsys.readouterr().err == ""


# --- chart_dependencies ---

def test_chart_dependencies_reads_chart_yaml(ecrt, tmp_path):
    write_chart_yaml_with_dependencies(tmp_path, [("internetaakafhandeling", "ita"), ("openzaak", None)])
    assert ecrt.chart_dependencies(tmp_path) == [("internetaakafhandeling", "ita"), ("openzaak", "")]


def test_chart_dependencies_missing_chart_yaml_returns_empty(ecrt, tmp_path):
    assert ecrt.chart_dependencies(tmp_path) == []


# --- normalize_name / name_candidates ---

def test_normalize_name_strips_all_punctuation(ecrt):
    assert ecrt.normalize_name("Zaak - ZAC") == "zaakzac"
    assert ecrt.normalize_name("OMC / Notify") == "omcnotify"


def test_name_candidates_no_brackets_is_just_the_whole_name(ecrt):
    assert ecrt.name_candidates("Zaak - ZAC") == ["zaakzac"]


def test_name_candidates_splits_bracketed_part_from_the_rest(ecrt):
    assert ecrt.name_candidates("Contact (KISS)") == ["contactkiss", "contact", "kiss"]


def test_name_candidates_dedupes_and_drops_empties(ecrt):
    """"(KISS)" alone, with nothing outside the brackets, must not
    produce a spurious empty "rest" candidate."""
    assert ecrt.name_candidates("(KISS)") == ["kiss"]


# --- component_and_alias ---

def test_component_and_alias_exact_name_match(ecrt):
    deps = [("internetaakafhandeling", "ita")]
    assert ecrt.component_and_alias("Interne Taak Afhandeling", deps) == ("internetaakafhandeling", "ita")


def test_component_and_alias_case_insensitive(ecrt):
    deps = [("internetaakafhandeling", "ita")]
    assert ecrt.component_and_alias("INTERNE TAAK AFHANDELING", deps) == ("internetaakafhandeling", "ita")


def test_component_and_alias_resolves_via_alias_substring(ecrt):
    """"Zaak - ZAC" doesn't equal dependency name "zaakafhandelcomponent"
    exactly, but its own alias "zac" is a literal substring of "Zaak -
    ZAC" (spaces/dash stripped: "zaakzac") — this is the rule that
    resolves most real components (the exact-match rule alone only ever
    fires for a name that's coincidentally identical to its Chart.yaml
    dependency name, like "Interne Taak Afhandeling")."""
    deps = [("zaakafhandelcomponent", "zac")]
    assert ecrt.component_and_alias("Zaak - ZAC", deps) == ("zaakafhandelcomponent", "zac")


def test_component_and_alias_resolves_via_bracketed_alias_exact_match(ecrt):
    """The bracketed part alone ("PABC") exactly equals the dependency's
    alias — resolved via name_candidates splitting it out, even though
    the whole name only contains it as a small piece of a much longer
    string."""
    deps = [("pabc", "pabc")]
    assert ecrt.component_and_alias("Platform Autorisatie Beheer Component (PABC)", deps) == ("pabc", "pabc")


def test_component_and_alias_resolves_via_name_relation_without_alias(ecrt):
    """A dependency with no alias at all can still resolve, purely by its
    own name relating to (here: being contained in) the bracketed part
    of the component's name."""
    deps = [("openinwoner", "")]
    assert ecrt.component_and_alias("Portaal (Open Inwoner platform)", deps) == ("openinwoner", "")


def test_component_and_alias_exact_match_takes_priority_over_alias_relation(ecrt):
    """"kiss" exactly equals one dependency's own name — that wins over a
    *different* dependency whose alias merely relates to it."""
    deps = [("kiss-chart", "kiss"), ("kiss", "k")]
    assert ecrt.component_and_alias("kiss", deps) == ("kiss", "k")


def test_component_and_alias_unresolved_is_unknown(ecrt):
    """"Open Zaak" doesn't match any dependency at all — "component"
    becomes UNKNOWN rather than left blank or guessed at, and "alias"
    stays empty."""
    assert ecrt.component_and_alias("Open Zaak", []) == ("UNKNOWN", "")


def test_component_and_alias_exact_alias_match_beats_substring_ambiguity(ecrt):
    """"kiss" exactly equals "kiss-chart"'s own alias "kiss" — that must
    resolve outright, even though "eck-stack"'s alias "kiss-eck" also
    happens to *contain* "kiss" as a substring. An exact alias match is
    its own tier, ahead of the looser substring-relation tier, precisely
    so this isn't treated as an ambiguity."""
    deps = [("kiss-chart", "kiss"), ("eck-stack", "kiss-eck")]
    assert ecrt.component_and_alias("kiss", deps) == ("kiss-chart", "kiss")


def test_component_and_alias_multiple_when_two_dependencies_share_exact_alias(ecrt):
    """A genuine ambiguity at the exact-alias tier: two dependencies
    that (however unusually) share the literal same alias — there's no
    principled way to prefer one over the other."""
    deps = [("foo-chart", "shared"), ("bar-chart", "shared")]
    assert ecrt.component_and_alias("shared", deps) == ("MULTIPLE", "MULTIPLE")


def test_component_and_alias_multiple_alias_relation_matches_is_multiple(ecrt):
    """A genuine ambiguity at the (looser, substring) alias-relation
    tier: "somekisseck" isn't an exact alias match for either dependency
    (ruling out tier 2), but contains both "kiss-chart"'s alias "kiss"
    and "eck-stack"'s alias "kiss-eck" as substrings."""
    deps = [("kiss-chart", "kiss"), ("eck-stack", "kiss-eck")]
    assert ecrt.component_and_alias("somekisseck", deps) == ("MULTIPLE", "MULTIPLE")


def test_component_and_alias_multiple_name_relation_matches_is_multiple(ecrt):
    """Same ambiguity, but at the (alias-less) name-relation tier: "foo"
    relates to both dependency names "foobar" and "foobaz"."""
    deps = [("foobar", ""), ("foobaz", "")]
    assert ecrt.component_and_alias("foo", deps) == ("MULTIPLE", "MULTIPLE")


def test_component_and_alias_clean_exact_match_short_circuits_ambiguous_lower_tier(ecrt):
    """A single exact-name match at tier 1 resolves immediately —
    without ever reaching the looser alias-relation tier, which would
    otherwise have been ambiguous between "kiss-chart" and "eck-stack"
    for this same text."""
    deps = [("kiss", "k"), ("kiss-chart", "kiss"), ("eck-stack", "kiss-eck")]
    assert ecrt.component_and_alias("kiss", deps) == ("kiss", "k")


# --- extract_release_rows ---

def test_extract_release_rows_matches_and_reports(ecrt, capsys):
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML)
    assert rows == [
        ["Product", "Info(NL)", "", "ZAC", "UNKNOWN", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Product", "Maykin", "", "Open Zaak", "UNKNOWN", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]
    out = capsys.readouterr().out
    assert "2 row(s) matched" in out


def test_extract_release_rows_resolves_component_and_alias_by_exact_match(ecrt, tmp_path):
    """A Chart.yaml dependency named exactly "zac" (with spaces stripped,
    identical to the row's own "ZAC") that also has an alias resolves
    "component"/"alias" for that row; "Open Zaak" doesn't match any
    dependency name this way and stays UNKNOWN. Uses a deliberately
    non-colliding alias ("zacalias") — a too-short one (e.g. "z") would
    spuriously substring-match "Open Zaak" too and defeat the point of
    this test."""
    write_chart_yaml_with_dependencies(tmp_path, [("zac", "zacalias")])
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    assert rows == [
        ["Product", "Info(NL)", "", "ZAC", "zac", "zacalias", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Product", "Maykin", "", "Open Zaak", "UNKNOWN", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]


def test_extract_release_rows_resolves_component_and_alias_by_alias_substring(ecrt, tmp_path):
    """"ZAC" doesn't equal dependency name "zaakafhandelcomponent"
    exactly, but the dependency's own alias "zac" is a substring of it —
    this is the rule that resolves most real components (see
    component_and_alias)."""
    write_chart_yaml_with_dependencies(tmp_path, [("zaakafhandelcomponent", "zac")])
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    assert rows[0] == ["Product", "Info(NL)", "", "ZAC", "zaakafhandelcomponent", "zac",
                        "5.0.0", "1.0.290", "5.1.0", "1.0.297"]


def test_extract_release_rows_resolves_component_without_alias_via_name_relation(ecrt, tmp_path):
    """"Open Zaak" resolves purely via a name relation against a
    dependency that has no alias at all — "component" gets that
    dependency's name and "alias" stays empty. "ZAC" doesn't relate to
    "openzaak" at all and stays UNKNOWN."""
    write_chart_yaml_with_dependencies(tmp_path, [("openzaak", None)])
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    assert rows[0][4] == "UNKNOWN"
    assert rows[1] == ["Product", "Maykin", "", "Open Zaak", "openzaak", "",
                        "1.27.0", "1.14.0", "1.27.4", "1.14.2"]


def test_extract_release_rows_not_tied_to_specific_version_numbers(ecrt):
    """The page renames "Versie 4.8"/"Versie 4.9" every release — a table
    headed "Versie 5.0"/"Versie 5.1" instead must resolve exactly the
    same way, into "source"/"target" by column order, not by number."""
    html = PRODUCT_TABLE_HTML.replace("Versie 4.8", "Versie 5.0").replace("Versie 4.9", "Versie 5.1")
    rows = ecrt.extract_release_rows(html)
    assert rows == [
        ["Product", "Info(NL)", "", "ZAC", "UNKNOWN", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Product", "Maykin", "", "Open Zaak", "UNKNOWN", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]


def test_extract_release_rows_replaces_non_semver_version_with_unknown_and_reports_count(ecrt, capsys):
    html = PRODUCT_TABLE_HTML.replace("<td>5.1.0</td>", "<td>?</td>")
    rows = ecrt.extract_release_rows(html)
    assert rows[0] == ["Product", "Info(NL)", "", "ZAC", "UNKNOWN", "", "5.0.0", "1.0.290", "UNKNOWN", "1.0.297"]
    out = capsys.readouterr().out
    assert "1 version value(s) were not semver-compatible — replaced with UNKNOWN" in out


def test_extract_release_rows_ignores_table_not_under_any_target_heading(ecrt, capsys):
    html = UNRELATED_TABLE_HTML + PRODUCT_TABLE_HTML
    rows = ecrt.extract_release_rows(html)
    assert len(rows) == 2
    out = capsys.readouterr().out
    assert "Found 2 table(s) on the page, 1 under a matching heading" in out
    assert "Legend" not in out  # the unrelated table was never even reported on


def test_extract_release_rows_reports_skip_for_incomplete_table_under_target_heading(ecrt, capsys):
    html = INCOMPLETE_UNDER_TARGET_HEADING_HTML + PRODUCT_TABLE_HTML
    rows = ecrt.extract_release_rows(html)
    assert len(rows) == 2
    out = capsys.readouterr().out
    assert '"Overige component versies": skipped (missing required column(s):' in out


def test_extract_release_rows_vendor_blank_used_by_populated_for_technische_table(ecrt):
    """A "Technische component versies" table has no Ontwikkelpartij
    column (vendor blank) but does have "Used by" — the reverse of a
    Product table."""
    rows = ecrt.extract_release_rows(TECHNISCHE_TABLE_HTML)
    assert rows == [["Technische", "", "ZAC", "Elastic operator", "UNKNOWN", "", "3.4.0", "3.4.0", "3.5.0", "3.5.0"]]


def test_extract_release_rows_resolves_component_via_used_by_not_name(ecrt, tmp_path):
    """TECHNISCHE_TABLE_HTML's row is named "Elastic operator" (shares no
    text with any real dependency) but has used_by "ZAC" — a much better
    resolution signal, since it's already the dependency's own alias.
    Resolution must use it instead of the row's own name."""
    write_chart_yaml_with_dependencies(tmp_path, [("zaakafhandelcomponent", "zac")])
    rows = ecrt.extract_release_rows(TECHNISCHE_TABLE_HTML, chart_dir=tmp_path)
    assert rows == [["Technische", "", "ZAC", "Elastic operator", "zaakafhandelcomponent", "zac",
                      "3.4.0", "3.4.0", "3.5.0", "3.5.0"]]


def test_extract_release_rows_resolves_exact_alias_match_despite_unrelated_substring_alias(ecrt, tmp_path):
    """A used_by value ("kiss") that exactly equals one dependency's own
    alias resolves outright, even with a second dependency ("eck-stack")
    present whose own alias ("kiss-eck") merely contains "kiss" as a
    substring — this must NOT register as an ambiguity."""
    write_chart_yaml_with_dependencies(tmp_path, [("kiss-chart", "kiss"), ("eck-stack", "kiss-eck")])
    html = TECHNISCHE_TABLE_HTML.replace("<td>ZAC</td>", "<td>kiss</td>")
    rows = ecrt.extract_release_rows(html, chart_dir=tmp_path)
    assert rows == [["Technische", "", "kiss", "Elastic operator", "kiss-chart", "kiss",
                      "3.4.0", "3.4.0", "3.5.0", "3.5.0"]]


def test_extract_release_rows_resolves_component_as_multiple(ecrt, tmp_path):
    """A used_by value ("shared") that's the literal same alias on two
    distinct Chart.yaml dependencies resolves the row to
    "MULTIPLE"/"MULTIPLE" rather than silently picking one."""
    write_chart_yaml_with_dependencies(tmp_path, [("foo-chart", "shared"), ("bar-chart", "shared")])
    html = TECHNISCHE_TABLE_HTML.replace("<td>ZAC</td>", "<td>shared</td>")
    rows = ecrt.extract_release_rows(html, chart_dir=tmp_path)
    assert rows == [["Technische", "", "shared", "Elastic operator", "MULTIPLE", "MULTIPLE",
                      "3.4.0", "3.4.0", "3.5.0", "3.5.0"]]


def test_extract_release_rows_used_by_blank_when_table_has_none(ecrt):
    """A Product table has no "Used by" column at all (only Ontwikkelpartij)."""
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML)
    assert all(row[2] == "" for row in rows)  # used_by is the 3rd column: section, vendor, used_by, ...


def test_extract_release_rows_combines_multiple_sections(ecrt):
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML + TECHNISCHE_TABLE_HTML)
    assert [r[0] for r in rows] == ["Product", "Product",
                                     "Technische"]


def test_extract_release_rows_custom_headings_overrides_default(ecrt):
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML + TECHNISCHE_TABLE_HTML,
                                      headings=["Technische component versies"])
    assert len(rows) == 1
    assert rows[0][0] == "Technische"


def test_extract_release_rows_no_tables_raises(ecrt):
    with pytest.raises(SystemExit, match="no <table> found"):
        ecrt.extract_release_rows("<p>no tables here</p>")


def test_extract_release_rows_no_table_under_target_heading_raises(ecrt):
    with pytest.raises(SystemExit, match="no table found directly under any of"):
        ecrt.extract_release_rows(UNRELATED_TABLE_HTML)


def test_extract_release_rows_every_matching_table_incomplete_raises(ecrt):
    with pytest.raises(SystemExit, match="every matching-heading table was missing a required column"):
        ecrt.extract_release_rows(INCOMPLETE_UNDER_TARGET_HEADING_HTML)


def test_extract_release_rows_skips_fully_blank_rows(ecrt):
    html = PRODUCT_TABLE_HTML.replace(
        "<tr>\n<td>Open Zaak</td>",
        "<tr><td></td><td></td><td></td><td></td><td></td><td></td></tr>\n<tr>\n<td>Open Zaak</td>",
    )
    rows = ecrt.extract_release_rows(html)
    assert len(rows) == 2  # the all-blank row was skipped, not counted


def test_extract_release_rows_warns_when_target_does_not_match_chart_yaml(ecrt, tmp_path, capsys):
    """PRODUCT_TABLE_HTML's target heading is "Versie 4.9" — a
    Chart.yaml at a different minor version must trigger the warning."""
    write_chart_yaml(tmp_path, "5.0.0")
    ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "'Versie 4.9'" in err


def test_extract_release_rows_silent_when_target_matches_chart_yaml(ecrt, tmp_path, capsys):
    write_chart_yaml(tmp_path, "4.9.0")
    ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    assert capsys.readouterr().err == ""


# --- main() integration ---

def test_main_writes_csv(ecrt, tmp_path, monkeypatch, capsys):
    output_path = tmp_path / "release-table.csv"
    monkeypatch.setattr(ecrt.sys, "argv", [
        "export-confluence-release-table.py",
        "--url", "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
        "--user", "kees@info.nl",
        "--token", "s3cr3t",
        "--output", str(output_path),
    ])
    monkeypatch.setattr(ecrt, "fetch_page_html", lambda url, user, token: PRODUCT_TABLE_HTML)

    ecrt.main()

    with output_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["section", "vendor", "used_by", "name", "component", "alias",
                        "source version app", "source version helm",
                        "target version app", "target version helm"]
    assert rows[1] == ["Product", "Info(NL)", "", "ZAC", "UNKNOWN", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"]
    assert rows[2] == ["Product", "Maykin", "", "Open Zaak", "UNKNOWN", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"]
    out = capsys.readouterr().out
    assert f"Wrote 2 row(s) to {output_path}" in out


def test_main_passes_resolved_token_and_url_user_through(ecrt, tmp_path, monkeypatch):
    output_path = tmp_path / "out.csv"
    monkeypatch.setattr(ecrt.sys, "argv", [
        "export-confluence-release-table.py",
        "--url", "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
        "--user", "kees@info.nl",
        "--token", "s3cr3t",
        "--output", str(output_path),
    ])
    captured = {}

    def fake_fetch(url, user, token):
        captured.update(url=url, user=user, token=token)
        return PRODUCT_TABLE_HTML

    monkeypatch.setattr(ecrt, "fetch_page_html", fake_fetch)
    ecrt.main()
    assert captured == {
        "url": "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
        "user": "kees@info.nl",
        "token": "s3cr3t",
    }


def test_main_passes_custom_heading_flags_through(ecrt, tmp_path, monkeypatch):
    output_path = tmp_path / "out.csv"
    monkeypatch.setattr(ecrt.sys, "argv", [
        "export-confluence-release-table.py",
        "--url", "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
        "--user", "kees@info.nl",
        "--token", "s3cr3t",
        "--output", str(output_path),
        "--heading", "Technische component versies",
    ])
    monkeypatch.setattr(ecrt, "fetch_page_html",
                         lambda url, user, token: PRODUCT_TABLE_HTML + TECHNISCHE_TABLE_HTML)

    ecrt.main()

    with output_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2  # header + the one Technische row only
    assert rows[1][0] == "Technische"
