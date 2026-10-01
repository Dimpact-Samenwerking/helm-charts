"""dedupe_images_manifest_changes_items, sort_images_manifest_changes_items."""

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


# --- dedupe_images_manifest_changes_items ---


def test_dedupe_images_manifest_changes_items_removes_exact_repeat_and_renumbers(cdb: ModuleType):
    """A lockstep component's duplicate header item (from a buggy run) is
    dropped and later items renumbered."""
    lines = [
        "# Changes:\n",
        "#   1. redis-operator 0.25.0 -> 0.26.0.\n",
        "#   2. ita 3.2.0 -> 3.3.0.\n",
        "#   3. ita 3.2.0 -> 3.3.0.\n",
        "#   4. zac 5.0.2 -> 5.4.4.\n",
        "\n",
    ]
    removed = cdb.dedupe_images_manifest_changes_items(lines)
    assert removed == ["ita 3.2.0 -> 3.3.0."]
    assert lines[1] == "#   1. redis-operator 0.25.0 -> 0.26.0.\n"
    assert lines[2] == "#   2. ita 3.2.0 -> 3.3.0.\n"
    assert lines[3] == "#   3. zac 5.0.2 -> 5.4.4.\n"
    assert lines[4] == "\n"
    assert len(lines) == 5


def test_dedupe_images_manifest_changes_items_updates_header_count_word(cdb: ModuleType):
    lines = [
        "# Four changes:\n",
        "#   1. openzaak 1.27.4 -> 1.29.3.\n",
        "#   2. kiss-eck 8.19.3 -> 8.19.19.\n",
        "#   3. kiss-eck 8.19.3 -> 8.19.19.\n",
        "#   4. zac 5.0.2 -> 5.4.4.\n",
    ]
    removed = cdb.dedupe_images_manifest_changes_items(lines)
    assert removed == ["kiss-eck 8.19.3 -> 8.19.19."]
    assert lines[0] == "# Three changes:\n"


def test_dedupe_images_manifest_changes_items_continuation_line_travels_with_kept_item(cdb: ModuleType):
    """A wrapped continuation line belongs to its item and goes with the
    kept occurrence."""
    lines = [
        "# Changes:\n",
        "#   1. openzaak 1.27.4 -> 1.29.3.\n",
        "#   2. ita 3.2.0 -> 3.3.0. Web and\n",
        "#      poller, tag bumps only.\n",
        "#   3. ita 3.2.0 -> 3.3.0. Web and\n",
        "#      poller, tag bumps only.\n",
    ]
    removed = cdb.dedupe_images_manifest_changes_items(lines)
    assert removed == ["ita 3.2.0 -> 3.3.0. Web and"]
    assert lines == [
        "# Changes:\n",
        "#   1. openzaak 1.27.4 -> 1.29.3.\n",
        "#   2. ita 3.2.0 -> 3.3.0. Web and\n",
        "#      poller, tag bumps only.\n",
    ]


def test_dedupe_images_manifest_changes_items_no_duplicates_is_a_noop(cdb: ModuleType):
    lines = [
        "# Changes:\n",
        "#   1. openzaak 1.27.4 -> 1.29.3.\n",
        "#   2. zac 5.0.2 -> 5.4.4.\n",
    ]
    original = list(lines)
    removed = cdb.dedupe_images_manifest_changes_items(lines)
    assert removed == []
    assert lines == original


def test_dedupe_images_manifest_changes_items_no_header_returns_empty(cdb: ModuleType):
    lines = ["- name: opstree/redis-operator\n", '  version: "0.26.0"\n']
    assert cdb.dedupe_images_manifest_changes_items(lines) == []


# --- sort_images_manifest_changes_items ---

# display_name_positions as images_manifest_display_name_positions computes them
# for a manifest listing redis-operator before zac.
CHANGES_ITEMS_POSITIONS = {"redis-operator": 0, "zac": 1}


