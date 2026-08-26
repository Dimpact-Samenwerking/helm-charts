"""lib.repo_access — dependency_repos, image_repos, _check_http_repo,
_check_registry_repo, check_repo_access. No network needed:
urllib.request.urlopen and lib.registry.registry_tag_exists are
monkeypatched wherever a live fetch would otherwise happen."""
import urllib.error

import yaml


def write_chart_yaml(chart_dir, deps):
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}), encoding="utf-8")


def write_values(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


# --- dependency_repos ---

def test_dependency_repos_resolves_alias_to_http(librepoaccess, tmp_path):
    write_chart_yaml(tmp_path, [{"name": "openzaak", "version": "1.14.2", "repository": "@maykinmedia"}])
    name, line, kind, target = librepoaccess.dependency_repos(tmp_path)[0]
    assert (name, kind, target) == ("openzaak", "http", "https://maykinmedia.github.io/charts/")
    assert line == 2


def test_dependency_repos_direct_http_url_passed_through(librepoaccess, tmp_path):
    write_chart_yaml(tmp_path, [{"name": "zaakbrug", "version": "2.3.28",
                                  "repository": "https://wearefrank.github.io/charts"}])
    name, line, kind, target = librepoaccess.dependency_repos(tmp_path)[0]
    assert (name, kind, target) == ("zaakbrug", "http", "https://wearefrank.github.io/charts")


def test_dependency_repos_oci_combines_path_and_chart_name(librepoaccess, tmp_path):
    write_chart_yaml(tmp_path, [{"name": "kiss-chart", "version": "3.0.0",
                                  "repository": "oci://ghcr.io/klantinteractie-servicesysteem"}])
    name, line, kind, target = librepoaccess.dependency_repos(tmp_path)[0]
    assert (name, kind, target) == (
        "kiss-chart", "oci", ("ghcr.io", "klantinteractie-servicesysteem/kiss-chart", "3.0.0"))


def test_dependency_repos_skips_local_file_dependency(librepoaccess, tmp_path):
    write_chart_yaml(tmp_path, [{"name": "mi-data", "version": "1.0.0", "repository": "file://../mi-data"}])
    assert librepoaccess.dependency_repos(tmp_path) == []


def test_dependency_repos_uses_alias_name_when_present(librepoaccess, tmp_path):
    write_chart_yaml(tmp_path, [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297",
                                  "repository": "@zac"}])
    names = [name for name, _, _, _ in librepoaccess.dependency_repos(tmp_path)]
    assert names == ["zac"]


def test_dependency_repos_no_dependencies_key(librepoaccess, tmp_path):
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"name": "podiumd"}), encoding="utf-8")
    assert librepoaccess.dependency_repos(tmp_path) == []


def test_dependency_repos_finds_correct_line_for_each_dependency(librepoaccess, tmp_path):
    (tmp_path / "Chart.yaml").write_text(
        "dependencies:\n"
        "  - name: openzaak\n"
        "    version: 1.14.2\n"
        "    repository: \"@maykinmedia\"\n"
        "  - name: zaakbrug\n"
        "    version: 2.3.28\n"
        "    repository: \"https://wearefrank.github.io/charts\"\n",
        encoding="utf-8",
    )
    repos = {name: line for name, line, _, _ in librepoaccess.dependency_repos(tmp_path)}
    assert repos == {"openzaak": 2, "zaakbrug": 5}


# --- image_repos ---

def test_image_repos_groups_by_repository_and_version(librepoaccess, tmp_path):
    write_values(tmp_path, (
        "pabc:\n"
        "  image:\n"
        "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
        f'    tag: "1.1.1@sha256:{"a" * 64}"\n'
    ))
    target, lines = librepoaccess.image_repos(tmp_path / "values.yaml")[0]
    assert target == ("ghcr.io", "platform-autorisatie-beheer-component/pabc-api", "1.1.1")
    assert lines == [4]


def test_image_repos_groups_multiple_pins_of_the_same_image(librepoaccess, tmp_path):
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
        "b:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    results = librepoaccess.image_repos(tmp_path / "values.yaml")
    assert len(results) == 1
    target, lines = results[0]
    assert target == ("docker.io", "org/repo", "1.0.0")
    assert lines == [4, 8]


def test_image_repos_skips_pins_needing_subchart_default_fallback(librepoaccess, tmp_path):
    write_values(tmp_path, (
        "openzaak:\n"
        "  image:\n"
        f'    tag: "1.14.2@sha256:{"a" * 64}"\n'
    ))
    assert librepoaccess.image_repos(tmp_path / "values.yaml") == []


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


# --- _check_registry_repo ---

