"""values_delta_section_heading / describe_key_changes,
values_tree_path_for / find_matching_images_entry /
update_images_manifest_entry, and update_images_manifest: split out of the
former, monolithic test_update_component_version.py for pylint's
too-many-lines check."""

from pathlib import Path
from types import ModuleType

# --- values_delta_section_heading / describe_key_changes ---


def test_values_delta_section_heading_app_and_chart_changed(ucv: ModuleType):
    heading = ucv.values_delta_section_heading("openformulieren", "3.4.10", "3.5.6", "1.12.0", "1.13.0")
    assert heading == "## openformulieren 3.4.10 → 3.5.6 (chart 1.12.0 → 1.13.0)\n"


def test_values_delta_section_heading_chart_unchanged(ucv: ModuleType):
    heading = ucv.values_delta_section_heading("openformulieren", "3.4.10", "3.5.6", "1.12.0", "1.12.0")
    assert heading == "## openformulieren 3.4.10 → 3.5.6 (chart 1.12.0, unchanged)\n"


def test_values_delta_section_heading_native_component_omits_chart_clause(ucv: ModuleType):
    """new_chart="-" (see lib.chart.NATIVE_COMPONENTS) drops the "(chart
    ...)" clause entirely rather than rendering "(chart None → -)"."""
    heading = ucv.values_delta_section_heading("frankgateway", "100", "104", None, "-")
    assert heading == "## frankgateway 100 → 104\n"


def test_describe_key_changes_reports_added_removed_renamed(ucv: ModuleType):
    baseline = {"a": 1, "old_name": {"x": 1}}
    current = {"a": 1, "new_name": {"x": 1}, "brand_new": 2}
    lines = ucv.describe_key_changes("comp", baseline, current)
    joined = "".join(lines)
    assert "`comp.brand_new` was added" in joined
    assert "`comp.old_name` was renamed to `comp.new_name`" in joined


def test_describe_key_changes_empty_when_nothing_changed(ucv: ModuleType):
    assert ucv.describe_key_changes("comp", {"a": 1}, {"a": 1}) == []


# --- values_tree_path_for / find_matching_images_entry / update_images_manifest_entry ---


def test_values_tree_path_for_single_image(libcomponentdocsentries: ModuleType):
    assert libcomponentdocsentries.values_tree_path_for("zac", "image") == ("zac",)


def test_values_tree_path_for_nested_image(libcomponentdocsentries: ModuleType):
    assert libcomponentdocsentries.values_tree_path_for("zgw-office-addin", "frontend.image") == (
        "zgw-office-addin",
        "frontend",
    )


def test_find_matching_images_entry_matches_by_path(libcomponentdocsentries: ModuleType):
    entries = [{"name": "zac"}, {"name": "zgw-office-addin-frontend"}]
    entry, idx, index = libcomponentdocsentries.find_matching_images_entry(
        entries, [0, 1], ("zgw-office-addin", "frontend")
    )
    assert entry["name"] == "zgw-office-addin-frontend"
    assert idx == 1
    assert index == 1


def test_find_matching_images_entry_none_when_unmatched(libcomponentdocsentries: ModuleType):
    entries = [{"name": "zac"}]
    entry, idx, index = libcomponentdocsentries.find_matching_images_entry(entries, [0], ("openformulieren",))
    assert entry is None and idx is None and index is None


def test_update_images_manifest_entry_updates_version_digest_and_comment(libcomponentdocsentries: ModuleType):
    lines = [
        "# ZAC — 5.0.1 -> 5.1.0\n",
        "- name: zac\n",
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n",
        '  version: "5.1.0"\n',
        '  digest: "sha256:aaaa"\n',
    ]
    entries = [{"name": "zac"}]
    changed = libcomponentdocsentries.update_images_manifest_entry(
        libcomponentdocsentries.ParsedManifest(lines, entries, [1]), 0, "5.4.3@sha256:bbbb", "zac"
    )
    assert changed is True
    assert lines[0] == "# ZAC — 5.0.1 -> 5.4.3\n"
    assert '"5.4.3"' in lines[3]
    assert '"sha256:bbbb"' in lines[4]


