"""lib.component_docs — existing_doc_baselines, create_missing_docs,
baseline_doc_paths, images_manifest_path: the standard-doc-set scan/
create/path helpers shared by create-doc-version and fix-doc-consistency.
The per-component doc-rewrite helpers (fix_component_version_table and
friends) are exercised through update-component-version/update-image-
version's own test suites instead, against realistic doc fixtures."""


# --- ensure_images_manifest_changes_header ---


def test_ensure_images_manifest_changes_header_creates_missing_header(libcomponentdocsheader):
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

    libcomponentdocsheader.ensure_images_manifest_changes_header(lines)

    text = "".join(lines)
    assert "# Images new or changed in podiumd 4.9.1 vs 4.9.0.\n#\n# Changes:\n#\n" in text
    assert "# See docs/_UPGRADE_PATHS" in text  # rest of the header preserved


def test_ensure_images_manifest_changes_header_noop_when_bare_header_exists(libcomponentdocsheader):
    lines = (
        "# Images new or changed in podiumd 4.9.1 vs 4.9.0.\n#\n# Changes:\n#   1. redis 8.0 -> 8.0.\n"
    ).splitlines(keepends=True)
    original = list(lines)

    libcomponentdocsheader.ensure_images_manifest_changes_header(lines)

    assert lines == original


def test_ensure_images_manifest_changes_header_noop_when_counted_header_exists(libcomponentdocsheader):
    lines = (
        "# Images new or changed in podiumd 4.9.1 vs 4.9.0.\n#\n# One change:\n#   1. redis 8.0 -> 8.0.\n"
    ).splitlines(keepends=True)
    original = list(lines)

    libcomponentdocsheader.ensure_images_manifest_changes_header(lines)

    assert lines == original


def test_ensure_images_manifest_changes_header_noop_when_no_intro_anchor_either(libcomponentdocsheader):
    """Defensive fallback: a manifest with no recognizable intro line at
    all (never produced by anything in this codebase) must never crash
    — silently does nothing, same as before this fix existed."""
    lines = ("# redis 8.0 -> 8.0\n- name: redis\n  url: redis\n").splitlines(keepends=True)
    original = list(lines)

    libcomponentdocsheader.ensure_images_manifest_changes_header(lines)

    assert lines == original


# --- renumber_images_manifest_changes_items ---


def test_renumber_images_manifest_changes_items_fixes_a_gap(libcomponentdocsheader):
    """A gap left by a human hand-removing an item's own block without
    renumbering everything after it — real case that surfaced this."""
    lines = ("# Changes:\n#   1. zac 5.0.2 -> 5.4.3.\n#   3. openformulieren 3.4.10 -> 3.5.6.\n").splitlines(
        keepends=True
    )
    changed = libcomponentdocsheader.renumber_images_manifest_changes_items(lines)
    assert changed is True
    assert lines[1] == "#   1. zac 5.0.2 -> 5.4.3.\n"
    assert lines[2] == "#   2. openformulieren 3.4.10 -> 3.5.6.\n"


def test_renumber_images_manifest_changes_items_already_correct_is_a_noop(libcomponentdocsheader):
    lines = ("# Changes:\n#   1. zac 5.0.2 -> 5.4.3.\n#   2. openformulieren 3.4.10 -> 3.5.6.\n").splitlines(
        keepends=True
    )
    original = list(lines)
    changed = libcomponentdocsheader.renumber_images_manifest_changes_items(lines)
    assert changed is False
    assert lines == original


def test_renumber_images_manifest_changes_items_updates_count_word(libcomponentdocsheader):
    """A gap fix that changes the item COUNT (not just individual
    numbers) must also update the header's own leading count word."""
    lines = ("# Three changes:\n#   1. zac 5.0.2 -> 5.4.3.\n#   4. openformulieren 3.4.10 -> 3.5.6.\n").splitlines(
        keepends=True
    )
    changed = libcomponentdocsheader.renumber_images_manifest_changes_items(lines)
    assert changed is True
    assert lines[0] == "# Two changes:\n"
    assert lines[2] == "#   2. openformulieren 3.4.10 -> 3.5.6.\n"


def test_renumber_images_manifest_changes_items_no_header_is_a_noop(libcomponentdocsheader):
    lines = ["some: yaml\n"]
    assert libcomponentdocsheader.renumber_images_manifest_changes_items(lines) is False


# --- images_manifest_order_key ---


def test_images_manifest_order_key_bare_string_unaffected_by_values(libcomponentdocsheader):
    """A bare STRING values_key (the historical shape — top-level key
    only) keeps the exact prior (index, is_sidecar) behavior, even when
    `values` is given — it's only ever deepened when the caller passes
    a full path TUPLE instead."""
    key_order = ["global", "zac"]
    values = {"global": {"images": {"nginx": {}, "curl": {}}}, "zac": {}}
    assert libcomponentdocsheader.images_manifest_order_key(key_order, "global", False, values) == (0, 0)
    assert libcomponentdocsheader.images_manifest_order_key(key_order, "global", True, values) == (
        0,
        1,
    )


def test_images_manifest_order_key_path_tuple_resolves_full_nested_position(libcomponentdocsheader):
    """Regression test: given a full values-tree path TUPLE (not just
    its own top-level key string) and `values`, this resolves the SAME
    real redis/nginx/curl/busybox sub-order the other two sort-key
    functions already do — the shared lib.upgradedoc.values_tree_
    position primitive, not a fourth, independent implementation."""
    key_order = ["global"]
    values = {
        "global": {
            "images": {
                "nginx": {},
                "curl": {},
                "busybox": {},
                "redis": {},
            }
        }
    }
    keys = [
        libcomponentdocsheader.images_manifest_order_key(key_order, ("global", "images", name), True, values)
        for name in ("nginx", "curl", "busybox", "redis")
    ]
    assert keys == sorted(keys)
    assert len(set(keys)) == 4


# --- insert_images_manifest_header_item ---


