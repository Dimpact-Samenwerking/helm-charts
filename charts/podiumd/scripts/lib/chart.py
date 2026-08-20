"""Chart.yaml/values.yaml helpers shared by every script that resolves a
podiumd dependency, pulls a specific chart version, or walks a values tree
for image references."""
import shutil
import tempfile
from pathlib import Path

import yaml

from lib.procutil import run


def get_path(node, dotted_path):
    for key in dotted_path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def find_dependency(deps, name_or_alias):
    """The Chart.yaml dependency entry matching this name or alias, or None
    if there isn't one — pure lookup, no I/O; callers load `deps` themselves
    (usually `chart_yaml["dependencies"]`) and decide how to report a miss."""
    for dep in deps:
        if dep["name"] == name_or_alias or dep.get("alias") == name_or_alias:
            return dep
    return None


def chart_ref(dep):
    """Return (ref, extra_repo_url_or_None) for `helm pull`, or (None, None)
    for a local path repository ("file://...") that must already be
    vendored — it has no remote to pull from."""
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


def pull_chart(dep, version, dest):
    """Pull a chart version via helm. Returns (ok, stderr)."""
    ref, repo_url = chart_ref(dep)
    if ref is None:
        return False, (f"dependency '{dep['name']}' uses a local path repository "
                        f"({dep['repository']}) — not fetchable remotely")
    cmd = ["helm", "pull", ref, "--version", version, "--untar", "--untardir", str(dest)]
    if repo_url:
        cmd += ["--repo", repo_url]
    result = run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stderr.strip()


def pulled_chart_dir(tmpdir):
    """The single chart directory `helm pull --untar` produced under tmpdir."""
    chart_dirs = [p for p in Path(tmpdir).iterdir() if p.is_dir()]
    if not chart_dirs:
        raise SystemExit(f"error: helm pull produced no chart directory in {tmpdir}")
    return chart_dirs[0]


def pull_chart_values(dep, version):
    """Pull a chart version into a throwaway temp dir and return its own
    values.yaml (parsed), cleaning up afterward. Raises SystemExit if the
    pull fails."""
    tmpdir = Path(tempfile.mkdtemp(prefix="pull-chart-values-"))
    try:
        ok, stderr = pull_chart(dep, version, tmpdir)
        if not ok:
            raise SystemExit(f"error: could not pull {dep['name']} {version}: {stderr}")
        chart_dir = pulled_chart_dir(tmpdir)
        return yaml.safe_load((chart_dir / "values.yaml").read_text()) or {}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def version_of(tag):
    return tag.split("@", 1)[0]


def find_images(node, path=""):
    """Recursively walk a parsed values.yaml tree, yielding (path, repository,
    tag) for every dict that has both a "repository" and a "tag" key."""
    images = []
    if isinstance(node, dict):
        if "repository" in node and "tag" in node:
            repo, tag = node["repository"], node["tag"]
            if repo and tag not in (None, ""):
                images.append((path or "(root)", repo, tag))
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else key
            images.extend(find_images(value, child_path))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            images.extend(find_images(item, f"{path}[{i}]"))
    return images
