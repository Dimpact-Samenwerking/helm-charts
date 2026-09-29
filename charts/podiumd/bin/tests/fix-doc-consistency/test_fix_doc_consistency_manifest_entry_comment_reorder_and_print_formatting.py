"""main() integration: images-manifest entry comments, reordering, and print
formatting of multi-item lists."""

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


# --- main() integration: images-manifest entry-comment correction ---


def test_main_corrects_stale_images_manifest_entry_comment(
    cdb: ModuleType, repo_with_baseline_tag, monkeypatch: pytest.MonkeyPatch
):
    images_path = repo_with_baseline_tag.parent / "images" / "images-4.9.0.yaml"
    write(
        images_path,
        "# Baseline: podiumd 4.8.5. Re-verify before release.\n\n"
        "# ZAC — 5.0.1 -> 5.1.0\n"
        "- name: zac\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n',
    )
    set_argv_and_dir(cdb, monkeypatch, repo_with_baseline_tag, "4.8.5")
    cdb.main()

    text = images_path.read_text(encoding="utf-8")
    assert "# ZAC — 5.0.2 -> 5.1.0" in text


def _repo_with_zac_bump(tmp_path: Path, entry_name: str, entry_url: str) -> tuple[Path, Path]:
    """Repo bumping zac 5.0.2 -> 5.1.0 since podiumd-4.8.5, with an
    images-4.9.0.yaml entry carrying a stale "5.0.1 -> 5.1.0" comment.
    Returns (doc_dir, images_path)."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:bbbb"}},
            }
        ),
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}},
            }
        ),
    )
    write(
        doc_dir / "4.8.3-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.1.0 | 1.0.297 (unchanged) | ACR mirror only |\n",
    )
    images_path = images_dir / "images-4.9.0.yaml"
    write(
        images_path,
        "# Baseline: podiumd 4.8.5. Re-verify before release.\n\n"
        "# ZAC — 5.0.1 -> 5.1.0\n"
        f"- name: {entry_name}\n"
        f"  url: {entry_url}\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n',
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zac, stale images-manifest comment", cwd=tmp_path)
    return doc_dir, images_path


def test_main_corrects_strip_registry_named_entry_via_repo_map(
    cdb: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """With the strip-registry entry name, main() must pass a repo_map built
    from the real Chart.yaml/values.yaml for the entry to resolve."""
    doc_dir, images_path = _repo_with_zac_bump(
        tmp_path, "infonl/zaakafhandelcomponent", "ghcr.io/infonl/zaakafhandelcomponent"
    )

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    text = images_path.read_text(encoding="utf-8")
    assert "# ZAC — 5.0.2 -> 5.1.0" in text


def test_main_corrects_url_then_name_in_one_run(cdb: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The url is corrected before the name, so a legacy name follows the
    corrected url in the same run instead of needing a second run."""
    doc_dir, images_path = _repo_with_zac_bump(tmp_path, "zac", "ghcr.io/infonl/zac-old")

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    text = images_path.read_text(encoding="utf-8")
    assert "- name: infonl/zaakafhandelcomponent\n  url: ghcr.io/infonl/zaakafhandelcomponent\n" in text
    assert "# ZAC — 5.0.2 -> 5.1.0" in text


def test_main_adds_missing_images_manifest_entry(cdb: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A changed component without a manifest entry gets one appended, not
    just reported."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:bbbb"}},
            }
        ),
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:aaaa"}},
            }
        ),
    )
    write(
        doc_dir / "4.8.3-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.1.0 | 1.0.297 (unchanged) | ACR mirror only |\n",
    )
    images_path = images_dir / "images-4.9.0.yaml"
    write(images_path, "# Baseline: podiumd 4.8.5. Re-verify before release.\n\n[]\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zac, no images-manifest entry yet", cwd=tmp_path)

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    text = images_path.read_text(encoding="utf-8")
    assert "# zac 5.0.2 -> 5.1.0" in text
    assert "- name: infonl/zaakafhandelcomponent" in text
    assert "url: ghcr.io/infonl/zaakafhandelcomponent" in text
    assert 'version: "5.1.0"' in text
    assert 'digest: "sha256:aaaa"' in text


# --- main() integration: reordering the table + Changes section ---


