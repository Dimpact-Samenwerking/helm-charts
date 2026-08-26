"""OCI registry helpers shared by every script that fetches or verifies a
live image digest — same flow as documented in /fetch-image-digest."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from lib.procutil import run

MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.docker.distribution.manifest.v2+json"
)

# Registries with a KNOWN token realm, queried preemptively so a normal
# pull needs only one round trip instead of two (request, get challenged,
# request again). Not the only registries that need a token — see
# _get_with_dynamic_auth below for anything not listed here.
TOKEN_ENDPOINTS = {
    "docker.io": "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull",
    "ghcr.io": "https://ghcr.io/token?scope=repository:{repo}:pull",
}
MANIFEST_HOSTS = {
    "docker.io": "registry-1.docker.io",
}

BEARER_CHALLENGE_PARAM_RE = re.compile(r'(\w+)="([^"]*)"')


def _parse_bearer_challenge(header_value):
    """Parses a `WWW-Authenticate: Bearer realm="...",service="...",
    scope="..."` challenge into {"realm": ..., "service": ..., "scope": ...}
    — the standard OCI Distribution auth flow every spec-compliant registry
    returns on a 401, including ones with no TOKEN_ENDPOINTS entry (see
    _get_with_dynamic_auth). None if it's not a Bearer challenge at all."""
    if not header_value or not header_value.lower().startswith("bearer "):
        return None
    params = dict(BEARER_CHALLENGE_PARAM_RE.findall(header_value))
    return params if "realm" in params else None


def _get_with_dynamic_auth(url, repo, headers):
    """GETs url, retrying once with a bearer token if the registry demands
    one via a WWW-Authenticate challenge that TOKEN_ENDPOINTS didn't already
    anticipate — confirmed 2026-08-26 this is exactly what docker.elastic.co
    needs: a direct anonymous manifest GET 401s, but the challenge names its
    own token realm (docker-auth.elastic.co), and a token from THAT realm is
    accepted same as any other OCI registry. Re-raises unchanged if the 401
    carries no Bearer challenge at all (a real auth wall — see
    UNVERIFIABLE_HOSTS) or retrying still fails."""
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers))
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
        challenge = _parse_bearer_challenge(e.headers.get("WWW-Authenticate"))
        if not challenge:
            raise
        query = {"scope": challenge.get("scope") or f"repository:{repo}:pull"}
        if challenge.get("service"):
            query["service"] = challenge["service"]
        token = json.loads(urllib.request.urlopen(
            f"{challenge['realm']}?{urllib.parse.urlencode(query)}").read())["token"]
        headers = {**headers, "Authorization": f"Bearer {token}"}
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers))


# Hosts that reject even an anonymous manifest read outright — not
# something a better auth flow could fix from here (a real IP/network
# restriction on the registry side, confirmed by hand). check_image_digests
# reports a fetch error against a host in this set separately from a
# genuine FETCH-ERR, since it can never succeed from an unprivileged
# environment regardless of whether the pin itself is correct. Empty for
# now — acrprodmgmt.azurecr.io was here (IP-firewalled to Dimpact's own
# allowlisted networks) but is being removed from values.yaml; add a host
# back here only after confirming by hand that no auth flow can reach it
# (see _get_with_dynamic_auth first — docker.elastic.co looked the same at
# first glance and turned out not to belong here).
UNVERIFIABLE_HOSTS = set()


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
    url = f"https://{api_host}/v2/{repo}/manifests/{tag}"
    try:
        with _get_with_dynamic_auth(url, repo, headers) as resp:
            return True, resp.headers.get("Docker-Content-Digest")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, None
        raise


HISTORICAL_DIGEST_RE_TMPL = r'tag:\s*"?{version}@sha256:([0-9a-f]{{64}})'


def historical_digests_for_tag(values_path, version):
    """Every distinct digest this repo's own git history has ever recorded
    for a "tag: <version>@sha256:<digest>" pin with this exact version
    string — every value this tag has ever been pinned to here, across
    every commit that touched values_path (both sides of every diff hunk).

    Two or more distinct digests is direct, empirical proof this tag has
    drifted before: upstream re-published new content under the same tag,
    and this repo had to re-pin it. Zero or one digest is NOT proof of
    stability — it only means this repo has never observed a change,
    which is inconclusive (the tag may simply not have been refreshed
    yet, or may have just been introduced)."""
    pattern = re.compile(HISTORICAL_DIGEST_RE_TMPL.format(version=re.escape(version)))
    result = run(["git", "-C", str(values_path.parent), "log", "-p", "--", values_path.name],
                 capture_output=True, text=True)
    if result.returncode != 0:
        return set()
    digests = set()
    for line in result.stdout.splitlines():
        if line.startswith(("+++", "---")) or not line.startswith(("+", "-")):
            continue
        m = pattern.search(line)
        if m:
            digests.add(m.group(1))
    return digests


