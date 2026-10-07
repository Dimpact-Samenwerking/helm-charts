"""canonical_version_cell and the version-table/heading fixers: pure logic, no git repo."""

from pathlib import Path
from types import ModuleType
from typing import Any

from lib.chart.chart_state import BaselineState
from lib.chart.chart_state import ComponentState
from lib.chart.chart_yaml import ChartDependency
from lib.fix_doc_consistency.component_version_table import fix_changes_heading_app_versions
from lib.fix_doc_consistency.component_version_table import fix_component_version_table
from lib.fix_doc_consistency.component_version_table import fix_values_delta_heading_app_versions
from lib.upgradedoc.resolve_component_row import ResolutionContext
from lib.upgradedoc.version_cells_and_key_changes import canonical_version_cell
from lib.yaml_types import YamlMapping

# --- canonical_version_cell ---


def test_canonical_version_cell_arrow_form(cdb: ModuleType):
    assert canonical_version_cell("5.0.2", "5.1.0") == "5.0.2 → 5.1.0"


def test_canonical_version_cell_unchanged_form(cdb: ModuleType):
    assert canonical_version_cell("1.0.297", "1.0.297") == "1.0.297 (unchanged)"


def test_canonical_version_cell_v_prefix_counts_as_unchanged(cdb: ModuleType):
    assert canonical_version_cell("v0.9.352", "0.9.352") == "0.9.352 (unchanged)"


# --- fix_component_version_table ---


def target_deps_and_values() -> tuple[list[ChartDependency], YamlMapping]:
    deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    values: YamlMapping = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    return deps, values


def test_fix_component_version_table_corrects_stale_source(cdb: ModuleType):
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.1 → 5.1.0 | 1.0.251 → 1.0.257 | ACR mirror only |\n"
    )
    target_deps, target_values = target_deps_and_values()
    baseline_deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_values: YamlMapping = {"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}

    new_text, changed, unmatched, unresolved = fix_component_version_table(
        text,
        ResolutionContext(
            None, ComponentState(target_deps, target_values), BaselineState(baseline_deps, baseline_values)
        ),
    )
    assert unmatched == [] and unresolved == []
    assert len(changed) == 1
    assert "5.0.2 → 5.1.0" in new_text
    assert "1.0.297 → 1.0.257" in new_text
    assert "5.0.1" not in new_text
    assert "1.0.251" not in new_text
    assert "ACR mirror only" in new_text  # notes column untouched


def test_fix_component_version_table_leaves_correct_row_untouched(cdb: ModuleType):
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.1.0 | 1.0.297 → 1.0.257 | ACR mirror only |\n"
    )
    target_deps, target_values = target_deps_and_values()
    baseline_deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_values: YamlMapping = {"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}

    new_text, changed, _unmatched, _unresolved = fix_component_version_table(
        text,
        ResolutionContext(
            None, ComponentState(target_deps, target_values), BaselineState(baseline_deps, baseline_values)
        ),
    )
    assert changed == []
    assert new_text == text


def test_fix_component_version_table_unmatched_component_reported(cdb: ModuleType):
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| Totally Unknown Thing | 1.0.0 → 2.0.0 | 1.0.0 → 2.0.0 | - |\n"
    )
    target_deps, target_values = target_deps_and_values()
    new_text, changed, unmatched, _unresolved = fix_component_version_table(
        text,
        ResolutionContext(
            None,
            ComponentState(target_deps, target_values),
            BaselineState([{"name": "zac", "version": "1.0.297"}], {}),
        ),
    )
    assert changed == []
    assert unmatched == ["Totally Unknown Thing"]
    assert new_text == text


def test_fix_component_version_table_no_baseline_data_reported_unresolved(cdb: ModuleType):
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.1 → 5.1.0 | 1.0.251 → 1.0.257 | ACR mirror only |\n"
    )
    target_deps, target_values = target_deps_and_values()
    new_text, changed, _unmatched, unresolved = fix_component_version_table(
        text,
        ResolutionContext(None, ComponentState(target_deps, target_values), BaselineState(None, None)),
    )
    assert changed == []
    assert unresolved == ["ZAC (Zaakafhandelcomponent)"]
    assert new_text == text


