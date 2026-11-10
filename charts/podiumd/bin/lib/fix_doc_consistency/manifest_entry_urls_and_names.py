"""fix-doc-consistency's images-manifest url/name repair."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lib.chart.chart_yaml import ChartDependency
from lib.chart.repo_and_path_resolution import full_repository_for_path
from lib.chart.repo_and_path_resolution import repository_group_key
from lib.chart.values_tree_primitives import ValuesPath
from lib.chart.values_tree_primitives import replace_scalar_value
from lib.images_manifest import ENTRY_NAME_RE
from lib.images_manifest import ENTRY_URL_RE
from lib.images_manifest import ManifestEntry
from lib.images_manifest import entry_field_line
from lib.images_manifest import entry_line_indices
from lib.images_manifest import parse_manifest_lines
from lib.upgradedoc.app_version_and_image_paths import chart_image_paths
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_image_path
from lib.yaml_types import YamlMapping


@dataclass
class UrlFixContext:
    """Resolution inputs for fix_images_manifest_entry_urls."""

    chart_dir: Path
    deps: list[ChartDependency]
    target_values: YamlMapping
    repo_map: dict[str, ValuesPath] | None = None


# A rewritten entry "url:" as (name, old_url, new_url), and what happened to one entry's "url:".
type UrlUpdate = tuple[str, str, str]
type UrlStatus = (
    tuple[Literal["unresolved"], str] | tuple[Literal["changed"], UrlUpdate] | tuple[Literal["unchanged"], None]
)


def _entry_url_status(
    entry: ManifestEntry, line_idx: int, lines: list[str], current_paths: dict[ValuesPath, str], context: UrlFixContext
) -> UrlStatus:
    """("unresolved", name), ("changed", (name, old_url, new_url)) or
    ("unchanged", None) for one entry's "url:". Mutates `lines` when the
    url changes."""
    name = entry["name"]
    path = resolve_entry_image_path(entry["name"], current_paths.keys(), context.repo_map)
    full_repo = (
        full_repository_for_path(context.chart_dir, context.deps, context.target_values, path)
        if path is not None
        else None
    )
    if full_repo is None:
        return "unresolved", name

    url_idx = entry_field_line(lines, line_idx, "url")
    if url_idx is None:
        return "unresolved", name

    url_m = ENTRY_URL_RE.match(lines[url_idx])
    if url_m is None:
        return "unresolved", name  # text after the url: no single value to compare
    current_url = url_m.group(1)
    if current_url == full_repo:
        return "unchanged", None
    lines[url_idx] = replace_scalar_value(lines[url_idx], full_repo)
    return "changed", (name, current_url, full_repo)


def fix_images_manifest_entry_urls(
    text: str,
    chart_dir: Path,
    deps: list[ChartDependency],
    target_values: YamlMapping,
    repo_map: dict[str, ValuesPath] | None = None,
) -> tuple[str, list[UrlUpdate], list[str]]:
    """Rewrite each entry's "url:" to the fully host-qualified repository of
    its values path (full_repository_for_path), as new entries get. Always
    offline: dependencies are vendored.

    Returns (new_text, changed_names, unresolved_names): changed_names is
    [(name, old_url, new_url), ...]; unresolved_names are entries whose
    path/repository can't be resolved or that lack a "url:" (reported, not
    touched)."""
    parsed = parse_manifest_lines(text)
    if parsed is None:
        return text, [], []
    lines = parsed.lines
    current_paths = chart_image_paths(target_values, deps)

    changed_names: list[UrlUpdate] = []
    unresolved_names: list[str] = []
    for entry, line_idx in zip(parsed.entries, parsed.entry_line_indices, strict=True):
        status = _entry_url_status(
            entry, line_idx, lines, current_paths, UrlFixContext(chart_dir, deps, target_values, repo_map)
        )
        if status[0] == "unresolved":
            unresolved_names.append(status[1])
        elif status[0] == "changed":
            changed_names.append(status[1])

    return "".join(lines), changed_names, unresolved_names


# A renamed entry as (old_name, new_name).
type EntryRename = tuple[str, str]


def fix_images_manifest_entry_names(text: str, repo_map: dict[str, ValuesPath]) -> tuple[str, list[EntryRename]]:
    """Rewrite each entry's "name:" to its url's group key (url minus
    registry host, e.g. "library/python"): the ACR mirror name the check
    expects. Skips entries without a url, whose new name is no known
    repository, or whose new name another entry has. Run after
    fix_images_manifest_entry_urls. Returns (new_text,
    [(old_name, new_name), ...])."""
    lines = text.splitlines(keepends=True)
    starts = entry_line_indices(lines)
    names = {_unquoted(name_match.group(1)) for index in starts if (name_match := ENTRY_NAME_RE.match(lines[index]))}
    renamed: list[EntryRename] = []
    for line_idx in starts:
        name_m = ENTRY_NAME_RE.match(lines[line_idx])
        url_idx = entry_field_line(lines, line_idx, "url")
        url_m = ENTRY_URL_RE.match(lines[url_idx]) if url_idx is not None else None
        if name_m is None or url_m is None:
            continue
        old_name, new_name = _unquoted(name_m.group(1)), repository_group_key(_unquoted(url_m.group(1)))
        if old_name == new_name or new_name not in repo_map or new_name in names:
            continue
        lines[line_idx] = replace_scalar_value(lines[line_idx], new_name)
        names.add(new_name)
        renamed.append((old_name, new_name))
    return "".join(lines), renamed


def _unquoted(scalar: str) -> str:
    """`scalar` without the YAML quotes around it."""
    return scalar.strip("\"'")
