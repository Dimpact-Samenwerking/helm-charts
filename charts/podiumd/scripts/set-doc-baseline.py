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
    set-doc-baseline.py <new-baseline>

Example:
    set-doc-baseline.py 4.8.3
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

Also bumps docs/images/images-<target>.yaml the same way: its "Baseline:
podiumd X" and "podiumd <target> vs X" header lines, and any
"<baseline>-to-<target>-<suffix>.md" reference to the just-renamed docs.
If that manifest doesn't exist yet, a header-only stub (empty image list)
is created — entries are never invented, since there's nothing to derive
them from.

Finally, corrects the upgrade doc's "Component versions" table: for every
row matched to a Chart.yaml dependency, the target (right-hand) version is
read straight from the current Chart.yaml/values.yaml, and the source
(left-hand) version from <new-baseline>'s resolved git ref — replacing
whatever the table currently says with the actual versions at each end. A
row is only rewritten when both ends are independently verifiable (the
baseline must resolve to a real git ref, and the component must have
existed there); anything else is reported, not guessed at.
"""
import re
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.gitutil import baseline_ref_candidates, find_repo_root, git_show_yaml, resolve_git_ref
from lib.upgradedoc import actual_app_version, match_dependency, normalize_version, parse_upgrade_doc_rows

CHART_YAML = SCRIPT_DIR.parents[0] / "Chart.yaml"
VALUES_YAML = SCRIPT_DIR.parents[0] / "values.yaml"
DOC_DIR = SCRIPT_DIR.parents[0] / "docs" / "_UPGRADE_PATHS"
IMAGES_DIR = SCRIPT_DIR.parents[0] / "docs" / "images"


def current_chart_version():
    return str(yaml.safe_load(CHART_YAML.read_text(encoding="utf-8"))["version"])

FILENAME_RE_TMPL = r"^(?P<baseline>\d+\.\d+\.\d+)-to-{target}-(?P<suffix>[\w\-]+)\.md$"
TITLE_ARROW_RE_TMPL = r"(?P<baseline>{baseline})(?P<arrow>\s*(?:→|->)\s*){target}"
COMPONENT_VERSIONS_RE_TMPL = r"Component versions \({target}\s+vs\s+(?P<baseline>{baseline})\)"

# Same shape as verify-podiumd.py's SIBLING_DOC_RE/IMAGES_REF check — any
# reference to one of the just-renamed docs, whatever baseline it names.
SIBLING_DOC_RE_TMPL = r"(?P<baseline>\d+\.\d+\.\d+)-to-{target}-(?P<suffix>upgrade|gemeente-specific|values-deltas)\.md"
BASELINE_LINE_RE = re.compile(r"(?P<prefix>Baseline:\s*podiumd\s+)(?P<baseline>\d+\.\d+\.\d+)")
VS_LINE_RE_TMPL = r"(?P<prefix>podiumd\s+{target}\s+vs\s+)(?P<baseline>\d+\.\d+\.\d+)"

IMAGES_STUB_TEMPLATE = (
    "# Baseline: podiumd {baseline}. Re-verify before release.\n"
    "#\n"
    "# Images new or changed in podiumd {target} vs {baseline}.\n"
    "#\n"
    "# See docs/_UPGRADE_PATHS/{baseline}-to-{target}-upgrade.md for the operator upgrade notes.\n"
    "#\n"
    "# Digests are the OCI image index (multi-arch manifest) digest as returned in\n"
    "# the Docker-Content-Digest response header from the source registry.\n\n"
    "[]\n"
)

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


def images_manifest_path(target):
    return IMAGES_DIR / f"images-{target}.yaml"


def extract_images_baseline(text):
    """The version named on the "Baseline: podiumd X" line, or None if the
    manifest doesn't have one (malformed/legacy header)."""
    m = BASELINE_LINE_RE.search(text)
    return m.group("baseline") if m else None


def update_sibling_doc_refs(text, target, new_baseline):
    """Rewrite any "<some-baseline>-to-<target>-<suffix>.md" reference
    (whatever baseline it currently names) to the new baseline — these docs
    were just renamed. Returns (new_text, changed)."""
    pattern = re.compile(SIBLING_DOC_RE_TMPL.format(target=re.escape(target)))
    new_text, count = pattern.subn(lambda m: f"{new_baseline}-to-{target}-{m.group('suffix')}.md", text)
    return new_text, count > 0


def update_images_manifest_baseline(text, target, new_baseline):
    """Rewrite the "Baseline: podiumd X" and "podiumd <target> vs X" lines
    to the new baseline, whatever X currently is. Returns (new_text, changed)."""
    text, n1 = BASELINE_LINE_RE.subn(rf"\g<prefix>{new_baseline}", text)
    vs_pattern = re.compile(VS_LINE_RE_TMPL.format(target=re.escape(target)))
    text, n2 = vs_pattern.subn(rf"\g<prefix>{new_baseline}", text)
    return text, (n1 + n2) > 0


def load_target_state():
    chart_yaml = yaml.safe_load(CHART_YAML.read_text(encoding="utf-8"))
    values = yaml.safe_load(VALUES_YAML.read_text(encoding="utf-8")) or {}
    return chart_yaml.get("dependencies", []), values