def redis_sidecar_deps_and_values(target_chart="0.26.1", baseline_chart="0.25.0", target_tag="8.6.6"):
    target_deps: list[ChartDependency] = [{"name": "redis-operator", "version": target_chart}]
    baseline_deps: list[ChartDependency] = [{"name": "redis-operator", "version": baseline_chart}]
    target_values: dict[str, Any] = {
        "redis-operator": {
            "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": f"{target_tag}@sha256:aaaa"}}
        }
    }
    baseline_values: YamlMapping = {
        "redis-operator": {"redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": "8.6.2@sha256:aaaa"}}}
    }
    return target_deps, target_values, baseline_deps, baseline_values


def test_fix_component_version_table_leaves_a_correct_sidecar_row_untouched(cdb: ModuleType):
    """A canonical sidecar row is never "corrected" against the dependency match_dependency fuzzy-matches it to."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - redis | 8.6.2 → 8.6.6 | - | ACR mirror only |\n"
    )
    target_deps, target_values, baseline_deps, baseline_values = redis_sidecar_deps_and_values()

    new_text, changed, _unmatched, _unresolved = fix_component_version_table(
        text,
        ResolutionContext(
            None, ComponentState(target_deps, target_values), BaselineState(baseline_deps, baseline_values)
        ),
    )
    assert changed == []
    assert new_text == text


def test_fix_component_version_table_corrects_a_stale_sidecar_row_using_its_own_tag(cdb: ModuleType):
    """A stale sidecar App cell is corrected against its own tag; its Helm-chart cell stays "-"."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - redis | 8.6.2 → 9.9.9 | - | ACR mirror only |\n"
    )
    target_deps, target_values, baseline_deps, baseline_values = redis_sidecar_deps_and_values()

    new_text, changed, _unmatched, _unresolved = fix_component_version_table(
        text,
        ResolutionContext(
            None, ComponentState(target_deps, target_values), BaselineState(baseline_deps, baseline_values)
        ),
    )
    assert len(changed) == 1
    assert "8.6.2 → 8.6.6" in new_text
    assert "9.9.9" not in new_text
    assert "| redis-operator - redis | 8.6.2 → 8.6.6 | - | ACR mirror only |" in new_text


def test_fix_component_version_table_corrects_a_native_components_wrong_chart_cell(cdb: ModuleType):
    """A native component (no Chart.yaml dependency) gets its wrong Helm-chart cell corrected back to "-"."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| frankgateway | 104 (unchanged) | 1.1.0 (new) | - |\n"
    )
    target_deps: list[ChartDependency] = [{"name": "zac", "version": "1.0.297"}]
    target_values: YamlMapping = {"frankgateway": {"image": {"tag": "104@sha256:aaaa"}}}
    baseline_deps: list[ChartDependency] = [{"name": "zac", "version": "1.0.297"}]
    baseline_values: YamlMapping = {"frankgateway": {"image": {"tag": "104@sha256:aaaa"}}}

    new_text, changed, unmatched, unresolved = fix_component_version_table(
        text,
        ResolutionContext(
            None, ComponentState(target_deps, target_values), BaselineState(baseline_deps, baseline_values)
        ),
    )
    assert unmatched == [] and unresolved == []
    assert len(changed) == 1
    assert "| frankgateway | 104 (unchanged) | - | - |" in new_text
    assert "1.1.0" not in new_text


def test_fix_component_version_table_leaves_a_correct_native_component_row_untouched(cdb: ModuleType):
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| frankgateway | 104 (unchanged) | - | - |\n"
    )
    target_deps: list[ChartDependency] = [{"name": "zac", "version": "1.0.297"}]
    target_values: YamlMapping = {"frankgateway": {"image": {"tag": "104@sha256:aaaa"}}}
    baseline_deps: list[ChartDependency] = [{"name": "zac", "version": "1.0.297"}]
    baseline_values: YamlMapping = {"frankgateway": {"image": {"tag": "104@sha256:aaaa"}}}

    new_text, changed, _unmatched, _unresolved = fix_component_version_table(
        text,
        ResolutionContext(
            None, ComponentState(target_deps, target_values), BaselineState(baseline_deps, baseline_values)
        ),
    )
    assert changed == []
    assert new_text == text


def test_fix_component_version_table_unresolvable_canonical_row_reported_not_corrupted(cdb: ModuleType):
    """A sidecar-shaped row with no resolvable repository is reported, not matched to an unrelated dependency."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - ghost | 0.6.6 → 0.6.7 | - | ACR mirror only |\n"
    )
    target_deps, target_values, baseline_deps, baseline_values = redis_sidecar_deps_and_values()

    new_text, changed, _unmatched, unresolved = fix_component_version_table(
        text,
        ResolutionContext(
            None, ComponentState(target_deps, target_values), BaselineState(baseline_deps, baseline_values)
        ),
    )
    assert changed == []
    assert unresolved == ["redis-operator - ghost"]
    assert new_text == text


