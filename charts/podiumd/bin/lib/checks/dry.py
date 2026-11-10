"""Report-only scan for copy-paste duplication between templates/*.yaml files.

Never fails: deduping is a human judgment call.
"""

import difflib

from pathlib import Path

from lib.settings import dry_check_high_similarity_threshold
from lib.settings import dry_check_min_significant_lines
from lib.settings import dry_check_similarity_threshold


def _significant_template_lines(path: Path) -> list[str]:
    """A template's lines without blanks and full-line comments, so they don't skew similarity."""
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "{{/*")):
            continue
        lines.append(line)
    return lines


def find_similar_template_pairs(templates_dir: Path, similarity_threshold: float, min_significant_lines: int):
    """(ratio, path_a, path_b) for every template pair at or above `similarity_threshold`, highest first."""
    paths = sorted(path for path in templates_dir.rglob("*.yaml") if path.is_file())
    significant = {path: _significant_template_lines(path) for path in paths}
    candidates = [path for path in paths if len(significant[path]) >= min_significant_lines]

    findings: list[tuple[float, Path, Path]] = []
    for index, path_a in enumerate(candidates):
        for path_b in candidates[index + 1 :]:
            ratio = difflib.SequenceMatcher(None, significant[path_a], significant[path_b]).ratio()
            if ratio >= similarity_threshold:
                findings.append((ratio, path_a, path_b))
    findings.sort(key=lambda finding: -finding[0])
    return findings, len(candidates)


def check_dry(chart_dir: Path):
    """Report-only: flag similar template pairs and suggest whether a shared helper is worth it."""
    similarity_threshold = dry_check_similarity_threshold(chart_dir)
    high_similarity_threshold = dry_check_high_similarity_threshold(chart_dir)
    min_significant_lines = dry_check_min_significant_lines(chart_dir)

    findings, candidate_count = find_similar_template_pairs(
        chart_dir / "templates", similarity_threshold, min_significant_lines
    )

    if not findings:
        print(
            f"OK: no structurally-similar template pairs found "
            f"(compared {candidate_count} template(s) with "
            f">= {min_significant_lines} significant line(s))"
        )
        return True, "0 candidate(s)"

    print(f"Found {len(findings)} structurally-similar template pair(s):")
    for ratio, path_a, path_b in findings:
        pct = round(ratio * 100)
        rel_a, rel_b = path_a.relative_to(chart_dir), path_b.relative_to(chart_dir)
        if ratio >= high_similarity_threshold:
            advice = (
                "likely worth deduping — near-identical shape, probably just a "
                "literal parameter (e.g. a component name) differs; consider a "
                "shared named template in _helpers.tpl, as with podiumd.storagePVC"
            )
        else:
            advice = (
                "borderline — inspect manually before deduping; could be a shared "
                "skeleton with genuinely different content per file (e.g. different "
                "env vars/secrets), where forcing a shared template would add more "
                "parameters than it saves"
            )
        print(f"  [{pct:3d}% similar] {rel_a}  <->  {rel_b}")
        print(f"      advice: {advice}")

    return True, f"{len(findings)} candidate(s) found (report-only, not a failure)"
