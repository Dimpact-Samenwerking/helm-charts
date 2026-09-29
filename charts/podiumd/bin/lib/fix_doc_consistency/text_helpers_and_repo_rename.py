"""fix-doc-consistency's text/heading helpers and the git-mv rename step."""

import re

from pathlib import Path

from lib.procutil import run

TITLE_ARROW_RE_TMPL = r"(?P<baseline>{baseline})(?P<arrow>\s*(?:→|->)\s*){target}"
COMPONENT_VERSIONS_RE_TMPL = r"Component versions \({target}\s+vs\s+(?P<baseline>{baseline})\)"

HEADING_LINE_RE = re.compile(r"^#{1,6}\s")
FENCE_LINE_RE = re.compile(r"^\s*```")


def find_collisions(by_suffix: dict[str, list[tuple[str, Path]]]):
    """suffix -> [(baseline, path), ...] for suffixes whose sources would collide on rename."""
    return {suffix: entries for suffix, entries in by_suffix.items() if len(entries) > 1}


def git_mv(src: Path, dst: Path):
    """`git mv src dst` so history follows the file; SystemExit with git's stderr on failure."""
    result = run(["git", "mv", str(src), str(dst)], cwd=src.parent, capture_output=True, text=True)
    if result.returncode != 0:
        msg = f"error: git mv {src} -> {dst} failed: {result.stderr.strip()}"
        raise SystemExit(msg)


def update_title_line(text: str, old_baseline: str, target: str, new_baseline: str):
    """Replace "<old_baseline> → <target>" (or "->") on the title line
    (line 1) only. Returns (new_text, changed)."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return text, False
    pattern = re.compile(TITLE_ARROW_RE_TMPL.format(baseline=re.escape(old_baseline), target=re.escape(target)))
    new_first, count = pattern.subn(lambda m: f"{new_baseline}{m.group('arrow')}{target}", lines[0])
    if count == 0:
        return text, False
    lines[0] = new_first
    return "".join(lines), True


def update_component_versions_heading(text: str, old_baseline: str, target: str, new_baseline: str):
    """Replace a "Component versions (<target> vs <old_baseline>)" heading
    anywhere in the body, if present. Returns (new_text, changed)."""
    pattern = re.compile(COMPONENT_VERSIONS_RE_TMPL.format(baseline=re.escape(old_baseline), target=re.escape(target)))
    new_text, count = pattern.subn(f"Component versions ({target} vs {new_baseline})", text)
    return new_text, count > 0


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

    Lines inside fenced code blocks are skipped via a per-line toggle
    (strip_fenced_code_blocks would shift line numbers). No blank line is
    added at the file's top or bottom."""
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    in_fence = False
    for i, line in enumerate(lines):
        if FENCE_LINE_RE.match(line):
            in_fence = not in_fence
            result.append(line)
            continue
        if not in_fence and HEADING_LINE_RE.match(line):
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
