"""End-to-end check_docs_consistency against a small, realistic podiumd-like
chart inside a real (hermetic, temp) git repo — exercises the full baseline
resolution + all the precheck/content-check stages together."""
import subprocess

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
VALUES_DELTAS_DOC = ("# Values deltas — PodiumD {baseline} → 4.9.0\n\n"
                      "- **ZAC** app `{app_source} → {app_target}` (chart `1.0.297`, unchanged) "
                      "— image tag only.\n\n"
                      "No gemeente podiumd.yml changes are required for this hop.\n")
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
    return (f'zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n'
            f'    tag: "{app_version}@sha256:abc"\n')


@pytest.fixture
def chart_repo(tmp_path):
    """Baseline commit (tagged podiumd-4.8.5) has ZAC 5.0.2; HEAD bumps it to
    5.4.3 and updates the matching docs to describe that exact change."""
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
    (chart_dir / "values.yaml").write_text(values_yaml("5.0.2"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "baseline", cwd=repo_root)
    git("tag", "podiumd-4.8.5", cwd=repo_root)

    (chart_dir / "values.yaml").write_text(values_yaml("5.4.3"))
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        UPGRADE_DOC.format(baseline="4.8.5", app_source="5.0.2", app_target="5.4.3"))
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(
        VALUES_DELTAS_DOC.format(baseline="4.8.5", app_source="5.0.2", app_target="5.4.3"))
    (images_dir / "images-4.9.0.yaml").write_text(
        IMAGES_MANIFEST.format(baseline="4.8.5", app_source="5.0.2", app_target="5.4.3"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "bump zac to 5.4.3", cwd=repo_root)

    return chart_dir


def test_fully_consistent_chart_passes_with_baseline(vp, chart_repo):
    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is True, detail


def test_fully_consistent_chart_passes_without_baseline(vp, chart_repo):
    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline=None)
    assert ok is True, detail


def test_no_matching_docs_is_a_soft_pass(vp, tmp_path):
    chart_dir = tmp_path / "charts" / "podiumd"
    (chart_dir / "docs" / "_UPGRADE_PATHS").mkdir(parents=True)
    (chart_dir / "docs" / "images").mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(CHART_YAML)
    (chart_dir / "values.yaml").write_text(values_yaml("5.4.3"))
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is True
    assert "skipped" in detail


def test_unmatched_row_is_reported_as_a_wrong_phrasing_mismatch(vp, chart_repo, capsys):
    """A row that matches neither a Chart.yaml dependency nor a
    canonical sidecar/shared-image name (see
    lib.chart.canonical_sidecar_row_names) is a real, reportable
    mismatch now — not a silently-skipped info print. "Keycloak" isn't
    a dependency this fixture's Chart.yaml has at all, and doesn't
    match the "<component> - <basename>"/"<basename>" form
    update-image-version itself writes."""
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(doc.read_text() + "| Keycloak | 1.0.0 → 1.0.1 | 1.0.0 (unchanged) | n/a |\n")

    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert ('4.8.5-to-4.9.0-upgrade.md: doc row "Keycloak" does not match a Chart.yaml dependency '
            'or a canonical sidecar/shared-image name') in out


def test_duplicate_row_names_are_reported(vp, chart_repo, capsys):
    """Two rows with the literal same name are always wrong, whatever
    they resolve to — a leftover/typo'd duplicate."""
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(doc.read_text() + "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.4.3 | 1.0.297 (unchanged) | dup |\n")

    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert ('4.8.5-to-4.9.0-upgrade.md: doc row "ZAC (Zaakafhandelcomponent)" is wrong or stale — '
            'not found in Chart.yaml or values.yaml') in out


def test_exact_dependency_match_wins_over_a_fuzzy_duplicate_claim(vp, chart_repo, capsys):
    """A row that only fuzzy-matches a real dependency (e.g. the real-
    world "Kiss Elasticsearch" row fuzzy-matching "kiss") must be
    flagged as wrong once ANOTHER row exactly names that same
    dependency — even when the fuzzy row's own app/chart cells already
    happen to equal the dependency's own actual version, so the
    ordinary per-row content check alone would never catch it."""
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(doc.read_text() + "| zac | 5.0.2 → 5.4.3 | 1.0.297 (unchanged) | exact match |\n")

    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert ('4.8.5-to-4.9.0-upgrade.md: doc row "ZAC (Zaakafhandelcomponent)" is wrong or stale — '
            'not found in Chart.yaml or values.yaml') in out
    # The exact row itself, with correct data, is never flagged.
    assert 'doc row "zac" ' not in out


def test_wrong_target_version_in_doc_is_caught(vp, chart_repo):
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(UPGRADE_DOC.format(baseline="4.8.5", app_source="5.0.2", app_target="5.9.9"))
    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is False
    assert "mismatch" in detail


def test_wrong_source_version_vs_baseline_is_caught(vp, chart_repo):
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(UPGRADE_DOC.format(baseline="4.8.5", app_source="9.9.9", app_target="5.4.3"))
    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is False
    assert "mismatch" in detail


