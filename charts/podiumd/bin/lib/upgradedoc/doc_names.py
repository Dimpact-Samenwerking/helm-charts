"""File names of the upgrade docs and images manifests, and the patterns that find them in names and text."""

import re

from collections.abc import Sequence
from pathlib import Path

from lib.version_numbers import BARE_VERSION_PATTERN

# The docs check_baseline_doc_set expects for every target.
STANDARD_SUFFIXES = ("upgrade", "gemeente-specific", "values-deltas")


def title_arrow_re(target: str) -> re.Pattern[str]:
    """ "<baseline> → <target>" (or "->") in a doc's title line, for any baseline.

    Shared by fix-doc-consistency, which rewrites it, and the checker, which
    compares its baseline; whole versions only, so "14.9.0" is not "4.9.0".
    """
    return re.compile(
        rf"(?<![\w.])(?P<baseline>{BARE_VERSION_PATTERN})(?P<arrow>\s*(?:→|->)\s*){re.escape(target)}(?![\w.])"
    )


IMAGES_MANIFEST_NAME_RE = re.compile(rf"images-(?P<target>{BARE_VERSION_PATTERN})\.yaml")


def doc_name(upgrade_docs_baseline: str, target: str, suffix: str) -> str:
    """<upgrade_docs_baseline>-to-<target>-<suffix>.md."""
    return f"{upgrade_docs_baseline}-to-{target}-{suffix}.md"


def doc_name_re(target: str | None = None, suffixes: Sequence[str] | None = None) -> re.Pattern[str]:
    """doc_name's shape, with "baseline", "target" and "suffix" groups.

    Any target and any suffix unless given, so new doc types need no change."""
    target_pattern = re.escape(target) if target else BARE_VERSION_PATTERN
    suffix_pattern = "|".join(map(re.escape, suffixes)) if suffixes else r"[\w\-]+"
    return re.compile(
        rf"(?P<baseline>{BARE_VERSION_PATTERN})-to-(?P<target>{target_pattern})-(?P<suffix>{suffix_pattern})\.md"
    )


def images_manifest_name(target: str) -> str:
    """images-<target>.yaml."""
    return f"images-{target}.yaml"


def images_manifest_path(images_dir: Path, target: str) -> Path:
    """The docs/images/images-<target>.yaml path for `target`, whether or not it exists."""
    return images_dir / images_manifest_name(target)
