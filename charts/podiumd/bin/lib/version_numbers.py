"""Bare release versions, and version strings as comparable number tuples."""

import re

from typing import TypeGuard

# A bare MAJOR.MINOR.PATCH, as in Chart.yaml's version and release-baseline.yaml's upgrade_docs.
BARE_VERSION_PATTERN = r"\d+\.\d+\.\d+"
_STABLE_SEMVER_RE = re.compile(rf"^v?({BARE_VERSION_PATTERN})$")


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
