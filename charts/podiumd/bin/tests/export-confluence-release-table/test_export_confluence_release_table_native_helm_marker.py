"""apply_native_helm_marker — with fetch_page_html mocked out, so no
network access or real Confluence page is needed."""

from pathlib import Path
from types import ModuleType

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


def write_values_yaml(chart_dir, keys):
    """A minimal values.yaml with each of `keys` as a top-level key
    mapping to an empty block."""
    (chart_dir / "values.yaml").write_text(
        "".join(f"{key}: {{}}\n" for key in keys),
        encoding="utf-8",
    )


def write_values_yaml_with_global_images(chart_dir, image_keys):
    """A minimal values.yaml with a top-level global.images map holding
    each of `image_keys` — mirrors the real chart's
    global.images.nginx/curl/busybox shared-base-image anchors."""
    lines = ["global:", "  images:"] + [f"    {key}: {{}}" for key in image_keys]
    (chart_dir / "values.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


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

# Same shape as TECHNISCHE_TABLE_HTML, but without the App/Helm
# sub-header split at all -- since 2026-09 the real page's "Technische
# component versies" table dropped its Helm sub-column entirely (its
# cells were always empty anyway), leaving one bare column per
# "Versie ..." group.
TECHNISCHE_TABLE_NO_HELM_HTML = """
<h2>Technische component versies</h2>
<table>
<tbody>
<tr>
<th></th>
<th>Used by</th>
<th>Versie 4.8</th>
<th>Versie 4.9</th>
</tr>
<tr>
<td>Elastic operator</td>
<td>ZAC</td>
<td>3.4.0</td>
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


# --- apply_native_helm_marker ---


def _row(used_by="", component="frankgateway", source_helm="", target_helm=""):
    return ["Product", "", used_by, "Frank Gateway", component, "", "", "104", source_helm, "105", target_helm]


def test_apply_native_helm_marker_fills_native_for_resolved_primary_row(ecrt: ModuleType):
    rows = [_row()]
    ecrt.apply_native_helm_marker(rows)
    assert rows[0][8] == "NATIVE" and rows[0][10] == "NATIVE"


def test_apply_native_helm_marker_skips_multiple(ecrt: ModuleType):
    rows = [_row(component="MULTIPLE")]
    ecrt.apply_native_helm_marker(rows)
    assert rows[0][8] == "" and rows[0][10] == ""


def test_apply_native_helm_marker_skips_unknown(ecrt: ModuleType):
    rows = [_row(component="UNKNOWN")]
    ecrt.apply_native_helm_marker(rows)
    assert rows[0][8] == "" and rows[0][10] == ""


def test_apply_native_helm_marker_skips_blank_component(ecrt: ModuleType):
    rows = [_row(component="")]
    ecrt.apply_native_helm_marker(rows)
    assert rows[0][8] == "" and rows[0][10] == ""


def test_apply_native_helm_marker_skips_used_by_tagged_row(ecrt: ModuleType):
    """A "used_by"-tagged sidecar row is never a component in its own
    right — "NATIVE" would be meaningless there, so it's left untouched
    even when its own helm cells are blank and its component resolved
    to a real single dependency."""
    rows = [_row(used_by="zac")]
    ecrt.apply_native_helm_marker(rows)
    assert rows[0][8] == "" and rows[0][10] == ""


def test_apply_native_helm_marker_skips_row_with_a_real_helm_value(ecrt: ModuleType):
    """Only BOTH helm cells blank counts as "genuinely no Helm chart" —
    a row with a real (or even just source-only/target-only) helm
    value is a normal versioned Helm dependency, left untouched."""
    rows = [_row(source_helm="1.2.9", target_helm="1.2.9")]
    ecrt.apply_native_helm_marker(rows)
    assert rows[0][8] == "1.2.9" and rows[0][10] == "1.2.9"


def test_apply_native_helm_marker_mutates_in_place_and_leaves_other_columns_untouched(ecrt: ModuleType):
    rows = [_row()]
    ecrt.apply_native_helm_marker(rows)
    assert rows[0] == ["Product", "", "", "Frank Gateway", "frankgateway", "", "", "104", "NATIVE", "105", "NATIVE"]


def test_extract_release_rows_fills_native_helm_for_orphan_key_component_with_no_helm_column(
    ecrt: ModuleType, tmp_path: Path
):
    """End-to-end: "Frank Gateway" resolves to the orphan values.yaml key
    "frankgateway" (no real Chart.yaml dependency backs it — same real
    case NATIVE_COMPONENTS/orphan_values_yaml_keys exist for), and the
    table it comes from has no Helm sub-column at all — its helm cells
    are filled "NATIVE" rather than left blank, since frankgateway
    genuinely has no separate Helm chart to report a version for."""
    write_chart_yaml_with_dependencies(tmp_path, [("openzaak", "")])
    write_values_yaml(tmp_path, ["frankgateway", "openzaak"])
    html = TECHNISCHE_TABLE_NO_HELM_HTML.replace(
        "<td>Elastic operator</td>\n<td>ZAC</td>", "<td>Frank Gateway</td>\n<td></td>"
    )
    rows = ecrt.extract_release_rows(html, chart_dir=tmp_path)
    assert rows == [
        ["Technische", "", "", "Frank Gateway", "frankgateway", "", "", "3.4.0", "NATIVE", "3.5.0", "NATIVE"]
    ]


def test_extract_release_rows_resolves_component_via_used_by_not_name(ecrt: ModuleType, tmp_path: Path):
    """TECHNISCHE_TABLE_HTML's row is named "Elastic operator" (shares no
    text with any real dependency) but has used_by "ZAC" — a much better
    resolution signal, since it's already the dependency's own alias.
    Resolution must use it instead of the row's own name."""
    write_chart_yaml_with_dependencies(tmp_path, [("zaakafhandelcomponent", "zac")])
    rows = ecrt.extract_release_rows(TECHNISCHE_TABLE_HTML, chart_dir=tmp_path)
    assert rows == [
        [
            "Technische",
            "",
            "ZAC",
            "Elastic operator",
            "zaakafhandelcomponent",
            "zac",
            "",
            "3.4.0",
            "3.4.0",
            "3.5.0",
            "3.5.0",
        ]
    ]


