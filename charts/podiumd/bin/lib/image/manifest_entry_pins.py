"""The version/digest an images-<target>.yaml entry must state: the tag
values.yaml pins at the entry's image path. check_docs_consistency
compares against it and fix-doc-consistency writes it, so the two
cannot disagree."""

import re

from pathlib import Path
from typing import Any

import yaml

from lib.chart.pull_and_subchart_resolution import global_image_paths
from lib.chart.pull_and_subchart_resolution import resolved_digest_pin
from lib.chart.repo_and_path_resolution import paths_by_repository
from lib.chart.repo_and_path_resolution import repo_group_representative
from lib.chart.values_tree_primitives import replace_scalar_value
from lib.upgradedoc.app_version_and_image_paths import find_image_tag_paths
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_image_path

ENTRY_START_RE = re.compile(r"^-\s*name:")


def current_image_paths(values: dict[str, Any]) -> dict[tuple[str, ...], str | None]:
    """{values-tree path: tag, or None when it has none} for every image
    in `values`, including the global.images anchors."""
    return {**dict(find_image_tag_paths(values)), **dict(global_image_paths(values))}


def image_repo_map(
    chart_dir: Path, deps: list[dict[str, Any]], values: dict[str, Any], paths: dict[tuple[str, ...], str | None]
) -> dict[str, tuple[str, ...]]:
    """{repository: representative values-tree path} for `paths`, used
    to match an entry to its image path by repository."""
    groups = paths_by_repository(chart_dir, deps, values, paths.keys())
    return {repo: repo_group_representative(group, deps) for repo, group in groups.items()}


def entry_pin(
    entry: dict[str, Any],
    values: dict[str, Any],
    paths: dict[tuple[str, ...], str | None],
    repo_map: dict[str, tuple[str, ...]],
    sibling_fields: dict[tuple[str, ...], dict[str, str]],
) -> tuple[tuple[str, ...] | None, str | None]:
    """(path, tag) for an images-manifest entry: its values-tree path
    and the tag pinned there, with the digest from a sibling field when
    the tag has none (resolved_digest_pin). Tag None when the path has
    no tag; (None, None) when the entry matches no image path."""
    path = resolve_entry_image_path(entry, paths.keys(), repo_map)
    if not path:
        return None, None
    tag = paths[path]
    return path, tag and (resolved_digest_pin(values, path, tag, sibling_fields) or tag)


def _rewrite_entry_pin(lines: list[str], start: int, tag: str) -> None:
    """Sets the version:/digest: lines of the entry starting at
    lines[start] to `tag` ("<version>@<digest>")."""
    version, digest = tag.split("@", 1)
    end = next(
        (i for i in range(start + 1, len(lines)) if ENTRY_START_RE.match(lines[i]) or not lines[i].strip()), len(lines)
    )
    for i in range(start, end):
        m = re.match(r"^\s*(version|digest):", lines[i])
        if m:
            lines[i] = replace_scalar_value(lines[i], version if m.group(1) == "version" else digest)


def _parsed_entries(text: str) -> tuple[list[str], list[tuple[int, dict[str, Any]]]]:
    """(lines, [(start line index, entry), ...]) of an images manifest,
    or no entries when it is not a list whose "- name:" lines line up
    with its entries."""
    lines = text.splitlines(keepends=True)
    try:
        entries = yaml.safe_load(text)
    except yaml.YAMLError:
        return lines, []
    starts = [i for i, line in enumerate(lines) if ENTRY_START_RE.match(line)]
    if not isinstance(entries, list) or len(starts) != len(entries):
        return lines, []
    return lines, list(zip(starts, entries, strict=True))


def sync_entry_pins(
    text: str,
    chart_dir: Path,
    deps: list[dict[str, Any]],
    values: dict[str, Any],
    sibling_fields: dict[tuple[str, ...], dict[str, str]],
) -> tuple[str, list[str]]:
    """Rewrites the version:/digest: of every entry in `text` whose pin
    differs from entry_pin. Entries whose pin has no digest are left
    alone. Returns (new_text, [entry name, ...])."""
    lines, entries = _parsed_entries(text)
    paths = current_image_paths(values)
    repo_map = image_repo_map(chart_dir, deps, values, paths)
    synced: list[str] = []
    for start, entry in entries:
        _path, tag = entry_pin(entry, values, paths, repo_map, sibling_fields)
        if tag is None or "@" not in tag or tag == f"{entry.get('version')}@{entry.get('digest')}":
            continue
        _rewrite_entry_pin(lines, start, tag)
        synced.append(entry["name"])
    return "".join(lines), synced