def test_fix_component_version_table_new_dependency_annotated_new_not_reported_unresolved(cdb: ModuleType):
    """A dependency absent from the baseline Chart.yaml gets "(new)" cells, not a manual-review report."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| openklant | 2.15.0 | 1.11.0 | - |\n"
    )
    target_deps: list[ChartDependency] = [{"name": "openklant", "version": "1.11.0"}]
    target_values: YamlMapping = {"openklant": {"image": {"tag": "2.15.0@sha256:aaaa"}}}

    new_text, changed, unmatched, unresolved = fix_component_version_table(
        text, ResolutionContext(None, ComponentState(target_deps, target_values), BaselineState([], {}))
    )
    assert unmatched == [] and unresolved == []
    assert len(changed) == 1
    assert "| openklant | 2.15.0 (new) | 1.11.0 (new) | - |" in new_text


def test_fix_component_version_table_new_dependency_already_annotated_is_untouched(cdb: ModuleType):
    """Idempotent: a row already reading "(new)" is left alone."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| openklant | 2.15.0 (new) | 1.11.0 (new) | - |\n"
    )
    target_deps: list[ChartDependency] = [{"name": "openklant", "version": "1.11.0"}]
    target_values: YamlMapping = {"openklant": {"image": {"tag": "2.15.0@sha256:aaaa"}}}

    new_text, changed, _unmatched, _unresolved = fix_component_version_table(
        text, ResolutionContext(None, ComponentState(target_deps, target_values), BaselineState([], {}))
    )
    assert changed == []
    assert new_text == text


