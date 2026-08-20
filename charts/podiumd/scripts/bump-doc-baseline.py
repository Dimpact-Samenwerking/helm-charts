#!/usr/bin/env python3
"""
Bump the baseline of every docs/_UPGRADE_PATHS/<baseline>-to-<target>-*.md
doc for the current chart's target version to a new baseline — e.g. rename
"4.8.2-to-4.9.0-upgrade.md" to "4.8.3-to-4.9.0-upgrade.md" (and its
"gemeente-specific"/"values-deltas" siblings), updating each doc's title
line to match.

The target version is always charts/podiumd/Chart.yaml's own "version:" —
same as verify-podiumd.py's docs-consistency check — not a parameter,
since these docs only ever exist for a hop landing on the current chart.

Usage:
    bump-doc-baseline.py <new-baseline>

Example:
    bump-doc-baseline.py 4.8.3
        # if Chart.yaml's version is 4.9.0, renames *-to-4.9.0-*.md

For each doc file matching "<some-baseline>-to-<target>-<suffix>.md":
  - git-mv it to "<new-baseline>-to-<target>-<suffix>.md" (a no-op, reported
    as unchanged, if it's already at new-baseline)
  - update its title line (line 1) baseline -> new-baseline
  - update a "Component versions (<target> vs <old-baseline>)" heading, if
    present, the same way

Refuses to touch anything and exits non-zero if two or more source files
would collide on the same "<suffix>.md" destination — e.g. both a
"4.8.2-to-4.9.0-upgrade.md" and a "4.8.3-to-4.9.0-upgrade.md" already
existing side by side. All-or-nothing: either every rename in the batch
happens, or none do.

If the target has no docs at all yet, or is only missing one of the three
standard docs (upgrade / gemeente-specific / values-deltas), the missing
one(s) are created fresh at "<new-baseline>-to-<target>-<suffix>.md" as
minimal TODO stubs — no content is invented, since nothing exists yet to
derive it from.

Any other mention of the old baseline in a doc's free-form prose (e.g.
"already on **4.8.2**") is NOT rewritten automatically — those lines are
listed at the end for manual review, since blind find/replace on prose
risks corrupting unrelated text that happens to contain the same version
string.
"""
import re
import subprocess
import sys
from pathlib import Path

import yaml

CHART_YAML = Path(__file__).resolve().parents[1] / "Chart.yaml"
DOC_DIR = Path(__file__).resolve().parents[1] / "docs" / "_UPGRADE_PATHS"


def current_chart_version():
    return str(yaml.safe_load(CHART_YAML.read_text(encoding="utf-8"))["version"])

FILENAME_RE_TMPL = r"^(?P<baseline>\d+\.\d+\.\d+)-to-{target}-(?P<suffix>[\w\-]+)\.md$"
TITLE_ARROW_RE_TMPL = r"(?P<baseline>{baseline})(?P<arrow>\s*(?:→|->)\s*){target}"
COMPONENT_VERSIONS_RE_TMPL = r"Component versions \({target}\s+vs\s+(?P<baseline>{baseline})\)"

# The three docs verify-podiumd.py's check_baseline_doc_set expects for
# every target — missing ones are created as stubs, not just renamed.
STANDARD_SUFFIXES = ("upgrade", "gemeente-specific", "values-deltas")

STUB_TEMPLATES = {
    "upgrade": (
        "# Upgrade guide: PodiumD {baseline} → {target}\n\n"
        "> See the Confluence Releases page for the agreed application\n"
        "> targets: <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.\n\n"
        "TODO: describe this hop's changes.\n\n"
        "## Component versions ({target} vs {baseline})\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n\n"
        "TODO\n"
    ),
    "gemeente-specific": (
        "# Gemeente-specific notes — PodiumD {baseline} → {target}\n\n"
        "Findings for this hop that apply to a **specific gemeente or environment** —\n"
        "not to the release in general — are collected here: data quirks, local\n"
        "overrides, hosting particulars, incident follow-ups.\n\n"
        "_None recorded yet._\n\n"
        "<!-- Add entries per gemeente/environment:\n\n"
        "## <gemeente> (<env>)\n\n"
        "- What was hit, why it is specific to this environment, and the\n"
        "  fix/workaround applied.\n"
        "-->\n"
    ),
    "values-deltas": (
        "# Values deltas — PodiumD {baseline} → {target}\n\n"
        "TODO: describe any gemeente `podiumd.yml` changes required for this hop.\n"
    ),
}


