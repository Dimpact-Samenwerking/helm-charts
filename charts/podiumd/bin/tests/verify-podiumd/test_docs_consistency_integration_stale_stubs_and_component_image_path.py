"""End-to-end check_docs_consistency against a small, realistic podiumd-like
chart inside a real (hermetic, temp) git repo — exercises the full baseline
resolution + all the precheck/content-check stages together.

Split from test_docs_consistency_integration.py (pylint too-many-lines): this
file covers the 2 baseline sanity tests, the stale stub-placeholder findings,
and the component-specific image path sections."""

import subprocess

from pathlib import Path
from types import ModuleType

import pytest

CHART_YAML = """\
apiVersion: v2
name: podiumd
version: 4.9.0
dependencies:
  - name: zaakafhandelcomponent
    alias: zac
    version: 1.0.297
    repository: "@zac"
"""

UPGRADE_DOC = """\
# Upgrade guide: PodiumD {baseline} → 4.9.0

## Component versions (4.9.0 vs {baseline})

| Component | App version | Helm chart | Notes |
| --- | --- | --- | --- |
| ZAC (Zaakafhandelcomponent) | {app_source} → {app_target} | 1.0.297 (unchanged) | n/a |

See [`{baseline}-to-4.9.0-values-deltas.md`]({baseline}-to-4.9.0-values-deltas.md).
"""

GEMEENTE_DOC = "# Gemeente-specific notes — PodiumD {baseline} → 4.9.0\n\nNone.\n"
VALUES_DELTAS_DOC = (
    "# Values deltas — PodiumD {baseline} → 4.9.0\n\n"
    "## ZAC {app_source} → {app_target} (chart 1.0.297, unchanged) — image tag only\n\n"
    "No gemeente podiumd.yml changes are required for this hop.\n"
)
IMAGES_MANIFEST = """\
# Baseline: podiumd {baseline} (test @ 0000000).
#
# Images new or changed in podiumd 4.9.0 vs {baseline}.
#
# Changes:
#   1. ZAC (Zaakafhandelcomponent) {app_source} -> {app_target} (chart 1.0.297, unchanged).
#
# See docs/_UPGRADE_PATHS/{baseline}-to-4.9.0-upgrade.md for the operator upgrade notes.

# ZAC — {app_source} -> {app_target}
- name: zac
  url: ghcr.io/infonl/zaakafhandelcomponent
  version: "{app_target}"
  digest: "sha256:abc"
"""


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def values_yaml(app_version):
    return (
        f'zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "{app_version}@sha256:abc"\n'
    )


def test_fully_consistent_chart_passes_with_baseline(vp: ModuleType, chart_repo):
    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is True, detail


def test_fully_consistent_chart_passes_without_baseline(vp: ModuleType, chart_repo):
    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline=None)
    assert ok is True, detail


# --- stale stub-placeholder findings (see lib.component_docs.strip_stale_
# upgrade_placeholders/strip_stale_values_deltas_todo_stub/has_stale_
# gemeente_specific_placeholder) ---


