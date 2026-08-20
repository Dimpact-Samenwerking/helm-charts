"""Report-only structural-duplication scan for templates/*.yaml — flags
file pairs that look like copy-paste (the shape podiumd.storagePVC was
factored out of) without ever failing the check; deduping is a judgment
call a human should make, not something to gate a build on."""
import difflib

# Similarity thresholds, calibrated against this repo's own templates/
# directory using two known reference points: the 9 pre-refactor
# storage.yaml files (see podiumd.storagePVC) — a confirmed real dedup win —
# score ~0.82 against each other (differ only by the literal component
# name); the two Keycloak realm-import jobs — same Job skeleton, but
# genuinely different env/secret content, NOT worth forcing into one
# template — score ~0.63. HIGH sits between the two so the storage-file
# case is correctly flagged "likely worth deduping" and the Keycloak case
# stays "borderline".
DRY_SIMILARITY_THRESHOLD = 0.6
DRY_HIGH_SIMILARITY_THRESHOLD = 0.75
# Below this many significant lines, near-any two short templates look
# "similar" by line-ratio alone — not worth reporting as a candidate.
DRY_MIN_SIGNIFICANT_LINES = 8


def _significant_template_lines(path):
    """A template's lines with blanks and full-line comments dropped, so
    similarity scoring isn't skewed by incidental whitespace or comment
    wording differences between two otherwise-identical templates."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("{{/*"):
            continue
        lines.append(line)
    return lines


def find_similar_template_pairs(templates_dir):
    """Pairwise-compare every templates/*.yaml file and flag pairs that are
    structurally very similar — the shape of duplication podiumd.storagePVC
    was factored out of (9 files, identical except for the literal
    component name). Returns (ratio, path_a, path_b) tuples, highest ratio
    first, for every pair at or above DRY_SIMILARITY_THRESHOLD."""
    paths = sorted(p for p in templates_dir.rglob("*.yaml") if p.is_file())
    significant = {p: _significant_template_lines(p) for p in paths}
    candidates = [p for p in paths if len(significant[p]) >= DRY_MIN_SIGNIFICANT_LINES]

    findings = []
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            ratio = difflib.SequenceMatcher(None, significant[a], significant[b]).ratio()
            if ratio >= DRY_SIMILARITY_THRESHOLD:
                findings.append((ratio, a, b))
    findings.sort(key=lambda f: -f[0])
    return findings, len(candidates)


def check_dry(chart_dir):
    """Report-only: never fails. Flags templates/*.yaml file pairs that look
    like copy-paste duplication and suggests whether deduping (a shared
    named template in _helpers.tpl, parameterized like podiumd.storagePVC)
    is likely worth it, or just a coincidence of both files being short and
    conventionally shaped. Duplication is a judgment call a human should
    make — this only surfaces candidates."""
    findings, candidate_count = find_similar_template_pairs(chart_dir / "templates")

    if not findings:
        print(f"OK: no structurally-similar template pairs found "
              f"(compared {candidate_count} template(s) with "
              f">= {DRY_MIN_SIGNIFICANT_LINES} significant line(s))")
        return True, "0 candidate(s)"

    print(f"Found {len(findings)} structurally-similar template pair(s):")
    for ratio, a, b in findings:
        pct = round(ratio * 100)
        rel_a, rel_b = a.relative_to(chart_dir), b.relative_to(chart_dir)
        if ratio >= DRY_HIGH_SIMILARITY_THRESHOLD:
            advice = ("likely worth deduping — near-identical shape, probably just a "
                      "literal parameter (e.g. a component name) differs; consider a "
                      "shared named template in _helpers.tpl, as with podiumd.storagePVC")
        else:
            advice = ("borderline — inspect manually before deduping; could be a shared "
                      "skeleton with genuinely different content per file (e.g. different "
                      "env vars/secrets), where forcing a shared template would add more "
                      "parameters than it saves")
        print(f"  [{pct:3d}% similar] {rel_a}  <->  {rel_b}")
        print(f"      advice: {advice}")

    return True, f"{len(findings)} candidate(s) found (report-only, not a failure)"
