#!/usr/bin/env python3
"""
List every container image (repository + tag) and every sub-chart dependency
declared by a podiumd dependency chart, at a given chart version.

Usage:
    list-helmchart-images.py <chart-name-or-alias> <chart-version>

Examples:
    list-helmchart-images.py zac 1.0.297
    list-helmchart-images.py zaakafhandelcomponent 1.0.297
    list-helmchart-images.py zgw-office-addin 0.0.92
    list-helmchart-images.py mi-data 1.0.0
        # mi-data (and any other "file://" local-path dependency) is read
        # straight from its own source directory instead of being pulled —
        # `helm pull` has no way to fetch a local relative path at all, and
        # a local dependency only ever has ONE real version: whatever's
        # currently checked out there. <chart-version> is still required
        # for a consistent CLI, but only used to warn if it doesn't match.

Requires the Helm repositories to already be added (see /helm-repos or
charts/podiumd/scripts/add-helm-repos.sh) and the `helm` CLI on PATH.
"""
import sys
import tempfile
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.chart import chart_ref, find_images, load_yaml, pull_chart, pulled_chart_dir, version_of
from lib.chart import find_dependency as _find_dependency

CHART_DIR = SCRIPT_DIR.parents[0]
CHART_YAML = CHART_DIR / "Chart.yaml"


def find_dependency(name_or_alias):
    deps = load_yaml(CHART_YAML)["dependencies"]
    dep = _find_dependency(deps, name_or_alias)
    if dep is None:
        raise SystemExit(f"error: no dependency named or aliased '{name_or_alias}' found in {CHART_YAML}")
    return dep


def local_chart_dir(dep):
    """The directory a "file://..." dependency's own repository actually
    points at, resolved relative to CHART_DIR (Helm's own convention for
    local path dependencies) — None for any other repository scheme."""
    repo = dep["repository"]
    if not repo.startswith("file://"):
        return None
    return (CHART_DIR / repo[len("file://"):]).resolve()


def report_chart(chart_dir, requested_version):
    chart_yaml = load_yaml(chart_dir / "Chart.yaml")
    values_yaml = load_yaml(chart_dir / "values.yaml") or {}

    actual_version = str(chart_yaml["version"])
    if actual_version != requested_version:
        print(f"note: {chart_dir} is actually version {actual_version!r}, "
              f"not the requested {requested_version!r}", file=sys.stderr)

    print(f"\nChart: {chart_yaml['name']} {actual_version} "
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


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    name_or_alias, version = sys.argv[1], sys.argv[2]
    dep = find_dependency(name_or_alias)

    local_dir = local_chart_dir(dep)
    if local_dir is not None:
        if not local_dir.is_dir():
            raise SystemExit(f"error: dependency '{dep['name']}' declares local path repository "
                              f"({dep['repository']}), but {local_dir} does not exist")
        print(f"Reading local chart source: {local_dir}")
        report_chart(local_dir, version)
        return

    tmpdir = Path(tempfile.mkdtemp(prefix="list-helmchart-images-"))
    try:
        ref, _ = chart_ref(dep)
        print(f"Pulling {ref} @ {version} ...")
        ok, stderr = pull_chart(dep, version, tmpdir)
        if not ok:
            raise SystemExit(f"error: helm pull failed for {ref}@{version}\n{stderr}")
        report_chart(pulled_chart_dir(tmpdir), version)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
