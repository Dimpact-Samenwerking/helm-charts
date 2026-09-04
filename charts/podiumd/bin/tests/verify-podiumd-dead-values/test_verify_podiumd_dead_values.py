"""verify-podiumd-dead-values's main() — argument parsing, the helm
pre-flight check, the runtime warning, and end-to-end wiring into
lib.dead_values_check.check_dead_values (mocked out here — its own
correctness is tests/verify-podiumd/test_dead_values_check.py's job,
not this script wrapper's)."""
import pytest


def test_help_flag_prints_docstring_and_exits_zero(vpdv, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["verify-podiumd-dead-values", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        vpdv.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == vpdv.__doc__ + "\n"


def test_wrong_arg_count_prints_docstring_and_exits_one(vpdv, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["verify-podiumd-dead-values", "unexpected-arg"])
    with pytest.raises(SystemExit) as exc_info:
        vpdv.main()
    assert exc_info.value.code == 1
    assert "Usage:" in capsys.readouterr().out


def test_missing_helm_fails_before_running_the_check(vpdv, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["verify-podiumd-dead-values"])
    monkeypatch.setattr(vpdv.shutil, "which", lambda name: None)

    def fail_if_called(*a, **kw):
        raise AssertionError("check_dead_values should never run without helm installed")

    monkeypatch.setattr(vpdv, "check_dead_values", fail_if_called)

    with pytest.raises(SystemExit) as exc_info:
        vpdv.main()

    assert exc_info.value.code == 1
    assert "helm is not installed" in capsys.readouterr().err


def test_main_prints_long_runtime_warning_before_running(vpdv, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["verify-podiumd-dead-values"])
    monkeypatch.setattr(vpdv.shutil, "which", lambda name: "/usr/bin/helm")
    monkeypatch.setattr(vpdv, "lint_args_for", lambda chart_dir: [])
    monkeypatch.setattr(vpdv, "check_dead_values", lambda chart_dir, extra_args: (True, "0/1321 dead"))

    with pytest.raises(SystemExit) as exc_info:
        vpdv.main()

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "40" in out  # the measured real-chart runtime, not just a vague "a while"
    assert out.index("WARNING") < out.index("OK: 0/1321 dead")


def test_main_reports_ok_and_exits_zero(vpdv, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["verify-podiumd-dead-values"])
    monkeypatch.setattr(vpdv.shutil, "which", lambda name: "/usr/bin/helm")
    monkeypatch.setattr(vpdv, "lint_args_for", lambda chart_dir: ["-f", "ci/lint-values.yaml"])
    captured_args = {}

    def fake_check(chart_dir, extra_args):
        captured_args["chart_dir"] = chart_dir
        captured_args["extra_args"] = extra_args
        return True, "0/1321 dead"

    monkeypatch.setattr(vpdv, "check_dead_values", fake_check)

    with pytest.raises(SystemExit) as exc_info:
        vpdv.main()

    assert exc_info.value.code == 0
    assert "OK: 0/1321 dead" in capsys.readouterr().out
    assert captured_args["chart_dir"] == vpdv.CHART_DIR
    assert captured_args["extra_args"] == ["-f", "ci/lint-values.yaml"]


def test_main_reports_fail_and_exits_one(vpdv, monkeypatch, capsys):
    """check_dead_values itself never actually returns ok=False (report-
    only by design), but main()'s own ok -> exit-code wiring should still
    do the right thing if that ever changed."""
    monkeypatch.setattr("sys.argv", ["verify-podiumd-dead-values"])
    monkeypatch.setattr(vpdv.shutil, "which", lambda name: "/usr/bin/helm")
    monkeypatch.setattr(vpdv, "lint_args_for", lambda chart_dir: [])
    monkeypatch.setattr(vpdv, "check_dead_values", lambda chart_dir, extra_args: (False, "boom"))

    with pytest.raises(SystemExit) as exc_info:
        vpdv.main()

    assert exc_info.value.code == 1
    assert "FAIL: boom" in capsys.readouterr().out
