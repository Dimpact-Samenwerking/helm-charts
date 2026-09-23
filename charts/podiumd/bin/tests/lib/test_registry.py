"""lib.registry.parse_repo / registry_tag_exists / historical_digests_for_tag /
list_tags / find_more_specific_tag_at_same_digest / is_sliding_tag — no
network needed, urllib.request.urlopen is monkeypatched wherever a live
fetch would happen; historical_digests_for_tag uses a real, hermetic temp
git repo (git log needs a real working tree)."""

import json
import subprocess
import urllib.error

from io import BytesIO

import pytest

# --- parse_repo ---


def test_parse_repo_bare_docker_hub_official_image(libregistry):
    assert libregistry.parse_repo("python") == ("docker.io", "library/python")


def test_parse_repo_bare_docker_hub_namespaced(libregistry):
    assert libregistry.parse_repo("nginxinc/nginx-unprivileged") == ("docker.io", "nginxinc/nginx-unprivileged")


def test_parse_repo_explicit_host(libregistry):
    assert libregistry.parse_repo("ghcr.io/infonl/zaakafhandelcomponent") == ("ghcr.io", "infonl/zaakafhandelcomponent")


def test_parse_repo_explicit_docker_io_host(libregistry):
    assert libregistry.parse_repo("docker.io/alpine/k8s") == ("docker.io", "alpine/k8s")


def test_parse_repo_localhost(libregistry):
    assert libregistry.parse_repo("localhost/foo") == ("localhost", "foo")


def test_parse_repo_host_with_port(libregistry):
    assert libregistry.parse_repo("localhost:5000/foo") == ("localhost:5000", "foo")


# --- registry_tag_exists ---


class FakeResponse:
    def __init__(self, headers=None, body=b""):
        self.headers = headers or {}
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_registry_tag_exists_no_token_needed(libregistry, monkeypatch):
    def fake_urlopen(req):
        assert "Authorization" not in req.headers
        return FakeResponse(headers={"Docker-Content-Digest": "sha256:" + "a" * 64})

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    exists, digest = libregistry.registry_tag_exists("quay.io", "coreos/etcd", "v3.5.16")
    assert exists is True
    assert digest == "sha256:" + "a" * 64


def test_registry_tag_exists_fetches_token_for_docker_hub(libregistry, monkeypatch):
    calls = []

    def fake_urlopen(arg):
        url = arg if isinstance(arg, str) else arg.full_url
        calls.append(url)
        if "auth.docker.io" in url:
            return FakeResponse(body=json.dumps({"token": "faketoken"}).encode())
        assert arg.headers.get("Authorization") == "Bearer faketoken"
        return FakeResponse(headers={"Docker-Content-Digest": "sha256:" + "b" * 64})

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    exists, digest = libregistry.registry_tag_exists("docker.io", "library/python", "3.14-slim")
    assert exists is True
    assert digest == "sha256:" + "b" * 64
    assert any("auth.docker.io" in c for c in calls)


def test_registry_tag_exists_404_returns_false(libregistry, monkeypatch):
    def fake_urlopen(req):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, BytesIO(b""))

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    exists, digest = libregistry.registry_tag_exists("quay.io", "coreos/etcd", "nonexistent")
    assert exists is False
    assert digest is None


def test_registry_tag_exists_reraises_non_404_error(libregistry, monkeypatch):
    def fake_urlopen(req):
        raise urllib.error.HTTPError(req.full_url, 500, "Server Error", {}, BytesIO(b""))

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        libregistry.registry_tag_exists("quay.io", "coreos/etcd", "v3.5.16")


