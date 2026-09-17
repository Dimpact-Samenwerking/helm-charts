"""canonical_version_cell, fix_component_version_table, fix_changes_heading_app_versions,
fix_values_delta_heading_app_versions — pure logic, no git repo needed."""


# --- canonical_version_cell ---


def test_canonical_version_cell_arrow_form(cdb):
    assert cdb.canonical_version_cell("5.0.2", "5.1.0") == "5.0.2 → 5.1.0"


def test_canonical_version_cell_unchanged_form(cdb):
    assert cdb.canonical_version_cell("1.0.297", "1.0.297") == "1.0.297 (unchanged)"


def test_canonical_version_cell_v_prefix_counts_as_unchanged(cdb):
    assert cdb.canonical_version_cell("v0.9.352", "0.9.352") == "0.9.352 (unchanged)"


# --- fix_component_version_table ---


def target_deps_and_values():
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}]
    values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    return deps, values


def test_fix_component_version_table_corrects_stale_source(cdb):
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.1 → 5.1.0 | 1.0.251 → 1.0.257 | ACR mirror only |\n"
    )
    target_deps, target_values = target_deps_and_values()
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_values = {"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, baseline_deps, baseline_values
    )
    assert unmatched == [] and unresolved == []
    assert len(changed) == 1
    assert "5.0.2 → 5.1.0" in new_text
    assert "1.0.297 → 1.0.257" in new_text
    assert "5.0.1" not in new_text
    assert "1.0.251" not in new_text
    assert "ACR mirror only" in new_text  # notes column untouched


def test_fix_component_version_table_leaves_correct_row_untouched(cdb):
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.1.0 | 1.0.297 → 1.0.257 | ACR mirror only |\n"
    )
    target_deps, target_values = target_deps_and_values()
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_values = {"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, baseline_deps, baseline_values
    )
    assert changed == []
    assert new_text == text


def test_fix_component_version_table_unmatched_component_reported(cdb):
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| Totally Unknown Thing | 1.0.0 → 2.0.0 | 1.0.0 → 2.0.0 | - |\n"
    )
    target_deps, target_values = target_deps_and_values()
    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, [{"name": "zac", "version": "1.0.297"}], {}
    )
    assert changed == []
    assert unmatched == ["Totally Unknown Thing"]
    assert new_text == text


def test_fix_component_version_table_no_baseline_data_reported_unresolved(cdb):
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.1 → 5.1.0 | 1.0.251 → 1.0.257 | ACR mirror only |\n"
    )
    target_deps, target_values = target_deps_and_values()
    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, None, None
    )
    assert changed == []
    assert unresolved == ["ZAC (Zaakafhandelcomponent)"]
    assert new_text == text


def redis_sidecar_deps_and_values(target_chart="0.26.1", baseline_chart="0.25.0", target_tag="8.6.6"):
    target_deps = [{"name": "redis-operator", "version": target_chart}]
    baseline_deps = [{"name": "redis-operator", "version": baseline_chart}]
    target_values = {
        "redis-operator": {
            "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": f"{target_tag}@sha256:aaaa"}}
        }
    }
    baseline_values = {
        "redis-operator": {"redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": "8.6.2@sha256:aaaa"}}}
    }
    return target_deps, target_values, baseline_deps, baseline_values


