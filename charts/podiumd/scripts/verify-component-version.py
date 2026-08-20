#!/usr/bin/env python3
"""
Verify that a component's target app image version(s) and Helm chart version
actually exist (published), BEFORE writing them into charts/podiumd/values.yaml
or Chart.yaml — a non-existent tag or chart version breaks image pulls /
`helm dependency update` at deploy time rather than at edit time.

Everything about the component is derived from the project rather than
hardcoded: which Helm repo it lives in and whether the chart version exists
comes from its charts/podiumd/Chart.yaml dependency entry (resolved and
pulled the same way as list-component-chart-images.py); the actual image
repository string comes from that chart's OWN values.yaml, and the registry
host is inferred from the repository string itself (standard Docker
convention — "ghcr.io/..." vs a bare "org/repo" implying Docker Hub).

The one thing that can't be derived automatically: a chart's values.yaml
mixes the app's own image with independently-versioned sidecars (ZAC alone
ships 10+ images — opa, solr, zookeeper, curl, gotenberg...), and nothing
in the chart says which one is "the app". COMPONENT_IMAGE_PATHS below is
that one small hint — just a values.yaml path, not a registry or repo — and
only needed for multi-image components; anything else defaults to the
top-level "image" block.

Usage:
    verify-component-version.py <component> <app-version> <chart-version>

Examples:
    verify-component-version.py zac 5.4.3 1.0.297
    verify-component-version.py zgw-office-addin 0.12.0 0.0.92
    verify-component-version.py openformulieren 3.5.6 1.12.0

Requires the Helm repositories to already be added (see /helm-repos or
charts/podiumd/scripts/add-helm-repos.sh) and the `helm` CLI on PATH.

Exit code is non-zero if either the app version or the chart version does not
exist — safe to use as a gate before bumping the chart.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.chart import chart_ref, get_path, pull_chart, pulled_chart_dir
from lib.chart import find_dependency as _find_dependency
from lib.registry import parse_repo, registry_tag_exists

CHART_YAML = SCRIPT_DIR.parents[0] / "Chart.yaml"

# component (name or alias) -> dotted values.yaml path(s) for its own image
# block(s), for components that ship more than one image that must move in
# lockstep. Anything not listed here defaults to a single top-level "image"
# block, which covers ordinary single-image components with no extra config.
COMPONENT_IMAGE_PATHS = {
    "zgw-office-addin": ["frontend.image", "backend.image"],
}
DEFAULT_IMAGE_PATHS = ["image"]


def find_dependency(name_or_alias):
    deps = yaml.safe_load(CHART_YAML.read_text())["dependencies"]
    dep = _find_dependency(deps, name_or_alias)
    if dep is None:
        raise SystemExit(f"error: no dependency named or aliased '{name_or_alias}' found in {CHART_YAML}")
    return dep


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    component, app_version, chart_version = sys.argv[1], sys.argv[2], sys.argv[3]

    dep = find_dependency(component)
    chart_name = dep["name"]

    tmpdir = Path(tempfile.mkdtemp(prefix="verify-component-version-"))
    try:
        print(f"Checking chart version {chart_version!r} for {chart_name}:")
        ok_chart, stderr = pull_chart(dep, chart_version, tmpdir)
        status = "FOUND  " if ok_chart else "MISSING"
        suffix = f"  ({stderr})" if not ok_chart else ""
        print(f"  [{status}] {chart_name} {chart_version}{suffix}")

        if not ok_chart:
            print()
            print("FAIL: chart version does not exist — cannot look up its image repositories")
            sys.exit(1)

        chart_dir = pulled_chart_dir(tmpdir)
        values = yaml.safe_load((chart_dir / "values.yaml").read_text()) or {}

        image_paths = COMPONENT_IMAGE_PATHS.get(component, DEFAULT_IMAGE_PATHS)
        repos = []
        for path in image_paths:
            repo = get_path(values, f"{path}.repository")
            if isinstance(repo, str) and repo:
                repos.append(repo)
        if not repos:
            print()
            print(f"FAIL: no repository found at {', '.join(image_paths)} in {chart_name}'s values.yaml "
                  f"— wrong path? see COMPONENT_IMAGE_PATHS")
            sys.exit(1)

        print(f"\nChecking app version {app_version!r} for {component}:")
        ok_images = True
        for repo in repos:
            host, repo_path = parse_repo(repo)
            exists, digest = registry_tag_exists(host, repo_path, app_version)
            status = "FOUND  " if exists else "MISSING"
            suffix = f"  digest={digest}" if digest else ""
            print(f"  [{status}] {host}/{repo_path}:{app_version}{suffix}")
            ok_images = ok_images and exists

        print()
        print("OK: both exist" if ok_images else "FAIL: one or more app image versions do not exist yet")
        sys.exit(0 if ok_images else 1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
