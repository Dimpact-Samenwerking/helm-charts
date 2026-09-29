"""apply_native_helm_marker, with fetch_page_html mocked."""

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
    """values.yaml with each of `keys` as an empty top-level block."""
    (chart_dir / "values.yaml").write_text(
        "".join(f"{key}: {{}}\n" for key in keys),
        encoding="utf-8",
    )


def write_values_yaml_with_global_images(chart_dir, image_keys):
    """values.yaml with a global.images map of `image_keys` (shared-image anchors)."""
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

# Technische tables have "Used by" (optional) instead of a vendor column.
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

# Like TECHNISCHE_TABLE_HTML but without the Helm sub-column, as on the real
# page since 2026-09.
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

# No heading above it: ignored outright, not reported as skipped.
UNRELATED_TABLE_HTML = "<table><tr><th>Legend</th></tr><tr><td>n/a</td></tr></table>"

# Under a target heading but missing App/Helm columns: reported as skipped.
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
    """A used_by sidecar row is not a component, so NATIVE never applies."""
    rows = [_row(used_by="zac")]
    ecrt.apply_native_helm_marker(rows)
    assert rows[0][8] == "" and rows[0][10] == ""


def test_apply_native_helm_marker_skips_row_with_a_real_helm_value(ecrt: ModuleType):
    """Only both helm cells blank means "no Helm chart"; any helm value
    leaves the row untouched."""
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
    """End-to-end: "Frank Gateway" resolves to orphan key "frankgateway" from
    a table without Helm column, so its helm cells become "NATIVE"."""
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
    """used_by ("ZAC", the dependency's alias) is used for resolution when
    the row name ("Elastic operator") matches nothing."""
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
    """An exact used_by alias match is not ambiguous because another alias
    merely contains it."""
    write_chart_yaml_with_dependencies(tmp_path, [("kiss-chart", "kiss"), ("eck-stack", "kiss-eck")])
    html = TECHNISCHE_TABLE_HTML.replace("<td>ZAC</td>", "<td>kiss</td>")
    rows = ecrt.extract_release_rows(html, chart_dir=tmp_path)
    assert rows == [
        ["Technische", "", "kiss", "Elastic operator", "kiss-chart", "kiss", "", "3.4.0", "3.4.0", "3.5.0", "3.5.0"]
    ]


def test_extract_release_rows_resolves_component_as_multiple(ecrt: ModuleType, tmp_path: Path):
    """A used_by alias shared by two dependencies resolves to MULTIPLE."""
    write_chart_yaml_with_dependencies(tmp_path, [("foo-chart", "shared"), ("bar-chart", "shared")])
    html = TECHNISCHE_TABLE_HTML.replace("<td>ZAC</td>", "<td>shared</td>")
    rows = ecrt.extract_release_rows(html, chart_dir=tmp_path)
    assert rows == [
        ["Technische", "", "shared", "Elastic operator", "MULTIPLE", "MULTIPLE", "", "3.4.0", "3.4.0", "3.5.0", "3.5.0"]
    ]


def test_extract_release_rows_resolves_component_via_orphan_values_yaml_key(ecrt: ModuleType, tmp_path: Path):
    """End-to-end last resort: exact orphan values.yaml key match."""
    write_chart_yaml_with_dependencies(tmp_path, [("openzaak", "")])
    write_values_yaml(tmp_path, ["zac", "openzaak"])
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    assert rows[0] == ["Product", "Info(NL)", "", "ZAC", "zac", "", "", "5.0.0", "1.0.290", "5.1.0", "1.0.297"]


def test_extract_release_rows_resolves_global_image_key_as_multiple(ecrt: ModuleType, tmp_path: Path):
    """A global.images key relation resolves as MULTIPLE, never as a single
    component."""
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
    """A MULTIPLE row without a resolvable image_basename warns: nothing
    downstream (verify-release-table-with-podiumd) re-derives it."""
    write_chart_yaml_with_dependencies(tmp_path, [("openzaak", "")])
    write_values_yaml_with_global_images(tmp_path, ["zac"])  # no "repository" key -> unresolvable
    ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    out = capsys.readouterr().out
    assert 'WARNING: "ZAC" resolved to MULTIPLE but no image_basename could be resolved' in out


def test_extract_release_rows_no_warning_when_multiple_row_resolves_an_image(
    ecrt: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """No warning for a MULTIPLE row that does resolve an image_basename."""
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
    """Two rows resolving to the same (component, image_basename) are flagged:
    MULTIPLE-row resolution has no claim-and-delete exclusivity."""
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
    """A Chart.yaml at a different minor than the target heading warns."""
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
    """An invalid Chart.yaml version warns that it couldn't verify, rather
    than passing silently."""
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
    """No resolvable target Versie group warns that it couldn't verify,
    rather than passing silently."""
    write_chart_yaml(tmp_path, "4.9.0")
    html = "<h2>Product component versies</h2><table><tbody><tr><td>x</td></tr></tbody></table>"
    with pytest.raises(SystemExit):
        ecrt.extract_release_rows(html, chart_dir=tmp_path)
    out = capsys.readouterr().out
    assert (
        "WARNING: could not verify Confluence target version against Chart.yaml — no "
        'table\'s "Versie ..." heading yielded a resolvable target-version group'
    ) in out
