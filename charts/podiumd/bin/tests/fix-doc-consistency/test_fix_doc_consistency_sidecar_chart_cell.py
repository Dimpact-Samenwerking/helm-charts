"""fix_component_version_table sets a sidecar row's chart cell to "-",
the value check_docs_consistency expects."""

from lib.component_docs.changes_section import BaselineState
from lib.component_docs.changes_section import ComponentState
from lib.fix_doc_consistency.component_version_table import fix_component_version_table
from lib.upgradedoc.resolve_component_row import ResolutionContext


def redis_values(tag: str) -> dict[str, object]:
    return {
        "redis-operator": {"redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": f"{tag}@sha256:aaaa"}}}
    }


def test_fix_component_version_table_sets_a_sidecar_rows_chart_cell_to_dash() -> None:
    """A chart version in a sidecar row (written by an older
    update-image-version) becomes "-"."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - redis | 8.6.2 → 8.6.6 | 0.26.1 (unchanged) | - |\n"
    )
    resolution = ResolutionContext(
        None,
        ComponentState([{"name": "redis-operator", "version": "0.26.1"}], redis_values("8.6.6")),
        BaselineState([{"name": "redis-operator", "version": "0.26.1"}], redis_values("8.6.2")),
    )

    new_text, changed, _unmatched, _unresolved = fix_component_version_table(text, resolution)

    assert len(changed) == 1
    assert "| redis-operator - redis | 8.6.2 → 8.6.6 | - | - |" in new_text
