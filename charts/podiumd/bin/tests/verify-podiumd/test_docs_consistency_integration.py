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
        values_yaml("5.4.3") + 'openformulieren:\n  image:\n    tag: "3.5.6@sha256:cccc"\n')

    ok, detail = vp.check_docs_consistency(chart_repo, upgrade_docs_baseline="4.8.5")
    assert ok is False
    assert "mismatch" in detail

    out = capsys.readouterr().out
    assert 'component "openformulieren" changed vs' in out
    assert 'has no row in the "Component versions" table' in out
    assert 'is not mentioned anywhere in the doc' in out
    assert "openformulieren" in out and "has no entry in images-4.9.0.yaml" in out


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
        order_doc([ZAAK_ROW, INWONER_ROW], ["Open Zaak bump", "Open Inwoner bump"]))
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


def test_unmatched_summary_row_never_flagged_against_real_components(vp, order_chart_dir):
    """A row that doesn't resolve to any Chart.yaml dependency (e.g. a
    shared-image summary row) sorts after every real component and must
    never itself trigger an ordering mismatch."""
    chart_dir, doc_dir = order_chart_dir
    summary_row = "| nginx-unprivileged (shared sidecar) | 1.31.4 | — | - |"
    (doc_dir / "4.8.5-to-4.9.0-upgrade.md").write_text(
        order_doc([ZAAK_ROW, INWONER_ROW, summary_row], ["Open Zaak bump", "Open Inwoner bump"]))
    ok, detail = vp.check_docs_consistency(chart_dir, upgrade_docs_baseline=None)
    assert ok is True, detail
