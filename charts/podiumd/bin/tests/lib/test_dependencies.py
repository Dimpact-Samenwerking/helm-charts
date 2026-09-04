"""lib.dependencies — ensure_repos_configured, check_dependencies,
_vendored_state_matches_chart_yaml. `helm` subprocess calls mocked out via
libdependencies.run, so these tests need neither the binary installed nor
network access."""
from types import SimpleNamespace

import yaml


def fake_run(returncode=0, stdout="", stderr=""):
    def _run(cmd, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    return _run


def write_matching_lock_state(chart_dir, deps):
    """A Chart.yaml + Chart.lock + vendored charts/*.tgz set that
    _vendored_state_matches_chart_yaml should recognize as already up to
    date — deps is [{"name", "version", "repository"}, ...], written to
    Chart.yaml exactly as given. Chart.lock gets each dependency's
    repository already resolved to its plain URL when Chart.yaml uses an
    "@alias" — the same real shape Helm itself always writes there
    (Chart.lock never stores an alias) — via lib.render_scope.
    REQUIRED_REPOS, so a test using an alias actually exercises that
    resolution instead of comparing "@alias" against itself trivially."""
    from lib.render_scope import REQUIRED_REPOS

    def resolved(dep):
        repo = dep["repository"]
        if repo.startswith("@"):
            repo = REQUIRED_REPOS.get(repo[1:], repo)
        return {**dep, "repository": repo}

    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}), encoding="utf-8")
    lock_deps = [resolved(dep) for dep in deps]
    (chart_dir / "Chart.lock").write_text(yaml.safe_dump({"dependencies": lock_deps, "digest": "sha256:aaaa"}),
                                            encoding="utf-8")
    charts_dir = chart_dir / "charts"
    charts_dir.mkdir(exist_ok=True)
    for dep in deps:
        (charts_dir / f"{dep['name']}-{dep['version']}.tgz").touch()


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


def test_ensure_repos_configured_scopes_repo_update_to_required_repos(libdependencies, monkeypatch):
    """The final `helm repo update` must never be a blanket, argument-less
    call — that refreshes EVERY repo this machine has ever had `helm repo
    add`ed to it (measured live: 19 configured locally, only 9 actually
    used by this chart — ~6.2s vs ~0.6s scoped). Passing REQUIRED_REPOS'
    own names restricts it to just the repos this function itself
    added/verified above."""
    monkeypatch.setattr(libdependencies, "REQUIRED_REPOS", {"zac": "https://example.invalid/zac/",
                                                             "kiss": "https://example.invalid/kiss/"})
    calls = []

    def recording_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(libdependencies, "run", recording_run)
    ok, _msg = libdependencies.ensure_repos_configured()
    assert ok is True
    update_call = next(cmd for cmd in calls if cmd[1] == "repo" and cmd[2] == "update")
    assert update_call == ["helm", "repo", "update", "zac", "kiss"]


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

def test_check_dependencies_success(libdependencies, tmp_path, monkeypatch, capsys):
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
    # announced before the (potentially slow, re-downloads everything)
    # update call, so it's visible even before Helm's own live-streamed
    # progress starts appearing
    assert "Running helm dependency update (attempt 1/3)..." in capsys.readouterr().out


def test_check_dependencies_update_failure(libdependencies, tmp_path, monkeypatch):
    monkeypatch.setattr(libdependencies, "run", fake_run(1, "", "network error"))
    monkeypatch.setattr(libdependencies.time, "sleep", lambda *_: None)
    ok, detail = libdependencies.check_dependencies(tmp_path)
    assert ok is False
    assert "update failed" in detail
    assert "after 3 attempt" in detail


def test_check_dependencies_retries_then_succeeds(libdependencies, tmp_path, monkeypatch, capsys):
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
    out = capsys.readouterr().out
    assert "Running helm dependency update (attempt 1/3)..." in out
    assert "Running helm dependency update (attempt 2/3)..." in out


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


# --- _vendored_state_matches_chart_yaml / check_dependencies fast path ---

def test_vendored_state_matches_chart_yaml_true_when_everything_lines_up(libdependencies, tmp_path):
    deps = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    write_matching_lock_state(tmp_path, deps)
    assert libdependencies._vendored_state_matches_chart_yaml(tmp_path) is True


def test_vendored_state_matches_chart_yaml_false_when_no_lock_file(libdependencies, tmp_path):
    deps = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}), encoding="utf-8")
    assert libdependencies._vendored_state_matches_chart_yaml(tmp_path) is False