def test_stale_upgrade_placeholder_is_reported_as_a_finding(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(doc.read_text() + "\n## Changes\n\nTODO\n\n### zac 5.0.2 → 5.4.3\n\nSome prose.\n")

    ok, _detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert ('4.8.5-to-4.9.0-upgrade.md: still has a stale "TODO" placeholder stranded alongside real content') in out


def test_bare_changes_todo_stub_with_no_real_block_is_not_flagged(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    """A "## Changes" section that STILL only has the bare TODO (no real
    "### ..." block yet) is the correct, expected state -- must not be
    reported as a stale-placeholder finding, matching strip_stale_
    upgrade_placeholders' own "must never be touched" guard. (Adding a
    bare "## Changes" section here also trips an unrelated, pre-existing
    check -- every table row needing its own "### ..." section once one
    exists at all -- so this only asserts on the specific finding this
    test cares about, not overall pass/fail.)"""
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(doc.read_text() + "\n## Changes\n\nTODO\n")

    vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")

    out = capsys.readouterr().out
    assert "still has a stale" not in out


def test_stale_values_deltas_placeholder_is_reported_as_a_finding(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-values-deltas.md"
    doc.write_text(
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
        "TODO: describe any gemeente `podiumd.yml` changes required for this hop.\n\n"
        "## ZAC 5.0.2 → 5.4.3 (chart 1.0.297, unchanged) — image tag only\n\n"
        "No gemeente podiumd.yml changes are required for this hop.\n"
    )

    ok, _detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert (
        "4.8.5-to-4.9.0-values-deltas.md: still has its own stale TODO placeholder "
        'stranded alongside a real "## ..." section'
    ) in out


def test_stale_gemeente_specific_placeholder_is_reported_as_a_finding(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    """Check-only finding -- nothing auto-fixes this one (see lib.
    component_docs.has_stale_gemeente_specific_placeholder's own
    docstring for why)."""
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-gemeente-specific.md"
    doc.write_text(
        "# Gemeente-specific notes — PodiumD 4.8.5 → 4.9.0\n\n"
        "_None recorded yet._\n\n"
        "## Utrecht (prod)\n\n"
        "- Some real finding.\n"
    )

    ok, _detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert (
        '4.8.5-to-4.9.0-gemeente-specific.md: still has its own stale "_None recorded yet._" '
        'placeholder stranded alongside a real "## <gemeente> (<env>)" section'
    ) in out


def test_bare_gemeente_specific_stub_with_no_real_section_is_not_flagged(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-gemeente-specific.md"
    doc.write_text("# Gemeente-specific notes — PodiumD 4.8.5 → 4.9.0\n\n_None recorded yet._\n")

    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is True, detail


def test_no_matching_docs_is_a_soft_pass(vp: ModuleType, tmp_path: Path):
    chart_dir = tmp_path / "charts" / "podiumd"
    (chart_dir / "docs" / "_UPGRADE_PATHS").mkdir(parents=True)
    (chart_dir / "docs" / "images").mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(CHART_YAML)
    (chart_dir / "values.yaml").write_text(values_yaml("5.4.3"))
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is True
    assert "skipped" in detail


def test_unmatched_row_is_reported_as_a_wrong_phrasing_mismatch(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    """A row that matches neither a Chart.yaml dependency nor a
    canonical sidecar/shared-image name (see
    lib.chart.canonical_sidecar_row_names) is a real, reportable
    mismatch now — not a silently-skipped info print. "Keycloak" isn't
    a dependency this fixture's Chart.yaml has at all, and doesn't
    match the "<component> - <basename>"/"<basename>" form
    update-image-version itself writes."""
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(doc.read_text() + "| Keycloak | 1.0.0 → 1.0.1 | 1.0.0 (unchanged) | n/a |\n")

    ok, _detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert (
        '4.8.5-to-4.9.0-upgrade.md: doc row "Keycloak" does not match a Chart.yaml dependency '
        "or a canonical sidecar/shared-image name"
    ) in out


def test_duplicate_row_names_are_reported(vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]):
    """Two rows with the literal same name are always wrong, whatever
    they resolve to — a leftover/typo'd duplicate."""
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(doc.read_text() + "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.4.3 | 1.0.297 (unchanged) | dup |\n")

    ok, _detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert (
        '4.8.5-to-4.9.0-upgrade.md: doc row "ZAC (Zaakafhandelcomponent)" is wrong or stale — '
        "not found in Chart.yaml or values.yaml"
    ) in out


def test_exact_dependency_match_wins_over_a_fuzzy_duplicate_claim(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    """A row that only fuzzy-matches a real dependency (e.g. the real-
    world "Kiss Elasticsearch" row fuzzy-matching "kiss") must be
    flagged as wrong once ANOTHER row exactly names that same
    dependency — even when the fuzzy row's own app/chart cells already
    happen to equal the dependency's own actual version, so the
    ordinary per-row content check alone would never catch it."""
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(doc.read_text() + "| zac | 5.0.2 → 5.4.3 | 1.0.297 (unchanged) | exact match |\n")

    ok, _detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert (
        '4.8.5-to-4.9.0-upgrade.md: doc row "ZAC (Zaakafhandelcomponent)" is wrong or stale — '
        "not found in Chart.yaml or values.yaml"
    ) in out
    # The exact row itself, with correct data, is never flagged.
    assert 'doc row "zac" ' not in out


def test_wrong_target_version_in_doc_is_caught(vp: ModuleType, chart_repo):
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(UPGRADE_DOC.format(baseline="4.8.5", app_source="5.0.2", app_target="5.9.9"))
    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is False
    assert "mismatch" in detail


def test_wrong_source_version_vs_baseline_is_caught(vp: ModuleType, chart_repo):
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(UPGRADE_DOC.format(baseline="4.8.5", app_source="9.9.9", app_target="5.4.3"))
    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is False
    assert "mismatch" in detail


def test_unresolvable_baseline_is_caught(vp: ModuleType, chart_repo):
    ok, _detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="9.9.9")
    assert ok is False


def test_undocumented_new_component_is_caught_everywhere(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    """A component added to Chart.yaml + values.yaml after the baseline, but
    never added to any doc, must be flagged as missing from the upgrade.md
    table, from values-deltas.md, and from the images manifest — not
    silently skipped just because no doc mentions it yet."""
    (chart_repo / "Chart.yaml").write_text(
        CHART_YAML + '  - name: openformulieren\n    version: "1.12.0"\n    repository: "@openformulieren"\n'
    )
    (chart_repo / "values.yaml").write_text(
        values_yaml("5.4.3")
        + 'openformulieren:\n  image:\n    repository: openformulieren/open-forms\n    tag: "3.5.6@sha256:cccc"\n'
    )

    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is False
    assert "mismatch" in detail

    out = capsys.readouterr().out
    assert 'component "openformulieren" changed vs' in out
    assert 'has no row in the "Component versions" table' in out
    assert 'has no "## ..." section of its own' in out
    assert "openformulieren" in out and "changed vs 4.8.5 but has no entry" in out


def test_component_with_only_a_new_sidecar_of_its_own_is_not_flagged_missing_a_row(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Regression test: zac gaining a brand-new sidecar of its own
    (opentelemetry-collector-contrib) with its OWN app+chart both
    unchanged must NOT be flagged "changed vs baseline but has no
    row" — that sidecar already needs (and gets, via fix-doc-
    consistency) its own separate row; a redundant row for zac itself
    would be noise, so check-doc must not DEMAND one either (see
    lib.component_docs.resolve_component_own_version_change, shared
    with fix-doc-consistency's own add_missing_component_rows so the
    two can never drift on which components actually need a row)."""
    repo_root = tmp_path
    chart_dir = repo_root / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    images_dir = chart_dir / "docs" / "images"
    for d in (doc_dir, images_dir):
        d.mkdir(parents=True)

    git("init", "-q", cwd=repo_root)
    git("config", "user.email", "test@example.com", cwd=repo_root)
    git("config", "user.name", "Test", cwd=repo_root)

    (chart_dir / "Chart.yaml").write_text(CHART_YAML)
    (chart_dir / "values.yaml").write_text(values_yaml("5.4.3"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "baseline", cwd=repo_root)
    git("tag", "podiumd-4.8.5", cwd=repo_root)

    # zac's own app version is unchanged; it just gains a brand-new sidecar.
    (chart_dir / "values.yaml").write_text(
        "zac:\n"
        "  image:\n"
        "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
        '    tag: "5.4.3@sha256:abc"\n'
        "  otel:\n"
        "    image:\n"
        "      repository: otel/opentelemetry-collector-contrib\n"
        '      tag: "0.158.0@sha256:def"\n'
    )
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n\n"
    )
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\nNo gemeente `podiumd.yml` changes are required for this hop.\n"
    )
    (images_dir / "images-4.9.0.yaml").write_text(
        "# Baseline: podiumd 4.8.5 (test @ 0000000).\n#\n"
        "# Images new or changed in podiumd 4.9.0 vs 4.8.5.\n#\n# Zero changes:\n#\n\n[]\n"
    )
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "zac gains a brand-new otel sidecar", cwd=repo_root)

    vp.check_docs_consistency(chart_dir, upgrade_docs_baseline="4.8.5")

    out = capsys.readouterr().out
    assert 'component "zac" changed vs 4.8.5 but has no row' not in out


def test_images_manifest_entry_with_no_real_change_is_caught(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    """The images manifest must list the EXACT set of changed images —
    an entry that doesn't resolve to any real values-tree image at all
    (typo'd or stale name) is flagged with the same "wrong or stale —
    not found" wording used for a -upgrade.md row that names no real
    component (see find_images_manifest_list_diff's unmatched_entry_
    names), not the "did not change" message reserved for an entry that
    DOES resolve to a real, merely-unchanged path."""
    images_path = chart_repo / "docs" / "images" / "images-4.9.0.yaml"
    images_path.write_text(
        images_path.read_text()
        + (
            "\n# stale entry — does not correspond to any actual change\n"
            "- name: does-not-exist\n"
            "  url: ghcr.io/infonl/does-not-exist\n"
            '  version: "1.0.0"\n'
            '  digest: "sha256:deadbeef"\n'
        )
    )

    ok, _detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is False

    out = capsys.readouterr().out
    assert ('entry "does-not-exist" is wrong or stale — not found in Chart.yaml or values.yaml') in out


def test_images_manifest_entry_missing_version_or_digest_is_reported_not_crashed(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    """With no bare-version baseline, check_images_manifest_format's key
    precheck never runs, so the entry loop is what first touches
    entry["version"]/entry["digest"] — a manifest entry missing one must
    produce a mismatch line, not a KeyError that aborts the whole check."""
    images_path = chart_repo / "docs" / "images" / "images-4.9.0.yaml"
    images_path.write_text(images_path.read_text().replace('  digest: "sha256:abc"\n', ""))

    ok, _detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline=None)
    assert ok is False
    out = capsys.readouterr().out
    assert 'zac: entry in images-4.9.0.yaml is missing "version" or "digest"' in out


def test_images_manifest_missing_changes_header_entirely_is_caught(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    """Regression test (real bug, real doc): a manifest with real entries
    but no "# Changes:" header anywhere at all (see lib.component_docs.
    ensure_images_manifest_changes_header's own docstring — real case:
    images-4.9.1.yaml gained 5 real entries this session with no header
    ever created for them to be listed in) must be flagged directly and
    unambiguously — never silently pass just because every individual
    entry happens to resolve cleanly otherwise."""
    images_path = chart_repo / "docs" / "images" / "images-4.9.0.yaml"
    text = images_path.read_text(encoding="utf-8")
    assert "# Changes:" in text
    stripped = "\n".join(line for line in text.splitlines() if "# Changes:" not in line and "#   1." not in line)
    images_path.write_text(stripped, encoding="utf-8")

    ok, _detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is False

    out = capsys.readouterr().out
    assert (
        'images-4.9.0.yaml: has 1 entry but no "# Changes:" header at all — every real change is '
        "undocumented in the summary list"
    ) in out


def test_images_manifest_format_issue_does_not_swallow_other_mismatches(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    """A format problem in images-<target>.yaml (e.g. a stale header
    comment) must not discard mismatches an earlier, completely unrelated
    check already found — like a component's own row going unmatched (see
    match_dependency) and so never being counted as covering a change
    already recorded in Chart.yaml/values.yaml. Both must be reported
    together in the same run, not one hiding the other."""
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(doc.read_text().replace("ZAC (Zaakafhandelcomponent)", "Some Unrelated Name"))

    images_path = chart_repo / "docs" / "images" / "images-4.9.0.yaml"
    images_path.write_text(images_path.read_text().replace("Baseline: podiumd 4.8.5", "Baseline: podiumd 9.9.9"))

    ok, _detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    out = capsys.readouterr().out

    assert ok is False
    assert 'component "zac" changed vs' in out
    assert 'has no row in the "Component versions" table' in out
    assert 'upgrade_docs_baseline line says "9.9.9", expected "4.8.5"' in out


def test_stale_pointer_reference_does_not_block_every_other_check(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    """A stale sibling-doc reference (a scar from an earlier, incomplete
    baseline rebase — the doc file itself was renamed, but an in-text
    link to its OLD name was never updated) used to make
    check_pointer_consistency's own precheck early-return immediately,
    so NOTHING else in check_docs_consistency ever ran at all — not the
    "Component versions" table check, not the values-deltas mention
    check, nothing. A single broken link anywhere could hide every real
    problem in the doc set. Both the pointer issue and an unrelated,
    already-present mismatch must now be reported together."""
    gemeente = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-gemeente-specific.md"
    gemeente.write_text(gemeente.read_text() + "\nSee [4.8.3-to-4.9.0-upgrade.md](4.8.3-to-4.9.0-upgrade.md).\n")

    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(doc.read_text().replace("ZAC (Zaakafhandelcomponent)", "Some Unrelated Name"))

    ok, _detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    out = capsys.readouterr().out

    assert ok is False
    assert (
        'reference "4.8.3-to-4.9.0-upgrade.md" targets podiumd 4.9.0 but its upgrade_docs_baseline '
        'is "4.8.3", expected "4.8.5"'
    ) in out
    assert 'component "zac" changed vs' in out
    assert 'has no row in the "Component versions" table' in out


# --- component-specific image path (a component whose real app image
# lives at a non-default path from lib.chart.COMPONENT_IMAGE_PATHS,
# resolved via image_paths_for rather than actual_app_version's own
# hardcoded shapes) ---

KEYCLOAK_CHART_YAML = """\
apiVersion: v2
name: podiumd
version: 4.9.0
dependencies:
  - name: keycloak-operator
    version: 1.12.1
    repository: "@adfinis"
"""

KEYCLOAK_UPGRADE_DOC = """\
# Upgrade guide: PodiumD {baseline} → 4.9.0

## Component versions (4.9.0 vs {baseline})

| Component | App version | Helm chart | Notes |
| --- | --- | --- | --- |
| keycloak-operator | - | 1.12.1 (unchanged) | - |

See [`{baseline}-to-4.9.0-values-deltas.md`]({baseline}-to-4.9.0-values-deltas.md).
"""
KEYCLOAK_GEMEENTE_DOC = "# Gemeente-specific notes — PodiumD {baseline} → 4.9.0\n\nNone.\n"
KEYCLOAK_VALUES_DELTAS_DOC = (
    "# Values deltas — PodiumD {baseline} → 4.9.0\n\nNo gemeente podiumd.yml changes are required for this hop.\n"
)


def keycloak_values(tag):
    return f'keycloak-operator:\n  operator:\n    config:\n      keycloakImage:\n        tag: "{tag}"\n'


@pytest.fixture
def keycloak_chart_repo(tmp_path: Path):
    """keycloak-operator's own real primary app image lives at the
    non-standard "operator.config.keycloakImage.tag" split-path
    convention, registered in lib.chart.COMPONENT_IMAGE_PATHS — the
    real-world case that used to be invisible to actual_app_version's
    own two hardcoded shapes (<key>.image.tag, frontend/backend), and
    is why the doc row below (app version pinned at "-") must now be
    flagged as a mismatch instead of silently skipped."""
    repo_root = tmp_path
    chart_dir = repo_root / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)

    git("init", "-q", cwd=repo_root)
    git("config", "user.email", "test@example.com", cwd=repo_root)
    git("config", "user.name", "Test", cwd=repo_root)

    (chart_dir / "Chart.yaml").write_text(KEYCLOAK_CHART_YAML)
    (chart_dir / "values.yaml").write_text(keycloak_values("26.6.4"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "baseline", cwd=repo_root)
    git("tag", "podiumd-4.8.5", cwd=repo_root)

    (chart_dir / "values.yaml").write_text(keycloak_values("26.7.2"))
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(KEYCLOAK_UPGRADE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(KEYCLOAK_GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(KEYCLOAK_VALUES_DELTAS_DOC.format(baseline="4.8.5"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "bump keycloak-operator app image, row left unresolved", cwd=repo_root)

    return chart_dir


def test_component_specific_image_path_mismatch_is_flagged_not_silently_skipped(
    vp: ModuleType, keycloak_chart_repo, capsys: pytest.CaptureFixture[str]
):
    """The doc row pins app version "-" while values.yaml actually has
    "26.7.2" at keycloak-operator's own registered image path — this
    must surface as a normal target-app mismatch, not be silently
    skipped just because the doc cell was empty."""
    ok, _detail = vp.check_docs_consistency(keycloak_chart_repo, upgrade_docs_baseline="4.8.5")
    out = capsys.readouterr().out

    assert ok is False
    assert (
        'keycloak-operator ("keycloak-operator") target app: values.yaml image tag is "26.7.2", '
        '4.8.5-to-4.9.0-upgrade.md says "-"'
    ) in out


# --- a row unchanged vs baseline ---


def test_row_unchanged_vs_baseline_is_reported(vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]):
    """ZAC reset to its baseline 5.0.2 (chart 1.0.297 on both sides), but
    the upgrade doc still has a row for it: nothing changed, so the row
    must go."""
    (chart_repo / "values.yaml").write_text(values_yaml("5.0.2"))
    upgrade_path = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    upgrade_path.write_text(
        upgrade_path.read_text().replace(
            "| 5.0.2 → 5.4.3 | 1.0.297 (unchanged) |", "| 5.0.2 (unchanged) | 1.0.297 (unchanged) |"
        )
    )
    ok, _detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is False
    out = capsys.readouterr().out
    assert 'doc row "ZAC (Zaakafhandelcomponent)" is unchanged vs podiumd-4.8.5' in out


def test_row_with_changed_app_is_not_reported_as_unchanged(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    """chart_repo's own ZAC row: chart unchanged, app 5.0.2 -> 5.4.3."""
    vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert "is unchanged vs" not in capsys.readouterr().out
