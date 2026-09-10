"""lib.render_scope.rendered_chart_paths/chart_tree_paths — the shared
"# Source: <path>" chart-tree-path parsing report_errors_by_subchart/
chart_name_from_source (tested in test_helm_helpers.py/test_yamllint.py)
now build on too, confirming the refactor didn't change either of
THEIR existing behavior."""


# --- rendered_chart_paths ---

def test_rendered_chart_paths_top_level_and_nested(librenderscope):
    """The nested eck-elasticsearch path also implies its own ANCESTOR
    ("podiumd/charts/openinwoner") is live -- see the dedicated umbrella-
    chart test below for why that inference exists at all."""
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


def test_rendered_chart_paths_umbrella_chart_with_no_own_templates_counts_as_rendered(librenderscope):
    """The real bug this ancestor inference fixes, confirmed live: eck-
    stack (aliased "kiss-eck") is a pure umbrella chart with NO
    templates/ of its own at all — only its own nested eck-elasticsearch/
    eck-kibana render anything. Without ancestor inference, "podiumd/
    charts/kiss-eck" would never appear in this set at all, making a
    perfectly enabled dependency indistinguishable from a disabled one
    to every consumer of this set."""
    rendered = (
        "---\n# Source: podiumd/charts/kiss-eck/charts/eck-elasticsearch/templates/elasticsearch.yaml\nkind: X\n"
        "---\n# Source: podiumd/charts/kiss-eck/charts/eck-kibana/templates/kibana.yaml\nkind: Y\n"
    )
    paths = librenderscope.rendered_chart_paths(rendered)
    assert "podiumd/charts/kiss-eck" in paths


def test_rendered_chart_paths_ancestor_inference_never_leaks_to_siblings(librenderscope):
    """openinwoner's own disabled nested eck-operator must NOT be
    inferred as live just because its own SIBLING (eck-elasticsearch,
    nested under the same parent) does render — ancestor inference only
    ever adds actual ancestors of a rendered path, never siblings."""
    rendered = "---\n# Source: podiumd/charts/openinwoner/charts/eck-elasticsearch/templates/c.yaml\nkind: Z\n"
    paths = librenderscope.rendered_chart_paths(rendered)
    assert "podiumd/charts/openinwoner/charts/eck-operator" not in paths


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