def test_unresolvable_baseline_is_caught(vp, chart_repo):
    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="9.9.9")
    assert ok is False


def test_undocumented_new_component_is_caught_everywhere(vp, chart_repo, capsys):
    """A component added to Chart.yaml + values.yaml after the baseline, but
    never added to any doc, must be flagged as missing from the upgrade.md
    table, from values-deltas.md, and from the images manifest — not
    silently skipped just because no doc mentions it yet."""
    (chart_repo / "Chart.yaml").write_text(
        CHART_YAML + '  - name: openformulieren\n    version: "1.12.0"\n    repository: "@openformulieren"\n')
    (chart_repo / "values.yaml").write_text(
        values_yaml("5.4.3") +
        'openformulieren:\n  image:\n    repository: openformulieren/open-forms\n    tag: "3.5.6@sha256:cccc"\n')

    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is False
    assert "mismatch" in detail

    out = capsys.readouterr().out
    assert 'component "openformulieren" changed vs' in out
    assert 'has no row in the "Component versions" table' in out
    assert 'is not mentioned anywhere in the doc' in out
    assert "openformulieren" in out and 'changed vs 4.8.5 but has no entry' in out


def test_images_manifest_entry_with_no_real_change_is_caught(vp, chart_repo, capsys):
    """The images manifest must list the EXACT set of changed images —
    an entry that doesn't resolve to any real values-tree image (typo'd
    or stale name) is flagged as extra, not silently accepted."""
    images_path = chart_repo / "docs" / "images" / "images-4.9.0.yaml"
    images_path.write_text(images_path.read_text() + (
        '\n# stale entry — does not correspond to any actual change\n'
        '- name: does-not-exist\n'
        '  url: ghcr.io/infonl/does-not-exist\n'
        '  version: "1.0.0"\n'
        '  digest: "sha256:deadbeef"\n'
    ))

    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is False

    out = capsys.readouterr().out
    assert ('entry "does-not-exist" is listed but its image did not change vs 4.8.5') in out


def test_images_manifest_format_issue_does_not_swallow_other_mismatches(vp, chart_repo, capsys):
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

    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    out = capsys.readouterr().out

    assert ok is False
    assert 'component "zac" changed vs' in out
    assert 'has no row in the "Component versions" table' in out
    assert 'upgrade_docs_baseline line says "9.9.9", expected "4.8.5"' in out


def test_stale_pointer_reference_does_not_block_every_other_check(vp, chart_repo, capsys):
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

    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    out = capsys.readouterr().out

    assert ok is False
    assert ('reference "4.8.3-to-4.9.0-upgrade.md" targets podiumd 4.9.0 but its upgrade_docs_baseline '
            'is "4.8.3", expected "4.8.5"') in out
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
KEYCLOAK_VALUES_DELTAS_DOC = ("# Values deltas — PodiumD {baseline} → 4.9.0\n\n"
                              "No gemeente podiumd.yml changes are required for this hop.\n")


def keycloak_values(tag):
    return f'keycloak-operator:\n  operator:\n    config:\n      keycloakImage:\n        tag: "{tag}"\n'


@pytest.fixture
def keycloak_chart_repo(tmp_path):
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


def test_component_specific_image_path_mismatch_is_flagged_not_silently_skipped(vp, keycloak_chart_repo, capsys):
    """The doc row pins app version "-" while values.yaml actually has
    "26.7.2" at keycloak-operator's own registered image path — this
    must surface as a normal target-app mismatch, not be silently
    skipped just because the doc cell was empty."""
    ok, detail = vp.check_docs_consistency(keycloak_chart_repo, upgrade_docs_baseline="4.8.5")
    out = capsys.readouterr().out

    assert ok is False
    assert ('keycloak-operator ("keycloak-operator") target app: values.yaml image tag is "26.7.2", '
            '4.8.5-to-4.9.0-upgrade.md says "-"') in out


# --- sidecar image (not a dependency's own primary image, but nested
# under it) -- doc row named "<values_key> - <basename>", the exact
# canonical form update-image-version writes (see
# lib.chart.canonical_sidecar_row_names) ---

REDIS_CHART_YAML = """\
apiVersion: v2
name: podiumd
version: 4.9.0
dependencies:
  - name: redis-operator
    version: 0.26.1
    repository: "@ot-helm"
"""

REDIS_UPGRADE_DOC = """\
# Upgrade guide: PodiumD {baseline} → 4.9.0

## Component versions (4.9.0 vs {baseline})

| Component | App version | Helm chart | Notes |
| --- | --- | --- | --- |
| redis-operator - redis | {app_source} → {app_target} | - | ACR mirror only |

See [`{baseline}-to-4.9.0-values-deltas.md`]({baseline}-to-4.9.0-values-deltas.md).
"""
REDIS_GEMEENTE_DOC = "# Gemeente-specific notes — PodiumD {baseline} → 4.9.0\n\nNone.\n"
REDIS_VALUES_DELTAS_DOC = ("# Values deltas — PodiumD {baseline} → 4.9.0\n\n"
                            "- **redis-operator** app `{app_source} → {app_target}` — image tag only.\n\n"
                            "No gemeente podiumd.yml changes are required for this hop.\n")
