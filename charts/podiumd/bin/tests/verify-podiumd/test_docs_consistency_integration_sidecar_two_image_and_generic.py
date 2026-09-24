"""End-to-end check_docs_consistency against a small, realistic podiumd-like
chart inside a real (hermetic, temp) git repo — exercises the full baseline
resolution + all the precheck/content-check stages together.

Split from test_docs_consistency_integration.py (pylint too-many-lines): this
file covers the second half of the sidecar-image section — redis-operator's
own multi-sidecar/job cases plus the generic chart-only/no-schema-diff cases."""

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

REDIS_CHART_YAML = """\
apiVersion: v2
name: podiumd
version: 4.9.0
dependencies:
  - name: redis-operator
    version: 0.26.1
    repository: "@ot-helm"
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
- name: redis-ha
  url: quay.io/opstree/redis
  version: "{app_target}"
  digest: "sha256:abc"
"""


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def redis_values(tag, digest="abc"):
    return (
        f"redis-operator:\n  redis-ha:\n    image:\n      repository: quay.io/opstree/redis\n"
        f'      tag: "{tag}@sha256:{digest}"\n'
    )


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


def test_unchanged_sidecar_with_no_row_is_not_flagged(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
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
        REDIS_TWO_IMAGES_VALUES_TMPL.format(redis_tag="8.6.2", exporter_tag="1.82.0")
    )
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "baseline", cwd=repo_root)
    git("tag", "podiumd-4.8.5", cwd=repo_root)

    # redis-ha's own redis image changes; redisExporter does not.
    (chart_dir / "values.yaml").write_text(
        REDIS_TWO_IMAGES_VALUES_TMPL.format(redis_tag="8.6.6", exporter_tag="1.82.0")
    )
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
        REDIS_VALUES_DELTAS_DOC.format(baseline="4.8.5", app_source="8.6.2", app_target="8.6.6")
    )
    (images_dir / "images-4.9.0.yaml").write_text(
        REDIS_IMAGES_MANIFEST.format(baseline="4.8.5", app_source="8.6.2", app_target="8.6.6")
    )
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "bump redis-ha's redis image only", cwd=repo_root)

    vp.check_docs_consistency(chart_dir, upgrade_docs_baseline="4.8.5")

    out = capsys.readouterr().out
    assert "redis-operator - redis-exporter" not in out


def test_new_sidecar_row_known_in_historical_images_manifest_is_not_a_warning(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Regression test: redis-operator's own "k8s" sidecar is added as a
    brand-new nested path this release (baseline has nothing for it at
    all), but its repository already appears, byte-for-byte at the same
    version, in an earlier release's own docs/images/images-4.8.0.yaml
    manifest — resolve_component_row's own historical-images-manifest
    fallback (see lib.chart.historical_app_version_for_path) resolves
    its baseline app version anyway, so this is verified clean, not
    left as an unverifiable warning the way a genuinely new pin would
    be (see test_new_dependency_unresolvable_baseline_row_is_a_warning_
    not_a_failure)."""
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

    (chart_dir / "values.yaml").write_text(
        redis_values("8.6.2") + "  k8s:\n    image:\n      repository: quay.io/alpine/k8s\n"
        '      tag: "1.36.2@sha256:cccc"\n'
    )
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - k8s | 1.36.2 (unchanged) | - | ACR mirror only |\n\n"
        "See [`4.8.5-to-4.9.0-values-deltas.md`](4.8.5-to-4.9.0-values-deltas.md).\n"
    )
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(REDIS_GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
        "## redis-operator - k8s 1.36.2 (unchanged)\n\n"
        "No gemeente podiumd.yml changes are required for this hop.\n"
    )
    (images_dir / "images-4.9.0.yaml").write_text(
        "# Baseline: podiumd 4.8.5 (test @ 0000000).\n#\n"
        "# Images new or changed in podiumd 4.9.0 vs 4.8.5.\n#\n# Zero changes:\n#\n\n[]\n"
    )
    (images_dir / "images-4.8.0.yaml").write_text(
        '- name: alpine/k8s\n  url: quay.io/alpine/k8s\n  version: "1.36.2"\n  digest: "sha256:cccc"\n'
    )
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "add k8s sidecar, pinned to an already-mirrored image", cwd=repo_root)

    vp.check_docs_consistency(chart_dir, upgrade_docs_baseline="4.8.5")

    out = capsys.readouterr().out
    assert 'doc row "redis-operator - k8s" source version could not be verified' not in out
    assert 'redis-operator - k8s" target app' not in out
    assert 'redis-operator - k8s" source app' not in out


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


def test_sidecar_app_version_resolved_from_its_own_trailing_image_key(vp: ModuleType, tmp_path: Path):
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


def test_unresolvable_canonical_named_row_is_not_fuzzy_matched_to_a_real_dependency(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
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
        "No gemeente podiumd.yml changes are required for this hop.\n"
    )
    (images_dir / "images-4.9.0.yaml").write_text(
        REDIS_IMAGES_MANIFEST.format(baseline="4.8.5", app_source="0.26.1", app_target="0.27.0")
    )
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "bump redis-operator and its unresolvable ghost sidecar", cwd=repo_root)

    ok, _detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline="4.8.5")

    assert ok is False
    out = capsys.readouterr().out
    assert (
        '4.8.5-to-4.9.0-upgrade.md: doc row "redis-operator - ghost" does not match a Chart.yaml '
        "dependency or a canonical sidecar/shared-image name"
    ) in out
    # The bug this guards against: falling through to match_dependency
    # would fuzzy-match "redis-operator - ghost" onto the real
    # redis-operator dependency and wrongly compare its own actual app
    # version (0.27.0) against the ghost row's app column (0.6.6 → 0.6.7).
    assert 'redis-operator ("redis-operator - ghost")' not in out


def test_chart_only_component_with_no_app_image_is_not_flagged(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    """A component genuinely without an app image of its own (not in
    lib.chart.COMPONENT_IMAGE_PATHS, and no plain "image" key either)
    must never trigger a target-app mismatch — actual_app_version can't
    resolve anything to compare against, so silence is correct, not a
    gap."""
    (chart_repo / "Chart.yaml").write_text(
        CHART_YAML + '  - name: redis-operator\n    version: "0.26.1"\n    repository: "@opstree"\n'
    )
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(
        doc.read_text().replace(
            "See [`", "| redis-operator | - | 0.26.1 (unchanged) | chart-only, no app image |\n\nSee [`"
        )
    )

    vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    out = capsys.readouterr().out
    assert "target app" not in out


def test_component_changed_with_no_key_diffs_needs_no_values_deltas_mention(vp: ModuleType, chart_repo):
    """When a component's app/chart bump doesn't touch any values.yaml
    schema (no keys added/removed/renamed), it needs no mention in
    values-deltas.md at all — that transition is already covered by
    -upgrade.md's own table + Changes section, and values-deltas.md
    exists to tell gemeentes what THEIR OWN podiumd.yml needs to react
    to (see lib.component_docs.sync_values_delta_sections' own
    docstring) — a plain version bump alone needs no gemeente action."""
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-values-deltas.md"
    doc.write_text(
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\nNo gemeente podiumd.yml changes are required for this hop.\n"
    )
    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is True, detail
