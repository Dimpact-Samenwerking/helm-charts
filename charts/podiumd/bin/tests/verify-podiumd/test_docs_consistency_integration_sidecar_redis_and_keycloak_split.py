"""End-to-end check_docs_consistency against a small, realistic podiumd-like
chart inside a real (hermetic, temp) git repo — exercises the full baseline
resolution + all the precheck/content-check stages together.

Split from test_docs_consistency_integration.py (pylint too-many-lines): this
file covers the first half of the sidecar-image section — the redis-operator
sidecar and keycloak-operator split tag/sha cases."""

import subprocess

import pytest


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


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
REDIS_VALUES_DELTAS_DOC = (
    "# Values deltas — PodiumD {baseline} → 4.9.0\n\n"
    "## redis-operator {app_source} → {app_target} — image tag only\n\n"
    "No gemeente podiumd.yml changes are required for this hop.\n"
)
REDIS_IMAGES_MANIFEST = """\
# Baseline: podiumd {baseline} (test @ 0000000).
#
# Images new or changed in podiumd 4.9.0 vs {baseline}.
#
# Changes:
#   1. redis-ha {app_source} -> {app_target}
#
# See docs/_UPGRADE_PATHS/{baseline}-to-4.9.0-upgrade.md for the operator upgrade notes.

#   sidecar: redis-operator - redis {app_source} -> {app_target}
- name: opstree/redis
  url: quay.io/opstree/redis
  version: "{app_target}"
  digest: "sha256:abc"
"""


def redis_values(tag, digest="abc"):
    return (
        f"redis-operator:\n  redis-ha:\n    image:\n      repository: quay.io/opstree/redis\n"
        f'      tag: "{tag}@sha256:{digest}"\n'
    )


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
        REDIS_UPGRADE_DOC.format(baseline="4.8.5", app_source="8.6.2", app_target="8.6.6")
    )
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(REDIS_GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(
        REDIS_VALUES_DELTAS_DOC.format(baseline="4.8.5", app_source="8.6.2", app_target="8.6.6")
    )
    (images_dir / "images-4.9.0.yaml").write_text(
        REDIS_IMAGES_MANIFEST.format(baseline="4.8.5", app_source="8.6.2", app_target="8.6.6")
    )
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
    assert (
        'redis-operator.redis-ha.image ("redis-operator - redis") target app: values.yaml image tag is '
        '"8.6.6", 4.8.5-to-4.9.0-upgrade.md says "9.9.9"'
    ) in out


def test_sidecar_row_wrong_source_app_vs_baseline_is_caught(vp, redis_sidecar_chart_repo, capsys):
    doc = redis_sidecar_chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(REDIS_UPGRADE_DOC.format(baseline="4.8.5", app_source="1.1.1", app_target="8.6.6"))

    ok, detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert (
        'redis-operator.redis-ha.image ("redis-operator - redis") source app: podiumd-4.8.5 has "8.6.2", '
        '4.8.5-to-4.9.0-upgrade.md says "1.1.1"'
    ) in out


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
    assert (
        '4.8.5-to-4.9.0-upgrade.md: doc row "Redis (redis-ha)" does not match a Chart.yaml '
        "dependency or a canonical sidecar/shared-image name"
    ) in out


def test_sidecar_digest_only_repin_is_not_flagged_as_changed(vp, tmp_path, capsys):
    """A sidecar image re-pinned to a NEW digest but the SAME version
    (e.g. nginx-unprivileged in a chart-wide digest-pinning sweep, #437)
    must never be reported as "changed vs baseline but has no row" in
    -upgrade.md — that doc documents VERSION changes, never a digest-
    only re-pin alone (see lib.upgradedoc.compute_changed_components/
    lib.image.docs.add_missing_sidecar_rows, and this same check's own
    canonical_names loop just below — all three deliberately stay
    version-only; see each one's own docstring for why. This is the
    negative case for the images-manifest's own, WIDER comparison
    (lib.upgradedoc.find_images_manifest_list_diff) checked just below:
    the two must not agree on this).

    images-4.9.0.yaml is a DIFFERENT story: a real, individually-
    deliberate digest-only re-pin genuinely belongs there (see find_
    images_manifest_list_diff's own docstring) — a real case confirmed
    live (clamav 1.5.4, keycloak-operator's init image), ground-truthed
    against the real chart to be rare, not a routine sweep flood. So
    THIS check (unlike the two above) DOES flag the missing entry."""
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
    (chart_dir / "values.yaml").write_text(redis_values("8.6.6", digest="a" * 64))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "baseline", cwd=repo_root)
    git("tag", "podiumd-4.8.5", cwd=repo_root)

    # Same version (8.6.6), digest-only re-pin.
    (chart_dir / "values.yaml").write_text(redis_values("8.6.6", digest="b" * 64))
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "See [`4.8.5-to-4.9.0-values-deltas.md`](4.8.5-to-4.9.0-values-deltas.md).\n"
    )
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(REDIS_GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\nNo gemeente podiumd.yml changes are required for this hop.\n"
    )
    (images_dir / "images-4.9.0.yaml").write_text(
        "# Baseline: podiumd 4.8.5 (test @ 0000000).\n"
        "#\n"
        "# Images new or changed in podiumd 4.9.0 vs 4.8.5.\n"
        "#\n"
        "# Changes:\n"
        "#\n"
        "# See docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md for the operator upgrade notes.\n\n"
        "[]\n"
    )
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "digest-only re-pin, no version change", cwd=repo_root)

    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline="4.8.5")

    assert ok is False, detail
    out = capsys.readouterr().out
    assert 'sidecar/shared image "redis-operator - redis" changed' not in out
    assert 'redis-operator - redis" but has no row in the "Component versions" table' not in out
    assert 'image "redis-operator - redis" changed vs 4.8.5 but has no entry' in out