def test_vendored_state_matches_chart_yaml_false_when_version_bumped(libdependencies, tmp_path):
    """Chart.lock still has the OLD version — Chart.yaml moved on since
    it was generated."""
    old = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    write_matching_lock_state(tmp_path, old)
    new = [{"name": "zac", "version": "1.0.298", "repository": "@zac"}]
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": new}), encoding="utf-8")
    assert libdependencies._vendored_state_matches_chart_yaml(tmp_path) is False


def test_vendored_state_matches_chart_yaml_false_when_dependency_count_differs(libdependencies, tmp_path):
    """A dependency was added or removed in Chart.yaml since the lock was
    generated — real case this guards against: frankgateway briefly added
    then removed as a Chart.yaml dependency."""
    deps = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    write_matching_lock_state(tmp_path, deps)
    deps_plus_one = deps + [{"name": "frankgateway", "version": "1.1.0", "repository": "@wearefrank"}]
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps_plus_one}), encoding="utf-8")
    assert libdependencies._vendored_state_matches_chart_yaml(tmp_path) is False


def test_vendored_state_matches_chart_yaml_false_when_tgz_missing(libdependencies, tmp_path):
    """Chart.lock and Chart.yaml agree, but the vendored .tgz itself is
    missing (or got lost — real case hit today: charts/*.tgz emptied by
    an unrelated interrupted run) — never trust the lock alone."""
    deps = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    write_matching_lock_state(tmp_path, deps)
    (tmp_path / "charts" / "zac-1.0.297.tgz").unlink()
    assert libdependencies._vendored_state_matches_chart_yaml(tmp_path) is False


def test_vendored_state_matches_chart_yaml_int_version_normalized(libdependencies, tmp_path):
    """A bare-looking version ("version: 26") parses as a YAML int, not a
    string — must still compare equal to Chart.lock's own quoted-string
    form of the same version."""
    (tmp_path / "Chart.yaml").write_text(
        "dependencies:\n  - name: keycloak\n    version: 26\n    repository: \"@keycloak\"\n",
        encoding="utf-8",
    )
    (tmp_path / "Chart.lock").write_text(
        "dependencies:\n  - name: keycloak\n    version: \"26\"\n    repository: \"@keycloak\"\ndigest: sha256:aaaa\n",
        encoding="utf-8",
    )
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts" / "keycloak-26.tgz").touch()
    assert libdependencies._vendored_state_matches_chart_yaml(tmp_path) is True


def test_check_dependencies_skips_update_when_already_vendored(libdependencies, tmp_path, monkeypatch, capsys):
    deps = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    write_matching_lock_state(tmp_path, deps)
    dep_list_output = "NAME\tVERSION\tREPOSITORY\tSTATUS\nzac\t1.0.297\t@zac\tok\n"

    def fail_if_update_called(cmd, **kwargs):
        if cmd[2] == "update":
            raise AssertionError("helm dependency update should have been skipped")
        return SimpleNamespace(returncode=0, stdout=dep_list_output, stderr="")

    monkeypatch.setattr(libdependencies, "run", fail_if_update_called)
    ok, detail = libdependencies.check_dependencies(tmp_path)
    assert ok is True
    assert "1 dependencies bundled" in detail
    out = capsys.readouterr().out
    assert "skipping helm dependency update" in out


def test_check_dependencies_falls_back_to_update_when_lock_stale(libdependencies, tmp_path, monkeypatch, capsys):
    """A stale/mismatched Chart.lock must never silently short-circuit —
    falls all the way back to the same full rebuild-from-scratch path a
    missing lock file takes."""
    old = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    write_matching_lock_state(tmp_path, old)
    new = [{"name": "zac", "version": "1.0.298", "repository": "@zac"}]
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": new}), encoding="utf-8")
    dep_list_output = "NAME\tVERSION\tREPOSITORY\tSTATUS\nzac\t1.0.298\t@zac\tok\n"

    def sequenced_run(cmd, **kwargs):
        if cmd[2] == "update":
            charts_dir = tmp_path / "charts"
            charts_dir.mkdir(exist_ok=True)
            (charts_dir / "zac-1.0.298.tgz").touch()
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=dep_list_output, stderr="")

    monkeypatch.setattr(libdependencies, "run", sequenced_run)
    ok, detail = libdependencies.check_dependencies(tmp_path)
    assert ok is True
    out = capsys.readouterr().out
    assert "skipping helm dependency update" not in out
    assert "Running helm dependency update (attempt 1/3)..." in out
