"""fix-doc-consistency on a copy of the docs: what it would change, and the docs as it would leave them."""

import contextlib
import difflib
import io
import shutil
import tempfile

from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

from lib.fix_doc_consistency.run import FixDocPaths
from lib.fix_doc_consistency.run import fix_docs

# The only docs/ subdirectories fix_docs writes.
DOC_SUBDIRS = ("_UPGRADE_PATHS", "images")
# Diff lines shown per changed file; the rest is counted.
MAX_DIFF_LINES = 20


@dataclass(frozen=True)
class DocChange:
    """One file fix-doc-consistency would create, change or remove (a rename removes the old name)."""

    name: str
    status: str
    diff: list[str]
    changed_lines: int


@dataclass(frozen=True)
class DryRun:
    """docs_dir holds the docs as fix-doc-consistency leaves them; error is set when it refused to run."""

    docs_dir: Path
    changes: list[DocChange]
    error: str | None


def _rename(old: Path, new: Path) -> None:
    old.rename(new)


def _files(docs_dir: Path) -> dict[str, str]:
    return {
        str(path.relative_to(docs_dir)): path.read_text(encoding="utf-8")
        for subdir in DOC_SUBDIRS
        for path in sorted((docs_dir / subdir).glob("*"))
        if path.is_file()
    }


def _change(name: str, old: str | None, new: str | None) -> DocChange:
    """Skips unified_diff's two file-header lines by position: a content line can also start with "--- "."""
    diff = list(difflib.unified_diff((old or "").splitlines(), (new or "").splitlines(), lineterm="", n=0))[2:]
    status = "created" if old is None else "removed" if new is None else "changed"
    changed_lines = sum(1 for line in diff if line.startswith(("+", "-")))
    return DocChange(name, status, diff, changed_lines)


@contextlib.contextmanager
def fix_docs_dry_run(chart_dir: Path, target: str, new_baseline: str) -> Generator[DryRun]:
    """Run fix_docs on a temporary copy of chart_dir's docs; the copy lives until the context ends.

    Its output is captured, and docs/images/images-baseline.yaml is not
    regenerated (that needs a helm render; it is a generated file anyway).
    """
    with tempfile.TemporaryDirectory(prefix="fix-doc-consistency-dry-run-") as tmp:
        docs_dir = Path(tmp) / "docs"
        for subdir in DOC_SUBDIRS:
            if (chart_dir / "docs" / subdir).is_dir():
                shutil.copytree(chart_dir / "docs" / subdir, docs_dir / subdir)
            else:
                (docs_dir / subdir).mkdir(parents=True)
        output = io.StringIO()
        error = None
        with contextlib.redirect_stdout(output):
            try:
                fix_docs(
                    FixDocPaths(chart_dir, docs_dir / "_UPGRADE_PATHS", docs_dir / "images", _rename),
                    target,
                    new_baseline,
                )
            except SystemExit:
                error = output.getvalue().strip()
        before, after = _files(chart_dir / "docs"), _files(docs_dir)
        changes = [
            _change(name, before.get(name), after.get(name))
            for name in sorted(set(before) | set(after))
            if before.get(name) != after.get(name)
        ]
        yield DryRun(docs_dir, changes, error)
