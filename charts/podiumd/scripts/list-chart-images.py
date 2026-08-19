#!/usr/bin/env python3
"""
List every container image (repository + tag) and every sub-chart dependency
declared by a podiumd dependency chart, at a given chart version.

Usage:
    list-chart-images.py <chart-name-or-alias> <chart-version>

Examples:
    list-chart-images.py zac 1.0.297
    list-chart-images.py zaakafhandelcomponent 1.0.297
    list-chart-images.py zgw-office-addin 0.0.92

Requires the Helm repositories to already be added (see /helm-repos or
charts/podiumd/scripts/add-helm-repos.sh) and the `helm` CLI on PATH.
"""
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

import yaml

CHART_YAML = Path(__file__).resolve().parents[1] / "Chart.yaml"


def find_dependency(name_or_alias):
    deps = yaml.safe_load(CHART_YAML.read_text())["dependencies"]
    for dep in deps:
        if dep["name"] == name_or_alias or dep.get("alias") == name_or_alias:
            return dep
    raise SystemExit(
        f"error: no dependency named or aliased '{name_or_alias}' found in {CHART_YAML}"
    )


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


def version_of(tag):
    return tag.split("@", 1)[0]


def find_images(node, path=""):
    """Recursively walk a parsed values.yaml tree, yielding (path, repository, tag)
    for every dict that has both a 'repository' and a 'tag' key."""
    images = []
    if isinstance(node, dict):
        if "repository" in node and "tag" in node:
            repo = node["repository"]
            tag = node["tag"]
            if repo and tag not in (None, ""):
                images.append((path or "(root)", repo, tag))
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else key
            images.extend(find_images(value, child_path))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            images.extend(find_images(item, f"{path}[{i}]"))
    return images


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    name_or_alias, version = sys.argv[1], sys.argv[2]
    dep = find_dependency(name_or_alias)
    ref = chart_ref(dep)

    tmpdir = Path(tempfile.mkdtemp(prefix="list-chart-images-"))
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
