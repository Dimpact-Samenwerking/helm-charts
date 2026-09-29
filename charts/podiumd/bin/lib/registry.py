"""OCI registry helpers for fetching and verifying live image digests (same flow as /fetch-image-digest)."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from http.client import HTTPMessage
from pathlib import Path
from typing import IO
from typing import BinaryIO
from typing import TypedDict

from lib.chart.values_tree_primitives import get_path
from lib.chart.values_tree_primitives import text_at
from lib.procutil import run
from lib.yaml_types import YamlValue
from lib.yaml_types import is_yaml_value

MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.docker.distribution.manifest.v2+json"
)

# Known token realms, fetched up front to save the 401 round trip; other registries use
# _get_with_dynamic_auth.
TOKEN_ENDPOINTS = {
    "docker.io": "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull",
    "ghcr.io": "https://ghcr.io/token?scope=repository:{repo}:pull",
}
MANIFEST_HOSTS = {
    "docker.io": "registry-1.docker.io",
}

BEARER_CHALLENGE_PARAM_RE = re.compile(r'(\w+)="([^"]*)"')


class TagCheck(TypedDict):
    """Whether one repository has a tag upstream: the repository, its
    parse_repo split, and registry_tag_exists' (exists, digest)."""

    repository: str
    host: str
    repo_path: str
    exists: bool
    digest: str | None


class ImagePathTagCheck(TagCheck):
    """A TagCheck for the image at one values-tree path."""

    path: str


def _read_json(resp: BinaryIO) -> YamlValue:
    """Parse a registry response body as JSON, raising URLError on a non-JSON 200.

    Rate-limit/proxy HTML pages are routine under load; URLError (an OSError) is what every
    caller already handles, so one bad response degrades to "can't tell" instead of a traceback."""
    raw = resp.read()
    where = getattr(resp, "url", None) or "registry"
    try:
        data: object = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        msg = f"non-JSON response from {where}: {e}"
        raise urllib.error.URLError(msg) from e
    if not is_yaml_value(data):
        msg = f"unexpected JSON from {where}"
        raise urllib.error.URLError(msg)
    return data


def _read_token(resp: BinaryIO) -> str:
    """_read_json plus the ["token"] lookup; a missing token raises URLError too."""
    token = text_at(_read_json(resp), "token")
    if token is None:
        msg = "auth response carried no token"
        raise urllib.error.URLError(msg)
    return token


def _urlopen(url_or_req: str | urllib.request.Request, timeout: float | None = None):
    """urllib.request.urlopen, passing timeout= only when given.

    Tests mock urlopen with a single-arg callable."""
    # Hosts are config-derived trusted registries, never attacker-controlled (same as ruff S310 exemption).
    if timeout is None:
        return urllib.request.urlopen(url_or_req)  # nosec B310
    return urllib.request.urlopen(url_or_req, timeout=timeout)  # nosec B310


def _parse_bearer_challenge(header_value: str | None):
    """Parse a `WWW-Authenticate: Bearer realm=...,service=...,scope=...` header into a dict.

    None unless it is a Bearer challenge with a realm."""
    if not header_value or not header_value.lower().startswith("bearer "):
        return None
    params = dict(BEARER_CHALLENGE_PARAM_RE.findall(header_value))
    return params if "realm" in params else None


