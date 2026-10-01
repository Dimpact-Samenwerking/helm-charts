"""main() integration: adding missing sidecar/shared-image rows and Changes
sections, plus the short-alias row-collision regression."""

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
    monkeypatch.setattr(cdb, "current_chart_version", lambda: target)


@pytest.fixture
def repo_with_new_sidecar_pinned_to_a_known_mirrored_image(tmp_path: Path):
    """redis-operator's "k8s" sidecar is a new path, but its exact pin is
    already recorded in an earlier images-4.8.0.yaml manifest."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [{"name": "redis-operator", "version": "1.36.1", "repository": "@opstree"}],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "redis-operator": {
                    "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": "8.6.2@sha256:aaaa"}}
                },
            }
        ),
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    images_dir = tmp_path / "docs" / "images"
    doc_dir.mkdir(parents=True)
    images_dir.mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [{"name": "redis-operator", "version": "1.36.2", "repository": "@opstree"}],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "redis-operator": {
                    "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": "8.6.2@sha256:aaaa"}},
                    "k8s": {"image": {"repository": "quay.io/alpine/k8s", "tag": "1.36.2@sha256:cccc"}},
                },
            }
        ),
    )
    write(
        doc_dir / "4.8.5-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| redis-operator | - | 1.36.1 → 1.36.2 | n/a |\n\n"
        "## Changes\n\n",
    )
    write(images_dir / "images-4.9.0.yaml", "# Baseline: podiumd 4.8.5.\n#\n# Zero changes:\n#\n\n")
    write(
        images_dir / "images-4.8.0.yaml",
        '- name: alpine/k8s\n  url: quay.io/alpine/k8s\n  version: "1.36.2"\n  digest: "sha256:cccc"\n',
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "add k8s sidecar, pinned to an already-mirrored image", cwd=tmp_path)
    return doc_dir


def test_main_new_sidecar_row_annotated_unchanged_when_known_in_historical_manifest(
    cdb: ModuleType, repo_with_new_sidecar_pinned_to_a_known_mirrored_image, monkeypatch: pytest.MonkeyPatch
):
    """A new sidecar path whose pin is in an earlier manifest reads
    "(unchanged)" in its App cell, not "(new)"."""
    doc_dir = repo_with_new_sidecar_pinned_to_a_known_mirrored_image
    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    upgrade = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| redis-operator - k8s | 1.36.2 (unchanged) | - | - |" in upgrade


def test_main_adds_missing_changes_section_for_an_existing_dependency_row(
    cdb: ModuleType,
    repo_with_undocumented_sidecar_bump,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A correct row without a "### ..." section gets one from the shared
    make_changes_section template, driven by the row's own cells."""
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_sidecar_bump, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_sidecar_bump / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "### ZAC (Zaakafhandelcomponent) 5.0.1 → 5.0.2 (chart 1.0.297, unchanged)" in upgrade
    out = capsys.readouterr().out
    assert "Adding missing '### ...' Changes section(s)" in out
    assert "ZAC (Zaakafhandelcomponent)" in out


def test_main_adds_todo_stub_section_when_row_has_no_app_version(
    cdb: ModuleType, repo_with_undocumented_sidecar_bump, monkeypatch: pytest.MonkeyPatch
):
    """An app cell of "-" gives a TODO-stub section rather than guessed prose."""
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_sidecar_bump, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_sidecar_bump / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "### redis-operator 0.26.1\n" in upgrade
    assert "TODO: describe this component's changes" in upgrade


def test_main_updates_a_changes_heading_missing_its_app_version(
    cdb: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression (openbao): a TODO-stub heading written while the app
    version was unresolvable is regenerated from the row's cells once it
    resolves; the old body is discarded as its accuracy is unknowable.

    "widget" is registered via tmp_path/etc/settings.yaml, which
    update_stale_app_version_headings reaches through its chart_dir."""
    import io
    import tarfile

    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        'component_resolution:\n  image_paths:\n    widget: ["image"]\n',
        encoding="utf-8",
    )

    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [{"name": "widget", "version": "2.0.0", "repository": "@example"}],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "widget": {"image": {"repository": "example/widget", "tag": ""}},
            }
        ),
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)

    charts_dir = tmp_path / "charts"
    charts_dir.mkdir()
    with tarfile.open(charts_dir / "widget-2.0.0.tgz", "w:gz") as tar:
        chart_data = yaml.safe_dump({"apiVersion": "v2", "version": "2.0.0", "appVersion": "9.9.9"}).encode("utf-8")
        info = tarfile.TarInfo(name="widget/Chart.yaml")
        info.size = len(chart_data)
        tar.addfile(info, io.BytesIO(chart_data))

    write(
        doc_dir / "4.8.5-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| widget | 9.9.9 (unchanged) | 2.0.0 (unchanged) | - |\n\n"
        "## Changes\n\n"
        "### widget 2.0.0\n\n"
        "TODO: describe this component's changes — its app version could not be resolved from the table row.\n\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "seed doc with a stale chart-only heading", cwd=tmp_path)

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    upgrade = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "### widget 9.9.9 (unchanged) (chart 2.0.0, unchanged)" in upgrade
    assert "TODO: describe this component's changes" not in upgrade
    assert "### widget 2.0.0\n" not in upgrade


def test_main_adds_sections_for_both_rows_named_by_a_two_component_heading(
    cdb: ModuleType,
    repo_with_undocumented_sidecar_bump,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A heading naming two components is not split and credits neither row,
    so each gets its own section; the combined heading is left for a human."""
    doc_dir = repo_with_undocumented_sidecar_bump
    doc = doc_dir / "4.8.5-to-4.9.0-upgrade.md"
    combined_heading = "### ZAC (Zaakafhandelcomponent) 5.0.1 → 5.0.2 + redis-operator 0.26.0 → 0.26.1\n\n"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace(
            "## Changes\n\n", "## Changes\n\n" + combined_heading + "Some shared prose that must not be touched.\n\n"
        ),
        encoding="utf-8",
    )

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    upgrade = doc.read_text(encoding="utf-8")
    assert combined_heading in upgrade
    assert "Some shared prose that must not be touched." in upgrade
    assert "### ZAC (Zaakafhandelcomponent) 5.0.1 → 5.0.2 (chart 1.0.297, unchanged)" in upgrade
    assert "### redis-operator 0.26.1\n" in upgrade
    out = capsys.readouterr().out
    assert "Adding missing '### ...' Changes section(s)" in out
    assert "ZAC (Zaakafhandelcomponent)" in out
    assert "redis-operator" in out


