"""main() integration: missing values-deltas.md mentions, "# Changes:"
renumbering, and the images-baseline.yaml fallback for new components."""

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


# --- main() integration: values-deltas.md missing top-level component mention ---


@pytest.fixture
def repo_with_unmentioned_component_bump(tmp_path: Path):
    """zaakbrug's tag and schema changed, but values-deltas.md has no section.
    The schema change is needed: a version-only bump gets no section."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakbrug", "version": "2.3.28", "repository": "https://wearefrank.github.io/charts"},
                ],
            }
        ),
    )
    write(tmp_path / "values.yaml", yaml.safe_dump({"zaakbrug": {"image": {"tag": "1.26.14@sha256:aaaa"}}}))
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
                "zaakbrug": {"image": {"tag": "1.26.15@sha256:bbbb"}, "newFeature": {"enabled": True}},
            }
        ),
    )
    write(
        doc_dir / "4.8.3-to-4.9.0-values-deltas.md",
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\nNo unrelated changes.\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zaakbrug, no values-deltas mention", cwd=tmp_path)
    return doc_dir


def test_main_adds_missing_values_delta_bullet(
    cdb: ModuleType,
    repo_with_unmentioned_component_bump,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    set_argv_and_dir(cdb, monkeypatch, repo_with_unmentioned_component_bump, "4.8.5")
    cdb.main()

    deltas = (repo_with_unmentioned_component_bump / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## zaakbrug 1.26.14 → 1.26.15 (chart 2.3.28, unchanged)\n" in deltas
    assert "- Key `zaakbrug.newFeature` was added.\n" in deltas
    assert "No unrelated changes." in deltas  # existing content preserved
    out = capsys.readouterr().out
    assert "Adding new component section(s)" in out
    assert "zaakbrug" in out


def test_main_collapses_pre_existing_double_blank_line_in_values_deltas(
    cdb: ModuleType, repo_with_unmentioned_component_bump, monkeypatch: pytest.MonkeyPatch
):
    """A stray double blank line never survives a values-deltas write."""
    doc = repo_with_unmentioned_component_bump / "4.8.3-to-4.9.0-values-deltas.md"
    doc.write_text("# Values deltas — PodiumD 4.8.3 → 4.9.0\n\n\nNo unrelated changes.\n", encoding="utf-8")
    set_argv_and_dir(cdb, monkeypatch, repo_with_unmentioned_component_bump, "4.8.5")
    cdb.main()

    deltas = (repo_with_unmentioned_component_bump / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "\n\n\n" not in deltas
    assert "## zaakbrug 1.26.14 → 1.26.15 (chart 2.3.28, unchanged)\n" in deltas  # the real edit still happened


def test_main_does_not_duplicate_already_mentioned_component_bullet(
    cdb: ModuleType,
    repo_with_unmentioned_component_bump,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    doc = repo_with_unmentioned_component_bump / "4.8.3-to-4.9.0-values-deltas.md"
    doc.write_text(
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\n"
        "## zaakbrug 1.26.14 → 1.26.15 (chart 2.3.28, unchanged)\n\n"
        "- Key `zaakbrug.newFeature` was added.\n",
        encoding="utf-8",
    )
    set_argv_and_dir(cdb, monkeypatch, repo_with_unmentioned_component_bump, "4.8.5")
    cdb.main()

    deltas = (repo_with_unmentioned_component_bump / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert deltas.count("## zaakbrug") == 1
    assert deltas.count("zaakbrug.newFeature") == 1
    out = capsys.readouterr().out
    assert "Adding new component section(s)" not in out
    assert "Updating key-change mention(s)" not in out


@pytest.fixture
def repo_with_pure_version_bump_and_stale_empty_section(tmp_path: Path):
    """A heading-only section for a schema-less version bump is pruned, not
    re-added."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakbrug", "version": "2.3.28", "repository": "https://wearefrank.github.io/charts"},
                ],
            }
        ),
    )
    write(tmp_path / "values.yaml", yaml.safe_dump({"zaakbrug": {"image": {"tag": "1.26.14@sha256:aaaa"}}}))
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    (tmp_path / "docs" / "images").mkdir(parents=True)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline state", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    write(tmp_path / "values.yaml", yaml.safe_dump({"zaakbrug": {"image": {"tag": "1.26.15@sha256:bbbb"}}}))
    write(
        doc_dir / "4.8.3-to-4.9.0-values-deltas.md",
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\n## zaakbrug 1.26.14 → 1.26.15 (chart 2.3.28, unchanged)\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zaakbrug, pure version bump", cwd=tmp_path)
    return doc_dir


def test_main_prunes_stale_empty_section_without_recreating_it(
    cdb: ModuleType,
    repo_with_pure_version_bump_and_stale_empty_section,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    set_argv_and_dir(cdb, monkeypatch, repo_with_pure_version_bump_and_stale_empty_section, "4.8.5")
    cdb.main()

    deltas = (repo_with_pure_version_bump_and_stale_empty_section / "4.8.5-to-4.9.0-values-deltas.md").read_text(
        encoding="utf-8"
    )
    assert "## zaakbrug" not in deltas
    out = capsys.readouterr().out
    assert "Removing empty section(s)" in out
    assert "'## zaakbrug 1.26.14 → 1.26.15 (chart 2.3.28, unchanged)'" in out
    assert "Adding new component section(s)" not in out


@pytest.fixture
def repo_with_unmentioned_native_component_bump(tmp_path: Path):
    """frankgateway (native, no Chart.yaml dependency) with tag and schema
    changes: covers the NATIVE_COMPONENTS branches of add_missing_component_rows
    and sync_values_delta_sections together."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakbrug", "version": "2.3.28", "repository": "https://wearefrank.github.io/charts"},
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zaakbrug": {"image": {"tag": "1.26.15@sha256:aaaa"}},
                "frankgateway": {"image": {"tag": "100@sha256:aaaa"}},
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
                "zaakbrug": {"image": {"tag": "1.26.15@sha256:aaaa"}},
                "frankgateway": {"image": {"tag": "104@sha256:bbbb"}, "nodeSelector": {"disktype": "ssd"}},
            }
        ),
    )
    write(
        doc_dir / "4.8.3-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| zaakbrug | 1.26.15 (unchanged) | 2.3.28 (unchanged) | - |\n\n"
        "## Changes\n\n",
    )
    write(
        doc_dir / "4.8.3-to-4.9.0-values-deltas.md",
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\nNo unrelated changes.\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump frankgateway, no row or values-deltas mention", cwd=tmp_path)
    return doc_dir


def test_main_adds_missing_native_component_row_and_bullet(
    cdb: ModuleType,
    repo_with_unmentioned_native_component_bump,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    set_argv_and_dir(cdb, monkeypatch, repo_with_unmentioned_native_component_bump, "4.8.5")
    cdb.main()

    upgrade = (repo_with_unmentioned_native_component_bump / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| frankgateway | 100 → 104 | - | - |" in upgrade

    deltas = (repo_with_unmentioned_native_component_bump / "4.8.5-to-4.9.0-values-deltas.md").read_text(
        encoding="utf-8"
    )
    assert "## frankgateway 100 → 104\n" in deltas
    assert "- Key `frankgateway.nodeSelector` was added.\n" in deltas

    out = capsys.readouterr().out
    assert "Adding missing component row(s)" in out
    assert "Adding new component section(s)" in out


def test_main_adds_todo_bullet_when_app_version_unresolvable(
    cdb: ModuleType, repo_with_undocumented_component_bumps, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Chart-only redis-operator with a new key, for the values-deltas heading
    (a schema-less chart bump would get no section)."""
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"tag": "5.0.2@sha256:bbbb"}},
                "openformulieren": {"image": {"tag": "3.5.6@sha256:dddd"}},
                "keycloak-operator": {"operator": {"config": {"keycloakImage": {"tag": "26.7.3", "sha": "ffff"}}}},
                "redis-operator": {"redisOperator": {"newFeature": True}},
            }
        ),
    )
    write(
        repo_with_undocumented_component_bumps / "4.8.3-to-4.9.0-values-deltas.md",
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\nNo unrelated changes.\n",
    )
    git("add", "-A", cwd=repo_with_undocumented_component_bumps)
    git(
        "commit",
        "-q",
        "-m",
        "add values-deltas doc + redis-operator schema key",
        cwd=repo_with_undocumented_component_bumps,
    )
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_component_bumps, "4.8.5")
    cdb.main()

    deltas = (repo_with_undocumented_component_bumps / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## redis-operator chart 0.26.1 → 0.27.0 — TODO: describe this component's changes" in deltas
    assert "- Key `redis-operator.redisOperator` was added.\n" in deltas


# --- main() integration: values-deltas.md missing key-change mentions ---


@pytest.fixture
def repo_with_undocumented_schema_change(tmp_path: Path):
    """zac drops "brpApi.extendWithZaaktype" but values-deltas.md doesn't mention it."""
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
                "zac": {
                    "image": {"tag": "5.0.2@sha256:bbbb"},
                    "brpApi": {"protocollering": {"verwerking": {"extendWithZaaktype": False, "otherKey": True}}},
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
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {
                    "image": {"tag": "5.1.0@sha256:aaaa"},
                    # extendWithZaaktype gone, otherKey remains — undocumented
                    "brpApi": {"protocollering": {"verwerking": {"otherKey": True}}},
                },
            }
        ),
    )
    write(
        doc_dir / "4.8.3-to-4.9.0-values-deltas.md",
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\nNo gemeente podiumd.yml changes are required for this hop.\n",
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zac, schema change undocumented", cwd=tmp_path)
    return doc_dir


def test_main_adds_missing_key_change_mention(
    cdb: ModuleType,
    repo_with_undocumented_schema_change,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_schema_change, "4.8.5")
    cdb.main()

    deltas = (repo_with_undocumented_schema_change / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    # No section names zac yet, so a new one carries the key-change line.
    assert "## zac 5.0.2 → 5.1.0 (chart 1.0.297, unchanged)\n" in deltas
    assert "- Key `zac.brpApi.protocollering.verwerking.extendWithZaaktype` was removed.\n" in deltas
    assert "No gemeente podiumd.yml changes are required" in deltas  # existing content preserved
    out = capsys.readouterr().out
    assert "Adding new component section(s)" in out


def test_main_adds_generated_line_above_user_prose(
    cdb: ModuleType,
    repo_with_undocumented_schema_change,
    monkeypatch: pytest.MonkeyPatch,
):
    """A prose mention doesn't replace the generated line: it goes right after the heading, the prose stays."""
    doc = repo_with_undocumented_schema_change / "4.8.3-to-4.9.0-values-deltas.md"
    doc.write_text(
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\n"
        "## zac 5.0.2 → 5.1.0 (chart 1.0.297, unchanged)\n\n"
        "Removed `zac.brpApi.protocollering.verwerking.extendWithZaaktype` — no longer needed.\n",
        encoding="utf-8",
    )
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_schema_change, "4.8.5")
    cdb.main()

    deltas = (repo_with_undocumented_schema_change / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert deltas == (
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\n"
        "## zac 5.0.2 → 5.1.0 (chart 1.0.297, unchanged)\n\n"
        "- Key `zac.brpApi.protocollering.verwerking.extendWithZaaktype` was removed.\n\n"
        "Removed `zac.brpApi.protocollering.verwerking.extendWithZaaktype` — no longer needed.\n"
    )


def test_main_does_not_duplicate_generated_key_change_line(
    cdb: ModuleType,
    repo_with_undocumented_schema_change,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    doc = repo_with_undocumented_schema_change / "4.8.3-to-4.9.0-values-deltas.md"
    doc.write_text(
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\n"
        "## zac 5.0.2 → 5.1.0 (chart 1.0.297, unchanged)\n\n"
        "- Key `zac.brpApi.protocollering.verwerking.extendWithZaaktype` was removed.\n\n"
        "No longer needed.\n",
        encoding="utf-8",
    )
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_schema_change, "4.8.5")
    cdb.main()

    deltas = (repo_with_undocumented_schema_change / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert deltas.count("extendWithZaaktype") == 1
    out = capsys.readouterr().out
    assert "Updating key-change mention(s)" not in out


def test_main_adds_key_change_line_shown_only_inside_a_fenced_code_block(
    cdb: ModuleType,
    repo_with_undocumented_schema_change,
    monkeypatch: pytest.MonkeyPatch,
):
    """An example of the line in a ``` fence is user text, not the section's generated line."""
    key_line = "- Key `zac.brpApi.protocollering.verwerking.extendWithZaaktype` was removed.\n"
    example = "Example:\n\n```markdown\n" + key_line + "```\n"
    doc = repo_with_undocumented_schema_change / "4.8.3-to-4.9.0-values-deltas.md"
    doc.write_text(
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\n## zac 5.0.2 → 5.1.0 (chart 1.0.297, unchanged)\n\n" + example,
        encoding="utf-8",
    )
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_schema_change, "4.8.5")
    cdb.main()

    deltas = (repo_with_undocumented_schema_change / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "## zac 5.0.2 → 5.1.0 (chart 1.0.297, unchanged)\n\n" + key_line + "\n" + example in deltas


# --- main() integration: renumbering a pre-existing "# Changes:" gap ---


@pytest.fixture
def repo_with_fully_documented_images_but_a_numbering_gap(tmp_path: Path):
    """Everything is correct except a numbering gap in the manifest's
    "# Changes:" list (a hand-removed item); dedupe and sort alone never
    renumber this."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "version": "1.0.297", "repository": "@zac", "alias": "zac"},
                    {
                        "name": "openforms",
                        "version": "1.12.0",
                        "repository": "@maykinmedia",
                        "alias": "openformulieren",
                    },
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"tag": "5.0.2@sha256:aaaa"}},
                "openformulieren": {"image": {"tag": "3.4.10@sha256:bbbb"}},
            },
            sort_keys=False,
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
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zac": {"image": {"tag": "5.4.3@sha256:cccc"}},
                "openformulieren": {"image": {"tag": "3.5.6@sha256:dddd"}},
            },
            sort_keys=False,
        ),
    )
    write(
        doc_dir / "4.8.3-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.4.3 | 1.0.297 (unchanged) | n/a |\n"
        "| openformulieren | 3.4.10 → 3.5.6 | 1.12.0 (unchanged) | n/a |\n\n"
        "## Changes\n\n",
    )
    write(
        doc_dir / "4.8.3-to-4.9.0-values-deltas.md",
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\nNo unrelated changes.\n",
    )
    write(
        images_dir / "images-4.9.0.yaml",
        "# Baseline: podiumd 4.8.5.\n#\n"
        "# Images new or changed in podiumd 4.9.0 vs 4.8.5.\n#\n"
        "# Changes:\n"
        "#   1. ZAC (Zaakafhandelcomponent) 5.0.2 -> 5.4.3.\n"
        "#   3. openformulieren 3.4.10 -> 3.5.6.\n#\n\n"
        "# ZAC — 5.0.2 -> 5.4.3\n"
        "- name: zac\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.4.3"\n'
        '  digest: "sha256:cccc"\n\n'
        "# openformulieren — 3.4.10 -> 3.5.6\n"
        "- name: openformulieren\n"
        "  url: maykinmedia/open-forms\n"
        '  version: "3.5.6"\n'
        '  digest: "sha256:dddd"\n',
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump both, images-manifest header has a gap", cwd=tmp_path)
    return doc_dir, images_dir


def test_main_renumbers_a_preexisting_changes_gap(
    cdb: ModuleType,
    repo_with_fully_documented_images_but_a_numbering_gap,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    doc_dir, images_dir = repo_with_fully_documented_images_but_a_numbering_gap
    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    images = (images_dir / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "#   1. ZAC (Zaakafhandelcomponent) 5.0.2 -> 5.4.3.\n" in images
    assert "#   2. openformulieren 3.4.10 -> 3.5.6.\n" in images
    assert "#   3." not in images
    out = capsys.readouterr().out
    assert "Renumbering '# Changes:' list in images-4.9.0.yaml" in out


# --- main() integration: images-baseline.yaml fallback for a brand-new component ---


@pytest.fixture
def repo_with_new_component_pinned_to_a_known_mirrored_image(tmp_path: Path):
    """A new dependency pinned to an image already recorded in an earlier
    images-4.8.0.yaml: git baseline has nothing to compare, but a known
    mirrored pin must not be listed as changed in images-4.9.0.yaml."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakbrug", "version": "2.3.28", "repository": "https://wearefrank.github.io/charts"},
                ],
            }
        ),
    )
    write(tmp_path / "values.yaml", yaml.safe_dump({"zaakbrug": {"image": {"tag": "1.26.15@sha256:aaaa"}}}))
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
                "dependencies": [
                    {"name": "zaakbrug", "version": "2.3.28", "repository": "https://wearefrank.github.io/charts"},
                    {
                        "name": "brp-personen-mock",
                        "version": "1.2.9",
                        "repository": "@dimpact",
                        "condition": "brppersonenmock.enabled",
                        "alias": "brppersonenmock",
                    },
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zaakbrug": {"image": {"tag": "1.26.15@sha256:aaaa"}},
                "brppersonenmock": {
                    "enabled": False,
                    "image": {"repository": "ghcr.io/brp-api/personen-mock", "tag": "2.7.0@sha256:bbbb"},
                },
            }
        ),
    )
    write(
        doc_dir / "4.8.3-to-4.9.0-upgrade.md",
        "# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\n"
        "## Component versions (4.9.0 vs 4.8.5)\n\n"
        "| Component | App version | Helm chart | Notes |\n"
        "| --- | --- | --- | --- |\n\n"
        "## Changes\n\n",
    )
    write(
        doc_dir / "4.8.3-to-4.9.0-values-deltas.md",
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\nNo unrelated changes.\n",
    )
    write(
        images_dir / "images-4.9.0.yaml",
        "# Baseline: podiumd 4.8.5.\n#\n# Zero changes:\n#\n\n"
        "- name: zaakbrug\n"
        "  url: wearefrank/zaakbrug\n"
        '  version: "1.26.15"\n'
        '  digest: "sha256:aaaa"\n',
    )
    write(
        images_dir / "images-4.8.0.yaml",
        "- name: brp-api/personen-mock\n"
        "  url: ghcr.io/brp-api/personen-mock\n"
        '  version: "2.7.0"\n'
        '  digest: "sha256:bbbb"\n',
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "add brppersonenmock, pinned to an already-mirrored image", cwd=tmp_path)
    return doc_dir, images_dir