def test_fix_component_version_table_new_sidecar_app_annotated_new_chart_cell_untouched(cdb: ModuleType):
    """A sidecar with no baseline tag gets App "(new)"; its Helm-chart cell stays "-"."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - k8s | 1.36.2 | - | ACR mirror only |\n"
    )
    target_deps, target_values, baseline_deps, baseline_values = redis_sidecar_deps_and_values()
    target_values["redis-operator"]["redis-ha"]["preDeleteJob"] = {
        "image": {"repository": "alpine/k8s", "tag": "1.36.2@sha256:cccc"}
    }

    new_text, changed, unmatched, unresolved = fix_component_version_table(
        text,
        ResolutionContext(
            None, ComponentState(target_deps, target_values), BaselineState(baseline_deps, baseline_values)
        ),
    )
    assert unmatched == [] and unresolved == []
    assert len(changed) == 1
    assert "| redis-operator - k8s | 1.36.2 (new) | - | ACR mirror only |" in new_text


def _write_historical_images_manifest(chart_dir, version, entries):
    """`url` defaults to `name`; pass a host-qualified `url` for callers that cross-check it."""
    images_dir = chart_dir / "docs" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / f"images-{version}.yaml").write_text(
        "".join(
            f'- name: {e["name"]}\n  url: {e.get("url", e["name"])}\n  version: "{e["version"]}"\n'
            f'  digest: "{e["digest"]}"\n'
            for e in entries
        ),
        encoding="utf-8",
    )


def test_fix_component_version_table_new_dependency_known_in_historical_manifest_is_unchanged(
    cdb: ModuleType, tmp_path: Path
):
    """A new dependency whose image is in an earlier images-<ver>.yaml at the same version gets App
    "(unchanged)"; its Chart cell stays "(new)"."""
    _write_historical_images_manifest(
        tmp_path,
        "4.8.0",
        [
            {
                "name": "brp-api/personen-mock",
                "url": "ghcr.io/brp-api/personen-mock",
                "version": "2.7.0-202606230850",
                "digest": "sha256:aaaa",
            }
        ],
    )
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| brppersonenmock | 2.7.0-202606230850 | 1.2.9 | - |\n"
    )
    target_deps: list[ChartDependency] = [{"name": "brppersonenmock", "version": "1.2.9"}]
    target_values: YamlMapping = {
        "brppersonenmock": {
            "image": {"repository": "ghcr.io/brp-api/personen-mock", "tag": "2.7.0-202606230850@sha256:aaaa"}
        }
    }

    new_text, changed, unmatched, unresolved = fix_component_version_table(
        text,
        ResolutionContext(
            tmp_path,
            ComponentState(target_deps, target_values),
            BaselineState([], {}),
            upgrade_docs_baseline="4.8.5",
        ),
    )
    assert unmatched == [] and unresolved == []
    assert len(changed) == 1
    assert "| brppersonenmock | 2.7.0-202606230850 (unchanged) | 1.2.9 (new) | - |" in new_text


def test_fix_component_version_table_new_sidecar_known_in_historical_manifest_is_unchanged(
    cdb: ModuleType, tmp_path: Path
):
    """Same historical-manifest fallback for a new sidecar row; the row starts stale so it is always
    rewritten, and the test checks what it becomes."""
    _write_historical_images_manifest(
        tmp_path,
        "4.8.0",
        [{"name": "alpine/k8s", "url": "quay.io/alpine/k8s", "version": "1.36.2", "digest": "sha256:cccc"}],
    )
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - k8s | 1.36.1 | - | ACR mirror only |\n"
    )
    target_deps, target_values, baseline_deps, baseline_values = redis_sidecar_deps_and_values()
    target_values["redis-operator"]["k8s"] = {
        "image": {"repository": "quay.io/alpine/k8s", "tag": "1.36.2@sha256:cccc"}
    }

    new_text, changed, unmatched, unresolved = fix_component_version_table(
        text,
        ResolutionContext(
            tmp_path,
            ComponentState(target_deps, target_values),
            BaselineState(baseline_deps, baseline_values),
            upgrade_docs_baseline="4.8.5",
        ),
    )
    assert unmatched == [] and unresolved == []
    assert len(changed) == 1
    assert "| redis-operator - k8s | 1.36.2 (unchanged) | - | ACR mirror only |" in new_text


def test_fix_component_version_table_corrects_a_stale_new_annotation_with_matching_numbers(
    cdb: ModuleType, tmp_path: Path
):
    """A stale "(new)" whose number already matches the target is still corrected to "(unchanged)".

    Comparing only the numeric endpoints would treat it as matching and never fix the annotation.
    """
    _write_historical_images_manifest(
        tmp_path,
        "4.8.0",
        [{"name": "alpine/k8s", "url": "quay.io/alpine/k8s", "version": "1.36.2", "digest": "sha256:cccc"}],
    )
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - k8s | 1.36.2 (new) | - | ACR mirror only |\n"
    )
    target_deps, target_values, baseline_deps, baseline_values = redis_sidecar_deps_and_values()
    target_values["redis-operator"]["k8s"] = {
        "image": {"repository": "quay.io/alpine/k8s", "tag": "1.36.2@sha256:cccc"}
    }

    new_text, changed, unmatched, unresolved = fix_component_version_table(
        text,
        ResolutionContext(
            tmp_path,
            ComponentState(target_deps, target_values),
            BaselineState(baseline_deps, baseline_values),
            upgrade_docs_baseline="4.8.5",
        ),
    )
    assert unmatched == [] and unresolved == []
    assert len(changed) == 1
    assert "| redis-operator - k8s | 1.36.2 (unchanged) | - | ACR mirror only |" in new_text


# --- fix_changes_heading_app_versions ---


def test_fix_changes_heading_app_versions_corrects_wrong_new_dependency_heading(cdb: ModuleType):
    """A new dependency's stale "a → b" Changes heading becomes "(new)", not "(unchanged)".

    Round-tripping through the rendered cell text cannot tell the two annotations apart.
    """
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| mi | 2.90.0 (new) | 1.1.0 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)\n\n"
        "Some stale prose here.\n"
    )
    deps: list[ChartDependency] = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values: YamlMapping = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = fix_changes_heading_app_versions(
        text,
        ResolutionContext(None, ComponentState(deps, target_values), BaselineState([], {}), upgrade_docs_baseline=None),
    )

    assert updated_headings == ["mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)"]
    assert "### mi 2.90.0 (new) (chart 1.1.0, unchanged)" in new_text
    assert "2.71.0" not in new_text
    assert "(unchanged)\n\nSome stale prose here." not in new_text  # body left as-is, not regenerated
    assert "Some stale prose here." in new_text


def test_fix_changes_heading_app_versions_syncs_headings_name_to_rows(cdb: ModuleType):
    """The row's display name is authoritative: a drifted heading name is synced to it."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| mi-data (MI-data exports) | 2.71.0 → 2.90.0 | 1.0.0 → 1.1.0 | - |\n\n"
        "## Changes\n\n"
        "### mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)\n\n"
        "Some stale prose here.\n"
    )
    deps: list[ChartDependency] = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values: YamlMapping = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = fix_changes_heading_app_versions(
        text,
        ResolutionContext(None, ComponentState(deps, target_values), BaselineState([], {}), upgrade_docs_baseline=None),
    )

    assert updated_headings == ["mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)"]
    assert "### mi-data (MI-data exports) 2.90.0 (new) (chart 1.1.0, unchanged)" in new_text
    assert "Some stale prose here." in new_text  # body left as-is, not regenerated


