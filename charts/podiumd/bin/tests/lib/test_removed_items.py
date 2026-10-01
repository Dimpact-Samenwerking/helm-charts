"""Removed components and images: detection, their -upgrade.md row and section, and the matching check."""

from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.component_docs.removed_item_docs import sync_removed_items
from lib.upgradedoc.chart_image_index import ChartImageIndex
from lib.upgradedoc.removed_items import RemovedItem
from lib.upgradedoc.removed_items import removed_items
from lib.upgradedoc.sorting_and_ordering import OrderingContext
from lib.yaml_types import YamlMapping

ZAC: ChartDependency = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
KISS: ChartDependency = {"name": "kiss", "version": "3.1.1"}
BASELINE_VALUES: YamlMapping = {
    "zac": {
        "image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.4@sha256:aaaa"},
        "opa": {"image": {"repository": "openpolicyagent/opa", "tag": "1.4.2@sha256:bbbb"}},
    },
    "kiss": {"image": {"repository": "ghcr.io/kiss/kiss-frontend", "tag": "3.1.1@sha256:cccc"}},
}
TARGET_VALUES: YamlMapping = {
    "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.5@sha256:dddd"}}
}
DOC = (
    "# Upgrade guide: PodiumD 4.9.2 → 4.9.3\n\n"
    "## Component versions (4.9.3 vs 4.9.2)\n\n"
    "| Component | App version | Helm chart | Notes |\n"
    "| --- | --- | --- | --- |\n"
    "| zac | 5.4.4 → 5.4.5 | 1.0.297 (unchanged) | - |\n\n"
    "## Changes\n\n"
    "### zac 5.4.4 → 5.4.5 (chart 1.0.297, unchanged)\n\n"
    "Details.\n\n"
    "- Image / digest: see [`images-4.9.3.yaml`](../images/images-4.9.3.yaml).\n"
)


def _items_and_ordering(tmp_path: Path) -> tuple[list[RemovedItem], OrderingContext]:
    target = ChartImageIndex(tmp_path, [ZAC], TARGET_VALUES)
    items = removed_items(target, ChartImageIndex(tmp_path, [ZAC, KISS], BASELINE_VALUES))
    removed_keys = {item.name: item.order_key for item in items}
    return items, OrderingContext([ZAC], TARGET_VALUES, target.canonical_names, removed_keys)


def test_removed_items_lists_a_removed_component_and_a_removed_sidecar(tmp_path: Path):
    items, _ordering = _items_and_ordering(tmp_path)

    assert [(item.name, item.old_app, item.old_chart) for item in items] == [
        ("zac - opa", "1.4.2", None),
        ("kiss", "3.1.1", "3.1.1"),
    ]


def test_sync_removed_items_writes_rows_and_sections_in_baseline_order(tmp_path: Path):
    items, ordering = _items_and_ordering(tmp_path)

    text, synced = sync_removed_items(DOC, items, "4.9.3", ordering)

    assert synced == ["zac - opa", "kiss"]
    assert (
        "| zac | 5.4.4 → 5.4.5 | 1.0.297 (unchanged) | - |\n"
        "| zac - opa | 1.4.2 (removed) | - | - |\n"
        "| kiss | 3.1.1 (removed) | 3.1.1 (removed) | - |\n"
    ) in text
    assert (
        "### zac - opa 1.4.2 (removed)\n\nPodiumD 4.9.3 removes **zac - opa** (was 1.4.2).\n\n"
        "### kiss 3.1.1 (removed)\n\nPodiumD 4.9.3 removes **kiss** (was 3.1.1).\n"
    ) in text
    assert sync_removed_items(text, items, "4.9.3", ordering) == (text, [])


def test_sync_removed_items_keeps_user_text_in_a_removed_section(tmp_path: Path):
    items, ordering = _items_and_ordering(tmp_path)
    text, _synced = sync_removed_items(DOC, items, "4.9.3", ordering)
    note = "Delete the kiss namespace by hand.\n"
    text = text.replace("(was 3.1.1).\n", "(was 3.1.1).\n\n" + note)

    assert sync_removed_items(text, items, "4.9.3", ordering) == (text, [])
    assert note in text


def test_an_image_that_moved_to_another_row_name_is_not_removed(tmp_path: Path):
    """The opa image now pinned through a global anchor: its repository is still there."""
    target_values: YamlMapping = {
        "global": {"images": {"opa": {"repository": "openpolicyagent/opa", "tag": "1.4.2@sha256:bbbb"}}},
        **TARGET_VALUES,
    }
    target = ChartImageIndex(tmp_path, [ZAC], target_values)

    assert removed_items(target, ChartImageIndex(tmp_path, [ZAC], BASELINE_VALUES)) == []
