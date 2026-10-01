"""fix_docs_dry_run: fix-doc-consistency on a copy of the docs, never on the docs themselves."""

import subprocess

from pathlib import Path

from lib.docs_consistency.dry_run import fix_docs_dry_run


def _docs_snapshot(chart_dir: Path) -> dict[str, str]:
    docs = chart_dir / "docs"
    return {str(p.relative_to(docs)): p.read_text(encoding="utf-8") for p in sorted(docs.rglob("*")) if p.is_file()}


def test_consistent_docs_give_no_changes(chart_repo: Path):
    with fix_docs_dry_run(chart_repo, "4.9.0", "4.8.5") as dry:
        assert dry.error is None
        assert dry.changes == []
        assert (dry.docs_dir / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md").is_file()
    assert not dry.docs_dir.exists()


def test_a_rebase_renames_in_the_copy_and_leaves_the_real_docs_alone(chart_repo: Path):
    """Rebasing onto 4.8.6 renames every doc; git mv must not run on the real docs."""
    before = _docs_snapshot(chart_repo)

    with fix_docs_dry_run(chart_repo, "4.9.0", "4.8.6") as dry:
        changes = {change.name: change.status for change in dry.changes}

    assert changes["_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md"] == "removed"
    assert changes["_UPGRADE_PATHS/4.8.6-to-4.9.0-upgrade.md"] == "created"
    assert _docs_snapshot(chart_repo) == before
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=chart_repo, check=True, capture_output=True, text=True
    ).stdout
    assert status == ""