def test_fix_changes_heading_app_versions_renames_even_when_app_version_already_correct(cdb: ModuleType):
    """A wrong name alone triggers a rewrite, but only when the heading name is the bare values_key
    (the auto-written, never hand-customized form)."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| mi-data (MI-data exports) | 2.90.0 (new) | 1.1.0 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### mi 2.90.0 (new) (chart 1.1.0, unchanged)\n\n"
        "Some stale prose here.\n"
    )
    deps: list[ChartDependency] = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values: YamlMapping = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = fix_changes_heading_app_versions(
        text,
        ResolutionContext(None, ComponentState(deps, target_values), BaselineState([], {}), upgrade_docs_baseline=None),
    )

    assert updated_headings == ["mi 2.90.0 (new) (chart 1.1.0, unchanged)"]
    assert "### mi-data (MI-data exports) 2.90.0 (new) (chart 1.1.0, unchanged)" in new_text


def test_fix_changes_heading_app_versions_preserves_deliberately_customized_name(cdb: ModuleType):
    """A hand-customized heading name with correct app-version wording is left untouched."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| Keycloak Operator (server + operator images) | 26.7.2 → 26.7.3 | 1.12.1 → 1.13.0 | - |\n\n"
        "## Changes\n\n"
        "### Keycloak Operator (server) 26.7.2 → 26.7.3 (chart 1.12.1 → 1.13.0)\n\n"
        "Real, hand-written prose describing just the server image bump.\n"
    )
    deps: list[ChartDependency] = [{"name": "keycloak-operator", "version": "1.13.0"}]
    target_values: YamlMapping = {
        "keycloak-operator": {
            "operator": {
                "config": {
                    "keycloakImage": {"repository": "quay.io/keycloak/keycloak", "tag": "26.7.3@sha256:" + "b" * 64}
                }
            }
        }
    }
    baseline_deps: list[ChartDependency] = [{"name": "keycloak-operator", "version": "1.12.1"}]
    baseline_values: YamlMapping = {
        "keycloak-operator": {
            "operator": {
                "config": {
                    "keycloakImage": {"repository": "quay.io/keycloak/keycloak", "tag": "26.7.2@sha256:" + "a" * 64}
                }
            }
        }
    }

    new_text, updated_headings = fix_changes_heading_app_versions(
        text,
        ResolutionContext(
            None,
            ComponentState(deps, target_values),
            BaselineState(baseline_deps, baseline_values),
            upgrade_docs_baseline="4.9.0",
        ),
    )

    assert updated_headings == []
    assert new_text == text


