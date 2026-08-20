"""parse_upgrade_doc_rows — markdown "Component versions" table parsing."""

TABLE = """\
# Upgrade guide

## Component versions (4.9.0 vs 4.8.5)

| Component | App version | Helm chart | Notes |
| --- | --- | --- | --- |
| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.4.3 | 1.0.297 (unchanged) | ACR mirror only |
| ZGW Office Add-in (frontend + backend) | v0.9.313 → 0.11.0 | 0.0.89 → 0.0.92 | ACR mirror only |
"""


def test_parses_all_rows(vp, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text(TABLE)
    rows = vp.parse_upgrade_doc_rows(doc)
    assert len(rows) == 2
    assert rows[0]["name"] == "ZAC (Zaakafhandelcomponent)"
    assert rows[0]["app_source"] == "5.0.2"
    assert rows[0]["app"] == "5.4.3"
    assert rows[0]["chart_source"] == "1.0.297"
    assert rows[0]["chart"] == "1.0.297"
    assert rows[1]["name"] == "ZGW Office Add-in (frontend + backend)"
    assert rows[1]["app_source"] == "v0.9.313"
    assert rows[1]["app"] == "0.11.0"
    assert rows[1]["chart_source"] == "0.0.89"
    assert rows[1]["chart"] == "0.0.92"


def test_header_and_separator_rows_are_skipped(vp, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text(TABLE)
    rows = vp.parse_upgrade_doc_rows(doc)
    names = [r["name"] for r in rows]
    assert "Component" not in names
    assert not any(set(n) <= set("-: ") for n in names)


def test_no_table_returns_empty_list(vp, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Upgrade guide\n\nJust prose, no table.\n")
    assert vp.parse_upgrade_doc_rows(doc) == []


def test_lines_that_are_not_full_table_rows_are_skipped(vp, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Title\n\n| only two cells |\n| ZAC | 5.0.2 -> 5.4.3 | 1.0.297 |\n")
    rows = vp.parse_upgrade_doc_rows(doc)
    assert len(rows) == 1
    assert rows[0]["name"] == "ZAC"
