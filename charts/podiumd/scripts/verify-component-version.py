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
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import yaml

CHART_YAML = Path(__file__).resolve().parents[1] / "Chart.yaml"

# component (name or alias) -> dotted values.yaml path(s) for its own image
# block(s), for components that ship more than one image that must move in
# lockstep. Anything not listed here defaults to a single top-level "image"
# block, which covers ordinary single-image components with no extra config.
COMPONENT_IMAGE_PATHS = {
    "zgw-office-addin": ["frontend.image", "backend.image"],
}
DEFAULT_IMAGE_PATHS = ["image"]

MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.docker.distribution.manifest.v2+json"
)

# Registries needing an anonymous pull token before the manifest lookup.
# Anything else (quay.io, gcr.io, registry.k8s.io, ...) accepts anonymous
# manifest GETs directly — same flow as documented in /fetch-image-digest.
TOKEN_ENDPOINTS = {
    "docker.io": "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull",
    "ghcr.io": "https://ghcr.io/token?scope=repository:{repo}:pull",
}
MANIFEST_HOSTS = {
    "docker.io": "registry-1.docker.io",
}


def find_dependency(name_or_alias):
    deps = yaml.safe_load(CHART_YAML.read_text())["dependencies"]
    for dep in deps:
        if dep["name"] == name_or_alias or dep.get("alias") == name_or_alias:
            return dep
    raise SystemExit(f"error: no dependency named or aliased '{name_or_alias}' found in {CHART_YAML}")


def chart_ref(dep):
    """Return (ref, extra_repo_url_or_None) for `helm pull`."""
    repo = dep["repository"]
    if repo.startswith("oci://"):
        return f"{repo}/{dep['name']}", None
    if repo.startswith("@"):
        return f"{repo[1:]}/{dep['name']}", None
    if repo.startswith("http://") or repo.startswith("https://"):
        return dep["name"], repo
    raise SystemExit(f"error: unsupported repository scheme: {repo}")


def pull_chart(dep, version, dest):
    """Pull a chart version via helm. Returns (ok, stderr)."""
    ref, repo_url = chart_ref(dep)
    cmd = ["helm", "pull", ref, "--version", version, "--untar", "--untardir", str(dest)]
    if repo_url:
        cmd += ["--repo", repo_url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stderr.strip()


def get_path(node, dotted_path):
    for key in dotted_path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def parse_repo(repository):
    """Split a Docker-style repository string into (registry_host, repo_path)
    using the standard Docker convention: the first path segment is a
    registry host only if it contains a "." or ":" (or is "localhost");
    otherwise the whole string is a Docker Hub repository."""
    first, sep, _ = repository.partition("/")
    if sep and ("." in first or ":" in first or first == "localhost"):
        return first, repository[len(first) + 1:]
    return "docker.io", repository


def registry_tag_exists(registry_host, repo, tag):
    """Return (exists, digest) for <repo>:<tag> on the given registry host,
    using an anonymous pull token where the registry requires one — same
    flow as /fetch-image-digest."""
    headers = {"Accept": MANIFEST_ACCEPT}
    token_url_tmpl = TOKEN_ENDPOINTS.get(registry_host)
    if token_url_tmpl:
        token = json.loads(urllib.request.urlopen(token_url_tmpl.format(repo=repo)).read())["token"]
        headers["Authorization"] = f"Bearer {token}"
    api_host = MANIFEST_HOSTS.get(registry_host, registry_host)
    req = urllib.request.Request(f"https://{api_host}/v2/{repo}/manifests/{tag}", headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return True, resp.headers.get("Docker-Content-Digest")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, None
        raise


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

        chart_dirs = [p for p in tmpdir.iterdir() if p.is_dir()]
        values = yaml.safe_load((chart_dirs[0] / "values.yaml").read_text()) or {}

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