def test_main_does_not_add_new_component_image_already_known_in_historical_manifest(
    cdb: ModuleType,
    repo_with_new_component_pinned_to_a_known_mirrored_image,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Only the image is skipped as known; the new schema still gets its
    -upgrade.md row/section and values-deltas.md section."""
    doc_dir, images_dir = repo_with_new_component_pinned_to_a_known_mirrored_image
    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    images = (images_dir / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "brp-api/personen-mock" not in images
    out = capsys.readouterr().out
    assert "Adding missing entr(y/ies) to images-4.9.0.yaml" not in out


def test_main_adds_new_component_image_not_in_historical_manifest(
    cdb: ModuleType, repo_with_new_component_pinned_to_a_known_mirrored_image, monkeypatch: pytest.MonkeyPatch
):
    """Without a historical manifest recording the pin, it is added as changed."""
    doc_dir, images_dir = repo_with_new_component_pinned_to_a_known_mirrored_image
    (images_dir / "images-4.8.0.yaml").write_text(
        "- name: brp-api/personen-mock\n"
        "  url: ghcr.io/brp-api/personen-mock\n"
        '  version: "2.6.0"\n'
        '  digest: "sha256:cccc"\n',
        encoding="utf-8",
    )
    repo_root = doc_dir.parent.parent
    git("add", "-A", cwd=repo_root)
    git("commit", "-q", "-m", "images-4.8.0.yaml doesn't have this pin", cwd=repo_root)
    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    images = (images_dir / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "brp-api/personen-mock" in images


def test_main_new_component_row_annotated_unchanged_when_known_in_historical_manifest(
    cdb: ModuleType, repo_with_new_component_pinned_to_a_known_mirrored_image, monkeypatch: pytest.MonkeyPatch
):
    """In the Component versions row a known pin reads "(unchanged)" for App,
    while the new Chart.yaml dependency still reads "(new)" for Helm."""
    doc_dir, _images_dir = repo_with_new_component_pinned_to_a_known_mirrored_image
    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    upgrade_doc = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| brppersonenmock | 2.7.0 (unchanged) | 1.2.9 (new) | - |" in upgrade_doc
