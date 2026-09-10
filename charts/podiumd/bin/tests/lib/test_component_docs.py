"""lib.component_docs — existing_doc_baselines, create_missing_docs,
baseline_doc_paths, images_manifest_path: the standard-doc-set scan/
create/path helpers shared by create-doc-version and fix-doc-consistency.
The per-component doc-rewrite helpers (fix_component_version_table and
friends) are exercised through update-component-version/update-image-
version's own test suites instead, against realistic doc fixtures."""


# --- ensure_images_manifest_changes_header ---

def test_ensure_images_manifest_changes_header_creates_missing_header(libcomponentdocs):
    """Regression test (real bug, real doc): a file that has lost its
    "# Changes:" header (or never had one) previously stayed that way
    forever — insert_images_manifest_header_item is a documented no-op
    when no header exists at all, so no amount of re-running fix-doc-
    consistency could ever add one back. Real case: images-4.9.1.yaml
    gained 5 real entries this session (redis, 3 openbao sidecars, zac's
    otel sidecar), each with a correct own "#"/"#   sidecar:" comment,
    but none of them ever got a "# Changes:" list item, because the
    header itself was simply missing and nothing ever created it."""
    lines = (
        "# Baseline: podiumd 4.9.0. Re-verify before release.\n"
        "#\n"
        "# Images new or changed in podiumd 4.9.1 vs 4.9.0.\n"
        "#\n"
        "# See docs/_UPGRADE_PATHS/4.9.0-to-4.9.1-upgrade.md for the operator upgrade notes.\n"
        "#\n"
        "# redis 8.0 -> 8.0\n"
        "- name: redis\n"
        "  url: redis\n"
    ).splitlines(keepends=True)

    libcomponentdocs.ensure_images_manifest_changes_header(lines)

    text = "".join(lines)
    assert "# Images new or changed in podiumd 4.9.1 vs 4.9.0.\n#\n# Changes:\n#\n" in text
    assert "# See docs/_UPGRADE_PATHS" in text  # rest of the header preserved


def test_ensure_images_manifest_changes_header_noop_when_bare_header_exists(libcomponentdocs):
    lines = (
        "# Images new or changed in podiumd 4.9.1 vs 4.9.0.\n"
        "#\n"
        "# Changes:\n"
        "#   1. redis 8.0 -> 8.0.\n"
    ).splitlines(keepends=True)
    original = list(lines)

    libcomponentdocs.ensure_images_manifest_changes_header(lines)

    assert lines == original


def test_ensure_images_manifest_changes_header_noop_when_counted_header_exists(libcomponentdocs):
    lines = (
        "# Images new or changed in podiumd 4.9.1 vs 4.9.0.\n"
        "#\n"
        "# One change:\n"
        "#   1. redis 8.0 -> 8.0.\n"
    ).splitlines(keepends=True)
    original = list(lines)

    libcomponentdocs.ensure_images_manifest_changes_header(lines)

    assert lines == original


def test_ensure_images_manifest_changes_header_noop_when_no_intro_anchor_either(libcomponentdocs):
    """Defensive fallback: a manifest with no recognizable intro line at
    all (never produced by anything in this codebase) must never crash
    — silently does nothing, same as before this fix existed."""
    lines = (
        "# redis 8.0 -> 8.0\n"
        "- name: redis\n"
        "  url: redis\n"
    ).splitlines(keepends=True)
    original = list(lines)

    libcomponentdocs.ensure_images_manifest_changes_header(lines)

    assert lines == original


# --- renumber_images_manifest_changes_items ---

def test_renumber_images_manifest_changes_items_fixes_a_gap(libcomponentdocs):
    """A gap left by a human hand-removing an item's own block without
    renumbering everything after it — real case that surfaced this."""
    lines = (
        "# Changes:\n"
        "#   1. zac 5.0.2 -> 5.4.3.\n"
        "#   3. openformulieren 3.4.10 -> 3.5.6.\n"
    ).splitlines(keepends=True)
    changed = libcomponentdocs.renumber_images_manifest_changes_items(lines)
    assert changed is True
    assert lines[1] == "#   1. zac 5.0.2 -> 5.4.3.\n"
    assert lines[2] == "#   2. openformulieren 3.4.10 -> 3.5.6.\n"


