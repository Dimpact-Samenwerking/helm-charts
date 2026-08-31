"""read_current_baseline, write_release_baseline — pure I/O against a
tmp_path file — plus a full main() integration test against a real,
hermetic temp git repo (to exercise the actual baseline_ref_candidates/
resolve_git_ref resolution, same as show-component-baseline-version's own
tests)."""
import subprocess

import pytest


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


# --- read_current_baseline / write_release_baseline ---

def test_read_current_baseline_missing_file_returns_none(cpb, tmp_path, monkeypatch):
    monkeypatch.setattr(cpb, "RELEASE_BASELINE_FILE", tmp_path / "release-baseline")
    assert cpb.read_current_baseline() is None


def test_read_current_baseline_strips_trailing_newline(cpb, tmp_path, monkeypatch):
    release_baseline_file = tmp_path / "release-baseline"
    release_baseline_file.write_text("4.8.4\n", encoding="utf-8")
    monkeypatch.setattr(cpb, "RELEASE_BASELINE_FILE", release_baseline_file)
    assert cpb.read_current_baseline() == "4.8.4"


def test_write_release_baseline_writes_bare_version_plus_newline(cpb, tmp_path, monkeypatch):
    release_baseline_file = tmp_path / "release-baseline"
    monkeypatch.setattr(cpb, "RELEASE_BASELINE_FILE", release_baseline_file)

    cpb.write_release_baseline("4.8.5")

    assert release_baseline_file.read_text(encoding="utf-8") == "4.8.5\n"


# --- main() integration, against a real hermetic temp repo ---
# main() only calls sys.exit() on error paths; on success it just returns,
# so only the failure-path tests wrap the call in pytest.raises(SystemExit).

@pytest.fixture
def repo(tmp_path):
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)
    return tmp_path


def set_up(cpb, monkeypatch, repo, argv, release_baseline_file):
    monkeypatch.setattr("sys.argv", ["change-podiumd-baseline", *argv])
    monkeypatch.setattr(cpb, "find_repo_root", lambda chart_dir: repo)
    monkeypatch.setattr(cpb, "RELEASE_BASELINE_FILE", release_baseline_file)
    # fix-doc-consistency and fix-helm-doc are invoked for real by
    # main() on any success path — fake both here (a real run would need
    # its own hermetic Chart.yaml/docs tree, and would otherwise run
    # against the REAL charts/podiumd since these are genuine subprocesses,
    # not something monkeypatch can reach into); test_main_invokes_fix_doc_consistency
    # and test_main_invokes_fix_helm_doc_after_fix_doc_consistency cover
    # the calls themselves.
    monkeypatch.setattr(cpb, "run_script", lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 0))


def test_main_records_a_resolvable_baseline(cpb, repo, tmp_path, monkeypatch, capsys):
    release_baseline_file = tmp_path / "release-baseline"
    set_up(cpb, monkeypatch, repo, ["4.8.5"], release_baseline_file)

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 0
    assert release_baseline_file.read_text(encoding="utf-8") == "4.8.5\n"
    out = capsys.readouterr().out
    assert "(none) -> 4.8.5" in out
    assert "resolved to podiumd-4.8.5" in out


def test_main_overwrites_an_existing_baseline(cpb, repo, tmp_path, monkeypatch, capsys):
    release_baseline_file = tmp_path / "release-baseline"
    release_baseline_file.write_text("4.8.4\n", encoding="utf-8")
    set_up(cpb, monkeypatch, repo, ["4.8.5"], release_baseline_file)

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 0
    assert release_baseline_file.read_text(encoding="utf-8") == "4.8.5\n"
    assert "4.8.4 -> 4.8.5" in capsys.readouterr().out


def test_main_same_baseline_is_a_noop_message_but_still_writes(cpb, repo, tmp_path, monkeypatch, capsys):
    release_baseline_file = tmp_path / "release-baseline"
    release_baseline_file.write_text("4.8.5\n", encoding="utf-8")
    set_up(cpb, monkeypatch, repo, ["4.8.5"], release_baseline_file)

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 0
    assert release_baseline_file.read_text(encoding="utf-8") == "4.8.5\n"
    assert "already 4.8.5" in capsys.readouterr().out


