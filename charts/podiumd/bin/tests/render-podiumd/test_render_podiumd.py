"""render-podiumd: renders the podiumd chart to a file of the caller's
choice via lib.render_scope.render_chart/lint_args_for — the same helpers
verify-podiumd's own checks use, so this stays DRY with them rather than
re-implementing the `helm template` invocation. helm/render_chart are
mocked out via rp.render_chart directly (same level test_misc.py's
--skip=/--include= tests mock vp.check_X at) — no real helm invocation
happens in these tests."""

from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest

from lib import dependencies


def fake_render_chart(returncode=0, stdout="", stderr=""):
    def _render_chart(chart_dir, extra_args):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return _render_chart


# --- -h/--help and argument validation ---


def test_help_flag_prints_docstring_and_exits_0(
    rp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        rp.main()
    assert exc_info.value.code == 0
    assert "Usage:" in capsys.readouterr().out


# --- default output path (no output-file given) ---


def test_no_args_writes_to_default_output(
    rp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """No output-file at all must fall back to DEFAULT_OUTPUT
    (charts/podiumd/rendered-helm.yaml) rather than erroring — this is
    now the common "just render it" case."""
    default_output = tmp_path / "rendered-helm.yaml"
    monkeypatch.setattr(rp, "DEFAULT_OUTPUT", default_output)
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd"])
    monkeypatch.setattr(rp, "lint_args_for", lambda chart_dir: [])
    monkeypatch.setattr(rp, "render_chart", fake_render_chart(0, "---\n# Source: a.yaml\nkind: Foo\n"))

    rp.main()

    assert default_output.read_text() == "---\n# Source: a.yaml\nkind: Foo\n"
    out = capsys.readouterr().out
    assert f"OK: rendered 1 manifest(s) to {default_output}" in out


# --- default extra_args (no extra CLI args given) ---


def test_no_extra_args_uses_lint_args_for_default(rp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    output_path = tmp_path / "out.yaml"
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd", str(output_path)])
    monkeypatch.setattr(rp, "lint_args_for", lambda chart_dir: ["-f", "ci/lint-values.yaml"])

    captured = {}

    def fake_render(chart_dir, extra_args):
        captured["extra_args"] = extra_args
        return SimpleNamespace(returncode=0, stdout="---\n# Source: a.yaml\nkind: Foo\n", stderr="")

    monkeypatch.setattr(rp, "render_chart", fake_render)

    rp.main()

    assert captured["extra_args"] == ["-f", "ci/lint-values.yaml"]


def test_no_extra_args_announces_default_ci_values(
    rp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A schema/render failure from a custom-args run (see the override test
    below) must never be mistaken for the standard verify-podiumd check
    failing — this printed line is what tells the two apart, so it must
    always say which basis was actually used before rendering."""
    output_path = tmp_path / "out.yaml"
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd", str(output_path)])
    monkeypatch.setattr(rp, "lint_args_for", lambda chart_dir: ["-f", "ci/lint-values.yaml"])
    monkeypatch.setattr(rp, "render_chart", fake_render_chart(0, "---\n# Source: a.yaml\nkind: Foo\n"))

    rp.main()

    out = capsys.readouterr().out
    assert "Rendering with default CI values: -f ci/lint-values.yaml" in out


# --- explicit extra CLI args override the default entirely ---


def test_extra_cli_args_override_default_lint_args(rp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    output_path = tmp_path / "out.yaml"
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd", str(output_path), "-s", "templates/frankgateway.yaml"])

    def fail_if_called(chart_dir):
        msg = "lint_args_for must not be called when extra args are given"
        raise AssertionError(msg)

    monkeypatch.setattr(rp, "lint_args_for", fail_if_called)

    captured = {}

    def fake_render(chart_dir, extra_args):
        captured["extra_args"] = extra_args
        return SimpleNamespace(returncode=0, stdout="---\n# Source: a.yaml\nkind: Foo\n", stderr="")

    monkeypatch.setattr(rp, "render_chart", fake_render)

    rp.main()

    assert captured["extra_args"] == ["-s", "templates/frankgateway.yaml"]


def test_extra_cli_args_announce_custom_render_not_default(
    rp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    output_path = tmp_path / "out.yaml"
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd", str(output_path), "-s", "templates/frankgateway.yaml"])
    monkeypatch.setattr(rp, "render_chart", fake_render_chart(0, "---\n# Source: a.yaml\nkind: Foo\n"))

    rp.main()

    out = capsys.readouterr().out
    assert (
        "Rendering with custom args (default -f ci/lint-values.yaml NOT applied): -s templates/frankgateway.yaml" in out
    )


# --- success: writes the rendered output and reports a doc count ---


def test_success_writes_rendered_output_to_file(
    rp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    output_path = tmp_path / "out.yaml"
    rendered = (
        "---\n# Source: podiumd/templates/a.yaml\nkind: Foo\n---\n# Source: podiumd/templates/b.yaml\nkind: Bar\n"
    )
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd", str(output_path)])
    monkeypatch.setattr(rp, "lint_args_for", lambda chart_dir: [])
    monkeypatch.setattr(rp, "render_chart", fake_render_chart(0, rendered))

    rp.main()

    assert output_path.read_text() == rendered
    out = capsys.readouterr().out
    assert f"OK: rendered 2 manifest(s) to {output_path}" in out
    assert "Largest rendered templates" in out


# --- failure: helm template fails, nothing written, exits 1 ---


def test_failure_does_not_write_file_and_exits_1(
    rp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    output_path = tmp_path / "out.yaml"
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd", str(output_path)])
    monkeypatch.setattr(rp, "lint_args_for", lambda chart_dir: [])
    monkeypatch.setattr(
        rp, "render_chart", fake_render_chart(1, "", "Error: podiumd/charts/zac/templates/a.yaml: broke")
    )

    with pytest.raises(SystemExit) as exc_info:
        rp.main()

    assert exc_info.value.code == 1
    assert not output_path.exists()
    out = capsys.readouterr().out
    assert "zac: 1" in out  # report_errors_by_subchart grouping
    assert "failed to render" in out


# --- --stdout: rendered YAML on stdout, every other message on stderr ---


def test_stdout_flag_writes_rendered_yaml_to_stdout(
    rp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    rendered = "---\n# Source: a.yaml\nkind: Foo\n"
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd", "--stdout"])
    monkeypatch.setattr(rp, "lint_args_for", lambda chart_dir: [])
    monkeypatch.setattr(rp, "render_chart", fake_render_chart(0, rendered))

    rp.main()

    captured = capsys.readouterr()
    assert captured.out == rendered  # stdout is PURE rendered YAML, nothing else


def test_stdout_flag_puts_status_and_summary_on_stderr(
    rp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    rendered = (
        "---\n# Source: podiumd/templates/a.yaml\nkind: Foo\n---\n# Source: podiumd/templates/b.yaml\nkind: Bar\n"
    )
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd", "--stdout"])
    monkeypatch.setattr(rp, "lint_args_for", lambda chart_dir: ["-f", "ci/lint-values.yaml"])
    monkeypatch.setattr(rp, "render_chart", fake_render_chart(0, rendered))

    rp.main()

    captured = capsys.readouterr()
    assert captured.out == rendered
    assert "Rendering with default CI values: -f ci/lint-values.yaml" in captured.err
    assert "OK: rendered 2 manifest(s) to stdout" in captured.err
    assert "Largest rendered templates" in captured.err  # report_largest_templates, redirected


def test_stdout_flag_with_extra_args(
    rp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    rendered = "---\n# Source: a.yaml\nkind: Foo\n"
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd", "--stdout", "-s", "templates/frankgateway.yaml"])

    def fail_if_called(chart_dir):
        msg = "lint_args_for must not be called when extra args are given"
        raise AssertionError(msg)

    monkeypatch.setattr(rp, "lint_args_for", fail_if_called)

    captured_args = {}

    def fake_render(chart_dir, extra_args):
        captured_args["extra_args"] = extra_args
        return SimpleNamespace(returncode=0, stdout=rendered, stderr="")

    monkeypatch.setattr(rp, "render_chart", fake_render)

    rp.main()

    assert captured_args["extra_args"] == ["-s", "templates/frankgateway.yaml"]
    assert capsys.readouterr().out == rendered


def test_stdout_flag_failure_puts_everything_on_stderr_and_writes_nothing(
    rp: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd", "--stdout"])
    monkeypatch.setattr(rp, "lint_args_for", lambda chart_dir: [])
    monkeypatch.setattr(
        rp, "render_chart", fake_render_chart(1, "", "Error: podiumd/charts/zac/templates/a.yaml: broke")
    )

    with pytest.raises(SystemExit) as exc_info:
        rp.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # nothing on stdout, even on failure
    assert "zac: 1" in captured.err
    assert "nothing written to stdout" in captured.err


# --- stale vendored sub-charts guard ---


def test_stale_vendored_dependencies_re_vendored_before_rendering(
    rp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Chart.yaml wants kiss-chart 3.1.1 but charts/ still has 3.0.0: the
    guard must re-vendor it BEFORE render_chart runs (which would
    otherwise fail on an unrelated-looking kiss-chart schema error), so
    the render sees an in-sync state. helm stubbed: `helm pull` writes the
    .tgz into --destination, every other call just succeeds."""
    (tmp_path / "Chart.yaml").write_text(
        "dependencies:\n  - name: kiss-chart\n    version: 3.1.1\n    repository: oci://ghcr.io/kiss\n",
        encoding="utf-8",
    )
    (tmp_path / "Chart.lock").write_text(
        "dependencies:\n  - name: kiss-chart\n    version: 3.0.0\n    repository: oci://ghcr.io/kiss\n",
        encoding="utf-8",
    )
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts" / "kiss-chart-3.0.0.tgz").touch()

    def fake_helm(cmd, **kwargs):
        if cmd[1] == "pull":
            dest = Path(cmd[cmd.index("--destination") + 1])
            (dest / "kiss-chart-3.1.1.tgz").touch()
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    rendered = []
    monkeypatch.setattr(dependencies, "run", fake_helm)
    monkeypatch.setattr(rp, "ensure_vendored_dependencies", dependencies.ensure_vendored_dependencies)
    monkeypatch.setattr(rp, "CHART_DIR", tmp_path)
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd", str(tmp_path / "out.yaml")])

    def fake_render(chart_dir, extra_args):
        rendered.append(dependencies.vendored_dependency_problems(chart_dir))
        raise SystemExit(0)

    monkeypatch.setattr(rp, "render_chart", fake_render)

    with pytest.raises(SystemExit):
        rp.main()

    assert rendered == [[]]
    assert sorted(path.name for path in (tmp_path / "charts").iterdir()) == ["kiss-chart-3.1.1.tgz"]