def test_fix_component_version_table_leaves_a_correct_sidecar_row_untouched(cdb):
    """Regression test: a correctly-phrased canonical sidecar row (see
    lib.chart.canonical_sidecar_row_names) must never be "corrected"
    against its unrelated owning dependency's own chart/app version —
    match_dependency fuzzy-matches "redis-operator - redis" to the real
    "redis-operator" dependency on its leading word, which used to
    silently rewrite this row's Helm-chart cell from "-" to
    "0.25.0 → 0.26.1" (redis-operator's own chart bump, nothing to do
    with this sidecar row at all)."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - redis | 8.6.2 → 8.6.6 | - | ACR mirror only |\n"
    )
    target_deps, target_values, baseline_deps, baseline_values = redis_sidecar_deps_and_values()

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, baseline_deps, baseline_values
    )
    assert changed == []
    assert new_text == text


def test_fix_component_version_table_corrects_a_stale_sidecar_row_using_its_own_tag(cdb):
    """A sidecar row's App-version cell IS still corrected when stale —
    against its OWN resolved tag, never the owning dependency's. Its
    Helm-chart cell stays "-" regardless (never rewritten to the
    dependency's own chart version, the exact corruption this guards
    against)."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - redis | 8.6.2 → 9.9.9 | - | ACR mirror only |\n"
    )
    target_deps, target_values, baseline_deps, baseline_values = redis_sidecar_deps_and_values()

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, baseline_deps, baseline_values
    )
    assert len(changed) == 1
    assert "8.6.2 → 8.6.6" in new_text
    assert "9.9.9" not in new_text
    assert "| redis-operator - redis | 8.6.2 → 8.6.6 | - | ACR mirror only |" in new_text


def test_fix_component_version_table_corrects_a_native_components_wrong_chart_cell(cdb):
    """Real bug this guards against: frankgateway (see lib.chart.
    NATIVE_COMPONENTS — no Chart.yaml dependency at all) briefly gained a
    mistaken Chart.yaml dependency entry, and its row's Helm-chart cell
    was written as if it were a real version ("1.1.0"). Unlike a
    sidecar's own "-" (trusted correct from the moment it's first
    written), a native component's chart cell CAN start out wrong like
    this, and nothing else ever corrects it back — this is the one place
    that does."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| frankgateway | 104 (unchanged) | 1.1.0 (new) | - |\n"
    )
    target_deps = [{"name": "zac", "version": "1.0.297"}]
    target_values = {"frankgateway": {"image": {"tag": "104@sha256:aaaa"}}}
    baseline_deps = [{"name": "zac", "version": "1.0.297"}]
    baseline_values = {"frankgateway": {"image": {"tag": "104@sha256:aaaa"}}}

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, baseline_deps, baseline_values
    )
    assert unmatched == [] and unresolved == []
    assert len(changed) == 1
    assert "| frankgateway | 104 (unchanged) | - | - |" in new_text
    assert "1.1.0" not in new_text


def test_fix_component_version_table_leaves_a_correct_native_component_row_untouched(cdb):
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| frankgateway | 104 (unchanged) | - | - |\n"
    )
    target_deps = [{"name": "zac", "version": "1.0.297"}]
    target_values = {"frankgateway": {"image": {"tag": "104@sha256:aaaa"}}}
    baseline_deps = [{"name": "zac", "version": "1.0.297"}]
    baseline_values = {"frankgateway": {"image": {"tag": "104@sha256:aaaa"}}}

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, baseline_deps, baseline_values
    )
    assert changed == []
    assert new_text == text


def test_fix_component_version_table_unresolvable_canonical_row_reported_not_corrupted(cdb):
    """A row shaped like the canonical sidecar form but with no
    resolvable repository (e.g. "kiss - podiumd-adapter", commented out
    in real life) must be reported as unresolved — never fall through
    to match_dependency and get "corrected" against an unrelated real
    dependency's own actual version just because it shares a leading
    word."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - ghost | 0.6.6 → 0.6.7 | - | ACR mirror only |\n"
    )
    target_deps, target_values, baseline_deps, baseline_values = redis_sidecar_deps_and_values()

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, baseline_deps, baseline_values
    )
    assert changed == []
    assert unresolved == ["redis-operator - ghost"]
    assert new_text == text


