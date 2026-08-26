#!/usr/bin/env python3
"""
Verify that a component's target app image version(s) actually exist
(published), BEFORE writing them into charts/podiumd/values.yaml — a
non-existent tag breaks image pulls at deploy time rather than at edit
time. The repository and registry host are derived from the TARGET chart
version's own values.yaml (pulled fresh — a version bump can add a new
sidecar or move a repository path); the one thing that can't be derived is
which of a multi-image chart's images (e.g. ZAC's 10+ sidecars) is "the
app" — see lib.chart.COMPONENT_IMAGE_PATHS.

This is why <chart-version> is still required here even though this
script only checks the APP version: without pulling that specific chart
version there's no way to know which repository to check at all. See
verify-helmchart-version.py for checking the chart version on its own.

Usage:
    verify-image-version.py <component> <app-version> <chart-version>

Examples:
    verify-image-version.py zac 5.4.3 1.0.297
    verify-image-version.py zgw-office-addin 0.12.0 0.0.92
    verify-image-version.py openformulieren 3.5.6 1.12.0

Requires the Helm repositories to already be added (see /helm-repos or
charts/podiumd/scripts/add-helm-repos.sh) and the `helm` CLI on PATH.

Exit code is non-zero if the chart version can't even be pulled, or if
any of the component's app image versions do not exist yet — safe to use
as a gate before bumping values.yaml.
"""
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.chart import check_image_versions, image_paths_for, pull_chart_values
from lib.chart import find_dependency as _find_dependency

CHART_YAML = SCRIPT_DIR.parents[0] / "Chart.yaml"


def find_dependency(name_or_alias):
    deps = yaml.safe_load(CHART_YAML.read_text())["dependencies"]
    dep = _find_dependency(deps, name_or_alias)
    if dep is None:
        raise SystemExit(f"error: no dependency named or aliased '{name_or_alias}' found in {CHART_YAML}")
    return dep


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    component, app_version, chart_version = sys.argv[1], sys.argv[2], sys.argv[3]

    dep = find_dependency(component)
    values = pull_chart_values(dep, chart_version)
    results = check_image_versions(values, image_paths_for(component), app_version)

    print(f"Checking app version {app_version!r} for {component} (chart {chart_version}):")
    ok = True
    for r in results:
        status = "FOUND  " if r["exists"] else "MISSING"
        suffix = f"  digest={r['digest']}" if r["digest"] else ""
        print(f"  [{status}] {r['host']}/{r['repo_path']}:{app_version}{suffix}")
        ok = ok and r["exists"]

    print()
    print("OK: image version(s) exist" if ok else "FAIL: one or more app image versions do not exist yet")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