REDIS_IMAGES_MANIFEST = """\
# Baseline: podiumd {baseline} (test @ 0000000).
#
# Images new or changed in podiumd 4.9.0 vs {baseline}.
#
# Changes:
#   1. redis-ha {app_source} -> {app_target}
#
# See docs/_UPGRADE_PATHS/{baseline}-to-4.9.0-upgrade.md for the operator upgrade notes.

# redis-ha — {app_source} -> {app_target}
- name: redis-ha
  url: quay.io/opstree/redis
  version: "{app_target}"
  digest: "sha256:abc"
"""


def redis_values(tag):
    return (f'redis-operator:\n  redis-ha:\n    image:\n      repository: quay.io/opstree/redis\n'
            f'      tag: "{tag}@sha256:abc"\n')


@pytest.fixture
def redis_sidecar_chart_repo(tmp_path):
    """redis-ha's own image is nested under the "redis-operator"
    dependency's own values — not that dependency's own registered
    primary image (image_paths_for defaults to "image", which doesn't
    exist here at all) — a sidecar, matched only via
    canonical_sidecar_row_names, never match_dependency."""
    repo_root = tmp_path
    chart_dir = repo_root / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    images_dir = chart_dir / "docs" / "images"
    for d in (doc_dir, images_dir):
        d.mkdir(parents=True)

    git("init", "-q", cwd=repo_root)
    git("config", "user.email", "test@example.com", cwd=repo_root)
    git("config", "user.name", "Test", cwd=repo_root)

    (chart_dir / "Chart.yaml").write_text(REDIS_CHART_YAML)
    (chart_dir / "values.yaml").write_text(redis_values("8.6.2"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "baseline", cwd=repo_root)
    git("tag", "podiumd-4.8.5", cwd=repo_root)

    (chart_dir / "values.yaml").write_text(redis_values("8.6.6"))
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        REDIS_UPGRADE_DOC.format(baseline="4.8.5", app_source="8.6.2", app_target="8.6.6"))
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(REDIS_GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(
        REDIS_VALUES_DELTAS_DOC.format(baseline="4.8.5", app_source="8.6.2", app_target="8.6.6"))
    (images_dir / "images-4.9.0.yaml").write_text(
        REDIS_IMAGES_MANIFEST.format(baseline="4.8.5", app_source="8.6.2", app_target="8.6.6"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "bump redis-ha's redis image, row uses canonical sidecar name", cwd=repo_root)

    return chart_dir


def test_sidecar_row_with_canonical_name_is_verified(vp, redis_sidecar_chart_repo):
    ok, detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is True, detail


def test_sidecar_row_wrong_target_app_is_caught(vp, redis_sidecar_chart_repo, capsys):
    doc = redis_sidecar_chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(REDIS_UPGRADE_DOC.format(baseline="4.8.5", app_source="8.6.2", app_target="9.9.9"))

    ok, detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert ('redis-operator.redis-ha.image ("redis-operator - redis") target app: values.yaml image tag is '
            '"8.6.6", 4.8.5-to-4.9.0-upgrade.md says "9.9.9"') in out


def test_sidecar_row_wrong_source_app_vs_baseline_is_caught(vp, redis_sidecar_chart_repo, capsys):
    doc = redis_sidecar_chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(REDIS_UPGRADE_DOC.format(baseline="4.8.5", app_source="1.1.1", app_target="8.6.6"))

    ok, detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert ('redis-operator.redis-ha.image ("redis-operator - redis") source app: podiumd-4.8.5 has "8.6.2", '
            '4.8.5-to-4.9.0-upgrade.md says "1.1.1"') in out


def test_sidecar_row_with_old_style_phrasing_is_flagged_as_wrong_phrasing(vp, redis_sidecar_chart_repo, capsys):
    """A row naming the same real sidecar image, but NOT in the exact
    canonical "<values_key> - <basename>" form update-image-version
    writes, is now a reportable mismatch — not silently skipped, and
    not fuzzy-matched into "close enough" either."""
    doc = redis_sidecar_chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(doc.read_text().replace("redis-operator - redis", "Redis (redis-ha)"))

    ok, detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert ('4.8.5-to-4.9.0-upgrade.md: doc row "Redis (redis-ha)" does not match a Chart.yaml '
            'dependency or a canonical sidecar/shared-image name') in out


def test_sidecar_with_no_row_at_all_is_caught_as_missing(vp, redis_sidecar_chart_repo, capsys):
    """A changed sidecar image with NO row at all — not even a wrongly-
    phrased one — must still be flagged: the dependency's own row
    doesn't exist here either, so the existing "component changed but
    has no row" check (which only tracks top-level keys) has nothing to
    anchor on; this needs its own per-sidecar-path check."""
    doc = redis_sidecar_chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "See [`4.8.5-to-4.9.0-values-deltas.md`](4.8.5-to-4.9.0-values-deltas.md).\n"
    )

    ok, detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert ('4.8.5-to-4.9.0-upgrade.md: sidecar/shared image "redis-operator - redis" changed vs '
            'podiumd-4.8.5 but has no row in the "Component versions" table') in out


def test_sidecar_missing_from_images_manifest_uses_canonical_name(vp, redis_sidecar_chart_repo, capsys):
    """A changed sidecar image with no images-manifest entry at all is
    reported under its canonical "<values_key> - <basename>" name (the
    same name every other check/row/heading for this sidecar already
    uses) — never the raw dotted values.yaml path."""
    images_path = redis_sidecar_chart_repo / "docs" / "images" / "images-4.9.0.yaml"
    images_path.write_text(
        "# Baseline: podiumd 4.8.5 (test @ 0000000).\n"
        "#\n"
        "# Images new or changed in podiumd 4.9.0 vs 4.8.5.\n"
        "#\n"
        "# Changes: none.\n"
        "#\n"
        "# See docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md for the operator upgrade notes.\n"
        "[]\n"
    )

    ok, detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert 'image "redis-operator - redis" changed vs 4.8.5 but has no entry' in out
    assert "redis-operator.redis-ha.image" not in out


def test_orphan_top_level_block_sharing_a_dependencys_sidecar_repository_is_covered(
        vp, redis_sidecar_chart_repo, capsys):
    """A top-level values.yaml block with no Chart.yaml dependency of its
    own at all (podiumd's own directly-templated "apiproxy"/
    "frankgateway"/"keycloak" blocks are the real cases) that shares the
    exact same repository as a real dependency's own sidecar (e.g. both
    alias the same shared global.images.nginx anchor) is covered by that
    ONE sidecar's own manifest entry too — not flagged as its own,
    separate "changed but has no entry" gap just because it isn't rooted
    at a known Chart.yaml dependency."""
    values_path = redis_sidecar_chart_repo / "values.yaml"
    values_path.write_text(
        values_path.read_text() +
        'apiproxy:\n  image:\n    repository: quay.io/opstree/redis\n    tag: "8.6.6@sha256:abc"\n'
    )

    ok, detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is True, detail
    out = capsys.readouterr().out
    assert "apiproxy" not in out


REDIS_TWO_IMAGES_VALUES_TMPL = (
    "redis-operator:\n"
    "  redis-ha:\n"
    "    image:\n"
    "      repository: quay.io/opstree/redis\n"
    '      tag: "{redis_tag}@sha256:aaaa"\n'
    "    redisExporter:\n"
    "      image:\n"
    "        repository: quay.io/opstree/redis-exporter\n"
    '        tag: "{exporter_tag}@sha256:bbbb"\n'
)


def test_unchanged_sidecar_with_no_row_is_not_flagged(vp, tmp_path, capsys):
    """Only the sidecar image that actually CHANGED vs baseline gets
    flagged as missing a row — a sibling sidecar with no row of its own
    but an UNCHANGED tag is correctly left alone, same "only report a
    real gap" rule the top-level "component changed but has no row"
    check already follows."""
    repo_root = tmp_path
    chart_dir = repo_root / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    images_dir = chart_dir / "docs" / "images"
    for d in (doc_dir, images_dir):
        d.mkdir(parents=True)

    git("init", "-q", cwd=repo_root)
    git("config", "user.email", "test@example.com", cwd=repo_root)
    git("config", "user.name", "Test", cwd=repo_root)

    (chart_dir / "Chart.yaml").write_text(REDIS_CHART_YAML)
    (chart_dir / "values.yaml").write_text(
        REDIS_TWO_IMAGES_VALUES_TMPL.format(redis_tag="8.6.2", exporter_tag="1.82.0"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "baseline", cwd=repo_root)
    git("tag", "podiumd-4.8.5", cwd=repo_root)

    # redis-ha's own redis image changes; redisExporter does not.
    (chart_dir / "values.yaml").write_text(
        REDIS_TWO_IMAGES_VALUES_TMPL.format(redis_tag="8.6.6", exporter_tag="1.82.0"))
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - redis | 8.6.2 → 8.6.6 | - | ACR mirror only |\n\n"
        "See [`4.8.5-to-4.9.0-values-deltas.md`](4.8.5-to-4.9.0-values-deltas.md).\n"
    )
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(REDIS_GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(
        REDIS_VALUES_DELTAS_DOC.format(baseline="4.8.5", app_source="8.6.2", app_target="8.6.6"))
    (images_dir / "images-4.9.0.yaml").write_text(
        REDIS_IMAGES_MANIFEST.format(baseline="4.8.5", app_source="8.6.2", app_target="8.6.6"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "bump redis-ha's redis image only", cwd=repo_root)

    vp.check_docs_consistency(chart_dir, upgrade_docs_baseline="4.8.5")

    out = capsys.readouterr().out
    assert "redis-operator - redis-exporter" not in out


JOB_TWO_IMAGES_VALUES_TMPL = (
    "redis-operator:\n"
    "  jobs:\n"
    "    setup:\n"
    "      image:\n"
    "        repository: quay.io/opstree/redis\n"
    '        tag: "8.6.2@sha256:aaaa"\n'
    "      initImage:\n"
    "        repository: quay.io/opstree/redis-init\n"
    '        tag: "{init_tag}@sha256:bbbb"\n'
)


def test_sidecar_app_version_resolved_from_its_own_trailing_image_key(vp, tmp_path):
    """A sidecar whose trailing values-tree key is NOT literally "image"
    (e.g. "initImage", sitting right next to a sibling "image" key in the
    very same job) must be compared against ITS OWN tag — not a hardcoded
    ".image.tag" guess, which would silently grab the sibling "image"
    key's tag instead and report a bogus mismatch. No baseline/images-
    manifest machinery involved here on purpose — this is purely about
    resolving the CURRENT tag from the right path (that's a separate,
    unrelated fuzzy matcher — see resolve_entry_path)."""
    chart_dir = tmp_path / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (chart_dir / "docs" / "images").mkdir(parents=True)

    (chart_dir / "Chart.yaml").write_text(REDIS_CHART_YAML)
    (chart_dir / "values.yaml").write_text(JOB_TWO_IMAGES_VALUES_TMPL.format(init_tag="3.14.7-slim"))
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - redis-init | 3.14.6-slim → 3.14.7-slim | - | ACR mirror only |\n\n"
        "See [`4.8.5-to-4.9.0-values-deltas.md`](4.8.5-to-4.9.0-values-deltas.md).\n"
    )

    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)

    assert ok is True, detail


def test_unresolvable_canonical_named_row_is_not_fuzzy_matched_to_a_real_dependency(vp, tmp_path, capsys):
    """A row shaped like the canonical "<values_key> - <basename>" sidecar
    form, but whose repository can't be resolved at all (no own override,
    no vendored subchart default — e.g. commented out, PodiumD Adapter's
    real-world case), has no entry in canonical_names. It must be reported
    as unresolvable — never fall through to match_dependency's fuzzy
    word-span matching, which would otherwise match its leading word
    ("redis-operator") to the real redis-operator dependency and compare
    the row against THAT dependency's own unrelated actual app version."""
    repo_root = tmp_path
    chart_dir = repo_root / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    images_dir = chart_dir / "docs" / "images"
    for d in (doc_dir, images_dir):
        d.mkdir(parents=True)

    git("init", "-q", cwd=repo_root)
    git("config", "user.email", "test@example.com", cwd=repo_root)
    git("config", "user.name", "Test", cwd=repo_root)

    # redis-operator's own primary "image" (unrelated to the unresolvable
    # sidecar row below) plus redis-ha's normally-resolvable one, so a
    # fuzzy match onto the dependency's own row would have something
    # concrete (and wrong) to compare against.
    values_tmpl = (
        "redis-operator:\n"
        "  image:\n"
        "    repository: quay.io/opstree/redis-operator\n"
        '    tag: "{op_tag}@sha256:cccc"\n'
        "  redis-ha:\n"
        "    image:\n"
        "      repository: quay.io/opstree/redis\n"
        '      tag: "8.6.2@sha256:aaaa"\n'
        "  ghost:\n"
        "    image:\n"
        "      # repository intentionally omitted — unresolvable, no subchart vendored either\n"
        '      tag: "{ghost_tag}@sha256:dddd"\n'
    )

    (chart_dir / "Chart.yaml").write_text(REDIS_CHART_YAML)
    (chart_dir / "values.yaml").write_text(values_tmpl.format(op_tag="0.26.1", ghost_tag="0.6.6"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "baseline", cwd=repo_root)
    git("tag", "podiumd-4.8.5", cwd=repo_root)

    (chart_dir / "values.yaml").write_text(values_tmpl.format(op_tag="0.27.0", ghost_tag="0.6.7"))
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator | 0.26.1 → 0.27.0 | 0.26.1 (unchanged) | n/a |\n"
        "| redis-operator - ghost | 0.6.6 → 0.6.7 | - | ACR mirror only |\n\n"
        "See [`4.8.5-to-4.9.0-values-deltas.md`](4.8.5-to-4.9.0-values-deltas.md).\n"
    )
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(REDIS_GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
        "- **redis-operator** app `0.26.1 → 0.27.0` — image tag only.\n"
        "- **ghost** app `0.6.6 → 0.6.7` — image tag only.\n\n"
        "No gemeente podiumd.yml changes are required for this hop.\n")
    (images_dir / "images-4.9.0.yaml").write_text(
        REDIS_IMAGES_MANIFEST.format(baseline="4.8.5", app_source="0.26.1", app_target="0.27.0"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "bump redis-operator and its unresolvable ghost sidecar", cwd=repo_root)

    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert ('4.8.5-to-4.9.0-upgrade.md: doc row "redis-operator - ghost" does not match a Chart.yaml '
            'dependency or a canonical sidecar/shared-image name') in out
    # The bug this guards against: falling through to match_dependency
    # would fuzzy-match "redis-operator - ghost" onto the real
    # redis-operator dependency and wrongly compare its own actual app
    # version (0.27.0) against the ghost row's app column (0.6.6 → 0.6.7).
    assert 'redis-operator ("redis-operator - ghost")' not in out


def test_chart_only_component_with_no_app_image_is_not_flagged(vp, chart_repo, capsys):
    """A component genuinely without an app image of its own (not in
    lib.chart.COMPONENT_IMAGE_PATHS, and no plain "image" key either)
    must never trigger a target-app mismatch — actual_app_version can't
    resolve anything to compare against, so silence is correct, not a
    gap."""
    (chart_repo / "Chart.yaml").write_text(
        CHART_YAML + '  - name: redis-operator\n    version: "0.26.1"\n    repository: "@opstree"\n')
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(doc.read_text().replace(
        "See [`",
        "| redis-operator | - | 0.26.1 (unchanged) | chart-only, no app image |\n\nSee [`"))

    vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    out = capsys.readouterr().out
    assert "target app" not in out


def test_component_changed_with_no_key_diffs_still_needs_values_deltas_mention(vp, chart_repo):
    """Even when a component's app/chart bump doesn't touch any values.yaml
    schema (no keys added/removed/renamed), it must still be mentioned
    somewhere in values-deltas.md — a plain version bump is still a change
    gemeentes should be told about."""
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-values-deltas.md"
    doc.write_text("# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
                    "No gemeente podiumd.yml changes are required for this hop.\n")
    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is False
    assert "mismatch" in detail


# --- Component versions table / Changes section ordering ---

ORDER_CHART_YAML = """\
apiVersion: v2
name: podiumd
version: 4.9.0
dependencies:
  - name: openzaak
    version: 1.14.2
    repository: "@maykinmedia"
  - name: openinwoner
    version: 2.4.0
    repository: "@maykinmedia"
"""

# openzaak's own block comes BEFORE openinwoner's -- this file order is
# the ordering signal values_key_order reads, so the doc is expected to
# list Open Zaak before Open Inwoner too.
ORDER_VALUES_YAML = (
    'openzaak:\n  image:\n    tag: "1.27.4@sha256:aaaa"\n'
    'openinwoner:\n  image:\n    tag: "2.4.2@sha256:bbbb"\n'
)

ZAAK_ROW = "| Open Zaak | 1.27.4 | 1.14.2 | - |"
INWONER_ROW = "| Open Inwoner | 2.4.2 | 2.4.0 | - |"


def order_doc(table_rows, changes_headings):
    table = "\n".join(table_rows)
    changes = "\n\n".join(f"### {h}\n\nDetails.\n" for h in changes_headings)
    return (
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        f"{table}\n\n"
        "## Changes\n\n"
        f"{changes}\n"
    )


@pytest.fixture
def order_chart_dir(tmp_path):
    chart_dir = tmp_path / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    (chart_dir / "docs" / "images").mkdir(parents=True)
    doc_dir.mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(ORDER_CHART_YAML)
    (chart_dir / "values.yaml").write_text(ORDER_VALUES_YAML)
    return chart_dir, doc_dir


def test_correctly_ordered_table_and_changes_pass(vp, order_chart_dir):
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW, INWONER_ROW], ["Open Zaak bump 1.27.4 → 1.27.4", "Open Inwoner bump 2.4.2 → 2.4.2"]))
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is True, detail