def test_registry_tag_exists_passes_timeout_when_given(libregistry, monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["timeout"] = timeout
        return FakeResponse(headers={"Docker-Content-Digest": "sha256:" + "a" * 64})

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    libregistry.registry_tag_exists("quay.io", "coreos/etcd", "v3.5.16", timeout=7)
    assert seen["timeout"] == 7


def test_registry_tag_exists_omits_timeout_kwarg_by_default(libregistry, monkeypatch):
    """Without an explicit timeout, urlopen must be called exactly like
    before this param existed (no timeout kwarg at all) — a caller mocking
    urlopen with a plain single-arg callable (every existing test here)
    must keep working unmodified."""

    def fake_urlopen(req):
        return FakeResponse(headers={"Docker-Content-Digest": "sha256:" + "a" * 64})

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    exists, digest = libregistry.registry_tag_exists("quay.io", "coreos/etcd", "v3.5.16")
    assert exists is True


def test_registry_tag_exists_discovers_token_via_bearer_challenge(libregistry, monkeypatch):
    """A host with no TOKEN_ENDPOINTS entry (like docker.elastic.co) that
    still needs a token: the first attempt 401s with a WWW-Authenticate
    challenge naming its own realm, which is then queried for a token and
    retried — no hardcoded host-specific endpoint required."""
    calls = []

    def fake_urlopen(arg):
        url = arg if isinstance(arg, str) else arg.full_url
        calls.append(url)
        if "docker-auth.elastic.co" in url:
            return FakeResponse(body=json.dumps({"token": "elastictoken"}).encode())
        if arg.headers.get("Authorization") == "Bearer elastictoken":
            return FakeResponse(headers={"Docker-Content-Digest": "sha256:" + "e" * 64})
        raise urllib.error.HTTPError(
            url,
            401,
            "Unauthorized",
            {
                "WWW-Authenticate": 'Bearer realm="https://docker-auth.elastic.co/auth",'
                'service="token-service",'
                'scope="repository:integrations/crawler:pull"'
            },
            BytesIO(b""),
        )

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    exists, digest = libregistry.registry_tag_exists("docker.elastic.co", "integrations/crawler", "1.0.0")
    assert exists is True
    assert digest == "sha256:" + "e" * 64
    assert any("docker-auth.elastic.co" in c for c in calls)


def test_registry_tag_exists_401_without_challenge_reraises(libregistry, monkeypatch):
    """A 401 that isn't a Bearer challenge at all (a real auth wall — see
    UNVERIFIABLE_HOSTS) is not something a token fetch could ever fix —
    must propagate unchanged, not loop or crash."""

    def fake_urlopen(req):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, BytesIO(b""))

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        libregistry.registry_tag_exists("firewalled-registry.example.com", "some/repo", "1.0.0")
    assert exc_info.value.code == 401


def test_registry_tag_exists_issues_a_head_request(libregistry, monkeypatch):
    """Docker Hub's own documented pull-rate-limit policy counts a manifest
    GET fully against the anonymous quota but not a HEAD (docs.docker.com/
    docker-hub/usage/pulls/) — confirmed live 2026-09-14 against docker.io
    and ghcr.io (identical Docker-Content-Digest header on both). This
    only ever reads response headers, never the body, so it must issue
    HEAD, not GET."""
    seen = {}

    def fake_urlopen(req):
        seen["method"] = req.get_method()
        return FakeResponse(headers={"Docker-Content-Digest": "sha256:" + "a" * 64})

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    libregistry.registry_tag_exists("quay.io", "coreos/etcd", "v3.5.16")
    assert seen["method"] == "HEAD"


def test_registry_tag_exists_falls_back_to_get_on_405(libregistry, monkeypatch):
    """A registry that doesn't support HEAD on the manifest endpoint
    answers 405 Method Not Allowed — registry_tag_exists must retry that
    one call with GET rather than treating it as a hard failure, and still
    return the correct result."""
    calls = []

    def fake_urlopen(req):
        calls.append(req.get_method())
        if req.get_method() == "HEAD":
            raise urllib.error.HTTPError(req.full_url, 405, "Method Not Allowed", {}, BytesIO(b""))
        return FakeResponse(headers={"Docker-Content-Digest": "sha256:" + "a" * 64})

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    exists, digest = libregistry.registry_tag_exists("quay.io", "coreos/etcd", "v3.5.16")
    assert exists is True
    assert digest == "sha256:" + "a" * 64
    assert calls == ["HEAD", "GET"]


def test_registry_tag_exists_404_on_head_returns_false_without_get_fallback(libregistry, monkeypatch):
    """A 404 is a genuine "tag doesn't exist" answer regardless of method —
    must NOT trigger the 405 GET-fallback path, which is specifically for
    "this registry doesn't support HEAD here", a different condition than
    "not found"."""

    def fake_urlopen(req):
        assert req.get_method() == "HEAD"
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, BytesIO(b""))

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    exists, digest = libregistry.registry_tag_exists("quay.io", "coreos/etcd", "nonexistent")
    assert exists is False
    assert digest is None