def test_fix_component_version_table_new_dependency_annotated_new_not_reported_unresolved(cdb):
    """A dependency with no matching entry at all in the baseline
    Chart.yaml (brand new this hop) gets "(new)" cells instead of being
    left untouched and reported for manual review — this row's
    baseline_resolved is unambiguously False (Chart.yaml either has the
    dependency at that ref or it doesn't), so there's nothing to
    "review by hand" here."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| openklant | 2.15.0 | 1.11.0 | - |\n"
    )
    target_deps = [{"name": "openklant", "version": "1.11.0"}]
    target_values = {"openklant": {"image": {"tag": "2.15.0@sha256:aaaa"}}}

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, [], {}
    )
    assert unmatched == [] and unresolved == []
    assert len(changed) == 1
    assert "| openklant | 2.15.0 (new) | 1.11.0 (new) | - |" in new_text


def test_fix_component_version_table_new_dependency_already_annotated_is_untouched(cdb):
    """Idempotent: a row already correctly reading "(new)" is left alone,
    not endlessly re-flagged as changed on every run."""
    text = (
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| openklant | 2.15.0 (new) | 1.11.0 (new) | - |\n"
    )
    target_deps = [{"name": "openklant", "version": "1.11.0"}]
    target_values = {"openklant": {"image": {"tag": "2.15.0@sha256:aaaa"}}}

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, [], {}
    )
    assert changed == []
    assert new_text == text


def test_fix_component_version_table_new_sidecar_app_annotated_new_chart_cell_untouched(cdb):
    """A sidecar with no baseline tag at all (brand new this hop) gets
    its App cell annotated "(new)" — its Helm-chart cell stays "-"
    regardless, same as every other sidecar row; there's no chart
    version of its own to annotate."""
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

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, None, target_deps, target_values, baseline_deps, baseline_values
    )
    assert unmatched == [] and unresolved == []
    assert len(changed) == 1
    assert "| redis-operator - k8s | 1.36.2 (new) | - | ACR mirror only |" in new_text


def _write_historical_images_manifest(chart_dir, version, entries):
    """`url` defaults to `name` when an entry doesn't give one of its own
    — a real images-manifest entry's own "url:" is always fully host-
    qualified, unlike a bare "name:" (see lib.chart.historical_app_
    version_for_path's own url cross-check), so a test relying on that
    fallback (rather than passing a realistic "url" explicitly) only
    ever works for a caller that doesn't cross-check it."""
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


def test_fix_component_version_table_new_dependency_known_in_historical_manifest_is_unchanged(cdb, tmp_path):
    """Regression test: a brand-new Chart.yaml dependency (baseline_deps
    has no matching entry at all) whose image repository already
    appears, byte-for-byte at the same version, in an earlier release's
    own images-4.8.0.yaml manifest — its APP cell should read
    "(unchanged)" instead of "(new)"; its CHART cell still correctly
    reads "(new)", since the Chart.yaml dependency line genuinely is
    new. Not the removed images-baseline.yaml side-file."""
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
    target_deps = [{"name": "brppersonenmock", "version": "1.2.9"}]
    target_values = {
        "brppersonenmock": {
            "image": {"repository": "ghcr.io/brp-api/personen-mock", "tag": "2.7.0-202606230850@sha256:aaaa"}
        }
    }

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, tmp_path, target_deps, target_values, [], {}, upgrade_docs_baseline="4.8.5"
    )
    assert unmatched == [] and unresolved == []
    assert len(changed) == 1
    assert "| brppersonenmock | 2.7.0-202606230850 (unchanged) | 1.2.9 (new) | - |" in new_text


def test_fix_component_version_table_new_sidecar_known_in_historical_manifest_is_unchanged(cdb, tmp_path):
    """Same fallback for a brand-new canonical sidecar row (see
    add_missing_sidecar_rows/lib.upgradedoc.resolve_component_row's own
    sidecar branch) — real case: redis-operator's own "k8s" sidecar. The
    row starts stale (a wrong target number) so it's guaranteed to be
    rewritten regardless of annotation text — the value under test is
    what it gets rewritten TO."""
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

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, tmp_path, target_deps, target_values, baseline_deps, baseline_values, upgrade_docs_baseline="4.8.5"
    )
    assert unmatched == [] and unresolved == []
    assert len(changed) == 1
    assert "| redis-operator - k8s | 1.36.2 (unchanged) | - | ACR mirror only |" in new_text