def test_check_registry_repo_ok(librepoaccess, monkeypatch):
    monkeypatch.setattr(librepoaccess, "registry_tag_exists",
                         lambda host, repo, tag, timeout=None: (True, "sha256:" + "a" * 64))
    ok, error = librepoaccess._check_registry_repo("ghcr.io", "org/chart", "1.0.0")
    assert ok is True
    assert error is None


def test_check_registry_repo_not_found(librepoaccess, monkeypatch):
    monkeypatch.setattr(librepoaccess, "registry_tag_exists",
                         lambda host, repo, tag, timeout=None: (False, None))
    ok, error = librepoaccess._check_registry_repo("ghcr.io", "org/chart", "9.9.9")
    assert ok is False
    assert "not found" in error


def test_check_registry_repo_network_error(librepoaccess, monkeypatch):
    def raise_error(host, repo, tag, timeout=None):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(librepoaccess, "registry_tag_exists", raise_error)
    ok, error = librepoaccess._check_registry_repo("ghcr.io", "org/chart", "1.0.0")
    assert ok is False
    assert "timed out" in error


def test_check_registry_repo_passes_timeout(librepoaccess, monkeypatch):
    seen = {}

    def fake_registry_tag_exists(host, repo, tag, timeout=None):
        seen["timeout"] = timeout
        return True, "sha256:" + "a" * 64

    monkeypatch.setattr(librepoaccess, "registry_tag_exists", fake_registry_tag_exists)
    librepoaccess._check_registry_repo("ghcr.io", "org/chart", "1.0.0")
    assert seen["timeout"] == librepoaccess.TIMEOUT_SECONDS


# --- check_repo_access ---

