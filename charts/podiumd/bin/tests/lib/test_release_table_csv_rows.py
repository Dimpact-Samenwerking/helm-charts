"""lib.release_table.csv_rows — read_release_table."""

from pathlib import Path

import pytest

from lib.release_table.csv_rows import CSV_HEADER
from lib.release_table.csv_rows import read_release_table

ROW = "Product,Info(NL),,ZAC,zaakafhandelcomponent,zac,zaakafhandelcomponent,5.0.0,1.0.290,5.1.0,1.0.297\n"


def test_read_release_table_reads_rows(tmp_path: Path):
    path = tmp_path / "release-table.csv"
    path.write_text(",".join(CSV_HEADER) + "\n" + ROW, encoding="utf-8")
    rows = read_release_table(path)
    assert len(rows) == 1
    assert rows[0]["name"] == "ZAC"
    assert rows[0]["used_by"] == ""
    assert rows[0]["target_version_helm"] == "1.0.297"


def test_read_release_table_rejects_other_header(tmp_path: Path):
    path = tmp_path / "release-table.csv"
    path.write_text("name,component\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="header doesn't match"):
        read_release_table(path)


def test_read_release_table_rejects_short_row(tmp_path: Path):
    path = tmp_path / "release-table.csv"
    path.write_text(",".join(CSV_HEADER) + "\nProduct,Info(NL)\n", encoding="utf-8")
    with pytest.raises(SystemExit, match=r"line 2 has 2 column\(s\), expected 11"):
        read_release_table(path)