def test_fix_component_version_table_corrects_a_stale_new_annotation_with_matching_numbers(cdb, tmp_path):
    """Regression test: a row written "(new)" by an OLDER fix-doc-
    consistency run (before the historical-images-manifest fallback
    existed) whose NUMBER already happens to match the target (both
    read "1.36.2") must still be corrected to "(unchanged)" — comparing
    only row["app_source"]/row["app"] (the numeric endpoints alone)
    would treat this row as already "matching" and never touch it,
    silently leaving the wrong annotation in place forever."""
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

    new_text, changed, unmatched, unresolved = cdb.fix_component_version_table(
        text, tmp_path, target_deps, target_values, baseline_deps, baseline_values, upgrade_docs_baseline="4.8.5"
    )
    assert unmatched == [] and unresolved == []
    assert len(changed) == 1
    assert "| redis-operator - k8s | 1.36.2 (unchanged) | - | ACR mirror only |" in new_text


# --- fix_changes_heading_app_versions ---


def test_fix_changes_heading_app_versions_corrects_wrong_new_dependency_heading(cdb):
    """Real bug, real doc: mi's own row was already correctly fixed
    ("2.90.0 (new)" — a brand-new Chart.yaml dependency this hop, no
    2.71.0 baseline value exists at all) by an earlier fix_component_
    version_table run, but its OWN "### mi ..." Changes heading was
    never revisited and still shows the stale, wrong
    "2.71.0 → 2.90.0" transition. Must become "2.90.0 (new)" — never
    "2.90.0 (unchanged)", the wrong wording a naive round-trip through
    the row's own rendered cell text (extract_source_version/
    extract_target_version, which can't tell "(new)" and "(unchanged)"
    apart once the annotation itself is stripped) would produce."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| mi | 2.90.0 (new) | 1.1.0 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)\n\n"
        "Some stale prose here.\n"
    )
    deps = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = cdb.fix_changes_heading_app_versions(
        text, None, deps, target_values, [], {}, upgrade_docs_baseline=None
    )

    assert updated_headings == ["mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)"]
    assert "### mi 2.90.0 (new) (chart 1.1.0, unchanged)" in new_text
    assert "2.71.0" not in new_text
    assert "(unchanged)\n\nSome stale prose here." not in new_text  # body left as-is, not regenerated
    assert "Some stale prose here." in new_text


def test_fix_changes_heading_app_versions_syncs_headings_name_to_rows(cdb):
    """Real bug found live: the table row's own display name ("mi-data
    (MI-data exports)") and this same component's own Changes heading
    ("mi") had drifted apart — every OTHER row/heading pair in the real
    doc agrees (exactly, or via a deliberately hand-customized variant
    of the same name), only mi's didn't. The ROW's own name is
    authoritative (see add_missing_component_rows' own docstring: the
    same "friendly" value is passed to both the row and the heading
    when freshly written together) — a first version of this fix instead
    preserved the heading's own (stale) name, which is backwards."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| mi-data (MI-data exports) | 2.71.0 → 2.90.0 | 1.0.0 → 1.1.0 | - |\n\n"
        "## Changes\n\n"
        "### mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)\n\n"
        "Some stale prose here.\n"
    )
    deps = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = cdb.fix_changes_heading_app_versions(
        text, None, deps, target_values, [], {}, upgrade_docs_baseline=None
    )

    assert updated_headings == ["mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)"]
    assert "### mi-data (MI-data exports) 2.90.0 (new) (chart 1.1.0, unchanged)" in new_text
    assert "Some stale prose here." in new_text  # body left as-is, not regenerated


