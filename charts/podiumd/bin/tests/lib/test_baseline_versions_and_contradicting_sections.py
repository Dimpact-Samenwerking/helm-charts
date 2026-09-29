"""compare_component_to_baseline and the checks that sections and manifest items match their row (openbao 4.9.3)."""

from pathlib import Path

import pytest

from lib.chart.chart_yaml import parse_chart_dependencies
from lib.component_docs.changes_section import BaselineState
from lib.component_docs.changes_section import ComponentState
from lib.component_docs.changes_section import DocContext
from lib.component_docs.changes_section import OrderingContext
from lib.component_docs.images_manifest_entries import expected_changes_items
from lib.component_docs.images_manifest_entries import fix_stale_changes_items
from lib.component_docs.images_manifest_entries import stale_changes_items
from lib.image.docs import changes_sections_contradicting_rows
from lib.image.docs import rebuild_changes_sections_contradicting_rows
from lib.upgradedoc.resolve_component_row import ResolutionContext
from lib.upgradedoc.resolve_component_row import compare_component_to_baseline
from lib.yaml_types import parse_yaml_mapping

TARGET_DEPS = parse_chart_dependencies(
    "dependencies:\n  - {name: openbao, version: 0.29.6, repository: '@openbao'}\n", "Chart.yaml"
)
BASELINE_DEPS = parse_chart_dependencies(
    "dependencies:\n  - {name: openbao, version: 0.28.4, repository: '@openbao'}\n", "Chart.yaml"
)
TARGET_VALUES = parse_yaml_mapping(
    "openbao:\n"
    "  configuration:\n    job:\n      image:\n        repository: quay.io/openbao/openbao\n"
    "        tag: &t 2.6.3@sha256:bbbb\n"
    "  server:\n    image:\n      repository: openbao/openbao\n      tag: *t\n",
    "values.yaml",
)
# 4.9.2: server.image.tag blank (chart default), only the job image pinned.
BASELINE_VALUES = parse_yaml_mapping(
    "openbao:\n"
    "  configuration:\n    job:\n      image:\n        repository: quay.io/openbao/openbao\n"
    "        tag: 2.5.5@sha256:aaaa\n"
    "  server:\n    image:\n      repository: openbao/openbao\n      tag: ''\n",
    "values.yaml",
)


@pytest.fixture
def chart_dir(tmp_path: Path) -> Path:
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        'component_resolution:\n  image_paths:\n    openbao: ["server.image", "configuration.job.image"]\n',
        encoding="utf-8",
    )
    return tmp_path


def test_blank_baseline_tag_with_a_changed_chart_resolves_like_the_row(chart_dir: Path):
    """The old section-side lookup read only server.image.tag and returned (None, None)."""
    resolution = ResolutionContext(
        chart_dir,
        ComponentState(TARGET_DEPS, TARGET_VALUES),
        BaselineState(BASELINE_DEPS, BASELINE_VALUES),
        "4.9.2",
    )
    assert compare_component_to_baseline(resolution, "openbao") == ("2.5.5", "0.28.4", False)


DOC = """\
# Upgrade guide: PodiumD 4.9.2 → 4.9.3

## Component versions (4.9.3 vs 4.9.2)

| Component | App version | Helm chart | Notes |
| --- | --- | --- | --- |
| openbao | 2.5.5 → 2.6.3 | 0.28.4 → 0.29.6 | - |

## Changes

### openbao 2.5.5 → 2.6.3 (chart 0.29.6, new)

PodiumD 4.9.3 introduces **openbao** at app version 2.6.3.

- Image / digest: see [`images-4.9.3.yaml`](../images/images-4.9.3.yaml).
"""


def _contexts(chart_dir: Path) -> tuple[DocContext, OrderingContext]:
    return DocContext(chart_dir, "4.9.3"), OrderingContext(TARGET_DEPS, TARGET_VALUES, {})


