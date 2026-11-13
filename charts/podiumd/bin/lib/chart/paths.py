"""Paths of the podiumd chart that contains these scripts."""

from pathlib import Path

CHART_DIR = Path(__file__).resolve().parents[3]
CHART_YAML = CHART_DIR / "Chart.yaml"
VALUES_YAML = CHART_DIR / "values.yaml"
DOC_DIR = CHART_DIR / "docs" / "_UPGRADE_PATHS"
IMAGES_DIR = CHART_DIR / "docs" / "images"

# Installed dependencies of a tool (`npm ci` in tools/): not part of the chart, never checked.
SKIPPED_DIR_NAMES = frozenset(("node_modules",))


def files_under(root: Path, pattern: str) -> list[Path]:
    """Files under `root` whose name matches `pattern`, in path order, outside SKIPPED_DIR_NAMES."""
    return sorted(
        path
        for path in root.rglob(pattern)
        if path.is_file() and SKIPPED_DIR_NAMES.isdisjoint(path.relative_to(root).parts)
    )
