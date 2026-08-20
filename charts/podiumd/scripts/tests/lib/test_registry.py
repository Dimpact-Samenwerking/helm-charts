"""lib.registry.parse_repo / registry_tag_exists — no network needed,
urllib.request.urlopen is monkeypatched wherever a live fetch would happen."""
import json
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
