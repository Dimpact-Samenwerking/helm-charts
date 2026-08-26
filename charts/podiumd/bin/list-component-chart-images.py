#!/usr/bin/env python3
"""
List every container image (repository + tag) and every sub-chart dependency
declared by a podiumd dependency chart, at a given chart version.

Usage:
    list-component-chart-images.py <chart-name-or-alias> <chart-version>

Examples:
    list-component-chart-images.py zac 1.0.297
    list-component-chart-images.py zaakafhandelcomponent 1.0.297
    list-component-chart-images.py zgw-office-addin 0.0.92

Requires the Helm repositories to already be added (see /helm-repos or
charts/podiumd/scripts/add-helm-repos.sh) and the `helm` CLI on PATH.
"""
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.chart import find_dependency as _find_dependency
from lib.chart import find_images, version_of

CHART_YAML = SCRIPT_DIR.parents[0] / "Chart.yaml"


def find_dependency(name_or_alias):
    deps = yaml.safe_load(CHART_YAML.read_text())["dependencies"]
    dep = _find_dependency(deps, name_or_alias)
    if dep is None:
        raise SystemExit(f"error: no dependency named or aliased '{name_or_alias}' found in {CHART_YAML}")
    return dep


def chart_ref(dep):
    repo = dep["repository"]
    if repo.startswith("oci://"):
        return f"{repo}/{dep['name']}"
    if repo.startswith("@"):
        return f"{repo[1:]}/{dep['name']}"
    raise SystemExit(f"error: unsupported repository scheme: {repo}")


def pull_chart(ref, version, dest):
    cmd = ["helm", "pull", ref, "--version", version, "--untar", "--untardir", str(dest)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"error: helm pull failed for {ref}@{version}\n{result.stderr.strip()}"
        )


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    name_or_alias, version = sys.argv[1], sys.argv[2]
    dep = find_dependency(name_or_alias)
    ref = chart_ref(dep)

    tmpdir = Path(tempfile.mkdtemp(prefix="list-component-chart-images-"))
    try:
        print(f"Pulling {ref} @ {version} ...")
        pull_chart(ref, version, tmpdir)

        chart_dirs = [p for p in tmpdir.iterdir() if p.is_dir()]
        if not chart_dirs:
            raise SystemExit("error: helm pull produced no chart directory")
        chart_dir = chart_dirs[0]

        chart_yaml = yaml.safe_load((chart_dir / "Chart.yaml").read_text())
        values_yaml = yaml.safe_load((chart_dir / "values.yaml").read_text()) or {}

        print(f"\nChart: {chart_yaml['name']} {chart_yaml['version']} "
              f"(appVersion: {chart_yaml.get('appVersion', 'n/a')})")

        sub_deps = chart_yaml.get("dependencies", [])
        if sub_deps:
            print("\nSub-chart dependencies:")
            for d in sub_deps:
                print(f"  - {d['name']}: {d['version']}")

        images = find_images(values_yaml)
        if images:
            print("\nImage references:")
            width = max(len(path) for path, _, _ in images)
            vwidth = max(len(version_of(tag)) for _, _, tag in images)
            for path, repo, tag in sorted(images):
                print(f"  {path.ljust(width)}  {version_of(tag).ljust(vwidth)}  {repo}:{tag}")
        else:
            print("\nNo image references found in values.yaml")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
