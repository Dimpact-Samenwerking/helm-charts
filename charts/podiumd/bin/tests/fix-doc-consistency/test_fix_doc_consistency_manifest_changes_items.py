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
    """Real symptom: a lockstep component's TWO missing_paths each got
    their own identical header item on an earlier (buggy) run — the
    second, exact-duplicate "ita 3.2.0 -> 3.3.0." item is dropped, and
    every item after it is renumbered down by one."""
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
    """A wrapped continuation line is part of the item's own compared
    text, and moves/stays with whichever occurrence of that item is
    kept — never left orphaned or duplicated on its own."""
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

# entries + entry_positions mirror what images_manifest_entry_positions
# would compute for a manifest listing redis-operator's own entry
# BEFORE zac's — position is what sort_images_manifest_changes_items
# now mirrors, instead of an independently fuzzy-matched dependency
# order (see the function's own docstring for why that regressed).
CHANGES_ITEMS_ENTRIES = [
    {"name": "opstree/redis-operator", "version": "0.26.0"},
    {"name": "infonl/zac", "version": "5.4.4"},
]
CHANGES_ITEMS_POSITIONS = {"opstree/redis-operator": 0, "infonl/zac": 1}


def test_sort_images_manifest_changes_items_reorders_and_renumbers(cdb: ModuleType):
    lines = [
        "# Baseline: podiumd 4.8.5.\n",
        "#\n",
        "# Changes:\n",
        "#   1. zac 5.0.2 -> 5.4.4.\n",
        "#   2. redis-operator 0.25.0 -> 0.26.0.\n",
        "\n",
    ]
    moved = cdb.sort_images_manifest_changes_items(lines, CHANGES_ITEMS_ENTRIES, CHANGES_ITEMS_POSITIONS)
    assert moved == [("redis-operator 0.25.0 -> 0.26.0.", 2, 1), ("zac 5.0.2 -> 5.4.4.", 1, 2)]
    assert lines[3] == "#   1. redis-operator 0.25.0 -> 0.26.0.\n"
    assert lines[4] == "#   2. zac 5.0.2 -> 5.4.4.\n"


def test_sort_images_manifest_changes_items_display_name_exact_match_takes_priority(cdb: ModuleType):
    """Real bug: "kiss" (a dependency's own bare alias) shares no word
    at all with its own image's repository basename ("kiss-frontend"),
    so match_changes_item_to_entry's fuzzy basename-in-text search could
    never resolve it — landing "kiss"'s own primary item far from its
    real sidecars ("kiss - crawler", "kiss - kiss-elastic-sync") despite
    the entry list itself already grouping all three together. Given
    display_name_positions, matched by EXACT prefix instead."""
    entries = [
        {"name": "klantinteractie-servicesysteem/kiss-frontend", "version": "3.0.0"},
        {"name": "integrations/crawler", "version": "1.0.0"},
        {"name": "opstree/redis-operator", "version": "0.26.0"},
    ]
    entry_positions = {
        "klantinteractie-servicesysteem/kiss-frontend": 0,
        "integrations/crawler": 1,
        "opstree/redis-operator": 2,
    }
    display_name_positions = {"kiss": 0, "kiss - crawler": 1, "redis-operator": 2}
    lines = [
        "# Changes:\n",
        "#   1. redis-operator 0.25.0 -> 0.26.0.\n",
        "#   2. kiss 2.2.4 -> 3.0.0.\n",
        "#   3. kiss - crawler 1.0.0 -> 1.0.0.\n",
        "\n",
    ]
    moved = cdb.sort_images_manifest_changes_items(lines, entries, entry_positions, display_name_positions)
    assert moved == [
        ("kiss 2.2.4 -> 3.0.0.", 2, 1),
        ("kiss - crawler 1.0.0 -> 1.0.0.", 3, 2),
        ("redis-operator 0.25.0 -> 0.26.0.", 1, 3),
    ]
    assert lines[1] == "#   1. kiss 2.2.4 -> 3.0.0.\n"
    assert lines[2] == "#   2. kiss - crawler 1.0.0 -> 1.0.0.\n"
    assert lines[3] == "#   3. redis-operator 0.25.0 -> 0.26.0.\n"


def test_sort_images_manifest_changes_items_display_name_prefers_longest_match(cdb: ModuleType):
    """ "keycloak-operator" is itself a valid, shorter prefix of
    "keycloak-operator - postgres 16 -> 16.15." — the longer, more
    specific display name must win, not the primary's own shorter one."""
    entries = [{"name": "postgres", "version": "16.15"}, {"name": "keycloak/keycloak", "version": "26.7.2"}]
    entry_positions = {"postgres": 1, "keycloak/keycloak": 0}
    display_name_positions = {"keycloak-operator": 0, "keycloak-operator - postgres": 1}
    lines = [
        "# Changes:\n",
        "#   1. keycloak-operator - postgres 16 -> 16.15.\n",
        "#   2. keycloak-operator 26.6.4 -> 26.7.2.\n",
        "\n",
    ]
    cdb.sort_images_manifest_changes_items(lines, entries, entry_positions, display_name_positions)
    assert lines[1] == "#   1. keycloak-operator 26.6.4 -> 26.7.2.\n"
    assert lines[2] == "#   2. keycloak-operator - postgres 16 -> 16.15.\n"


def test_sort_images_manifest_changes_items_no_display_name_positions_falls_back_to_fuzzy(cdb: ModuleType):
    """Omitting display_name_positions (the default) behaves exactly as
    before — the existing fuzzy match_changes_item_to_entry path, fully
    unaffected."""
    lines = [
        "# Changes:\n",
        "#   1. zac 5.0.2 -> 5.4.4.\n",
        "#   2. redis-operator 0.25.0 -> 0.26.0.\n",
        "\n",
    ]
    moved = cdb.sort_images_manifest_changes_items(lines, CHANGES_ITEMS_ENTRIES, CHANGES_ITEMS_POSITIONS)
    assert moved == [("redis-operator 0.25.0 -> 0.26.0.", 2, 1), ("zac 5.0.2 -> 5.4.4.", 1, 2)]


