"""End-to-end check_docs_consistency on a small podiumd-like chart in a temp git repo:
redis-operator sidecar and keycloak/keycloak-operator split tag/sha cases."""

import subprocess

from pathlib import Path
from types import ModuleType

import pytest


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


# --- sidecar image (nested under a dependency, not its primary image): row named
# "<values_key> - <basename>", as update-image-version writes it ---

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
def redis_sidecar_chart_repo(tmp_path: Path):
    """redis-ha's image is a sidecar under "redis-operator" (no primary "image" key),
    matched only via canonical_sidecar_row_names, never match_dependency."""
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


def test_sidecar_row_with_canonical_name_is_verified(vp: ModuleType, redis_sidecar_chart_repo):
    ok, detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is True, detail


def test_sidecar_row_wrong_target_app_is_caught(
    vp: ModuleType, redis_sidecar_chart_repo, capsys: pytest.CaptureFixture[str]
):
    doc = redis_sidecar_chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(REDIS_UPGRADE_DOC.format(baseline="4.8.5", app_source="8.6.2", app_target="9.9.9"))

    ok, _detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert (
        'redis-operator.redis-ha.image ("redis-operator - redis") target app: values.yaml image tag is '
        '"8.6.6", 4.8.5-to-4.9.0-upgrade.md says "9.9.9"'
    ) in out


def test_sidecar_row_wrong_source_app_vs_baseline_is_caught(
    vp: ModuleType, redis_sidecar_chart_repo, capsys: pytest.CaptureFixture[str]
):
    doc = redis_sidecar_chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(REDIS_UPGRADE_DOC.format(baseline="4.8.5", app_source="1.1.1", app_target="8.6.6"))

    ok, _detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert (
        'redis-operator.redis-ha.image ("redis-operator - redis") source app: podiumd-4.8.5 has "8.6.2", '
        '4.8.5-to-4.9.0-upgrade.md says "1.1.1"'
    ) in out


def test_sidecar_row_with_old_style_phrasing_is_flagged_as_wrong_phrasing(
    vp: ModuleType, redis_sidecar_chart_repo, capsys: pytest.CaptureFixture[str]
):
    """A row for the sidecar not in the exact canonical "<values_key> - <basename>" form
    is a mismatch: neither skipped nor fuzzy-matched."""
    doc = redis_sidecar_chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(doc.read_text().replace("redis-operator - redis", "Redis (redis-ha)"))

    ok, _detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert (
        '4.8.5-to-4.9.0-upgrade.md: doc row "Redis (redis-ha)" does not match a Chart.yaml '
        "dependency or a canonical sidecar/shared-image name"
    ) in out