def test_update_images_manifest_entry_updates_shared_group_comment(libcomponentdocsentries: ModuleType):
    """A second entry (backend) sharing the first entry's (frontend)
    comment, separated by a blank line, must still have that shared
    comment's version pair updated — not skipped as "no comment"."""
    lines = [
        "# ZGW Office Add-in — v0.9.313 -> v0.9.352\n",
        "- name: zgw-office-addin-frontend\n",
        '  version: "v0.9.352"\n',
        '  digest: "sha256:aaaa"\n',
        "\n",
        "- name: zgw-office-addin-backend\n",
        '  version: "v0.9.352"\n',
        '  digest: "sha256:bbbb"\n',
    ]
    entries = [{"name": "zgw-office-addin-frontend"}, {"name": "zgw-office-addin-backend"}]
    changed = libcomponentdocsentries.update_images_manifest_entry(
        libcomponentdocsentries.ParsedManifest(lines, entries, [1, 5]), 1, "v0.9.400@sha256:cccc", "zgw-office-addin"
    )
    assert changed is True
    assert lines[0] == "# ZGW Office Add-in — v0.9.313 -> v0.9.400\n"
    assert '"v0.9.400"' in lines[6]
    assert '"sha256:cccc"' in lines[7]


# --- update_images_manifest ---


def test_update_images_manifest_creates_missing_header(ucv: ModuleType, tmp_path: Path):
    """Regression test (real bug, real doc): update_images_manifest's own
    "# Changes:" header-item logic was entirely guarded by "if header_idx
    is not None:" — a manifest with no header at all (see lib.component_
    docs.ensure_images_manifest_changes_header's own docstring for the
    real case: images-4.9.1.yaml gained 5 real entries via fix-doc-
    consistency this session with no header to add a list item to) got
    changes_action=None forever, silently, from update-component-version/
    update-image-version's own writes too, not just fix-doc-consistency's.
    A missing header must now be created first, so the item still gets
    added."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Baseline: podiumd 4.8.5. Re-verify before release.\n"
        "#\n"
        "# Images new or changed in podiumd 4.9.0 vs 4.8.5.\n"
        "#\n"
        "# See docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md for the operator upgrade notes.\n"
        "#\n\n"
        "# ZAC — 5.0.2 -> 5.1.0\n"
        "- name: zac\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    changes_action, entry_updates, _missing = ucv.update_images_manifest(
        ucv.ManifestUpdateTarget(images_path, "zac", "zac"),
        ucv.VersionChange("5.1.0", "5.4.3", "1.0.297", "1.0.297"),
        ucv.ImagePathUpdate(
            ["image"], {"image": "ghcr.io/infonl/zaakafhandelcomponent"}, {"image": "5.4.3@sha256:cccc"}
        ),
        [],
        {},
    )
    assert changes_action == "added"
    assert entry_updates == ["zac"]
    text = images_path.read_text(encoding="utf-8")
    assert "# Changes:\n" in text
    header_idx = text.index("# Changes:\n")
    intro_idx = text.index("# Images new or changed")
    assert intro_idx < header_idx
    assert "1. zac 5.1.0 -> 5.4.3 (chart 1.0.297, unchanged)." in text


def test_update_images_manifest_no_baseline_app_renders_new(ucv: ModuleType, tmp_path: Path):
    """Regression test: update_images_manifest's own item_text used to
    ALWAYS hardcode "<old_app> -> <new_app>" with no (new)/(unchanged)/
    (digest changed) branch at all — a genuinely brand-new component
    (no baseline app version at all, old_app=None) rendered as a
    nonsensical "<new_app> -> <new_app>" instead of "<new_app> (new)"."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Baseline: podiumd 4.8.5. Re-verify before release.\n"
        "#\n"
        "# Images new or changed in podiumd 4.9.0 vs 4.8.5.\n"
        "#\n"
        "# See docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md for the operator upgrade notes.\n"
        "#\n\n"
        "# ZAC — 5.0.2 -> 5.1.0\n"
        "- name: zac\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    changes_action, _entry_updates, _missing = ucv.update_images_manifest(
        ucv.ManifestUpdateTarget(images_path, "redis", "redis"),
        ucv.VersionChange(None, "8.10.1", "-", "-"),
        ucv.ImagePathUpdate(["image"], {"image": "redis"}, {"image": "8.10.1@sha256:cccc"}),
        [],
        {},
    )
    assert changes_action == "added"
    text = images_path.read_text(encoding="utf-8")
    assert "redis 8.10.1 (new)." in text
    assert "8.10.1 -> 8.10.1" not in text


