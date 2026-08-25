#!/usr/bin/env python3
"""
Open a new podiumd release cycle: bump charts/podiumd/Chart.yaml's own
version/appVersion to the target named by the current branch, then scaffold
the upgrade-path docs for the outgoing version as the new baseline (runs
set-doc-baseline.py).

Reads everything from repo state — no arguments:
  - baseline: the chart's current version (Chart.yaml's "version:", before
    this script touches it) — the release being left behind.
  - target: parsed from the current branch name, which must be exactly
    "feature/podiumd-<MAJOR.MINOR.PATCH>" (this repo's branching
    convention — see README.md#branching-strategy).

Refuses to run if:
  - the branch name doesn't match that shape, or
  - the target isn't strictly newer than the baseline (a same-or-lower
    target would scaffold the upgrade docs backwards).

Usage:
    create-podiumd-version.py

Example:
    # on branch feature/podiumd-4.10.0, with Chart.yaml at version: 4.9.0
    create-podiumd-version.py
        # bumps Chart.yaml's version/appVersion 4.9.0 -> 4.10.0, then runs
        # set-doc-baseline.py 4.9.0
"""
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.chart import SEMVER_RE as CHART_VERSION_RE
from lib.chart import chart_version, replace_scalar_value
from lib.gitutil import current_branch, find_repo_root
from lib.procutil import run_script

CHART_DIR = SCRIPT_DIR.parent
CHART_YAML = CHART_DIR / "Chart.yaml"
SET_DOC_BASELINE_SCRIPT = SCRIPT_DIR / "set-doc-baseline.py"

BRANCH_RE = re.compile(r"^feature/podiumd-(\d+\.\d+\.\d+)$")


def current_chart_version():
    return chart_version(CHART_YAML)


def version_tuple(v):
    return tuple(int(part) for part in v.split("."))


def update_chart_version(new_version):
    """Bump Chart.yaml's top-level "version:" and "appVersion:" (this
    repo's own chart always keeps the two in lockstep — see git history of
    every prior release bump) to new_version. Returns the field names
    actually changed, in file order."""
    lines = CHART_YAML.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = []
    for i, line in enumerate(lines):
        if re.match(r"^version:\s", line):
            lines[i] = replace_scalar_value(line, new_version)
            changed.append("version")
        elif re.match(r"^appVersion:\s", line):
            lines[i] = replace_scalar_value(line, new_version)
            changed.append("appVersion")
    if "version" not in changed:
        raise SystemExit(f"error: could not find a top-level 'version:' line in {CHART_YAML}")
    CHART_YAML.write_text("".join(lines), encoding="utf-8")
    return changed


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) != 1:
        print(__doc__)
        sys.exit(1)

    repo_root = find_repo_root(CHART_DIR)
    if repo_root is None:
        print("error: not inside a git repository")
        sys.exit(1)

    branch = current_branch(repo_root)
    m = BRANCH_RE.match(branch)
    if not m:
        print(f"error: current branch '{branch or '(detached HEAD)'}' does not match "
              f"'feature/podiumd-<MAJOR.MINOR.PATCH>' — refusing to guess the target version")
        sys.exit(1)
    target = m.group(1)

    baseline = current_chart_version()
    if not CHART_VERSION_RE.match(baseline):
        print(f"error: {CHART_YAML}'s version '{baseline}' is not a plain MAJOR.MINOR.PATCH")
        sys.exit(1)

    if version_tuple(baseline) >= version_tuple(target):
        print(f"error: baseline {baseline} (Chart.yaml's current version) is not older than "
              f"target {target} (from the branch name) — refusing to open a version that isn't newer")
        sys.exit(1)

    changed = update_chart_version(target)
    print(f"{CHART_YAML.name}: {', '.join(changed)} {baseline} -> {target}")

    print()
    print(f"=== Running set-doc-baseline.py {baseline} ===")
    result = run_script([sys.executable, str(SET_DOC_BASELINE_SCRIPT), baseline])
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