def test_fix_changes_heading_app_versions_renames_even_when_app_version_already_correct(cdb):
    """A wrong NAME alone (app-version wording already correct) is still
    enough to trigger a rewrite — the two checks are independent, not
    "only bother if the version is ALSO wrong" — but ONLY because the
    heading's own current name is precisely the bare values_key "mi"
    (add_missing_component_rows' own auto-write convention), the
    unambiguous "never hand-customized, still says what a fresh
    auto-write would" signal (see the next test for what happens when
    it isn't)."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| mi-data (MI-data exports) | 2.90.0 (new) | 1.1.0 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### mi 2.90.0 (new) (chart 1.1.0, unchanged)\n\n"
        "Some stale prose here.\n"
    )
    deps = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = cdb.fix_changes_heading_app_versions(
        text, None, deps, target_values, [], {}, upgrade_docs_baseline=None
    )

    assert updated_headings == ["mi 2.90.0 (new) (chart 1.1.0, unchanged)"]
    assert "### mi-data (MI-data exports) 2.90.0 (new) (chart 1.1.0, unchanged)" in new_text


def test_fix_changes_heading_app_versions_preserves_deliberately_customized_name(cdb):
    """Real bug found live against the real chart: a first version of
    this fix renamed "### Keycloak Operator (server) 26.7.2 -> 26.7.3
    (chart 1.12.1 -> 1.13.0)" to "### Keycloak Operator (server +
    operator images) 26.7.2 -> 26.7.3 (chart 1.12.1 -> 1.13.0)" — the
    row's own longer name — even though the app-version wording was
    ALREADY correct and the heading's own name is a DELIBERATE, human-
    written editorial variant (distinguishing this heading, about just
    the server image, from "keycloak-operator - operator"'s own
    separate row/heading), never the stale bare values_key. Must be
    left completely untouched."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| Keycloak Operator (server + operator images) | 26.7.2 → 26.7.3 | 1.12.1 → 1.13.0 | - |\n\n"
        "## Changes\n\n"
        "### Keycloak Operator (server) 26.7.2 → 26.7.3 (chart 1.12.1 → 1.13.0)\n\n"
        "Real, hand-written prose describing just the server image bump.\n"
    )
    deps = [{"name": "keycloak-operator", "version": "1.13.0"}]
    target_values = {
        "keycloak-operator": {
            "operator": {
                "config": {
                    "keycloakImage": {"repository": "quay.io/keycloak/keycloak", "tag": "26.7.3@sha256:" + "b" * 64}
                }
            }
        }
    }
    baseline_deps = [{"name": "keycloak-operator", "version": "1.12.1"}]
    baseline_values = {
        "keycloak-operator": {
            "operator": {
                "config": {
                    "keycloakImage": {"repository": "quay.io/keycloak/keycloak", "tag": "26.7.2@sha256:" + "a" * 64}
                }
            }
        }
    }

    new_text, updated_headings = cdb.fix_changes_heading_app_versions(
        text, None, deps, target_values, baseline_deps, baseline_values, upgrade_docs_baseline="4.9.0"
    )

    assert updated_headings == []
    assert new_text == text