class _DropAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect to another host without the Authorization header.

    Registries redirect blob downloads to a storage CDN (docker.elastic.co does),
    which answers HTTP 400 to the registry's bearer token."""

    # Signature fixed by urllib.request.HTTPRedirectHandler.redirect_request, which this overrides.
    def redirect_request(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


_BLOB_OPENER = urllib.request.build_opener(_DropAuthOnRedirect)


def _urlopen_blob(url_or_req: str | urllib.request.Request, timeout: float | None = None):
    """_urlopen for blob downloads: redirects to another host drop the Authorization header."""
    # Same trusted registry hosts as _urlopen.
    return _BLOB_OPENER.open(url_or_req, timeout=timeout)  # nosec B310


def _get_with_dynamic_auth(
    url: str,
    repo: str,
    headers: dict[str, str],
    timeout: float | None = None,
    method: str = "GET",
):
    """Request url, retrying once with a token from the 401's Bearer challenge realm.

    Needed for registries not in TOKEN_ENDPOINTS, e.g. docker.elastic.co (realm
    docker-auth.elastic.co). Re-raises a 401 without a Bearer challenge. The retry uses the
    same method. A blob download follows a redirect to another host without the
    Authorization header (see _DropAuthOnRedirect)."""
    urlopen = _urlopen_blob if "/blobs/" in url else _urlopen
    try:
        return urlopen(urllib.request.Request(url, headers=headers, method=method), timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
        challenge = _parse_bearer_challenge(e.headers.get("WWW-Authenticate"))
        if not challenge:
            raise
        query = {"scope": challenge.get("scope") or f"repository:{repo}:pull"}
        if challenge.get("service"):
            query["service"] = challenge["service"]
        token = _read_token(_urlopen(f"{challenge['realm']}?{urllib.parse.urlencode(query)}", timeout=timeout))
        headers = {**headers, "Authorization": f"Bearer {token}"}
        return urlopen(urllib.request.Request(url, headers=headers, method=method), timeout=timeout)


# Hosts that reject even anonymous manifest reads (network restriction); check_image_digests
# reports their fetch errors separately. Add one only after confirming no auth flow reaches it
# (docker.elastic.co looked like this but just needed _get_with_dynamic_auth).
UNVERIFIABLE_HOSTS: set[str] = set()


def parse_repo(repository: str) -> tuple[str, str]:
    """Split a repository string into (registry_host, repo_path), Docker-style.

    The first segment is a host only if it contains "." or ":" or is "localhost"; otherwise
    it is Docker Hub, with un-namespaced official images under "library/"."""
    first, sep, _ = repository.partition("/")
    if sep and ("." in first or ":" in first or first == "localhost"):
        return first, repository[len(first) + 1 :]
    if not sep:
        return "docker.io", f"library/{repository}"
    return "docker.io", repository


def _fetch_manifest_digest(
    url: str, repo: str, headers: dict[str, str], timeout: float | None, method: str
) -> tuple[bool, str | None]:
    """(exists, digest) from one manifest request; a 404 means (False, None), other errors propagate."""
    try:
        with _get_with_dynamic_auth(url, repo, headers, timeout=timeout, method=method) as resp:
            return True, resp.headers.get("Docker-Content-Digest")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, None
        raise


def registry_tag_exists(
    registry_host: str, repo: str, tag: str, timeout: float | None = None
) -> tuple[bool, str | None]:
    """Return (exists, digest) for <repo>:<tag>, with an anonymous pull token where needed.

    timeout (seconds) bounds every request; None waits indefinitely. Uses HEAD: only the
    Docker-Content-Digest header is read, and Docker Hub counts a manifest GET against the
    anonymous rate limit but not a HEAD. Falls back to GET only on 405."""
    headers = {"Accept": MANIFEST_ACCEPT}
    token_url_tmpl = TOKEN_ENDPOINTS.get(registry_host)
    if token_url_tmpl:
        token = _read_token(_urlopen(token_url_tmpl.format(repo=repo), timeout=timeout))
        headers["Authorization"] = f"Bearer {token}"
    api_host = MANIFEST_HOSTS.get(registry_host, registry_host)
    url = f"https://{api_host}/v2/{repo}/manifests/{tag}"
    try:
        return _fetch_manifest_digest(url, repo, headers, timeout, "HEAD")
    except urllib.error.HTTPError as e:
        if e.code != 405:
            raise
        return _fetch_manifest_digest(url, repo, headers, timeout, "GET")


IMAGE_CONFIG_ACCEPT = "application/vnd.oci.image.config.v1+json,application/vnd.docker.container.image.v1+json"
# The node platform whose image variant is inspected in a multi-arch index.
NODE_PLATFORM = ("linux", "amd64")


def _registry_json(registry_host: str, repo: str, path: str, accept: str, timeout: float | None) -> YamlValue:
    """GET /v2/<repo>/<path> as JSON, authenticated like list_tags."""
    headers = {"Accept": accept}
    token_url_tmpl = TOKEN_ENDPOINTS.get(registry_host)
    if token_url_tmpl:
        headers["Authorization"] = f"Bearer {_read_token(_urlopen(token_url_tmpl.format(repo=repo)))}"
    api_host = MANIFEST_HOSTS.get(registry_host, registry_host)
    url = f"https://{api_host}/v2/{repo}/{path}"
    with _get_with_dynamic_auth(url, repo, headers, timeout=timeout) as resp:
        return _read_json(resp)


def _platform_manifest_digest(index: YamlValue) -> str:
    """The NODE_PLATFORM manifest's digest in a multi-arch index; URLError if it has none."""
    entries = get_path(index, "manifests")
    for entry in entries if isinstance(entries, list) else []:
        platform = (text_at(entry, "platform.os"), text_at(entry, "platform.architecture"))
        digest = text_at(entry, "digest")
        if platform == NODE_PLATFORM and digest:
            return digest
    msg = f"no {'/'.join(NODE_PLATFORM)} image in the index"
    raise urllib.error.URLError(msg)


def image_config_user(registry_host: str, repo: str, reference: str, timeout: float | None = None) -> str:
    """The image's default user (its config "User"; "" means root), for a tag or digest `reference`.

    Reads the manifest and config blob only, no image pull. A multi-arch index
    uses its NODE_PLATFORM image. Raises URLError when the registry answers
    without a usable manifest or config.
    """
    manifest = _registry_json(registry_host, repo, f"manifests/{reference}", MANIFEST_ACCEPT, timeout)
    if get_path(manifest, "manifests") is not None:
        digest = _platform_manifest_digest(manifest)
        manifest = _registry_json(registry_host, repo, f"manifests/{digest}", MANIFEST_ACCEPT, timeout)
    config_digest = text_at(manifest, "config.digest")
    if not config_digest:
        msg = f"manifest of {registry_host}/{repo}:{reference} has no config"
        raise urllib.error.URLError(msg)
    config = _registry_json(registry_host, repo, f"blobs/{config_digest}", IMAGE_CONFIG_ACCEPT, timeout)
    return text_at(config, "config.User") or ""


HISTORICAL_DIGEST_RE_TMPL = r'tag:\s*"?{version}@sha256:([0-9a-f]{{64}})'


def historical_digests_for_tag(values_path: Path, version: str) -> set[str]:
    """Every distinct digest git history of values_path has pinned for "tag: <version>@sha256:...".

    Two or more proves the tag drifted before; zero or one is inconclusive."""
    pattern = re.compile(HISTORICAL_DIGEST_RE_TMPL.format(version=re.escape(version)))
    result = run(
        ["git", "-C", str(values_path.parent), "log", "-p", "--", values_path.name], capture_output=True, text=True
    )
    if result.returncode != 0:
        return set()
    digests: set[str] = set()
    for line in result.stdout.splitlines():
        if line.startswith(("+++", "---")) or not line.startswith(("+", "-")):
            continue
        m = pattern.search(line)
        if m:
            digests.add(m.group(1))
    return digests


def list_tags(registry_host: str, repo: str):
    """All published tag names, via the generic OCI GET /v2/<repo>/tags/list endpoint."""
    headers: dict[str, str] = {}
    token_url_tmpl = TOKEN_ENDPOINTS.get(registry_host)
    if token_url_tmpl:
        token = _read_token(_urlopen(token_url_tmpl.format(repo=repo)))
        headers["Authorization"] = f"Bearer {token}"
    api_host = MANIFEST_HOSTS.get(registry_host, registry_host)
    url = f"https://{api_host}/v2/{repo}/tags/list"
    with _get_with_dynamic_auth(url, repo, headers) as resp:
        tags = get_path(_read_json(resp), "tags") or []
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        msg = f"tags/list response from {api_host} is not a list of tag names"
        raise urllib.error.URLError(msg)
    return [tag for tag in tags if isinstance(tag, str)]


NUMERIC_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)")


def _numeric_prefix_and_suffix(tag: str):
    """("3.14", "-slim") for "3.14-slim" — the leading dotted-digits run and
    everything after. (None, tag) if it doesn't start with a digit."""
    m = NUMERIC_PREFIX_RE.match(tag)
    if not m:
        return None, tag
    return m.group(1), tag[m.end() :]


def _is_more_specific_tag(candidate: str, version: str):
    """True if candidate refines version, e.g. "3.14.7-slim" or "3.14-slim-trixie" for "3.14-slim".

    Not a string-prefix check: the numeric parts must match as whole dot components
    ("3.13" never refines "3.14"), and candidate's suffix must equal or extend version's."""
    cand_num, cand_suffix = _numeric_prefix_and_suffix(candidate)
    ver_num, ver_suffix = _numeric_prefix_and_suffix(version)
    if cand_num is None or ver_num is None:
        return False
    cand_parts, ver_parts = cand_num.split("."), ver_num.split(".")
    if cand_parts[: len(ver_parts)] != ver_parts:
        return False
    return cand_suffix == ver_suffix or cand_suffix.startswith(ver_suffix)


def find_newest_same_variant_tag(registry_host: str, repo: str, version: str) -> str:
    """The numerically highest published tag with version's suffix, else version itself.

    Unlike _is_more_specific_tag, any newer same-variant release counts. Candidates must
    have as many dot components as version: frank-gateway publishes bare CI run-ID tags
    ("12294937630"), and (12294937630,) > (1, 1, 0) in tuple comparison."""
    ver_num, ver_suffix = _numeric_prefix_and_suffix(version)
    if ver_num is None:
        return version

    def numeric_tuple(num: str):
        return tuple(int(p) for p in num.split("."))

    ver_parts = ver_num.split(".")
    best, best_key = version, numeric_tuple(ver_num)
    for tag in list_tags(registry_host, repo):
        num, suffix = _numeric_prefix_and_suffix(tag)
        if num is None or suffix != ver_suffix or len(num.split(".")) != len(ver_parts):
            continue
        key = numeric_tuple(num)
        if key > best_key:
            best, best_key = tag, key
    return best


def find_more_specific_tag_at_same_digest(registry_host: str, repo: str, version: str, live_digest: str):
    """A published tag more specific than version that currently has the same digest, or None.

    Evidence version is a rolling alias; reflects current registry state, not past drift."""
    candidates = sorted(t for t in list_tags(registry_host, repo) if t != version and _is_more_specific_tag(t, version))
    for t in candidates:
        exists, digest = registry_tag_exists(registry_host, repo, t)
        if exists and digest == live_digest:
            return t
    return None


def is_sliding_tag(values_path: Path, registry_host: str, repo: str, version: str, live_digest: str):
    """True if this tag is expected to drift, so a digest mismatch is routine.

    Proof: >= 2 historical digests in git. Otherwise falls back to a more specific tag at the
    same live digest. A network error there counts as not sliding, so real mismatches are
    never downgraded."""
    if len(historical_digests_for_tag(values_path, version)) >= 2:
        return True
    try:
        return find_more_specific_tag_at_same_digest(registry_host, repo, version, live_digest) is not None
    except (urllib.error.URLError, OSError):
        return False