def test_fix_changes_heading_app_versions_no_version_marker_never_touched(cdb: ModuleType):
    """A heading with no version marker (arrow, "(new)", "(unchanged)", "(digest changed)") is never touched."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| mi-data (MI-data exports) | 2.90.0 (new) | 1.1.0 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### mi\n\n"
        "Free-form prose with no version claim at all.\n"
    )
    deps: list[ChartDependency] = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values: YamlMapping = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = fix_changes_heading_app_versions(
        text,
        ResolutionContext(None, ComponentState(deps, target_values), BaselineState([], {}), upgrade_docs_baseline=None),
    )

    assert updated_headings == []
    assert new_text == text


def test_fix_changes_heading_app_versions_already_correct_heading_untouched(cdb: ModuleType):
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| mi | 2.90.0 (new) | 1.1.0 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### mi 2.90.0 (new) (chart 1.1.0, unchanged)\n\n"
        "PodiumD 4.9.1 introduces **mi** at app version 2.90.0.\n"
    )
    deps: list[ChartDependency] = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values: YamlMapping = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = fix_changes_heading_app_versions(
        text,
        ResolutionContext(None, ComponentState(deps, target_values), BaselineState([], {}), upgrade_docs_baseline=None),
    )

    assert updated_headings == []
    assert new_text == text


def test_fix_changes_heading_app_versions_real_version_bump_still_corrected(cdb: ModuleType):
    """A stale heading for a real version bump is corrected too, not only the "(new)" case."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| zac | 5.4.0 → 5.5.0 | 1.0.297 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### zac 5.4.0 → 5.4.0 (chart 1.0.297, unchanged)\n\n"
        "Stale prose from a previous, wrong resolution.\n"
    )
    deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    target_values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.5.0@sha256:" + "b" * 64}}
    }
    baseline_deps: list[ChartDependency] = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_values: YamlMapping = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.0@sha256:" + "a" * 64}}
    }

    new_text, updated_headings = fix_changes_heading_app_versions(
        text,
        ResolutionContext(
            None,
            ComponentState(deps, target_values),
            BaselineState(baseline_deps, baseline_values),
            upgrade_docs_baseline="4.9.0",
        ),
    )

    assert updated_headings == ["zac 5.4.0 → 5.4.0 (chart 1.0.297, unchanged)"]
    assert "### zac 5.4.0 → 5.5.0 (chart 1.0.297, unchanged)" in new_text


def test_fix_changes_heading_app_versions_corrects_stale_bare_sidecar_heading(cdb: ModuleType):
    """A stale bare global.images sidecar heading (e.g. "redis") is corrected like a "dep" heading."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis | 8.10.1 (new) | - | - |\n\n"
        "## Changes\n\n"
        "### redis 8.0 → 8.10.1\n\n"
        "Some stale prose here.\n"
    )
    deps: list[ChartDependency] = []
    target_values: YamlMapping = {
        "global": {"images": {"redis": {"repository": "redis", "tag": "8.10.1@sha256:" + "a" * 64}}}
    }

    new_text, updated_headings = fix_changes_heading_app_versions(
        text,
        ResolutionContext(None, ComponentState(deps, target_values), BaselineState([], {}), upgrade_docs_baseline=None),
    )

    assert updated_headings == ["redis 8.0 → 8.10.1"]
    assert "### redis 8.10.1 (new)" in new_text
    assert "8.0 →" not in new_text
    assert "Some stale prose here." in new_text  # body left as-is, not regenerated


def test_fix_changes_heading_app_versions_corrects_stale_real_sidecar_heading(cdb: ModuleType):
    """A stale nested sidecar heading ("redis-operator - redis") is corrected; the canonical sidecar match
    takes precedence over match_dependency's fuzzy leading-word match."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - redis | 8.6.2 → 8.6.6 | - | ACR mirror only |\n\n"
        "## Changes\n\n"
        "### redis-operator - redis 8.6.1 → 8.6.6 (chart 0.25.0, unchanged)\n\n"
        "Some stale prose here.\n"
    )
    target_deps, target_values, baseline_deps, baseline_values = redis_sidecar_deps_and_values()

    new_text, updated_headings = fix_changes_heading_app_versions(
        text,
        ResolutionContext(
            None,
            ComponentState(target_deps, target_values),
            BaselineState(baseline_deps, baseline_values),
            upgrade_docs_baseline="4.8.5",
        ),
    )

    assert updated_headings == ["redis-operator - redis 8.6.1 → 8.6.6 (chart 0.25.0, unchanged)"]
    assert "### redis-operator - redis 8.6.2 → 8.6.6 (chart 0.25.0, unchanged)" in new_text


