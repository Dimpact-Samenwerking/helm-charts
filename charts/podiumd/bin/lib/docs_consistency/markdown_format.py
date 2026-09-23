"""Doc-title + basic markdown well-formedness checks for the three
upgrade_docs_baseline docs (upgrade, gemeente-specific, values-deltas) —
used by lib.docs_consistency.check_docs_consistency."""

import re

from pathlib import Path


def check_doc_title(doc_path: Path, upgrade_docs_baseline: str, podiumd_version: str):
    """Verify a doc's first line states the "<upgrade_docs_baseline> → <podiumd_version>"
    pair — catches a doc that was renamed without updating its own heading."""
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
    name = f"{upgrade_docs_baseline}-to-{podiumd_version}-{suffix}.md"
    doc_path = doc_dir / name
    if not doc_path.is_file():
        return name, [f'expected "{name}" does not exist']
    return name, check_doc_title(doc_path, upgrade_docs_baseline, podiumd_version)


def check_markdown_format(doc_path: Path):
    """Minimal sanity check that a doc is well-formed markdown, before trying
    to parse anything out of it: non-empty, opens with a level-1 heading, and
    any fenced code blocks are balanced (an unclosed ``` silently swallows
    the rest of the file when rendered)."""
    text = doc_path.read_text(encoding="utf-8")
    if not text.strip():
        return ["file is empty"]

    issues = []
    first_line = text.splitlines()[0]
    if not first_line.startswith("# "):
        issues.append(f'first line "{first_line}" is not a level-1 heading ("# ...")')

    # Allow leading indentation: upgrade docs routinely nest ``` blocks
    # under numbered list steps, so the fence is not at column 0.
    fence_count = len(re.findall(r"^[ \t]*```", text, re.MULTILINE))
    if fence_count % 2 != 0:
        issues.append(f"{fence_count} fenced code block markers (```) — unbalanced")

    return issues


def check_baseline_doc_set(doc_dir: Path, upgrade_docs_baseline: str, podiumd_version: str):
    """Existence + markdown-format precheck for all three upgrade_docs_baseline docs,
    run BEFORE any content-based check on them — a doc that's missing or
    malformed makes every downstream check on it meaningless."""
    issues = []
    for suffix in ("upgrade", "gemeente-specific", "values-deltas"):
        name = f"{upgrade_docs_baseline}-to-{podiumd_version}-{suffix}.md"
        doc_path = doc_dir / name
        if not doc_path.is_file():
            issues.append(f'expected "{name}" does not exist')
            continue
        issues.extend(f"{name}: {issue}" for issue in check_markdown_format(doc_path))
    return issues
