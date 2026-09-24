"""lib.image.baseline_refresh — the render + regenerate step shared by
fix-doc-consistency, update-component-version and update-image-version."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.chart.chart_yaml import ChartDependency
from lib.image import baseline_refresh
from lib.yaml_types import YamlMapping


def no_lint_args(_chart_dir: Path) -> list[str]:
    return []


def render_returning(returncode: int, stdout: str):
    """A render_chart stand-in whose render ends with `returncode`."""

    def fake_render_chart(_chart_dir: Path, _extra_args: list[str]) -> SimpleNamespace:
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="boom" if returncode else "")

    return fake_render_chart


def test_refresh_images_baseline_passes_the_render_to_the_regeneration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The render's paths reach regenerate_images_baseline_manifest, and
    its result (written count, unresolvable repositories) is reported."""
    seen: dict[str, object] = {}

    def rendered_paths_of(stdout: str) -> set[str]:
        return {stdout}

    def fake_regenerate(
        chart_dir: Path,
        deps: list[ChartDependency],
        values: YamlMapping,
        images_baseline_path: Path,
        rendered_paths: set[str],
    ) -> tuple[int, list[str], bool]:
        seen.update(chart_dir=chart_dir, deps=deps, values=values, path=images_baseline_path, rendered=rendered_paths)
        return 3, ["docker.io/unresolvable"], True

    monkeypatch.setattr(baseline_refresh, "lint_args_for", no_lint_args)
    monkeypatch.setattr(baseline_refresh, "render_chart", render_returning(0, "rendered"))
    monkeypatch.setattr(baseline_refresh, "rendered_chart_paths", rendered_paths_of)
    monkeypatch.setattr(baseline_refresh, "regenerate_images_baseline_manifest", fake_regenerate)
    path = tmp_path / "images-baseline.yaml"

    baseline_refresh.refresh_images_baseline(tmp_path, [{"name": "zac", "version": "1.0.0"}], {"zac": {}}, path)

    assert seen == {
        "chart_dir": tmp_path,
        "deps": [{"name": "zac", "version": "1.0.0"}],
        "values": {"zac": {}},
        "path": path,
        "rendered": {"rendered"},
    }
    out = capsys.readouterr().out
    assert "=== Regenerating images-baseline.yaml ===" in out
    assert "wrote 3 entries" in out
    assert "docker.io/unresolvable" in out


def test_refresh_images_baseline_exits_when_the_render_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed render exits 1 before anything is written."""
    monkeypatch.setattr(baseline_refresh, "lint_args_for", no_lint_args)
    monkeypatch.setattr(baseline_refresh, "render_chart", render_returning(1, ""))
    path = tmp_path / "images-baseline.yaml"

    with pytest.raises(SystemExit) as exc_info:
        baseline_refresh.refresh_images_baseline(tmp_path, [], {}, path)

    assert exc_info.value.code == 1
    assert not path.exists()