def test_fix_changes_heading_app_versions_already_correct_sidecar_heading_untouched(cdb: ModuleType):
    """An already-correct sidecar heading is never rewritten."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis | 8.10.1 (new) | - | - |\n\n"
        "## Changes\n\n"
        "### redis 8.10.1 (new)\n\n"
        "Some prose here.\n"
    )
    deps: list[ChartDependency] = []
    target_values: YamlMapping = {
        "global": {"images": {"redis": {"repository": "redis", "tag": "8.10.1@sha256:" + "a" * 64}}}
    }

    new_text, updated_headings = fix_changes_heading_app_versions(
        text,
        ResolutionContext(None, ComponentState(deps, target_values), BaselineState([], {}), upgrade_docs_baseline=None),
    )

    assert updated_headings == []
    assert new_text == text


def test_fix_changes_heading_app_versions_corrects_moved_repository_sidecar_heading(cdb: ModuleType, tmp_path: Path):
    """A sidecar heading whose repository moved anchors (postgres consolidated into global.images) gets
    "a → b", not "(new)", matching the table row's repository-moved fallback."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| postgres | 16-alpine → 16.15-alpine | - | - |\n\n"
        "## Changes\n\n"
        "### postgres 16.15-alpine (new)\n\n"
        "Some stale prose here.\n"
    )
    deps: list[ChartDependency] = [{"name": "openbao", "version": "2.0.0"}]
    target_values: YamlMapping = {
        "global": {"images": {"postgres": {"repository": "postgres", "tag": "16.15-alpine@sha256:aaaa"}}},
        "openbao": {
            "database": {"schemaJob": {"image": {"repository": "postgres", "tag": "16.15-alpine@sha256:aaaa"}}}
        },
    }
    baseline_values: YamlMapping = {
        "openbao": {"database": {"schemaJob": {"image": {"repository": "postgres", "tag": "16-alpine@sha256:bbbb"}}}},
    }

    new_text, updated_headings = fix_changes_heading_app_versions(
        text,
        ResolutionContext(
            tmp_path,
            ComponentState(deps, target_values),
            BaselineState(deps, baseline_values),
            upgrade_docs_baseline=None,
        ),
    )

    assert updated_headings == ["postgres 16.15-alpine (new)"]
    assert "### postgres 16-alpine → 16.15-alpine" in new_text
    assert "(new)" not in new_text
    assert "Some stale prose here." in new_text  # body left as-is, not regenerated


# --- fix_values_delta_heading_app_versions ---

MI_UPGRADE_DOC_TEXT = (
    "## Component versions (4.9.1 vs 4.9.0)\n\n"
    "| Component | App version | Helm chart | Notes |\n"
    "| --- | --- | --- | --- |\n"
    "| mi-data (MI-data exports) | 2.90.0 (new) | 1.0.0 → 1.1.0 | - |\n"
)


