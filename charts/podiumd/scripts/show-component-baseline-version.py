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
import re
import subprocess
import sys
from pathlib import Path

import yaml

RELATIVE_CHART_DIR = "charts/podiumd"

# component (name or alias) -> dotted values.yaml path(s) for its own image
# block(s), for components that ship more than one image. Anything not
# listed here defaults to a single top-level "image" block — same
# convention as verify-component-version.py.
COMPONENT_IMAGE_PATHS = {
    "zgw-office-addin": ["frontend.image", "backend.image"],
}
DEFAULT_IMAGE_PATHS = ["image"]


def run(cmd):
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def find_repo_root():
    result = run(["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        raise SystemExit("error: not inside a git repository")
    return Path(result.stdout.strip())


def baseline_ref_candidates(baseline):
    """A bare version like "4.8.5" is resolved to the release tag first, then
    the (possibly not-yet-merged) feature branch. An explicit ref is used as-is."""
    if re.match(r"^\d+\.\d+\.\d+", baseline):
        return [f"podiumd-{baseline}", f"origin/feature/podiumd-{baseline}", f"feature/podiumd-{baseline}"]
    return [baseline]


def resolve_git_ref(repo_root, candidates):
    for ref in candidates:
        result = run(["git", "-C", str(repo_root), "rev-parse", "--verify", "-q", f"{ref}^{{commit}}"])
        if result.returncode == 0:
            return ref
    return None


def git_show_yaml(repo_root, ref, relpath):
    result = run(["git", "-C", str(repo_root), "show", f"{ref}:{relpath}"])
    if result.returncode != 0:
        return None
    return yaml.safe_load(result.stdout)


def find_dependency(deps, name_or_alias):
    for dep in deps:
        if dep["name"] == name_or_alias or dep.get("alias") == name_or_alias:
            return dep
    return None


def get_path(node, dotted_path):
    for key in dotted_path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def find_app_versions(values, values_key, image_paths):
    base = values.get(values_key, {}) if isinstance(values, dict) else {}
    versions = []
    for path in image_paths:
        tag = get_path(base, f"{path}.tag")
        if tag:
            versions.append((path, tag))
    return versions


def main():
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
    image_paths = COMPONENT_IMAGE_PATHS.get(component, DEFAULT_IMAGE_PATHS)
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