@pytest.fixture
def repo_with_out_of_order_doc(tmp_path: Path):
    """Table rows and "## Changes" blocks both in the opposite of values.yaml
    key order."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "openzaak", "version": "1.14.2", "repository": "@maykinmedia"},
                    {"name": "openinwoner", "version": "2.4.0", "repository": "@maykinmedia"},
                ],
            },
            sort_keys=False,
        ),
    )
    # sort_keys=False: file order is the ordering signal (values_key_order).
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "openzaak": {"image": {"tag": "1.27.4@sha256:aaaa"}},
                "openinwoner": {"image": {"tag": "2.4.2@sha256:bbbb"}},
            },
            sort_keys=False,
        ),
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    write(
        doc_dir / "4.8.3-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.3 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.3)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| Open Inwoner | 2.4.2 | 2.4.0 | - |\n"
        "| Open Zaak | 1.27.4 | 1.14.2 | - |\n\n"
        "## Changes\n\n"
        "### Open Inwoner 2.4.2 → 2.4.2\n\n"
        "Inwoner details.\n\n"
        "### Open Zaak 1.27.4 → 1.27.4\n\n"
        "Zaak details.\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "seed out-of-order doc", cwd=tmp_path)
    return doc_dir


def test_main_reorders_table_and_changes_to_match_values_yaml(
    cdb: ModuleType, repo_with_out_of_order_doc, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    set_argv_and_dir(cdb, monkeypatch, repo_with_out_of_order_doc, "4.8.3")
    cdb.main()

    upgrade = (repo_with_out_of_order_doc / "4.8.3-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    lines = upgrade.splitlines()
    table_rows = [line for line in lines if line.startswith("| Open")]
    assert table_rows == ["| Open Zaak | 1.27.4 | 1.14.2 | - |", "| Open Inwoner | 2.4.2 | 2.4.0 | - |"]
    assert upgrade.index("### Open Zaak") < upgrade.index("### Open Inwoner")
    assert "Zaak details." in upgrade and "Inwoner details." in upgrade  # block content preserved

    out = capsys.readouterr().out
    assert "Reordering" in out
    assert "table row 'Open Zaak': position 2 -> 1" in out
    assert "changes block '### Open Zaak 1.27.4 → 1.27.4': position 2 -> 1" in out


def test_main_already_ordered_doc_reports_no_reordering(
    cdb: ModuleType, repo_with_out_of_order_doc, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    doc = repo_with_out_of_order_doc / "4.8.3-to-4.9.0-upgrade.md"
    doc.write_text(
        "# Upgrade guide: PodiumD 4.8.3 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.3)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| Open Zaak | 1.27.4 | 1.14.2 | - |\n"
        "| Open Inwoner | 2.4.2 | 2.4.0 | - |\n",
        encoding="utf-8",
    )
    set_argv_and_dir(cdb, monkeypatch, repo_with_out_of_order_doc, "4.8.3")
    cdb.main()

    out = capsys.readouterr().out
    assert "Reordering" not in out


def test_main_reorders_a_sidecar_row_to_come_after_its_own_parent_row(
    cdb: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A sidecar row shares its parent's values_key_index; the " - "
    tie-break must put it after the parent, since a stable sort alone keeps
    a sidecar that came first."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [{"name": "redis-operator", "version": "0.26.1", "repository": "@opstree"}],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "redis-operator": {
                    "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": "8.6.6@sha256:aaaa"}}
                },
            }
        ),
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    write(
        doc_dir / "4.8.3-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.3 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.3)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator - redis | 8.6.2 → 8.6.6 | - | - |\n"
        "| redis-operator | 0.26.1 (unchanged) | 0.26.1 (unchanged) | - |\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "seed sidecar-before-parent doc", cwd=tmp_path)

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.3")
    cdb.main()

    upgrade = (doc_dir / "4.8.3-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    lines = upgrade.splitlines()
    table_rows = [line for line in lines if line.startswith("| redis-operator")]
    assert table_rows == [
        "| redis-operator | 0.26.1 (unchanged) | 0.26.1 (unchanged) | - |",
        "| redis-operator - redis | 8.6.2 → 8.6.6 | - | - |",
    ]
    out = capsys.readouterr().out
    assert "Reordering" in out


# --- main() print formatting: multi-item lists split one per line, not comma-joined ---


def test_main_reports_unmatched_components_one_per_line(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    write(
        repo / "4.8.2-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.2)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| Totally Unknown Thing A | 1.0.0 → 2.0.0 | 1.0.0 → 2.0.0 | - |\n"
        "| Totally Unknown Thing B | 1.0.0 → 2.0.0 | 1.0.0 → 2.0.0 | - |\n",
    )
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")

    cdb.main()

    out = capsys.readouterr().out
    assert "Could not match 2 component(s) in 4.8.2-to-4.9.0-upgrade.md to a Chart.yaml dependency, left as-is:" in out
    assert "  Totally Unknown Thing A" in out
    assert "  Totally Unknown Thing B" in out
    assert "Totally Unknown Thing A, Totally Unknown Thing B" not in out


def test_main_reports_unresolved_source_versions_one_per_line(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Unverifiable source versions are printed one per line under a count
    header, not comma-joined."""
    write(
        repo.parents[1] / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
                    {"name": "openzaak", "version": "1.14.2", "repository": "@openzaak"},
                ],
            }
        ),
    )
    write(
        repo.parents[1] / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"tag": "5.1.0@sha256:aaaa"}},
                "openzaak": {"image": {"tag": "1.29.3@sha256:bbbb"}},
            }
        ),
    )
    write(
        repo / "4.8.2-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.2)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.1 → 5.1.0 | 1.0.251 → 1.0.257 | - |\n"
        "| Open Zaak | 1.27.4 → 1.29.3 | 1.14.2 (unchanged) | - |\n",
    )
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")

    cdb.main()

    out = capsys.readouterr().out
    assert "Could not verify source version for 2 component(s) in 4.8.2-to-4.9.0-upgrade.md" in out
    assert "  ZAC (Zaakafhandelcomponent)" in out
    assert "  Open Zaak" in out
    assert "ZAC (Zaakafhandelcomponent), Open Zaak" not in out


def test_main_reports_unresolved_image_entries_one_per_line(
    cdb: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    images_dir = repo.parent / "images"
    write(
        images_dir / "images-4.9.0.yaml",
        '- name: totally-unknown-a\n  version: "1.0.0"\n- name: totally-unknown-b\n  version: "1.0.0"\n',
    )
    set_argv_and_dir(cdb, monkeypatch, repo, "4.8.2")

    cdb.main()

    out = capsys.readouterr().out
    assert "Could not verify source/target version for 2 entry(s) in images-4.9.0.yaml" in out
    assert "  totally-unknown-a" in out
    assert "  totally-unknown-b" in out
    assert "totally-unknown-a, totally-unknown-b" not in out
