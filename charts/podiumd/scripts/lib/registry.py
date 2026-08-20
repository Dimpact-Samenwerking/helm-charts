"""OCI registry helpers shared by every script that fetches or verifies a
live image digest — same flow as documented in /fetch-image-digest."""
import json
import urllib.error
import urllib.request

MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.docker.distribution.manifest.v2+json"
)

# Registries needing an anonymous pull token before the manifest lookup.
# Anything else (quay.io, gcr.io, registry.k8s.io, ...) accepts anonymous
# manifest GETs directly.
TOKEN_ENDPOINTS = {
    "docker.io": "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull",
    "ghcr.io": "https://ghcr.io/token?scope=repository:{repo}:pull",
}
MANIFEST_HOSTS = {
    "docker.io": "registry-1.docker.io",
}


def parse_repo(repository):
    """Split a Docker-style repository string into (registry_host, repo_path)
    using the standard Docker convention: the first path segment is a
    registry host only if it contains a "." or ":" (or is "localhost");
    otherwise the whole string is a Docker Hub repository — official images
    with no namespace (e.g. "python") live under "library/" on the registry
    API even though that prefix is omitted in the human-readable form."""
    first, sep, _ = repository.partition("/")
    if sep and ("." in first or ":" in first or first == "localhost"):
        return first, repository[len(first) + 1:]
    if not sep:
        return "docker.io", f"library/{repository}"
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
