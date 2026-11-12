"""Pin bullets of upgrade-doc Changes blocks for values paths that share a YAML anchor.

An environment overrides values per path, so a pin reached through a YAML
alias needs its own bullet: overriding one path doesn't change the other.
An alias that had the old version the documented bullet shows gets a copy
of it; one that had another version (it joined the anchor) shows its own,
unless another Changes block already documents it.
"""

import re

from dataclasses import dataclass

from lib.chart.values_tree_primitives import text_at
from lib.chart.values_tree_primitives import version_of
from lib.component_docs.changes_section import ALIAS_NOTE
from lib.upgradedoc.sorting_and_ordering import changes_blocks_with_lines
from lib.upgradedoc.sorting_and_ordering import parse_changes_blocks
from lib.upgradedoc.version_cells import PIN_TEXT_PATTERN
from lib.upgradedoc.version_cells import pin_version_text
from lib.yaml_types import YamlValue

# "- `<path>` ..." (image block, under "pinned at:") or "- Image tag pin `<path>` ..." /
# "- Version pin `<path>` ..." (component block).
_PIN_BULLET_RE = re.compile(r"^- (?:Image tag pin |Version pin )?`(?P<path>[^`\s]+)` ")
_PIN_TEXT_RE = re.compile(PIN_TEXT_PATTERN)


@dataclass(frozen=True)
class MissingPinBullet:
    """A Changes block documents `documented_path` but not `missing_path`, which shares its anchor."""

    heading: str
    documented_path: str
    missing_path: str


@dataclass(frozen=True)
class _Bullet:
    start: int
    end: int
    path: str


def _block_bullets(lines: list[str], start: int, end: int) -> list[_Bullet]:
    """Pin bullets in lines[start:end]; a bullet runs on over its "  "-indented continuation lines."""
    bullets: list[_Bullet] = []
    start_index = start
    while start_index < end:
        bullet_match = _PIN_BULLET_RE.match(lines[start_index])
        if not bullet_match:
            start_index += 1
            continue
        end_index = start_index + 1
        while end_index < end and lines[end_index].startswith("  ") and lines[end_index].strip():
            end_index += 1
        bullets.append(_Bullet(start_index, end_index, bullet_match.group("path")))
        start_index = end_index
    return bullets


def _baseline_version(baseline_values: YamlValue, path: str) -> str | None:
    old = text_at(baseline_values, path)
    return version_of(old) if isinstance(old, str) and old else None


def _shown_old(bullet_line: str) -> str | None:
    """The old version a pin bullet shows: None for "(new)" or no version text."""
    pin = _PIN_TEXT_RE.search(bullet_line)
    if pin is None or pin.group("pin_status") == "new":
        return None
    return pin.group("pin_old") or pin.group("pin_kept")


def _aliased_bullet(
    bullet_lines: list[str], documented_path: str, missing_path: str, baseline_values: YamlValue
) -> list[str]:
    """A copy of a bullet naming `missing_path`, marked as sharing `documented_path`'s anchor.

    The version text is `missing_path`'s own when its old version differs from the shown one.
    """
    first = bullet_lines[0].rstrip("\n").replace(f"`{documented_path}`", f"`{missing_path}`", 1)
    own_old = _baseline_version(baseline_values, missing_path)
    pin = _PIN_TEXT_RE.search(first)
    if pin is not None and own_old != _shown_old(first):
        new = pin.group("pin_new") or pin.group("pin_kept")
        first = f"{first[: pin.start()]}{pin_version_text(own_old, new)}{first[pin.end() :]}"
    note = ALIAS_NOTE.format(path=documented_path)
    suffix = " in" if first.endswith(" in") else ""
    first = f"{first.removesuffix(suffix)} {note}{suffix}"
    return [f"{first}\n", *bullet_lines[1:]]


# A pin bullet and the alias paths missing next to it.
type _UndocumentedAliases = tuple[_Bullet, list[str]]


def _scan(
    text: str, alias_groups: dict[str, tuple[str, ...]], baseline_values: YamlValue
) -> tuple[list[str], list[_UndocumentedAliases]]:
    """(lines, [(bullet, paths missing next to it), ...]) in document order.

    An alias with another old version than the bullet shows is missing only when no
    Changes block documents it: a path that joined the anchor may have its own section.
    """
    lines, blocks = changes_blocks_with_lines(text)
    block_bullets = [_block_bullets(lines, block["start"] + 1, block["end"]) for block in blocks]
    documented_anywhere = {documented_bullet.path for bullets in block_bullets for documented_bullet in bullets}
    found: list[_UndocumentedAliases] = []
    for bullets in block_bullets:
        documented = {documented_bullet.path for documented_bullet in bullets}
        for bullet in bullets:
            old = _shown_old(lines[bullet.start])
            missing = [
                path
                for path in alias_groups.get(bullet.path, ())
                if path not in documented
                and (_baseline_version(baseline_values, path) == old or path not in documented_anywhere)
            ]
            documented.update(missing)
            if missing:
                found.append((bullet, missing))
    return lines, found


def _headings_by_line(text: str) -> dict[int, str]:
    return {
        line_index: block["heading"]
        for block in parse_changes_blocks(text)
        for line_index in range(block["start"], block["end"])
    }


def _missing_pin_bullets(text: str, found: list[_UndocumentedAliases]) -> list[MissingPinBullet]:
    headings = _headings_by_line(text)
    return [
        MissingPinBullet(headings[bullet.start], bullet.path, path) for bullet, missing in found for path in missing
    ]


def add_missing_pin_bullets(
    text: str, alias_groups: dict[str, tuple[str, ...]], baseline_values: YamlValue
) -> tuple[str, list[MissingPinBullet]]:
    """Add a bullet for each path sharing an anchor with a documented pin bullet, after the bullet it copies.

    Returns (new_text, the bullets added).
    """
    lines, found = _scan(text, alias_groups, baseline_values)
    added = _missing_pin_bullets(text, found)
    for bullet, missing in reversed(found):
        bullet_lines = lines[bullet.start : bullet.end]
        aliased = [
            line for path in missing for line in _aliased_bullet(bullet_lines, bullet.path, path, baseline_values)
        ]
        lines = [*lines[: bullet.end], *aliased, *lines[bullet.end :]]
    return "".join(lines), added
