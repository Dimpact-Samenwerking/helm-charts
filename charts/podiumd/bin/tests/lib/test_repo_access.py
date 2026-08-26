"""lib.repo_access — dependency_repos, _check_http_repo, _check_oci_repo,
check_repo_access. No network needed: urllib.request.urlopen and
lib.registry.registry_tag_exists are monkeypatched wherever a live fetch
would otherwise happen."""
import urllib.error

import yaml


def write_chart_yaml(chart_dir, deps):
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}), encoding="utf-8")


# --- dependency_repos ---

def test_dependency_repos_resolves_alias_to_http(librepoaccess, tmp_path):
    write_chart_yaml(tmp_path, [{"name": "openzaak", "version": "1.14.2", "repository": "@maykinmedia"}])
    assert librepoaccess.dependency_repos(tmp_path) == [
        ("openzaak", "http", "https://maykinmedia.github.io/charts/"),
    ]


def test_dependency_repos_direct_http_url_passed_through(librepoaccess, tmp_path):
    write_chart_yaml(tmp_path, [{"name": "zaakbrug", "version": "2.3.28",
                                  "repository": "https://wearefrank.github.io/charts"}])
    assert librepoaccess.dependency_repos(tmp_path) == [
        ("zaakbrug", "http", "https://wearefrank.github.io/charts"),
    ]


def test_dependency_repos_oci_combines_path_and_chart_name(librepoaccess, tmp_path):
    write_chart_yaml(tmp_path, [{"name": "kiss-chart", "version": "3.0.0",
                                  "repository": "oci://ghcr.io/klantinteractie-servicesysteem"}])
    assert librepoaccess.dependency_repos(tmp_path) == [
        ("kiss-chart", "oci", ("ghcr.io", "klantinteractie-servicesysteem/kiss-chart", "3.0.0")),
    ]


def test_dependency_repos_skips_local_file_dependency(librepoaccess, tmp_path):
    write_chart_yaml(tmp_path, [{"name": "mi-data", "version": "1.0.0", "repository": "file://../mi-data"}])
    assert librepoaccess.dependency_repos(tmp_path) == []


def test_dependency_repos_uses_alias_name_when_present(librepoaccess, tmp_path):
    write_chart_yaml(tmp_path, [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297",
                                  "repository": "@zac"}])
    names = [name for name, _, _ in librepoaccess.dependency_repos(tmp_path)]
    assert names == ["zac"]


def test_dependency_repos_no_dependencies_key(librepoaccess, tmp_path):
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"name": "podiumd"}), encoding="utf-8")
    assert librepoaccess.dependency_repos(tmp_path) == []


# --- _check_http_repo ---

class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_check_http_repo_ok(librepoaccess, monkeypatch):
    def fake_urlopen(url, timeout=None):
        assert url == "https://maykinmedia.github.io/charts/index.yaml"
        assert timeout == librepoaccess.TIMEOUT_SECONDS
        return FakeResponse()

    monkeypatch.setattr(librepoaccess.urllib.request, "urlopen", fake_urlopen)
    ok, error = librepoaccess._check_http_repo("https://maykinmedia.github.io/charts/")
    assert ok is True
    assert error is None


def test_check_http_repo_adds_missing_trailing_slash(librepoaccess, monkeypatch):
    def fake_urlopen(url, timeout=None):
        assert url == "https://wearefrank.github.io/charts/index.yaml"
        return FakeResponse()

    monkeypatch.setattr(librepoaccess.urllib.request, "urlopen", fake_urlopen)
    ok, _ = librepoaccess._check_http_repo("https://wearefrank.github.io/charts")
    assert ok is True


def test_check_http_repo_http_error(librepoaccess, monkeypatch):
    def fake_urlopen(url, timeout=None):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(librepoaccess.urllib.request, "urlopen", fake_urlopen)
    ok, error = librepoaccess._check_http_repo("https://private.example.com/charts/")
    assert ok is False
    assert "HTTP 403" in error


def test_check_http_repo_unreachable(librepoaccess, monkeypatch):
    def fake_urlopen(url, timeout=None):
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(librepoaccess.urllib.request, "urlopen", fake_urlopen)
    ok, error = librepoaccess._check_http_repo("https://nonexistent.invalid/charts/")
    assert ok is False
    assert "not known" in error


