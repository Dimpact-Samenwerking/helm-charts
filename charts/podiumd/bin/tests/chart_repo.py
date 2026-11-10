"""A podiumd chart in a throwaway git repository, for tests that compare a release state with a tagged baseline."""

from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from tests.fixture_data import write_chart_dependencies
from tests.git_repo import commit_all
from tests.git_repo import commit_tagged
from tests.git_repo import init_git_repo

UPGRADE_DOC_PATH = "docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md"
GEMEENTE_DOC_PATH = "docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-gemeente-specific.md"
VALUES_DELTAS_PATH = "docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-values-deltas.md"
IMAGES_MANIFEST_PATH = "docs/images/images-4.9.0.yaml"


def write_chart_files(chart_dir: Path, files: Mapping[str, str]) -> None:
    """Write each `files` entry (path relative to chart_dir: text), creating its directory."""
    for relative_path, text in files.items():
        path = chart_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def write_chart_state(
    chart_dir: Path, deps: list[dict[str, str]], values: Mapping[str, object], *, sort_values: bool = True
) -> None:
    """Chart.yaml with `deps` and values.yaml with `values`: one release state of the chart."""
    write_chart_dependencies(chart_dir / "Chart.yaml", deps)
    (chart_dir / "values.yaml").write_text(yaml.safe_dump(dict(values), sort_keys=sort_values), encoding="utf-8")


def make_doc_dirs(chart_dir: Path) -> Path:
    """docs/_UPGRADE_PATHS and docs/images, as a release has them; returns docs/_UPGRADE_PATHS."""
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True, exist_ok=True)
    (chart_dir / "docs" / "images").mkdir(parents=True, exist_ok=True)
    return doc_dir


def point_chart_paths(script: ModuleType, monkeypatch: pytest.MonkeyPatch, chart_dir: Path) -> None:
    """Make a script's CHART_DIR, CHART_YAML and VALUES_YAML the test chart's."""
    monkeypatch.setattr(script, "CHART_DIR", chart_dir)
    monkeypatch.setattr(script, "CHART_YAML", chart_dir / "Chart.yaml")
    monkeypatch.setattr(script, "VALUES_YAML", chart_dir / "values.yaml")


def docs_text(chart_dir: Path) -> dict[str, str]:
    """Every file under docs/, by its path relative to docs/."""
    root = chart_dir / "docs"
    return {str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*")) if p.is_file()}


def seed_chart_repo(
    chart_dir: Path, deps: list[dict[str, str]], values: Mapping[str, object], *, sort_values: bool = True
) -> Path:
    """A new repository holding the given state and empty doc dirs, uncommitted; returns docs/_UPGRADE_PATHS."""
    init_git_repo(chart_dir)
    write_chart_state(chart_dir, deps, values, sort_values=sort_values)
    return make_doc_dirs(chart_dir)


def tagged_baseline_repo(
    chart_dir: Path, deps: list[dict[str, str]], values: Mapping[str, object], *, sort_values: bool = True
) -> Path:
    """seed_chart_repo with the state committed and tagged podiumd-4.8.5; returns docs/_UPGRADE_PATHS."""
    doc_dir = seed_chart_repo(chart_dir, deps, values, sort_values=sort_values)
    commit_tagged(chart_dir, "baseline state", "4.8.5")
    return doc_dir


def commit_text_baseline(repo_root: Path, chart_yaml: str, values: str, chart_subdir: str = "charts/podiumd") -> Path:
    """A new repository at repo_root with this Chart.yaml and values.yaml in chart_subdir ("" for the root) and
    empty doc dirs, tagged podiumd-4.8.5; returns the chart dir."""
    chart_dir = repo_root / chart_subdir
    init_git_repo(repo_root)
    write_chart_files(chart_dir, {"Chart.yaml": chart_yaml, "values.yaml": values})
    make_doc_dirs(chart_dir)
    commit_tagged(repo_root, "baseline", "4.8.5")
    return chart_dir


def commit_hop(chart_dir: Path, message: str, files: Mapping[str, str]) -> None:
    """Write the hop's `files` under chart_dir (in charts/podiumd) and commit them on top of the baseline."""
    write_chart_files(chart_dir, files)
    commit_all(chart_dir.parents[1], message)
