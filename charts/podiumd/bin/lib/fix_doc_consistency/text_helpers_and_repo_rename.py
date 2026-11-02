"""fix-doc-consistency's text/heading helpers and the git-mv rename step."""

import re

from pathlib import Path

from lib.component_docs.owned_parts import generated_heading_name
from lib.procutil import run
from lib.upgradedoc.doc_names import title_arrow_re
from lib.upgradedoc.string_and_parsing_basics import fenced_line_flags
from lib.version_numbers import BARE_VERSION_PATTERN

# Any baseline, not only the doc's file name one: a heading left on a third
# version (hand-edited, or a doc already renamed) is rebased too.
COMPONENT_VERSIONS_RE_TMPL = rf"Component versions \({{target}}\s+vs\s+(?P<baseline>{BARE_VERSION_PATTERN})\)"

HEADING_LINE_RE = re.compile(r"^#{1,6}\s")
_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<text>.*?)\s*$")
_LINK_FRAGMENT_RE = re.compile(r"\]\(#(?P<fragment>[^)\s]+)\)")


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
    new_first = title_arrow_re(target).sub(lambda m: f"{new_baseline}{m.group('arrow')}{target}", lines[0])
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
    """1-indexed line numbers where old_baseline still appears, for manual review.

    Whole versions only: "14.8.4" or "4.8.40" is not 4.8.4, "v4.8.4." is.
    """
    pattern = re.compile(rf"(?<![\d.]){re.escape(old_baseline)}(?!\.?\d)")
    return [i + 1 for i, line in enumerate(text.splitlines()) if pattern.search(line)]


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


def heading_slug(heading: str):
    """The anchor GitHub gives a heading, which pymarkdown's MD051 checks "(#...)" links against."""
    return "".join(c for c in heading.lower() if c.isalnum() or c in " -_").replace(" ", "-")


def _headings(text: str) -> list[tuple[str, str]]:
    """(marks, text) of each "#" heading outside fenced code blocks."""
    lines = text.splitlines()
    fenced = fenced_line_flags(lines)
    return [
        (m.group("marks"), m.group("text"))
        for line, in_fence in zip(lines, fenced, strict=True)
        if not in_fence and (m := _HEADING_RE.match(line))
    ]


def _generated_headings(headings: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """(marks, component name) -> text of each generated heading; a name on two headings is left out."""
    by_name: dict[tuple[str, str], list[str]] = {}
    for marks, heading in headings:
        name = generated_heading_name(heading)
        if name is not None:
            by_name.setdefault((marks, name), []).append(heading)
    return {key: texts[0] for key, texts in by_name.items() if len(texts) == 1}


def retarget_heading_links(old_text: str, new_text: str) -> tuple[str, list[str]]:
    """Point "(#...)" links at a generated heading the writers renamed between old_text and new_text.

    A heading is the same one when its level and component name are. Returns
    (new_text, ["#old -> #new", ...]).
    """
    new_headings = _headings(new_text)
    old_generated = _generated_headings(_headings(old_text))
    new_generated = _generated_headings(new_headings)
    current = {heading_slug(heading) for _marks, heading in new_headings}
    moves = {
        heading_slug(old_generated[key]): heading_slug(new_generated[key])
        for key in old_generated.keys() & new_generated.keys()
        if heading_slug(old_generated[key]) not in current
    }
    if not moves:
        return new_text, []
    retargeted: list[str] = []

    def retarget(m: re.Match[str]):
        target = moves.get(m.group("fragment"))
        if target is None:
            return m.group(0)
        retargeted.append(f"#{m.group('fragment')} -> #{target}")
        return f"](#{target})"

    lines = new_text.splitlines(keepends=True)
    fenced = fenced_line_flags(lines)
    text = "".join(
        line if in_fence else _LINK_FRAGMENT_RE.sub(retarget, line)
        for line, in_fence in zip(lines, fenced, strict=True)
    )
    return text, retargeted