def test_update_images_manifest_updates_existing_entry(ucv: ModuleType, tmp_path: Path):
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Two changes:\n"
        "#   1. zac 5.0.2 -> 5.1.0 (chart 1.0.297, unchanged).\n"
        "#   2. other 1.0.0 -> 1.0.1 (chart 1.0.0, unchanged).\n"
        "#\n"
        "# ZAC — 5.0.2 -> 5.1.0\n"
        "- name: zac\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    changes_action, entry_updates, missing = ucv.update_images_manifest(
        ucv.ManifestUpdateTarget(images_path, "zac", "zac"),
        ucv.VersionChange("5.1.0", "5.4.3", "1.0.297", "1.0.297"),
        ucv.ImagePathUpdate(
            ["image"], {"image": "ghcr.io/infonl/zaakafhandelcomponent"}, {"image": "5.4.3@sha256:cccc"}
        ),
        [],
        {},
    )
    assert changes_action == "updated"
    assert entry_updates == ["zac"]
    assert missing == []
    text = images_path.read_text(encoding="utf-8")
    assert "1. zac 5.1.0 -> 5.4.3 (chart 1.0.297, unchanged)." in text
    assert '"5.4.3"' in text
    assert '"sha256:cccc"' in text


def test_update_images_manifest_native_component_omits_chart_clause(ucv: ModuleType, tmp_path: Path):
    """new_chart="-" (see lib.chart.NATIVE_COMPONENTS) writes a "# Changes:"
    header item with no "(chart ...)" clause at all, rather than the
    misleading "(chart None, unchanged)"."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# One change:\n"
        "#   1. zac 5.0.2 -> 5.1.0 (chart 1.0.297, unchanged).\n"
        "#\n"
        "# ZAC — 5.0.2 -> 5.1.0\n"
        "- name: zac\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    changes_action, entry_updates, _missing = ucv.update_images_manifest(
        ucv.ManifestUpdateTarget(images_path, "frankgateway", "frankgateway"),
        ucv.VersionChange("100", "104", None, "-"),
        ucv.ImagePathUpdate([], {}, {}),
        [],
        {},
    )
    assert changes_action == "added"
    assert entry_updates == []
    text = images_path.read_text(encoding="utf-8")
    assert "frankgateway 100 -> 104.\n" in text
    assert "frankgateway 100 -> 104 (chart" not in text


def test_update_images_manifest_recognizes_bare_changes_header(ucv: ModuleType, tmp_path: Path):
    """A bare "# Changes:" header (no leading count word) — the real,
    hand-curated images-4.9.0.yaml's own actual shape, and lib.
    component_docs.IMAGES_STUB_TEMPLATE's own fresh one — must still be
    found and updated. Before find_images_manifest_changes_header was
    shared, this function's own header search only matched
    CHANGES_HEADER_RE's counted form, so a bare header was silently
    invisible to it: changes_action stayed None and the numbered item
    list was never touched, even though the entry itself still updated
    fine below."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Changes:\n"
        "#   1. zac 5.0.2 -> 5.1.0 (chart 1.0.297, unchanged).\n"
        "#\n"
        "# ZAC — 5.0.2 -> 5.1.0\n"
        "- name: zac\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    changes_action, entry_updates, _missing = ucv.update_images_manifest(
        ucv.ManifestUpdateTarget(images_path, "zac", "zac"),
        ucv.VersionChange("5.1.0", "5.4.3", "1.0.297", "1.0.297"),
        ucv.ImagePathUpdate(
            ["image"], {"image": "ghcr.io/infonl/zaakafhandelcomponent"}, {"image": "5.4.3@sha256:cccc"}
        ),
        [],
        {},
    )
    assert changes_action == "updated"
    assert entry_updates == ["zac"]
    text = images_path.read_text(encoding="utf-8")
    assert "1. zac 5.1.0 -> 5.4.3 (chart 1.0.297, unchanged)." in text
    # The bare header itself is left exactly as-is — never invents a
    # count word it didn't already have.
    assert text.startswith("# Changes:\n")


def test_update_images_manifest_bare_header_new_item_no_count_word_invented(ucv: ModuleType, tmp_path: Path):
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Changes:\n"
        "#   1. zac 5.0.2 -> 5.1.0 (chart 1.0.297, unchanged).\n"
        "#\n"
        "# ZAC — 5.0.2 -> 5.1.0\n"
        "- name: zac\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    changes_action, _entry_updates, missing = ucv.update_images_manifest(
        ucv.ManifestUpdateTarget(images_path, "openformulieren", "openformulieren"),
        ucv.VersionChange("3.4.10", "3.5.6", "1.12.0", "1.12.0"),
        ucv.ImagePathUpdate(["image"], {"image": "openformulieren/open-forms"}, {"image": "3.5.6@sha256:dddd"}),
        [],
        {},
    )
    assert changes_action == "added"
    assert missing == [("image", "openformulieren/open-forms", "3.5.6@sha256:dddd")]
    text = images_path.read_text(encoding="utf-8")
    assert text.startswith("# Changes:\n")
    assert "2. openformulieren 3.4.10 -> 3.5.6 (chart 1.12.0, unchanged)." in text