def test_sort_images_manifest_changes_items_continuation_line_travels_with_item(cdb: ModuleType):
    """A wrapped continuation line (2+ spaces after "#") stays attached
    to its own item when that item moves — never split off or left
    behind at its old position."""
    lines = [
        "# Changes:\n",
        "#   1. zac 5.0.2 -> 5.4.4.\n",
        "#   2. redis-operator (shared global.images.nginx anchor, used by every\n",
        "#      nginx sidecar in the chart) 0.25.0 -> 0.26.0.\n",
        "\n",
    ]
    moved = cdb.sort_images_manifest_changes_items(lines, CHANGES_ITEMS_ENTRIES, CHANGES_ITEMS_POSITIONS)
    assert len(moved) == 2
    assert lines[1].startswith("#   1. redis-operator (shared")
    assert lines[2] == "#      nginx sidecar in the chart) 0.25.0 -> 0.26.0.\n"
    assert lines[3] == "#   2. zac 5.0.2 -> 5.4.4.\n"


def test_sort_images_manifest_changes_items_unresolved_item_sorts_last(cdb: ModuleType):
    """An item that doesn't resolve to any of this manifest's own
    entries (free-form prose — see lib.docs_consistency.match_changes_
    item_to_entry) sorts after every real one — never dragged around by
    a real item's move."""
    lines = [
        "# Changes:\n",
        "#   1. Totally Unknown Thing 1.0.0 -> 2.0.0.\n",
        "#   2. zac 5.0.2 -> 5.4.4.\n",
        "#   3. redis-operator 0.25.0 -> 0.26.0.\n",
        "\n",
    ]
    cdb.sort_images_manifest_changes_items(lines, CHANGES_ITEMS_ENTRIES, CHANGES_ITEMS_POSITIONS)
    assert lines[1] == "#   1. redis-operator 0.25.0 -> 0.26.0.\n"
    assert lines[2] == "#   2. zac 5.0.2 -> 5.4.4.\n"
    assert lines[3] == "#   3. Totally Unknown Thing 1.0.0 -> 2.0.0.\n"


def test_sort_images_manifest_changes_items_mirrors_entry_order_not_fuzzy_dependency_match(cdb: ModuleType):
    """The real bug this redesign fixes: an item's own free-form prose
    mentioning an unrelated dependency's name only incidentally (here,
    "keycloak-operator" inside a parenthetical aside about "keycloak
    app image") must NOT be fuzzy-matched to that dependency — it must
    follow whichever entry match_changes_item_to_entry actually
    resolves it to (its own "keycloak/keycloak" entry), landing at
    THAT entry's own real position, not wherever a "keycloak-operator"
    dependency-name match would have placed it."""
    entries = [{"name": "postgres", "version": "16.15"}, {"name": "keycloak/keycloak", "version": "26.7.2"}]
    positions = {"postgres": 0, "keycloak/keycloak": 1}
    lines = [
        "# Changes:\n",
        "#   1. Keycloak app image 26.6.4 -> 26.7.2 (keycloak-operator chart\n",
        "#      unchanged, 1.12.1).\n",
        "#   2. keycloak-operator - postgres 16 -> 16.15.\n",
        "\n",
    ]
    moved = cdb.sort_images_manifest_changes_items(lines, entries, positions)
    assert len(moved) == 2
    assert lines[1] == "#   1. keycloak-operator - postgres 16 -> 16.15.\n"
    assert lines[2].startswith("#   2. Keycloak app image")


def test_sort_images_manifest_changes_items_already_ordered_reports_nothing(cdb: ModuleType):
    lines = [
        "# Changes:\n",
        "#   1. redis-operator 0.25.0 -> 0.26.0.\n",
        "#   2. zac 5.0.2 -> 5.4.4.\n",
        "\n",
    ]
    original = list(lines)
    moved = cdb.sort_images_manifest_changes_items(lines, CHANGES_ITEMS_ENTRIES, CHANGES_ITEMS_POSITIONS)
    assert moved == []
    assert lines == original


def test_sort_images_manifest_changes_items_no_header_is_a_noop(cdb: ModuleType):
    lines = ["- name: opstree/redis-operator\n", '  version: "0.26.0"\n']
    moved = cdb.sort_images_manifest_changes_items(lines, CHANGES_ITEMS_ENTRIES, CHANGES_ITEMS_POSITIONS)
    assert moved == []


def test_main_reorders_images_manifest_to_match_values_yaml(
    cdb: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """images-4.9.0.yaml lists zac before redis-operator, but values.yaml
    (via sort_keys=False — see repo_with_out_of_order_doc's own comment
    on why the dict's own insertion order matters) lists redis-operator
    first — main() must reorder the manifest's own entries too, not just
    the "Component versions" table/Changes blocks."""
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
    # The "# Changes:" numbered list is ALSO reordered and renumbered.
    assert "#   1. redis-operator 0.25.0 -> 0.26.0.\n" in text
    assert "#   2. zac 5.0.2 -> 5.4.4.\n" in text

    out = capsys.readouterr().out
    assert "Reordering" in out
    assert "'# Changes:' item 2 -> 1: redis-operator 0.25.0 -> 0.26.0." in out
    assert "'# Changes:' item 1 -> 2: zac 5.0.2 -> 5.4.4." in out
    assert "entry 'redis-operator': position 2 -> 1" in out
    assert "entry 'zac': position 1 -> 2" in out
