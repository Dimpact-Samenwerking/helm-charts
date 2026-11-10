"""etc/release-table.csv (written by export-confluence-release-table): its
column set, the ReleaseTableRow type and the checked reader."""

import csv
import sys

from pathlib import Path
from typing import TypedDict

CSV_HEADER = [
    "section",
    "vendor",
    "used_by",
    "name",
    "component",
    "alias",
    "image_basename",
    "source_version_app",
    "source_version_helm",
    "target_version_app",
    "target_version_helm",
]


class ReleaseTableRow(TypedDict):
    """One release-table.csv row; every column is text ("" when empty)."""

    section: str
    vendor: str
    used_by: str
    name: str
    component: str
    alias: str
    image_basename: str
    source_version_app: str
    source_version_helm: str
    target_version_app: str
    target_version_helm: str


def _row(values: list[str], where: str) -> ReleaseTableRow:
    if len(values) != len(CSV_HEADER):
        msg = f"error: {where} has {len(values)} column(s), expected {len(CSV_HEADER)}"
        sys.exit(msg)
    cells = dict(zip(CSV_HEADER, values, strict=True))
    return {
        "section": cells["section"],
        "vendor": cells["vendor"],
        "used_by": cells["used_by"],
        "name": cells["name"],
        "component": cells["component"],
        "alias": cells["alias"],
        "image_basename": cells["image_basename"],
        "source_version_app": cells["source_version_app"],
        "source_version_helm": cells["source_version_helm"],
        "target_version_app": cells["target_version_app"],
        "target_version_helm": cells["target_version_helm"],
    }


# (line number, values) of one release-table.csv data row.
type CsvRecord = tuple[int, list[str]]


def release_table_records(path: Path) -> list[CsvRecord]:
    """(line number, values) of each data row of the release-table.csv at `path`; exits on a bad header."""
    with path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.reader(csv_file)
        header = next(reader, None)
        if header != CSV_HEADER:
            msg = f"error: {path}'s header doesn't match the release-table.csv columns ({', '.join(CSV_HEADER)})"
            sys.exit(msg)
        return [(reader.line_num, values) for values in reader]


def read_release_table(path: Path) -> list[ReleaseTableRow]:
    """The rows of the release-table.csv at `path`; exits on a bad header or column count."""
    return [_row(values, f"{path} line {line_num}") for line_num, values in release_table_records(path)]