def test_main_invokes_fix_doc_consistency(cpb, repo, tmp_path, monkeypatch, capsys):
    release_baseline_file = tmp_path / "release-baseline"
    set_up(cpb, monkeypatch, repo, ["4.8.5"], release_baseline_file)
    calls = []
    real_fake = cpb.run_script
    monkeypatch.setattr(cpb, "run_script", lambda cmd, *a, **k: (calls.append(cmd), real_fake(cmd, *a, **k))[1])

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 0
    assert calls[0][0] == cpb.sys.executable
    assert calls[0][1] == str(cpb.FIX_DOC_CONSISTENCY_SCRIPT)
    assert calls[0][2] == "4.8.5"
    assert "fix-doc-consistency 4.8.5" in capsys.readouterr().out


def test_main_invokes_fix_helm_doc_after_fix_doc_consistency(cpb, repo, tmp_path, monkeypatch, capsys):
    release_baseline_file = tmp_path / "release-baseline"
    set_up(cpb, monkeypatch, repo, ["4.8.5"], release_baseline_file)
    calls = []
    real_fake = cpb.run_script
    monkeypatch.setattr(cpb, "run_script", lambda cmd, *a, **k: (calls.append(cmd), real_fake(cmd, *a, **k))[1])

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 0
    assert len(calls) == 2
    assert calls[1][0] == cpb.sys.executable
    assert calls[1][1] == str(cpb.FIX_HELM_DOC_SCRIPT)
    assert "fix-helm-doc" in capsys.readouterr().out


def test_main_propagates_fix_doc_consistency_failure_exit_code(cpb, repo, tmp_path, monkeypatch):
    release_baseline_file = tmp_path / "release-baseline"
    set_up(cpb, monkeypatch, repo, ["4.8.5"], release_baseline_file)
    monkeypatch.setattr(cpb, "run_script", lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 1))

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 1


def test_main_skips_fix_helm_doc_when_fix_doc_consistency_fails(cpb, repo, tmp_path, monkeypatch):
    release_baseline_file = tmp_path / "release-baseline"
    set_up(cpb, monkeypatch, repo, ["4.8.5"], release_baseline_file)
    calls = []

    def fake_run_script(cmd, *a, **k):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(cpb, "run_script", fake_run_script)

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 1
    assert len(calls) == 1  # fix-helm-doc never invoked


def test_main_propagates_fix_helm_doc_failure_exit_code(cpb, repo, tmp_path, monkeypatch):
    release_baseline_file = tmp_path / "release-baseline"
    set_up(cpb, monkeypatch, repo, ["4.8.5"], release_baseline_file)

    def fake_run_script(cmd, *a, **k):
        returncode = 1 if str(cpb.FIX_HELM_DOC_SCRIPT) in cmd else 0
        return subprocess.CompletedProcess(cmd, returncode)

    monkeypatch.setattr(cpb, "run_script", fake_run_script)

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 1


def test_main_unresolvable_baseline_fails_without_writing(cpb, repo, tmp_path, monkeypatch, capsys):
    release_baseline_file = tmp_path / "release-baseline"
    release_baseline_file.write_text("4.8.4\n", encoding="utf-8")
    set_up(cpb, monkeypatch, repo, ["9.9.9"], release_baseline_file)

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 1
    assert "could not resolve baseline" in capsys.readouterr().out
    assert release_baseline_file.read_text(encoding="utf-8") == "4.8.4\n"  # untouched


def test_main_not_a_git_repo_fails(cpb, monkeypatch, tmp_path, capsys):
    release_baseline_file = tmp_path / "release-baseline"
    monkeypatch.setattr("sys.argv", ["change-podiumd-baseline", "4.8.5"])
    monkeypatch.setattr(cpb, "find_repo_root", lambda chart_dir: None)
    monkeypatch.setattr(cpb, "RELEASE_BASELINE_FILE", release_baseline_file)

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 1
    assert "not inside a git repository" in capsys.readouterr().out


def test_main_requires_exactly_one_argument(cpb, monkeypatch):
    monkeypatch.setattr("sys.argv", ["change-podiumd-baseline"])
    with pytest.raises(SystemExit) as exc_info:
        cpb.main()
    assert exc_info.value.code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(cpb, monkeypatch, capsys, flag):
    monkeypatch.setattr("sys.argv", ["change-podiumd-baseline", flag])
    with pytest.raises(SystemExit) as exc_info:
        cpb.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == cpb.__doc__ + "\n"
