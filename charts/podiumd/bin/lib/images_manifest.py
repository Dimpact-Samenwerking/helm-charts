"""docs/images/images-*.yaml: the ManifestEntry type and checked parsing.
A finished manifest has all four fields on every entry (every committed
one does; images_manifest_problem enforces it). A manifest being written
or repaired may still lack url/version/digest on an entry, which the
fixers handle, so only "name" is required by the type."""

import re

from dataclasses import dataclass
from typing import NotRequired
from typing import TypedDict
from typing import TypeGuard

import yaml

from lib.yaml_types import YamlShapeError
from lib.yaml_types import YamlValue
from lib.yaml_types import parse_yaml

MANIFEST_ENTRY_KEYS = ("name", "url", "version", "digest")
# The line that starts an entry, and its parts; the fixers edit the text line by line.
ENTRY_START_RE = re.compile(r"^-\s*name:")
ENTRY_NAME_RE = re.compile(r"^-\s*name:\s*(\S+)\s*$")
ENTRY_URL_RE = re.compile(r"^\s*url:\s*(\S+)\s*$")


class ManifestEntry(TypedDict):
    """One images-manifest entry."""

    name: str
    url: NotRequired[str]
    version: NotRequired[str]
    digest: NotRequired[str]


def _entries_problem(entries: YamlValue, *, complete: bool) -> str | None:
    """What is wrong with `entries` as a list of ManifestEntry (with all four
    keys present when `complete`), or None. Entries are counted from 1, as
    a reader of the file counts them."""
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        return "does not contain a YAML list of mappings"
    for i, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        required = MANIFEST_ENTRY_KEYS if complete else ("name",)
        missing = [k for k in required if k not in entry]
        if missing:
            return f"entry #{i} is missing key(s): {', '.join(missing)}"
        wrong = [k for k in MANIFEST_ENTRY_KEYS if k in entry and not isinstance(entry[k], str)]
        if wrong:
            return f"entry #{i}: {', '.join(wrong)} must be a quoted string"
    return None


def images_manifest_problem(entries: YamlValue) -> str | None:
    """None if `entries` is a finished images manifest (every entry has all
    four keys), else what is wrong with it."""
    return _entries_problem(entries, complete=True)


def is_images_manifest(entries: YamlValue) -> TypeGuard[list[ManifestEntry]]:
    """Whether `entries` is a list of ManifestEntry (a draft is enough:
    only "name" is required)."""
    return _entries_problem(entries, complete=False) is None


def parse_images_manifest(text: str, source: str) -> list[ManifestEntry]:
    """The entries of the images manifest in `text` ([] for an empty
    document). Raises YamlShapeError naming `source` if they do not match
    ManifestEntry; yaml.YAMLError passes through."""
    entries = parse_yaml(text, source)
    if entries is None:
        return []
    if not is_images_manifest(entries):
        raise YamlShapeError(source, _entries_problem(entries, complete=False) or "not an images manifest")
    return entries


def try_parse_images_manifest(text: str) -> list[ManifestEntry] | None:
    """parse_images_manifest, or None when `text` is not valid YAML or not a
    valid images manifest — for fixers, which leave such a document alone
    (the consistency check reports it)."""
    try:
        return parse_images_manifest(text, "images manifest")
    except (yaml.YAMLError, YamlShapeError):
        return None


@dataclass
class ParsedManifest:
    """Parsed manifest entries, their "- name:" line indices and the raw lines, kept in lockstep."""

    entries: list[ManifestEntry]
    entry_line_indices: list[int]
    lines: list[str]


def entry_line_indices(lines: list[str]) -> list[int]:
    """Index of each entry's "- name:" line."""
    return [i for i, line in enumerate(lines) if ENTRY_START_RE.match(line)]


def entry_block_end(lines: list[str], start: int) -> int:
    """End (exclusive) of the entry starting at lines[start]: the next entry or blank line."""
    return next(
        (i for i in range(start + 1, len(lines)) if ENTRY_START_RE.match(lines[i]) or not lines[i].strip()), len(lines)
    )


def entry_field_line(lines: list[str], start: int, field: str) -> int | None:
    """Index of the "<field>:" line with a value in the entry starting at lines[start], or None."""
    field_re = re.compile(rf"^\s*{re.escape(field)}:\s*\S")
    return next((i for i in range(start, entry_block_end(lines, start)) if field_re.match(lines[i])), None)


def parse_manifest_lines(text: str) -> ParsedManifest | None:
    """`text` parsed with each entry's line index; None unless it is a valid manifest whose every
    entry has its own "- name:" line, so a fixer never edits the wrong entry (the check reports it)."""
    lines = text.splitlines(keepends=True)
    entries = try_parse_images_manifest(text)
    starts = entry_line_indices(lines)
    if entries is None or len(starts) != len(entries):
        return None
    return ParsedManifest(entries, starts, lines)