def test_main_adds_version_pin_bullet_for_a_version_paths_component(
    cdb: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A component in component_resolution.version_paths gets a "Version pin"
    bullet, not an "Image tag pin `<key>.image.tag`" guess for a path that
    doesn't exist.

    Uses the real "redis-operator" registration: the baseline-side lookup
    calls actual_app_version without chart_dir, so a tmp_path-only
    settings override would be seen on the target side only."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "widget-a", "version": "1.0.0", "repository": "@example"},
                    {"name": "redis-operator", "version": "2.0.0", "repository": "@example"},
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "widget-a": {"image": {"tag": "1.1.0@sha256:aaaa"}},
                "redis-operator": {"redisOperator": {"imageTag": "2.1.0"}},
            }
        ),
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "widget-a": {"image": {"tag": "1.2.0@sha256:bbbb"}},
                "redis-operator": {"redisOperator": {"imageTag": "2.2.0"}},
            }
        ),
    )
    write(
        doc_dir / "4.8.5-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| widget-a | 1.1.0 → 1.2.0 | 1.0.0 (unchanged) | - |\n"
        "| redis-operator | 2.1.0 → 2.2.0 | 2.0.0 (unchanged) | - |\n\n"
        "## Changes\n\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump", cwd=tmp_path)

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    upgrade = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "### widget-a 1.1.0 → 1.2.0 (chart 1.0.0, unchanged)" in upgrade
    assert "Image tag pin `widget-a.image.tag`" in upgrade
    assert "### redis-operator 2.1.0 → 2.2.0 (chart 2.0.0, unchanged)" in upgrade
    assert "Version pin `redis-operator.redisOperator.imageTag`" in upgrade
    assert "Image tag pin `redis-operator" not in upgrade


def test_main_does_not_duplicate_an_existing_sidecar_row(
    cdb: ModuleType, repo_with_undocumented_sidecar_bump, monkeypatch: pytest.MonkeyPatch
):
    doc_dir = repo_with_undocumented_sidecar_bump
    doc = doc_dir / "4.8.5-to-4.9.0-upgrade.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace(
            "| redis-operator | - | 0.26.0 → 0.26.1 | n/a |\n",
            "| redis-operator | - | 0.26.0 → 0.26.1 | n/a |\n"
            "| redis-operator - redis | 8.6.2 → 8.6.6 | - | already documented by hand |\n",
        ),
        encoding="utf-8",
    )

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    upgrade = doc.read_text(encoding="utf-8")
    assert upgrade.count("| redis-operator - redis |") == 1
    assert "already documented by hand" in upgrade
    # The hand-written row exists, so only the missing "### ..." section is
    # added, from the row's own cells.
    assert "### redis-operator - redis 8.6.2 → 8.6.6" in upgrade


def test_main_leaves_unchanged_sidecar_with_no_row_alone(
    cdb: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A sidecar whose tag didn't change gets no row; only real changes are
    documented."""
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
                    "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": "8.6.2@sha256:aaaa"}}
                },
            }
        ),
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(
        doc_dir / "4.8.5-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "unrelated commit, redis-ha's own image untouched", cwd=tmp_path)

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    upgrade = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "redis-operator - redis" not in upgrade
    out = capsys.readouterr().out
    assert "Adding missing sidecar/shared-image row(s)" not in out


@pytest.fixture
def repo_with_short_alias_collision_risk(tmp_path: Path):
    """Regression fixture: alias "mi" is a mid-word substring of
    "ensurePodiumdAdminUser"; without word boundaries in find_component_row,
    adding "mi" overwrote that unrelated row."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "mi-data", "alias": "mi", "version": "1.0.0", "repository": "@dimpact"},
                ],
            }
        ),
    )
    write(tmp_path / "values.yaml", yaml.safe_dump({"mi": {"image": {"tag": "2.0.0@sha256:aaaa"}}}))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(tmp_path / "values.yaml", yaml.safe_dump({"mi": {"image": {"tag": "2.1.0@sha256:bbbb"}}}))
    write(
        doc_dir / "4.8.3-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| Python (ensurePodiumdAdminUser init image) | 3.14-slim (unchanged) | 1.0.0 (unchanged) | - |\n\n"
        "## Changes\n\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump mi, no doc row added", cwd=tmp_path)
    return doc_dir


def test_main_short_alias_does_not_corrupt_unrelated_row(
    cdb: ModuleType, repo_with_short_alias_collision_risk, monkeypatch: pytest.MonkeyPatch
):
    set_argv_and_dir(cdb, monkeypatch, repo_with_short_alias_collision_risk, "4.8.5")
    cdb.main()

    upgrade = (repo_with_short_alias_collision_risk / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert ("| Python (ensurePodiumdAdminUser init image) | 3.14-slim (unchanged) | 1.0.0 (unchanged) | - |") in upgrade
    assert "| mi | 2.0.0 → 2.1.0 | 1.0.0 (unchanged) | - |" in upgrade
