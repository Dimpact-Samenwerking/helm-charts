"""Title and markdown well-formedness checks for the upgrade, gemeente-specific and values-deltas docs."""

import re

from pathlib import Path

from lib.upgradedoc.doc_names import STANDARD_SUFFIXES
from lib.upgradedoc.doc_names import doc_name


def check_doc_title(doc_path: Path, upgrade_docs_baseline: str, podiumd_version: str) -> list[str]:
    """Verify a doc's first line states "<upgrade_docs_baseline> → <podiumd_version>"."""
    lines = doc_path.read_text(encoding="utf-8").splitlines()
    first_line = lines[0] if lines else ""
    if not re.search(rf"{re.escape(upgrade_docs_baseline)}\s*(?:→|->)\s*{re.escape(podiumd_version)}", first_line):
        return [
            f'{doc_path.name} title line "{first_line}" does not read "{upgrade_docs_baseline} → {podiumd_version}"'
        ]
    return []


def check_companion_doc(doc_dir: Path, upgrade_docs_baseline: str, podiumd_version: str, suffix: str):
    """When a bare-version upgrade_docs_baseline is given, verify the matching
    <upgrade_docs_baseline>-to-<podiumd_version>-<suffix>.md exists and its title line
    states the same "<upgrade_docs_baseline> → <podiumd_version>" pair."""
    name = doc_name(upgrade_docs_baseline, podiumd_version, suffix)
    doc_path = doc_dir / name
    if not doc_path.is_file():
        return name, [f'expected "{name}" does not exist']
    return name, check_doc_title(doc_path, upgrade_docs_baseline, podiumd_version)


def check_markdown_format(doc_path: Path):
    """Check a doc is non-empty, opens with a level-1 heading, and has balanced ``` fences.

    An unclosed fence swallows the rest of the file when rendered.
    """
    text = doc_path.read_text(encoding="utf-8")
    if not text.strip():
        return ["file is empty"]

    issues: list[str] = []
    first_line = text.splitlines()[0]
    if not first_line.startswith("# "):
        issues.append(f'first line "{first_line}" is not a level-1 heading ("# ...")')

    # Fences may be indented under numbered list steps.
    fence_count = len(re.findall(r"^[ \t]*```", text, re.MULTILINE))
    if fence_count % 2 != 0:
        issues.append(f"{fence_count} fenced code block markers (```) — unbalanced")

    return issues


def check_baseline_doc_set(doc_dir: Path, upgrade_docs_baseline: str, podiumd_version: str):
    """Existence and format precheck of all three docs; run before content checks."""
    issues: list[str] = []
    for suffix in STANDARD_SUFFIXES:
        name = doc_name(upgrade_docs_baseline, podiumd_version, suffix)
        doc_path = doc_dir / name
        if not doc_path.is_file():
            issues.append(f'expected "{name}" does not exist')
            continue
        issues.extend(f"{name}: {issue}" for issue in check_markdown_format(doc_path))
    return issues