KEYCLOAK_SPLIT_CHART_YAML = """\
apiVersion: v2
name: podiumd
version: 4.9.0
dependencies:
  - name: keycloak-operator
    version: 1.13.0
    repository: "@adfinis"
"""

KEYCLOAK_SPLIT_UPGRADE_DOC = """\
# Upgrade guide: PodiumD {baseline} → 4.9.0

## Component versions (4.9.0 vs {baseline})

| Component | App version | Helm chart | Notes |
| --- | --- | --- | --- |
| keycloak-operator | {app_source} → {app_target} | 1.13.0 (unchanged) | - |
| keycloak-operator - operator | {op_source} → {op_target} | - | - |

See [`{baseline}-to-4.9.0-values-deltas.md`]({baseline}-to-4.9.0-values-deltas.md).
"""
KEYCLOAK_SPLIT_GEMEENTE_DOC = "# Gemeente-specific notes — PodiumD {baseline} → 4.9.0\n\nNone.\n"
KEYCLOAK_SPLIT_VALUES_DELTAS_DOC = (
    "# Values deltas — PodiumD {baseline} → 4.9.0\n\nNo gemeente podiumd.yml changes are required for this hop.\n"
)
KEYCLOAK_SPLIT_IMAGES_MANIFEST = """\
# Baseline: podiumd {baseline} (test @ 0000000).
#
# Images new or changed in podiumd 4.9.0 vs {baseline}.
#
# Changes:
#   1. keycloak-operator {app_source} -> {app_target}.
#   2. keycloak-operator - operator {op_source} -> {op_target}.
#

# keycloak-operator {app_source} -> {app_target}
- name: keycloak/keycloak
  url: keycloak/keycloak
  version: "{app_target}"
  digest: "sha256:{app_digest}"
#   sidecar: keycloak-operator - operator {op_source} -> {op_target}
- name: keycloak/keycloak-operator
  url: keycloak/keycloak-operator
  version: "{op_target}"
  digest: "sha256:{op_digest}"
"""


def keycloak_split_values(app_tag, app_digest, op_tag, op_digest):
    """keycloak-operator's own split tag:/sha: convention (see
    lib.chart.SPLIT_TAG_SHA_PATHS) for both its primary app image
    (operator.config.keycloakImage, aliased into the top-level
    keycloak.image the same way podiumd's own values.yaml does) and its
    own operator image (operator.image) — neither ever embeds "@sha256"
    in "tag:" directly, unlike every other image in the chart."""
    return (
        f"keycloak-operator:\n"
        f"  operator:\n"
        f"    image:\n"
        f"      repository: quay.io/keycloak/keycloak-operator\n"
        f'      tag: "{op_tag}"\n'
        f'      sha: "{op_digest}"\n'
        f"    config:\n"
        f"      keycloakImage:\n"
        f"        repository: quay.io/keycloak/keycloak\n"
        f'        tag: "{app_tag}"\n'
        f'        sha: "{app_digest}"\n'
        f"keycloak:\n"
        f"  image:\n"
        f"    repository: quay.io/keycloak/keycloak\n"
        f'    tag: "{app_tag}"\n'
        f'    sha: "{app_digest}"\n'
    )


