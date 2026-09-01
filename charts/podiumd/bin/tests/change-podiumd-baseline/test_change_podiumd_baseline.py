"""main() integration test against a real, hermetic temp git repo (to
exercise the actual baseline_ref_candidates/resolve_git_ref resolution,
same as show-component-baseline-version's own tests). The read/write
sides (lib.chart.upgrade_docs_baseline/write_release_baselines) are
pure I/O already covered in tests/lib/test_chart.py -- this file only
exercises main()'s own wiring: it reads the CURRENT upgrade_docs
baseline, writes the new one (release_table is never touched), and
chains into fix-doc-consistency then fix-helm-doc."""
import subprocess

import pytest


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


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


def set_up(cpb, monkeypatch, repo, argv):
    monkeypatch.setattr("sys.argv", ["change-podiumd-baseline", *argv])
    monkeypatch.setattr(cpb, "find_repo_root", lambda chart_dir: repo)
    monkeypatch.setattr(cpb, "CHART_DIR", repo)
    # fix-doc-consistency and fix-helm-doc are invoked for real by
    # main() on any success path — fake both here (a real run would need
    # its own hermetic Chart.yaml/docs tree, and would otherwise run
    # against the REAL charts/podiumd since these are genuine subprocesses,
    # not something monkeypatch can reach into); test_main_invokes_fix_doc_consistency
    # and test_main_invokes_fix_helm_doc_after_fix_doc_consistency cover
    # the calls themselves.
    monkeypatch.setattr(cpb, "run_script", lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 0))


def test_main_records_a_resolvable_baseline(cpb, repo, monkeypatch, capsys):
    set_up(cpb, monkeypatch, repo, ["4.8.5"])

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 0
    assert cpb.read_upgrade_docs_baseline(repo) == "4.8.5"
    out = capsys.readouterr().out
    assert "upgrade_docs (none) -> 4.8.5" in out
    assert "resolved to podiumd-4.8.5" in out


def test_main_overwrites_an_existing_baseline(cpb, repo, monkeypatch, capsys):
    cpb.write_release_baselines(repo, upgrade_docs="4.8.4")
    set_up(cpb, monkeypatch, repo, ["4.8.5"])

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 0
    assert cpb.read_upgrade_docs_baseline(repo) == "4.8.5"
    assert "upgrade_docs 4.8.4 -> 4.8.5" in capsys.readouterr().out


def test_main_never_touches_release_table(cpb, repo, monkeypatch):
    cpb.write_release_baselines(repo, upgrade_docs="4.8.4", release_table="4.8.0")
    set_up(cpb, monkeypatch, repo, ["4.8.5"])

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 0
    from lib.chart import release_table_baseline
    assert release_table_baseline(repo) == "4.8.0"  # untouched


def test_main_same_baseline_is_a_noop_message_but_still_writes(cpb, repo, monkeypatch, capsys):
    cpb.write_release_baselines(repo, upgrade_docs="4.8.5")
    set_up(cpb, monkeypatch, repo, ["4.8.5"])

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 0
    assert cpb.read_upgrade_docs_baseline(repo) == "4.8.5"
    assert "upgrade_docs already 4.8.5" in capsys.readouterr().out


def test_main_invokes_fix_doc_consistency(cpb, repo, monkeypatch, capsys):
    set_up(cpb, monkeypatch, repo, ["4.8.5"])
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


def test_main_invokes_fix_helm_doc_after_fix_doc_consistency(cpb, repo, monkeypatch, capsys):
    set_up(cpb, monkeypatch, repo, ["4.8.5"])
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


def test_main_propagates_fix_doc_consistency_failure_exit_code(cpb, repo, monkeypatch):
    set_up(cpb, monkeypatch, repo, ["4.8.5"])
    monkeypatch.setattr(cpb, "run_script", lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 1))

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 1


def test_main_skips_fix_helm_doc_when_fix_doc_consistency_fails(cpb, repo, monkeypatch):
    set_up(cpb, monkeypatch, repo, ["4.8.5"])
    calls = []

    def fake_run_script(cmd, *a, **k):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(cpb, "run_script", fake_run_script)

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 1
    assert len(calls) == 1  # fix-helm-doc never invoked


def test_main_propagates_fix_helm_doc_failure_exit_code(cpb, repo, monkeypatch):
    set_up(cpb, monkeypatch, repo, ["4.8.5"])

    def fake_run_script(cmd, *a, **k):
        returncode = 1 if str(cpb.FIX_HELM_DOC_SCRIPT) in cmd else 0
        return subprocess.CompletedProcess(cmd, returncode)

    monkeypatch.setattr(cpb, "run_script", fake_run_script)

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 1


def test_main_unresolvable_baseline_fails_without_writing(cpb, repo, monkeypatch, capsys):
    cpb.write_release_baselines(repo, upgrade_docs="4.8.4")
    set_up(cpb, monkeypatch, repo, ["9.9.9"])

    with pytest.raises(SystemExit) as exc_info:
        cpb.main()

    assert exc_info.value.code == 1
    assert "could not resolve baseline" in capsys.readouterr().out
    assert cpb.read_upgrade_docs_baseline(repo) == "4.8.4"  # untouched


def test_main_not_a_git_repo_fails(cpb, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("sys.argv", ["change-podiumd-baseline", "4.8.5"])
    monkeypatch.setattr(cpb, "find_repo_root", lambda chart_dir: None)
    monkeypatch.setattr(cpb, "CHART_DIR", tmp_path)

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