def test_sidecar_digest_only_repin_is_not_flagged_as_changed(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """A digest-only re-pin (same version) must not be flagged in -upgrade.md, which
    documents version changes only.

    images-4.9.0.yaml compares digests too, so its missing entry IS flagged."""
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
| keycloak | {app_source} → {app_target} | - | - |
| keycloak-operator | {op_source} → {op_target} | 1.13.0 (unchanged) | - |

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
#   1. keycloak {app_source} -> {app_target}.
#   2. keycloak-operator {op_source} -> {op_target}.
#

# keycloak {app_source} -> {app_target}
- name: keycloak/keycloak
  url: keycloak/keycloak
  version: "{app_target}"
  digest: "sha256:{app_digest}"
# keycloak-operator {op_source} -> {op_target}
- name: keycloak/keycloak-operator
  url: keycloak/keycloak-operator
  version: "{op_target}"
  digest: "sha256:{op_digest}"
"""


def keycloak_split_values(app_tag, app_digest, op_tag, op_digest):
    """Values using the split tag:/sha: convention for keycloak.image (whose anchors
    keycloak-operator's keycloakImage aliases) and operator.image."""
    return (
        f"keycloak:\n"
        f"  image:\n"
        f"    repository: &keycloakImageRepo quay.io/keycloak/keycloak\n"
        f'    tag: &keycloakImageVersion "{app_tag}"\n'
        f'    sha: &keycloakImageDigest "{app_digest}"\n'
        f"keycloak-operator:\n"
        f"  operator:\n"
        f"    image:\n"
        f"      repository: quay.io/keycloak/keycloak-operator\n"
        f'      tag: "{op_tag}"\n'
        f'      sha: "{op_digest}"\n'
        f"    config:\n"
        f"      keycloakImage:\n"
        f"        repository: *keycloakImageRepo\n"
        f"        tag: *keycloakImageVersion\n"
        f"        sha: *keycloakImageDigest\n"
    )


@pytest.fixture
def keycloak_split_chart_repo(tmp_path: Path):
    """Chart whose digests live in a sibling "sha:" field, so the per-entry check must
    resolve the split pin (resolved_digest_pin) instead of comparing the bare tag."""
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
    git("commit", "-q", "-m", "bump keycloak's and keycloak-operator's split tag/sha images", cwd=repo_root)

    return chart_dir


def test_split_tag_sha_path_digest_is_resolved_not_compared_as_bare_tag(
    vp: ModuleType, keycloak_split_chart_repo, capsys: pytest.CaptureFixture[str]
):
    """Regression: comparing the bare "tag:" of a split tag/sha path against the manifest's
    "version@digest" flagged every up-to-date pin as a mismatch."""
    ok, _detail = vp.check_docs_consistency(keycloak_split_chart_repo, upgrade_docs_baseline="4.8.5")
    out = capsys.readouterr().out

    assert ok is True, out
    assert "values.yaml tag is" not in out
    # Must resolve via repo_map's exact match: fuzzy word-matching can't, since the entry
    # name has "keycloak" twice and the values path once.
    assert "no matching image in values.yaml, skipped" not in out


def test_unresolvable_entry_names_the_manifest_file_its_own_message(
    vp: ModuleType, keycloak_split_chart_repo, capsys: pytest.CaptureFixture[str]
):
    """Regression: an unresolvable images-manifest entry must name its manifest file.

    upgrade_docs_baseline=None, else check_images_manifest_format's entry-list-diff
    precheck reports the entry as stale first and skips the per-entry loop."""
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


def test_split_tag_sha_path_real_mismatch_is_still_caught(
    vp: ModuleType, keycloak_split_chart_repo, capsys: pytest.CaptureFixture[str]
):
    """A real digest mismatch on a resolved sha: field must still be caught."""
    values_path = keycloak_split_chart_repo / "values.yaml"
    values_path.write_text(values_path.read_text().replace('"' + "c" * 64 + '"', '"' + "e" * 64 + '"'))

    ok, _detail = vp.check_docs_consistency(keycloak_split_chart_repo, upgrade_docs_baseline="4.8.5")
    out = capsys.readouterr().out

    assert ok is False
    assert 'keycloak/keycloak: values.yaml tag is "26.7.3@sha256:' + "e" * 64 in out


def test_sidecar_with_no_row_at_all_is_caught_as_missing(
    vp: ModuleType, redis_sidecar_chart_repo, capsys: pytest.CaptureFixture[str]
):
    """A changed sidecar with no row at all must be flagged: the "component changed but
    has no row" check only tracks top-level keys, so this needs a per-sidecar check."""
    doc = redis_sidecar_chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "See [`4.8.5-to-4.9.0-values-deltas.md`](4.8.5-to-4.9.0-values-deltas.md).\n"
    )

    ok, _detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert (
        '4.8.5-to-4.9.0-upgrade.md: sidecar/shared image "redis-operator - redis" changed vs '
        'podiumd-4.8.5 but has no row in the "Component versions" table'
    ) in out


def test_sidecar_missing_from_images_manifest_uses_canonical_name(
    vp: ModuleType, redis_sidecar_chart_repo, capsys: pytest.CaptureFixture[str]
):
    """A sidecar missing from images-manifest is reported by its canonical
    "<values_key> - <basename>" name, not the dotted values path."""
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

    ok, _detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert 'image "redis-operator - redis" changed vs 4.8.5 but has no entry' in out
    assert "redis-operator.redis-ha.image" not in out


def test_orphan_top_level_block_sharing_a_dependencys_sidecar_repository_is_covered(
    vp: ModuleType, redis_sidecar_chart_repo, capsys: pytest.CaptureFixture[str]
):
    """A top-level block with no Chart.yaml dependency (e.g. apiproxy) sharing a
    dependency sidecar's repository is covered by that sidecar's manifest entry."""
    values_path = redis_sidecar_chart_repo / "values.yaml"
    values_path.write_text(
        values_path.read_text()
        + 'apiproxy:\n  image:\n    repository: quay.io/opstree/redis\n    tag: "8.6.6@sha256:abc"\n'
    )

    ok, detail = vp.check_docs_consistency(redis_sidecar_chart_repo, upgrade_docs_baseline="4.8.5")

    assert ok is True, detail
    out = capsys.readouterr().out
    assert "apiproxy" not in out
