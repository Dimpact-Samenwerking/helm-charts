"""Preceding-comment lookup, images-manifest "# Changes:" block parsing
and path_display_name."""

import re

from collections.abc import Callable
from collections.abc import Mapping

from lib.chart.chart_yaml import ChartDependency
from lib.chart.registered_paths import is_primary_image_path
from lib.chart.values_tree_primitives import values_key_of
from lib.images_manifest import ManifestEntry
from lib.upgradedoc.string_and_parsing_basics import VersionRow
from lib.upgradedoc.string_and_parsing_basics import extract_source_version
from lib.upgradedoc.string_and_parsing_basics import extract_target_version

BARE_CHART_CLAUSE_RE = re.compile(
    r"\bchart\s+`?[A-Za-z0-9][\w.\-]*`?\s*(?:→|->)\s*`?[A-Za-z0-9][\w.\-]*`?", re.IGNORECASE
)


VERSION_SPEC_RE = re.compile(
    r"[A-Za-z0-9][\w.\-]*\s*(?:→|->)\s*[A-Za-z0-9][\w.\-]*"
    r"|[A-Za-z0-9][\w.\-]*\s*\((?:new|unchanged|digest changed)\)"
)


# "<version> (new)", "(unchanged)" or "(digest changed)": an item without a version pair.
_SINGLE_VERSION_SPEC_RE = re.compile(r"(?<!\S)(?P<version>v?\d[\w.\-]*)\s*\((?P<kind>new|unchanged|digest changed)\)")


def find_preceding_comment(lines: list[str], entry_line_index: int) -> str:
    """The contiguous comment line(s) directly above a "- name: ..." line, joined."""
    comment_lines: list[str] = []
    j = entry_line_index - 1
    while j >= 0 and lines[j].strip().startswith("#"):
        comment_lines.insert(0, lines[j].strip())
        j -= 1
    return " ".join(comment_lines)


def find_preceding_comment_line(lines: list[str], entry_line_index: int) -> int | None:
    """Index of the closest comment line above entry_line_index stating a version spec, or None.

    A spec is an arrow pair or a bare "(new)"/"(unchanged)"/"(digest changed)"
    (VERSION_SPEC_RE). Stops at the first blank/non-comment line."""
    j = entry_line_index - 1
    while j >= 0 and lines[j].strip().startswith("#"):
        if VERSION_SPEC_RE.search(lines[j]):
            return j
        j -= 1
    return None


def find_grouped_preceding_comment(
    lines: list[str],
    entries: list[ManifestEntry],
    entry_line_indices: list[int],
    index: int,
    same_group: Callable[[ManifestEntry, ManifestEntry], bool],
) -> str:
    """The comment describing entries[index]'s version bump.

    Its own preceding comment if any, else that of the previous entry when
    same_group says they share one comment block (e.g. zgw-office-addin's
    frontend + backend). same_group should require the same component and
    declared version, so independently versioned siblings (zac vs zac.opa)
    don't inherit each other's comment."""
    owner = _comment_owner(
        entries, entry_line_indices, index, same_group, lambda i: bool(find_preceding_comment(lines, i))
    )
    return "" if owner is None else find_preceding_comment(lines, entry_line_indices[owner])


def find_grouped_preceding_comment_line(
    lines: list[str],
    entries: list[ManifestEntry],
    entry_line_indices: list[int],
    index: int,
    same_group: Callable[[ManifestEntry, ManifestEntry], bool],
) -> int | None:
    """Like find_grouped_preceding_comment, but returns the comment's line index."""
    owner = _comment_owner(
        entries, entry_line_indices, index, same_group, lambda i: find_preceding_comment_line(lines, i) is not None
    )
    return None if owner is None else find_preceding_comment_line(lines, entry_line_indices[owner])


def _comment_owner(
    entries: list[ManifestEntry],
    entry_line_indices: list[int],
    index: int,
    same_group: Callable[[ManifestEntry, ManifestEntry], bool],
    has_comment: Callable[[int], bool],
) -> int | None:
    """Index of the entry whose comment describes entries[index]: itself, or an earlier entry of its group."""
    while not has_comment(entry_line_indices[index]):
        if index == 0 or not same_group(entries[index], entries[index - 1]):
            return None
        index -= 1
    return index