def test_contradicting_section_is_reported_and_rebuilt_from_its_row(chart_dir: Path):
    doc_context, ordering = _contexts(chart_dir)
    found_list = changes_sections_contradicting_rows(DOC, doc_context, ordering)
    assert len(found_list) == 1
    found = found_list[0]
    assert found.expected_heading == "openbao 2.5.5 → 2.6.3 (chart 0.28.4 → 0.29.6)"
    assert found.generated_only

    text, rebuilt = rebuild_changes_sections_contradicting_rows(DOC, doc_context, ordering)

    assert [s.heading for s in rebuilt] == [found.heading]
    assert "### openbao 2.5.5 → 2.6.3 (chart 0.28.4 → 0.29.6)\n" in text
    assert "PodiumD 4.9.3 upgrades **openbao** from app version 2.5.5\nto 2.6.3.\n" in text
    assert "- Helm chart `openbao` `0.28.4` → `0.29.6` in\n" in text
    assert not changes_sections_contradicting_rows(text, doc_context, ordering)


def test_section_with_hand_written_text_is_reported_but_not_rebuilt(chart_dir: Path):
    doc = DOC.replace("- Image / digest", "Restart the vault pods after the upgrade.\n\n- Image / digest")
    doc_context, ordering = _contexts(chart_dir)

    found_list = changes_sections_contradicting_rows(doc, doc_context, ordering)
    assert len(found_list) == 1
    found = found_list[0]
    assert not found.generated_only
    assert rebuild_changes_sections_contradicting_rows(doc, doc_context, ordering) == (doc, [])


MANIFEST: str = """\
# Baseline: podiumd 4.9.2.
#
# Changes:
#   1. zac 5.4.4 -> 5.4.5 (chart 1.0.297, unchanged).
#   2. openbao 2.5.5 (unchanged).
#
"""


def _expected_items(chart_dir: Path):
    resolution = ResolutionContext(
        chart_dir,
        ComponentState(TARGET_DEPS, TARGET_VALUES),
        BaselineState(BASELINE_DEPS, BASELINE_VALUES),
        "4.9.2",
    )
    return expected_changes_items(["openbao"], {}, resolution)


def test_stale_changes_item_is_reported_and_fixed_from_its_row(chart_dir: Path):
    """The item kept "(unchanged)" after a rerun; the row says 2.5.5 → 2.6.3, chart 0.28.4 → 0.29.6.

    The chart changed, so the rewritten item gets the chart clause although the old one had none."""
    expected = _expected_items(chart_dir)
    lines = MANIFEST.splitlines(keepends=True)

    assert stale_changes_items(lines, expected) == [
        (4, "openbao 2.5.5 (unchanged).", "openbao 2.5.5 -> 2.6.3 (chart 0.28.4 -> 0.29.6).")
    ]
    assert fix_stale_changes_items(lines, expected) == [
        ("openbao 2.5.5 (unchanged).", "openbao 2.5.5 -> 2.6.3 (chart 0.28.4 -> 0.29.6).")
    ]
    assert lines[4] == "#   2. openbao 2.5.5 -> 2.6.3 (chart 0.28.4 -> 0.29.6).\n"
    assert not stale_changes_items(lines, expected)


def test_changes_item_chart_clause_is_checked_only_when_present(chart_dir: Path):
    expected = _expected_items(chart_dir)
    wrong_chart = MANIFEST.replace("openbao 2.5.5 (unchanged).", "openbao 2.5.5 -> 2.6.3 (chart 0.29.6, new).")
    right_chart = MANIFEST.replace("openbao 2.5.5 (unchanged).", "openbao 2.5.5 -> 2.6.3 (chart 0.28.4 -> 0.29.6).")

    assert stale_changes_items(wrong_chart.splitlines(keepends=True), expected) == [
        (4, "openbao 2.5.5 -> 2.6.3 (chart 0.29.6, new).", "openbao 2.5.5 -> 2.6.3 (chart 0.28.4 -> 0.29.6).")
    ]
    assert not stale_changes_items(right_chart.splitlines(keepends=True), expected)
