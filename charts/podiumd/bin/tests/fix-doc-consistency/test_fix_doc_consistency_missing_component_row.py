"""main() integration: adding a missing "Component versions" row for an
undocumented component bump, plus its first missing-sidecar-row scenarios."""

import subprocess

import yaml


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def write(path, text):
    path.write_text(text, encoding="utf-8")


def set_argv_and_dir(cdb, monkeypatch, doc_dir, new_baseline, target="4.9.0"):
    monkeypatch.setattr("sys.argv", ["fix-doc-consistency"])
    monkeypatch.setattr(cdb, "read_upgrade_docs_baseline", lambda chart_dir: new_baseline)
    monkeypatch.setattr(cdb, "DOC_DIR", doc_dir)
    monkeypatch.setattr(cdb, "IMAGES_DIR", doc_dir.parent / "images")
    monkeypatch.setattr(cdb, "CHART_YAML", doc_dir.parents[1] / "Chart.yaml")
    monkeypatch.setattr(cdb, "VALUES_YAML", doc_dir.parents[1] / "values.yaml")
    monkeypatch.setattr(cdb, "current_chart_version", lambda: target)


# --- main() integration: adding a missing "Component versions" row ---


def test_main_collapses_pre_existing_double_blank_line_on_write(cdb, tmp_path, monkeypatch):
    """Regression test (MD012, no-multiple-blanks): whatever the source —
    a stray double blank line already sitting in the doc before this run
    touched it at all, not something this specific run's own edit
    introduced — must never survive a write this script makes. Uses its
    own minimal fixture (not repo_with_undocumented_component_bumps) so
    the seeded double blank line is the ONLY doc-quality issue in play."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                    {
                        "name": "openforms",
                        "alias": "openformulieren",
                        "version": "1.11.0",
                        "repository": "@maykinmedia",
                    },
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"tag": "5.0.2@sha256:bbbb"}},
                "openformulieren": {"image": {"tag": "3.4.10@sha256:cccc"}},
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
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                    {
                        "name": "openforms",
                        "alias": "openformulieren",
                        "version": "1.12.0",
                        "repository": "@maykinmedia",
                    },
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"tag": "5.0.2@sha256:bbbb"}},
                "openformulieren": {"image": {"tag": "3.5.6@sha256:dddd"}},
            }
        ),
    )
    # Deliberately seeded double blank line between the table and "##
    # Changes" -- unrelated to the row this run is about to add.
    write(
        doc_dir / "4.8.5-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.2 (unchanged) | 1.0.297 (unchanged) | n/a |\n\n\n"
        "## Changes\n\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump openformulieren, no doc row added, doc has a stray double blank line", cwd=tmp_path)

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    upgrade = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "\n\n\n" not in upgrade
    assert "| openformulieren | 3.4.10 → 3.5.6 | 1.11.0 → 1.12.0 | - |" in upgrade  # the real edit still happened


def test_main_adds_missing_row_with_resolvable_app_version(
    cdb, repo_with_undocumented_component_bumps, monkeypatch, capsys
):
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_component_bumps, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_component_bumps / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| openformulieren | 3.4.10 → 3.5.6 | 1.11.0 → 1.12.0 | - |" in upgrade
    assert "### openformulieren 3.4.10 → 3.5.6 (chart 1.11.0 → 1.12.0)" in upgrade
    assert "TODO" not in upgrade.split("### openformulieren")[1].split("###")[0]
    out = capsys.readouterr().out
    assert "Adding missing component row(s)" in out
    assert "openformulieren" in out


def test_main_adds_missing_row_with_component_specific_image_path(
    cdb, repo_with_undocumented_component_bumps, monkeypatch, capsys
):
    """keycloak-operator's real app version lives at its own registered
    lib.chart.COMPONENT_IMAGE_PATHS split-path — actual_app_version
    resolves it just like a plain "<key>.image.tag" component, so the
    new row gets a full app-version cell and Changes section, not a
    TODO stub."""
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_component_bumps, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_component_bumps / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| keycloak-operator | 26.6.4 → 26.7.3 | 1.12.1 → 1.13.0 | - |" in upgrade
    assert "### keycloak-operator 26.6.4 → 26.7.3 (chart 1.12.1 → 1.13.0)" in upgrade
    assert "TODO" not in upgrade.split("### keycloak-operator")[1].split("###")[0]
    out = capsys.readouterr().out
    assert "keycloak-operator" in out


def test_main_adds_missing_row_with_unresolvable_app_version_as_todo_stub(
    cdb, repo_with_undocumented_component_bumps, monkeypatch, capsys
):
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_component_bumps, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_component_bumps / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| redis-operator | - | 0.26.1 → 0.27.0 | - |" in upgrade
    assert "### redis-operator 0.26.1 → 0.27.0" in upgrade
    assert "TODO: describe this component's changes" in upgrade
    out = capsys.readouterr().out
    assert "redis-operator" in out


def test_main_leaves_existing_row_untouched_when_adding_missing_ones(
    cdb, repo_with_undocumented_component_bumps, monkeypatch
):
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_component_bumps, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_component_bumps / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| ZAC (Zaakafhandelcomponent) | 5.0.2 (unchanged) | 1.0.297 (unchanged) | n/a |" in upgrade


def test_main_adds_missing_sidecar_row_nested_under_a_dependency(
    cdb, repo_with_undocumented_sidecar_bump, monkeypatch, capsys
):
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_sidecar_bump, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_sidecar_bump / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| redis-operator - redis | 8.6.2 → 8.6.6 | - | - |" in upgrade
    assert "### redis-operator - redis 8.6.2 → 8.6.6" in upgrade
    assert "chart" not in upgrade.split("### redis-operator - redis")[1].split("###")[0].lower()
    out = capsys.readouterr().out
    assert "Adding missing sidecar/shared-image row(s)" in out
    assert "redis-operator - redis" in out


def test_main_adds_missing_sidecar_row_for_global_shared_image(cdb, repo_with_undocumented_sidecar_bump, monkeypatch):
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_sidecar_bump, "4.8.5")
    cdb.main()

    upgrade = (repo_with_undocumented_sidecar_bump / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| curl | 8.10.1 → 8.11.0 | - | - |" in upgrade
    assert "### curl 8.10.1 → 8.11.0" in upgrade
