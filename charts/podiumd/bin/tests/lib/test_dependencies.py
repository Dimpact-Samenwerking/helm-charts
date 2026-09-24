"""lib.dependencies — ensure_repos_configured, check_dependencies,
vendored_state_matches_chart_yaml, update_vendored_dependencies,
ensure_vendored_dependencies. `helm` subprocess calls mocked out via
libdependencies.run, so these tests need neither the binary installed nor
network access."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from lib.settings import helm_repos_urls_by_alias


def fake_run(returncode=0, stdout="", stderr=""):
    def _run(cmd, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return _run


def write_matching_lock_state(chart_dir, deps):
    """A Chart.yaml + Chart.lock + vendored charts/*.tgz set that
    vendored_state_matches_chart_yaml should recognize as already up to
    date — deps is [{"name", "version", "repository"}, ...], written to
    Chart.yaml exactly as given. Chart.lock gets each dependency's
    repository already resolved to its plain URL when Chart.yaml uses an
    "@alias" — the same real shape Helm itself always writes there
    (Chart.lock never stores an alias) — via lib.settings.
    helm_repos_urls_by_alias (chart_dir has no settings.yaml, so this is
    the hard-coded default), so a test using an alias actually exercises
    that resolution instead of comparing "@alias" against itself
    trivially."""

    required_repos = helm_repos_urls_by_alias(chart_dir)

    def resolved(dep):
        repo = dep["repository"]
        if repo.startswith("@"):
            repo = required_repos.get(repo[1:], repo)
        return {**dep, "repository": repo}

    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}), encoding="utf-8")
    lock_deps = [resolved(dep) for dep in deps]
    (chart_dir / "Chart.lock").write_text(
        yaml.safe_dump({"dependencies": lock_deps, "digest": "sha256:aaaa"}), encoding="utf-8"
    )
    charts_dir = chart_dir / "charts"
    charts_dir.mkdir(exist_ok=True)
    for dep in deps:
        (charts_dir / f"{dep['name']}-{dep['version']}.tgz").touch()


# --- ensure_repos_configured ---


def test_ensure_repos_configured_success(libdependencies, tmp_path, monkeypatch):
    monkeypatch.setattr(
        libdependencies, "helm_repos_urls_by_alias", lambda chart_dir: {"zac": "https://example.invalid/zac/"}
    )
    monkeypatch.setattr(libdependencies, "run", fake_run(0))
    ok, msg = libdependencies.ensure_repos_configured(tmp_path)
    assert ok is True
    assert msg == "repos configured"


def test_ensure_repos_configured_repo_add_failure(libdependencies, tmp_path, monkeypatch):
    monkeypatch.setattr(
        libdependencies, "helm_repos_urls_by_alias", lambda chart_dir: {"zac": "https://example.invalid/zac/"}
    )
    monkeypatch.setattr(libdependencies, "run", fake_run(1, "", "network unreachable"))
    ok, msg = libdependencies.ensure_repos_configured(tmp_path)
    assert ok is False
    assert "helm repo add zac failed" in msg
    assert "network unreachable" in msg


def test_ensure_repos_configured_scopes_repo_update_to_required_repos(libdependencies, tmp_path, monkeypatch):
    """The final `helm repo update` must never be a blanket, argument-less
    call — that refreshes EVERY repo this machine has ever had `helm repo
    add`ed to it (measured live: 19 configured locally, only 9 actually
    used by this chart — ~6.2s vs ~0.6s scoped). Passing helm_repos_urls_
    by_alias' own names restricts it to just the repos this function
    itself added/verified above."""
    monkeypatch.setattr(
        libdependencies,
        "helm_repos_urls_by_alias",
        lambda chart_dir: {"zac": "https://example.invalid/zac/", "kiss": "https://example.invalid/kiss/"},
    )
    calls = []

    def recording_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(libdependencies, "run", recording_run)
    ok, _msg = libdependencies.ensure_repos_configured(tmp_path)
    assert ok is True
    update_call = next(cmd for cmd in calls if cmd[1] == "repo" and cmd[2] == "update")
    assert update_call == ["helm", "repo", "update", "zac", "kiss"]


def test_ensure_repos_configured_repo_update_failure(libdependencies, tmp_path, monkeypatch):
    monkeypatch.setattr(
        libdependencies, "helm_repos_urls_by_alias", lambda chart_dir: {"zac": "https://example.invalid/zac/"}
    )

    def sequenced_run(cmd, **kwargs):
        if cmd[1] == "repo" and cmd[2] == "add":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(libdependencies, "run", sequenced_run)
    ok, msg = libdependencies.ensure_repos_configured(tmp_path)
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
    ok, _detail = libdependencies.check_dependencies(tmp_path)
    assert ok is True
    assert calls["update"] == 2
    out = capsys.readouterr().out
    assert "Running helm dependency update (attempt 1/3)..." in out
    assert "Running helm dependency update (attempt 2/3)..." in out


def test_check_dependencies_zero_retry_attempts_is_a_clear_error(libdependencies, tmp_path, monkeypatch):
    """Regression test: dependency_fetch.retry_attempts = 0 ran helm zero
    times and then crashed with AttributeError on the missing result. It
    now fails with an error that names the setting."""
    monkeypatch.setattr(libdependencies, "run", fake_run())
    monkeypatch.setattr(libdependencies, "dependency_fetch_retry_attempts", lambda _chart_dir: 0)
    with pytest.raises(SystemExit, match="retry_attempts must be at least 1, got 0"):
        libdependencies.check_dependencies(tmp_path)


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


# --- vendored_state_matches_chart_yaml / check_dependencies fast path ---


def testvendored_state_matches_chart_yaml_true_when_everything_lines_up(libdependencies, tmp_path):
    deps = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    write_matching_lock_state(tmp_path, deps)
    assert libdependencies.vendored_state_matches_chart_yaml(tmp_path) is True


def testvendored_state_matches_chart_yaml_false_when_no_lock_file(libdependencies, tmp_path):
    deps = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}), encoding="utf-8")
    assert libdependencies.vendored_state_matches_chart_yaml(tmp_path) is False


def testvendored_state_matches_chart_yaml_false_when_version_bumped(libdependencies, tmp_path):
    """Chart.lock still has the OLD version — Chart.yaml moved on since
    it was generated."""
    old = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    write_matching_lock_state(tmp_path, old)
    new = [{"name": "zac", "version": "1.0.298", "repository": "@zac"}]
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": new}), encoding="utf-8")
    assert libdependencies.vendored_state_matches_chart_yaml(tmp_path) is False


def testvendored_state_matches_chart_yaml_false_when_dependency_count_differs(libdependencies, tmp_path):
    """A dependency was added or removed in Chart.yaml since the lock was
    generated — real case this guards against: frankgateway briefly added
    then removed as a Chart.yaml dependency."""
    deps = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    write_matching_lock_state(tmp_path, deps)
    deps_plus_one = [*deps, {"name": "frankgateway", "version": "1.1.0", "repository": "@wearefrank"}]
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps_plus_one}), encoding="utf-8")
    assert libdependencies.vendored_state_matches_chart_yaml(tmp_path) is False


def testvendored_state_matches_chart_yaml_false_when_tgz_missing(libdependencies, tmp_path):
    """Chart.lock and Chart.yaml agree, but the vendored .tgz itself is
    missing (or got lost — real case hit today: charts/*.tgz emptied by
    an unrelated interrupted run) — never trust the lock alone."""
    deps = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    write_matching_lock_state(tmp_path, deps)
    (tmp_path / "charts" / "zac-1.0.297.tgz").unlink()
    assert libdependencies.vendored_state_matches_chart_yaml(tmp_path) is False


def testvendored_state_matches_chart_yaml_int_version_normalized(libdependencies, tmp_path):
    """A bare-looking version ("version: 26") parses as a YAML int, not a
    string — must still compare equal to Chart.lock's own quoted-string
    form of the same version."""
    (tmp_path / "Chart.yaml").write_text(
        'dependencies:\n  - name: keycloak\n    version: 26\n    repository: "@keycloak"\n',
        encoding="utf-8",
    )
    (tmp_path / "Chart.lock").write_text(
        'dependencies:\n  - name: keycloak\n    version: "26"\n    repository: "@keycloak"\ndigest: sha256:aaaa\n',
        encoding="utf-8",
    )
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts" / "keycloak-26.tgz").touch()
    assert libdependencies.vendored_state_matches_chart_yaml(tmp_path) is True


def test_check_dependencies_skips_update_when_already_vendored(libdependencies, tmp_path, monkeypatch, capsys):
    deps = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    write_matching_lock_state(tmp_path, deps)
    dep_list_output = "NAME\tVERSION\tREPOSITORY\tSTATUS\nzac\t1.0.297\t@zac\tok\n"

    def fail_if_update_called(cmd, **kwargs):
        if cmd[2] == "update":
            msg = "helm dependency update should have been skipped"
            raise AssertionError(msg)
        return SimpleNamespace(returncode=0, stdout=dep_list_output, stderr="")

    monkeypatch.setattr(libdependencies, "run", fail_if_update_called)
    ok, detail = libdependencies.check_dependencies(tmp_path)
    assert ok is True
    assert "1 dependencies bundled" in detail
    out = capsys.readouterr().out
    assert "skipping helm dependency update" in out


def test_check_dependencies_falls_back_to_full_update_when_fetch_fails(libdependencies, tmp_path, monkeypatch, capsys):
    """A stale Chart.lock whose changed dependency can't be fetched on its
    own (here: `helm pull` "succeeds" without writing the .tgz) must
    never silently short-circuit — falls all the way back to the same
    full rebuild-from-scratch path a missing lock file takes."""
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
    ok, _detail = libdependencies.check_dependencies(tmp_path)
    assert ok is True
    out = capsys.readouterr().out
    assert "skipping helm dependency update" not in out
    assert "helm pull zac 1.0.298 did not produce zac-1.0.298.tgz" in out
    assert "Running helm dependency update (attempt 1/3)..." in out


# --- vendored_dependency_problems / ensure_vendored_dependencies ---


def test_vendored_dependency_problems_empty_when_in_sync(libdependencies, tmp_path):
    deps = [{"name": "kiss-chart", "version": "3.1.1", "repository": "@kiss"}]
    write_matching_lock_state(tmp_path, deps)
    assert libdependencies.vendored_dependency_problems(tmp_path) == []


def test_vendored_dependency_problems_empty_when_chart_has_no_dependencies(libdependencies, tmp_path):
    """Nothing to vendor at all — unlike vendored_state_matches_chart_yaml
    (which returns False here so check_dependencies still runs a real
    update), the guard has nothing to complain about."""
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"name": "x", "version": "1.0.0"}), encoding="utf-8")
    assert libdependencies.vendored_dependency_problems(tmp_path) == []
    assert libdependencies.vendored_state_matches_chart_yaml(tmp_path) is False


def test_vendored_dependency_problems_names_wrong_tgz_version(libdependencies, tmp_path):
    """The real incident: Chart.yaml moved to kiss-chart 3.1.1 (Chart.lock
    regenerated too), but charts/ still has the old 3.0.0 package."""
    deps = [{"name": "kiss-chart", "version": "3.1.1", "repository": "@kiss"}]
    write_matching_lock_state(tmp_path, deps)
    (tmp_path / "charts" / "kiss-chart-3.1.1.tgz").rename(tmp_path / "charts" / "kiss-chart-3.0.0.tgz")
    assert libdependencies.vendored_dependency_problems(tmp_path) == [
        "kiss-chart: Chart.yaml wants 3.1.1, charts/ has 3.0.0"
    ]


def test_vendored_dependency_problems_tgz_missing_entirely(libdependencies, tmp_path):
    deps = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    write_matching_lock_state(tmp_path, deps)
    (tmp_path / "charts" / "zac-1.0.297.tgz").unlink()
    assert libdependencies.vendored_dependency_problems(tmp_path) == ["zac: charts/zac-1.0.297.tgz is missing"]


def test_vendored_dependency_problems_lock_missing(libdependencies, tmp_path):
    deps = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    write_matching_lock_state(tmp_path, deps)
    (tmp_path / "Chart.lock").unlink()
    assert libdependencies.vendored_dependency_problems(tmp_path) == ["Chart.lock is missing"]


def test_vendored_dependency_problems_lock_disagrees_with_chart_yaml(libdependencies, tmp_path):
    """Chart.yaml bumped (and a dependency dropped) since Chart.lock and
    charts/ were last generated — every side of the drift is named."""
    old = [
        {"name": "kiss-chart", "version": "3.0.0", "repository": "@kiss"},
        {"name": "mi-data", "version": "1.0.0", "repository": "@dimpact"},
    ]
    write_matching_lock_state(tmp_path, old)
    new = [{"name": "kiss-chart", "version": "3.1.1", "repository": "@kiss"}]
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": new}), encoding="utf-8")
    assert libdependencies.vendored_dependency_problems(tmp_path) == [
        "kiss-chart: Chart.yaml wants 3.1.1, Chart.lock has 3.0.0",
        "mi-data: in Chart.lock (1.0.0) but no longer in Chart.yaml",
        "kiss-chart: Chart.yaml wants 3.1.1, charts/ has 3.0.0",
    ]


def test_ensure_vendored_dependencies_passes_when_in_sync(libdependencies, tmp_path, monkeypatch):
    deps = [{"name": "zac", "version": "1.0.297", "repository": "@zac"}]
    write_matching_lock_state(tmp_path, deps)
    monkeypatch.setattr(libdependencies, "run", fail_on_any_helm_call)
    assert libdependencies.ensure_vendored_dependencies(tmp_path) is None


def test_ensure_vendored_dependencies_re_vendors_a_stale_state(libdependencies, tmp_path, monkeypatch, capsys):
    """The referentielijsten case: Chart.yaml bumped, charts/ + Chart.lock
    still at the old version — the guard names the drift on stderr,
    fetches only that one dependency and lets the script carry on,
    stdout untouched."""
    bump_zac(tmp_path)
    monkeypatch.setattr(libdependencies, "run", pull_writes_tgz(tmp_path))
    monkeypatch.chdir(tmp_path.parent)

    assert libdependencies.ensure_vendored_dependencies(tmp_path) is None

    captured = capsys.readouterr()
    assert not captured.out
    assert f"{tmp_path.name}/charts/ and Chart.lock do not match Chart.yaml, re-vendoring:" in captured.err
    assert "  - zac: Chart.yaml wants 1.0.298, charts/ has 1.0.297" in captured.err
    assert "Re-vendored only what changed: fetched 1 of 2 dependencies (zac 1.0.298)" in captured.err
    assert libdependencies.vendored_dependency_problems(tmp_path) == []


def test_ensure_vendored_dependencies_exits_when_re_vendoring_fails(libdependencies, tmp_path, monkeypatch):
    bump_zac(tmp_path)
    monkeypatch.setattr(libdependencies, "run", fake_run(1, "", "network unreachable"))
    monkeypatch.chdir(tmp_path.parent)

    with pytest.raises(SystemExit) as exc_info:
        libdependencies.ensure_vendored_dependencies(tmp_path)

    message = str(exc_info.value.code)
    assert message.startswith(f"error: could not re-vendor {tmp_path.name}/charts/ (helm repo add ")
    assert message.endswith(f"Run: helm dependency update {tmp_path.name}")


# --- update_vendored_dependencies / update_changed_dependencies ---


def fail_on_any_helm_call(cmd, **kwargs):
    message = f"unexpected helm call: {cmd}"
    raise AssertionError(message)


def bump_zac(chart_dir):
    """charts/ + Chart.lock vendored for zac 1.0.297 + clamav 3.7.2, then
    Chart.yaml moves zac on to 1.0.298 (clamav unchanged)."""
    old = [
        {"name": "zac", "version": "1.0.297", "repository": "@zac"},
        {"name": "clamav", "version": "3.7.2", "repository": "@wiremind"},
    ]
    write_matching_lock_state(chart_dir, old)
    new = [{**old[0], "version": "1.0.298"}, old[1]]
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": new}), encoding="utf-8")


def pull_writes_tgz(chart_dir, calls=None):
    """A `run` stand-in whose `helm pull`/`helm package` write the
    <name>-<version>.tgz into --destination, as the real ones do; every
    other helm call (repo add/update) just succeeds. Records each argv
    into `calls` when given."""

    def _run(cmd, **kwargs):
        if calls is not None:
            calls.append(cmd)
        if cmd[1] == "dependency":
            message = "full helm dependency update should not run"
            raise AssertionError(message)
        if cmd[1] in {"pull", "package"}:
            dest = Path(cmd[cmd.index("--destination") + 1])
            name = cmd[2].rsplit("/", 1)[-1]
            version = cmd[cmd.index("--version") + 1] if "--version" in cmd else "0.0.0"
            (dest / f"{name}-{version}.tgz").write_text("fetched", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return _run


def test_update_vendored_dependencies_fetches_only_what_changed(libdependencies, tmp_path, monkeypatch):
    bump_zac(tmp_path)
    clamav_before = (tmp_path / "charts" / "clamav-3.7.2.tgz").stat().st_mtime_ns
    calls = []
    monkeypatch.setattr(libdependencies, "run", pull_writes_tgz(tmp_path, calls))

    ok, detail = libdependencies.update_vendored_dependencies(tmp_path)

    assert ok is True
    assert detail == "fetched 1 of 2 dependencies (zac 1.0.298)"
    zac_url = helm_repos_urls_by_alias(tmp_path)["zac"]
    assert len(calls) == 1
    assert calls[0][:7] == ["helm", "pull", "zac", "--repo", zac_url, "--version", "1.0.298"]
    charts = sorted(path.name for path in (tmp_path / "charts").iterdir())
    assert charts == ["clamav-3.7.2.tgz", "zac-1.0.298.tgz"]
    assert (tmp_path / "charts" / "clamav-3.7.2.tgz").stat().st_mtime_ns == clamav_before
    lock = yaml.safe_load((tmp_path / "Chart.lock").read_text(encoding="utf-8"))
    assert [(dep["name"], dep["version"]) for dep in lock["dependencies"]] == [
        ("zac", "1.0.298"),
        ("clamav", "3.7.2"),
    ]
    assert lock["digest"].startswith("sha256:")
    assert libdependencies.vendored_dependency_problems(tmp_path) == []


def test_update_changed_dependencies_leaves_state_untouched_when_a_fetch_fails(libdependencies, tmp_path, monkeypatch):
    bump_zac(tmp_path)
    lock_before = (tmp_path / "Chart.lock").read_text(encoding="utf-8")
    monkeypatch.setattr(libdependencies, "run", fake_run(1, "", "404 not found"))
    monkeypatch.setattr(libdependencies.time, "sleep", lambda *_: None)

    ok, detail = libdependencies.update_changed_dependencies(tmp_path)

    assert ok is False
    assert detail == "helm pull zac 1.0.298 failed: 404 not found"
    assert sorted(path.name for path in (tmp_path / "charts").iterdir()) == ["clamav-3.7.2.tgz", "zac-1.0.297.tgz"]
    assert (tmp_path / "Chart.lock").read_text(encoding="utf-8") == lock_before


def test_update_changed_dependencies_drops_removed_dependency(libdependencies, tmp_path, monkeypatch):
    """A dependency removed from Chart.yaml: nothing to fetch, its .tgz
    goes and Chart.lock is rewritten."""
    bump_zac(tmp_path)
    kept = [{"name": "clamav", "version": "3.7.2", "repository": "@wiremind"}]
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": kept}), encoding="utf-8")
    monkeypatch.setattr(libdependencies, "run", fail_on_any_helm_call)

    ok, detail = libdependencies.update_changed_dependencies(tmp_path)

    assert ok is True
    assert detail == "fetched 0 of 1 dependencies (none, Chart.lock only)"
    assert sorted(path.name for path in (tmp_path / "charts").iterdir()) == ["clamav-3.7.2.tgz"]
    assert libdependencies.vendored_dependency_problems(tmp_path) == []


def test_update_changed_dependencies_needs_a_lock_to_start_from(libdependencies, tmp_path, monkeypatch):
    bump_zac(tmp_path)
    (tmp_path / "Chart.lock").unlink()
    monkeypatch.setattr(libdependencies, "run", fail_on_any_helm_call)
    assert libdependencies.update_changed_dependencies(tmp_path) == (False, "no usable Chart.lock to update")


def test_update_changed_dependencies_leaves_version_ranges_to_helm(libdependencies, tmp_path, monkeypatch):
    bump_zac(tmp_path)
    ranged = [{"name": "zac", "version": "~1.0.0", "repository": "@zac"}]
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": ranged}), encoding="utf-8")
    monkeypatch.setattr(libdependencies, "run", fail_on_any_helm_call)
    assert libdependencies.update_changed_dependencies(tmp_path) == (False, "version range for zac")


@pytest.mark.parametrize(
    ("repository", "expected"),
    [
        (
            "oci://ghcr.io/kiss/",
            ["helm", "pull", "oci://ghcr.io/kiss/kiss-chart", "--version", "3.1.1", "--destination"],
        ),
        (
            "https://charts.example/",
            ["helm", "pull", "kiss-chart", "--repo", "https://charts.example/", "--version", "3.1.1", "--destination"],
        ),
        ("@unknown-alias", None),
    ],
)
def test_fetch_command_per_repository_kind(libdependencies, tmp_path, repository, expected):
    dep = {"name": "kiss-chart", "version": "3.1.1", "repository": repository}
    cmd = libdependencies._fetch_command(tmp_path, dep, {}, tmp_path / "dest")
    if expected is None:
        assert cmd is None
    else:
        assert cmd == [*expected, str(tmp_path / "dest")]


def test_fetch_command_packages_a_file_dependency(libdependencies, tmp_path):
    dep = {"name": "mi-data", "version": "1.1.0", "repository": "file://../mi-data"}
    cmd = libdependencies._fetch_command(tmp_path / "podiumd", dep, {}, tmp_path / "dest")
    assert cmd == ["helm", "package", str(tmp_path / "mi-data"), "--destination", str(tmp_path / "dest")]