def test_check_repo_access_all_reachable(librepoaccess, tmp_path, monkeypatch):
    write_chart_yaml(tmp_path, [
        {"name": "openzaak", "version": "1.14.2", "repository": "@maykinmedia"},
        {"name": "kiss-chart", "version": "3.0.0", "repository": "oci://ghcr.io/klantinteractie-servicesysteem"},
    ])
    write_values(tmp_path, (
        "pabc:\n"
        "  image:\n"
        "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
        f'    tag: "1.1.1@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(librepoaccess, "_check_http_repo", lambda url: (True, None))
    monkeypatch.setattr(librepoaccess, "_check_registry_repo", lambda host, repo, tag: (True, None))
    ok, detail = librepoaccess.check_repo_access(tmp_path)
    assert ok is True
    assert "3 repo(s)/image(s) reachable" in detail


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
    assert "1 repo(s)/image(s) reachable (8 references, 0 denylisted, skipped)" in detail


def test_check_repo_access_no_values_yaml_only_checks_charts(librepoaccess, tmp_path, monkeypatch):
    write_chart_yaml(tmp_path, [{"name": "openzaak", "version": "1.14.2", "repository": "@maykinmedia"}])
    monkeypatch.setattr(librepoaccess, "_check_http_repo", lambda url: (True, None))
    ok, detail = librepoaccess.check_repo_access(tmp_path)
    assert ok is True
    assert "1 repo(s)/image(s) reachable (1 references, 0 denylisted, skipped)" in detail


def test_check_repo_access_reports_kind_file_and_line_for_chart_repo(librepoaccess, tmp_path, monkeypatch, capsys):
    write_chart_yaml(tmp_path, [{"name": "zaakbrug", "version": "2.3.28",
                                  "repository": "https://wearefrank.github.io/charts"}])
    monkeypatch.setattr(librepoaccess, "_check_http_repo", lambda url: (True, None))
    librepoaccess.check_repo_access(tmp_path)
    out = capsys.readouterr().out
    assert "[OK] chart" in out
    assert "zaakbrug" in out
    assert "Chart.yaml:2" in out


def test_check_repo_access_reports_kind_file_and_line_for_image(librepoaccess, tmp_path, monkeypatch, capsys):
    write_chart_yaml(tmp_path, [])
    write_values(tmp_path, (
        "pabc:\n"
        "  image:\n"
        "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
        f'    tag: "1.1.1@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(librepoaccess, "_check_registry_repo", lambda host, repo, tag: (True, None))
    librepoaccess.check_repo_access(tmp_path)
    out = capsys.readouterr().out
    assert "[OK] image" in out
    assert "ghcr.io/platform-autorisatie-beheer-component/pabc-api:1.1.1" in out
    assert "values.yaml:4" in out


def test_check_repo_access_fails_on_unreachable_chart_repo(librepoaccess, tmp_path, monkeypatch):
    write_chart_yaml(tmp_path, [
        {"name": "openzaak", "version": "1.14.2", "repository": "@maykinmedia"},
        {"name": "zaakbrug", "version": "2.3.28", "repository": "https://wearefrank.github.io/charts"},
    ])
    monkeypatch.setattr(librepoaccess, "_check_http_repo",
                         lambda url: (True, None) if "maykinmedia" in url else (False, "HTTP 403 fetching " + url))
    ok, detail = librepoaccess.check_repo_access(tmp_path)
    assert ok is False
    assert "1/2 repo(s)/image(s) unreachable or unauthorized" in detail
    assert "zaakbrug" in detail


def test_check_repo_access_fails_on_unreachable_image(librepoaccess, tmp_path, monkeypatch, capsys):
    write_chart_yaml(tmp_path, [])
    write_values(tmp_path, (
        "pabc:\n"
        "  image:\n"
        "    repository: ghcr.io/groundnuty/k8s-wait-for\n"
        f'    tag: "v2.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(librepoaccess, "_check_registry_repo", lambda host, repo, tag: (False, "not found"))
    ok, detail = librepoaccess.check_repo_access(tmp_path)
    assert ok is False
    assert "image" in detail
    assert "k8s-wait-for" in detail
    out = capsys.readouterr().out
    assert "[FAIL] image" in out


def test_check_repo_access_no_network_dependencies_or_images(librepoaccess, tmp_path):
    write_chart_yaml(tmp_path, [{"name": "mi-data", "version": "1.0.0", "repository": "file://../mi-data"}])
    write_values(tmp_path, "mi-data:\n  enabled: true\n")
    ok, detail = librepoaccess.check_repo_access(tmp_path)
    assert ok is True
    assert "0 repo(s)/image(s) reachable" in detail


# --- is_denylisted_host ---

def test_is_denylisted_host_matches_azurecr(librepoaccess):
    assert librepoaccess.is_denylisted_host("acrprodmgmt.azurecr.io") is True
    assert librepoaccess.is_denylisted_host("azurecr.io") is True


def test_is_denylisted_host_ignores_unrelated_host(librepoaccess):
    assert librepoaccess.is_denylisted_host("ghcr.io") is False
    assert librepoaccess.is_denylisted_host("docker.io") is False


# --- check_repo_access: denylist ---

def test_check_repo_access_skips_denylisted_chart_repo(librepoaccess, tmp_path, monkeypatch, capsys):
    write_chart_yaml(tmp_path, [{"name": "pabc", "version": "1.1.1",
                                  "repository": "oci://acrprodmgmt.azurecr.io/some-namespace"}])

    def fail_if_called(*a, **kw):
        raise AssertionError("a denylisted host must never actually be checked")

    monkeypatch.setattr(librepoaccess, "_check_registry_repo", fail_if_called)
    ok, detail = librepoaccess.check_repo_access(tmp_path)
    assert ok is True
    assert "0 repo(s)/image(s) reachable" in detail
    assert "1 denylisted, skipped" in detail
    out = capsys.readouterr().out
    assert "[SKIP ] chart" in out
    assert "acrprodmgmt.azurecr.io is denylisted" in out


def test_check_repo_access_skips_denylisted_image(librepoaccess, tmp_path, monkeypatch, capsys):
    write_chart_yaml(tmp_path, [])
    write_values(tmp_path, (
        "pabc:\n"
        "  image:\n"
        "    repository: acrprodmgmt.azurecr.io/platform-autorisatie-beheer-component/pabc-api\n"
        f'    tag: "1.1.1@sha256:{"a" * 64}"\n'
    ))

    def fail_if_called(*a, **kw):
        raise AssertionError("a denylisted host must never actually be checked")

    monkeypatch.setattr(librepoaccess, "_check_registry_repo", fail_if_called)
    ok, detail = librepoaccess.check_repo_access(tmp_path)
    assert ok is True
    assert "1 denylisted, skipped" in detail
    out = capsys.readouterr().out
    assert "[SKIP ] image" in out


def test_check_repo_access_denylist_does_not_shadow_unrelated_failure(librepoaccess, tmp_path, monkeypatch):
    """A denylisted entry is skipped on its own — it must not mask a real
    failure elsewhere in the same run."""
    write_chart_yaml(tmp_path, [
        {"name": "pabc", "version": "1.1.1", "repository": "oci://acrprodmgmt.azurecr.io/some-namespace"},
        {"name": "zaakbrug", "version": "2.3.28", "repository": "https://wearefrank.github.io/charts"},
    ])
    monkeypatch.setattr(librepoaccess, "_check_registry_repo",
                         lambda *a: (_ for _ in ()).throw(AssertionError("denylisted host checked")))
    monkeypatch.setattr(librepoaccess, "_check_http_repo", lambda url: (False, "HTTP 403"))
    ok, detail = librepoaccess.check_repo_access(tmp_path)
    assert ok is False
    assert "1/1 repo(s)/image(s) unreachable" in detail
    assert "1 denylisted, skipped" in detail
