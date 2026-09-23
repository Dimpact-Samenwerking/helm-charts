"""Paths of the podiumd chart that contains these scripts
(charts/podiumd/bin/lib/chart/ -> charts/podiumd/)."""

from pathlib import Path

CHART_DIR = Path(__file__).resolve().parents[3]
CHART_YAML = CHART_DIR / "Chart.yaml"
VALUES_YAML = CHART_DIR / "values.yaml"
DOC_DIR = CHART_DIR / "docs" / "_UPGRADE_PATHS"
IMAGES_DIR = CHART_DIR / "docs" / "images"