def test_out_of_order_table_row_is_caught(vp, order_chart_dir, capsys):
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([INWONER_ROW, ZAAK_ROW], ["Open Zaak bump", "Open Inwoner bump"]))
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is False
    assert "mismatch" in detail
    out = capsys.readouterr().out
    assert '"Component versions" table lists "Open Zaak" right after "Open Inwoner"' in out
    assert "should follow values.yaml's own component order" in out


def test_out_of_order_changes_block_is_caught(vp, order_chart_dir, capsys):
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW, INWONER_ROW], ["Open Inwoner bump", "Open Zaak bump"]))
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is False
    assert "mismatch" in detail
    out = capsys.readouterr().out
    assert '"## Changes" section has "### Open Zaak bump" right after "### Open Inwoner bump"' in out
    assert "Changes blocks should follow values.yaml's own component order" in out


def test_unmatched_summary_row_never_flagged_against_real_components(vp, order_chart_dir, capsys):
    """A row that doesn't resolve to any Chart.yaml dependency (e.g. a
    shared-image summary row) sorts after every real component and must
    never itself trigger an ORDERING mismatch — it's now separately
    flagged as a wrong-phrasing mismatch (doesn't match a canonical
    sidecar/shared-image name either — see canonical_sidecar_row_names),
    but that's a different, unrelated finding from what this test is
    about."""
    chart_dir, doc_dir = order_chart_dir
    summary_row = "| nginx-unprivileged (shared sidecar) | 1.31.4 | — | - |"
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW, INWONER_ROW, summary_row], ["Open Zaak bump", "Open Inwoner bump"]))
    vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert "own component order" not in capsys.readouterr().out


