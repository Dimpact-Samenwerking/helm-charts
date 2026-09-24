"""fix-doc-consistency's own text/heading helpers and the git-mv rename
step, split out of that script for pylint's too-many-lines check. Pure
text/subprocess helpers, no dependency on the script's own SCRIPT_DIR-
derived paths."""

import re

from pathlib import Path

from lib.procutil import run

TITLE_ARROW_RE_TMPL = r"(?P<baseline>{baseline})(?P<arrow>\s*(?:→|->)\s*){target}"
COMPONENT_VERSIONS_RE_TMPL = r"Component versions \({target}\s+vs\s+(?P<baseline>{baseline})\)"

HEADING_LINE_RE = re.compile(r"^#{1,6}\s")
FENCE_LINE_RE = re.compile(r"^\s*```")


def find_collisions(by_suffix: dict[str, list[tuple[str, Path]]]):
    """suffix -> [(baseline, path), ...] for every suffix with more than one
    source file — these would collide on the same rename destination."""
    return {suffix: entries for suffix, entries in by_suffix.items() if len(entries) > 1}


def git_mv(src: Path, dst: Path):
    """`git mv src dst` (run from src's own directory), raising SystemExit
    with git's own stderr on failure — the actual rename step behind
    fix-doc-consistency's baseline-mismatch renames, so history/blame
    follows the file instead of a plain filesystem move losing it."""
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
    """ "a" | "a and b" | "a, b, and c" — natural-language join for a
    per-doc summary line combining however many of its own independent
    fixes actually fired this run (stub-TODO removal, stale sibling-doc
    references, collapsed blank lines, ...), instead of a fixed set of
    hand-enumerated if/elif/else combinations that stops scaling past
    two possible fixes."""
    if len(parts) <= 1:
        return "".join(parts)
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def remaining_mentions(text: str, old_baseline: str):
    """Line numbers (1-indexed) where old_baseline still appears, for a
    manual-review reminder — every match, not just ones already handled."""
    return [i + 1 for i, line in enumerate(text.splitlines()) if old_baseline in line]


def ensure_blank_lines_around_headings(text: str):
    """Insert a missing blank line directly above and/or below every real
    "#"-heading line (pymarkdown's MD022, headings-surrounded-by-blank-
    lines) — the companion collapse_multiple_blank_lines below never
    adds, only ever removes EXCESS blank lines. A heading landing
    directly against non-blank content on either side was never
    something this script repaired, only ever produced fresh: real case,
    lib.component_docs.insert_changes_section relocating whatever block
    currently sorts last in the file used to assume a blank line already
    separated it from the PRECEDING content, which isn't guaranteed —
    e.g. this exact function, run on an earlier pass, already collapsed
    that same trailing blank away as part of its own EOF-quirk fix
    below, or a reordering pass simply never normalized the seam.

    A "#" line inside a fenced ```...``` code block (a shell comment, a
    YAML "#" key, ...) is never a real heading and is never touched —
    tracked with a plain per-line fence toggle rather than lib.
    upgradedoc.strip_fenced_code_blocks' own text-collapsing substitution,
    which would desync every line number this function depends on. Never
    adds a blank line at the very top/bottom of the file — nothing there
    to separate a heading from."""
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
    """First inserts any blank line MISSING around a heading (see ensure_
    blank_lines_around_headings), then collapses any run of 2+
    consecutive blank lines down to exactly one (pymarkdown's MD012,
    no-multiple-blanks) — never changes a doc's rendered meaning
    (Markdown treats one blank line and several identically), just
    removes purely cosmetic byte duplication this script's own splicing
    (a new stub section inserted between two existing ones, a reordered
    block leaving a stray blank line behind, ...) can otherwise
    accumulate. Applied right before writing any of the three standard
    .md docs this script manages, so a real MD012/MD022 violation never
    needs a separate fix-markdown pass afterward for something this
    script itself introduced.

    ALSO collapses any trailing blank line(s) right before EOF down to a
    single final newline — confirmed live against real pymarkdown: it
    counts EOF itself as an implicit extra blank line, so a file merely
    ENDING in "content\n\n" (one syntactic blank line before EOF, no
    triple newline anywhere for the check above to ever catch) already
    reports "Multiple consecutive blank lines: Expected: 1, Actual: 2"
    at the line right after the last real content line. All three fixes
    together mean this doc's own blank-line convention matches
    everywhere in it: at least one blank line around every heading, at
    most one blank line ever anywhere (including right before EOF)."""
    text = ensure_blank_lines_around_headings(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"\n+\Z", "\n", text)