def test_renumber_images_manifest_changes_items_already_correct_is_a_noop(libcomponentdocs):
    lines = (
        "# Changes:\n"
        "#   1. zac 5.0.2 -> 5.4.3.\n"
        "#   2. openformulieren 3.4.10 -> 3.5.6.\n"
    ).splitlines(keepends=True)
    original = list(lines)
    changed = libcomponentdocs.renumber_images_manifest_changes_items(lines)
    assert changed is False
    assert lines == original


def test_renumber_images_manifest_changes_items_updates_count_word(libcomponentdocs):
    """A gap fix that changes the item COUNT (not just individual
    numbers) must also update the header's own leading count word."""
    lines = (
        "# Three changes:\n"
        "#   1. zac 5.0.2 -> 5.4.3.\n"
        "#   4. openformulieren 3.4.10 -> 3.5.6.\n"
    ).splitlines(keepends=True)
    changed = libcomponentdocs.renumber_images_manifest_changes_items(lines)
    assert changed is True
    assert lines[0] == "# Two changes:\n"
    assert lines[2] == "#   2. openformulieren 3.4.10 -> 3.5.6.\n"


def test_renumber_images_manifest_changes_items_no_header_is_a_noop(libcomponentdocs):
    lines = ["some: yaml\n"]
    assert libcomponentdocs.renumber_images_manifest_changes_items(lines) is False


# --- images_manifest_order_key ---

def test_images_manifest_order_key_bare_string_unaffected_by_values(libcomponentdocs):
    """A bare STRING values_key (the historical shape — top-level key
    only) keeps the exact prior (index, is_sidecar) behavior, even when
    `values` is given — it's only ever deepened when the caller passes
    a full path TUPLE instead."""
    key_order = ["global", "zac"]
    values = {"global": {"images": {"nginx": {}, "curl": {}}}, "zac": {}}
    assert libcomponentdocs.images_manifest_order_key(key_order, "global", False, values) == (0, 0)
    assert libcomponentdocs.images_manifest_order_key(key_order, "global", True, values) == (0, 1)


def test_images_manifest_order_key_path_tuple_resolves_full_nested_position(libcomponentdocs):
    """Regression test: given a full values-tree path TUPLE (not just
    its own top-level key string) and `values`, this resolves the SAME
    real redis/nginx/curl/busybox sub-order the other two sort-key
    functions already do — the shared lib.upgradedoc.values_tree_
    position primitive, not a fourth, independent implementation."""
    key_order = ["global"]
    values = {"global": {"images": {
        "nginx": {}, "curl": {}, "busybox": {}, "redis": {},
    }}}
    keys = [
        libcomponentdocs.images_manifest_order_key(key_order, ("global", "images", name), True, values)
        for name in ("nginx", "curl", "busybox", "redis")
    ]
    assert keys == sorted(keys)
    assert len(set(keys)) == 4


# --- insert_images_manifest_header_item ---

def test_insert_images_manifest_header_item_at_correct_position(libcomponentdocs):
    lines = (
        "# Changes:\n"
        "#   1. openformulieren 3.4.10 -> 3.5.6.\n"
    ).splitlines(keepends=True)
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
            {"name": "openformulieren", "version": "1.12.0"}]
    key_order = ["zac", "openformulieren"]
    libcomponentdocs.insert_images_manifest_header_item(
        lines, deps, key_order, (0, 0), "zac 5.0.2 -> 5.4.3.")
    assert lines == [
        "# Changes:\n",
        "#   1. zac 5.0.2 -> 5.4.3.\n",
        "#   2. openformulieren 3.4.10 -> 3.5.6.\n",
    ]


def test_insert_images_manifest_header_item_fixes_a_preexisting_gap(libcomponentdocs):
    """Inserting a new item must not just shift each EXISTING item's own
    (possibly already-wrong) number by +1 — it must leave the WHOLE list
    gapless 1..N, fixing any pre-existing drift as a side effect (see
    renumber_images_manifest_changes_items). Real bug: the old relative-
    shift logic would have turned "1, 3" (gap at 2) into "1, 2, 4" here
    (still missing "3") instead of the correct "1, 2, 3"."""
    lines = (
        "# Changes:\n"
        "#   1. openzaak 1.27.4 -> 1.29.3.\n"
        "#   3. zgw-office-addin v0.9.313 -> 0.11.0.\n"
    ).splitlines(keepends=True)
    deps = [{"name": "openzaak", "version": "1.14.2"},
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
            {"name": "zgw-office-addin", "version": "0.0.89"}]
    key_order = ["openzaak", "zac", "zgw-office-addin"]
    libcomponentdocs.insert_images_manifest_header_item(
        lines, deps, key_order, (1, 0), "zac 5.0.2 -> 5.4.3.")
    assert lines == [
        "# Changes:\n",
        "#   1. openzaak 1.27.4 -> 1.29.3.\n",
        "#   2. zac 5.0.2 -> 5.4.3.\n",
        "#   3. zgw-office-addin v0.9.313 -> 0.11.0.\n",
    ]