def load_baseline_state(new_baseline):
    """(deps, values) as they were at new_baseline's resolved git ref, or
    (None, None) if it can't be resolved (e.g. that release hasn't been cut
    yet) — callers skip table-version correction gracefully in that case."""
    repo_root = find_repo_root(CHART_YAML.parent)
    if repo_root is None:
        return None, None
    ref = resolve_git_ref(repo_root, baseline_ref_candidates(new_baseline))
    if ref is None:
        return None, None
    rel_chart_dir = CHART_YAML.parent.relative_to(repo_root)
    baseline_chart_yaml = git_show_yaml(repo_root, ref, f"{rel_chart_dir}/Chart.yaml")
    if baseline_chart_yaml is None:
        return None, None
    baseline_values = git_show_yaml(repo_root, ref, f"{rel_chart_dir}/values.yaml") or {}
    return baseline_chart_yaml.get("dependencies", []), baseline_values


def canonical_version_cell(actual_source, actual_target):
    if normalize_version(actual_source) == normalize_version(actual_target):
        return f"{actual_target} (unchanged)"
    return f"{actual_source} → {actual_target}"


def fix_component_version_table(text, target_deps, target_values, baseline_deps, baseline_values):
    """Rewrite each "Component versions" table row's App/Helm-chart cells to
    the actual baseline (source) and target versions found in git/Chart.yaml/
    values.yaml. A row is only rewritten when both its source and target are
    independently verifiable; anything else is left as-is and reported.
    Returns (new_text, changed_rows, unmatched_names, unresolved_names)."""
    lines = text.splitlines(keepends=True)
    rows = parse_upgrade_doc_rows(text)
    changed_rows, unmatched_names, unresolved_names = [], [], []

    for row in rows:
        dep = match_dependency(row["name"], target_deps)
        if dep is None:
            unmatched_names.append(row["name"])
            continue
        values_key = dep.get("alias", dep["name"])
        actual_target_chart = str(dep["version"])
        actual_target_app = actual_app_version(target_values, values_key)

        baseline_dep = match_dependency(row["name"], baseline_deps) if baseline_deps else None
        if baseline_dep is None:
            unresolved_names.append(row["name"])
            continue
        actual_baseline_chart = str(baseline_dep["version"])
        actual_baseline_app = actual_app_version(baseline_values, values_key)

        row_changed = False
        line = lines[row["line_index"]]
        cells = [c.strip() for c in line.strip().strip("|").split("|")]

        if actual_target_app is not None and actual_baseline_app is not None and (
            normalize_version(row["app_source"]) != normalize_version(actual_baseline_app)
            or normalize_version(row["app"]) != normalize_version(actual_target_app)
        ):
            cells[1] = canonical_version_cell(actual_baseline_app, actual_target_app)
            row_changed = True

        if normalize_version(row["chart_source"]) != normalize_version(actual_baseline_chart) \
                or normalize_version(row["chart"]) != normalize_version(actual_target_chart):
            cells[2] = canonical_version_cell(actual_baseline_chart, actual_target_chart)
            row_changed = True

        if row_changed:
            suffix = "\n" if line.endswith("\n") else ""
            lines[row["line_index"]] = "| " + " | ".join(cells) + " |" + suffix
            changed_rows.append((row["name"], cells[1], cells[2]))

    return "".join(lines), changed_rows, unmatched_names, unresolved_names


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

    images_path = images_manifest_path(target)
    if not images_path.is_file():
        images_path.write_text(IMAGES_STUB_TEMPLATE.format(baseline=new_baseline, target=target),
                                encoding="utf-8")
        print(f"  {images_path.name}: created (was missing)")
    else:
        text = images_path.read_text(encoding="utf-8")
        old_images_baseline = extract_images_baseline(text)
        if old_images_baseline == new_baseline:
            print(f"  {images_path.name}: already baseline {new_baseline} — unchanged")
        else:
            text, refs_changed = update_sibling_doc_refs(text, target, new_baseline)
            text, baseline_changed = update_images_manifest_baseline(text, target, new_baseline)
            images_path.write_text(text, encoding="utf-8")
            print(f"  {images_path.name}: baseline updated")
            if refs_changed:
                print(f"    doc references -> {new_baseline}-to-{target}-*.md")
            if baseline_changed:
                print(f"    baseline header line(s): -> {new_baseline}")
            if old_images_baseline:
                leftovers = remaining_mentions(text, old_images_baseline)
                if leftovers:
                    review_notes.append((images_path.name, leftovers))

    upgrade_path = DOC_DIR / f"{new_baseline}-to-{target}-upgrade.md"
    if upgrade_path.is_file():
        target_deps, target_values = load_target_state()
        baseline_deps, baseline_values = load_baseline_state(new_baseline)
        text = upgrade_path.read_text(encoding="utf-8")
        new_text, changed_rows, unmatched_names, unresolved_names = fix_component_version_table(
            text, target_deps, target_values, baseline_deps, baseline_values
        )
        if changed_rows:
            upgrade_path.write_text(new_text, encoding="utf-8")
            print()
            print(f"=== Correcting component version table in {upgrade_path.name} ===")
            for name, app_cell, chart_cell in changed_rows:
                print(f"  {name}: app {app_cell}  |  chart {chart_cell}")
        if unresolved_names:
            print()
            print(f"Could not verify source version for: {', '.join(unresolved_names)}"
                  f" — baseline {new_baseline} doesn't resolve to a git ref, or the component "
                  f"didn't exist there yet. Table left as-is for these; review by hand.")
        if unmatched_names:
            print()
            print(f"Could not match to a Chart.yaml dependency, left as-is: {', '.join(unmatched_names)}")

    if review_notes:
        print()
        print("Review these lines by hand — old baseline text may remain in free-form prose:")
        for name, lines in review_notes:
            print(f"  {name}: line(s) {', '.join(map(str, lines))}")

    print()
    print(f"Done. Run verify-podiumd.py --baseline {new_baseline} to confirm consistency before committing.")


if __name__ == "__main__":
    main()
