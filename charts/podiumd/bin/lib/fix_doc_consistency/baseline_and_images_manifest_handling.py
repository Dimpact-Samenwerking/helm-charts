"""fix-doc-consistency's sibling-doc-reference and images-manifest baseline rewriting helpers."""

import re

# Same shape as verify-podiumd's SIBLING_DOC_RE/IMAGES_REF check.
SIBLING_DOC_RE_TMPL = r"(?P<baseline>\d+\.\d+\.\d+)-to-{target}-(?P<suffix>upgrade|gemeente-specific|values-deltas)\.md"
BASELINE_LINE_RE = re.compile(r"(?P<prefix>Baseline:\s*podiumd\s+)(?P<baseline>\d+\.\d+\.\d+)")
VS_LINE_RE_TMPL = r"(?P<prefix>podiumd\s+{target}\s+vs\s+)(?P<baseline>\d+\.\d+\.\d+)"


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


def update_images_manifest_baseline(text: str, target: str, new_baseline: str):
    """Rewrite the "Baseline: podiumd X" and "podiumd <target> vs X" lines to new_baseline.

    Returns (new_text, changed)."""
    text, n1 = BASELINE_LINE_RE.subn(rf"\g<prefix>{new_baseline}", text)
    vs_pattern = re.compile(VS_LINE_RE_TMPL.format(target=re.escape(target)))
    text, n2 = vs_pattern.subn(rf"\g<prefix>{new_baseline}", text)
    return text, (n1 + n2) > 0