def test_table_row_with_no_changes_section_is_caught(vp, order_chart_dir, capsys):
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW, INWONER_ROW], ["Open Zaak bump"]))
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is False
    assert "mismatch" in detail
    out = capsys.readouterr().out
    assert 'table row "Open Inwoner" has no matching "### ..." section under "## Changes"' in out


def test_changes_section_with_no_table_row_is_caught(vp, order_chart_dir, capsys):
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW], ["Open Zaak bump", "Open Inwoner bump"]))
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is False
    assert "mismatch" in detail
    out = capsys.readouterr().out
    assert '"## Changes" section "### Open Inwoner bump" has no matching row in the ' \
           '"Component versions" table' in out


def test_heading_naming_two_components_is_flagged_and_neither_row_is_credited(vp, order_chart_dir, capsys):
    """A single "### ..." heading naming two components at once (the
    real-world case: "### ECK Operator 3.4.0 → 3.5.0 + ECK Stack
    (kiss-eck) 0.19.0 → 0.20.0") is assessed as a whole, never split on
    "+" or any other separator — a heading either unambiguously names
    ONE component, or it's wrong. Here it names two, so it's reported as
    its own "no matching row" finding (exactly like an orphan heading
    naming zero would be — there's no special "combines" wording), AND
    neither Open Zaak's nor Open Inwoner's own row is credited by it —
    both are independently reported as having no matching section of
    their own, since a heading naming two components never satisfies
    either one's correspondence."""
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW, INWONER_ROW], ["Open Zaak bump + Open Inwoner bump"]))
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is False
    assert "mismatch" in detail
    out = capsys.readouterr().out
    assert '"## Changes" section "### Open Zaak bump + Open Inwoner bump" has no matching row in the ' \
           '"Component versions" table' in out
    assert 'table row "Open Zaak" has no matching "### ..." section under "## Changes"' in out
    assert 'table row "Open Inwoner" has no matching "### ..." section under "## Changes"' in out