def test_fix_changes_heading_app_versions_no_version_marker_never_touched(cdb):
    """A heading naming a real "dep" identity but with NO recognizable
    version marker at all (arrow/"(new)"/"(unchanged)"/"(digest
    changed)") was never meant to carry a machine-verifiable version in
    the first place — real doc: values-deltas.md's own bare "## mi"
    would-be case; reproduced here via -upgrade.md's own Changes
    heading shape instead, since the mechanism (changes_heading_has_
    app_version) is identical for both. Must be left untouched, not
    "corrected" into inventing a version it never claimed to show."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| mi-data (MI-data exports) | 2.90.0 (new) | 1.1.0 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### mi\n\n"
        "Free-form prose with no version claim at all.\n"
    )
    deps = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = cdb.fix_changes_heading_app_versions(
        text, None, deps, target_values, [], {}, upgrade_docs_baseline=None
    )

    assert updated_headings == []
    assert new_text == text


def test_fix_changes_heading_app_versions_already_correct_heading_untouched(cdb):
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| mi | 2.90.0 (new) | 1.1.0 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### mi 2.90.0 (new) (chart 1.1.0, unchanged)\n\n"
        "PodiumD 4.9.1 introduces **mi** at app version 2.90.0.\n"
    )
    deps = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = cdb.fix_changes_heading_app_versions(
        text, None, deps, target_values, [], {}, upgrade_docs_baseline=None
    )

    assert updated_headings == []
    assert new_text == text


def test_fix_changes_heading_app_versions_real_version_bump_still_corrected(cdb):
    """A real version transition (not a brand-new dependency) with a
    stale heading is corrected the same way — the "(new)" case above
    isn't the only one this covers."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| zac | 5.4.0 → 5.5.0 | 1.0.297 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### zac 5.4.0 → 5.4.0 (chart 1.0.297, unchanged)\n\n"
        "Stale prose from a previous, wrong resolution.\n"
    )
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    target_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.5.0@sha256:" + "b" * 64}}
    }
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.0@sha256:" + "a" * 64}}
    }

    new_text, updated_headings = cdb.fix_changes_heading_app_versions(
        text, None, deps, target_values, baseline_deps, baseline_values, upgrade_docs_baseline="4.9.0"
    )

    assert updated_headings == ["zac 5.4.0 → 5.4.0 (chart 1.0.297, unchanged)"]
    assert "### zac 5.4.0 → 5.5.0 (chart 1.0.297, unchanged)" in new_text


