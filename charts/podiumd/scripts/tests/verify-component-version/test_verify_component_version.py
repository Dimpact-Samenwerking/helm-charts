"""find_dependency, pull_chart, get_path, parse_repo,
registry_tag_exists, and main() — `helm pull` and all registry network calls
are mocked out, so these tests need neither `helm` nor network access.

Everything about a component (Helm repo, chart-version existence, actual
image repository string) is derived dynamically — from the dependency's
Chart.yaml entry and the pulled chart's own values.yaml — so the tests build
small synthetic Chart.yaml / pulled-chart fixtures rather than hardcoding
expected repo/registry data per component."""
import json
import subprocess
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
import yaml


def write_chart_yaml(vcv, dependencies):
    vcv.CHART_YAML.write_text(yaml.safe_dump({"dependencies": dependencies}))


# --- find_dependency ---

def test_find_dependency_by_name(vcv, tmp_path, monkeypatch):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    assert vcv.find_dependency("zaakafhandelcomponent")["alias"] == "zac"


def test_find_dependency_by_alias(vcv, tmp_path, monkeypatch):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    assert vcv.find_dependency("zac")["name"] == "zaakafhandelcomponent"


def test_find_dependency_not_found_raises(vcv, tmp_path, monkeypatch):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    with pytest.raises(SystemExit, match="no dependency named or aliased"):
        vcv.find_dependency("totally-unknown")


# chart_ref is a pure passthrough of lib.chart.chart_ref — covered directly
# in tests/lib/test_chart.py, no need to duplicate here.


# --- pull_chart ---

def test_pull_chart_success(vcv, tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""))
    ok, stderr = vcv.pull_chart({"name": "zac", "repository": "@zac"}, "1.0.297", tmp_path)
    assert ok is True
    assert stderr == ""


def test_pull_chart_failure(vcv, tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                         lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="not found"))
    ok, stderr = vcv.pull_chart({"name": "zac", "repository": "@zac"}, "9.9.9", tmp_path)
    assert ok is False
    assert stderr == "not found"


