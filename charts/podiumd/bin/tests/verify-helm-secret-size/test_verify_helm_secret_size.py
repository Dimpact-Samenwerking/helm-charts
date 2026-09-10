"""main() — the standalone verify-helm-secret-size CLI: a thin argparse
wrapper around lib.release_secret_size's own core (build_release/
encoded_secret_size/format_report/record_result), unlike check_release_
secret_size (verify-podiumd's own integration, tested in tests/verify-
podiumd/test_release_secret_size.py) this CLI renders via its OWN `helm
template <name> <chart_dir> ...` call (an arbitrary --name, so it can't
go through lib.render_scope.render_chart, which is hardcoded to
CHART_NAME) — mocked here via vhss.run, never a real helm invocation."""
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_main_requires_chart_argument(vhss, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["verify-helm-secret-size"])
    with pytest.raises(SystemExit) as exc_info:
        vhss.main()
    assert exc_info.value.code == 2
    assert "--chart" in capsys.readouterr().err


def test_main_helm_template_command_uses_chart_dir_name_by_default(vhss, monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="manifest", stderr="")

    monkeypatch.setattr(vhss, "run", fake_run)
    monkeypatch.setattr(vhss, "build_release", lambda *a, **kw: ({}, "1.0.0", []))
    monkeypatch.setattr("sys.argv", ["verify-helm-secret-size", "--chart", str(tmp_path)])

    vhss.main()

    assert captured["cmd"][:3] == ["helm", "template", tmp_path.name]
    assert "-f" not in captured["cmd"]


def test_main_helm_template_command_uses_explicit_name_and_values_file(vhss, monkeypatch, tmp_path):
    values_path = tmp_path / "lint-values.yaml"
    values_path.write_text("foo: bar\n")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="manifest", stderr="")

    monkeypatch.setattr(vhss, "run", fake_run)
    monkeypatch.setattr(vhss, "build_release", lambda *a, **kw: ({}, "1.0.0", []))
    monkeypatch.setattr("sys.argv", [
        "verify-helm-secret-size", "--chart", str(tmp_path), "--name", "podiumd", "-f", str(values_path),
    ])

    vhss.main()

    assert captured["cmd"][:3] == ["helm", "template", "podiumd"]
    assert "-f" in captured["cmd"]
    assert str(values_path) in captured["cmd"]


def test_main_passes_parsed_values_override_to_build_release(vhss, monkeypatch, tmp_path):
    values_path = tmp_path / "lint-values.yaml"
    values_path.write_text("foo: bar\n")
    monkeypatch.setattr(vhss, "run", lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="manifest", stderr=""))
    captured = {}

    def fake_build_release(chart_dir, values_override, manifest, name, namespace):
        captured["values_override"] = values_override
        return {}, "1.0.0", []

    monkeypatch.setattr(vhss, "build_release", fake_build_release)
    monkeypatch.setattr("sys.argv", ["verify-helm-secret-size", "--chart", str(tmp_path), "-f", str(values_path)])

    vhss.main()

    assert captured["values_override"] == {"foo": "bar"}


def test_main_no_values_file_means_no_config_override(vhss, monkeypatch, tmp_path):
    monkeypatch.setattr(vhss, "run", lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="manifest", stderr=""))
    captured = {}

    def fake_build_release(chart_dir, values_override, manifest, name, namespace):
        captured["values_override"] = values_override
        return {}, "1.0.0", []

    monkeypatch.setattr(vhss, "build_release", fake_build_release)
    monkeypatch.setattr("sys.argv", ["verify-helm-secret-size", "--chart", str(tmp_path)])

    vhss.main()

    assert captured["values_override"] is None


