"""fix-doc-consistency's sibling-doc-reference and images-manifest baseline rewriting helpers."""

import re

# Same shape as verify-podiumd's SIBLING_DOC_RE/IMAGES_REF check.
SIBLING_DOC_RE_TMPL = r"(?P<baseline>\d+\.\d+\.\d+)-to-{target}-(?P<suffix>upgrade|gemeente-specific|values-deltas)\.md"
BASELINE_LINE_RE = re.compile(r"(?P<prefix>Baseline:\s*podiumd\s+)(?P<baseline>\d+\.\d+\.\d+)")
# Any target and baseline, so a wrong one is rewritten too.
VS_LINE_RE = re.compile(r"(?P<prefix>podiumd\s+)(?P<target>\d+\.\d+\.\d+)(?P<vs>\s+vs\s+)(?P<baseline>\d+\.\d+\.\d+)")


def extract_images_baseline(text: str):
    """The version on the "Baseline: podiumd X" line, or None if absent."""
    m = BASELINE_LINE_RE.search(text)
    return m.group("baseline") if m else None


def update_sibling_doc_refs(text: str, target: str, new_baseline: str):
    """Rewrite every "<any-baseline>-to-<target>-<suffix>.md" reference to new_baseline.

    Safe unconditionally: the chart supports exactly one upgrade path per target.
    `changed` means the text differs, not that the pattern matched (an already-correct
    reference matches too). Returns (new_text, changed)."""
    pattern = re.compile(SIBLING_DOC_RE_TMPL.format(target=re.escape(target)))
    new_text = pattern.sub(lambda m: f"{new_baseline}-to-{target}-{m.group('suffix')}.md", text)
    return new_text, new_text != text


def fix_images_manifest_header_lines(text: str, target: str, new_baseline: str):
    """The "Baseline: podiumd X" and "podiumd <target> vs X" header lines, rewritten or added.

    A missing line is added where IMAGES_STUB_TEMPLATE has it: the Baseline
    line first, the "vs" line after it. Returns (new_text, changed)."""
    new_text, found = BASELINE_LINE_RE.subn(rf"\g<prefix>{new_baseline}", text, count=1)
    if not found:
        new_text = f"# Baseline: podiumd {new_baseline}. Re-verify before release.\n" + new_text
    new_text, found = VS_LINE_RE.subn(rf"\g<prefix>{target}\g<vs>{new_baseline}", new_text, count=1)
    if not found:
        lines = new_text.splitlines(keepends=True)
        baseline_idx = next(i for i, line in enumerate(lines) if BASELINE_LINE_RE.search(line))
        lines.insert(baseline_idx + 1, f"#\n# Images new or changed in podiumd {target} vs {new_baseline}.\n")
        new_text = "".join(lines)
    return new_text, new_text != text
