"""render-podiumd.py: renders the podiumd chart to a file of the caller's
choice via lib.render_scope.render_chart/lint_args_for — the same helpers
verify-podiumd.py's own checks use, so this stays DRY with them rather than
re-implementing the `helm template` invocation. helm/render_chart are
mocked out via rp.render_chart directly (same level test_misc.py's
--skip=/--include= tests mock vp.check_X at) — no real helm invocation
happens in these tests."""
from types import SimpleNamespace

import pytest


def fake_render_chart(returncode=0, stdout="", stderr=""):
    def _render_chart(chart_dir, extra_args):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    return _render_chart


# --- -h/--help and argument validation ---

def test_help_flag_prints_docstring_and_exits_0(rp, monkeypatch, capsys):
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd.py", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        rp.main()
    assert exc_info.value.code == 0
    assert "Usage:" in capsys.readouterr().out


def test_no_output_file_prints_docstring_and_exits_1(rp, monkeypatch, capsys):
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd.py"])
    with pytest.raises(SystemExit) as exc_info:
        rp.main()
    assert exc_info.value.code == 1
    assert "Usage:" in capsys.readouterr().out


# --- default extra_args (no extra CLI args given) ---

def test_no_extra_args_uses_lint_args_for_default(rp, tmp_path, monkeypatch):
    output_path = tmp_path / "out.yaml"
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd.py", str(output_path)])
    monkeypatch.setattr(rp, "lint_args_for", lambda chart_dir: ["-f", "ci/lint-values.yaml"])

    captured = {}

    def fake_render(chart_dir, extra_args):
        captured["extra_args"] = extra_args
        return SimpleNamespace(returncode=0, stdout="---\n# Source: a.yaml\nkind: Foo\n", stderr="")

    monkeypatch.setattr(rp, "render_chart", fake_render)

    rp.main()

    assert captured["extra_args"] == ["-f", "ci/lint-values.yaml"]


def test_no_extra_args_announces_default_ci_values(rp, tmp_path, monkeypatch, capsys):
    """A schema/render failure from a custom-args run (see the override test
    below) must never be mistaken for the standard verify-podiumd.py check
    failing — this printed line is what tells the two apart, so it must
    always say which basis was actually used before rendering."""
    output_path = tmp_path / "out.yaml"
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd.py", str(output_path)])
    monkeypatch.setattr(rp, "lint_args_for", lambda chart_dir: ["-f", "ci/lint-values.yaml"])
    monkeypatch.setattr(rp, "render_chart", fake_render_chart(0, "---\n# Source: a.yaml\nkind: Foo\n"))

    rp.main()

    out = capsys.readouterr().out
    assert "Rendering with default CI values: -f ci/lint-values.yaml" in out


# --- explicit extra CLI args override the default entirely ---

def test_extra_cli_args_override_default_lint_args(rp, tmp_path, monkeypatch):
    output_path = tmp_path / "out.yaml"
    monkeypatch.setattr(rp.sys, "argv",
                         ["render-podiumd.py", str(output_path), "-s", "templates/frankgateway.yaml"])

    def fail_if_called(chart_dir):
        raise AssertionError("lint_args_for must not be called when extra args are given")

    monkeypatch.setattr(rp, "lint_args_for", fail_if_called)

    captured = {}

    def fake_render(chart_dir, extra_args):
        captured["extra_args"] = extra_args
        return SimpleNamespace(returncode=0, stdout="---\n# Source: a.yaml\nkind: Foo\n", stderr="")

    monkeypatch.setattr(rp, "render_chart", fake_render)

    rp.main()

    assert captured["extra_args"] == ["-s", "templates/frankgateway.yaml"]


def test_extra_cli_args_announce_custom_render_not_default(rp, tmp_path, monkeypatch, capsys):
    output_path = tmp_path / "out.yaml"
    monkeypatch.setattr(rp.sys, "argv",
                         ["render-podiumd.py", str(output_path), "-s", "templates/frankgateway.yaml"])
    monkeypatch.setattr(rp, "render_chart", fake_render_chart(0, "---\n# Source: a.yaml\nkind: Foo\n"))

    rp.main()

    out = capsys.readouterr().out
    assert "Rendering with custom args (default -f ci/lint-values.yaml NOT applied): " \
           "-s templates/frankgateway.yaml" in out


# --- success: writes the rendered output and reports a doc count ---

def test_success_writes_rendered_output_to_file(rp, tmp_path, monkeypatch, capsys):
    output_path = tmp_path / "out.yaml"
    rendered = "---\n# Source: podiumd/templates/a.yaml\nkind: Foo\n---\n# Source: podiumd/templates/b.yaml\nkind: Bar\n"
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd.py", str(output_path)])
    monkeypatch.setattr(rp, "lint_args_for", lambda chart_dir: [])
    monkeypatch.setattr(rp, "render_chart", fake_render_chart(0, rendered))

    rp.main()

    assert output_path.read_text() == rendered
    out = capsys.readouterr().out
    assert f"OK: rendered 2 manifest(s) to {output_path}" in out
    assert "Largest rendered templates" in out


# --- failure: helm template fails, nothing written, exits 1 ---

def test_failure_does_not_write_file_and_exits_1(rp, tmp_path, monkeypatch, capsys):
    output_path = tmp_path / "out.yaml"
    monkeypatch.setattr(rp.sys, "argv", ["render-podiumd.py", str(output_path)])
    monkeypatch.setattr(rp, "lint_args_for", lambda chart_dir: [])
    monkeypatch.setattr(rp, "render_chart", fake_render_chart(1, "", "Error: podiumd/charts/zac/templates/a.yaml: broke"))

    with pytest.raises(SystemExit) as exc_info:
        rp.main()

    assert exc_info.value.code == 1
    assert not output_path.exists()
    out = capsys.readouterr().out
    assert "zac: 1" in out  # report_errors_by_subchart grouping
    assert "failed to render" in out