def test_main_render_failure_exits_one(vhss, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(vhss, "run", lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="boom"))
    monkeypatch.setattr("sys.argv", ["verify-helm-secret-size", "--chart", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        vhss.main()

    assert exc_info.value.code == 1
    assert "boom" in capsys.readouterr().err


def test_main_prints_report_on_success(vhss, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(vhss, "run", lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="manifest", stderr=""))
    monkeypatch.setattr(vhss, "build_release", lambda *a, **kw: ({"manifest": "x"}, "4.9.1", []))
    monkeypatch.setattr("sys.argv", ["verify-helm-secret-size", "--chart", str(tmp_path)])

    vhss.main()  # must not raise

    out = capsys.readouterr().out
    assert f"chart:          {tmp_path.name} 4.9.1" in out
    assert "used:" in out


def test_main_prints_subchart_freshness_warnings_to_stderr(vhss, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(vhss, "run", lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="manifest", stderr=""))
    monkeypatch.setattr(vhss, "build_release",
                         lambda *a, **kw: ({}, "4.9.1", ["Chart.yaml declares zac@1.0.297, stale vendored copy"]))
    monkeypatch.setattr("sys.argv", ["verify-helm-secret-size", "--chart", str(tmp_path)])

    vhss.main()

    err = capsys.readouterr().err
    assert "WARNING: Chart.yaml declares zac@1.0.297" in err


def test_main_record_flag_calls_record_result_and_prints_path(vhss, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(vhss, "run", lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="manifest", stderr=""))
    monkeypatch.setattr(vhss, "build_release", lambda *a, **kw: ({}, "4.9.1", []))
    recorded = {}

    def fake_record_result(chart_dir, chart_name, version, encoded_bytes, pct):
        recorded.update(chart_dir=chart_dir, chart_name=chart_name, version=version)
        return chart_dir / "docs" / "release-secret-size.md"

    monkeypatch.setattr(vhss, "record_result", fake_record_result)
    monkeypatch.setattr("sys.argv", ["verify-helm-secret-size", "--chart", str(tmp_path), "--record"])

    vhss.main()

    assert recorded["version"] == "4.9.1"
    out = capsys.readouterr().out
    assert "recorded:" in out
    assert "release-secret-size.md" in out


def test_main_without_record_flag_never_calls_record_result(vhss, monkeypatch, tmp_path):
    monkeypatch.setattr(vhss, "run", lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="manifest", stderr=""))
    monkeypatch.setattr(vhss, "build_release", lambda *a, **kw: ({}, "4.9.1", []))

    def fail_if_called(*a, **kw):
        raise AssertionError("record_result must not be called without --record")

    monkeypatch.setattr(vhss, "record_result", fail_if_called)
    monkeypatch.setattr("sys.argv", ["verify-helm-secret-size", "--chart", str(tmp_path)])

    vhss.main()  # must not raise


def test_main_exits_one_and_warns_at_threshold(vhss, monkeypatch, tmp_path, capsys):
    """Regression: the standalone CLI's own exit-1 semantics, unchanged
    by the refactor -- pct >= WARN_THRESHOLD still fails the run."""
    monkeypatch.setattr(vhss, "run", lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="manifest", stderr=""))
    monkeypatch.setattr(vhss, "build_release", lambda *a, **kw: ({}, "4.9.1", []))
    monkeypatch.setattr(vhss, "encoded_secret_size", lambda release: (1000, 500, 950000, 0.95))
    monkeypatch.setattr("sys.argv", ["verify-helm-secret-size", "--chart", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        vhss.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "95.0%" in err
    assert "request entity too large" in err


def test_main_passes_under_threshold_does_not_exit(vhss, monkeypatch, tmp_path):
    monkeypatch.setattr(vhss, "run", lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="manifest", stderr=""))
    monkeypatch.setattr(vhss, "build_release", lambda *a, **kw: ({}, "4.9.1", []))
    monkeypatch.setattr(vhss, "encoded_secret_size", lambda release: (1000, 500, 100, 0.0001))
    monkeypatch.setattr("sys.argv", ["verify-helm-secret-size", "--chart", str(tmp_path)])

    vhss.main()  # must not raise / must not sys.exit


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(vhss, monkeypatch, capsys, flag):
    monkeypatch.setattr("sys.argv", ["verify-helm-secret-size", flag])
    with pytest.raises(SystemExit) as exc_info:
        vhss.main()
    assert exc_info.value.code == 0
    assert "Estimate the size of the Helm release Secret" in capsys.readouterr().out