# --- images_manifest_path ---

def test_images_manifest_path(libcomponentdocs, tmp_path):
    assert libcomponentdocs.images_manifest_path(tmp_path, "4.9.0") == tmp_path / "images-4.9.0.yaml"


# --- baseline_doc_paths ---

def test_baseline_doc_paths_none_baseline_returns_none_none(libcomponentdocs, tmp_path):
    assert libcomponentdocs.baseline_doc_paths(tmp_path, None, "4.9.0") == (None, None)


def test_baseline_doc_paths_missing_upgrade_doc_returns_none_none(libcomponentdocs, tmp_path):
    assert libcomponentdocs.baseline_doc_paths(tmp_path, "4.8.5", "4.9.0") == (None, None)


def test_baseline_doc_paths_finds_both(libcomponentdocs, tmp_path):
    (tmp_path / "4.8.5-to-4.9.0-upgrade.md").write_text("x", encoding="utf-8")
    (tmp_path / "4.8.5-to-4.9.0-values-deltas.md").write_text("x", encoding="utf-8")
    upgrade_path, values_deltas_path = libcomponentdocs.baseline_doc_paths(tmp_path, "4.8.5", "4.9.0")
    assert upgrade_path == tmp_path / "4.8.5-to-4.9.0-upgrade.md"
    assert values_deltas_path == tmp_path / "4.8.5-to-4.9.0-values-deltas.md"


def test_baseline_doc_paths_missing_values_deltas_is_none(libcomponentdocs, tmp_path):
    (tmp_path / "4.8.5-to-4.9.0-upgrade.md").write_text("x", encoding="utf-8")
    upgrade_path, values_deltas_path = libcomponentdocs.baseline_doc_paths(tmp_path, "4.8.5", "4.9.0")
    assert upgrade_path == tmp_path / "4.8.5-to-4.9.0-upgrade.md"
    assert values_deltas_path is None


# --- existing_doc_baselines ---

def test_existing_doc_baselines_groups_by_suffix(libcomponentdocs, tmp_path):
    (tmp_path / "4.8.2-to-4.9.0-upgrade.md").write_text("x", encoding="utf-8")
    (tmp_path / "4.8.2-to-4.9.0-values-deltas.md").write_text("x", encoding="utf-8")
    (tmp_path / "4.7.8-to-4.8.0-upgrade.md").write_text("x", encoding="utf-8")  # different target, ignored

    by_suffix = libcomponentdocs.existing_doc_baselines(tmp_path, "4.9.0")

    assert set(by_suffix.keys()) == {"upgrade", "values-deltas"}
    assert by_suffix["upgrade"] == [("4.8.2", tmp_path / "4.8.2-to-4.9.0-upgrade.md")]


def test_existing_doc_baselines_empty_when_no_match(libcomponentdocs, tmp_path):
    (tmp_path / "4.7.8-to-4.8.0-upgrade.md").write_text("x", encoding="utf-8")
    assert libcomponentdocs.existing_doc_baselines(tmp_path, "4.9.0") == {}


def test_existing_doc_baselines_multiple_sources_for_one_suffix(libcomponentdocs, tmp_path):
    """Two different baselines both claiming the same suffix for this
    target — the exact shape create-doc-version's mismatch refusal and
    fix-doc-consistency's collision refusal both key off."""
    (tmp_path / "4.8.2-to-4.9.0-upgrade.md").write_text("x", encoding="utf-8")
    (tmp_path / "4.8.3-to-4.9.0-upgrade.md").write_text("x", encoding="utf-8")
    by_suffix = libcomponentdocs.existing_doc_baselines(tmp_path, "4.9.0")
    assert sorted(by_suffix["upgrade"]) == [
        ("4.8.2", tmp_path / "4.8.2-to-4.9.0-upgrade.md"),
        ("4.8.3", tmp_path / "4.8.3-to-4.9.0-upgrade.md"),
    ]


# --- create_missing_docs ---