def test_insert_images_manifest_header_item_at_correct_position(libcomponentdocsheader):
    lines = ("# Changes:\n#   1. openformulieren 3.4.10 -> 3.5.6.\n").splitlines(keepends=True)
    deps = [
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
        {"name": "openformulieren", "version": "1.12.0"},
    ]
    key_order = ["zac", "openformulieren"]
    libcomponentdocsheader.insert_images_manifest_header_item(lines, deps, key_order, (0, 0), "zac 5.0.2 -> 5.4.3.")
    assert lines == [
        "# Changes:\n",
        "#   1. zac 5.0.2 -> 5.4.3.\n",
        "#   2. openformulieren 3.4.10 -> 3.5.6.\n",
    ]


def test_insert_images_manifest_header_item_fixes_a_preexisting_gap(libcomponentdocsheader):
    """Inserting a new item must not just shift each EXISTING item's own
    (possibly already-wrong) number by +1 — it must leave the WHOLE list
    gapless 1..N, fixing any pre-existing drift as a side effect (see
    renumber_images_manifest_changes_items). Real bug: the old relative-
    shift logic would have turned "1, 3" (gap at 2) into "1, 2, 4" here
    (still missing "3") instead of the correct "1, 2, 3"."""
    lines = ("# Changes:\n#   1. openzaak 1.27.4 -> 1.29.3.\n#   3. zgw-office-addin v0.9.313 -> 0.11.0.\n").splitlines(
        keepends=True
    )
    deps = [
        {"name": "openzaak", "version": "1.14.2"},
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
        {"name": "zgw-office-addin", "version": "0.0.89"},
    ]
    key_order = ["openzaak", "zac", "zgw-office-addin"]
    libcomponentdocsheader.insert_images_manifest_header_item(lines, deps, key_order, (1, 0), "zac 5.0.2 -> 5.4.3.")
    assert lines == [
        "# Changes:\n",
        "#   1. openzaak 1.27.4 -> 1.29.3.\n",
        "#   2. zac 5.0.2 -> 5.4.3.\n",
        "#   3. zgw-office-addin v0.9.313 -> 0.11.0.\n",
    ]


# --- images_manifest_path ---


def test_images_manifest_path(libcomponentdocs, libcomponentdocsbaselinedocstubs, tmp_path):
    assert libcomponentdocsbaselinedocstubs.images_manifest_path(tmp_path, "4.9.0") == tmp_path / "images-4.9.0.yaml"


# --- baseline_doc_paths ---


def test_baseline_doc_paths_none_baseline_returns_none_none(
    libcomponentdocs, libcomponentdocsbaselinedocstubs, tmp_path
):
    assert libcomponentdocsbaselinedocstubs.baseline_doc_paths(tmp_path, None, "4.9.0") == (None, None)


def test_baseline_doc_paths_missing_upgrade_doc_returns_none_none(
    libcomponentdocs, libcomponentdocsbaselinedocstubs, tmp_path
):
    assert libcomponentdocsbaselinedocstubs.baseline_doc_paths(tmp_path, "4.8.5", "4.9.0") == (None, None)


def test_baseline_doc_paths_finds_both(libcomponentdocs, libcomponentdocsbaselinedocstubs, tmp_path):
    (tmp_path / "4.8.5-to-4.9.0-upgrade.md").write_text("x", encoding="utf-8")
    (tmp_path / "4.8.5-to-4.9.0-values-deltas.md").write_text("x", encoding="utf-8")
    upgrade_path, values_deltas_path = libcomponentdocsbaselinedocstubs.baseline_doc_paths(tmp_path, "4.8.5", "4.9.0")
    assert upgrade_path == tmp_path / "4.8.5-to-4.9.0-upgrade.md"
    assert values_deltas_path == tmp_path / "4.8.5-to-4.9.0-values-deltas.md"


def test_baseline_doc_paths_missing_values_deltas_is_none(libcomponentdocs, libcomponentdocsbaselinedocstubs, tmp_path):
    (tmp_path / "4.8.5-to-4.9.0-upgrade.md").write_text("x", encoding="utf-8")
    upgrade_path, values_deltas_path = libcomponentdocsbaselinedocstubs.baseline_doc_paths(tmp_path, "4.8.5", "4.9.0")
    assert upgrade_path == tmp_path / "4.8.5-to-4.9.0-upgrade.md"
    assert values_deltas_path is None


# --- existing_doc_baselines ---


def test_existing_doc_baselines_groups_by_suffix(libcomponentdocs, libcomponentdocsbaselinedocstubs, tmp_path):
    (tmp_path / "4.8.2-to-4.9.0-upgrade.md").write_text("x", encoding="utf-8")
    (tmp_path / "4.8.2-to-4.9.0-values-deltas.md").write_text("x", encoding="utf-8")
    (tmp_path / "4.7.8-to-4.8.0-upgrade.md").write_text("x", encoding="utf-8")  # different target, ignored

    by_suffix = libcomponentdocsbaselinedocstubs.existing_doc_baselines(tmp_path, "4.9.0")

    assert set(by_suffix.keys()) == {"upgrade", "values-deltas"}
    assert by_suffix["upgrade"] == [("4.8.2", tmp_path / "4.8.2-to-4.9.0-upgrade.md")]


def test_existing_doc_baselines_empty_when_no_match(libcomponentdocs, libcomponentdocsbaselinedocstubs, tmp_path):
    (tmp_path / "4.7.8-to-4.8.0-upgrade.md").write_text("x", encoding="utf-8")
    assert libcomponentdocsbaselinedocstubs.existing_doc_baselines(tmp_path, "4.9.0") == {}


def test_existing_doc_baselines_multiple_sources_for_one_suffix(
    libcomponentdocs, libcomponentdocsbaselinedocstubs, tmp_path
):
    """Two different baselines both claiming the same suffix for this
    target — the exact shape create-doc-version's mismatch refusal and
    fix-doc-consistency's collision refusal both key off."""
    (tmp_path / "4.8.2-to-4.9.0-upgrade.md").write_text("x", encoding="utf-8")
    (tmp_path / "4.8.3-to-4.9.0-upgrade.md").write_text("x", encoding="utf-8")
    by_suffix = libcomponentdocsbaselinedocstubs.existing_doc_baselines(tmp_path, "4.9.0")
    assert sorted(by_suffix["upgrade"]) == [
        ("4.8.2", tmp_path / "4.8.2-to-4.9.0-upgrade.md"),
        ("4.8.3", tmp_path / "4.8.3-to-4.9.0-upgrade.md"),
    ]


