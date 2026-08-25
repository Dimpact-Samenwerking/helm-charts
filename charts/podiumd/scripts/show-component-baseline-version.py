#!/usr/bin/env python3
"""
Show the Helm chart version and app image version(s) pinned for a podiumd
component at a given baseline podiumd release — useful for finding out what
a release actually shipped before writing an upgrade doc's "source" column,
without checking out that release or digging through git history by hand.

Usage:
    show-component-baseline-version.py <component> <baseline>

Examples:
    show-component-baseline-version.py zac 4.8.5
    show-component-baseline-version.py zgw-office-addin 4.8.5
    show-component-baseline-version.py openformulieren 4.8.5

<baseline> is a bare version (e.g. "4.8.5"), resolved to the podiumd-4.8.5
git tag, falling back to the feature/podiumd-4.8.5 / origin/feature/podiumd-
4.8.5 branch if the tag doesn't exist yet — or an explicit git ref, used
as-is. Reads charts/podiumd/Chart.yaml + values.yaml as they were at that
ref via `git show` — no checkout needed.
"""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.chart import find_dependency, get_path, image_paths_for
from lib.gitutil import baseline_ref_candidates, git_show_yaml, resolve_git_ref
from lib.gitutil import find_repo_root as _find_repo_root

RELATIVE_CHART_DIR = "charts/podiumd"


def find_repo_root():
    repo_root = _find_repo_root(Path(__file__).resolve().parent)
    if repo_root is None:
        raise SystemExit("error: not inside a git repository")
    return repo_root


def find_app_versions(values, values_key, image_paths):
    base = values.get(values_key, {}) if isinstance(values, dict) else {}
    versions = []
    for path in image_paths:
        tag = get_path(base, f"{path}.tag")
        if tag:
            versions.append((path, tag))
    return versions


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    component, baseline = sys.argv[1], sys.argv[2]

    repo_root = find_repo_root()
    candidates = baseline_ref_candidates(baseline)
    ref = resolve_git_ref(repo_root, candidates)
    if not ref:
        print(f"error: could not resolve baseline '{baseline}' to a git ref "
              f"(tried {', '.join(candidates)})")
        sys.exit(1)

    chart_yaml = git_show_yaml(repo_root, ref, f"{RELATIVE_CHART_DIR}/Chart.yaml")
    if chart_yaml is None:
        print(f"error: could not read {RELATIVE_CHART_DIR}/Chart.yaml at {ref}")
        sys.exit(1)
    values = git_show_yaml(repo_root, ref, f"{RELATIVE_CHART_DIR}/values.yaml") or {}

    dep = find_dependency(chart_yaml.get("dependencies", []), component)
    if not dep:
        print(f"error: no dependency named or aliased '{component}' "
              f"in {RELATIVE_CHART_DIR}/Chart.yaml at {ref}")
        sys.exit(1)

    values_key = dep.get("alias", dep["name"])
    image_paths = image_paths_for(component)
    app_versions = find_app_versions(values, values_key, image_paths)

    print(f"Component: {component} (Chart.yaml dependency: {dep['name']}, values key: {values_key})")
    print(f"Baseline: {baseline} (resolved to {ref})")
    print(f"Helm chart version: {dep['version']}")
    if app_versions:
        print("App version(s):")
        for label, tag in app_versions:
            version = tag.split("@", 1)[0]
            print(f"  {label}: {version}  ({tag})")
    else:
        print(f"App version: no tag override found at {', '.join(image_paths)} "
              f"under '{values_key}:' — chart default applies")


if __name__ == "__main__":
    main()