def test_registry_tag_exists_500_on_head_reraises_without_get_fallback(libregistry, monkeypatch):
    """Only a 405 means "try GET instead" — any other error (a real server
    problem, say) must surface as itself, not be masked by a speculative
    retry under a different method."""

    def fake_urlopen(req):
        assert req.get_method() == "HEAD"
        raise urllib.error.HTTPError(req.full_url, 500, "Server Error", {}, BytesIO(b""))

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        libregistry.registry_tag_exists("quay.io", "coreos/etcd", "v3.5.16")
    assert exc_info.value.code == 500


def test_registry_tag_exists_head_method_threaded_through_bearer_challenge_retry(libregistry, monkeypatch):
    """_get_with_dynamic_auth's post-401-challenge retry (see that test
    above for the non-HEAD version of this flow) must reuse the SAME HTTP
    method as the original request — a HEAD request that 401s and gets a
    token should retry as HEAD again, not silently upgrade to GET."""
    calls = []

    def fake_urlopen(arg):
        url = arg if isinstance(arg, str) else arg.full_url
        if "docker-auth.elastic.co" in url:
            return FakeResponse(body=json.dumps({"token": "elastictoken"}).encode())
        calls.append(arg.get_method())
        if arg.headers.get("Authorization") == "Bearer elastictoken":
            return FakeResponse(headers={"Docker-Content-Digest": "sha256:" + "e" * 64})
        raise urllib.error.HTTPError(
            url,
            401,
            "Unauthorized",
            {
                "WWW-Authenticate": 'Bearer realm="https://docker-auth.elastic.co/auth",'
                'service="token-service",'
                'scope="repository:integrations/crawler:pull"'
            },
            BytesIO(b""),
        )

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    exists, digest = libregistry.registry_tag_exists("docker.elastic.co", "integrations/crawler", "1.0.0")
    assert exists is True
    assert digest == "sha256:" + "e" * 64
    assert calls == ["HEAD", "HEAD"]


def test_list_tags_still_issues_a_get_request(libregistry, monkeypatch):
    """list_tags genuinely reads the response body (the "tags" list) — it
    must stay GET, unaffected by registry_tag_exists's own switch to
    HEAD."""
    seen = {}

    def fake_urlopen(req):
        seen["method"] = req.get_method()
        return FakeResponse(body=json.dumps({"tags": ["1.0.0"]}).encode())

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    libregistry.list_tags("quay.io", "coreos/etcd")
    assert seen["method"] == "GET"


