"""Version strings as comparable number tuples."""

import re

_STABLE_SEMVER_RE = re.compile(r"^v?(\d+\.\d+\.\d+)$")


def dotted_numbers(text: str) -> tuple[int, ...]:
    """(1, 2, 3) for "1.2.3": a dotted run of digits as a tuple that compares numerically."""
    return tuple(int(part) for part in text.split("."))


def stable_semver_key(version: str) -> tuple[int, ...] | None:
    """dotted_numbers of a stable "X.Y.Z" version ("v" prefix allowed); None for anything else."""
    m = _STABLE_SEMVER_RE.match(version)
    return dotted_numbers(m.group(1)) if m else None
