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
from lib.upgradedoc.sorting_and_ordering import parse_upgrade_doc_changes_blocks
from lib.upgradedoc.version_cells_and_key_changes import PIN_TEXT_PATTERN
from lib.upgradedoc.version_cells_and_key_changes import pin_version_text
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
    i = start
    while i < end:
        m = _PIN_BULLET_RE.match(lines[i])
        if not m:
            i += 1
            continue
        j = i + 1
        while j < end and lines[j].startswith("  ") and lines[j].strip():
            j += 1
        bullets.append(_Bullet(i, j, m.group("path")))
        i = j
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
    first = f"{first[: -len(' in')]} {note} in" if first.endswith(" in") else f"{first} {note}"
    return [first + "\n", *bullet_lines[1:]]


def _scan(
    text: str, alias_groups: dict[str, tuple[str, ...]], baseline_values: YamlValue
) -> tuple[list[str], list[tuple[_Bullet, list[str]]]]:
    """(lines, [(bullet, paths missing next to it), ...]) in document order.

    An alias with another old version than the bullet shows is missing only when no
    Changes block documents it: a path that joined the anchor may have its own section.
    """
    lines, blocks = changes_blocks_with_lines(text)
    block_bullets = [_block_bullets(lines, block["start"] + 1, block["end"]) for block in blocks]
    documented_anywhere = {b.path for bullets in block_bullets for b in bullets}
    found: list[tuple[_Bullet, list[str]]] = []
    for bullets in block_bullets:
        documented = {b.path for b in bullets}
        for bullet in bullets:
            old = _shown_old(lines[bullet.start])
            missing = [
                p
                for p in alias_groups.get(bullet.path, ())
                if p not in documented
                and (_baseline_version(baseline_values, p) == old or p not in documented_anywhere)
            ]
            documented.update(missing)
            if missing:
                found.append((bullet, missing))
    return lines, found


def _headings_by_line(text: str) -> dict[int, str]:
    return {i: b["heading"] for b in parse_upgrade_doc_changes_blocks(text) for i in range(b["start"], b["end"])}


def _missing_pin_bullets(text: str, found: list[tuple[_Bullet, list[str]]]) -> list[MissingPinBullet]:
    headings = _headings_by_line(text)
    return [MissingPinBullet(headings[b.start], b.path, p) for b, missing in found for p in missing]


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
        lines[bullet.end : bullet.end] = [
            line for path in missing for line in _aliased_bullet(bullet_lines, bullet.path, path, baseline_values)
        ]
    return "".join(lines), added
