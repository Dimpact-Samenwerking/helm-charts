"""die, require_helm, resolve_chart_dir, lint_args_for, print_summary — the
small orchestration helpers not covered elsewhere."""
import pytest


def test_die_exits_nonzero_and_prints_to_stderr(vp, capsys):
    with pytest.raises(SystemExit) as exc_info:
        vp.die("something broke")
    assert exc_info.value.code == 1
    assert "FAIL: something broke" in capsys.readouterr().err


def test_require_helm_passes_when_helm_present(vp, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/helm")
    vp.require_helm()  # must not raise


def test_require_helm_dies_when_helm_missing(vp, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit):
        vp.require_helm()


def test_resolve_chart_dir_returns_dir_with_chart_yaml(vp, tmp_path, monkeypatch):
    (tmp_path / "Chart.yaml").write_text("name: podiumd\nversion: 4.9.0\n")
    monkeypatch.setattr(vp, "DEFAULT_CHART_DIR", tmp_path)
    assert vp.resolve_chart_dir() == tmp_path.resolve()


def test_resolve_chart_dir_dies_without_chart_yaml(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "DEFAULT_CHART_DIR", tmp_path)
    with pytest.raises(SystemExit):
        vp.resolve_chart_dir()


def test_lint_args_for_uses_ci_values_when_present(vp, tmp_path):
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "lint-values.yaml").write_text("foo: bar\n")
    args = vp.lint_args_for(tmp_path)
    assert args == ["-f", str(tmp_path / "ci" / "lint-values.yaml")]


def test_lint_args_for_falls_back_without_ci_values(vp, tmp_path, capsys):
    args = vp.lint_args_for(tmp_path)
    assert args == []
    assert "WARNING" in capsys.readouterr().out


def test_print_summary_all_pass(vp, capsys):
    results = [("Lint", True, "0 errors"), ("Render", True, "257 manifests")]
    vp.print_summary(results, overall_ok=True)
    out = capsys.readouterr().out
    assert "Lint" in out and "PASS" in out
    assert "All checks passed." in out


def test_print_summary_reports_failure(vp, capsys):
    results = [("Lint", False, "1 error")]
    vp.print_summary(results, overall_ok=False)
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "One or more checks failed" in out


def test_print_summary_reports_skip(vp, capsys):
    """A step recorded with ok=None (skipped via --skip-<check>) renders as
    SKIP, not PASS or FAIL, and does not read as a failure."""
    results = [("Lint", None, "skipped"), ("Full render", True, "257 manifests")]
    vp.print_summary(results, overall_ok=True)
    out = capsys.readouterr().out
    assert "Lint" in out and "SKIP" in out
    assert "All checks passed." in out


# --- SKIPPABLE_STEPS ---

def test_skippable_steps_names_match_main_run_steps(vp):
    """Every (flag, step name) pair in SKIPPABLE_STEPS must name a step that
    main() actually runs — a typo here would silently make a --skip-<flag>
    flag do nothing."""
    import inspect
    source = inspect.getsource(vp.main)
    for _, step_name in vp.SKIPPABLE_STEPS:
        assert f'run_step("{step_name}"' in source, \
            f'no run_step("{step_name}", ...) call found in main()'


def test_skippable_steps_flags_are_unique_and_kebab_case(vp):
    flags = [flag for flag, _ in vp.SKIPPABLE_STEPS]
    assert len(flags) == len(set(flags))
    for flag in flags:
        assert flag == flag.lower()
        assert " " not in flag


# --- main(): --skip-<check> end-to-end ---

def test_main_skips_requested_steps_and_runs_the_rest(vp, monkeypatch, capsys):
    """--skip-lint --skip-full-render must skip exactly those two steps
    (never calling their check functions) while every other step still runs
    normally, and the run still exits 0."""
    monkeypatch.setattr(vp.sys, "argv", ["verify-podiumd.py", "--skip-lint", "--skip-full-render"])
    monkeypatch.setattr(vp, "require_helm", lambda: None)
    monkeypatch.setattr(vp, "resolve_chart_dir", lambda: "/fake/chart/dir")
    monkeypatch.setattr(vp, "ensure_repos_configured", lambda: None)
    monkeypatch.setattr(vp, "lint_args_for", lambda chart_dir: [])

    ran = []

    def make_check(name):
        def check(*args):
            ran.append(name)
            return True, "ok"
        return check

    monkeypatch.setattr(vp, "check_utf8_format", make_check("utf8"))
    monkeypatch.setattr(vp, "check_dependencies", make_check("deps"))
    monkeypatch.setattr(vp, "check_duplicate_keys", make_check("dupe"))
    monkeypatch.setattr(vp, "check_image_digests", make_check("digests"))
    monkeypatch.setattr(vp, "check_docs_consistency", make_check("docs"))

    def fail_if_called(*args):
        raise AssertionError("this check should have been skipped")

    monkeypatch.setattr(vp, "check_lint", fail_if_called)
    monkeypatch.setattr(vp, "check_render", fail_if_called)

    vp.main()  # must not raise / must not sys.exit

    assert ran == ["utf8", "deps", "dupe", "digests", "docs"]
    out = capsys.readouterr().out
    assert "Lint" in out and "SKIP" in out
    assert "Full render" in out and "SKIP" in out
    assert "All checks passed." in out


def test_main_skipped_step_does_not_count_as_failure(vp, monkeypatch):
    """Skipping every step except one that fails must still exit non-zero —
    a skip must never mask a real failure in a step that DID run."""
    monkeypatch.setattr(vp.sys, "argv", [
        "verify-podiumd.py", "--skip-dependencies", "--skip-image-digests",
        "--skip-docs-consistency", "--skip-lint", "--skip-full-render",
    ])
    monkeypatch.setattr(vp, "require_helm", lambda: None)
    monkeypatch.setattr(vp, "resolve_chart_dir", lambda: "/fake/chart/dir")
    monkeypatch.setattr(vp, "ensure_repos_configured", lambda: None)
    monkeypatch.setattr(vp, "check_utf8_format", lambda *a: (False, "BOM found"))

    with pytest.raises(SystemExit) as exc_info:
        vp.main()
    assert exc_info.value.code == 1