def test_pull_chart_https_repo_adds_repo_flag(vcv, tmp_path, monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    vcv.pull_chart({"name": "openforms", "repository": "https://maykinmedia.github.io/charts/"},
                    "1.12.0", tmp_path)
    assert "--repo" in captured["cmd"]
    assert "https://maykinmedia.github.io/charts/" in captured["cmd"]


# --- get_path ---

def test_get_path_nested(vcv):
    values = {"frontend": {"image": {"repository": "x/y"}}}
    assert vcv.get_path(values, "frontend.image.repository") == "x/y"


def test_get_path_missing_key_returns_none(vcv):
    assert vcv.get_path({"a": {}}, "a.b.c") is None


def test_get_path_non_dict_intermediate_returns_none(vcv):
    assert vcv.get_path({"a": "scalar"}, "a.b") is None


# --- parse_repo ---

@pytest.mark.parametrize("repo,expected", [
    ("ghcr.io/infonl/zaakafhandelcomponent", ("ghcr.io", "infonl/zaakafhandelcomponent")),
    ("openformulieren/open-forms", ("docker.io", "openformulieren/open-forms")),
    ("quay.io/keycloak/keycloak", ("quay.io", "keycloak/keycloak")),
    ("localhost:5000/x/y", ("localhost:5000", "x/y")),
])
def test_parse_repo(vcv, repo, expected):
    assert vcv.parse_repo(repo) == expected


# --- registry_tag_exists ---

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


def make_fake_urlopen(known_tags, expect_token_for=()):
    """known_tags: {(host, repo, tag): digest}. expect_token_for: hosts that
    must NOT receive a token-endpoint call before a manifest request (used to
    assert token-less registries like quay.io skip that round trip)."""
    token_calls = []

    def fake_urlopen(arg, *a, **kw):
        url = arg if isinstance(arg, str) else arg.full_url
        if "/token?" in url:
            token_calls.append(url)
            return FakeResponse(json.dumps({"token": "fake-token"}).encode())
        if "/manifests/" in url:
            host = url.split("://", 1)[1].split("/", 1)[0]
            _, rest = url.split("/v2/", 1)
            repo, tag = rest.split("/manifests/")
            digest = known_tags.get((host, repo, tag))
            if digest is None:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return FakeResponse(b"", headers={"Docker-Content-Digest": digest})
        raise AssertionError(f"unexpected URL in test: {url}")

    fake_urlopen.token_calls = token_calls
    return fake_urlopen


def test_registry_tag_exists_ghcr_found(vcv, monkeypatch):
    fake = make_fake_urlopen({("ghcr.io", "infonl/zaakafhandelcomponent", "5.4.3"): "sha256:abc"})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    exists, digest = vcv.registry_tag_exists("ghcr.io", "infonl/zaakafhandelcomponent", "5.4.3")
    assert exists is True
    assert digest == "sha256:abc"
    assert len(fake.token_calls) == 1  # ghcr needs a token


def test_registry_tag_exists_dockerhub_found(vcv, monkeypatch):
    fake = make_fake_urlopen({("registry-1.docker.io", "openformulieren/open-forms", "3.5.6"): "sha256:def"})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    exists, digest = vcv.registry_tag_exists("docker.io", "openformulieren/open-forms", "3.5.6")
    assert exists is True
    assert digest == "sha256:def"
    assert len(fake.token_calls) == 1  # docker hub needs a token too


def test_registry_tag_exists_missing(vcv, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", make_fake_urlopen({}))
    exists, digest = vcv.registry_tag_exists("ghcr.io", "infonl/zaakafhandelcomponent", "9.9.9")
    assert exists is False
    assert digest is None


def test_registry_tag_exists_token_less_registry_skips_token_call(vcv, monkeypatch):
    """quay.io / gcr.io / registry.k8s.io accept anonymous manifest GETs
    directly — no token round trip should happen for them."""
    fake = make_fake_urlopen({("quay.io", "keycloak/keycloak", "26.6.4"): "sha256:ghi"})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    exists, digest = vcv.registry_tag_exists("quay.io", "keycloak/keycloak", "26.6.4")
    assert exists is True
    assert fake.token_calls == []


def test_registry_tag_exists_reraises_non_404_errors(vcv, monkeypatch):
    def broken_urlopen(arg, *a, **kw):
        url = arg if isinstance(arg, str) else arg.full_url
        if "/token?" in url:
            return FakeResponse(json.dumps({"token": "fake-token"}).encode())
        raise urllib.error.HTTPError(url, 500, "Internal Server Error", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", broken_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        vcv.registry_tag_exists("ghcr.io", "infonl/zaakafhandelcomponent", "5.4.3")


# --- main() ---

def write_pulled_chart(dest, name, values_yaml):
    """Real `helm pull --untar --untardir dest` creates dest/<name>/... —
    main() looks for that nested directory."""
    chart_dir = dest / name
    chart_dir.mkdir()
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({"name": name, "version": "1.0.0"}))
    (chart_dir / "values.yaml").write_text(yaml.safe_dump(values_yaml))


def run_main(vcv, monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["verify-component-version.py", *argv])
    with pytest.raises(SystemExit) as exc_info:
        vcv.main()
    return exc_info.value.code


def test_main_single_image_component_success(vcv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])

    def fake_pull_chart(dep, version, dest):
        write_pulled_chart(dest, "zaakafhandelcomponent",
                            {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": ""}})
        return True, ""

    monkeypatch.setattr(vcv, "pull_chart", fake_pull_chart)
    monkeypatch.setattr(vcv, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:fake"))
    code = run_main(vcv, monkeypatch, ["zac", "5.4.3", "1.0.297"])
    assert code == 0
    out = capsys.readouterr().out
    assert "ghcr.io/infonl/zaakafhandelcomponent:5.4.3" in out
    assert "OK: both exist" in out


def test_main_multi_image_component_checks_both(vcv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zgw-office-addin", "repository": "@zgw-office-addin"}])

    def fake_pull_chart(dep, version, dest):
        write_pulled_chart(dest, "zgw-office-addin", {
            "frontend": {"image": {"repository": "ghcr.io/infonl/zgw-office-addin-frontend", "tag": "x"}},
            "backend": {"image": {"repository": "ghcr.io/infonl/zgw-office-addin-backend", "tag": "x"}},
        })
        return True, ""

    checked = []

    def fake_registry_tag_exists(host, repo, tag):
        checked.append(repo)
        return True, "sha256:fake"

    monkeypatch.setattr(vcv, "pull_chart", fake_pull_chart)
    monkeypatch.setattr(vcv, "registry_tag_exists", fake_registry_tag_exists)
    code = run_main(vcv, monkeypatch, ["zgw-office-addin", "0.11.0", "0.0.92"])
    assert code == 0
    assert checked == ["infonl/zgw-office-addin-frontend", "infonl/zgw-office-addin-backend"]


def test_main_dockerhub_component(vcv, tmp_path, monkeypatch, capsys):
    """openformulieren ships on Docker Hub — the registry must be inferred
    from the repository string, not assumed to be ghcr for everything."""
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "openforms", "alias": "openformulieren", "repository": "@maykinmedia"}])

    def fake_pull_chart(dep, version, dest):
        write_pulled_chart(dest, "openforms",
                            {"image": {"repository": "openformulieren/open-forms", "tag": "3.4.10"}})
        return True, ""

    checked_hosts = []

    def fake_registry_tag_exists(host, repo, tag):
        checked_hosts.append(host)
        return True, "sha256:fake"

    monkeypatch.setattr(vcv, "pull_chart", fake_pull_chart)
    monkeypatch.setattr(vcv, "registry_tag_exists", fake_registry_tag_exists)
    code = run_main(vcv, monkeypatch, ["openformulieren", "3.5.6", "1.12.0"])
    assert code == 0
    assert checked_hosts == ["docker.io"]


def test_main_missing_chart_version_skips_image_check(vcv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])

    monkeypatch.setattr(vcv, "pull_chart", lambda dep, version, dest: (False, "version not found"))
    registry_called = []
    monkeypatch.setattr(vcv, "registry_tag_exists",
                         lambda host, repo, tag: registry_called.append(1) or (True, "x"))
    code = run_main(vcv, monkeypatch, ["zac", "5.4.3", "9.9.9"])
    assert code == 1
    assert registry_called == []  # never even attempted — chart version doesn't exist
    out = capsys.readouterr().out
    assert "MISSING" in out
    assert "cannot look up its image repositories" in out


def test_main_missing_app_version_fails(vcv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])

    def fake_pull_chart(dep, version, dest):
        write_pulled_chart(dest, "zaakafhandelcomponent",
                            {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": ""}})
        return True, ""

    monkeypatch.setattr(vcv, "pull_chart", fake_pull_chart)
    monkeypatch.setattr(vcv, "registry_tag_exists", lambda host, repo, tag: (False, None))
    code = run_main(vcv, monkeypatch, ["zac", "9.9.9", "1.0.297"])
    assert code == 1
    out = capsys.readouterr().out
    assert "MISSING" in out
    assert "FAIL: one or more app image versions" in out


def test_main_no_repository_at_configured_path_fails(vcv, tmp_path, monkeypatch, capsys):
    """The chart was pulled fine, but COMPONENT_IMAGE_PATHS points somewhere
    that doesn't actually have a repository key — should fail clearly rather
    than silently report success with zero images checked."""
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])

    def fake_pull_chart(dep, version, dest):
        write_pulled_chart(dest, "zaakafhandelcomponent", {"somethingElse": {"repository": "x/y", "tag": "1"}})
        return True, ""

    monkeypatch.setattr(vcv, "pull_chart", fake_pull_chart)
    code = run_main(vcv, monkeypatch, ["zac", "5.4.3", "1.0.297"])
    assert code == 1
    assert "no repository found" in capsys.readouterr().out


def test_main_requires_exactly_three_arguments(vcv, monkeypatch):
    code = run_main(vcv, monkeypatch, ["zac", "5.4.3"])
    assert code == 1