def test_extract_release_rows_resolves_exact_alias_match_despite_unrelated_substring_alias(
    ecrt: ModuleType, tmp_path: Path
):
    """A used_by value ("kiss") that exactly equals one dependency's own
    alias resolves outright, even with a second dependency ("eck-stack")
    present whose own alias ("kiss-eck") merely contains "kiss" as a
    substring — this must NOT register as an ambiguity."""
    write_chart_yaml_with_dependencies(tmp_path, [("kiss-chart", "kiss"), ("eck-stack", "kiss-eck")])
    html = TECHNISCHE_TABLE_HTML.replace("<td>ZAC</td>", "<td>kiss</td>")
    rows = ecrt.extract_release_rows(html, chart_dir=tmp_path)
    assert rows == [
        ["Technische", "", "kiss", "Elastic operator", "kiss-chart", "kiss", "", "3.4.0", "3.4.0", "3.5.0", "3.5.0"]
    ]


def test_extract_release_rows_resolves_component_as_multiple(ecrt: ModuleType, tmp_path: Path):
    """A used_by value ("shared") that's the literal same alias on two
    distinct Chart.yaml dependencies resolves the row to
    "MULTIPLE"/"MULTIPLE" rather than silently picking one."""
    write_chart_yaml_with_dependencies(tmp_path, [("foo-chart", "shared"), ("bar-chart", "shared")])
    html = TECHNISCHE_TABLE_HTML.replace("<td>ZAC</td>", "<td>shared</td>")
    rows = ecrt.extract_release_rows(html, chart_dir=tmp_path)
    assert rows == [
        ["Technische", "", "shared", "Elastic operator", "MULTIPLE", "MULTIPLE", "", "3.4.0", "3.4.0", "3.5.0", "3.5.0"]
    ]


