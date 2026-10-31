"""Sphinx configuration for the PodiumD chart documentation (Read the Docs)."""

import re
from pathlib import Path

_CHART_YAML = Path(__file__).resolve().parent.parent / "Chart.yaml"
# A regex instead of a YAML parser keeps PyYAML out of the docs requirements.
_VERSION = re.search(
    r"^version:\s*\"?([^\"\s]+)", _CHART_YAML.read_text(encoding="utf-8"), re.MULTILINE
)

project = "PodiumD"
author = "Dimpact"
copyright = "Dimpact"  # noqa: A001 - Sphinx reads this exact name
release = _VERSION.group(1) if _VERSION else ""
version = release

extensions = [
    "myst_parser",
    "sphinxcontrib.mermaid",
]

root_doc = "index"
# _README.MD is the only upper-case suffix in the tree.
source_suffix = {".md": "markdown", ".MD": "markdown"}
exclude_patterns = ["_build", "**/.DS_Store", "**/.gitkeep"]

myst_enable_extensions = ["colon_fence", "deflist", "tasklist"]
# Docs link to section anchors (`file.md#some-heading`) GitHub-style.
myst_heading_anchors = 4
myst_fence_as_directive = ["mermaid"]

language = "en"
html_theme = "furo"
html_title = f"PodiumD {release}"
html_context = {
    "source_type": "github",
    "source_user": "Dimpact-Samenwerking",
    "source_repo": "helm-charts",
    "source_version": "main",
    "source_directory": "charts/podiumd/docs/",
}
html_theme_options = {
    "source_repository": "https://github.com/Dimpact-Samenwerking/helm-charts/",
    "source_branch": "main",
    "source_directory": "charts/podiumd/docs/",
}
