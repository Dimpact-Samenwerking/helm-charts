"""ghcr_tag_exists, chart_version_exists, and main() — all network calls
mocked out via a fake urllib.request.urlopen, using ZAC's real (previously
verified) digest/chart data as the worked example, so tests are hermetic and
don't depend on GHCR/GitHub Pages being reachable."""
import json
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
import yaml

ZAC_REPO = "infonl/zaakafhandelcomponent"
ZAC_TAG = "5.4.3"
ZAC_DIGEST = "sha256:c5640dd38aef91fa90b4859f01d631fb19c17146b3920323520a9e75f2632812"

ZAC_INDEX_YAML = yaml.safe_dump({
    "apiVersion": "v1",
    "entries": {
        "zaakafhandelcomponent": [
            {"version": "1.0.297", "appVersion": "5.5", "urls": ["https://example/zaakafhandelcomponent-1.0.297.tgz"]},
            {"version": "1.0.294", "appVersion": "5.4", "urls": ["https://example/zaakafhandelcomponent-1.0.294.tgz"]},
        ]
    },
}).encode()


class FakeResponse:
    def __init__(self, data, headers=None):
        self._data = data
        self.headers = headers or {}

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def make_fake_urlopen(known_tags):
    """known_tags: dict mapping (repo, tag) -> digest-or-None (None means the
    tag doesn't exist and the manifest request should 404)."""

    def fake_urlopen(arg, *a, **kw):
        url = arg if isinstance(arg, str) else arg.full_url
        if "/token?" in url:
            return FakeResponse(json.dumps({"token": "fake-token"}).encode())
        if "/manifests/" in url:
            # url looks like https://ghcr.io/v2/<repo>/manifests/<tag>
            _, rest = url.split("/v2/", 1)
            repo, tag = rest.split("/manifests/")
            digest = known_tags.get((repo, tag))
            if digest is None:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return FakeResponse(b"", headers={"Docker-Content-Digest": digest})
        if url.endswith("index.yaml"):
            return FakeResponse(ZAC_INDEX_YAML)
        raise AssertionError(f"unexpected URL in test: {url}")

    return fake_urlopen


# --- ghcr_tag_exists ---

def test_ghcr_tag_exists_found(vcv, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", make_fake_urlopen({(ZAC_REPO, ZAC_TAG): ZAC_DIGEST}))
    exists, digest = vcv.ghcr_tag_exists(ZAC_REPO, ZAC_TAG)
    assert exists is True
    assert digest == ZAC_DIGEST


def test_ghcr_tag_exists_missing(vcv, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", make_fake_urlopen({}))
    exists, digest = vcv.ghcr_tag_exists(ZAC_REPO, "9.9.9")
    assert exists is False
    assert digest is None


def test_ghcr_tag_exists_reraises_non_404_errors(vcv, monkeypatch):
    def broken_urlopen(arg, *a, **kw):
        url = arg if isinstance(arg, str) else arg.full_url
        if "/token?" in url:
            return FakeResponse(json.dumps({"token": "fake-token"}).encode())
        raise urllib.error.HTTPError(url, 500, "Internal Server Error", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", broken_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        vcv.ghcr_tag_exists(ZAC_REPO, ZAC_TAG)


# --- chart_version_exists ---

def test_chart_version_exists_found(vcv, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", make_fake_urlopen({}))
    exists, entry = vcv.chart_version_exists(
        "https://infonl.github.io/dimpact-zaakafhandelcomponent/index.yaml",
        "zaakafhandelcomponent", "1.0.297")
    assert exists is True
    assert entry["appVersion"] == "5.5"


def test_chart_version_exists_missing(vcv, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", make_fake_urlopen({}))
    exists, entry = vcv.chart_version_exists(
        "https://infonl.github.io/dimpact-zaakafhandelcomponent/index.yaml",
        "zaakafhandelcomponent", "1.0.999")
    assert exists is False
    assert entry is None


def test_chart_version_exists_unknown_chart_name(vcv, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", make_fake_urlopen({}))
    exists, entry = vcv.chart_version_exists(
        "https://infonl.github.io/dimpact-zaakafhandelcomponent/index.yaml",
        "totally-unknown-chart", "1.0.0")
    assert exists is False
    assert entry is None


# --- main() ---

def run_main(vcv, monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["verify-component-version.py", *argv])
    with pytest.raises(SystemExit) as exc_info:
        vcv.main()
    return exc_info.value.code


def test_main_exits_zero_when_both_exist(vcv, monkeypatch, capsys):
    monkeypatch.setattr(vcv, "ghcr_tag_exists", lambda repo, tag: (True, ZAC_DIGEST))
    monkeypatch.setattr(vcv, "chart_version_exists",
                         lambda url, name, version: (True, {"appVersion": "5.5"}))
    code = run_main(vcv, monkeypatch, ["zac", ZAC_TAG, "1.0.297"])
    assert code == 0
    out = capsys.readouterr().out
    assert "FOUND" in out
    assert "OK: both exist" in out


def test_main_exits_nonzero_when_app_version_missing(vcv, monkeypatch, capsys):
    monkeypatch.setattr(vcv, "ghcr_tag_exists", lambda repo, tag: (False, None))
    monkeypatch.setattr(vcv, "chart_version_exists",
                         lambda url, name, version: (True, {"appVersion": "0.2.0"}))
    code = run_main(vcv, monkeypatch, ["zgw-office-addin", "0.12.0", "0.0.92"])
    assert code == 1
    out = capsys.readouterr().out
    assert "MISSING" in out
    assert "FAIL" in out


def test_main_exits_nonzero_when_chart_version_missing(vcv, monkeypatch, capsys):
    monkeypatch.setattr(vcv, "ghcr_tag_exists", lambda repo, tag: (True, ZAC_DIGEST))
    monkeypatch.setattr(vcv, "chart_version_exists", lambda url, name, version: (False, None))
    code = run_main(vcv, monkeypatch, ["zac", ZAC_TAG, "1.0.999"])
    assert code == 1


def test_main_checks_both_office_addin_images(vcv, monkeypatch, capsys):
    """zgw-office-addin ships two images that must both be checked."""
    checked_repos = []

    def fake_ghcr(repo, tag):
        checked_repos.append(repo)
        return True, "sha256:fake"

    monkeypatch.setattr(vcv, "ghcr_tag_exists", fake_ghcr)
    monkeypatch.setattr(vcv, "chart_version_exists", lambda url, name, version: (True, {}))
    run_main(vcv, monkeypatch, ["zgw-office-addin", "0.11.0", "0.0.92"])
    assert checked_repos == ["infonl/zgw-office-addin-frontend", "infonl/zgw-office-addin-backend"]


def test_main_rejects_unknown_component(vcv, monkeypatch, capsys):
    code = run_main(vcv, monkeypatch, ["totally-unknown", "1.0.0", "1.0.0"])
    assert code == 1
    assert "unknown component" in capsys.readouterr().out


def test_main_requires_exactly_three_arguments(vcv, monkeypatch, capsys):
    code = run_main(vcv, monkeypatch, ["zac", "5.4.3"])
    assert code == 1