def test_fix_changes_heading_app_versions_corrects_stale_bare_sidecar_heading(cdb):
    """Regression test: a canonical sidecar/MULTIPLE-scope heading (a
    bare global.images anchor like "redis", not a real Chart.yaml
    dependency) can go stale the exact same way a "dep" heading can —
    proven wrong live: today's redis/redis-operator historical-manifest
    collision fix changed what resolve_component_row now resolves for
    "redis" (correctly rewriting the TABLE row to "8.10.1 (new)"), but
    the heading, previously never even considered here at all, was left
    showing the stale "8.0 → 8.10.1" transition implying a real prior
    version that never existed."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis | 8.10.1 (new) | - | - |\n\n"
        "## Changes\n\n"
        "### redis 8.0 → 8.10.1\n\n"
        "Some stale prose here.\n"
    )
    deps = []
    target_values = {"global": {"images": {"redis": {"repository": "redis", "tag": "8.10.1@sha256:" + "a" * 64}}}}

    new_text, updated_headings = cdb.fix_changes_heading_app_versions(
        text, None, deps, target_values, [], {}, upgrade_docs_baseline=None
    )

    assert updated_headings == ["redis 8.0 → 8.10.1"]
    assert "### redis 8.10.1 (new)" in new_text
    assert "8.0 →" not in new_text
    assert "Some stale prose here." in new_text  # body left as-is, not regenerated


def test_fix_changes_heading_app_versions_corrects_stale_real_sidecar_heading(cdb):
    """The general case, not just the bare global-anchor shape above: a
    real sidecar nested under an owning dependency ("redis-operator -
    redis") can go stale the same way — proves the fix isn't specific
    to redis's own MULTIPLE/global shape. Also proves match_dependency's
    own fuzzy leading-word match (which would otherwise treat this as
    plain "redis-operator", an unrelated identity — see lib.chart.
    canonical_sidecar_row_names' own docstring) never fires here: the
    canonical sidecar match always takes precedence."""
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

    new_text, updated_headings = cdb.fix_changes_heading_app_versions(
        text, None, target_deps, target_values, baseline_deps, baseline_values, upgrade_docs_baseline="4.8.5"
    )

    assert updated_headings == ["redis-operator - redis 8.6.1 → 8.6.6 (chart 0.25.0, unchanged)"]
    assert "### redis-operator - redis 8.6.2 → 8.6.6 (chart 0.25.0, unchanged)" in new_text


def test_fix_changes_heading_app_versions_already_correct_sidecar_heading_untouched(cdb):
    """Negative case: an already-correct sidecar heading (name AND
    app-version wording both already right) must never be spuriously
    rewritten — same discipline as the existing "dep"-kind untouched
    test above, now proven for sidecar kind too."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis | 8.10.1 (new) | - | - |\n\n"
        "## Changes\n\n"
        "### redis 8.10.1 (new)\n\n"
        "Some prose here.\n"
    )
    deps = []
    target_values = {"global": {"images": {"redis": {"repository": "redis", "tag": "8.10.1@sha256:" + "a" * 64}}}}

    new_text, updated_headings = cdb.fix_changes_heading_app_versions(
        text, None, deps, target_values, [], {}, upgrade_docs_baseline=None
    )

    assert updated_headings == []
    assert new_text == text


def test_fix_changes_heading_app_versions_corrects_moved_repository_sidecar_heading(cdb, tmp_path):
    """Live end-to-end reproduction of the resolve_component_row/
    add_missing_sidecar_rows divergence (podiumd 4.9.1's postgres
    consolidation, see lib.chart.baseline_tag_for_sidecar_path): the
    "Component versions" table row was already correct ("16-alpine →
    16.15-alpine" — lib.image_docs.add_missing_sidecar_rows' own
    repository-moved fallback resolved it right), but this heading, an
    INDEPENDENT resolution via resolve_component_row, still rendered
    "(new)" for the exact same shared image — global.images.postgres
    never existed in baseline_values, but the same "postgres" repository
    already did, at openbao.database.schemaJob.image (keycloak-
    operator's own sibling pin consolidated into this same anchor too)."""
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| postgres | 16-alpine → 16.15-alpine | - | - |\n\n"
        "## Changes\n\n"
        "### postgres 16.15-alpine (new)\n\n"
        "Some stale prose here.\n"
    )
    deps = [{"name": "openbao", "version": "2.0.0"}]
    target_values = {
        "global": {"images": {"postgres": {"repository": "postgres", "tag": "16.15-alpine@sha256:aaaa"}}},
        "openbao": {
            "database": {"schemaJob": {"image": {"repository": "postgres", "tag": "16.15-alpine@sha256:aaaa"}}}
        },
    }
    baseline_values = {
        "openbao": {"database": {"schemaJob": {"image": {"repository": "postgres", "tag": "16-alpine@sha256:bbbb"}}}},
    }

    new_text, updated_headings = cdb.fix_changes_heading_app_versions(
        text, tmp_path, deps, target_values, deps, baseline_values, upgrade_docs_baseline=None
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


def test_fix_values_delta_heading_app_versions_corrects_wrong_name_and_new_dependency_wording(cdb):
    """Real bug, real doc: -values-deltas.md's own "## mi ..." section
    heading has the SAME stale wording AND the SAME wrong (bare "mi",
    not the row's own "mi-data (MI-data exports)") name problem as
    -upgrade.md's own Changes heading did — values-deltas.md has no
    "Component versions" table of its own, so its row data (and the
    authoritative display name) can only come from -upgrade.md's."""
    values_deltas_text = (
        "# Values deltas — PodiumD 4.9.0 → 4.9.1\n\n"
        "## mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)\n\n"
        "- Key `mi.transfer.noEpsv` (optional) added.\n"
    )
    deps = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = cdb.fix_values_delta_heading_app_versions(
        MI_UPGRADE_DOC_TEXT, values_deltas_text, None, deps, target_values, [], {}, upgrade_docs_baseline=None
    )

    assert updated_headings == ["mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)"]
    assert "## mi-data (MI-data exports) 2.90.0 (new) (chart 1.1.0, unchanged)" in new_text
    assert "- Key `mi.transfer.noEpsv` (optional) added." in new_text  # body left as-is


def test_fix_values_delta_heading_app_versions_already_correct_heading_untouched(cdb):
    values_deltas_text = (
        "# Values deltas — PodiumD 4.9.0 → 4.9.1\n\n"
        "## mi-data (MI-data exports) 2.90.0 (new) (chart 1.1.0, unchanged)\n\n"
        "- Key `mi.transfer.noEpsv` (optional) added.\n"
    )
    deps = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = cdb.fix_values_delta_heading_app_versions(
        MI_UPGRADE_DOC_TEXT, values_deltas_text, None, deps, target_values, [], {}, upgrade_docs_baseline=None
    )

    assert updated_headings == []
    assert new_text == values_deltas_text


def test_fix_values_delta_heading_app_versions_corrects_stale_sidecar_heading(cdb):
    """Confirms the shared _fix_heading_app_versions/_resolved_rows_by_
    values_key fix ALSO closes this exact gap for -values-deltas.md's
    own "## ..." section headings, not just -upgrade.md's "### ..."
    ones — both callers share the same core, so the fix landing there
    fixes both docs at once (verified directly here, not assumed)."""
    redis_upgrade_doc_text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis | 8.10.1 (new) | - | - |\n"
    )
    values_deltas_text = (
        "# Values deltas — PodiumD 4.9.0 → 4.9.1\n\n## redis 8.0 → 8.10.1\n\n- `global.images.redis` added.\n"
    )
    deps = []
    target_values = {"global": {"images": {"redis": {"repository": "redis", "tag": "8.10.1@sha256:" + "a" * 64}}}}

    new_text, updated_headings = cdb.fix_values_delta_heading_app_versions(
        redis_upgrade_doc_text, values_deltas_text, None, deps, target_values, [], {}, upgrade_docs_baseline=None
    )

    assert updated_headings == ["redis 8.0 → 8.10.1"]
    assert "## redis 8.10.1 (new)" in new_text
    assert "- `global.images.redis` added." in new_text  # body left as-is


