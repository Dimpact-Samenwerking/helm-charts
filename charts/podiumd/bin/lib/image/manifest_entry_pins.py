"""The version/digest an images-<target>.yaml entry must state, shared by the checker and the fixer."""

import re

from collections.abc import Mapping
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.pull_and_subchart_resolution import resolved_digest_pin
from lib.chart.values_tree_primitives import replace_scalar_value
from lib.images_manifest import ManifestEntry
from lib.images_manifest import entry_block_end
from lib.images_manifest import parse_manifest_lines
from lib.settings import DigestPinningException
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_image_path
from lib.upgradedoc.chart_image_index import ChartImageIndex
from lib.yaml_types import YamlMapping


def entry_pin(
    entry: ManifestEntry,
    values: YamlMapping,
    paths: Mapping[tuple[str, ...], str | None],
    repo_map: dict[str, tuple[str, ...]],
    sibling_fields: dict[tuple[str, ...], DigestPinningException],
) -> tuple[tuple[str, ...] | None, str | None]:
    """(path, tag) pinned for an images-manifest entry, digest from a sibling field if needed.

    tag None when the path has no tag; (None, None) when no path matches.
    """
    path = resolve_entry_image_path(entry["name"], paths.keys(), repo_map)
    if not path:
        return None, None
    tag = paths[path]
    return path, tag and (resolved_digest_pin(values, path, tag, sibling_fields) or tag)


def _rewrite_entry_pin(lines: list[str], start: int, tag: str) -> None:
    """Sets the version:/digest: lines of the entry starting at
    lines[start] to `tag` ("<version>@<digest>")."""
    version, digest = tag.split("@", 1)
    for i in range(start, entry_block_end(lines, start)):
        m = re.match(r"^\s*(version|digest):", lines[i])
        if m:
            lines[i] = replace_scalar_value(lines[i], version if m.group(1) == "version" else digest)


def sync_entry_pins(
    text: str,
    chart_dir: Path,
    deps: list[ChartDependency],
    values: YamlMapping,
    sibling_fields: dict[tuple[str, ...], DigestPinningException],
) -> tuple[str, list[str]]:
    """Rewrite version:/digest: of entries whose pin differs; digest-less pins are left alone.

    Returns (new_text, [entry name, ...]).
    """
    parsed = parse_manifest_lines(text)
    if parsed is None:
        return text, []
    lines = parsed.lines
    index = ChartImageIndex(chart_dir, deps, values)
    synced: list[str] = []
    for start, entry in zip(parsed.entry_line_indices, parsed.entries, strict=True):
        _path, tag = entry_pin(entry, values, index.paths, index.repo_map, sibling_fields)
        if tag is None or "@" not in tag or tag == f"{entry.get('version')}@{entry.get('digest')}":
            continue
        _rewrite_entry_pin(lines, start, tag)
        synced.append(entry["name"])
    return "".join(lines), synced