def test_sort_images_manifest_changes_items_reorders_and_renumbers(cdb: ModuleType):
    lines = [
        "# Baseline: podiumd 4.8.5.\n",
        "#\n",
        "# Changes:\n",
        "#   1. zac 5.0.2 -> 5.4.4.\n",
        "#   2. redis-operator 0.25.0 -> 0.26.0.\n",
        "\n",
    ]
    moved = cdb.sort_images_manifest_changes_items(lines, CHANGES_ITEMS_POSITIONS)
    assert moved == [("redis-operator 0.25.0 -> 0.26.0.", 2, 1), ("zac 5.0.2 -> 5.4.4.", 1, 2)]
    assert lines[3] == "#   1. redis-operator 0.25.0 -> 0.26.0.\n"
    assert lines[4] == "#   2. zac 5.0.2 -> 5.4.4.\n"


def test_sort_images_manifest_changes_items_matches_the_display_name_not_the_image_basename(cdb: ModuleType):
    """Regression: "kiss" shares no word with its basename "kiss-frontend"; the display name keeps it with its sidecars."""
    display_name_positions = {"kiss": 0, "kiss - crawler": 1, "redis-operator": 2}
    lines = [
        "# Changes:\n",
        "#   1. redis-operator 0.25.0 -> 0.26.0.\n",
        "#   2. kiss 2.2.4 -> 3.0.0.\n",
        "#   3. kiss - crawler 1.0.0 -> 1.0.0.\n",
        "\n",
    ]
    moved = cdb.sort_images_manifest_changes_items(lines, display_name_positions)
    assert moved == [
        ("kiss 2.2.4 -> 3.0.0.", 2, 1),
        ("kiss - crawler 1.0.0 -> 1.0.0.", 3, 2),
        ("redis-operator 0.25.0 -> 0.26.0.", 1, 3),
    ]


def test_sort_images_manifest_changes_items_display_name_prefers_longest_match(cdb: ModuleType):
    """The longest matching display-name prefix wins over the primary's."""
    display_name_positions = {"keycloak-operator": 0, "keycloak-operator - postgres": 1}
    lines = [
        "# Changes:\n",
        "#   1. keycloak-operator - postgres 16 -> 16.15.\n",
        "#   2. keycloak-operator 26.6.4 -> 26.7.2.\n",
        "\n",
    ]
    cdb.sort_images_manifest_changes_items(lines, display_name_positions)
    assert lines[1] == "#   1. keycloak-operator 26.6.4 -> 26.7.2.\n"
    assert lines[2] == "#   2. keycloak-operator - postgres 16 -> 16.15.\n"


def test_sort_images_manifest_changes_items_continuation_line_travels_with_item(cdb: ModuleType):
    """A wrapped continuation line (2+ spaces after "#") moves with its item."""
    lines = [
        "# Changes:\n",
        "#   1. zac 5.0.2 -> 5.4.4.\n",
        "#   2. redis-operator (shared global.images.nginx anchor, used by every\n",
        "#      nginx sidecar in the chart) 0.25.0 -> 0.26.0.\n",
        "\n",
    ]
    moved = cdb.sort_images_manifest_changes_items(lines, CHANGES_ITEMS_POSITIONS)
    assert len(moved) == 2
    assert lines[1].startswith("#   1. redis-operator (shared")
    assert lines[2] == "#      nginx sidecar in the chart) 0.25.0 -> 0.26.0.\n"
    assert lines[3] == "#   2. zac 5.0.2 -> 5.4.4.\n"


def test_sort_images_manifest_changes_items_hand_written_item_sorts_last(cdb: ModuleType):
    """An item naming no display name sorts after all real ones, even when it mentions a component."""
    lines = [
        "# Changes:\n",
        "#   1. Keycloak app image 26.6.4 -> 26.7.2 (zac chart unchanged).\n",
        "#   2. zac 5.0.2 -> 5.4.4.\n",
        "#   3. redis-operator 0.25.0 -> 0.26.0.\n",
        "\n",
    ]
    cdb.sort_images_manifest_changes_items(lines, CHANGES_ITEMS_POSITIONS)
    assert lines[1] == "#   1. redis-operator 0.25.0 -> 0.26.0.\n"
    assert lines[2] == "#   2. zac 5.0.2 -> 5.4.4.\n"
    assert lines[3].startswith("#   3. Keycloak app image")