def test_changes_heading_naming_no_real_component_is_caught_as_no_matching_row(vp, order_chart_dir, capsys):
    """A Changes heading that never actually names a real Chart.yaml
    dependency at all (the real-world case: "### Keycloak app image
    26.6.4 → 26.7.2" — never says "keycloak-operator" or even
    "operator") still has to be reported as having no matching table
    row, the same as a heading naming the wrong component would be —
    resolving to nothing is not itself a pass."""
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW, INWONER_ROW], ["Open Zaak bump", "Open Inwoner bump", "Unrelated release note"]))
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is False
    assert "mismatch" in detail
    out = capsys.readouterr().out
    assert '"## Changes" section "### Unrelated release note" has no matching row in the ' \
           '"Component versions" table' in out


def test_changes_heading_missing_app_version_is_caught(vp, order_chart_dir, capsys):
    """A "### ..." heading naming a real, resolvable component but never
    showing its app version at all (real case: "### openbao 0.28.4" —
    add_missing_component_rows' own chart-only TODO-stub shape, written
    back when actual_app_version couldn't resolve anything yet) must be
    flagged once that version DOES become resolvable — a stale heading
    like this is never rewritten automatically (fix-doc-consistency
    never touches an EXISTING section's own text), so nothing else would
    ever catch it going stale."""
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW, INWONER_ROW], ["Open Zaak bump", "Open Inwoner bump 2.4.2 → 2.4.2"]))
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is False
    assert "mismatch" in detail
    out = capsys.readouterr().out
    assert '"## Changes" section "### Open Zaak bump" is missing the primary-image app version ' \
           'in its own heading — values.yaml shows "1.27.4"' in out
    assert 'section "### Open Inwoner bump 2.4.2 → 2.4.2" is missing the primary-image app version' not in out


