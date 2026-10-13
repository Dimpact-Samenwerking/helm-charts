"""Bare release versions, and version strings as comparable number tuples."""

import re

from collections.abc import Iterable
from typing import TypeGuard

# A bare MAJOR.MINOR.PATCH, as in Chart.yaml's version and release-baseline.yaml's upgrade_docs.
BARE_VERSION_PATTERN = r"\d+\.\d+\.\d+"
_STABLE_SEMVER_RE = re.compile(rf"^v?({BARE_VERSION_PATTERN})$")
# The leading dotted-digits run of an image tag, after an optional "v": "3.14" of "3.14-slim" or "v3.14".
NUMERIC_PREFIX_RE = re.compile(r"^(v?)(\d+(?:\.\d+)*)")


def is_bare_version(version: str | None) -> TypeGuard[str]:
    """Whether `version` is a bare MAJOR.MINOR.PATCH (no "v", no pre-release): a release, not a git ref."""
    return version is not None and re.fullmatch(BARE_VERSION_PATTERN, version) is not None


def dotted_numbers(text: str) -> tuple[int, ...]:
    """(1, 2, 3) for "1.2.3": a dotted run of digits as a tuple that compares numerically."""
    return tuple(int(part) for part in text.split("."))


def stable_semver_key(version: str) -> tuple[int, ...] | None:
    """dotted_numbers of a stable "X.Y.Z" version ("v" prefix allowed); None for anything else."""
    m = _STABLE_SEMVER_RE.match(version)
    return dotted_numbers(m.group(1)) if m else None


def _major_line_of_key(key: tuple[int, ...]) -> tuple[int, ...]:
    """(16,) for (16, 15); () for a single number such as a build number, all one line."""
    return key[:1] if len(key) > 1 else ()


def major_line(version: str) -> tuple[int, ...] | None:
    """The major line of an image tag: (16,) for "16.15-alpine" or "v16.1", () for "104"
    (see _major_line_of_key); None if `version` doesn't start with a number."""
    m = NUMERIC_PREFIX_RE.match(version)
    return _major_line_of_key(dotted_numbers(m.group(2))) if m else None


def newest_per_major(current: tuple[int, ...], candidates: Iterable[tuple[str, tuple[int, ...]]]) -> list[str]:
    """The highest candidate above `current` in each major line (see major_line), lines ascending.

    One per major because staying on the current major (postgres 16 while 18 is out)
    is as valid a target as the newest release.
    """
    best: dict[tuple[int, ...], tuple[tuple[int, ...], str]] = {}
    for version, key in candidates:
        line = _major_line_of_key(key)
        if key > current and (line not in best or key > best[line][0]):
            best[line] = (key, version)
    return [best[line][1] for line in sorted(best)]