def list_tags(registry_host, repo):
    """All published tag names for a repository, via the generic OCI
    Distribution "tags/list" endpoint (GET /v2/<repo>/tags/list) — supported
    by Docker Hub, ghcr.io, quay.io, and any spec-compliant registry, unlike
    Docker Hub's richer but Hub-specific REST API."""
    headers = {}
    token_url_tmpl = TOKEN_ENDPOINTS.get(registry_host)
    if token_url_tmpl:
        token = json.loads(urllib.request.urlopen(token_url_tmpl.format(repo=repo)).read())["token"]
        headers["Authorization"] = f"Bearer {token}"
    api_host = MANIFEST_HOSTS.get(registry_host, registry_host)
    url = f"https://{api_host}/v2/{repo}/tags/list"
    with _get_with_dynamic_auth(url, repo, headers) as resp:
        return json.loads(resp.read()).get("tags") or []


NUMERIC_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)")


def _numeric_prefix_and_suffix(tag):
    """("3.14", "-slim") for "3.14-slim" — the leading dotted-digits run and
    everything after. (None, tag) if it doesn't start with a digit."""
    m = NUMERIC_PREFIX_RE.match(tag)
    if not m:
        return None, tag
    return m.group(1), tag[m.end():]


def _is_more_specific_tag(candidate, version):
    """True if candidate refines version — e.g. "3.14.7-slim" or
    "3.14-slim-trixie" for "3.14-slim" — NOT a plain string-prefix check:
    "3.14.7-slim" doesn't literally start with "3.14-slim" (the dot lands
    in a different place), but it IS a more specific patch build of the
    same minor version and variant. Requires candidate's dotted-numeric
    part to start with version's (as whole dot-separated components, so
    "3.13" is never mistaken for a refinement of "3.14"), and candidate's
    suffix to equal or extend version's (so "9.10.1" — a different image
    variant, not a refinement — never matches "9.10.1-slim")."""
    cand_num, cand_suffix = _numeric_prefix_and_suffix(candidate)
    ver_num, ver_suffix = _numeric_prefix_and_suffix(version)
    if cand_num is None or ver_num is None:
        return False
    cand_parts, ver_parts = cand_num.split("."), ver_num.split(".")
    if cand_parts[:len(ver_parts)] != ver_parts:
        return False
    return cand_suffix == ver_suffix or cand_suffix.startswith(ver_suffix)


def find_newest_same_variant_tag(registry_host, repo, version):
    """The numerically-highest published tag sharing version's suffix/
    variant (e.g. both "-slim", or both no suffix) — version itself if
    nothing newer is published, or if version isn't a numeric-style tag at
    all (nothing to meaningfully compare). Used by check_cves to tell "a
    newer tag exists, worth checking whether it fixes a given CVE" apart
    from "already on the newest published tag in this line — no fix
    available yet." Deliberately a different relation than
    _is_more_specific_tag (which requires candidate to REFINE version,
    e.g. "3.14.7-slim" for "3.14-slim") — this instead wants any newer
    same-variant release, refinement or not."""
    ver_num, ver_suffix = _numeric_prefix_and_suffix(version)
    if ver_num is None:
        return version

    def numeric_tuple(num):
        return tuple(int(p) for p in num.split("."))

    best, best_key = version, numeric_tuple(ver_num)
    for tag in list_tags(registry_host, repo):
        num, suffix = _numeric_prefix_and_suffix(tag)
        if num is None or suffix != ver_suffix:
            continue
        key = numeric_tuple(num)
        if key > best_key:
            best, best_key = tag, key
    return best


def find_more_specific_tag_at_same_digest(registry_host, repo, version, live_digest):
    """A currently-published tag that's strictly more specific than version
    (e.g. "3.14.7-slim" for "3.14-slim" — see _is_more_specific_tag) and
    resolves to the same digest RIGHT NOW as version's own live digest —
    evidence version is a coarser rolling alias for whatever the latest
    matching build is, not a stable reference in its own right. Returns the
    found tag name, or None. Only meaningful as a fallback when
    historical_digests_for_tag is inconclusive — this checks the registry's
    CURRENT state, not whether version has actually drifted before."""
    candidates = sorted(t for t in list_tags(registry_host, repo)
                         if t != version and _is_more_specific_tag(t, version))
    for t in candidates:
        exists, digest = registry_tag_exists(registry_host, repo, t)
        if exists and digest == live_digest:
            return t
    return None


def is_sliding_tag(values_path, registry_host, repo, version, live_digest):
    """True if this tag is expected to drift, so a digest mismatch against
    it is routine rather than a failure. Primary evidence: this repo's own
    git history shows the tag has changed digest before (>= 2 distinct
    digests ever recorded for it) — direct proof of past drift. Only when
    that's inconclusive (this repo has never observed it change) does this
    fall back to checking whether the registry currently has a more
    specific sibling tag at the same digest, i.e. whether version currently
    looks like a coarser alias. A network problem in that fallback means
    "can't tell" — treated as NOT sliding, so a real pin mismatch is never
    silently downgraded to "expected drift" just because a check failed."""
    if len(historical_digests_for_tag(values_path, version)) >= 2:
        return True
    try:
        return find_more_specific_tag_at_same_digest(registry_host, repo, version, live_digest) is not None
    except (urllib.error.URLError, OSError):
        return False
