"""lib.render_scope.rendered_chart_paths/chart_tree_paths: "# Source:"
chart-tree-path parsing."""

from pathlib import Path
from types import ModuleType

import pytest

# --- rendered_chart_paths ---


def test_rendered_chart_paths_top_level_and_nested(librenderscope: ModuleType):
    """A nested rendered path also marks its ancestor
    ("podiumd/charts/openinwoner") live."""
    rendered = (
        "---\n# Source: podiumd/templates/a.yaml\nkind: X\n"
        "---\n# Source: podiumd/charts/zac/templates/b.yaml\nkind: Y\n"
        "---\n# Source: podiumd/charts/openinwoner/charts/eck-elasticsearch/templates/c.yaml\nkind: Z\n"
    )
    assert librenderscope.rendered_chart_paths(rendered) == {
        "podiumd",
        "podiumd/charts/zac",
        "podiumd/charts/openinwoner",
        "podiumd/charts/openinwoner/charts/eck-elasticsearch",
    }


def test_rendered_chart_paths_umbrella_chart_with_no_own_templates_counts_as_rendered(librenderscope: ModuleType):
    """An umbrella chart without templates (kiss-eck) only renders via nested
    charts; ancestor inference keeps it from looking disabled."""
    rendered = (
        "---\n# Source: podiumd/charts/kiss-eck/charts/eck-elasticsearch/templates/elasticsearch.yaml\nkind: X\n"
        "---\n# Source: podiumd/charts/kiss-eck/charts/eck-kibana/templates/kibana.yaml\nkind: Y\n"
    )
    paths = librenderscope.rendered_chart_paths(rendered)
    assert "podiumd/charts/kiss-eck" in paths


def test_rendered_chart_paths_ancestor_inference_never_leaks_to_siblings(librenderscope: ModuleType):
    """A rendered sibling doesn't make a nested chart live: only ancestors
    are inferred."""
    rendered = "---\n# Source: podiumd/charts/openinwoner/charts/eck-elasticsearch/templates/c.yaml\nkind: Z\n"
    paths = librenderscope.rendered_chart_paths(rendered)
    assert "podiumd/charts/openinwoner/charts/eck-operator" not in paths


def test_rendered_chart_paths_distinguishes_top_level_from_same_named_nested(librenderscope: ModuleType):
    """A top-level and a nested same-named eck-operator stay separate paths."""
    rendered = (
        "---\n# Source: podiumd/charts/eck-operator/templates/statefulset.yaml\nkind: StatefulSet\n"
        "---\n# Source: podiumd/charts/openinwoner/templates/deployment.yaml\nkind: Deployment\n"
    )
    paths = librenderscope.rendered_chart_paths(rendered)
    assert "podiumd/charts/eck-operator" in paths
    assert "podiumd/charts/openinwoner/charts/eck-operator" not in paths


def test_rendered_chart_paths_empty_when_no_source_markers(librenderscope: ModuleType):
    assert librenderscope.rendered_chart_paths("no source markers here") == set()


def test_rendered_chart_paths_deduplicates(librenderscope: ModuleType):
    rendered = (
        "---\n# Source: podiumd/charts/zac/templates/a.yaml\nkind: X\n"
        "---\n# Source: podiumd/charts/zac/templates/b.yaml\nkind: Y\n"
    )
    assert librenderscope.rendered_chart_paths(rendered) == {"podiumd/charts/zac"}


def test_rendered_chart_paths_ignores_chart_paths_outside_source_lines(librenderscope: ModuleType):
    """A chart-tree-shaped string inside a rendered resource (not on a
    "# Source:" line) must not count as a live chart path."""
    rendered = (
        "---\n# Source: podiumd/charts/zac/templates/cm.yaml\n"
        "kind: ConfigMap\ndata:\n  note: podiumd/charts/openbao/templates/x.yaml\n"
    )
    assert librenderscope.rendered_chart_paths(rendered) == {"podiumd/charts/zac"}


# --- friendly_vendor_charts ---


def test_friendly_vendor_charts_matches_mixed_case_keyword(
    librenderscope: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """A vendor keyword written in mixed case still matches the lowercased
    repository."""
    monkeypatch.setattr(librenderscope, "helm_repos_urls_by_alias", lambda chart_dir: {})
    monkeypatch.setattr(librenderscope, "vendor_classification_keywords", lambda chart_dir: {"InfoNL": "Info(NL)"})
    monkeypatch.setattr(librenderscope, "vendor_classification_chart_overrides", lambda chart_dir: {})
    monkeypatch.setattr(
        librenderscope,
        "load_chart_dependencies",
        lambda path: [
            {"name": "zaakafhandelcomponent", "alias": "zac", "repository": "https://infonl.github.io/charts"}
        ],
    )
    assert librenderscope.friendly_vendor_charts(tmp_path) == {"zac": "Info(NL)"}


# --- chart_tree_paths (shared primitive) ---


def test_chart_tree_paths_finds_every_match_in_order(librenderscope: ModuleType):
    text = "Error: zac/templates/a.yaml:1\nError: openzaak/templates/c.yaml:1\n"
    assert librenderscope.chart_tree_paths(text) == ["zac", "openzaak"]


def test_chart_tree_paths_keeps_full_nested_path(librenderscope: ModuleType):
    text = "podiumd/charts/eck-operator/charts/eck-operator-crds/templates/all-crds.yaml"
    assert librenderscope.chart_tree_paths(text) == ["podiumd/charts/eck-operator/charts/eck-operator-crds"]
