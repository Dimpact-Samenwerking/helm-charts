"""current_chart_version, extract_images_baseline / update_sibling_doc_refs /
update_images_manifest_baseline, plus main() integration for images-<target>.yaml
handling and end-to-end component-version-table correction. The
`repo_with_baseline_tag` fixture lives in conftest.py (shared with other test
files in this directory)."""

import subprocess

from pathlib import Path
from types import ModuleType

import pytest
import yaml


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def write(path, text):
    path.write_text(text, encoding="utf-8")


def set_argv_and_dir(cdb: ModuleType, monkeypatch: pytest.MonkeyPatch, doc_dir, new_baseline, target="4.9.0"):
    monkeypatch.setattr("sys.argv", ["fix-doc-consistency"])
    monkeypatch.setattr(cdb, "read_upgrade_docs_baseline", lambda chart_dir: new_baseline)
    monkeypatch.setattr(cdb, "DOC_DIR", doc_dir)
    monkeypatch.setattr(cdb, "IMAGES_DIR", doc_dir.parent / "images")
    monkeypatch.setattr(cdb, "CHART_YAML", doc_dir.parents[1] / "Chart.yaml")
    monkeypatch.setattr(cdb, "VALUES_YAML", doc_dir.parents[1] / "values.yaml")
    monkeypatch.setattr(cdb, "current_chart_version", lambda: target)


# --- current_chart_version ---