def test_fix_values_delta_heading_app_versions_corrects_wrong_name_and_new_dependency_wording(cdb: ModuleType):
    """values-deltas.md's "## mi" heading gets the -upgrade.md row's name and wording; values-deltas.md
    has no table of its own."""
    values_deltas_text = (
        "# Values deltas — PodiumD 4.9.0 → 4.9.1\n\n"
        "## mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)\n\n"
        "- Key `mi.transfer.noEpsv` (optional) added.\n"
    )
    deps: list[ChartDependency] = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values: YamlMapping = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = fix_values_delta_heading_app_versions(
        MI_UPGRADE_DOC_TEXT,
        values_deltas_text,
        ResolutionContext(None, ComponentState(deps, target_values), BaselineState([], {}), upgrade_docs_baseline=None),
    )

    assert updated_headings == ["mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)"]
    assert "## mi-data (MI-data exports) 2.90.0 (new) (chart 1.1.0, unchanged)" in new_text
    assert "- Key `mi.transfer.noEpsv` (optional) added." in new_text  # body left as-is


def test_fix_values_delta_heading_app_versions_already_correct_heading_untouched(cdb: ModuleType):
    values_deltas_text = (
        "# Values deltas — PodiumD 4.9.0 → 4.9.1\n\n"
        "## mi-data (MI-data exports) 2.90.0 (new) (chart 1.1.0, unchanged)\n\n"
        "- Key `mi.transfer.noEpsv` (optional) added.\n"
    )
    deps: list[ChartDependency] = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values: YamlMapping = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = fix_values_delta_heading_app_versions(
        MI_UPGRADE_DOC_TEXT,
        values_deltas_text,
        ResolutionContext(None, ComponentState(deps, target_values), BaselineState([], {}), upgrade_docs_baseline=None),
    )

    assert updated_headings == []
    assert new_text == values_deltas_text


def test_fix_values_delta_heading_app_versions_corrects_stale_sidecar_heading(cdb: ModuleType):
    """A stale sidecar "## ..." heading in -values-deltas.md is corrected via the shared core."""
    redis_upgrade_doc_text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis | 8.10.1 (new) | - | - |\n"
    )
    values_deltas_text = (
        "# Values deltas — PodiumD 4.9.0 → 4.9.1\n\n## redis 8.0 → 8.10.1\n\n- `global.images.redis` added.\n"
    )
    deps: list[ChartDependency] = []
    target_values: YamlMapping = {
        "global": {"images": {"redis": {"repository": "redis", "tag": "8.10.1@sha256:" + "a" * 64}}}
    }

    new_text, updated_headings = fix_values_delta_heading_app_versions(
        redis_upgrade_doc_text,
        values_deltas_text,
        ResolutionContext(None, ComponentState(deps, target_values), BaselineState([], {}), upgrade_docs_baseline=None),
    )

    assert updated_headings == ["redis 8.0 → 8.10.1"]
    assert "## redis 8.10.1 (new)" in new_text
    assert "- `global.images.redis` added." in new_text  # body left as-is


def test_fix_values_delta_heading_app_versions_bare_hand_written_heading_never_touched(cdb: ModuleType):
    """Hand-written values-deltas.md headings with no version marker are never touched, even if resolvable."""
    values_deltas_text = (
        "# Values deltas — PodiumD 4.9.0 → 4.9.1\n\n## mi\n\nFree-form prose, no version marker at all.\n"
    )
    deps: list[ChartDependency] = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values: YamlMapping = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = fix_values_delta_heading_app_versions(
        MI_UPGRADE_DOC_TEXT,
        values_deltas_text,
        ResolutionContext(None, ComponentState(deps, target_values), BaselineState([], {}), upgrade_docs_baseline=None),
    )

    assert updated_headings == []
    assert new_text == values_deltas_text


def test_fix_values_delta_heading_app_versions_no_upgrade_doc_is_a_noop(cdb: ModuleType):
    """No -upgrade.md: nothing to resolve against, so no heading is touched and no error."""
    values_deltas_text = (
        "# Values deltas — PodiumD 4.9.0 → 4.9.1\n\n"
        "## mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)\n\n"
        "- Key `mi.transfer.noEpsv` (optional) added.\n"
    )
    deps: list[ChartDependency] = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values: YamlMapping = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = fix_values_delta_heading_app_versions(
        "",
        values_deltas_text,
        ResolutionContext(None, ComponentState(deps, target_values), BaselineState([], {}), upgrade_docs_baseline=None),
    )

    assert updated_headings == []
    assert new_text == values_deltas_text
