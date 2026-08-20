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
    return f'zac:\n  image:\n    tag: "{app_version}@sha256:abc"\n'


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
    (doc_dir / "4.8.5-to-4.9.0-values-deltas.md").write_text(VALUES_DELTAS_DOC.format(baseline="4.8.5"))
    (images_dir / "images-4.9.0.yaml").write_text(
        IMAGES_MANIFEST.format(baseline="4.8.5", app_source="5.0.2", app_target="5.4.3"))
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "bump zac to 5.4.3", cwd=repo_root)

    return chart_dir


def test_fully_consistent_chart_passes_with_baseline(vp, chart_repo):
    ok, detail = vp.check_docs_consistency(chart_repo, baseline="4.8.5")
    assert ok is True, detail


def test_fully_consistent_chart_passes_without_baseline(vp, chart_repo):
    ok, detail = vp.check_docs_consistency(chart_repo, baseline=None)
    assert ok is True, detail


def test_no_matching_docs_is_a_soft_pass(vp, tmp_path):
    chart_dir = tmp_path / "charts" / "podiumd"
    (chart_dir / "docs" / "_UPGRADE_PATHS").mkdir(parents=True)
    (chart_dir / "docs" / "images").mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(CHART_YAML)
    (chart_dir / "values.yaml").write_text(values_yaml("5.4.3"))
    ok, detail = vp.check_docs_consistency(chart_dir, baseline=None)
    assert ok is True
    assert "skipped" in detail


def test_wrong_target_version_in_doc_is_caught(vp, chart_repo):
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(UPGRADE_DOC.format(baseline="4.8.5", app_source="5.0.2", app_target="5.9.9"))
    ok, detail = vp.check_docs_consistency(chart_repo, baseline="4.8.5")
    assert ok is False
    assert "mismatch" in detail


def test_wrong_source_version_vs_baseline_is_caught(vp, chart_repo):
    doc = chart_repo / "docs" / "_UPGRADE_PATHS" / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(UPGRADE_DOC.format(baseline="4.8.5", app_source="9.9.9", app_target="5.4.3"))
    ok, detail = vp.check_docs_consistency(chart_repo, baseline="4.8.5")
    assert ok is False
    assert "mismatch" in detail


def test_unresolvable_baseline_is_caught(vp, chart_repo):
    ok, detail = vp.check_docs_consistency(chart_repo, baseline="9.9.9")
    assert ok is False