def test_update_images_manifest_reports_missing_entry(ucv: ModuleType, tmp_path: Path):
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# One change:\n"
        "#   1. zac 5.0.2 -> 5.1.0 (chart 1.0.297, unchanged).\n"
        "#\n"
        "# ZAC — 5.0.2 -> 5.1.0\n"
        "- name: zac\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    changes_action, entry_updates, missing = ucv.update_images_manifest(
        ucv.ManifestUpdateTarget(images_path, "openformulieren", "openformulieren"),
        ucv.VersionChange("3.4.10", "3.5.6", "1.12.0", "1.12.0"),
        ucv.ImagePathUpdate(["image"], {"image": "openformulieren/open-forms"}, {"image": "3.5.6@sha256:dddd"}),
        [],
        {},
    )
    assert changes_action == "added"
    assert entry_updates == []
    assert missing == [("image", "openformulieren/open-forms", "3.5.6@sha256:dddd")]
    text = images_path.read_text(encoding="utf-8")
    assert "Two changes:" in text
    assert "2. openformulieren 3.4.10 -> 3.5.6 (chart 1.12.0, unchanged)." in text


def test_update_images_manifest_new_item_lands_after_continuation_line(ucv: ModuleType, tmp_path: Path):
    """A new item must be appended after the LAST item's continuation
    comment line, not immediately after its numbered line — otherwise it
    gets spliced in the middle of the previous item's own comment block."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Two changes:\n"
        "#   1. zac 5.0.1 -> 5.1.0 (chart 1.0.251 -> 1.0.257).\n"
        "#   2. zgw-office-addin v0.9.313 -> v0.9.352 (chart 0.0.89, unchanged).\n"
        "#      Repository names (zgw-office-addin-{frontend,backend}) unchanged from 4.8.5.\n"
        "#\n"
        "# ZAC — 5.0.1 -> 5.1.0\n"
        "- name: zac\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    changes_action, _entry_updates, _missing = ucv.update_images_manifest(
        ucv.ManifestUpdateTarget(images_path, "openformulieren", "openformulieren"),
        ucv.VersionChange("3.4.10", "3.5.6", "1.12.0", "1.12.0"),
        ucv.ImagePathUpdate(["image"], {"image": "openformulieren/open-forms"}, {"image": "3.5.6@sha256:dddd"}),
        [],
        {},
    )
    assert changes_action == "added"
    lines = images_path.read_text(encoding="utf-8").splitlines()
    assert lines[3] == "#      Repository names (zgw-office-addin-{frontend,backend}) unchanged from 4.8.5."
    assert lines[4] == "#   3. openformulieren 3.4.10 -> 3.5.6 (chart 1.12.0, unchanged)."
    assert lines[5] == "#"


def test_update_images_manifest_new_item_inserted_at_values_yaml_position_not_appended(ucv: ModuleType, tmp_path: Path):
    """Real bug: a brand-new "# Changes:" header item used to always land
    at the very end of the list regardless of values.yaml's own
    component order, only ever fixed by a LATER fix-doc-consistency run.
    Given real deps/values, redis-operator's own new item must land
    BEFORE zac's existing one — redis-operator is values.yaml's first
    top-level key here — not after it."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# One change:\n"
        "#   1. zac 5.0.2 -> 5.4.3 (chart 1.0.297, unchanged).\n"
        "#\n"
        "# ZAC — 5.0.2 -> 5.4.3\n"
        "- name: zac\n"
        '  version: "5.4.3"\n'
        '  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    deps = [
        {"name": "redis-operator", "version": "1.0.0"},
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
    ]
    values = {
        "redis-operator": {"image": {"repository": "opstree/redis-operator", "tag": "0.26.0@sha256:bbbb"}},
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.3@sha256:aaaa"}},
    }
    changes_action, _entry_updates, missing = ucv.update_images_manifest(
        ucv.ManifestUpdateTarget(images_path, "redis-operator", "redis-operator"),
        ucv.VersionChange("0.25.0", "0.26.0", "1.0.0", "1.0.0"),
        ucv.ImagePathUpdate(["image"], {"image": "opstree/redis-operator"}, {"image": "0.26.0@sha256:bbbb"}),
        deps,
        values,
    )
    assert changes_action == "added"
    assert missing == [("image", "opstree/redis-operator", "0.26.0@sha256:bbbb")]
    text = images_path.read_text(encoding="utf-8")
    assert "#   1. redis-operator 0.25.0 -> 0.26.0 (chart 1.0.0, unchanged).\n" in text
    assert "#   2. zac 5.0.2 -> 5.4.3 (chart 1.0.297, unchanged).\n" in text
    assert "Two changes:" in text
