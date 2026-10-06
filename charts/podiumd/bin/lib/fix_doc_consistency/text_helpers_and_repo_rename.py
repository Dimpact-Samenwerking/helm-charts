"""fix-doc-consistency's text/heading helpers and the git-mv rename step."""

import re

from pathlib import Path

from lib.procutil import run
from lib.upgradedoc.string_and_parsing_basics import fenced_line_flags
from lib.version_numbers import BARE_VERSION_PATTERN

# Any baseline, not only the doc's file name one: a title or heading left on a
# third version (hand-edited, or a doc already renamed) is rebased too.
TITLE_ARROW_RE_TMPL = rf"(?P<baseline>{BARE_VERSION_PATTERN})(?P<arrow>\s*(?:→|->)\s*){{target}}"
COMPONENT_VERSIONS_RE_TMPL = rf"Component versions \({{target}}\s+vs\s+(?P<baseline>{BARE_VERSION_PATTERN})\)"

HEADING_LINE_RE = re.compile(r"^#{1,6}\s")


def find_collisions(by_suffix: dict[str, list[tuple[str, Path]]]):
    """suffix -> [(baseline, path), ...] for suffixes whose sources would collide on rename."""
    return {suffix: entries for suffix, entries in by_suffix.items() if len(entries) > 1}


def git_mv(src: Path, dst: Path):
    """`git mv src dst` so history follows the file; SystemExit with git's stderr on failure.

    An untracked src (a stub an earlier run created and nobody committed yet)
    has no history to follow, and git mv would refuse it halfway through a
    rebase, so it is renamed in place.
    """
    tracked = run(
        ["git", "ls-files", "--error-unmatch", "--", src.name], cwd=src.parent, capture_output=True, text=True
    )
    if tracked.returncode != 0:
        src.rename(dst)
        return
    result = run(["git", "mv", str(src), str(dst)], cwd=src.parent, capture_output=True, text=True)
    if result.returncode != 0:
        msg = f"error: git mv {src} -> {dst} failed: {result.stderr.strip()}"
        raise SystemExit(msg)


def update_title_line(text: str, target: str, new_baseline: str):
    """Point "<baseline> → <target>" (or "->") on the title line (line 1) at
    new_baseline. Returns (new_text, changed)."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return text, False
    pattern = re.compile(TITLE_ARROW_RE_TMPL.format(target=re.escape(target)))
    new_first = pattern.sub(lambda m: f"{new_baseline}{m.group('arrow')}{target}", lines[0])
    if new_first == lines[0]:
        return text, False
    lines[0] = new_first
    return "".join(lines), True


def update_component_versions_heading(text: str, target: str, new_baseline: str):
    """Point a "Component versions (<target> vs <baseline>)" heading anywhere
    in the body at new_baseline. Returns (new_text, changed)."""
    pattern = re.compile(COMPONENT_VERSIONS_RE_TMPL.format(target=re.escape(target)))
    new_text = pattern.sub(f"Component versions ({target} vs {new_baseline})", text)
    return new_text, new_text != text


def join_and(parts: list[str]):
    """ "a" | "a and b" | "a, b, and c"."""
    if len(parts) <= 1:
        return "".join(parts)
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def remaining_mentions(text: str, old_baseline: str):
    """1-indexed line numbers where old_baseline still appears, for manual review."""
    return [i + 1 for i, line in enumerate(text.splitlines()) if old_baseline in line]


def ensure_blank_lines_around_headings(text: str):
    """Insert missing blank lines around "#" headings (MD022).

    Lines inside fenced code blocks are skipped (fenced_line_flags). No
    blank line is added at the file's top or bottom."""
    lines = text.splitlines(keepends=True)
    fenced = fenced_line_flags(lines)
    result: list[str] = []
    for i, line in enumerate(lines):
        if not fenced[i] and HEADING_LINE_RE.match(line):
            if result and result[-1].strip():
                result.append("\n")
            result.append(line)
            if i + 1 < len(lines) and lines[i + 1].strip():
                result.append("\n")
        else:
            result.append(line)
    return "".join(result)


def collapse_multiple_blank_lines(text: str):
    """Normalize blank lines before writing a managed .md doc (MD022/MD012).

    Ensures blank lines around headings, collapses runs of blank lines to
    one, and trims trailing blanks to a single final newline: pymarkdown
    counts EOF as a blank line, so "content\\n\\n" already fails MD012."""
    text = ensure_blank_lines_around_headings(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"\n+\Z", "\n", text)
