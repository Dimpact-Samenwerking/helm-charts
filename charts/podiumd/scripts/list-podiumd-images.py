#!/usr/bin/env python3
"""
List every container image (repository + tag) actually configured for the
podiumd chart: for each Chart.yaml dependency, the sub-chart's default
values.yaml merged with podiumd's own overrides in values.yaml, plus any
images configured directly at the top level of podiumd's own values.yaml.

Usage:
    list-podiumd-images.py [--refresh]

    --refresh   Ignore locally vendored charts/podiumd/charts/*.tgz and
                always `helm pull` the pinned version instead.

Requires the Helm repositories to already be added (see /helm-repos or
charts/podiumd/scripts/add-helm-repos.sh) and the `helm` CLI on PATH, unless
every dependency is already vendored locally (e.g. after `helm dependency
update`), in which case no network access is needed at all.
"""
import subprocess
import sys
import tempfile
import shutil
import tarfile
from pathlib import Path

import yaml

PODIUMD_DIR = Path(__file__).resolve().parents[1]
CHART_YAML = PODIUMD_DIR / "Chart.yaml"
VALUES_YAML = PODIUMD_DIR / "values.yaml"
VENDORED_DIR = PODIUMD_DIR / "charts"


def chart_ref(dep):
    repo = dep["repository"]
    if repo.startswith("oci://"):
        return f"{repo}/{dep['name']}", None
    if repo.startswith("@"):
        return f"{repo[1:]}/{dep['name']}", None
    if repo.startswith("http://") or repo.startswith("https://"):
        return dep["name"], repo
    if repo.startswith("file://"):
        return None, None
    raise SystemExit(f"error: unsupported repository scheme: {repo}")


def pull_chart(dep, dest):
    ref, repo_url = chart_ref(dep)
    if ref is None:
        raise SystemExit(
            f"error: dependency '{dep['name']}' uses a local path repository "
            f"({dep['repository']}) and is not vendored locally; cannot fetch it remotely"
        )
    cmd = ["helm", "pull", ref, "--version", dep["version"], "--untar", "--untardir", str(dest)]
    if repo_url:
        cmd += ["--repo", repo_url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"error: helm pull failed for {ref}@{dep['version']}\n{result.stderr.strip()}")


def load_chart(dep, tmproot, refresh):
    vendored = VENDORED_DIR / f"{dep['name']}-{dep['version']}.tgz"
    if not refresh and vendored.exists():
        dest = tmproot / dep["name"]
        dest.mkdir()
        with tarfile.open(vendored) as tf:
            tf.extractall(dest)
    else:
        dest = tmproot / dep["name"]
        dest.mkdir()
        pull_chart(dep, dest)

    chart_dirs = [p for p in dest.iterdir() if p.is_dir()]
    if not chart_dirs:
        raise SystemExit(f"error: no chart directory found for {dep['name']}")
    chart_dir = chart_dirs[0]

    chart_yaml = yaml.safe_load((chart_dir / "Chart.yaml").read_text())
    values_path = chart_dir / "values.yaml"
    values = yaml.safe_load(values_path.read_text()) if values_path.exists() else {}
    return chart_yaml, values or {}


def deep_merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(base.get(key), value)
        return merged
    return override if override is not None else base


def version_of(tag):
    return tag.split("@", 1)[0]


def find_images(node, path=""):
    images = []
    if isinstance(node, dict):
        if "repository" in node and "tag" in node:
            repo, tag = node["repository"], node["tag"]
            if repo and tag not in (None, ""):
                images.append((path or "(root)", repo, tag))
        for key, value in node.items():
            images.extend(find_images(value, f"{path}.{key}" if path else key))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            images.extend(find_images(item, f"{path}[{i}]"))
    return images


def is_enabled(condition, root_values):
    if not condition:
        return True
    node = root_values
    for part in condition.split("."):
        if not isinstance(node, dict) or part not in node:
            return True  # no explicit override; assume chart default (enabled)
        node = node[part]
    return bool(node)


def main():
    refresh = "--refresh" in sys.argv[1:]

    deps = yaml.safe_load(CHART_YAML.read_text())["dependencies"]
    root_values = yaml.safe_load(VALUES_YAML.read_text()) or {}
    dep_keys = {dep.get("alias", dep["name"]) for dep in deps}

    tmproot = Path(tempfile.mkdtemp(prefix="list-podiumd-images-"))
    try:
        # Top-level values not tied to any dependency (e.g. global.images.*)
        top_level_images = []
        for key, value in root_values.items():
            if key not in dep_keys:
                top_level_images.extend(find_images(value, key))
        if top_level_images:
            print("=== podiumd top-level values (not part of a dependency) ===")
            width = max(len(p) for p, _, _ in top_level_images)
            vwidth = max(len(version_of(t)) for _, _, t in top_level_images)
            for path, repo, tag in sorted(top_level_images):
                print(f"  {path.ljust(width)}  {version_of(tag).ljust(vwidth)}  {repo}:{tag}")
            print()

        for dep in deps:
            key = dep.get("alias", dep["name"])
            enabled = is_enabled(dep.get("condition"), root_values)
            status = "" if enabled else "  [disabled]"
            print(f"=== {key} ({dep['name']} {dep['version']}){status} ===")

            try:
                chart_yaml, defaults = load_chart(dep, tmproot, refresh)
            except SystemExit as e:
                print(f"  {e}\n")
                continue

            print(f"  appVersion: {chart_yaml.get('appVersion', 'n/a')}")

            sub_deps = chart_yaml.get("dependencies", [])
            if sub_deps:
                print("  sub-chart dependencies:")
                for d in sub_deps:
                    print(f"    - {d['name']}: {d['version']}")

            overrides = root_values.get(key, {})
            merged = deep_merge(defaults, overrides)
            images = find_images(merged)
            if images:
                width = max(len(p) for p, _, _ in images)
                vwidth = max(len(version_of(t)) for _, _, t in images)
                for path, repo, tag in sorted(images):
                    print(f"  {path.ljust(width)}  {version_of(tag).ljust(vwidth)}  {repo}:{tag}")
            else:
                print("  (no image references found)")
            print()
    finally:
        shutil.rmtree(tmproot, ignore_errors=True)


if __name__ == "__main__":
    main()
