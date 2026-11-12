"""The real fix-doc-consistency run on a chart in a throwaway git repository, for the update-* end-to-end tests."""

from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest

import lib.image.docs as image_docs

from lib.docs_consistency.check import check_docs_consistency
from lib.fix_doc_consistency.rebase_state import FixDocPaths
from lib.fix_doc_consistency.run import fix_docs
from lib.image import baseline_refresh
from tests.chart_repo import docs_text
from tests.chart_repo import point_chart_paths
from tests.git_repo import commit_all

UPGRADE = "_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md"
MANIFEST = "images/images-4.9.0.yaml"


def _rename(old: Path, new: Path) -> None:
    """A plain rename: the test repository needs no git mv."""
    old.rename(new)


def run_fix_docs(chart_dir: Path) -> None:
    """fix-doc-consistency on chart_dir's docs for the 4.8.5 → 4.9.0 hop."""
    fix_docs(
        FixDocPaths(chart_dir, chart_dir / "docs" / "_UPGRADE_PATHS", chart_dir / "docs" / "images", _rename),
        "4.9.0",
        "4.8.5",
    )


def stub_registry_and_render(monkeypatch: pytest.MonkeyPatch, cached_digest: str, live_digest: str) -> None:
    """Every image exists in the registry (cached and live lookups), and the chart renders empty."""
    monkeypatch.setattr(image_docs, "cached_tag_exists", lambda chart_dir, repository, version: (True, cached_digest))
    monkeypatch.setattr("lib.registry.registry_tag_exists", lambda host, repo, tag: (True, live_digest))
    monkeypatch.setattr(
        baseline_refresh,
        "render_chart",
        lambda chart_dir, extra_args: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )


def document_earlier_bump(chart_dir: Path, heading_prefix: str, note: str, message: str) -> None:
    """Write the docs for the working tree's bump, put `note` under the heading starting with
    `heading_prefix` as user text, and commit it all."""
    run_fix_docs(chart_dir)
    upgrade = chart_dir / "docs" / UPGRADE
    text = upgrade.read_text(encoding="utf-8")
    heading = next(line for line in text.splitlines() if line.startswith(heading_prefix))
    upgrade.write_text(text.replace(f"{heading}\n\n", f"{heading}\n\n{note}\n"), encoding="utf-8")
    commit_all(chart_dir, message)


def point_script_at(script: ModuleType, monkeypatch: pytest.MonkeyPatch, chart_dir: Path) -> None:
    """An update-* script working on chart_dir, finishing with the real fix-doc-consistency run."""
    point_chart_paths(script, monkeypatch, chart_dir)
    monkeypatch.setattr(script, "complete_docs_and_finish", lambda: run_fix_docs(chart_dir))


def bump(script: ModuleType, chart_dir: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> dict[str, str]:
    """Run the update-* script's main() as `argv` (its name first), then require the checker to accept the docs."""
    monkeypatch.setattr("sys.argv", list(argv))
    script.main()
    written = docs_text(chart_dir)
    ok, detail = check_docs_consistency(chart_dir, "4.8.5")
    assert ok, detail
    return written
