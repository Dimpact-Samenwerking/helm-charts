"""fix-doc-consistency's own sibling-doc-reference and images-manifest
baseline rewriting helpers, split out of that script for pylint's
too-many-lines check. Pure text helpers, no dependency on the script's
own SCRIPT_DIR-derived paths."""

import re

# Same shape as verify-podiumd's SIBLING_DOC_RE/IMAGES_REF check — any
# reference to one of the just-renamed docs, whatever baseline it names.
SIBLING_DOC_RE_TMPL = r"(?P<baseline>\d+\.\d+\.\d+)-to-{target}-(?P<suffix>upgrade|gemeente-specific|values-deltas)\.md"
BASELINE_LINE_RE = re.compile(r"(?P<prefix>Baseline:\s*podiumd\s+)(?P<baseline>\d+\.\d+\.\d+)")
VS_LINE_RE_TMPL = r"(?P<prefix>podiumd\s+{target}\s+vs\s+)(?P<baseline>\d+\.\d+\.\d+)"


def extract_images_baseline(text: str):
    """The version named on the "Baseline: podiumd X" line, or None if the
    manifest doesn't have one (malformed/legacy header)."""
    m = BASELINE_LINE_RE.search(text)
    return m.group("baseline") if m else None


def update_sibling_doc_refs(text: str, target: str, new_baseline: str):
    """Rewrite any "<some-baseline>-to-<target>-<suffix>.md" reference
    (whatever baseline it currently names) to the new baseline — these docs
    were just renamed. Used both on the per-suffix docs themselves (a
    values-deltas doc pointing at its sibling upgrade.md, say) and on
    images-<target>.yaml. Safe unconditionally: this chart supports exactly
    one upgrade path per target, so a reference targeting `target` always
    means the current baseline, never some other still-valid historical
    hop. `changed` reflects whether the text actually differs, NOT
    whether the pattern matched anything — a doc already mentioning
    "<new_baseline>-to-<target>-*.md" (nothing stale left to fix) still
    matches the pattern, but subn's own replacement rebuilds the exact
    same string; counting matches alone falsely reported "fixed" for
    every such already-correct mention. Returns (new_text, changed)."""
    pattern = re.compile(SIBLING_DOC_RE_TMPL.format(target=re.escape(target)))
    new_text = pattern.sub(lambda m: f"{new_baseline}-to-{target}-{m.group('suffix')}.md", text)
    return new_text, new_text != text


def update_images_manifest_baseline(text: str, target: str, new_baseline: str):
    """Rewrite the "Baseline: podiumd X" and "podiumd <target> vs X" lines
    to the new baseline, whatever X currently is. Returns (new_text, changed)."""
    text, n1 = BASELINE_LINE_RE.subn(rf"\g<prefix>{new_baseline}", text)
    vs_pattern = re.compile(VS_LINE_RE_TMPL.format(target=re.escape(target)))
    text, n2 = vs_pattern.subn(rf"\g<prefix>{new_baseline}", text)
    return text, (n1 + n2) > 0