NEW_DEP_CHART_YAML_BASELINE = """\
apiVersion: v2
name: podiumd
version: 4.8.5
dependencies:
  - name: zaakafhandelcomponent
    alias: zac
    version: 1.0.297
    repository: "@zac"
"""
NEW_DEP_CHART_YAML_TARGET = """\
apiVersion: v2
name: podiumd
version: 4.9.0
dependencies:
  - name: zaakafhandelcomponent
    alias: zac
    version: 1.0.297
    repository: "@zac"
  - name: openklant
    version: 2.15.0
    repository: "@openklant"
"""
NEW_DEP_UPGRADE_DOC = """\
# Upgrade guide: PodiumD {baseline} → 4.9.0

## Component versions (4.9.0 vs {baseline})

| Component | App version | Helm chart | Notes |
| --- | --- | --- | --- |
| ZAC (Zaakafhandelcomponent) | 5.0.2 (unchanged) | 1.0.297 (unchanged) | n/a |
| openklant | 2.15.0 (new) | 2.15.0 (new) | - |

See [`{baseline}-to-4.9.0-values-deltas.md`]({baseline}-to-4.9.0-values-deltas.md).
"""
NEW_DEP_GEMEENTE_DOC = "# Gemeente-specific notes — PodiumD {baseline} → 4.9.0\n\nNone.\n"
NEW_DEP_VALUES_DELTAS_DOC = ("# Values deltas — PodiumD {baseline} → 4.9.0\n\n"
                             "- **openklant** newly added (`openklant.image`).\n\n"
                             "No gemeente podiumd.yml changes are required for this hop.\n")
