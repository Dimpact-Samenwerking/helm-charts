"""lib.image.baseline_refresh — the render + regenerate step shared by
fix-doc-consistency, update-component-version and update-image-version."""

from types import SimpleNamespace

import pytest

import lib.image.baseline_refresh as baseline_refresh


def test_refresh_images_baseline_passes_the_render_to_the_regeneration(tmp_path, monkeypatch, capsys):
    """The render's paths reach regenerate_images_baseline_manifest, and
    its result (written count, unresolvable repositories) is reported."""
    seen = {}
    monkeypatch.setattr(baseline_refresh, "lint_args_for", lambda chart_dir: ["-f", "ci/lint-values.yaml"])
    monkeypatch.setattr(
        baseline_refresh,
        "render_chart",
        lambda chart_dir, extra_args: SimpleNamespace(returncode=0, stdout="rendered", stderr=""),
    )
    monkeypatch.setattr(baseline_refresh, "rendered_chart_paths", lambda stdout: {stdout})

    def fake_regenerate(chart_dir, deps, values, images_baseline_path, rendered_paths):
        seen.update(chart_dir=chart_dir, deps=deps, values=values, path=images_baseline_path, rendered=rendered_paths)
        return 3, ["docker.io/unresolvable"], True

    monkeypatch.setattr(baseline_refresh, "regenerate_images_baseline_manifest", fake_regenerate)
    path = tmp_path / "images-baseline.yaml"

    baseline_refresh.refresh_images_baseline(tmp_path, [{"name": "zac"}], {"zac": {}}, path)

    assert seen == {
        "chart_dir": tmp_path,
        "deps": [{"name": "zac"}],
        "values": {"zac": {}},
        "path": path,
        "rendered": {"rendered"},
    }
    out = capsys.readouterr().out
    assert "=== Regenerating images-baseline.yaml ===" in out
    assert "wrote 3 entries" in out
    assert "docker.io/unresolvable" in out


def test_refresh_images_baseline_exits_when_the_render_fails(tmp_path, monkeypatch):
    """A failed render exits 1 before anything is written."""
    monkeypatch.setattr(baseline_refresh, "lint_args_for", lambda chart_dir: [])
    monkeypatch.setattr(
        baseline_refresh,
        "render_chart",
        lambda chart_dir, extra_args: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )
    path = tmp_path / "images-baseline.yaml"

    with pytest.raises(SystemExit) as exc_info:
        baseline_refresh.refresh_images_baseline(tmp_path, [], {}, path)

    assert exc_info.value.code == 1
    assert not path.exists()
