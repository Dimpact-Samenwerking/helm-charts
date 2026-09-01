"""parse_changes_block, check_images_manifest_format — including the two
regressions found during development: a version number like "1.17.1-static"
on a continuation line being mistaken for a new numbered list item, and a
trailing period being captured as part of a version."""
from dep_helpers import make_dep

REAL_MANIFEST = """\
# Baseline: podiumd 4.8.5 (origin/feature/podiumd-4.8.5 @ f27a008).
#   git diff f27a008..HEAD -- charts/podiumd/Chart.yaml charts/podiumd/values.yaml
#
# Images new or changed in podiumd 4.9.0 vs 4.8.5.
#
# Changes:
#   1. ZAC (Zaakafhandelcomponent) 5.0.2 -> 5.4.3 (chart 1.0.297, unchanged).
#      Includes a bump of the ZAC OPA sidecar (openpolicyagent/opa
#      1.17.1-static -> 1.19.0-static). Other sidecars unchanged.
#   2. ZGW Office Add-in v0.9.313 -> 0.11.0 (chart 0.0.89 -> 0.0.92).
#
# See docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md for the operator upgrade notes.

# ZAC — 5.0.2 -> 5.4.3
- name: zac
  url: ghcr.io/infonl/zaakafhandelcomponent
  version: "5.4.3"
  digest: "sha256:aaa"

# ZAC OPA sidecar — 1.17.1-static -> 1.19.0-static
- name: opa
  url: openpolicyagent/opa
  version: "1.19.0-static"
  digest: "sha256:bbb"
"""


def test_parse_changes_block_extracts_all_items(libupgradedoc):
    items = libupgradedoc.parse_changes_block(REAL_MANIFEST)
    assert len(items) == 2
    assert items[0]["name"] == "ZAC (Zaakafhandelcomponent)"
    assert items[0]["app_source"] == "5.0.2"
    assert items[0]["app"] == "5.4.3"
    assert items[0]["chart_source"] == "1.0.297"
    assert items[0]["chart"] == "1.0.297"
    assert items[1]["name"] == "ZGW Office Add-in"
    assert items[1]["app_source"] == "v0.9.313"
    assert items[1]["app"] == "0.11.0"


def test_parse_changes_block_does_not_mistake_version_continuation_for_new_item(libupgradedoc):
    """Regression: "1.17.1-static -> 1.19.0-static" on an indented
    continuation line must not be parsed as a bogus item #17."""
    items = libupgradedoc.parse_changes_block(REAL_MANIFEST)
    names = [i["name"] for i in items]
    assert not any("17.1" in n for n in names)


def test_parse_changes_block_no_changes_section(libupgradedoc):
    assert libupgradedoc.parse_changes_block("# just a header\n# no changes block\n") == []


# --- check_images_manifest_format ---

DEPS = [
    make_dep("zaakafhandelcomponent", "1.0.297", alias="zac"),
    make_dep("zgw-office-addin", "0.0.92"),
]
VALUES = {"zac": {"image": {"tag": "5.4.3@sha256:aaa"}, "opa": {"image": {"tag": "1.19.0-static@sha256:bbb"}}}}


def test_images_manifest_format_passes_for_consistent_manifest(libdocsconsistency, tmp_path):
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(REAL_MANIFEST)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert issues == []


