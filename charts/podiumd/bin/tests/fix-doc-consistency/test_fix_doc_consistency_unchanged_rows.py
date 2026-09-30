"""remove_unchanged_component_rows: a "Component versions" row whose app and
chart both equal the baseline's is removed with the generated parts of its "### ..." section."""

from lib.chart.chart_yaml import ChartDependency
from lib.component_docs.changes_section import BaselineState
from lib.component_docs.changes_section import ComponentState
from lib.fix_doc_consistency.component_version_table import remove_unchanged_component_rows
from lib.upgradedoc.resolve_component_row import ResolutionContext
from lib.yaml_types import YamlMapping

DEPS: list[ChartDependency] = [
    {"name": "redis-operator", "version": "0.26.1"},
    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
]


def values(redis_tag: str, zac_tag: str) -> YamlMapping:
    return {
        "redis-operator": {
            "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": f"{redis_tag}@sha256:aaaa"}}
        },
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": f"{zac_tag}@sha256:bbbb"}},
    }


DOC = (
    "## Component versions (4.9.0 vs 4.8.5)\n\n"
    "| Component | App version | Helm chart | Notes |\n"
    "| --- | --- | --- | --- |\n"
    "| redis-operator - redis | v8.6.6 → v8.10.1 | - | - |\n"
    "| ZAC (Zaakafhandelcomponent) | 5.4.4 (unchanged) | 1.0.297 (unchanged) | - |\n\n"
    "## Changes\n\n"
    "### redis-operator - redis v8.6.6 → v8.10.1 (chart 0.26.1, unchanged)\n\n"
    "PodiumD 4.9.0 upgrades the **redis-operator - redis** image to v8.10.1,\n"
    "pinned at:\n\n"
    "- `redis-operator.redis-ha.image.tag` `v8.6.6` → `v8.10.1`\n\n"
    "### ZAC (Zaakafhandelcomponent) 5.4.4 (unchanged) (chart 1.0.297, unchanged)\n\n"
    "**ZAC (Zaakafhandelcomponent)**'s own app version (5.4.4) is unchanged this hop.\n\n"
    "## Corrections\n\n"
    "None.\n"
)


def test_remove_unchanged_component_rows_removes_row_and_section() -> None:
    resolution = ResolutionContext(
        None,
        ComponentState(DEPS, values("v8.10.1", "5.4.4")),
        BaselineState(DEPS, values("v8.6.6", "5.4.4")),
    )

    new_text, removed = remove_unchanged_component_rows(DOC, resolution)

    assert removed == ["ZAC (Zaakafhandelcomponent)"]
    assert "ZAC" not in new_text
    assert "| redis-operator - redis | v8.6.6 → v8.10.1 | - | - |" in new_text
    assert "### redis-operator - redis v8.6.6 → v8.10.1" in new_text
    assert "- `redis-operator.redis-ha.image.tag` `v8.6.6` → `v8.10.1`\n\n## Corrections\n" in new_text


def test_remove_unchanged_component_rows_keeps_hand_written_text_of_the_section() -> None:
    """Only the generated parts go; the user's note and the heading above it stay."""
    doc = DOC.replace("is unchanged this hop.\n\n", "is unchanged this hop.\n\nRestart ZAC after the upgrade.\n\n")
    resolution = ResolutionContext(
        None,
        ComponentState(DEPS, values("v8.10.1", "5.4.4")),
        BaselineState(DEPS, values("v8.6.6", "5.4.4")),
    )

    new_text, removed = remove_unchanged_component_rows(doc, resolution)

    assert removed == ["ZAC (Zaakafhandelcomponent)"]
    assert "| ZAC (Zaakafhandelcomponent) |" not in new_text
    assert (
        "### ZAC (Zaakafhandelcomponent) 5.4.4 (unchanged) (chart 1.0.297, unchanged)\n\n"
        "Restart ZAC after the upgrade.\n\n## Corrections\n"
    ) in new_text


def test_remove_unchanged_component_rows_reverted_sidecar() -> None:
    """redis reverted to baseline v8.6.6 while the doc still has its row and section."""
    resolution = ResolutionContext(
        None,
        ComponentState(DEPS, values("v8.6.6", "5.4.5")),
        BaselineState(DEPS, values("v8.6.6", "5.4.4")),
    )

    new_text, removed = remove_unchanged_component_rows(DOC, resolution)

    assert removed == ["redis-operator - redis"]
    assert "redis" not in new_text


def test_remove_unchanged_component_rows_keeps_rows_without_baseline() -> None:
    resolution = ResolutionContext(
        None,
        ComponentState(DEPS, values("v8.10.1", "5.4.4")),
        BaselineState(None, None),
    )

    new_text, removed = remove_unchanged_component_rows(DOC, resolution)

    assert removed == []
    assert new_text == DOC
