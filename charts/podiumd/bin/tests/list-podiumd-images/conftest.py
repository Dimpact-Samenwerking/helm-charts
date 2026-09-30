"""Load list-podiumd-images (hyphenated, not importable) with its path
constants pointed at a temp dir, so tests never read the real chart."""

import importlib.util

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "list-podiumd-images"


@pytest.fixture(scope="session")
def _module() -> ModuleType:
    loader = SourceFileLoader("list_podiumd_images", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("list_podiumd_images", SCRIPT_PATH, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class _AllChartTreePaths:
    """rendered_paths stand-in reporting every path as rendered, so tests
    that don't exercise the render-gate treat everything as live."""

    def __contains__(self, item):
        return True


@pytest.fixture(autouse=True)
def stub_render_chart(_module: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Stub render_chart: a real `helm template` would run against the
    synthetic tmp_path chart. Tests of disabled paths override this."""
    monkeypatch.setattr(
        _module, "render_chart", lambda chart_dir, extra_args: SimpleNamespace(returncode=0, stdout="", stderr="")
    )
    monkeypatch.setattr(_module, "rendered_chart_paths", lambda stdout: _AllChartTreePaths())


@pytest.fixture
def lpi(_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    vendored_dir = tmp_path / "charts"
    vendored_dir.mkdir()
    monkeypatch.setattr(_module, "CHART_YAML", tmp_path / "Chart.yaml")
    monkeypatch.setattr(_module, "VALUES_YAML", tmp_path / "values.yaml")
    monkeypatch.setattr(_module, "VENDORED_DIR", vendored_dir)
    return _module


@pytest.fixture(autouse=True)
def stub_ensure_vendored_dependencies(_module: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Stub ensure_vendored_dependencies: the fake chart has no vendored
    sub-charts. Tests of the guard restore the real one."""
    monkeypatch.setattr(_module, "ensure_vendored_dependencies", lambda chart_dir: None)