def test_images_manifest_format_missing_file(libdocsconsistency, tmp_path):
    issues = libdocsconsistency.check_images_manifest_format(tmp_path / "missing.yaml", "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert "does not exist" in issues[0]


def test_images_manifest_format_invalid_yaml(libdocsconsistency, tmp_path):
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text("- name: zac\n  bad: [\n")
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any("not valid YAML" in i for i in issues)


def test_images_manifest_format_missing_required_keys(libdocsconsistency, tmp_path):
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text("- name: zac\n  version: \"5.4.3\"\n")
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any("missing key" in i for i in issues)


def test_images_manifest_format_stale_baseline_header(libdocsconsistency, tmp_path):
    text = REAL_MANIFEST.replace("podiumd 4.8.5", "podiumd 4.8.2").replace(
        "4.9.0 vs 4.8.5", "4.9.0 vs 4.8.2")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any('baseline line says "4.8.2"' in i for i in issues)
    assert any('"... vs ..." line says upgrade_docs_baseline "4.8.2"' in i for i in issues)


def test_images_manifest_format_trailing_period_not_captured(libdocsconsistency, tmp_path):
    """Regression: the "vs" line ends with a bare period right after the
    baseline number ("vs 4.8.5."); it must not be captured as part of the
    version string."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(REAL_MANIFEST)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert not any("4.8.5." in i for i in issues)


def test_images_manifest_format_changes_block_target_mismatch(libdocsconsistency, tmp_path):
    text = REAL_MANIFEST.replace("5.0.2 -> 5.4.3 (chart 1.0.297", "5.0.2 -> 5.9.9 (chart 1.0.297")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any("target app" in i and "5.9.9" in i for i in issues)


def test_images_manifest_format_entry_comment_target_mismatch(libdocsconsistency, tmp_path):
    text = REAL_MANIFEST.replace(
        "# ZAC OPA sidecar — 1.17.1-static -> 1.19.0-static",
        "# ZAC OPA sidecar — 1.17.1-static -> 9.9.9-static",
    )
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any('comment says target "9.9.9-static"' in i for i in issues)


def test_images_manifest_format_missing_entry_comment(libdocsconsistency, tmp_path):
    text = REAL_MANIFEST.replace("# ZAC OPA sidecar — 1.17.1-static -> 1.19.0-static\n", "")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any('entry "opa" has no preceding comment' in i for i in issues)


ZGW_MANIFEST = """\
# Baseline: podiumd 4.8.5 (origin/feature/podiumd-4.8.5 @ f27a008).
#
# Images new or changed in podiumd 4.9.0 vs 4.8.5.
#
# Changes:
#   1. ZGW Office Add-in v0.9.313 -> v0.9.352 (chart 0.0.89, unchanged).

# ZGW Office Add-in — v0.9.313 -> v0.9.352
- name: zgw-office-addin-frontend
  url: ghcr.io/infonl/zgw-office-addin-frontend
  version: "v0.9.352"
  digest: "sha256:aaa"

- name: zgw-office-addin-backend
  url: ghcr.io/infonl/zgw-office-addin-backend
  version: "v0.9.352"
  digest: "sha256:bbb"
"""
ZGW_DEPS = [make_dep("zgw-office-addin", "0.0.89")]
ZGW_VALUES = {"zgw-office-addin": {
    "frontend": {"image": {"tag": "v0.9.352@sha256:aaa"}},
    "backend": {"image": {"tag": "v0.9.352@sha256:bbb"}},
}}


def test_images_manifest_format_multi_image_component_shares_one_comment(libdocsconsistency, tmp_path):
    """A multi-image component (zgw-office-addin's frontend + backend) needs
    only ONE preceding comment for the whole group — the second entry, with
    a blank line (not a comment) directly above it, must NOT be flagged as
    missing a comment of its own."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(ZGW_MANIFEST)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", ZGW_DEPS, ZGW_VALUES, {})
    assert issues == []


def test_images_manifest_format_source_vs_baseline(libdocsconsistency, tmp_path):
    baseline_values = {"zac": {"opa": {"image": {"tag": "1.17.1-static@sha256:old"}}}}
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(REAL_MANIFEST)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, baseline_values)
    assert issues == []


def test_images_manifest_format_source_vs_baseline_mismatch(libdocsconsistency, tmp_path):
    # baseline actually has a different starting version than the comment claims
    baseline_values = {"zac": {"opa": {"image": {"tag": "2.0.0-static@sha256:old"}}}}
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(REAL_MANIFEST)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, baseline_values)
    assert any('comment says source "1.17.1-static"' in i for i in issues)


# --- Changes items for plain images with no Chart.yaml dependency of their
# own (e.g. an init-container image) -- must fall back to this same
# manifest's own entries instead of being flagged as a missing dependency ---

PYTHON_MANIFEST = """\
# Baseline: podiumd 4.8.5 (origin/feature/podiumd-4.8.5 @ f27a008).
#
# Images new or changed in podiumd 4.9.0 vs 4.8.5.
#
# Changes:
#   1. Python (ensurePodiumdAdminUser init image) 3.14-slim -> 3.14.7-slim —
#      now pinned to a specific patch instead of the floating minor tag.
#
# See docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md for the operator upgrade notes.

# Python (ensurePodiumdAdminUser init image) — 3.14-slim -> 3.14.7-slim
- name: library/python
  url: docker.io/library/python
  version: "3.14.7-slim"
  digest: "sha256:ccc"
"""


def test_images_manifest_format_plain_image_changes_item_matches_entry(libdocsconsistency, tmp_path):
    """A Changes item for a plain image (no Chart.yaml dependency of its
    own) must not be flagged just because match_dependency finds nothing —
    it should resolve against this manifest's own "library/python" entry
    instead and pass, since the target versions agree."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(PYTHON_MANIFEST)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert issues == []


def test_images_manifest_format_plain_image_changes_item_target_mismatch(libdocsconsistency, tmp_path):
    """Once resolved to its entry, a real mismatch must still be caught."""
    text = PYTHON_MANIFEST.replace("3.14-slim -> 3.14.7-slim —", "3.14-slim -> 9.9.9 —")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any("target app" in i and "9.9.9" in i for i in issues)


def test_images_manifest_format_changes_item_matching_neither_dep_nor_entry_still_reported(
        libdocsconsistency, tmp_path):
    text = PYTHON_MANIFEST.replace(
        "Python (ensurePodiumdAdminUser init image)", "Totally Unknown Thing")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any('Totally Unknown Thing" — no matching Chart.yaml dependency or images-manifest entry' in i
               for i in issues)