def test_fix_values_delta_heading_app_versions_bare_hand_written_heading_never_touched(cdb):
    """Real bug found live: values-deltas.md's own bare "## zaakbrug"
    and free-form "## Breaking — Frank!Gateway (only when
    `frankgateway.enabled: true`)" section headings got clobbered by a
    first version of this fix — neither shows any recognizable version
    marker at all (changes_heading_has_app_version), so neither was
    ever a "wrong wording" case to begin with; both must be left
    completely untouched even though they resolve to a real "dep"
    identity with a resolvable target app version."""
    values_deltas_text = (
        "# Values deltas — PodiumD 4.9.0 → 4.9.1\n\n## mi\n\nFree-form prose, no version marker at all.\n"
    )
    deps = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = cdb.fix_values_delta_heading_app_versions(
        MI_UPGRADE_DOC_TEXT, values_deltas_text, None, deps, target_values, [], {}, upgrade_docs_baseline=None
    )

    assert updated_headings == []
    assert new_text == values_deltas_text


def test_fix_values_delta_heading_app_versions_no_upgrade_doc_is_a_noop(cdb):
    """No -upgrade.md at all (upgrade_doc_text == "") — nothing to
    resolve the row data against, so no heading is ever touched, never
    an error."""
    values_deltas_text = (
        "# Values deltas — PodiumD 4.9.0 → 4.9.1\n\n"
        "## mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)\n\n"
        "- Key `mi.transfer.noEpsv` (optional) added.\n"
    )
    deps = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    target_values = {"mi": {"image": {"repository": "azure-cli", "tag": "2.90.0@sha256:" + "a" * 64}}}

    new_text, updated_headings = cdb.fix_values_delta_heading_app_versions(
        "", values_deltas_text, None, deps, target_values, [], {}, upgrade_docs_baseline=None
    )

    assert updated_headings == []
    assert new_text == values_deltas_text
