"""Load update-image-version (hyphenated, not importable) as module `uiv`.

An autouse fixture points the module's path constants at a hermetic
tmp_path, because main() would otherwise write the real values.yaml. Also stubs the final
fix-helm-doc call."""

import importlib.util
import subprocess

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest
import yaml

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "update-image-version"


@pytest.fixture(scope="session")
def uiv() -> ModuleType:
    loader = SourceFileLoader("update_image_version_cli", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("update_image_version_cli", SCRIPT_PATH, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def isolate_paths(uiv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text(
        yaml.safe_dump({"apiVersion": "v2", "name": "podiumd", "version": "1.0.0", "dependencies": []}),
        encoding="utf-8",
    )
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_yaml)


@pytest.fixture(autouse=True)
def stub_fix_helm_doc(uiv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    real_run = subprocess.run
    target = str(uiv.FIX_HELM_DOC_SCRIPT)

    def fake_run(cmd, *args, **kwargs):
        if isinstance(cmd, (list, tuple)) and target in cmd:
            return subprocess.CompletedProcess(cmd, 0)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)


@pytest.fixture(autouse=True)
def stub_ensure_vendored_dependencies(uiv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Stub ensure_vendored_dependencies: the fake chart has no vendored
    sub-charts. Tests of the guard restore the real one."""
    monkeypatch.setattr(uiv, "ensure_vendored_dependencies", lambda chart_dir: None)


@pytest.fixture(autouse=True)
def stub_run_fix_doc_consistency(uiv: ModuleType, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record run_fix_doc_consistency calls instead of running the real
    script on the real chart; returns one "fix-doc" item per call."""
    calls: list[str] = []

    def record() -> None:
        calls.append("fix-doc")

    monkeypatch.setattr(uiv, "complete_docs_and_finish", record)
    return calls
