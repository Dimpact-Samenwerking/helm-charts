"""main() integration: values-deltas.md missing top-level component mentions and
key-change mentions, renumbering a pre-existing "# Changes:" gap, and the
images-baseline.yaml fallback for a brand-new component."""

import subprocess

import pytest
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


# --- main() integration: values-deltas.md missing top-level component mention ---


@pytest.fixture
def repo_with_unmentioned_component_bump(tmp_path):
    """zaakbrug's own app image tag changed AND a real values.yaml schema
    key was added between the baseline tag and HEAD, but values-deltas.md
    never got a section for it at all — the gap sync_values_delta_
    sections exists to fill in. The schema change matters here (not just
    the version bump): a pure version-only bump gets no values-deltas.md
    section at all (see sync_values_delta_sections' own docstring) — the
    tests below need a real "- Key ..." line to exercise section
    creation/reuse meaningfully."""
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


def test_main_adds_missing_values_delta_bullet(cdb, repo_with_unmentioned_component_bump, monkeypatch, capsys):
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
    cdb, repo_with_unmentioned_component_bump, monkeypatch
):
    """Same regression as the upgrade.md write path, for values_deltas_
    path's own write site — a stray double blank line already in the doc
    must never survive a write this script makes, regardless of source."""
    doc = repo_with_unmentioned_component_bump / "4.8.3-to-4.9.0-values-deltas.md"
    doc.write_text("# Values deltas — PodiumD 4.8.3 → 4.9.0\n\n\nNo unrelated changes.\n", encoding="utf-8")
    set_argv_and_dir(cdb, monkeypatch, repo_with_unmentioned_component_bump, "4.8.5")
    cdb.main()

    deltas = (repo_with_unmentioned_component_bump / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert "\n\n\n" not in deltas
    assert "## zaakbrug 1.26.14 → 1.26.15 (chart 2.3.28, unchanged)\n" in deltas  # the real edit still happened


def test_main_does_not_duplicate_already_mentioned_component_bullet(
    cdb, repo_with_unmentioned_component_bump, monkeypatch, capsys
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
    assert "Adding missing key-change mention(s)" not in out


@pytest.fixture
def repo_with_pure_version_bump_and_stale_empty_section(tmp_path):
    """zaakbrug's app image tag changed but its OWN values.yaml subtree
    has no schema change at all — nothing for a gemeente to act on — yet
    values-deltas.md already has a heading-only section for it (left
    over from before the "no empty sections" rule existed). fix-doc-
    consistency must prune that stale section, never re-add a fresh
    empty one in its place."""
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
    cdb, repo_with_pure_version_bump_and_stale_empty_section, monkeypatch, capsys
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
def repo_with_unmentioned_native_component_bump(tmp_path):
    """frankgateway (see lib.chart.NATIVE_COMPONENTS) has no Chart.yaml
    dependency at all — its own app image tag AND a real values.yaml
    schema key changed between the baseline tag and HEAD, with no
    "Component versions" row and no values-deltas section at all yet,
    real end-to-end coverage for both add_missing_component_rows and
    sync_values_delta_sections' own NATIVE_COMPONENTS branches together.
    The schema change matters (not just the version bump) — see
    sync_values_delta_sections' own docstring for why a pure version
    bump alone gets no values-deltas.md section at all."""
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
    cdb, repo_with_unmentioned_native_component_bump, monkeypatch, capsys
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
    cdb, repo_with_undocumented_component_bumps, tmp_path, monkeypatch
):
    """redis-operator is chart-only — no matching values.yaml image at
    all — same fixture as the "Component versions" row tests, exercised
    here for the values-deltas heading instead. A genuine schema change
    (a brand-new key under its own subtree) is added here so there's
    real "- Key ..." content to document — a pure, schema-less chart
    bump alone gets no values-deltas.md section at all (see sync_
    values_delta_sections' own docstring)."""
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
def repo_with_undocumented_schema_change(tmp_path):
    """zac's values.yaml drops the "brpApi.extendWithZaaktype" key between the
    baseline tag and HEAD, but values-deltas.md never mentions it — the real
    gap this feature exists to catch up on."""
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


def test_main_adds_missing_key_change_mention(cdb, repo_with_undocumented_schema_change, monkeypatch, capsys):
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_schema_change, "4.8.5")
    cdb.main()

    deltas = (repo_with_undocumented_schema_change / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    # No existing "## ..." section names zac yet, so it gets a brand new
    # one (see sync_values_delta_sections) carrying the missing key-change
    # line as its own body content.
    assert "## zac 5.0.2 → 5.1.0 (chart 1.0.297, unchanged)\n" in deltas
    assert "- Key `zac.brpApi.protocollering.verwerking.extendWithZaaktype` was removed.\n" in deltas
    assert "No gemeente podiumd.yml changes are required" in deltas  # existing content preserved
    out = capsys.readouterr().out
    assert "Adding new component section(s)" in out


def test_main_does_not_duplicate_already_mentioned_key_change(
    cdb, repo_with_undocumented_schema_change, monkeypatch, capsys
):
    doc = repo_with_undocumented_schema_change / "4.8.3-to-4.9.0-values-deltas.md"
    doc.write_text(
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\n"
        "Removed `zac.brpApi.protocollering.verwerking.extendWithZaaktype` — no longer needed.\n",
        encoding="utf-8",
    )
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_schema_change, "4.8.5")
    cdb.main()

    deltas = (repo_with_undocumented_schema_change / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert deltas.count("extendWithZaaktype") == 1
    out = capsys.readouterr().out
    assert "Adding missing key-change mention(s)" not in out


def test_main_ignores_mention_inside_fenced_code_block_and_does_not_duplicate(
    cdb, repo_with_undocumented_schema_change, monkeypatch, capsys
):
    """Regression: a fenced code block earlier in the doc (containing an
    unbalanced backtick, as real-world example snippets often do) used to
    desync backtick-span pairing for the REST of the document, making an
    already-mentioned key look unmentioned — main() would then re-add a
    duplicate mention right next to the real one instead of recognizing
    it (see lib.upgradedoc.strip_fenced_code_blocks)."""
    doc = repo_with_undocumented_schema_change / "4.8.3-to-4.9.0-values-deltas.md"
    doc.write_text(
        "# Values deltas — PodiumD 4.8.3 → 4.9.0\n\n"
        "```yaml\n"
        "some: `unbalanced backtick example\n"
        "```\n\n"
        "Removed `zac.brpApi.protocollering.verwerking.extendWithZaaktype` — no longer needed.\n",
        encoding="utf-8",
    )
    set_argv_and_dir(cdb, monkeypatch, repo_with_undocumented_schema_change, "4.8.5")
    cdb.main()

    deltas = (repo_with_undocumented_schema_change / "4.8.5-to-4.9.0-values-deltas.md").read_text(encoding="utf-8")
    assert deltas.count("extendWithZaaktype") == 1
    out = capsys.readouterr().out
    assert "Adding missing key-change mention(s)" not in out


# --- main() integration: renumbering a pre-existing "# Changes:" gap ---


@pytest.fixture
def repo_with_fully_documented_images_but_a_numbering_gap(tmp_path):
    """Both zac and openformulieren are already fully, correctly
    documented everywhere (no missing row/section/entry, nothing stale,
    already in the right order) — the ONLY thing wrong is the images
    manifest's own "# Changes:" list numbering, which has a gap (a
    human hand-removed a THIRD item's own block, between these two,
    without renumbering) — real case that surfaced this gap. Neither
    dedupe (no duplicates) nor sort (already correctly ordered) would
    ever touch this on their own."""
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
    cdb, repo_with_fully_documented_images_but_a_numbering_gap, monkeypatch, capsys
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
def repo_with_new_component_pinned_to_a_known_mirrored_image(tmp_path):
    """brppersonenmock is added as a brand-new Chart.yaml dependency in
    this release, pinned to an image version+digest that's ALREADY
    recorded, at the same version, in an earlier release's own docs/
    images/images-4.8.0.yaml manifest (from some earlier, unrelated
    hop) — real case that surfaced this gap. The git baseline has
    nothing at all to compare brppersonenmock's own image tag against
    (the component didn't exist there), but since this EXACT pin is
    already a known, previously-mirrored image, it must NOT be added to
    images-4.9.0.yaml as a changed image."""
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
    cdb, repo_with_new_component_pinned_to_a_known_mirrored_image, monkeypatch, capsys
):
    """brppersonenmock's own SCHEMA is genuinely new, so it still gets a
    real -upgrade.md row/Changes section and values-deltas.md section
    (unaffected by this fallback) — only its IMAGE is recognized as
    already-known (via an earlier release's own images-4.8.0.yaml
    manifest) and thus skipped from images-4.9.0.yaml specifically."""
    doc_dir, images_dir = repo_with_new_component_pinned_to_a_known_mirrored_image
    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    images = (images_dir / "images-4.9.0.yaml").read_text(encoding="utf-8")
    assert "brp-api/personen-mock" not in images
    out = capsys.readouterr().out
    assert "Adding missing entr(y/ies) to images-4.9.0.yaml" not in out


def test_main_adds_new_component_image_not_in_historical_manifest(
    cdb, repo_with_new_component_pinned_to_a_known_mirrored_image, monkeypatch
):
    """Same shape, but no historical images-<version>.yaml records this
    exact pin anywhere — still added as changed, same as before this
    fallback existed."""
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
    cdb, repo_with_new_component_pinned_to_a_known_mirrored_image, monkeypatch
):
    """The SAME fallback, applied to -upgrade.md's own "Component
    versions" row instead of images-4.9.0.yaml: brppersonenmock's
    Chart.yaml dependency is brand new (baseline has no matching
    dependency at all), but its own image pin is already recorded in
    an earlier release's own images-4.8.0.yaml manifest, so its App
    cell reads "(unchanged)" rather than a nonsensical "(new)" — its
    Helm-chart cell still correctly reads "(new)", since the Chart.yaml
    dependency line genuinely is."""
    doc_dir, images_dir = repo_with_new_component_pinned_to_a_known_mirrored_image
    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    upgrade_doc = (doc_dir / "4.8.5-to-4.9.0-upgrade.md").read_text(encoding="utf-8")
    assert "| brppersonenmock | 2.7.0 (unchanged) | 1.2.9 (new) | - |" in upgrade_doc
