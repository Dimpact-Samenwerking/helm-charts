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


# --- find_sliding_tag_line_range / is_sliding_pin ---

GLOBAL_IMAGES_VALUES = """\
global:
  configuration:
    enabled: true
  images:
    nginx: &nginxImage
      repository: nginxinc/nginx-unprivileged
      tag: "1.31.3@sha256:aaaa"
      pullPolicy: IfNotPresent
    curl: &curlImage
      repository: curlimages/curl
      tag: "8.21.0@sha256:bbbb"
      pullPolicy: IfNotPresent

tags:
  redis: false

zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.1.0@sha256:cccc"
"""


def test_find_sliding_tag_line_range_finds_global_images_block(libregistry):
    lines = GLOBAL_IMAGES_VALUES.splitlines()
    start, end = libregistry.find_sliding_tag_line_range(lines)
    assert lines[start].strip() == "images:"
    assert lines[end].strip() == "tags:"


def test_find_sliding_tag_line_range_none_without_global_key(libregistry):
    assert libregistry.find_sliding_tag_line_range(["zac:\n", "  image:\n"]) is None


def test_find_sliding_tag_line_range_none_without_images_key(libregistry):
    lines = "global:\n  configuration:\n    enabled: true\n".splitlines()
    assert libregistry.find_sliding_tag_line_range(lines) is None


def test_is_sliding_pin_true_inside_global_images_block(libregistry):
    lines = GLOBAL_IMAGES_VALUES.splitlines()
    sliding_range = libregistry.find_sliding_tag_line_range(lines)
    nginx_tag_line = next(i + 1 for i, line in enumerate(lines) if "1.31.3@sha256" in line)
    assert libregistry.is_sliding_pin(nginx_tag_line, sliding_range) is True


def test_is_sliding_pin_false_outside_global_images_block(libregistry):
    lines = GLOBAL_IMAGES_VALUES.splitlines()
    sliding_range = libregistry.find_sliding_tag_line_range(lines)
    zac_tag_line = next(i + 1 for i, line in enumerate(lines) if "5.1.0@sha256" in line)
    assert libregistry.is_sliding_pin(zac_tag_line, sliding_range) is False


def test_is_sliding_pin_false_when_no_range_found(libregistry):
    assert libregistry.is_sliding_pin(5, None) is False
