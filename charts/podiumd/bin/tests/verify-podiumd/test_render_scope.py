"""lib.render_scope.rendered_chart_paths/chart_tree_paths — the shared
"# Source: <path>" chart-tree-path parsing report_errors_by_subchart/
chart_name_from_source (tested in test_helm_helpers.py/test_yamllint.py)
now build on too, confirming the refactor didn't change either of
THEIR existing behavior."""


# --- rendered_chart_paths ---

def test_rendered_chart_paths_top_level_and_nested(librenderscope):
    rendered = (
        "---\n# Source: podiumd/templates/a.yaml\nkind: X\n"
        "---\n# Source: podiumd/charts/zac/templates/b.yaml\nkind: Y\n"
        "---\n# Source: podiumd/charts/openinwoner/charts/eck-elasticsearch/templates/c.yaml\nkind: Z\n"
    )
    assert librenderscope.rendered_chart_paths(rendered) == {
        "podiumd",
        "podiumd/charts/zac",
        "podiumd/charts/openinwoner/charts/eck-elasticsearch",
    }


def test_rendered_chart_paths_distinguishes_top_level_from_same_named_nested(librenderscope):
    """The real case this exists for: a top-level "eck-operator"
    dependency vs. openinwoner's own separate, same-named NESTED
    eck-operator — the two must never collapse into one path."""
    rendered = (
        "---\n# Source: podiumd/charts/eck-operator/templates/statefulset.yaml\nkind: StatefulSet\n"
        "---\n# Source: podiumd/charts/openinwoner/templates/deployment.yaml\nkind: Deployment\n"
    )
    paths = librenderscope.rendered_chart_paths(rendered)
    assert "podiumd/charts/eck-operator" in paths
    assert "podiumd/charts/openinwoner/charts/eck-operator" not in paths


def test_rendered_chart_paths_empty_when_no_source_markers(librenderscope):
    assert librenderscope.rendered_chart_paths("no source markers here") == set()


def test_rendered_chart_paths_deduplicates(librenderscope):
    rendered = (
        "---\n# Source: podiumd/charts/zac/templates/a.yaml\nkind: X\n"
        "---\n# Source: podiumd/charts/zac/templates/b.yaml\nkind: Y\n"
    )
    assert librenderscope.rendered_chart_paths(rendered) == {"podiumd/charts/zac"}


# --- chart_tree_paths (shared primitive) ---

def test_chart_tree_paths_finds_every_match_in_order(librenderscope):
    text = "Error: zac/templates/a.yaml:1\nError: openzaak/templates/c.yaml:1\n"
    assert librenderscope.chart_tree_paths(text) == ["zac", "openzaak"]


def test_chart_tree_paths_keeps_full_nested_path(librenderscope):
    text = "podiumd/charts/eck-operator/charts/eck-operator-crds/templates/all-crds.yaml"
    assert librenderscope.chart_tree_paths(text) == ["podiumd/charts/eck-operator/charts/eck-operator-crds"]