def test_extract_release_rows_resolves_component_via_orphan_values_yaml_key(ecrt: ModuleType, tmp_path: Path):
    """ "ZAC" (PRODUCT_TABLE_HTML's own row) doesn't match any real
    dependency here, but exactly equals the orphan values.yaml key
    "zac" — resolved end-to-end as a last resort."""
    write_chart_yaml_with_dependencies(tmp_path, [("openzaak", "")])
    write_values_yaml(tmp_path, ["zac", "openzaak"])
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    assert rows[0] == ["Product", "Info(NL)", "", "ZAC", "zac", "", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"]


def test_extract_release_rows_resolves_global_image_key_as_multiple(ecrt: ModuleType, tmp_path: Path):
    """ "Open Zaak" resolves normally via its real dependency; "ZAC"
    matches nothing real but does relate to global image key "zac" —
    resolved end-to-end as MULTIPLE, since a global.images key is never
    treated as a single component's own."""
    write_chart_yaml_with_dependencies(tmp_path, [("openzaak", "")])
    write_values_yaml_with_global_images(tmp_path, ["zac"])
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    assert rows == [
        ["Product", "Info(NL)", "", "ZAC", "MULTIPLE", "MULTIPLE", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Product", "Maykin", "", "Open Zaak", "openzaak", "", "", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]


def test_extract_release_rows_warns_when_multiple_row_has_no_resolved_image(
    ecrt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Regression test: a MULTIPLE row (see component_and_alias) export
    couldn't resolve an image_basename for used to go silent all the way
    through — the CSV just got a blank column, and verify-release-table-
    with-podiumd can't catch it either (it only ever compares columns
    this script already resolved, never re-derives). Now warns instead of
    silently writing an untracked row."""
    write_chart_yaml_with_dependencies(tmp_path, [("openzaak", "")])
    write_values_yaml_with_global_images(tmp_path, ["zac"])  # no "repository" key -> unresolvable
    ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    out = capsys.readouterr().out
    assert 'WARNING: "ZAC" resolved to MULTIPLE but no image_basename could be resolved' in out


def test_extract_release_rows_no_warning_when_multiple_row_resolves_an_image(
    ecrt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """The new warning must not fire for a MULTIPLE row that DOES resolve
    an image_basename — only for one that can't."""
    write_chart_yaml_with_dependencies(tmp_path, [("openzaak", "")])
    (tmp_path / "values.yaml").write_text(
        "global:\n  images:\n    zac:\n      repository: org/zac-base\n", encoding="utf-8"
    )
    ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    out = capsys.readouterr().out
    assert "WARNING" not in out


def test_extract_release_rows_warns_on_duplicate_component_and_image(
    ecrt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Regression test: two distinct rows resolving to the exact same
    (component, image_basename) pair — e.g. the same global.images key
    accidentally named on two rows, since resolve_image_basenames'
    MULTIPLE-row resolution (unlike its real-dependency one) has no
    claim-and-delete exclusivity — must be flagged as a duplicate."""
    write_chart_yaml_with_dependencies(tmp_path, [("openzaak", "")])
    (tmp_path / "values.yaml").write_text(
        "global:\n  images:\n    zac:\n      repository: org/zac-base\n", encoding="utf-8"
    )
    duplicated_zac_row = (
        "<tr><td>ZAC</td><td>Info(NL)</td><td>5.0.0</td><td>1.0.290</td><td>5.1.0</td><td>1.0.297</td></tr>"
    )
    html = PRODUCT_TABLE_HTML.replace(
        "</tr>\n<tr>\n<td>Open Zaak</td>", f"</tr>\n{duplicated_zac_row}\n<tr>\n<td>Open Zaak</td>"
    )
    rows = ecrt.extract_release_rows(html, chart_dir=tmp_path)
    assert sum(1 for row in rows if row[3] == "ZAC") == 2
    out = capsys.readouterr().out
    assert ('WARNING: 2 rows all resolve to the same component "MULTIPLE" + image "zac-base": ZAC, ZAC') in out


def test_extract_release_rows_used_by_blank_when_table_has_none(ecrt: ModuleType):
    """A Product table has no "Used by" column at all (only Ontwikkelpartij)."""
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML)
    assert all(row[2] == "" for row in rows)  # used_by is the 3rd column: section, vendor, used_by, ...


def test_extract_release_rows_combines_multiple_sections(ecrt: ModuleType):
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML + TECHNISCHE_TABLE_HTML)
    assert [r[0] for r in rows] == ["Product", "Product", "Technische"]


def test_extract_release_rows_custom_headings_overrides_default(ecrt: ModuleType):
    rows = ecrt.extract_release_rows(
        PRODUCT_TABLE_HTML + TECHNISCHE_TABLE_HTML, headings=["Technische component versies"]
    )
    assert len(rows) == 1
    assert rows[0][0] == "Technische"


def test_extract_release_rows_no_tables_raises(ecrt: ModuleType):
    with pytest.raises(SystemExit, match="no <table> found"):
        ecrt.extract_release_rows("<p>no tables here</p>")


def test_extract_release_rows_no_table_under_target_heading_raises(ecrt: ModuleType):
    with pytest.raises(SystemExit, match="no table found directly under any of"):
        ecrt.extract_release_rows(UNRELATED_TABLE_HTML)


def test_extract_release_rows_every_matching_table_incomplete_raises(ecrt: ModuleType):
    with pytest.raises(SystemExit, match="every matching-heading table was missing a required column"):
        ecrt.extract_release_rows(INCOMPLETE_UNDER_TARGET_HEADING_HTML)


def test_extract_release_rows_skips_fully_blank_rows(ecrt: ModuleType):
    html = PRODUCT_TABLE_HTML.replace(
        "<tr>\n<td>Open Zaak</td>",
        "<tr><td></td><td></td><td></td><td></td><td></td><td></td></tr>\n<tr>\n<td>Open Zaak</td>",
    )
    rows = ecrt.extract_release_rows(html)
    assert len(rows) == 2  # the all-blank row was skipped, not counted


def test_extract_release_rows_warns_when_target_does_not_match_chart_yaml(
    ecrt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """PRODUCT_TABLE_HTML's target heading is "Versie 4.9" — a
    Chart.yaml at a different minor version must trigger the warning."""
    write_chart_yaml(tmp_path, "5.0.0")
    ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "'Versie 4.9'" in err


def test_extract_release_rows_silent_when_target_matches_chart_yaml(
    ecrt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    write_chart_yaml(tmp_path, "4.9.0")
    ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    assert capsys.readouterr().err == ""


def test_extract_release_rows_warns_when_chart_yaml_version_unparseable(
    ecrt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Regression test: Chart.yaml's own "version:" not being a valid
    MAJOR.MINOR(.PATCH) used to make check_target_matches_chart_version
    quietly return, indistinguishable from "checked, and it matched" —
    now warns that it couldn't verify at all."""
    write_chart_yaml(tmp_path, "not-a-version")
    ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    out = capsys.readouterr().out
    assert (
        "WARNING: could not verify Confluence target version against Chart.yaml — its own "
        '"version: not-a-version" isn\'t a valid MAJOR.MINOR(.PATCH)'
    ) in out


def test_extract_release_rows_warns_when_no_target_label_found(
    ecrt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Regression test: a table whose header never yielded a resolvable
    "target" Versie group (find_versie_groups) used to leave
    target_labels empty, which quietly made check_target_matches_chart_
    version behave exactly like "verified, and it matched" — now warns
    that it couldn't verify at all."""
    write_chart_yaml(tmp_path, "4.9.0")
    html = "<h2>Product component versies</h2><table><tbody><tr><td>x</td></tr></tbody></table>"
    with pytest.raises(SystemExit):
        ecrt.extract_release_rows(html, chart_dir=tmp_path)
    out = capsys.readouterr().out
    assert (
        "WARNING: could not verify Confluence target version against Chart.yaml — no "
        'table\'s "Versie ..." heading yielded a resolvable target-version group'
    ) in out
