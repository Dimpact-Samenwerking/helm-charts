"""Pin bullets of upgrade-doc Changes blocks for values paths that share a YAML anchor.

An environment overrides values per path, so a pin reached through a YAML
alias needs its own bullet: overriding one path doesn't change the other.
"""

import re

from dataclasses import dataclass

from lib.upgradedoc.sorting_and_ordering import parse_upgrade_doc_changes_blocks

# "- `<path>` ..." (image block, under "pinned at:") or "- Image tag pin `<path>` ..." /
# "- Version pin `<path>` ..." (component block).
_PIN_BULLET_RE = re.compile(r"^- (?:Image tag pin |Version pin )?`(?P<path>[^`\s]+)` ")


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


def _aliased_bullet(bullet_lines: list[str], documented_path: str, missing_path: str) -> list[str]:
    """A copy of a bullet naming `missing_path`, marked as sharing `documented_path`'s anchor."""
    first = bullet_lines[0].rstrip("\n").replace(f"`{documented_path}`", f"`{missing_path}`", 1)
    note = f"(shares a YAML anchor with `{documented_path}`)"
    first = f"{first[: -len(' in')]} {note} in" if first.endswith(" in") else f"{first} {note}"
    return [first + "\n", *bullet_lines[1:]]


def _scan(text: str, alias_groups: dict[str, tuple[str, ...]]) -> tuple[list[str], list[tuple[_Bullet, list[str]]]]:
    """(lines, [(bullet, paths missing next to it), ...]) in document order."""
    lines = text.splitlines(keepends=True)
    found: list[tuple[_Bullet, list[str]]] = []
    for block in parse_upgrade_doc_changes_blocks(text):
        bullets = _block_bullets(lines, block["start"] + 1, block["end"])
        documented = {b.path for b in bullets}
        for bullet in bullets:
            missing = [p for p in alias_groups.get(bullet.path, ()) if p not in documented]
            documented.update(missing)
            if missing:
                found.append((bullet, missing))
    return lines, found


def _headings_by_line(text: str) -> dict[int, str]:
    return {i: b["heading"] for b in parse_upgrade_doc_changes_blocks(text) for i in range(b["start"], b["end"])}


def _missing_pin_bullets(text: str, found: list[tuple[_Bullet, list[str]]]) -> list[MissingPinBullet]:
    headings = _headings_by_line(text)
    return [MissingPinBullet(headings[b.start], b.path, p) for b, missing in found for p in missing]


def find_missing_pin_bullets(text: str, alias_groups: dict[str, tuple[str, ...]]) -> list[MissingPinBullet]:
    """Paths sharing an anchor with a documented pin bullet that have no bullet of their own."""
    return _missing_pin_bullets(text, _scan(text, alias_groups)[1])


def add_missing_pin_bullets(text: str, alias_groups: dict[str, tuple[str, ...]]) -> tuple[str, list[MissingPinBullet]]:
    """Add the bullets find_missing_pin_bullets reports, each after the bullet it copies."""
    lines, found = _scan(text, alias_groups)
    added = _missing_pin_bullets(text, found)
    for bullet, missing in reversed(found):
        bullet_lines = lines[bullet.start : bullet.end]
        lines[bullet.end : bullet.end] = [
            line for path in missing for line in _aliased_bullet(bullet_lines, bullet.path, path)
        ]
    return "".join(lines), added
