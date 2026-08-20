#!/usr/bin/env python3
"""
Verify that a component's target app image version(s) and Helm chart version
actually exist (published), BEFORE writing them into charts/podiumd/values.yaml
or Chart.yaml — a non-existent tag or chart version breaks image pulls /
`helm dependency update` at deploy time rather than at edit time.

Usage:
    verify-component-version.py <component> <app-version> <chart-version>

Examples:
    verify-component-version.py zac 5.4.3 1.0.297
    verify-component-version.py zgw-office-addin 0.12.0 0.0.92

Exit code is non-zero if either the app version or the chart version does not
exist — safe to use as a gate before bumping the chart.
"""
import json
import sys
import urllib.error
import urllib.request

import yaml

# component (name or alias) -> GHCR image repositories whose tag must match
# the app version. Some components (e.g. zgw-office-addin) ship more than
# one image that must move in lockstep.
COMPONENT_IMAGES = {
    "zac": ["infonl/zaakafhandelcomponent"],
    "zaakafhandelcomponent": ["infonl/zaakafhandelcomponent"],
    "zgw-office-addin": ["infonl/zgw-office-addin-frontend", "infonl/zgw-office-addin-backend"],
}

# component (name or alias) -> (chart name in the repo's index.yaml, index.yaml URL)
COMPONENT_CHART_REPOS = {
    "zac": ("zaakafhandelcomponent", "https://infonl.github.io/dimpact-zaakafhandelcomponent/index.yaml"),
    "zaakafhandelcomponent": ("zaakafhandelcomponent", "https://infonl.github.io/dimpact-zaakafhandelcomponent/index.yaml"),
    "zgw-office-addin": ("zgw-office-addin", "https://infonl.github.io/zgw-office-addin/index.yaml"),
}

MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.docker.distribution.manifest.v2+json"
)


def ghcr_tag_exists(repo, tag):
    """Return (exists, digest) for ghcr.io/<repo>:<tag>, using an anonymous
    pull token — same flow as /fetch-image-digest."""
    token_resp = urllib.request.urlopen(f"https://ghcr.io/token?scope=repository:{repo}:pull")
    token = json.loads(token_resp.read())["token"]
    req = urllib.request.Request(
        f"https://ghcr.io/v2/{repo}/manifests/{tag}",
        headers={"Authorization": f"Bearer {token}", "Accept": MANIFEST_ACCEPT},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return True, resp.headers.get("Docker-Content-Digest")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, None
        raise


def chart_version_exists(index_url, chart_name, version):
    """Return (exists, index-entry-or-None) for a chart version in a Helm
    repo's index.yaml."""
    data = yaml.safe_load(urllib.request.urlopen(index_url).read())
    for entry in data.get("entries", {}).get(chart_name, []):
        if entry["version"] == version:
            return True, entry
    return False, None


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    component, app_version, chart_version = sys.argv[1], sys.argv[2], sys.argv[3]

    images = COMPONENT_IMAGES.get(component)
    chart_repo = COMPONENT_CHART_REPOS.get(component)
    if not images or not chart_repo:
        known = ", ".join(sorted(set(COMPONENT_IMAGES) | set(COMPONENT_CHART_REPOS)))
        print(f"error: unknown component '{component}' (known: {known})")
        sys.exit(1)

    ok = True

    print(f"Checking app version {app_version!r} for {component}:")
    for repo in images:
        exists, digest = ghcr_tag_exists(repo, app_version)
        status = "FOUND  " if exists else "MISSING"
        suffix = f"  digest={digest}" if digest else ""
        print(f"  [{status}] ghcr.io/{repo}:{app_version}{suffix}")
        ok = ok and exists

    chart_name, index_url = chart_repo
    print(f"Checking chart version {chart_version!r} for {chart_name}:")
    exists, entry = chart_version_exists(index_url, chart_name, chart_version)
    status = "FOUND  " if exists else "MISSING"
    suffix = f"  appVersion={entry.get('appVersion')}" if entry else ""
    print(f"  [{status}] {chart_name} {chart_version}{suffix}")
    ok = ok and exists

    print()
    print("OK: both exist" if ok else "FAIL: one or more versions do not exist yet")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
