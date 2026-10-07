"""End-to-end check_docs_consistency on a small podiumd-like chart in a temp git repo.

Covers redis-operator multi-sidecar/job cases and generic chart-only/no-schema-diff cases."""

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
- name: opstree/redis
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
    """Only a sidecar whose tag CHANGED vs baseline is flagged as missing a row."""
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
    assert "redisExporter" not in out


def test_new_sidecar_row_known_in_historical_images_manifest_is_not_a_warning(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Regression: a new nested sidecar path whose repository+version appears in an earlier
    images manifest resolves its baseline via the historical-manifest fallback, so it's
    verified clean rather than warned as unresolvable."""
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
    """A sidecar keyed e.g. "initImage" next to a sibling "image" must be compared against
    its own tag, not a hardcoded ".image.tag" (which would report a bogus mismatch)."""
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
    """A "<values_key> - <image-basename>" row whose repository can't be resolved must be reported
    as unresolvable, never fuzzy-matched by match_dependency onto the real dependency
    (which would compare against that dependency's unrelated app version)."""
    repo_root = tmp_path
    chart_dir = repo_root / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    images_dir = chart_dir / "docs" / "images"
    for d in (doc_dir, images_dir):
        d.mkdir(parents=True)

    git("init", "-q", cwd=repo_root)
    git("config", "user.email", "test@example.com", cwd=repo_root)
    git("config", "user.name", "Test", cwd=repo_root)

    # resolvable images, so a wrong fuzzy match would have something to compare against
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
    # a fuzzy match onto redis-operator would compare 0.27.0 against the ghost row
    assert 'redis-operator ("redis-operator - ghost")' not in out


def test_chart_only_component_with_no_app_image_is_not_flagged(
    vp: ModuleType, chart_repo, capsys: pytest.CaptureFixture[str]
):
    """A component without an app image of its own never triggers a target-app mismatch."""
    (chart_repo / "Chart.yaml").write_text(
        CHART_YAML + '  - name: redis-operator\n    version: "0.26.1"\n    repository: "@opstree"\n'
    )
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    new_text = doc.read_text().replace(
        "See [`", "| redis-operator | - | 0.26.1 (unchanged) | chart-only, no app image |\n\nSee [`"
    )
    # str.replace() silently no-ops on a missing anchor; guard against a vacuous pass
    assert "| redis-operator |" in new_text
    doc.write_text(new_text)

    vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    out = capsys.readouterr().out
    assert "target app" not in out


def test_component_changed_with_no_key_diffs_needs_no_values_deltas_mention(vp: ModuleType, chart_repo):
    """A version bump with no values.yaml schema change needs no values-deltas.md mention:
    that file only lists what gemeentes must change in their podiumd.yml."""
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-values-deltas.md"
    doc.write_text(
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\nNo gemeente podiumd.yml changes are required for this hop.\n"
    )
    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is True, detail


REDIS_ALIASED_VALUES_TMPL = (
    "redis-operator:\n"
    "  redis-ha:\n"
    "    labelMasterCronJob:\n"
    "      image: &k8s\n"
    "        repository: docker.io/alpine/k8s\n"
    '        tag: "{tag}@sha256:cccc"\n'
    "    preDeleteJob:\n"
    "      image: *k8s\n"
)
ALIASED_PIN_DOC = (
    "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
    "## Component versions (4.9.0 vs 4.8.5)\n\n"
    "| Component | App version | Helm chart | Notes |\n"
    "| --- | --- | --- | --- |\n"
    "| redis-operator - k8s | 1.37.0 → 1.37.1 | - | - |\n\n"
    "## Changes\n\n"
    "### redis-operator - k8s 1.37.0 → 1.37.1\n\n"
    "PodiumD 4.9.0 upgrades the **redis-operator - k8s** image to 1.37.1,\n"
    "pinned at:\n\n"
    "- `redis-operator.redis-ha.labelMasterCronJob.image.tag` `1.37.0` → `1.37.1`\n"
    "{extra}\n"
    "- Image / digest: see [`images-4.9.0.yaml`](../images/images-4.9.0.yaml).\n"
)


@pytest.mark.parametrize("alias_bullet", ["missing", "present"])
def test_changes_block_must_name_every_path_sharing_the_pins_anchor(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], alias_bullet: str
):
    """preDeleteJob.image aliases labelMasterCronJob.image, so a bump changes both paths;
    an environment overriding one path needs the doc to name the other too."""
    repo_root = tmp_path
    chart_dir = repo_root / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    git("init", "-q", cwd=repo_root)
    git("config", "user.email", "test@example.com", cwd=repo_root)
    git("config", "user.name", "Test", cwd=repo_root)
    (chart_dir / "Chart.yaml").write_text(REDIS_CHART_YAML)
    (chart_dir / "values.yaml").write_text(REDIS_ALIASED_VALUES_TMPL.format(tag="1.37.0"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "baseline", cwd=repo_root)
    git("tag", "podiumd-4.8.5", cwd=repo_root)

    (chart_dir / "values.yaml").write_text(REDIS_ALIASED_VALUES_TMPL.format(tag="1.37.1"))
    extra = (
        "- `redis-operator.redis-ha.preDeleteJob.image.tag` `1.37.0` → `1.37.1`\n" if alias_bullet == "present" else ""
    )
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(ALIASED_PIN_DOC.replace("{extra}", extra))
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(REDIS_GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(
        REDIS_VALUES_DELTAS_DOC.format(baseline="4.8.5", app_source="1.37.0", app_target="1.37.1")
    )

    vp.check_docs_consistency(chart_dir, upgrade_docs_baseline="4.8.5")

    out = capsys.readouterr().out
    repair = "+- `redis-operator.redis-ha.preDeleteJob.image.tag` `1.37.0` → `1.37.1`"
    assert (repair in out) == (alias_bullet == "missing"), out


@pytest.mark.parametrize("blank_line", ["missing", "present"])
def test_changes_block_needs_a_blank_line_before_the_image_digest_pointer(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], blank_line: str
):
    """update-component-version wrote the pointer right after the last pin bullet."""
    repo_root = tmp_path
    chart_dir = repo_root / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    git("init", "-q", cwd=repo_root)
    git("config", "user.email", "test@example.com", cwd=repo_root)
    git("config", "user.name", "Test", cwd=repo_root)
    (chart_dir / "Chart.yaml").write_text(REDIS_CHART_YAML)
    (chart_dir / "values.yaml").write_text(REDIS_ALIASED_VALUES_TMPL.format(tag="1.37.0"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "baseline", cwd=repo_root)
    git("tag", "podiumd-4.8.5", cwd=repo_root)

    (chart_dir / "values.yaml").write_text(REDIS_ALIASED_VALUES_TMPL.format(tag="1.37.1"))
    extra = "- `redis-operator.redis-ha.preDeleteJob.image.tag` `1.37.0` → `1.37.1`\n"
    doc = ALIASED_PIN_DOC.replace("{extra}", extra)
    if blank_line == "missing":
        doc = doc.replace(extra + "\n", extra)
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(doc)
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(REDIS_GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(
        REDIS_VALUES_DELTAS_DOC.format(baseline="4.8.5", app_source="1.37.0", app_target="1.37.1")
    )

    vp.check_docs_consistency(chart_dir, upgrade_docs_baseline="4.8.5")

    out = capsys.readouterr().out
    assert ("4.8.5-to-4.9.0-upgrade.md (changed" in out) == (blank_line == "missing"), out


@pytest.mark.parametrize("pointer", ["missing", "present"])
def test_changes_block_needs_its_image_digest_pointer(
    vp: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], pointer: str
):
    """A section that lost its pointer (e.g. in a merge resolution) is reported."""
    repo_root = tmp_path
    chart_dir = repo_root / "charts" / "podiumd"
    doc_dir = chart_dir / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    git("init", "-q", cwd=repo_root)
    git("config", "user.email", "test@example.com", cwd=repo_root)
    git("config", "user.name", "Test", cwd=repo_root)
    (chart_dir / "Chart.yaml").write_text(REDIS_CHART_YAML)
    (chart_dir / "values.yaml").write_text(REDIS_ALIASED_VALUES_TMPL.format(tag="1.37.0"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "baseline", cwd=repo_root)
    git("tag", "podiumd-4.8.5", cwd=repo_root)

    (chart_dir / "values.yaml").write_text(REDIS_ALIASED_VALUES_TMPL.format(tag="1.37.1"))
    doc = ALIASED_PIN_DOC.replace("{extra}", "- `redis-operator.redis-ha.preDeleteJob.image.tag` `1.37.0` → `1.37.1`\n")
    if pointer == "missing":
        doc = doc.replace("\n- Image / digest: see [`images-4.9.0.yaml`](../images/images-4.9.0.yaml).\n", "")
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(doc)
    (doc_dir / "4.8.5-to-4.9.0-gemeente-specific.md").write_text(REDIS_GEMEENTE_DOC.format(baseline="4.8.5"))
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(
        REDIS_VALUES_DELTAS_DOC.format(baseline="4.8.5", app_source="1.37.0", app_target="1.37.1")
    )

    vp.check_docs_consistency(chart_dir, upgrade_docs_baseline="4.8.5")

    out = capsys.readouterr().out
    assert ("+- Image / digest: see [`images-4.9.0.yaml`]" in out) == (pointer == "missing"), out