@pytest.fixture
def keycloak_split_chart_repo(tmp_path):
    """keycloak.image (and keycloak-operator's own operator.image) pin
    their digest via a separate sibling "sha:" field, never embedded in
    "tag:" (lib.chart.SPLIT_TAG_SHA_PATHS) — the per-entry version/digest
    check further down in check_docs_consistency must resolve that split
    shape (lib.chart.resolved_digest_pin) before comparing against the
    images-manifest entry's own "version@digest", not compare the bare
    "tag:" value directly (which never has the digest half at all)."""
    repo_root = tmp_path
    chart_dir = repo_root / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    images_dir = chart_dir / "docs" / "images"
    for d in (doc_dir, images_dir):
        d.mkdir(parents=True)

    git("init", "-q", cwd=repo_root)
    git("config", "user.email", "test@example.com", cwd=repo_root)
    git("config", "user.name", "Test", cwd=repo_root)

    (chart_dir / "Chart.yaml").write_text(KEYCLOAK_SPLIT_CHART_YAML)
    (chart_dir / "values.yaml").write_text(keycloak_split_values("26.7.2", "a" * 64, "26.6.4", "b" * 64))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "baseline", cwd=repo_root)
    git("tag", "podiumd-4.8.5", cwd=repo_root)

    (chart_dir / "values.yaml").write_text(keycloak_split_values("26.7.3", "c" * 64, "26.7.3", "d" * 64))
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        KEYCLOAK_SPLIT_UPGRADE_DOC.format(
            baseline="4.8.5", app_source="26.7.2", app_target="26.7.3", op_source="26.6.4", op_target="26.7.3"
        )
    )
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(KEYCLOAK_SPLIT_GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(KEYCLOAK_SPLIT_VALUES_DELTAS_DOC.format(baseline="4.8.5"))
    (images_dir / "images-4.9.0.yaml").write_text(
        KEYCLOAK_SPLIT_IMAGES_MANIFEST.format(
            baseline="4.8.5",
            app_source="26.7.2",
            app_target="26.7.3",
            app_digest="c" * 64,
            op_source="26.6.4",
            op_target="26.7.3",
            op_digest="d" * 64,
        )
    )
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "bump keycloak-operator's split tag/sha images", cwd=repo_root)

    return chart_dir


def test_split_tag_sha_path_digest_is_resolved_not_compared_as_bare_tag(vp, keycloak_split_chart_repo, capsys):
    """Regression test: keycloak.image's digest lives in a separate
    "sha:" field (lib.chart.SPLIT_TAG_SHA_PATHS), never embedded in
    "tag:". The per-entry images-manifest check used to compare the bare
    "tag:" string directly against the manifest's "version@digest",
    which can never match for a split-tag/sha path — every correctly
    up-to-date pin was wrongly reported as a mismatch."""
    ok, detail = vp.check_docs_consistency(keycloak_split_chart_repo, upgrade_docs_baseline="4.8.5")
    out = capsys.readouterr().out

    assert ok is True, out
    assert "values.yaml tag is" not in out
    # keycloak/keycloak-operator's own repository (quay.io/keycloak/
    # keycloak-operator) matches its own path exactly via repo_map — the
    # per-entry loop must resolve it there, not fall back to
    # resolve_entry_path's fuzzy word-matching (which can't: the entry
    # name repeats "keycloak" once for the org and once for the repo,
    # while the values-tree path only has it once, so neither an exact
    # nor a substring match is ever found).
    assert "no matching image in values.yaml, skipped" not in out


def test_unresolvable_entry_names_the_manifest_file_its_own_message(vp, keycloak_split_chart_repo, capsys):
    """Regression test: an images-manifest entry the per-entry loop truly
    can't resolve to any values-tree path must name the manifest file
    it's in — the diagnostic used to be a bare "entry ... — no matching
    image" print with no file, useless once a chart has more than one
    images-<version>.yaml on disk over its history.

    upgrade_docs_baseline=None (not "4.8.5") is required here: with a
    bare-version baseline, check_images_manifest_format's own entry-
    list-diff precheck would catch this same stale entry FIRST (as
    "wrong or stale") and skip the per-entry loop entirely — see
    test_images_manifest_entry_missing_version_or_digest_is_reported_
    not_crashed's own docstring for the same reasoning."""
    images_path = keycloak_split_chart_repo / "docs" / "images" / "images-4.9.0.yaml"
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

    vp.check_docs_consistency(keycloak_split_chart_repo, upgrade_docs_baseline=None)
    out = capsys.readouterr().out

    assert '(images-4.9.0.yaml: entry "does-not-exist" — no matching image in values.yaml, skipped)' in out


def test_split_tag_sha_path_real_mismatch_is_still_caught(vp, keycloak_split_chart_repo, capsys):
    """Once resolved via its own sha: field, a REAL digest mismatch must
    still be caught, not silently swallowed by the fix above."""
    values_path = keycloak_split_chart_repo / "values.yaml"
    values_path.write_text(values_path.read_text().replace('"' + "c" * 64 + '"', '"' + "e" * 64 + '"'))

    ok, detail = vp.check_docs_consistency(keycloak_split_chart_repo, upgrade_docs_baseline="4.8.5")
    out = capsys.readouterr().out

    assert ok is False
    assert 'keycloak/keycloak: values.yaml tag is "26.7.3@sha256:' + "e" * 64 in out


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
    assert (
        '4.8.5-to-4.9.0-upgrade.md: sidecar/shared image "redis-operator - redis" changed vs '
        'podiumd-4.8.5 but has no row in the "Component versions" table'
    ) in out


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
    vp, redis_sidecar_chart_repo, capsys
):
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
        values_path.read_text()
        + 'apiproxy:\n  image:\n    repository: quay.io/opstree/redis\n    tag: "8.6.6@sha256:abc"\n'
    )

    ok, detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is True, detail
    out = capsys.readouterr().out
    assert "apiproxy" not in out