# --- _check_oci_repo ---

def test_check_oci_repo_ok(librepoaccess, monkeypatch):
    monkeypatch.setattr(librepoaccess, "registry_tag_exists",
                         lambda host, repo, tag, timeout=None: (True, "sha256:" + "a" * 64))
    ok, error = librepoaccess._check_oci_repo("ghcr.io", "org/chart", "1.0.0")
    assert ok is True
    assert error is None


def test_check_oci_repo_not_found(librepoaccess, monkeypatch):
    monkeypatch.setattr(librepoaccess, "registry_tag_exists",
                         lambda host, repo, tag, timeout=None: (False, None))
    ok, error = librepoaccess._check_oci_repo("ghcr.io", "org/chart", "9.9.9")
    assert ok is False
    assert "not found" in error


def test_check_oci_repo_network_error(librepoaccess, monkeypatch):
    def raise_error(host, repo, tag, timeout=None):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(librepoaccess, "registry_tag_exists", raise_error)
    ok, error = librepoaccess._check_oci_repo("ghcr.io", "org/chart", "1.0.0")
    assert ok is False
    assert "timed out" in error


def test_check_oci_repo_passes_timeout(librepoaccess, monkeypatch):
    seen = {}

    def fake_registry_tag_exists(host, repo, tag, timeout=None):
        seen["timeout"] = timeout
        return True, "sha256:" + "a" * 64

    monkeypatch.setattr(librepoaccess, "registry_tag_exists", fake_registry_tag_exists)
    librepoaccess._check_oci_repo("ghcr.io", "org/chart", "1.0.0")
    assert seen["timeout"] == librepoaccess.TIMEOUT_SECONDS


# --- check_repo_access ---

def test_check_repo_access_all_reachable(librepoaccess, tmp_path, monkeypatch):
    write_chart_yaml(tmp_path, [
        {"name": "openzaak", "version": "1.14.2", "repository": "@maykinmedia"},
        {"name": "kiss-chart", "version": "3.0.0", "repository": "oci://ghcr.io/klantinteractie-servicesysteem"},
    ])
    monkeypatch.setattr(librepoaccess, "_check_http_repo", lambda url: (True, None))
    monkeypatch.setattr(librepoaccess, "_check_oci_repo", lambda host, repo, tag: (True, None))
    ok, detail = librepoaccess.check_repo_access(tmp_path)
    assert ok is True
    assert "2 repo(s) reachable" in detail


def test_check_repo_access_dedupes_shared_repo(librepoaccess, tmp_path, monkeypatch):
    """8 @maykinmedia dependencies must trigger exactly one reachability
    check against that repo, not eight identical ones."""
    write_chart_yaml(tmp_path, [
        {"name": f"comp-{i}", "version": "1.0.0", "repository": "@maykinmedia"} for i in range(8)
    ])
    calls = []
    monkeypatch.setattr(librepoaccess, "_check_http_repo", lambda url: (calls.append(url), (True, None))[1])
    ok, detail = librepoaccess.check_repo_access(tmp_path)
    assert ok is True
    assert len(calls) == 1
    assert "1 repo(s) reachable (8 dependencies)" in detail


def test_check_repo_access_fails_on_unreachable_repo(librepoaccess, tmp_path, monkeypatch, capsys):
    write_chart_yaml(tmp_path, [
        {"name": "openzaak", "version": "1.14.2", "repository": "@maykinmedia"},
        {"name": "zaakbrug", "version": "2.3.28", "repository": "https://wearefrank.github.io/charts"},
    ])
    monkeypatch.setattr(librepoaccess, "_check_http_repo",
                         lambda url: (True, None) if "maykinmedia" in url else (False, "HTTP 403 fetching " + url))
    ok, detail = librepoaccess.check_repo_access(tmp_path)
    assert ok is False
    assert "1/2 repo(s) unreachable or unauthorized" in detail
    assert "zaakbrug" in detail
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "[OK]" in out


def test_check_repo_access_no_network_dependencies(librepoaccess, tmp_path):
    write_chart_yaml(tmp_path, [{"name": "mi-data", "version": "1.0.0", "repository": "file://../mi-data"}])
    ok, detail = librepoaccess.check_repo_access(tmp_path)
    assert ok is True
    assert "0 repo(s) reachable" in detail
