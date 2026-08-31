"""Loads update-image-version (a hyphenated filename, not importable
normally) as a module named `uiv` so tests can call its functions/main()
directly.

An autouse fixture points every module-level path constant (CHART_DIR,
CHART_YAML, VALUES_YAML, DOC_DIR, IMAGES_DIR) at a hermetic tmp_path by
default — main() now always runs the doc-update step after a successful
bump (lib.component_docs/lib.image_docs), which reads/writes real files
at those paths; without this, a test that only cares about the
values.yaml bump itself (the pre-existing convention here — only
VALUES_YAML used to matter) would silently read/write the REAL
charts/podiumd/Chart.yaml and docs/ tree instead. A test can still
override any of these further (e.g. write its own Chart.yaml) for its
own scenario. Also stubs the unconditional fix-podiumd-readme
subprocess call at the end of main(), same convention as
tests/set-doc-baseline/conftest.py."""
import importlib.util
from importlib.machinery import SourceFileLoader
import subprocess
from pathlib import Path

import pytest
import yaml

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "update-image-version"


@pytest.fixture(scope="session")
def uiv():
    loader = SourceFileLoader("update_image_version_cli", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("update_image_version_cli", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def isolate_paths(uiv, tmp_path, monkeypatch):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text(
        yaml.safe_dump({"apiVersion": "v2", "name": "podiumd", "version": "1.0.0", "dependencies": []}),
        encoding="utf-8",
    )
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text("{}\n", encoding="utf-8")
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    images_dir = tmp_path / "docs" / "images"
    doc_dir.mkdir(parents=True)
    images_dir.mkdir(parents=True)

    monkeypatch.setattr(uiv, "CHART_DIR", tmp_path)
    monkeypatch.setattr(uiv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(uiv, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(uiv, "DOC_DIR", doc_dir)
    monkeypatch.setattr(uiv, "IMAGES_DIR", images_dir)


@pytest.fixture(autouse=True)
def stub_fix_podiumd_readme(uiv, monkeypatch):
    real_run = subprocess.run
    target = str(uiv.FIX_README_SCRIPT)

    def fake_run(cmd, *args, **kwargs):
        if isinstance(cmd, (list, tuple)) and target in cmd:
            return subprocess.CompletedProcess(cmd, 0)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