def test_sort_images_manifest_changes_items_already_ordered_reports_nothing(cdb: ModuleType):
    lines = [
        "# Changes:\n",
        "#   1. redis-operator 0.25.0 -> 0.26.0.\n",
        "#   2. zac 5.0.2 -> 5.4.4.\n",
        "\n",
    ]
    original = list(lines)
    moved = cdb.sort_images_manifest_changes_items(lines, CHANGES_ITEMS_POSITIONS)
    assert moved == []
    assert lines == original


def test_sort_images_manifest_changes_items_no_header_is_a_noop(cdb: ModuleType):
    lines = ["- name: opstree/redis-operator\n", '  version: "0.26.0"\n']
    moved = cdb.sort_images_manifest_changes_items(lines, CHANGES_ITEMS_POSITIONS)
    assert moved == []


def test_main_reorders_images_manifest_to_match_values_yaml(
    cdb: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """main() reorders manifest entries to values.yaml order too, not just
    the table and Changes blocks."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "redis-operator", "version": "0.26.1", "repository": "@opstree"},
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                ],
            },
            sort_keys=False,
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "redis-operator": {
                    "image": {"repository": "quay.io/opstree/redis-operator", "tag": "0.26.0@sha256:aaaa"}
                },
                "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.4@sha256:bbbb"}},
            },
            sort_keys=False,
        ),
    )
    doc_dir = tmp_path / "docs" / "_UPGRADE_PATHS"
    doc_dir.mkdir(parents=True)
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    images_path = images_dir / "images-4.9.0.yaml"
    write(
        images_path,
        "# Baseline: podiumd 4.8.5. Re-verify before release.\n"
        "#\n"
        "# Changes:\n"
        "#   1. zac 5.0.2 -> 5.4.4.\n"
        "#   2. redis-operator 0.25.0 -> 0.26.0.\n"
        "\n"
        "# zac 5.0.2 -> 5.4.4\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.4.4"\n'
        '  digest: "sha256:bbbb"\n\n'
        "# redis-operator 0.25.0 -> 0.26.0\n"
        "- name: opstree/redis-operator\n"
        "  url: quay.io/opstree/redis-operator\n"
        '  version: "0.26.0"\n'
        '  digest: "sha256:aaaa"\n',
    )
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "seed out-of-order images manifest", cwd=tmp_path)

    set_argv_and_dir(cdb, monkeypatch, doc_dir, "4.8.5")
    cdb.main()

    text = images_path.read_text(encoding="utf-8")
    assert text.index("opstree/redis-operator") < text.index("infonl/zaakafhandelcomponent")
    # Each entry's own comment travels WITH it, never left behind.
    assert text.index("# redis-operator") < text.index("- name: opstree/redis-operator")
    assert text.index("# zac") < text.index("- name: infonl/zaakafhandelcomponent")
    assert "#   1. redis-operator 0.25.0 -> 0.26.0.\n" in text
    assert "#   2. zac 5.0.2 -> 5.4.4.\n" in text
    assert text.index("#   1. redis-operator") < text.index("#   2. zac")
    assert "#   1. zac 5.0.2 -> 5.4.4.\n" not in text
    assert "#   2. redis-operator 0.25.0 -> 0.26.0.\n" not in text

    out = capsys.readouterr().out
    assert "Reordering" in out
    assert "'# Changes:' item 2 -> 1: redis-operator 0.25.0 -> 0.26.0." in out
    assert "'# Changes:' item 1 -> 2: zac 5.0.2 -> 5.4.4." in out
    assert "entry 'redis-operator': position 2 -> 1" in out
    assert "entry 'zac': position 1 -> 2" in out