# --- create_missing_docs ---


def test_create_missing_docs_creates_all_when_none_exist(libcomponentdocs, libcomponentdocsbaselinedocstubs, tmp_path):
    doc_dir = tmp_path / "docs"
    images_dir = tmp_path / "images"
    doc_dir.mkdir()
    images_dir.mkdir()

    created = libcomponentdocsbaselinedocstubs.create_missing_docs(doc_dir, images_dir, "4.8.5", "4.9.0")

    assert set(created) == {
        "4.8.5-to-4.9.0-upgrade.md",
        "4.8.5-to-4.9.0-gemeente-specific.md",
        "4.8.5-to-4.9.0-values-deltas.md",
        "images-4.9.0.yaml",
    }
    upgrade_text = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "PodiumD 4.8.5 → 4.9.0" in upgrade_text
    images_text = (images_dir / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "Baseline: podiumd 4.8.5." in images_text


def test_create_missing_docs_never_overwrites_existing(libcomponentdocs, libcomponentdocsbaselinedocstubs, tmp_path):
    doc_dir = tmp_path / "docs"
    images_dir = tmp_path / "images"
    doc_dir.mkdir()
    images_dir.mkdir()
    existing = doc_dir / "4.8.5-to-4.9.0-upgrade.md"
    existing.write_text("hand-written content\n", encoding="utf-8")

    created = libcomponentdocsbaselinedocstubs.create_missing_docs(doc_dir, images_dir, "4.8.5", "4.9.0")

    assert "4.8.5-to-4.9.0-upgrade.md" not in created
    assert existing.read_text(encoding="utf-8") == "hand-written content\n"
    assert "4.8.5-to-4.9.0-gemeente-specific.md" in created  # the other two still get created


def test_create_missing_docs_nothing_to_do_when_all_exist(libcomponentdocs, libcomponentdocsbaselinedocstubs, tmp_path):
    doc_dir = tmp_path / "docs"
    images_dir = tmp_path / "images"
    doc_dir.mkdir()
    images_dir.mkdir()
    for suffix in libcomponentdocsbaselinedocstubs.STANDARD_SUFFIXES:
        (doc_dir / f"4.8.5-to-4.9.0-{suffix}.md").write_text("x", encoding="utf-8")
    (images_dir / "images-4.9.0.yaml").write_text("x", encoding="utf-8")

    assert libcomponentdocsbaselinedocstubs.create_missing_docs(doc_dir, images_dir, "4.8.5", "4.9.0") == []


# --- values_delta_section_heading ---


def test_values_delta_section_heading_app_changed_chart_unchanged(libcomponentdocsdeltas):
    heading = libcomponentdocsdeltas.values_delta_section_heading("zac", "5.0.2", "5.4.3", "1.0.297", "1.0.297")
    assert heading == "## zac 5.0.2 → 5.4.3 (chart 1.0.297, unchanged)\n"


def test_values_delta_section_heading_native_component_omits_chart_clause(libcomponentdocsdeltas):
    heading = libcomponentdocsdeltas.values_delta_section_heading("frankgateway", "100", "104", None, "-")
    assert heading == "## frankgateway 100 → 104\n"


def test_values_delta_section_heading_unresolved_app_version_with_chart(libcomponentdocsdeltas):
    heading = libcomponentdocsdeltas.values_delta_section_heading("redis-operator", None, None, "0.26.1", "0.27.0")
    assert heading == (
        "## redis-operator chart 0.26.1 → 0.27.0 — TODO: describe this component's changes; "
        "its app version could not be resolved automatically.\n"
    )


# --- find_values_delta_section / insert_values_delta_section / append_values_delta_section_body ---

DEPS = [
    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
    {"name": "openformulieren", "version": "1.12.0"},
]


# --- resolve_component_own_version_change / add_missing_component_rows ---


def test_resolve_component_own_version_change_true_when_both_unchanged(libcomponentdocschanges):
    """Regression test: zac gaining a brand-new sidecar of its own (not
    modeled here — this only checks the OWN-version resolution) with
    its own chart+app both unchanged must resolve unchanged=True."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"tag": "5.4.4@sha256:aaaa"}}}
    resolved = libcomponentdocschanges.resolve_component_own_version_change("zac", deps, deps, values, values, None, [])
    assert resolved is not None
    *_rest, unchanged = resolved
    assert unchanged is True


def test_resolve_component_own_version_change_false_when_app_changed(libcomponentdocschanges):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    current = {"zac": {"image": {"tag": "5.4.4@sha256:bbbb"}}}
    baseline = {"zac": {"image": {"tag": "5.0.2@sha256:aaaa"}}}
    resolved = libcomponentdocschanges.resolve_component_own_version_change(
        "zac", deps, deps, current, baseline, None, []
    )
    _dep, _chart_name, _old_chart, _new_chart, old_app, new_app, unchanged = resolved
    assert (old_app, new_app, unchanged) == ("5.0.2", "5.4.4", False)


def test_resolve_component_own_version_change_false_when_chart_changed(libcomponentdocschanges):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    baseline_deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}]
    values = {"zac": {"image": {"tag": "5.4.4@sha256:aaaa"}}}
    resolved = libcomponentdocschanges.resolve_component_own_version_change(
        "zac", deps, baseline_deps, values, values, None, []
    )
    *_rest, unchanged = resolved
    assert unchanged is False


def test_resolve_component_own_version_change_native_component_ignores_chart(libcomponentdocschanges):
    """frankgateway (see lib.chart.NATIVE_COMPONENTS) has no chart at
    all — new_chart == "-" always counts as "chart unchanged", so the
    decision hinges entirely on the app version."""
    values = {"frankgateway": {"image": {"tag": "104@sha256:aaaa"}}}
    resolved = libcomponentdocschanges.resolve_component_own_version_change(
        "frankgateway", [], [], values, values, None, []
    )
    *_rest, unchanged = resolved
    assert unchanged is True


def test_resolve_component_own_version_change_none_for_unmatched_key(libcomponentdocschanges):
    resolved = libcomponentdocschanges.resolve_component_own_version_change("ghost", [], [], {}, {}, None, [])
    assert resolved is None


def test_resolve_component_own_version_change_vendored_subchart_fallback_applies_to_baseline_too(
    libcomponentdocschanges, tmp_path
):
    """Regression test (real bug, real doc): openbao's own "server.image.
    tag" is deliberately left blank in both baseline and target values.yaml
    (see settings.yaml's own component_resolution.image_paths["openbao"]
    comment) — its real app version only ever resolves via the
    vendored-.tgz subchart_app_version fallback (see lib.upgradedoc.
    actual_app_version), which the OLD code never even attempted for the
    baseline side. Its chart version (0.28.4) is unchanged this hop, so
    the exact same vendored .tgz backs both sides — old_app must resolve
    to the SAME "v2.5.5" as new_app, not None, and unchanged must be True,
    exactly like any other component whose own version genuinely didn't
    change (e.g. zac). Before this fix, old_app stayed None (wrongly
    rendering "(new)") purely because of this resolution gap, not because
    openbao's version actually changed. No monkeypatch needed — openbao is
    already registered in the real component_resolution.image_paths."""
    import io
    import tarfile

    import yaml as pyyaml

    charts_dir = tmp_path / "charts"
    charts_dir.mkdir()
    tgz_path = charts_dir / "openbao-0.28.4.tgz"
    with tarfile.open(tgz_path, "w:gz") as tar:
        for filename, content in (
            ("openbao/values.yaml", {"server": {"image": {"tag": ""}}}),
            ("openbao/Chart.yaml", {"apiVersion": "v2", "version": "0.28.4", "appVersion": "v2.5.5"}),
        ):
            data = pyyaml.safe_dump(content).encode("utf-8")
            info = tarfile.TarInfo(name=filename)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    dep = {"name": "openbao", "version": "0.28.4"}
    values = {"openbao": {"server": {"image": {"repository": "quay.io/openbao/openbao", "tag": ""}}}}

    resolved = libcomponentdocschanges.resolve_component_own_version_change(
        "openbao", [dep], [dep], values, values, tmp_path, []
    )
    _dep, _chart_name, old_chart, new_chart, old_app, new_app, unchanged = resolved
    assert (old_chart, new_chart, old_app, new_app, unchanged) == ("0.28.4", "0.28.4", "v2.5.5", "v2.5.5", True)


def test_resolve_component_own_version_change_vendored_fallback_never_used_when_chart_changed(
    libcomponentdocschanges, tmp_path
):
    """The vendored-subchart fallback above must never fire when the
    chart version itself changed — the current chart_dir's vendored .tgz
    (at the TARGET's chart version) is only a valid stand-in for the
    baseline's own app version when it's the SAME .tgz backing both
    sides. A real baseline-side chart bump must stay unresolved (old_app
    None) rather than silently reusing the wrong file's appVersion. No
    monkeypatch needed — openbao is already registered in the real
    component_resolution.image_paths."""
    import io
    import tarfile

    import yaml as pyyaml

    charts_dir = tmp_path / "charts"
    charts_dir.mkdir()
    tgz_path = charts_dir / "openbao-0.29.0.tgz"
    with tarfile.open(tgz_path, "w:gz") as tar:
        for filename, content in (
            ("openbao/values.yaml", {"server": {"image": {"tag": ""}}}),
            ("openbao/Chart.yaml", {"apiVersion": "v2", "version": "0.29.0", "appVersion": "v2.6.0"}),
        ):
            data = pyyaml.safe_dump(content).encode("utf-8")
            info = tarfile.TarInfo(name=filename)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    dep = {"name": "openbao", "version": "0.29.0"}
    baseline_dep = {"name": "openbao", "version": "0.28.4"}
    values = {"openbao": {"server": {"image": {"repository": "quay.io/openbao/openbao", "tag": ""}}}}

    resolved = libcomponentdocschanges.resolve_component_own_version_change(
        "openbao", [dep], [baseline_dep], values, values, tmp_path, []
    )
    _dep, _chart_name, old_chart, new_chart, old_app, new_app, unchanged = resolved
    assert (old_chart, new_chart, old_app, new_app, unchanged) == ("0.28.4", "0.29.0", None, "v2.6.0", False)


def test_resolve_component_own_version_change_eck_operator_now_reads_unchanged(libcomponentdocschanges, tmp_path):
    """Regression test (real bug, real doc, real chart): eck-operator
    existed, enabled, at the podiumd-4.9.1 baseline with NO explicit
    values.yaml "image:" override at all (same shape modeled here —
    only "enabled: true", nothing else); its chart version (3.5.0) is
    UNCHANGED this hop, and the target added an explicit split "tag:"/
    "digest:" override still reading the same 3.5.0. Since eck-operator
    is now registered in component_resolution.image_paths (no monkeypatch needed —
    that registration IS the fix under test), the vendored-subchart
    fallback correctly resolves old_app to the SAME "3.5.0" as new_app,
    so this now reads (unchanged), not "(new)" — confirmed live on the
    real chart's own 4.9.1-to-4.9.2-upgrade.md before/after this fix."""
    import io
    import tarfile

    import yaml as pyyaml

    charts_dir = tmp_path / "charts"
    charts_dir.mkdir()
    tgz_path = charts_dir / "eck-operator-3.5.0.tgz"
    with tarfile.open(tgz_path, "w:gz") as tar:
        for filename, content in (
            ("eck-operator/values.yaml", {"image": {"tag": "3.5.0"}}),
            ("eck-operator/Chart.yaml", {"apiVersion": "v2", "version": "3.5.0", "appVersion": "3.5.0"}),
        ):
            data = pyyaml.safe_dump(content).encode("utf-8")
            info = tarfile.TarInfo(name=filename)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    dep = {"name": "eck-operator", "version": "3.5.0", "condition": "eck-operator.enabled"}
    baseline_values = {"eck-operator": {"enabled": True}}  # no "image:" override at all, real 4.9.1 shape
    target_values = {"eck-operator": {"enabled": True, "image": {"tag": "3.5.0", "digest": "sha256:" + "b" * 64}}}

    resolved = libcomponentdocschanges.resolve_component_own_version_change(
        "eck-operator", [dep], [dep], target_values, baseline_values, tmp_path, []
    )
    _dep, _chart_name, old_chart, new_chart, old_app, new_app, unchanged = resolved
    assert (old_chart, new_chart, old_app, new_app, unchanged) == ("3.5.0", "3.5.0", "3.5.0", "3.5.0", True)


def test_add_missing_component_rows_skips_own_unchanged_component(libcomponentdocschanges, tmp_path):
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
    new_text, added_names = libcomponentdocschanges.add_missing_component_rows(
        text, tmp_path, deps, values, deps, values, {"zac"}, "4.9.1"
    )
    assert added_names == []
    assert "zac" not in new_text


def test_add_missing_component_rows_still_adds_a_real_bump(libcomponentdocschanges, tmp_path):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    current_values = {"zac": {"image": {"tag": "5.4.4@sha256:bbbb"}}}
    baseline_values = {"zac": {"image": {"tag": "5.0.2@sha256:aaaa"}}}
    text = (
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n\n"
    )
    new_text, added_names = libcomponentdocschanges.add_missing_component_rows(
        text, tmp_path, deps, current_values, deps, baseline_values, {"zac"}, "4.9.1"
    )
    assert added_names == ["zac"]
    assert "| zac | 5.0.2 → 5.4.4 | 1.0.297 (unchanged) | - |" in new_text


# --- insert_changes_section ---


def test_insert_changes_section_strips_bare_todo_stub_on_first_insertion(libcomponentdocschanges):
    """Regression test (real bug, real doc): 4.9.1-to-4.9.2-upgrade.md's
    own "## Changes\n\nTODO\n" — the exact STUB_TEMPLATES["upgrade"] shape
    create-doc-version scaffolds before any real content exists — never
    got cleared the moment the FIRST real "### ..." block landed."""
    text = "## Changes\n\nTODO\n"
    section_text = (
        "### eck-operator 3.5.0 (new) (chart 3.5.0, unchanged)\n\n"
        "PodiumD 4.9.2 introduces **eck-operator** at app version 3.5.0.\n\n"
    )
    new_text = libcomponentdocschanges.insert_changes_section(text, section_text, "eck-operator", [], {})
    assert "TODO" not in new_text
    assert new_text == "## Changes\n\n" + section_text


def test_insert_changes_section_second_insertion_after_real_block_unaffected(libcomponentdocschanges):
    """Once a real "### ..." block already exists, `blocks` is non-empty
    and the stub-stripping path (only reachable when `blocks` is empty)
    never fires — a second insertion behaves exactly as before this fix."""
    text = (
        "## Changes\n\n### eck-operator 3.5.0 (new) (chart 3.5.0, unchanged)\n\n"
        "PodiumD 4.9.2 introduces **eck-operator** at app version 3.5.0.\n\n"
    )
    section_text = "### zac 5.0.2 → 5.4.4\n\nSome prose.\n\n"
    new_text = libcomponentdocschanges.insert_changes_section(
        text, section_text, "zac", DEPS, {"zac": {}, "eck-operator": {}}
    )
    assert "### eck-operator" in new_text
    assert "### zac" in new_text
    assert "TODO" not in new_text


def test_insert_changes_section_never_strips_real_prose_mentioning_todo(libcomponentdocschanges):
    """A "## Changes" section with real, human-written prose that happens
    to start with the word "TODO" (but isn't the exact bare-stub shape)
    must never be silently deleted."""
    text = "## Changes\n\nTODO: figure out redis sidecar wording later.\n"
    section_text = (
        "### eck-operator 3.5.0 (new) (chart 3.5.0, unchanged)\n\n"
        "PodiumD 4.9.2 introduces **eck-operator** at app version 3.5.0.\n\n"
    )
    new_text = libcomponentdocschanges.insert_changes_section(text, section_text, "eck-operator", [], {})
    assert "TODO: figure out redis sidecar wording later." in new_text


def test_insert_changes_section_also_strips_the_top_level_intro_todo_on_first_insertion(libcomponentdocschanges):
    """Both of upgrade.md's own stub placeholders -- the top-level intro
    "TODO: describe this hop's changes." AND "## Changes"' own bare
    "TODO" -- must clear together the moment the FIRST real "### ..."
    block is inserted, not just the "## Changes" one on its own."""
    text = (
        UPGRADE_DOC_INTRO + "TODO: describe this hop's changes.\n\n"
        "## Component versions (4.9.2 vs 4.9.1)\n\n"
        "## Changes\n\n"
        "TODO\n"
    )
    section_text = (
        "### eck-operator 3.5.0 (new) (chart 3.5.0, unchanged)\n\n"
        "PodiumD 4.9.2 introduces **eck-operator** at app version 3.5.0.\n\n"
    )
    new_text = libcomponentdocschanges.insert_changes_section(text, section_text, "eck-operator", [], {})
    assert "TODO" not in new_text
    assert new_text == (UPGRADE_DOC_INTRO + "## Component versions (4.9.2 vs 4.9.1)\n\n## Changes\n\n" + section_text)


# --- strip_stale_upgrade_placeholders (retroactive cleanup, fix-doc-consistency) ---

UPGRADE_DOC_INTRO = (
    "# Upgrade guide: PodiumD 4.9.1 → 4.9.2\n\n"
    "> See the Confluence Releases page for the agreed application\n"
    "> targets: <https://dimpact.atlassian.net/wiki/spaces/PCP/pages/7602191/Releases+PodiumD>.\n\n"
)


def test_strip_stale_upgrade_placeholders_removes_both_leftovers_before_a_real_block(libcomponentdocschanges):
    """Regression test (real bug, real doc): 4.9.1-to-4.9.2-upgrade.md's
    own "### eck-operator ..." block was inserted BEFORE insert_changes_
    section's own insertion-time fix existed, leaving BOTH the top-level
    intro "TODO: describe this hop's changes." AND "## Changes"' own
    bare "TODO" stranded beside it forever -- both clear together as ONE
    event, since both equally mean "this hop has real recorded changes"."""
    text = (
        UPGRADE_DOC_INTRO + "TODO: describe this hop's changes.\n\n"
        "## Component versions (4.9.2 vs 4.9.1)\n\n"
        "## Changes\n\n"
        "TODO\n\n"
        "### eck-operator 3.5.0 (new) (chart 3.5.0, unchanged)\n\n"
        "PodiumD 4.9.2 introduces **eck-operator** at app version 3.5.0.\n\n"
        "- Image tag pin `eck-operator.image.tag` `3.5.0` (new) in\n"
        "  `charts/podiumd/values.yaml`.\n"
    )
    new_text, changed = libcomponentdocschanges.strip_stale_upgrade_placeholders(text)
    assert changed is True
    assert "TODO" not in new_text
    assert new_text == (
        UPGRADE_DOC_INTRO + "## Component versions (4.9.2 vs 4.9.1)\n\n"
        "## Changes\n\n"
        "### eck-operator 3.5.0 (new) (chart 3.5.0, unchanged)\n\n"
        "PodiumD 4.9.2 introduces **eck-operator** at app version 3.5.0.\n\n"
        "- Image tag pin `eck-operator.image.tag` `3.5.0` (new) in\n"
        "  `charts/podiumd/values.yaml`.\n"
    )


def test_strip_stale_upgrade_placeholders_leaves_a_still_empty_section_untouched(libcomponentdocschanges):
    """A "## Changes" section that STILL only has the bare TODO (no real
    "### ..." block yet) is the correct, expected state for a genuinely
    new doc -- must never be touched, and neither must the intro TODO
    sitting right above it."""
    text = (
        UPGRADE_DOC_INTRO + "TODO: describe this hop's changes.\n\n"
        "## Component versions (4.9.2 vs 4.9.1)\n\n"
        "## Changes\n\n"
        "TODO\n"
    )
    new_text, changed = libcomponentdocschanges.strip_stale_upgrade_placeholders(text)
    assert changed is False
    assert new_text == text


def test_strip_stale_upgrade_placeholders_never_strips_real_prose_mentioning_todo(libcomponentdocschanges):
    text = (
        UPGRADE_DOC_INTRO + "TODO: this describes something else entirely, not the stub.\n\n"
        "## Component versions (4.9.2 vs 4.9.1)\n\n"
        "## Changes\n\n"
        "TODO: figure out redis sidecar wording later.\n\n"
        "### eck-operator 3.5.0 (new) (chart 3.5.0, unchanged)\n\n"
        "PodiumD 4.9.2 introduces **eck-operator** at app version 3.5.0.\n\n"
    )
    new_text, changed = libcomponentdocschanges.strip_stale_upgrade_placeholders(text)
    assert changed is False
    assert "TODO: this describes something else entirely, not the stub." in new_text
    assert "TODO: figure out redis sidecar wording later." in new_text


def test_strip_stale_upgrade_placeholders_noop_without_a_changes_heading(libcomponentdocschanges):
    text = "### some other heading\n\nprose\n"
    new_text, changed = libcomponentdocschanges.strip_stale_upgrade_placeholders(text)
    assert changed is False
    assert new_text == text


def test_strip_stale_upgrade_placeholders_strips_only_the_changes_todo_when_intro_already_clean(
    libcomponentdocschanges,
):
    """A doc that's already had its own intro TODO cleared by hand (or a
    previous partial fix) but still has "## Changes"' own bare TODO must
    still get that one cleared -- the two placeholders are one event
    only in the sense that they clear TOGETHER when both are present,
    not that neither can ever be fixed without the other."""
    text = (
        UPGRADE_DOC_INTRO + "## Component versions (4.9.2 vs 4.9.1)\n\n"
        "## Changes\n\n"
        "TODO\n\n"
        "### eck-operator 3.5.0 (new) (chart 3.5.0, unchanged)\n\n"
        "PodiumD 4.9.2 introduces **eck-operator** at app version 3.5.0.\n\n"
    )
    new_text, changed = libcomponentdocschanges.strip_stale_upgrade_placeholders(text)
    assert changed is True
    assert "TODO" not in new_text
    assert "### eck-operator" in new_text


def test_find_values_delta_section_matches_hand_written_heading(libcomponentdocsdeltas):
    text = "# Values deltas\n\n## KISS 2.2.4 → 3.0.0 — required edits\n\nSome prose.\n"
    section = libcomponentdocsdeltas.find_values_delta_section(text, "kiss", [{"name": "kiss", "version": "3.0.0"}])
    assert section is not None
    assert section["heading"] == "KISS 2.2.4 → 3.0.0 — required edits"


def test_find_values_delta_section_no_match_returns_none(libcomponentdocsdeltas):
    text = "# Values deltas\n\n## zac 5.0.2 → 5.4.3\n\n- Key `zac.a` was added.\n"
    assert libcomponentdocsdeltas.find_values_delta_section(text, "openformulieren", DEPS) is None


def test_insert_values_delta_section_positions_by_values_yaml_order(libcomponentdocsdeltas):
    text = "# Values deltas\n\n## openformulieren 3.4.10 → 3.5.6\n\n- Key `a` was added.\n"
    new_text = libcomponentdocsdeltas.insert_values_delta_section(
        text, "zac", "## zac 5.0.2 → 5.4.3\n", ["- Key `zac.a` was added.\n"], DEPS, {"zac": {}, "openformulieren": {}}
    )
    assert new_text.index("## zac") < new_text.index("## openformulieren")


def test_insert_values_delta_section_strips_bare_todo_stub_on_first_insertion(libcomponentdocsdeltas):
    """Same class of bug as insert_changes_section's own (see that
    function's tests): a values-deltas.md doc still carrying STUB_
    TEMPLATES["values-deltas"]'s own bare TODO sentence (create-doc-
    version's scaffold, before any real "## ..." section exists) must
    have it cleared the moment the FIRST real section gets inserted."""
    text = (
        "# Values deltas — PodiumD 4.9.1 → 4.9.2\n\n"
        "TODO: describe any gemeente `podiumd.yml` changes required for this hop.\n"
    )
    new_text = libcomponentdocsdeltas.insert_values_delta_section(
        text, "zac", "## zac 5.0.2 → 5.4.3\n", ["- Key `zac.a` was added.\n"], DEPS, {"zac": {}}
    )
    assert "TODO" not in new_text
    assert new_text == (
        "# Values deltas — PodiumD 4.9.1 → 4.9.2\n\n## zac 5.0.2 → 5.4.3\n\n- Key `zac.a` was added.\n\n"
    )


def test_insert_values_delta_section_second_insertion_unaffected(libcomponentdocsdeltas):
    """Once a real section already exists, `sections` is non-empty and
    the stub-stripping path never fires — matches insert_changes_
    section's own equivalent guarantee."""
    text = "# Values deltas — PodiumD 4.9.1 → 4.9.2\n\n## openformulieren 3.4.10 → 3.5.6\n\n- Key `a` was added.\n"
    new_text = libcomponentdocsdeltas.insert_values_delta_section(
        text, "zac", "## zac 5.0.2 → 5.4.3\n", ["- Key `zac.a` was added.\n"], DEPS, {"zac": {}, "openformulieren": {}}
    )
    assert "## openformulieren" in new_text
    assert "## zac" in new_text
    assert "TODO" not in new_text


def test_insert_values_delta_section_never_strips_real_prose_mentioning_todo(libcomponentdocsdeltas):
    text = "# Values deltas — PodiumD 4.9.1 → 4.9.2\n\nTODO: check with gemeente X about their override Y.\n"
    new_text = libcomponentdocsdeltas.insert_values_delta_section(
        text, "zac", "## zac 5.0.2 → 5.4.3\n", ["- Key `zac.a` was added.\n"], DEPS, {"zac": {}}
    )
    assert "TODO: check with gemeente X about their override Y." in new_text


# --- strip_stale_values_deltas_todo_stub (retroactive cleanup, fix-doc-consistency) ---


def test_strip_stale_values_deltas_todo_stub_removes_leftover_before_a_real_section(libcomponentdocsdeltas):
    """Regression test (real bug, real doc): 4.9.1-to-4.9.2-values-deltas.md's
    own "## eck-operator ..." section was inserted BEFORE insert_values_
    delta_section's own insertion-time fix existed, leaving the stub
    TODO sentence stranded beside it forever."""
    text = (
        "# Values deltas — PodiumD 4.9.1 → 4.9.2\n\n"
        "TODO: describe any gemeente `podiumd.yml` changes required for this hop.\n\n"
        "## eck-operator 3.5.0 (new) (chart 3.5.0, unchanged)\n\n"
        "- Key `eck-operator.image` was added.\n"
    )
    new_text, changed = libcomponentdocsdeltas.strip_stale_values_deltas_todo_stub(text)
    assert changed is True
    assert "TODO" not in new_text
    assert new_text == (
        "# Values deltas — PodiumD 4.9.1 → 4.9.2\n\n"
        "## eck-operator 3.5.0 (new) (chart 3.5.0, unchanged)\n\n"
        "- Key `eck-operator.image` was added.\n"
    )


def test_strip_stale_values_deltas_todo_stub_leaves_a_still_empty_doc_untouched(libcomponentdocsdeltas):
    """A doc that STILL only has the bare stub (no real section yet) is
    the correct, expected state for a genuinely new doc -- must never be
    touched."""
    text = (
        "# Values deltas — PodiumD 4.9.1 → 4.9.2\n\n"
        "TODO: describe any gemeente `podiumd.yml` changes required for this hop.\n"
    )
    new_text, changed = libcomponentdocsdeltas.strip_stale_values_deltas_todo_stub(text)
    assert changed is False
    assert new_text == text


def test_strip_stale_values_deltas_todo_stub_never_strips_real_prose_mentioning_todo(libcomponentdocsdeltas):
    text = (
        "# Values deltas — PodiumD 4.9.1 → 4.9.2\n\n"
        "TODO: check with gemeente X about their override Y.\n\n"
        "## eck-operator 3.5.0 (new) (chart 3.5.0, unchanged)\n\n"
        "- Key `eck-operator.image` was added.\n"
    )
    new_text, changed = libcomponentdocsdeltas.strip_stale_values_deltas_todo_stub(text)
    assert changed is False
    assert "TODO: check with gemeente X about their override Y." in new_text


def test_strip_stale_values_deltas_todo_stub_noop_without_any_section(libcomponentdocsdeltas):
    text = "# Values deltas — PodiumD 4.9.1 → 4.9.2\n\nSome hand-written prose, no section yet.\n"
    new_text, changed = libcomponentdocsdeltas.strip_stale_values_deltas_todo_stub(text)
    assert changed is False
    assert new_text == text


# --- gemeente-specific.md: has_stale_gemeente_specific_placeholder (checker-only, no fixer) ---

GEMEENTE_STUB = (
    "# Gemeente-specific notes — PodiumD 4.9.1 → 4.9.2\n\n"
    "Findings for this hop that apply to a **specific gemeente or environment** —\n"
    "not to the release in general — are collected here: data quirks, local\n"
    "overrides, hosting particulars, incident follow-ups.\n\n"
    "_None recorded yet._\n\n"
    "<!-- Add entries per gemeente/environment:\n\n"
    "## <gemeente> (<env>)\n\n"
    "- What was hit, why it is specific to this environment, and the\n"
    "  fix/workaround applied.\n"
    "-->\n"
)


def test_has_real_gemeente_specific_content_false_for_the_bare_stub(libcomponentdocsdeltas):
    """The stub's own EXAMPLE "## <gemeente> (<env>)" heading lives
    inside its commented-out template block -- must never count as real
    content on its own."""
    assert libcomponentdocsdeltas.has_real_gemeente_specific_content(GEMEENTE_STUB) is False


def test_has_real_gemeente_specific_content_true_for_a_real_section(libcomponentdocsdeltas):
    text = GEMEENTE_STUB + "\n## Utrecht (prod)\n\n- Some real finding.\n"
    assert libcomponentdocsdeltas.has_real_gemeente_specific_content(text) is True


def test_has_stale_gemeente_specific_placeholder_true_when_both_present(libcomponentdocsdeltas):
    """Regression case this checker exists for: a human added a real
    "## <gemeente> (<env>)" finding but left the "_None recorded yet._"
    placeholder in place above it."""
    text = GEMEENTE_STUB + "\n## Utrecht (prod)\n\n- Some real finding.\n"
    assert libcomponentdocsdeltas.has_stale_gemeente_specific_placeholder(text) is True


def test_has_stale_gemeente_specific_placeholder_false_for_the_bare_stub(libcomponentdocsdeltas):
    """A doc that STILL only has the bare stub (nothing recorded yet) is
    the correct, expected state -- must never be flagged."""
    assert libcomponentdocsdeltas.has_stale_gemeente_specific_placeholder(GEMEENTE_STUB) is False


def test_has_stale_gemeente_specific_placeholder_false_once_placeholder_removed_by_hand(libcomponentdocsdeltas):
    """Once a human clears the placeholder themselves (the only way it
    can ever go -- there's no automated fixer for this one), the finding
    must stop firing."""
    text = GEMEENTE_STUB.replace("_None recorded yet._\n\n", "") + "\n## Utrecht (prod)\n\n- Some real finding.\n"
    assert libcomponentdocsdeltas.has_stale_gemeente_specific_placeholder(text) is False


def test_append_values_delta_section_body_adds_after_existing_content(libcomponentdocsdeltas):
    text = "# Values deltas\n\n## KISS — required edits\n\nSome prose.\n\n## PABC\n\nOther prose.\n"
    sections = libcomponentdocsdeltas.find_values_delta_section(text, "kiss", [{"name": "kiss", "version": "1.0.0"}])
    new_text = libcomponentdocsdeltas.append_values_delta_section_body(text, sections, ["- Key `kiss.a` was added.\n"])
    assert "Some prose.\n\n- Key `kiss.a` was added.\n\n## PABC" in new_text


def test_remove_values_delta_section_never_removes_multi_identity_heading(libcomponentdocsdeltas):
    """A hand-written section covering several components at once must
    never be deleted just because one of them reset to baseline."""
    text = "# Values deltas\n\n## ZAC and ZGW Office Add-in — no changes\n\nProse.\n"
    deps = DEPS + [{"name": "zgw-office-addin", "version": "0.0.89"}]
    new_text, removed = libcomponentdocsdeltas.remove_values_delta_section(text, "zac", deps)
    assert removed is False
    assert new_text == text


# --- sync_values_delta_sections ---


def test_sync_values_delta_sections_skips_key_with_no_schema_change(libcomponentdocsdeltas, tmp_path):
    """A pure app/chart version bump — no describe_key_changes lines at
    all — gets no brand-new section: a heading with nothing under it is
    worse than no heading (values-deltas.md exists for gemeente-
    actionable schema changes, not a general changelog)."""
    text = "# Values deltas\n\nNo gemeente podiumd.yml changes are required for this hop.\n"
    values = {"zac": {"image": {}}}
    new_text, created, updated = libcomponentdocsdeltas.sync_values_delta_sections(
        text, tmp_path, DEPS, values, DEPS, values, {"zac"}
    )
    assert created == []
    assert updated == []
    assert new_text == text


def test_sync_values_delta_sections_creates_section_only_when_key_lines_exist(libcomponentdocsdeltas, tmp_path):
    text = "# Values deltas\n\nNo gemeente podiumd.yml changes are required for this hop.\n"
    baseline_values = {"zac": {"image": {}}}
    target_values = {"zac": {"image": {}, "newFeature": True}}
    new_text, created, updated = libcomponentdocsdeltas.sync_values_delta_sections(
        text, tmp_path, DEPS, target_values, DEPS, baseline_values, {"zac"}
    )
    assert created == ["zac"]
    assert "## zac" in new_text
    assert "- Key `zac.newFeature` was added.\n" in new_text


# --- prune_empty_values_delta_sections ---


def test_prune_empty_values_delta_sections_removes_a_heading_with_nothing_under_it(libcomponentdocsdeltas):
    text = (
        "# Values deltas\n\n"
        "## zac 5.0.2 → 5.4.3 (chart 1.0.297, unchanged)\n\n"
        "## openformulieren 3.4.10 → 3.5.6\n\n"
        "- Key `openformulieren.a` was added.\n"
    )
    new_text, removed = libcomponentdocsdeltas.prune_empty_values_delta_sections(text)
    assert removed == ["zac 5.0.2 → 5.4.3 (chart 1.0.297, unchanged)"]
    assert "## zac" not in new_text
    assert "## openformulieren" in new_text
    assert "- Key `openformulieren.a` was added.\n" in new_text


def test_prune_empty_values_delta_sections_never_removes_hand_written_prose(libcomponentdocsdeltas):
    text = "# Values deltas\n\n## KISS — required edits\n\nSome real prose here.\n"
    new_text, removed = libcomponentdocsdeltas.prune_empty_values_delta_sections(text)
    assert removed == []
    assert new_text == text


def test_prune_empty_values_delta_sections_no_sections_is_unchanged(libcomponentdocsdeltas):
    text = "# Values deltas\n\nTODO.\n"
    new_text, removed = libcomponentdocsdeltas.prune_empty_values_delta_sections(text)
    assert removed == []
    assert new_text == text


def test_images_stub_template_has_a_changes_header(libcomponentdocsheader, libcomponentdocsbaselinedocstubs):
    """A fresh images-manifest stub must include a "# Changes:" anchor
    line, not just the bare "[]" YAML placeholder — without it, find_
    images_manifest_changes_header finds nothing, so add_missing_images_
    manifest_entries (and update_images_manifest) can add new entries to
    the body but never a matching numbered item above them, silently
    leaving the "# Changes:" section looking like the literal "[]" it
    started as (real symptom reported live)."""
    text = libcomponentdocsbaselinedocstubs.IMAGES_STUB_TEMPLATE.format(upgrade_docs_baseline="4.8.5", target="4.9.0")
    lines = text.splitlines(keepends=True)
    header_idx, header_has_count = libcomponentdocsheader.find_images_manifest_changes_header(lines)
    assert header_idx is not None
    assert header_has_count is False