# --- historical_digests_for_tag ---


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def values_repo(tmp_path):
    """A real, hermetic git repo whose values.yaml history pins solr's tag
    to THREE different digests across three commits (real drift, like this
    project's own history), and zac's tag to just one (never observed to
    change)."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    values_path = tmp_path / "values.yaml"

    values_path.write_text(
        'zac:\n  image:\n    tag: "5.1.0@sha256:' + "c" * 64 + '"\n'
        'solr:\n  image:\n    tag: "9.10.1-slim@sha256:' + "a" * 64 + '"\n'
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "initial", cwd=tmp_path)

    values_path.write_text(
        'zac:\n  image:\n    tag: "5.1.0@sha256:' + "c" * 64 + '"\n'
        'solr:\n  image:\n    tag: "9.10.1-slim@sha256:' + "b" * 64 + '"\n'
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "refresh solr digest #1", cwd=tmp_path)

    values_path.write_text(
        'zac:\n  image:\n    tag: "5.1.0@sha256:' + "c" * 64 + '"\n'
        'solr:\n  image:\n    tag: "9.10.1-slim@sha256:' + "d" * 64 + '"\n'
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "refresh solr digest #2", cwd=tmp_path)

    return values_path


def test_historical_digests_for_tag_finds_multiple_past_digests(libregistry, values_repo):
    digests = libregistry.historical_digests_for_tag(values_repo, "9.10.1-slim")
    assert digests == {"a" * 64, "b" * 64, "d" * 64}


def test_historical_digests_for_tag_single_digest_when_never_refreshed(libregistry, values_repo):
    digests = libregistry.historical_digests_for_tag(values_repo, "5.1.0")
    assert digests == {"c" * 64}


def test_historical_digests_for_tag_empty_outside_git_repo(libregistry, tmp_path):
    values_path = tmp_path / "values.yaml"
    values_path.write_text('zac:\n  image:\n    tag: "5.1.0@sha256:' + "c" * 64 + '"\n')
    assert libregistry.historical_digests_for_tag(values_path, "5.1.0") == set()


def test_historical_digests_for_tag_empty_for_unknown_version(libregistry, values_repo):
    assert libregistry.historical_digests_for_tag(values_repo, "9.9.9-nonexistent") == set()


# --- list_tags ---


def test_list_tags_returns_tag_names(libregistry, monkeypatch):
    def fake_urlopen(req):
        return FakeResponse(body=json.dumps({"tags": ["9.10.1", "9.10.1-slim"]}).encode())

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    assert libregistry.list_tags("quay.io", "coreos/etcd") == ["9.10.1", "9.10.1-slim"]


def test_list_tags_fetches_token_for_docker_hub(libregistry, monkeypatch):
    calls = []

    def fake_urlopen(arg):
        url = arg if isinstance(arg, str) else arg.full_url
        calls.append(url)
        if "auth.docker.io" in url:
            return FakeResponse(body=json.dumps({"token": "faketoken"}).encode())
        assert arg.headers.get("Authorization") == "Bearer faketoken"
        return FakeResponse(body=json.dumps({"tags": ["3.14-slim"]}).encode())

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    assert libregistry.list_tags("docker.io", "library/python") == ["3.14-slim"]


def test_list_tags_empty_when_missing_from_response(libregistry, monkeypatch):
    monkeypatch.setattr(libregistry.urllib.request, "urlopen", lambda req: FakeResponse(body=json.dumps({}).encode()))
    assert libregistry.list_tags("quay.io", "coreos/etcd") == []


def test_list_tags_non_json_200_raises_urlerror_not_jsondecodeerror(libregistry, monkeypatch):
    """A 200 response carrying an HTML rate-limit / interstitial page
    (routine for Docker Hub / Cloudflare-fronted registries under load)
    must degrade to a URLError — the type every caller already catches —
    not a JSONDecodeError that aborts the whole verify-podiumd run."""
    monkeypatch.setattr(
        libregistry.urllib.request, "urlopen", lambda req: FakeResponse(body=b"<html>429 Too Many Requests</html>")
    )
    with pytest.raises(urllib.error.URLError):
        libregistry.list_tags("quay.io", "coreos/etcd")


def test_registry_tag_exists_non_json_token_response_raises_urlerror(libregistry, monkeypatch):
    def fake_urlopen(arg):
        url = arg if isinstance(arg, str) else arg.full_url
        if "auth.docker.io" in url:
            return FakeResponse(body=b"<html>503</html>")
        msg = "must not reach the manifest request"
        raise AssertionError(msg)

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.URLError):
        libregistry.registry_tag_exists("docker.io", "library/python", "3.14-slim")


def test_list_tags_token_response_missing_token_key_raises_urlerror(libregistry, monkeypatch):
    monkeypatch.setattr(
        libregistry.urllib.request, "urlopen", lambda arg: FakeResponse(body=json.dumps({"not_token": "x"}).encode())
    )
    with pytest.raises(urllib.error.URLError):
        libregistry.list_tags("docker.io", "library/python")


def test_list_tags_discovers_token_via_bearer_challenge(libregistry, monkeypatch):
    def fake_urlopen(arg):
        url = arg if isinstance(arg, str) else arg.full_url
        if "docker-auth.elastic.co" in url:
            return FakeResponse(body=json.dumps({"token": "elastictoken"}).encode())
        if arg.headers.get("Authorization") == "Bearer elastictoken":
            return FakeResponse(body=json.dumps({"tags": ["1.0.0"]}).encode())
        raise urllib.error.HTTPError(
            url,
            401,
            "Unauthorized",
            {"WWW-Authenticate": 'Bearer realm="https://docker-auth.elastic.co/auth",service="token-service"'},
            BytesIO(b""),
        )

    monkeypatch.setattr(libregistry.urllib.request, "urlopen", fake_urlopen)
    assert libregistry.list_tags("docker.elastic.co", "integrations/crawler") == ["1.0.0"]


# --- _parse_bearer_challenge ---


def test_parse_bearer_challenge_extracts_all_params(libregistry):
    header = 'Bearer realm="https://docker-auth.elastic.co/auth",service="token-service",scope="repository:foo:pull"'
    assert libregistry._parse_bearer_challenge(header) == {
        "realm": "https://docker-auth.elastic.co/auth",
        "service": "token-service",
        "scope": "repository:foo:pull",
    }


def test_parse_bearer_challenge_none_for_non_bearer_scheme(libregistry):
    assert libregistry._parse_bearer_challenge('Basic realm="foo"') is None


def test_parse_bearer_challenge_none_for_missing_header(libregistry):
    assert libregistry._parse_bearer_challenge(None) is None


def test_parse_bearer_challenge_none_without_realm(libregistry):
    assert libregistry._parse_bearer_challenge('Bearer service="token-service"') is None


# --- _is_more_specific_tag ---


def test_is_more_specific_tag_patch_refinement(libregistry):
    assert libregistry._is_more_specific_tag("3.14.7-slim", "3.14-slim") is True


def test_is_more_specific_tag_suffix_refinement(libregistry):
    assert libregistry._is_more_specific_tag("3.14-slim-trixie", "3.14-slim") is True


def test_is_more_specific_tag_both_refinements(libregistry):
    assert libregistry._is_more_specific_tag("3.14.7-slim-trixie", "3.14-slim") is True


def test_is_more_specific_tag_rejects_different_minor_version(libregistry):
    # 3.13.14 is not a refinement of 3.14 just because both start with "3.1"
    assert libregistry._is_more_specific_tag("3.13.14-slim", "3.14-slim") is False


def test_is_more_specific_tag_rejects_different_variant(libregistry):
    # "9.10.1" (no suffix) is a different image variant, not a refinement
    assert libregistry._is_more_specific_tag("9.10.1", "9.10.1-slim") is False


def test_is_more_specific_tag_rejects_non_numeric_tag(libregistry):
    assert libregistry._is_more_specific_tag("unrelated-tag", "3.14-slim") is False


# --- find_more_specific_tag_at_same_digest ---


def test_find_more_specific_tag_at_same_digest_finds_sibling(libregistry, monkeypatch):
    monkeypatch.setattr(libregistry, "list_tags", lambda host, repo: ["3.14-slim", "3.14.7-slim", "3.13-slim"])
    monkeypatch.setattr(
        libregistry,
        "registry_tag_exists",
        lambda host, repo, tag: (True, "sha256:" + "b" * 64) if tag == "3.14.7-slim" else (True, "sha256:" + "z" * 64),
    )
    found = libregistry.find_more_specific_tag_at_same_digest(
        "docker.io", "library/python", "3.14-slim", "sha256:" + "b" * 64
    )
    assert found == "3.14.7-slim"


def test_find_more_specific_tag_at_same_digest_none_when_no_sibling_matches(libregistry, monkeypatch):
    monkeypatch.setattr(libregistry, "list_tags", lambda host, repo: ["9.10.1", "9.10.1-slim"])
    monkeypatch.setattr(libregistry, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "z" * 64))
    found = libregistry.find_more_specific_tag_at_same_digest(
        "docker.io", "library/solr", "9.10.1-slim", "sha256:" + "a" * 64
    )
    assert found is None


def test_find_more_specific_tag_at_same_digest_ignores_non_prefix_tags(libregistry, monkeypatch):
    monkeypatch.setattr(libregistry, "list_tags", lambda host, repo: ["unrelated-tag"])
    monkeypatch.setattr(libregistry, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "a" * 64))
    found = libregistry.find_more_specific_tag_at_same_digest(
        "docker.io", "library/python", "3.14-slim", "sha256:" + "a" * 64
    )
    assert found is None


# --- find_newest_same_variant_tag ---


def test_find_newest_same_variant_tag_finds_newer_release(libregistry, monkeypatch):
    monkeypatch.setattr(libregistry, "list_tags", lambda host, repo: ["3.14-slim", "3.15-slim", "3.13-slim"])
    assert libregistry.find_newest_same_variant_tag("docker.io", "library/python", "3.14-slim") == "3.15-slim"


def test_find_newest_same_variant_tag_returns_version_when_already_newest(libregistry, monkeypatch):
    monkeypatch.setattr(libregistry, "list_tags", lambda host, repo: ["1.0.0", "1.1.0", "1.2.0"])
    assert libregistry.find_newest_same_variant_tag("docker.io", "org/repo", "1.2.0") == "1.2.0"


def test_find_newest_same_variant_tag_ignores_different_variant(libregistry, monkeypatch):
    """A newer version under a DIFFERENT suffix/variant (e.g. "-alpine"
    vs. the pinned "-slim") is a different image entirely, not a
    same-line release worth surfacing."""
    monkeypatch.setattr(libregistry, "list_tags", lambda host, repo: ["3.99-alpine"])
    assert libregistry.find_newest_same_variant_tag("docker.io", "library/python", "3.14-slim") == "3.14-slim"


def test_find_newest_same_variant_tag_compares_numeric_not_lexicographic(libregistry, monkeypatch):
    """ "1.9.0" must sort before "1.10.0" as a version — a plain string
    comparison would get this backwards."""
    monkeypatch.setattr(libregistry, "list_tags", lambda host, repo: ["1.9.0", "1.10.0"])
    assert libregistry.find_newest_same_variant_tag("docker.io", "org/repo", "1.9.0") == "1.10.0"


def test_find_newest_same_variant_tag_non_numeric_version_returns_itself(libregistry, monkeypatch):
    monkeypatch.setattr(libregistry, "list_tags", lambda host, repo: ["latest", "stable"])
    assert libregistry.find_newest_same_variant_tag("docker.io", "org/repo", "latest") == "latest"


def test_find_newest_same_variant_tag_ignores_bare_ci_run_id_tags(libregistry, monkeypatch):
    """Regression test for a real bug, confirmed live against ghcr.io/
    wearefrank/frank-gateway: alongside real 3-component releases and an
    old pre-semver 1-component build-number scheme, this repo ALSO
    publishes dozens of bare GitHub Actions run-ID tags with no suffix —
    e.g. "12294937630". Plain tuple comparison ((12294937630,) > (1, 1,
    0)) let a run-ID tag "win" purely because it parses to a SHORTER
    numeric tuple whose first component happens to be huge — the
    component-count guard must reject it outright, regardless of value,
    leaving the real newest same-arity release as the answer."""
    monkeypatch.setattr(
        libregistry,
        "list_tags",
        lambda host, repo: [
            "57",
            "104",  # old pre-semver build-number scheme (1 component)
            "1.0.0",
            "1.1.0",  # real releases (3 components) — same as version's own arity
            "10617868164",
            "12294937630",  # bare CI run-ID tags (1 component, no suffix)
        ],
    )
    assert libregistry.find_newest_same_variant_tag("ghcr.io", "wearefrank/frank-gateway", "1.1.0") == "1.1.0"


def test_find_newest_same_variant_tag_still_finds_newer_release_among_ci_run_id_tags(libregistry, monkeypatch):
    """Same shape as the regression above, but with a genuinely newer
    same-arity release ALSO published — it must still be found, not
    masked by the presence of the bare run-ID tags."""
    monkeypatch.setattr(
        libregistry,
        "list_tags",
        lambda host, repo: [
            "57",
            "104",
            "1.0.0",
            "1.1.0",
            "1.2.0",
            "10617868164",
            "12294937630",
        ],
    )
    assert libregistry.find_newest_same_variant_tag("ghcr.io", "wearefrank/frank-gateway", "1.1.0") == "1.2.0"


# --- is_sliding_tag ---


def test_is_sliding_tag_true_from_history_alone(libregistry, values_repo, monkeypatch):
    def fail_if_called(*a, **k):
        msg = "registry fallback should not be needed when history is conclusive"
        raise AssertionError(msg)

    monkeypatch.setattr(libregistry, "find_more_specific_tag_at_same_digest", fail_if_called)
    assert (
        libregistry.is_sliding_tag(values_repo, "docker.io", "library/solr", "9.10.1-slim", "sha256:" + "d" * 64)
        is True
    )


def test_is_sliding_tag_falls_back_to_registry_when_history_inconclusive(libregistry, values_repo, monkeypatch):
    monkeypatch.setattr(libregistry, "find_more_specific_tag_at_same_digest", lambda *a, **k: "5.1.0-extra")
    assert (
        libregistry.is_sliding_tag(values_repo, "docker.io", "ghcr.io/infonl/zac", "5.1.0", "sha256:" + "c" * 64)
        is True
    )


def test_is_sliding_tag_false_when_both_signals_say_no(libregistry, values_repo, monkeypatch):
    monkeypatch.setattr(libregistry, "find_more_specific_tag_at_same_digest", lambda *a, **k: None)
    assert (
        libregistry.is_sliding_tag(values_repo, "docker.io", "ghcr.io/infonl/zac", "5.1.0", "sha256:" + "c" * 64)
        is False
    )


def test_is_sliding_tag_false_when_registry_fallback_errors(libregistry, values_repo, monkeypatch):
    def raise_network_error(*a, **k):
        msg = "down"
        raise urllib.error.URLError(msg)

    monkeypatch.setattr(libregistry, "find_more_specific_tag_at_same_digest", raise_network_error)
    assert (
        libregistry.is_sliding_tag(values_repo, "docker.io", "ghcr.io/infonl/zac", "5.1.0", "sha256:" + "c" * 64)
        is False
    )