def test_current_chart_version_reads_chart_yaml(cdb: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text("version: 4.9.0\nname: podiumd\n", encoding="utf-8")
    monkeypatch.setattr(cdb, "CHART_YAML", chart_yaml)
    assert cdb.current_chart_version() == "4.9.0"


# --- extract_images_baseline / update_sibling_doc_refs / update_images_manifest_baseline ---


def test_extract_images_baseline_finds_version(cdb: ModuleType):
    text = "# Baseline: podiumd 4.8.2. Re-verify before release.\n"
    assert cdb.extract_images_baseline(text) == "4.8.2"


def test_extract_images_baseline_none_when_absent(cdb: ModuleType):
    assert cdb.extract_images_baseline("no header here\n") is None


def test_update_sibling_doc_refs_rewrites_whatever_baseline_is_named(cdb: ModuleType):
    text = "See docs/_UPGRADE_PATHS/4.8.3-to-4.9.0-upgrade.md for details.\n"
    new_text, changed = cdb.update_sibling_doc_refs(text, "4.9.0", "4.8.5")
    assert changed is True
    assert "4.8.5-to-4.9.0-upgrade.md" in new_text
    assert "4.8.3" not in new_text


def test_update_sibling_doc_refs_ignores_other_targets(cdb: ModuleType):
    text = "See docs/_UPGRADE_PATHS/4.7.8-to-4.8.0-upgrade.md for an older hop.\n"
    new_text, changed = cdb.update_sibling_doc_refs(text, "4.9.0", "4.8.5")
    assert changed is False
    assert new_text == text


def test_update_sibling_doc_refs_already_correct_reference_is_not_reported_changed(cdb: ModuleType):
    """Regression test: a doc mentioning "<new_baseline>-to-<target>-*.md"
    (nothing stale left — the reference already names the current
    baseline) still MATCHES the pattern, but subn's own replacement
    rebuilds the exact same string — `changed` must reflect whether the
    TEXT actually differs, not whether the pattern matched anything, or
    main()'s own "already baseline ... — fixed stale sibling doc
    reference(s)" print falsely claims a fix for every already-correct
    mention (real case: a doc that merely references its own sibling
    doc correctly, with nothing to repair, printed as "fixed" with no
    file actually changed)."""
    text = "See docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md for details.\n"
    new_text, changed = cdb.update_sibling_doc_refs(text, "4.9.0", "4.8.5")
    assert changed is False
    assert new_text == text


def test_update_images_manifest_baseline_rewrites_both_lines(cdb: ModuleType):
    text = (
        "# Baseline: podiumd 4.8.2 (main @ abc1234). Re-verify before release.\n"
        "#\n"
        "# Images new or changed in podiumd 4.9.0 vs 4.8.2.\n"
    )
    new_text, changed = cdb.update_images_manifest_baseline(text, "4.9.0", "4.8.5")
    assert changed is True
    assert "Baseline: podiumd 4.8.5 (main @ abc1234)" in new_text
    assert "podiumd 4.9.0 vs 4.8.5" in new_text


def test_update_images_manifest_baseline_no_match_returns_unchanged(cdb: ModuleType):
    text = "no baseline lines here\n"
    new_text, changed = cdb.update_images_manifest_baseline(text, "4.9.0", "4.8.5")
    assert changed is False
    assert new_text == text


# --- main() integration: images-<target>.yaml handling ---


def test_main_creates_images_manifest_when_missing(cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch):
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.3")
    cdb.main()

    images_path = repo.parent / "images" / "images-4.9.0.yaml"
    assert images_path.is_file()
    text = images_path.read_text(encoding="utf-8")
    assert "Baseline: podiumd 4.8.3" in text
    assert "podiumd 4.9.0 vs 4.8.3" in text
    assert "4.8.3-to-4.9.0-upgrade.md" in text
    assert text.strip().endswith("[]")


def test_main_bumps_existing_images_manifest(cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch):
    images_path = repo.parent / "images" / "images-4.9.0.yaml"
    write(
        images_path,
        "# Baseline: podiumd 4.8.2 (main @ abc1234). Re-verify before release.\n"
        "#\n"
        "# Images new or changed in podiumd 4.9.0 vs 4.8.2.\n"
        "#\n"
        "# See docs/_UPGRADE_PATHS/4.8.2-to-4.9.0-upgrade.md for the operator upgrade notes.\n\n"
        "- name: zac\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n',
    )
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.5")
    cdb.main()

    text = images_path.read_text(encoding="utf-8")
    assert "Baseline: podiumd 4.8.5" in text
    assert "podiumd 4.9.0 vs 4.8.5" in text
    assert "4.8.5-to-4.9.0-upgrade.md" in text
    assert "- name: zac" in text  # entries untouched


def test_main_images_manifest_already_at_baseline_is_noop(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    images_path = repo.parent / "images" / "images-4.9.0.yaml"
    original = "# Baseline: podiumd 4.8.2 (main @ abc1234). Re-verify before release.\n"
    write(images_path, original)
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")
    cdb.main()

    assert images_path.read_text(encoding="utf-8") == original
    out = capsys.readouterr().out
    assert "images-4.9.0.yaml: already baseline 4.8.2 — unchanged" in out


def test_main_images_baseline_manifest_second_run_reports_unchanged(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Regression test: regenerate_images_baseline_manifest used to
    unconditionally rewrite (and report on) images-baseline.yaml every
    single run, even when nothing about the chart actually changed —
    the ONE doc-writer in this script without the same write-gating
    every OTHER doc type it manages already has (see e.g. the
    "already baseline ... — unchanged" test right above this one). A
    second run with no underlying chart change must report "unchanged"
    instead of "wrote N entries", and must not touch the file's own
    mtime at all — no spurious write, no spurious git-diff churn."""
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")
    cdb.main()
    out1 = capsys.readouterr().out
    assert "=== Regenerating images-baseline.yaml ===" in out1
    assert "wrote 0 entries" in out1  # zac has no "repository:" override in this fixture — nothing resolvable

    images_baseline_path = repo.parent / "images" / "images-baseline.yaml"
    mtime_after_first = images_baseline_path.stat().st_mtime_ns
    text_after_first = images_baseline_path.read_text(encoding="utf-8")

    cdb.main()
    out2 = capsys.readouterr().out
    assert "unchanged (0 entries)" in out2
    assert "wrote" not in out2
    assert images_baseline_path.stat().st_mtime_ns == mtime_after_first
    assert images_baseline_path.read_text(encoding="utf-8") == text_after_first


# --- main() integration: end-to-end component-version-table correction ---


def test_main_corrects_stale_table_using_real_baseline_tag(
    cdb: ModuleType, repo_with_baseline_tag, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    set_argv_and_dir(cdb, monkeypatch, repo_with_baseline_tag, "4.8.5")
    cdb.main()

    upgrade = (repo_with_baseline_tag / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "5.0.2 → 5.1.0" in upgrade
    assert "1.0.297 → 1.0.257" in upgrade
    assert "5.0.1" not in upgrade
    assert "1.0.251" not in upgrade
    out = capsys.readouterr().out
    assert "Correcting component version table" in out


@pytest.fixture
def repo_with_mi_shaped_stale_docs(tmp_path: Path):
    """The real mi bug, reproduced synthetically: a Chart.yaml dependency
    ("mi-data", alias "mi") that already existed at the baseline ref
    (condition-gated, disabled by default) but had NO "image:" block
    pinned in values.yaml there yet — its own app version is genuinely
    unresolvable at baseline, so per component_version_cell it should
    render "(new)" everywhere, never a stale "<old> → <new>" transition.
    All three surfaces (the table row, its own -upgrade.md Changes
    heading, its own -values-deltas.md section heading) were written by
    an earlier, buggy tool run with the wrong transition AND, for the
    two headings, the wrong (bare "mi", not the row's own "mi-data
    (MI-data exports)") name too."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {
                        "name": "mi-data",
                        "alias": "mi",
                        "version": "1.0.0",
                        "repository": "file://../mi-data",
                        "condition": "mi.enabled",
                    },
                ],
            }
        ),
    )
    write(tmp_path / "values.yaml", yaml.safe_dump({"mi": {"enabled": False}}))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.9.0", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {
                        "name": "mi-data",
                        "alias": "mi",
                        "version": "1.1.0",
                        "repository": "file://../mi-data",
                        "condition": "mi.enabled",
                    },
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "mi": {
                    "enabled": False,
                    "image": {"repository": "mcr.microsoft.com/azure-cli", "tag": "2.90.0@sha256:" + "a" * 64},
                },
            }
        ),
    )
    write(
        doc_dir / "4.9.0-to-4.9.1-upgrade.md",
        "# Upgrade guide: PodiumD 4.9.0 → 4.9.1\n\n"
        "## Component versions (4.9.1 vs 4.9.0)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| mi-data (MI-data exports) | 2.71.0 → 2.90.0 | 1.0.0 → 1.1.0 | - |\n\n"
        "## Changes\n\n"
        "### mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)\n\n"
        "Some stale prose here.\n",
    )
    write(
        doc_dir / "4.9.0-to-4.9.1-values-deltas.md",
        "# Values deltas — PodiumD 4.9.0 → 4.9.1\n\n"
        "## mi 2.71.0 → 2.90.0 (chart 1.1.0, unchanged)\n\n"
        "- Key `mi.transfer.noEpsv` (optional) added.\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "mi bump, stale docs from an old buggy run", cwd=tmp_path)
    return doc_dir


def test_main_corrects_mi_shaped_stale_name_and_new_dependency_wording_everywhere(
    cdb: ModuleType, repo_with_mi_shaped_stale_docs, monkeypatch: pytest.MonkeyPatch
):
    """One fix-doc-consistency run corrects all three surfaces to the
    SAME name ("mi-data (MI-data exports)", the row's own — see
    fix_changes_heading_app_versions' own docstring for why that one is
    authoritative) and the SAME "(new)" wording (never the stale
    "2.71.0 → 2.90.0" transition, since mi's own app version genuinely
    never resolved at baseline)."""
    set_argv_and_dir(cdb, monkeypatch, repo_with_mi_shaped_stale_docs, "4.9.0", target="4.9.1")
    cdb.main()

    upgrade = (repo_with_mi_shaped_stale_docs / "4.9.0-to-4.9.1-upgrade.md").read_text(encoding="utf-8")
    values_deltas = (repo_with_mi_shaped_stale_docs / "4.9.0-to-4.9.1-values-deltas.md").read_text(encoding="utf-8")

    assert "| mi-data (MI-data exports) | 2.90.0 (new) | 1.0.0 → 1.1.0 | - |" in upgrade
    assert "### mi-data (MI-data exports) 2.90.0 (new) (chart 1.1.0, unchanged)" in upgrade
    assert "## mi-data (MI-data exports) 2.90.0 (new) (chart 1.1.0, unchanged)" in values_deltas
    assert "2.71.0" not in upgrade
    assert "2.71.0" not in values_deltas
