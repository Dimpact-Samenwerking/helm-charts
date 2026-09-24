"""etc/release-table.csv (written by export-confluence-release-table): its
column set, the ReleaseTableRow type and the checked reader."""

import csv

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
        raise SystemExit(msg)
    (
        section,
        vendor,
        used_by,
        name,
        component,
        alias,
        image_basename,
        source_version_app,
        source_version_helm,
        target_version_app,
        target_version_helm,
    ) = values
    return {
        "section": section,
        "vendor": vendor,
        "used_by": used_by,
        "name": name,
        "component": component,
        "alias": alias,
        "image_basename": image_basename,
        "source_version_app": source_version_app,
        "source_version_helm": source_version_helm,
        "target_version_app": target_version_app,
        "target_version_helm": target_version_helm,
    }


def read_release_table(path: Path) -> list[ReleaseTableRow]:
    """The rows of the release-table.csv at `path`. Exits with an error
    naming the file if its header is not CSV_HEADER or a row has the wrong
    number of columns."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header != CSV_HEADER:
            msg = f"error: {path}'s header doesn't match the release-table.csv columns ({', '.join(CSV_HEADER)})"
            raise SystemExit(msg)
        return [_row(values, f"{path} line {reader.line_num}") for values in reader]
