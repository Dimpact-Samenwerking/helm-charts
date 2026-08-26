"""lib.dependencies — ensure_repos_configured, check_dependencies. `helm`
subprocess calls mocked out via libdependencies.run, so these tests need
neither the binary installed nor network access."""
from types import SimpleNamespace


def fake_run(returncode=0, stdout="", stderr=""):
    def _run(cmd, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    return _run


# --- ensure_repos_configured ---

def test_ensure_repos_configured_success(libdependencies, monkeypatch):
    monkeypatch.setattr(libdependencies, "REQUIRED_REPOS", {"zac": "https://example.invalid/zac/"})
    monkeypatch.setattr(libdependencies, "run", fake_run(0))
    ok, msg = libdependencies.ensure_repos_configured()
    assert ok is True
    assert msg == "repos configured"


def test_ensure_repos_configured_repo_add_failure(libdependencies, monkeypatch):
    monkeypatch.setattr(libdependencies, "REQUIRED_REPOS", {"zac": "https://example.invalid/zac/"})
    monkeypatch.setattr(libdependencies, "run", fake_run(1, "", "network unreachable"))
    ok, msg = libdependencies.ensure_repos_configured()
    assert ok is False
    assert "helm repo add zac failed" in msg
    assert "network unreachable" in msg


def test_ensure_repos_configured_repo_update_failure(libdependencies, monkeypatch):
    monkeypatch.setattr(libdependencies, "REQUIRED_REPOS", {"zac": "https://example.invalid/zac/"})

    def sequenced_run(cmd, **kwargs):
        if cmd[1] == "repo" and cmd[2] == "add":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(libdependencies, "run", sequenced_run)
    ok, msg = libdependencies.ensure_repos_configured()
    assert ok is False
    assert "helm repo update failed" in msg


# --- check_dependencies ---

def test_check_dependencies_success(libdependencies, tmp_path, monkeypatch):
    dep_list_output = "NAME\tVERSION\tREPOSITORY\tSTATUS\na\t1.0\t@x\tok\nb\t2.0\t@x\tok\n"

    def sequenced_run(cmd, **kwargs):
        if cmd[2] == "update":
            # real `helm dependency update` (re-)creates charts/*.tgz; the
            # function rm -rf's the old charts/ dir first, so the mock must
            # simulate that side effect for the later glob() count to match
            charts_dir = tmp_path / "charts"
            charts_dir.mkdir()
            (charts_dir / "a.tgz").touch()
            (charts_dir / "b.tgz").touch()
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=dep_list_output, stderr="")

    monkeypatch.setattr(libdependencies, "run", sequenced_run)
    ok, detail = libdependencies.check_dependencies(tmp_path)
    assert ok is True
    assert "2 dependencies bundled" in detail


def test_check_dependencies_update_failure(libdependencies, tmp_path, monkeypatch):
    monkeypatch.setattr(libdependencies, "run", fake_run(1, "", "network error"))
    monkeypatch.setattr(libdependencies.time, "sleep", lambda *_: None)
    ok, detail = libdependencies.check_dependencies(tmp_path)
    assert ok is False
    assert "update failed" in detail
    assert "after 3 attempt" in detail


def test_check_dependencies_retries_then_succeeds(libdependencies, tmp_path, monkeypatch):
    dep_list_output = "NAME\tVERSION\tREPOSITORY\tSTATUS\na\t1.0\t@x\tok\n"
    calls = {"update": 0}

    def sequenced_run(cmd, **kwargs):
        if cmd[2] == "update":
            calls["update"] += 1
            if calls["update"] < 2:
                return SimpleNamespace(returncode=1, stdout="", stderr="network error")
            charts_dir = tmp_path / "charts"
            charts_dir.mkdir()
            (charts_dir / "a.tgz").touch()
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=dep_list_output, stderr="")

    monkeypatch.setattr(libdependencies, "run", sequenced_run)
    monkeypatch.setattr(libdependencies.time, "sleep", lambda *_: None)
    ok, detail = libdependencies.check_dependencies(tmp_path)
    assert ok is True
    assert calls["update"] == 2


def test_check_dependencies_azure_not_logged_in_skips_retry(libdependencies, tmp_path, monkeypatch):
    calls = {"update": 0}

    def sequenced_run(cmd, **kwargs):
        if cmd[:2] == ["az", "account"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="Please run 'az login'")
        calls["update"] += 1
        return SimpleNamespace(
            returncode=1, stdout="",
            stderr="Error: could not download from https://acrprodmgmt.azurecr.io/helm/foo: 401 Unauthorized",
        )

    monkeypatch.setattr(libdependencies, "run", sequenced_run)
    monkeypatch.setattr(libdependencies.time, "sleep", lambda *_: None)
    ok, detail = libdependencies.check_dependencies(tmp_path)
    assert ok is False
    assert calls["update"] == 1  # no retries once an auth problem is confirmed
    assert "acrprodmgmt.azurecr.io" in detail
    assert "az login" in detail
    assert "az acr login --name acrprodmgmt" in detail


def test_check_dependencies_azure_logged_in_still_retries(libdependencies, tmp_path, monkeypatch):
    calls = {"update": 0}

    def sequenced_run(cmd, **kwargs):
        if cmd[:2] == ["az", "account"]:
            return SimpleNamespace(returncode=0, stdout="{}", stderr="")
        calls["update"] += 1
        return SimpleNamespace(
            returncode=1, stdout="",
            stderr="Error: could not download from https://acrprodmgmt.azurecr.io/helm/foo: timeout",
        )

    monkeypatch.setattr(libdependencies, "run", sequenced_run)
    monkeypatch.setattr(libdependencies.time, "sleep", lambda *_: None)
    ok, detail = libdependencies.check_dependencies(tmp_path)
    assert ok is False
    assert calls["update"] == 3  # already logged in, so a network blip still gets retried
    assert "after 3 attempt" in detail


def test_check_dependencies_azure_cli_missing(libdependencies, tmp_path, monkeypatch):
    def sequenced_run(cmd, **kwargs):
        if cmd[:2] == ["az", "account"]:
            raise FileNotFoundError("az not found")
        return SimpleNamespace(
            returncode=1, stdout="",
            stderr="Error: could not download from https://acrprodmgmt.azurecr.io/helm/foo",
        )

    monkeypatch.setattr(libdependencies, "run", sequenced_run)
    monkeypatch.setattr(libdependencies.time, "sleep", lambda *_: None)
    ok, detail = libdependencies.check_dependencies(tmp_path)
    assert ok is False
    assert "Azure CLI (`az`) not found" in detail


def test_check_dependencies_count_mismatch(libdependencies, tmp_path, monkeypatch):
    (tmp_path / "charts").mkdir()
    # only one .tgz on disk but the dependency list reports two

    def sequenced_run(cmd, **kwargs):
        if cmd[2] == "update":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="NAME\tVERSION\tSTATUS\na\t1.0\tok\nb\t2.0\tok\n", stderr="")

    monkeypatch.setattr(libdependencies, "run", sequenced_run)
    ok, detail = libdependencies.check_dependencies(tmp_path)
    assert ok is False
    assert "expected 2 bundled" in detail


def test_check_dependencies_bad_status_fails(libdependencies, tmp_path, monkeypatch):
    def sequenced_run(cmd, **kwargs):
        if cmd[2] == "update":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="NAME\tVERSION\tSTATUS\na\t1.0\tfailed\n", stderr="")

    monkeypatch.setattr(libdependencies, "run", sequenced_run)
    ok, detail = libdependencies.check_dependencies(tmp_path)
    assert ok is False
    assert "did not resolve" in detail