def parse_changes_block(text: str) -> list[VersionRow]:
    """Parse an images manifest's "# Changes:" numbered list into VersionRows, e.g.:
        #   1. ZAC (Zaakafhandelcomponent) 5.0.2 -> 5.4.3 (chart 1.0.297, unchanged).

    Lines with 2+ spaces after "#" are continuations joined onto the current
    item, so a version pair split across a wrap is still found. A
    single-space "#" line ends the current item."""
    items: list[VersionRow] = []
    current = None  # raw text accumulated so far for the item being parsed
    for line in _changes_block_lines(text):
        # "\.\s+", not "\.\s*": a version like "1.17.1" on a continuation line
        # must not look like a new list item.
        m = re.match(r"^#\s*\d+\.\s+(.+)$", line)
        if m:
            if current is not None:
                items.append(_finalize_changes_item(current))
            current = m.group(1)
            continue

        cont_m = re.match(r"^#\s{2,}(\S.*)$", line)
        if cont_m and current is not None:
            current += " " + cont_m.group(1)
        elif current is not None:
            items.append(_finalize_changes_item(current))
            current = None

    if current is not None:
        items.append(_finalize_changes_item(current))
    return items


def _changes_block_lines(text: str):
    """Yield the "#" comment lines after the "# Changes:" heading, up to
    the first non-comment line."""
    in_changes = False
    for line in text.splitlines():
        if not line.startswith("#"):
            if in_changes:
                return
            continue
        if re.match(r"^#\s*Changes:\s*$", line):
            in_changes = True
            continue
        if in_changes:
            yield line


def _finalize_changes_item(rest: str) -> VersionRow:
    # Prose often ends with a period right after the version, which the version
    # regex swallows; stripped below since versions never end in ".".
    chart_m = re.search(r"\(chart\s+([^)]+)\)", rest)
    chart_source = extract_source_version(chart_m.group(1)) if chart_m else None
    chart_target = extract_target_version(chart_m.group(1)) if chart_m else None

    # A bare "chart X -> Y" clause (no parens) is a chart bump, not the app
    # version, whether alone or the first of two pairs; remove it from the
    # text searched for the app version. A parenthesized match above wins.
    app_search_text = rest
    bare_chart_m = BARE_CHART_CLAUSE_RE.search(rest)
    if bare_chart_m:
        if chart_source is None:
            chart_source = extract_source_version(bare_chart_m.group(0))
            chart_target = extract_target_version(bare_chart_m.group(0))
        app_search_text = rest[: bare_chart_m.start()] + " " + rest[bare_chart_m.end() :]

    app_source, app_target, name = _app_versions_and_name(rest, app_search_text)
    return {
        "name": name,
        "app_source": app_source,
        "app": app_target,
        "chart_source": _strip_period(chart_source),
        "chart": _strip_period(chart_target),
    }


def _strip_period(version: str | None) -> str | None:
    return version.rstrip(".") if version else version


def _app_versions_and_name(rest: str, app_search_text: str) -> tuple[str | None, str | None, str]:
    """(app_source, app_target, name) of an item; name is `rest` when no app version is found."""
    if re.search(r"(?:→|->)", app_search_text):
        app_source = _strip_period(extract_source_version(app_search_text))
        app_target = _strip_period(extract_target_version(app_search_text))
        idx = app_search_text.find(app_source) if app_source else -1
        return app_source, app_target, app_search_text[:idx].strip() if idx > 0 else rest
    # Without an arrow, the extractors' fallback would return leftover prose
    # as a fake app version.
    single_m = _SINGLE_VERSION_SPEC_RE.search(app_search_text)
    if single_m is None:
        return None, None, rest
    app_target = _strip_period(single_m.group("version"))
    app_source = None if single_m.group("kind") == "new" else app_target
    return app_source, app_target, app_search_text[: single_m.start()].strip()


def path_display_name(
    path: tuple[str, ...], deps: list[ChartDependency], canonical_names: Mapping[str, tuple[str, ...]]
) -> str:
    """Doc-facing name for a values-tree image path.

    "<values_key>" for a dependency's primary image, else the name
    canonical_names maps the path to, else the dotted path."""
    by_values_key = {values_key_of(dep): dep for dep in deps}
    dep = by_values_key.get(path[0])
    if dep is not None and is_primary_image_path(path, deps):
        return path[0]
    for name, candidate_path in canonical_names.items():
        if candidate_path == path:
            return name
    return ".".join(path)