def find_target_docs(target):
    """Return {suffix: (baseline, path)} for every doc matching
    "<baseline>-to-<target>-<suffix>.md" in DOC_DIR."""
    pattern = re.compile(FILENAME_RE_TMPL.format(target=re.escape(target)))
    by_suffix = {}
    for path in DOC_DIR.glob(f"*-to-{target}-*.md"):
        m = pattern.match(path.name)
        if not m:
            continue
        by_suffix.setdefault(m.group("suffix"), []).append((m.group("baseline"), path))
    return by_suffix


def find_collisions(by_suffix):
    """suffix -> [(baseline, path), ...] for every suffix with more than one
    source file — these would collide on the same rename destination."""
    return {suffix: entries for suffix, entries in by_suffix.items() if len(entries) > 1}


def git_mv(src, dst):
    result = subprocess.run(["git", "mv", str(src), str(dst)], cwd=src.parent, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"error: git mv {src} -> {dst} failed: {result.stderr.strip()}")


def update_title_line(text, old_baseline, target, new_baseline):
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


def update_component_versions_heading(text, old_baseline, target, new_baseline):
    """Replace a "Component versions (<target> vs <old_baseline>)" heading
    anywhere in the body, if present. Returns (new_text, changed)."""
    pattern = re.compile(COMPONENT_VERSIONS_RE_TMPL.format(baseline=re.escape(old_baseline), target=re.escape(target)))
    new_text, count = pattern.subn(f"Component versions ({target} vs {new_baseline})", text)
    return new_text, count > 0


def remaining_mentions(text, old_baseline):
    """Line numbers (1-indexed) where old_baseline still appears, for a
    manual-review reminder — every match, not just ones already handled."""
    return [i + 1 for i, line in enumerate(text.splitlines()) if old_baseline in line]


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    new_baseline = sys.argv[1]
    target = current_chart_version()

    by_suffix = find_target_docs(target)

    collisions = find_collisions(by_suffix)
    if collisions:
        print(f"error: multiple source docs would collide on the same target for '{target}':")
        for suffix, entries in sorted(collisions.items()):
            print(f"  {suffix}:")
            for baseline, path in sorted(entries):
                print(f"    {path.name}  (baseline {baseline})")
        print()
        print("Refusing to rename anything — resolve the collision above first.")
        sys.exit(1)

    print(f"=== Bumping baseline for target {target} to {new_baseline} ===")
    review_notes = []
    all_suffixes = sorted(set(by_suffix) | set(STANDARD_SUFFIXES))
    for suffix in all_suffixes:
        if suffix not in by_suffix:
            new_name = f"{new_baseline}-to-{target}-{suffix}.md"
            new_path = DOC_DIR / new_name
            new_path.write_text(STUB_TEMPLATES[suffix].format(baseline=new_baseline, target=target),
                                 encoding="utf-8")
            print(f"  {new_name}: created (was missing)")
            continue

        [(old_baseline, path)] = by_suffix[suffix]
        if old_baseline == new_baseline:
            print(f"  {path.name}: already baseline {new_baseline} — unchanged")
            continue

        new_name = f"{new_baseline}-to-{target}-{suffix}.md"
        new_path = DOC_DIR / new_name
        text = path.read_text(encoding="utf-8")

        text, title_changed = update_title_line(text, old_baseline, target, new_baseline)
        text, heading_changed = update_component_versions_heading(text, old_baseline, target, new_baseline)

        if path != new_path:
            git_mv(path, new_path)
        new_path.write_text(text, encoding="utf-8")

        print(f"  {path.name} -> {new_name}")
        if title_changed:
            print(f"    title line: {old_baseline} -> {new_baseline}")
        if heading_changed:
            print(f"    'Component versions' heading: {old_baseline} -> {new_baseline}")

        leftovers = remaining_mentions(text, old_baseline)
        if leftovers:
            review_notes.append((new_name, leftovers))

    if review_notes:
        print()
        print("Review these lines by hand — old baseline text may remain in free-form prose:")
        for name, lines in review_notes:
            print(f"  {name}: line(s) {', '.join(map(str, lines))}")

    print()
    print(f"Done. Run verify-podiumd.py --baseline {new_baseline} to confirm consistency before committing.")


if __name__ == "__main__":
    main()