NEW_DEP_IMAGES_MANIFEST = """\
# Baseline: podiumd {baseline} (test @ 0000000).
#
# Images new or changed in podiumd 4.9.0 vs {baseline}.
#
# Changes: none.
#
# See docs/_UPGRADE_PATHS/{baseline}-to-4.9.0-upgrade.md for the operator upgrade notes.

# openklant — 2.15.0
- name: openklant/open-klant
  url: openklant/open-klant
  version: "2.15.0"
  digest: "sha256:abc"
"""


def new_dep_values():
    return ('zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n'
            '    tag: "5.0.2@sha256:aaaa"\n'
            'openklant:\n  image:\n    repository: openklant/open-klant\n    tag: "2.15.0@sha256:bbbb"\n')


@pytest.fixture
def new_dependency_chart_repo(tmp_path):
    """"openklant" doesn't exist at all at the baseline ref — added as a
    brand-new Chart.yaml dependency in this release. Its doc row's
    source (baseline) version can never be verified against a baseline
    that has no such dependency at all — this is the exact real-world
    gap fix-doc-consistency's own fix_component_version_table already
    tracks as "unresolved" (left uncorrected, and now written as
    "2.15.0 (new)" rather than left blank), which check_docs_consistency
    used to silently treat as clean, since it never had anything to
    compare the row's claimed source version against. Otherwise a fully
    clean, complete doc set — nothing else here should surface any
    mismatch, so the row-source warning's own severity (warning, not
    failure) can be checked in isolation."""
    repo_root = tmp_path
    chart_dir = repo_root / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    images_dir = chart_dir / "docs" / "images"
    for d in (doc_dir, images_dir):
        d.mkdir(parents=True)

    git("init", "-q", cwd=repo_root)
    git("config", "user.email", "test@example.com", cwd=repo_root)
    git("config", "user.name", "Test", cwd=repo_root)

    (chart_dir / "Chart.yaml").write_text(NEW_DEP_CHART_YAML_BASELINE)
    (chart_dir / "values.yaml").write_text(
        'zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "5.0.2@sha256:aaaa"\n')
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "baseline", cwd=repo_root)
    git("tag", "podiumd-4.8.5", cwd=repo_root)

    (chart_dir / "Chart.yaml").write_text(NEW_DEP_CHART_YAML_TARGET)
    (chart_dir / "values.yaml").write_text(new_dep_values())
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(NEW_DEP_UPGRADE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(NEW_DEP_GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(NEW_DEP_VALUES_DELTAS_DOC.format(baseline="4.8.5"))
    (images_dir / "images-4.9.0.yaml").write_text(NEW_DEP_IMAGES_MANIFEST.format(baseline="4.8.5"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "add openklant, a brand-new dependency", cwd=repo_root)

    return chart_dir


def test_new_dependency_unresolvable_baseline_row_is_a_warning_not_a_failure(
        vp, new_dependency_chart_repo, capsys):
    """A doc row for a component that didn't exist at the baseline ref at
    all must be surfaced (never silently treated as clean, since its
    source cells were never actually compared against anything) — but
    only as a warning, not a mismatch: there's nothing wrong with the
    doc here, a brand-new component simply has no baseline to compare
    against, same reason fix-doc-consistency's own fix_component_
    version_table doesn't treat it as an error either (writes "(new)"
    cells for it instead of reporting it for manual review)."""
    ok, detail = vp.check_docs_consistency(new_dependency_chart_repo, upgrade_docs_baseline="4.8.5")
    out = capsys.readouterr().out

    assert ok is True, detail
    assert ('WARNING: 4.8.5-to-4.9.0-upgrade.md: doc row "openklant" source version could not be '
            'verified against') in out
    assert 'openklant" target app' not in out  # target side still resolves fine, no false mismatch there


def test_plus_in_heading_not_naming_two_real_components_still_resolves_normally(vp, order_chart_dir, capsys):
    """A literal "+" in a heading isn't itself the signal — assessment
    never splits on it at all. Here only "Open Zaak" names a real
    component; the rest of the text ("+ misc cleanup") is plain prose
    that names nothing, so the heading as a whole still resolves to
    exactly one identity and must pass normally, same as any other
    single-component heading."""
    chart_dir, doc_dir = order_chart_dir
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW, INWONER_ROW],
                  ["Open Zaak bump 1.27.4 → 1.27.4 + misc cleanup", "Open Inwoner bump 2.4.2 → 2.4.2"]))
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is True, detail
    out = capsys.readouterr().out
    assert "has no matching" not in out
