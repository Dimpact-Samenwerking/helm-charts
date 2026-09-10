"""Loads list-podiumd-images (a hyphenated filename, not importable
normally) as a module, with its module-level path constants (CHART_YAML,
VALUES_YAML, VENDORED_DIR) repointed at an isolated temp directory so tests
never read/depend on the real chart."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "list-podiumd-images"


@pytest.fixture(scope="session")
def _module():
    loader = SourceFileLoader("list_podiumd_images", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("list_podiumd_images", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _AllChartTreePaths:
    """A rendered_paths stand-in whose `in` check always reports True —
    the default stub_render_chart fixture's behavior below, so every
    test written before the render-gate existed (assuming every
    declared dependency/row is live, the same assumption the old
    condition-only is_enabled() effectively made) keeps working
    unchanged. A test that specifically wants to exercise the new
    disabled-via-render-gate behavior overrides render_chart/
    rendered_chart_paths itself, same convention as any other autouse
    default (see tests/fix-doc-consistency/conftest.py's own
    stub_render_chart, which this mirrors)."""

    def __contains__(self, item):
        return True


@pytest.fixture(autouse=True)
def stub_render_chart(_module, monkeypatch):
    """main()'s own new render_chart() call (feeding the render-gate
    that replaced the old condition-only is_enabled()) would otherwise
    invoke a REAL `helm template` against whatever CHART_YAML/
    VALUES_YAML/VENDORED_DIR a test has monkeypatched via the `lpi`
    fixture below — a synthetic tmp_path chart with no real vendored
    structure behind it at all. Stubbed to a successful render whose
    rendered_paths reports EVERY chart-tree path as rendered by
    default (see _AllChartTreePaths) — a test exercising the new
    disabled/nested-disabled behavior overrides this via its own
    monkeypatch.setattr, same as any other autouse default."""
    monkeypatch.setattr(_module, "render_chart",
                         lambda chart_dir, extra_args: SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(_module, "rendered_chart_paths", lambda stdout: _AllChartTreePaths())


@pytest.fixture
def lpi(_module, tmp_path, monkeypatch):
    vendored_dir = tmp_path / "charts"
    vendored_dir.mkdir()
    monkeypatch.setattr(_module, "CHART_YAML", tmp_path / "Chart.yaml")
    monkeypatch.setattr(_module, "VALUES_YAML", tmp_path / "values.yaml")
    monkeypatch.setattr(_module, "VENDORED_DIR", vendored_dir)
    return _module