def test_create_missing_docs_creates_all_when_none_exist(libcomponentdocs, tmp_path):
    doc_dir = tmp_path / "docs"
    images_dir = tmp_path / "images"
    doc_dir.mkdir()
    images_dir.mkdir()

    created = libcomponentdocs.create_missing_docs(doc_dir, images_dir, "4.8.5", "4.9.0")

    assert set(created) == {
        "4.8.5-to-4.9.0-upgrade.md", "4.8.5-to-4.9.0-gemeente-specific.md",
        "4.8.5-to-4.9.0-values-deltas.md", "images-4.9.0.yaml",
    }
    upgrade_text = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "PodiumD 4.8.5 → 4.9.0" in upgrade_text
    images_text = (images_dir / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "Baseline: podiumd 4.8.5." in images_text


def test_create_missing_docs_never_overwrites_existing(libcomponentdocs, tmp_path):
    doc_dir = tmp_path / "docs"
    images_dir = tmp_path / "images"
    doc_dir.mkdir()
    images_dir.mkdir()
    existing = doc_dir / "4.8.5-to-4.9.0-upgrade.md"
    existing.write_text("hand-written content\n", encoding="utf-8")

    created = libcomponentdocs.create_missing_docs(doc_dir, images_dir, "4.8.5", "4.9.0")

    assert "4.8.5-to-4.9.0-upgrade.md" not in created
    assert existing.read_text(encoding="utf-8") == "hand-written content\n"
    assert "4.8.5-to-4.9.0-gemeente-specific.md" in created  # the other two still get created


def test_create_missing_docs_nothing_to_do_when_all_exist(libcomponentdocs, tmp_path):
    doc_dir = tmp_path / "docs"
    images_dir = tmp_path / "images"
    doc_dir.mkdir()
    images_dir.mkdir()
    for suffix in libcomponentdocs.STANDARD_SUFFIXES:
        (doc_dir / f"4.8.5-to-4.9.0-{suffix}.md").write_text("x", encoding="utf-8")
    (images_dir / "images-4.9.0.yaml").write_text("x", encoding="utf-8")

    assert libcomponentdocs.create_missing_docs(doc_dir, images_dir, "4.8.5", "4.9.0") == []


# --- values_delta_section_heading ---

def test_values_delta_section_heading_app_changed_chart_unchanged(libcomponentdocs):
    heading = libcomponentdocs.values_delta_section_heading("zac", "5.0.2", "5.4.3", "1.0.297", "1.0.297")
    assert heading == "## zac 5.0.2 → 5.4.3 (chart 1.0.297, unchanged)\n"


def test_values_delta_section_heading_native_component_omits_chart_clause(libcomponentdocs):
    heading = libcomponentdocs.values_delta_section_heading("frankgateway", "100", "104", None, "-")
    assert heading == "## frankgateway 100 → 104\n"


def test_values_delta_section_heading_unresolved_app_version_with_chart(libcomponentdocs):
    heading = libcomponentdocs.values_delta_section_heading("redis-operator", None, None, "0.26.1", "0.27.0")
    assert heading == ("## redis-operator chart 0.26.1 → 0.27.0 — TODO: describe this component's changes; "
                        "its app version could not be resolved automatically.\n")


# --- find_values_delta_section / insert_values_delta_section / append_values_delta_section_body ---

DEPS = [
    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
    {"name": "openformulieren", "version": "1.12.0"},
]


# --- resolve_component_own_version_change / add_missing_component_rows ---

def test_resolve_component_own_version_change_true_when_both_unchanged(libcomponentdocs):
    """Regression test: zac gaining a brand-new sidecar of its own (not
    modeled here — this only checks the OWN-version resolution) with
    its own chart+app both unchanged must resolve unchanged=True."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"tag": "5.4.4@sha256:aaaa"}}}
    resolved = libcomponentdocs.resolve_component_own_version_change("zac", deps, deps, values, values, None, [])
    assert resolved is not None
    *_rest, unchanged = resolved
    assert unchanged is True


def test_resolve_component_own_version_change_false_when_app_changed(libcomponentdocs):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    current = {"zac": {"image": {"tag": "5.4.4@sha256:bbbb"}}}
    baseline = {"zac": {"image": {"tag": "5.0.2@sha256:aaaa"}}}
    resolved = libcomponentdocs.resolve_component_own_version_change("zac", deps, deps, current, baseline, None, [])
    _dep, _chart_name, _old_chart, _new_chart, old_app, new_app, unchanged = resolved
    assert (old_app, new_app, unchanged) == ("5.0.2", "5.4.4", False)


def test_resolve_component_own_version_change_false_when_chart_changed(libcomponentdocs):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}]
    values = {"zac": {"image": {"tag": "5.4.4@sha256:aaaa"}}}
    resolved = libcomponentdocs.resolve_component_own_version_change(
        "zac", deps, baseline_deps, values, values, None, [])
    *_rest, unchanged = resolved
    assert unchanged is False


def test_resolve_component_own_version_change_native_component_ignores_chart(libcomponentdocs):
    """frankgateway (see lib.chart.NATIVE_COMPONENTS) has no chart at
    all — new_chart == "-" always counts as "chart unchanged", so the
    decision hinges entirely on the app version."""
    values = {"frankgateway": {"image": {"tag": "104@sha256:aaaa"}}}
    resolved = libcomponentdocs.resolve_component_own_version_change(
        "frankgateway", [], [], values, values, None, [])
    *_rest, unchanged = resolved
    assert unchanged is True


def test_resolve_component_own_version_change_none_for_unmatched_key(libcomponentdocs):
    resolved = libcomponentdocs.resolve_component_own_version_change("ghost", [], [], {}, {}, None, [])
    assert resolved is None


def test_resolve_component_own_version_change_vendored_subchart_fallback_applies_to_baseline_too(
        libcomponentdocs, tmp_path, monkeypatch):
    """Regression test (real bug, real doc): openbao's own "server.image.
    tag" is deliberately left blank in both baseline and target values.yaml
    (see lib.chart.COMPONENT_IMAGE_PATHS["openbao"]'s own comment) — its
    real app version only ever resolves via the vendored-.tgz subchart_
    app_version fallback (see lib.upgradedoc.actual_app_version), which
    the OLD code never even attempted for the baseline side. Its chart
    version (0.28.4) is unchanged this hop, so the exact same vendored
    .tgz backs both sides — old_app must resolve to the SAME "v2.5.5" as
    new_app, not None, and unchanged must be True, exactly like any other
    component whose own version genuinely didn't change (e.g. zac). Before
    this fix, old_app stayed None (wrongly rendering "(new)") purely
    because of this resolution gap, not because openbao's version
    actually changed."""
    monkeypatch.setitem(libcomponentdocs.image_paths_for.__globals__["COMPONENT_IMAGE_PATHS"],
                         "openbao", ["server.image"])
    import io
    import tarfile

    import yaml as pyyaml
    charts_dir = tmp_path / "charts"
    charts_dir.mkdir()
    tgz_path = charts_dir / "openbao-0.28.4.tgz"
    with tarfile.open(tgz_path, "w:gz") as tar:
        for filename, content in (
                ("openbao/values.yaml", {"server": {"image": {"tag": ""}}}),
                ("openbao/Chart.yaml", {"apiVersion": "v2", "version": "0.28.4", "appVersion": "v2.5.5"})):
            data = pyyaml.safe_dump(content).encode("utf-8")
            info = tarfile.TarInfo(name=filename)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    dep = {"name": "openbao", "version": "0.28.4"}
    values = {"openbao": {"server": {"image": {"repository": "quay.io/openbao/openbao", "tag": ""}}}}

    resolved = libcomponentdocs.resolve_component_own_version_change(
        "openbao", [dep], [dep], values, values, tmp_path, [])
    _dep, _chart_name, old_chart, new_chart, old_app, new_app, unchanged = resolved
    assert (old_chart, new_chart, old_app, new_app, unchanged) == ("0.28.4", "0.28.4", "v2.5.5", "v2.5.5", True)


def test_resolve_component_own_version_change_vendored_fallback_never_used_when_chart_changed(
        libcomponentdocs, tmp_path, monkeypatch):
    """The vendored-subchart fallback above must never fire when the
    chart version itself changed — the current chart_dir's vendored .tgz
    (at the TARGET's chart version) is only a valid stand-in for the
    baseline's own app version when it's the SAME .tgz backing both
    sides. A real baseline-side chart bump must stay unresolved (old_app
    None) rather than silently reusing the wrong file's appVersion."""
    monkeypatch.setitem(libcomponentdocs.image_paths_for.__globals__["COMPONENT_IMAGE_PATHS"],
                         "openbao", ["server.image"])
    import io
    import tarfile

    import yaml as pyyaml
    charts_dir = tmp_path / "charts"
    charts_dir.mkdir()
    tgz_path = charts_dir / "openbao-0.29.0.tgz"
    with tarfile.open(tgz_path, "w:gz") as tar:
        for filename, content in (
                ("openbao/values.yaml", {"server": {"image": {"tag": ""}}}),
                ("openbao/Chart.yaml", {"apiVersion": "v2", "version": "0.29.0", "appVersion": "v2.6.0"})):
            data = pyyaml.safe_dump(content).encode("utf-8")
            info = tarfile.TarInfo(name=filename)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    dep = {"name": "openbao", "version": "0.29.0"}
    baseline_dep = {"name": "openbao", "version": "0.28.4"}
    values = {"openbao": {"server": {"image": {"repository": "quay.io/openbao/openbao", "tag": ""}}}}

    resolved = libcomponentdocs.resolve_component_own_version_change(
        "openbao", [dep], [baseline_dep], values, values, tmp_path, [])
    _dep, _chart_name, old_chart, new_chart, old_app, new_app, unchanged = resolved
    assert (old_chart, new_chart, old_app, new_app, unchanged) == ("0.28.4", "0.29.0", None, "v2.6.0", False)


def test_add_missing_component_rows_skips_own_unchanged_component(libcomponentdocs, tmp_path):
    """Regression test: zac's subtree gains a brand-new sidecar of its
    own (not modeled here directly — actual_changed_keys already
    contains "zac" for whatever reason, matching what compute_changed_
    components would report), but zac's OWN chart+app are both
    unchanged — no row/section should be added for zac itself; that
    sidecar already gets its own separate row via add_missing_sidecar_
    rows. Real case: zac gaining opentelemetry-collector-contrib,
    openbao gaining three brand-new sidecars — neither's own version
    moved, so a redundant "(unchanged)" row for the owner was pure
    noise."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"tag": "5.4.4@sha256:aaaa"}}}
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n\n"
    )
    new_text, added_names = libcomponentdocs.add_missing_component_rows(
        text, tmp_path, deps, values, deps, values, {"zac"}, "4.9.1")
    assert added_names == []
    assert "zac" not in new_text


def test_add_missing_component_rows_still_adds_a_real_bump(libcomponentdocs, tmp_path):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    current_values = {"zac": {"image": {"tag": "5.4.4@sha256:bbbb"}}}
    baseline_values = {"zac": {"image": {"tag": "5.0.2@sha256:aaaa"}}}
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n\n"
    )
    new_text, added_names = libcomponentdocs.add_missing_component_rows(
        text, tmp_path, deps, current_values, deps, baseline_values, {"zac"}, "4.9.1")
    assert added_names == ["zac"]
    assert "| zac | 5.0.2 → 5.4.4 | 1.0.297 (unchanged) | - |" in new_text


def test_find_values_delta_section_matches_hand_written_heading(libcomponentdocs):
    text = "# Values deltas\n\n## KISS 2.2.4 → 3.0.0 — required edits\n\nSome prose.\n"
    section = libcomponentdocs.find_values_delta_section(text, "kiss", [{"name": "kiss", "version": "3.0.0"}])
    assert section is not None
    assert section["heading"] == "KISS 2.2.4 → 3.0.0 — required edits"


def test_find_values_delta_section_no_match_returns_none(libcomponentdocs):
    text = "# Values deltas\n\n## zac 5.0.2 → 5.4.3\n\n- Key `zac.a` was added.\n"
    assert libcomponentdocs.find_values_delta_section(text, "openformulieren", DEPS) is None


def test_insert_values_delta_section_positions_by_values_yaml_order(libcomponentdocs):
    text = "# Values deltas\n\n## openformulieren 3.4.10 → 3.5.6\n\n- Key `a` was added.\n"
    new_text = libcomponentdocs.insert_values_delta_section(
        text, "zac", "## zac 5.0.2 → 5.4.3\n", ["- Key `zac.a` was added.\n"], DEPS,
        {"zac": {}, "openformulieren": {}})
    assert new_text.index("## zac") < new_text.index("## openformulieren")


def test_append_values_delta_section_body_adds_after_existing_content(libcomponentdocs):
    text = "# Values deltas\n\n## KISS — required edits\n\nSome prose.\n\n## PABC\n\nOther prose.\n"
    sections = libcomponentdocs.find_values_delta_section(text, "kiss", [{"name": "kiss", "version": "1.0.0"}])
    new_text = libcomponentdocs.append_values_delta_section_body(text, sections, ["- Key `kiss.a` was added.\n"])
    assert "Some prose.\n\n- Key `kiss.a` was added.\n\n## PABC" in new_text


def test_remove_values_delta_section_never_removes_multi_identity_heading(libcomponentdocs):
    """A hand-written section covering several components at once must
    never be deleted just because one of them reset to baseline."""
    text = "# Values deltas\n\n## ZAC and ZGW Office Add-in — no changes\n\nProse.\n"
    deps = DEPS + [{"name": "zgw-office-addin", "version": "0.0.89"}]
    new_text, removed = libcomponentdocs.remove_values_delta_section(text, "zac", deps)
    assert removed is False
    assert new_text == text


# --- sync_values_delta_sections ---

def test_sync_values_delta_sections_skips_key_with_no_schema_change(libcomponentdocs, tmp_path):
    """A pure app/chart version bump — no describe_key_changes lines at
    all — gets no brand-new section: a heading with nothing under it is
    worse than no heading (values-deltas.md exists for gemeente-
    actionable schema changes, not a general changelog)."""
    text = "# Values deltas\n\nNo gemeente podiumd.yml changes are required for this hop.\n"
    values = {"zac": {"image": {}}}
    new_text, created, updated = libcomponentdocs.sync_values_delta_sections(
        text, tmp_path, DEPS, values, DEPS, values, {"zac"})
    assert created == []
    assert updated == []
    assert new_text == text


def test_sync_values_delta_sections_creates_section_only_when_key_lines_exist(libcomponentdocs, tmp_path):
    text = "# Values deltas\n\nNo gemeente podiumd.yml changes are required for this hop.\n"
    baseline_values = {"zac": {"image": {}}}
    target_values = {"zac": {"image": {}, "newFeature": True}}
    new_text, created, updated = libcomponentdocs.sync_values_delta_sections(
        text, tmp_path, DEPS, target_values, DEPS, baseline_values, {"zac"})
    assert created == ["zac"]
    assert "## zac" in new_text
    assert "- Key `zac.newFeature` was added.\n" in new_text


# --- prune_empty_values_delta_sections ---

def test_prune_empty_values_delta_sections_removes_a_heading_with_nothing_under_it(libcomponentdocs):
    text = (
        "# Values deltas\n\n"
        "## zac 5.0.2 → 5.4.3 (chart 1.0.297, unchanged)\n\n"
        "## openformulieren 3.4.10 → 3.5.6\n\n"
        "- Key `openformulieren.a` was added.\n"
    )
    new_text, removed = libcomponentdocs.prune_empty_values_delta_sections(text)
    assert removed == ["zac 5.0.2 → 5.4.3 (chart 1.0.297, unchanged)"]
    assert "## zac" not in new_text
    assert "## openformulieren" in new_text
    assert "- Key `openformulieren.a` was added.\n" in new_text


def test_prune_empty_values_delta_sections_never_removes_hand_written_prose(libcomponentdocs):
    text = "# Values deltas\n\n## KISS — required edits\n\nSome real prose here.\n"
    new_text, removed = libcomponentdocs.prune_empty_values_delta_sections(text)
    assert removed == []
    assert new_text == text


def test_prune_empty_values_delta_sections_no_sections_is_unchanged(libcomponentdocs):
    text = "# Values deltas\n\nTODO.\n"
    new_text, removed = libcomponentdocs.prune_empty_values_delta_sections(text)
    assert removed == []
    assert new_text == text


def test_images_stub_template_has_a_changes_header(libcomponentdocs):
    """A fresh images-manifest stub must include a "# Changes:" anchor
    line, not just the bare "[]" YAML placeholder — without it, find_
    images_manifest_changes_header finds nothing, so add_missing_images_
    manifest_entries (and update_images_manifest) can add new entries to
    the body but never a matching numbered item above them, silently
    leaving the "# Changes:" section looking like the literal "[]" it
    started as (real symptom reported live)."""
    text = libcomponentdocs.IMAGES_STUB_TEMPLATE.format(upgrade_docs_baseline="4.8.5", target="4.9.0")
    lines = text.splitlines(keepends=True)
    header_idx, header_has_count = libcomponentdocs.find_images_manifest_changes_header(lines)
    assert header_idx is not None
    assert header_has_count is False
