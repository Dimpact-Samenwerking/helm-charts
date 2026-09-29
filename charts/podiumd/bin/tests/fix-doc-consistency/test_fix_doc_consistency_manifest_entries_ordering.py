"""add_missing_images_manifest_entries ordering, header and backfill scenarios
(ordered_images_manifest_chart_dir fixture cluster)."""

from pathlib import Path
from types import ModuleType

import pytest
import yaml


def write(path, text):
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def ordered_images_manifest_chart_dir(tmp_path: Path):
    """values.yaml order openzaak -> keycloak-operator -> zac; the postgres
    sidecar resolves via an own override, no vendored tgz needed."""
    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "openzaak", "version": "1.14.2", "repository": "@openzaak"},
                    {"name": "keycloak-operator", "version": "1.12.1", "repository": "@adfinis"},
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257", "repository": "@zac"},
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "openzaak": {"image": {"repository": "openzaak/open-zaak", "tag": "1.29.3@sha256:aaaa"}},
                "keycloak-operator": {
                    "job": {"postgres": {"image": {"repository": "postgres", "tag": "16.15@sha256:bbbb"}}}
                },
                "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:cccc"}},
            }
        ),
    )
    return tmp_path


def _ordered_deps():
    return [
        {"name": "openzaak", "version": "1.14.2"},
        {"name": "keycloak-operator", "version": "1.12.1"},
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"},
    ]


def _ordered_target_values():
    return {
        "openzaak": {"image": {"repository": "openzaak/open-zaak", "tag": "1.29.3@sha256:aaaa"}},
        "keycloak-operator": {"job": {"postgres": {"image": {"repository": "postgres", "tag": "16.15@sha256:bbbb"}}}},
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.1.0@sha256:cccc"}},
    }


def _ordered_baseline_values():
    return {
        "openzaak": {"image": {"repository": "openzaak/open-zaak", "tag": "1.27.4@sha256:aaaa"}},
        "keycloak-operator": {"job": {"postgres": {"image": {"repository": "postgres", "tag": "16.0@sha256:eeee"}}}},
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.2@sha256:cccc"}},
    }


def test_add_missing_images_manifest_entries_inserts_at_correct_body_and_header_position(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """A missing middle component is inserted between its neighbours in both
    body and "# Changes:" list, not appended at the end."""
    text = (
        "# Two changes:\n"
        "#   1. openzaak 1.27.4 -> 1.29.3.\n"
        "#   2. zac 5.0.2 -> 5.1.0.\n"
        "\n"
        "# openzaak — 1.27.4 -> 1.29.3\n"
        "- name: openzaak/open-zaak\n"
        "  url: openzaak/open-zaak\n"
        '  version: "1.29.3"\n'
        '  digest: "sha256:aaaa"\n'
        "\n"
        "# zac — 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:cccc"\n'
    )

    new_text, added, skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text,
        cdb.MissingEntriesContext(
            ordered_images_manifest_chart_dir,
            _ordered_deps(),
            _ordered_target_values(),
            _ordered_baseline_values(),
        ),
    )

    assert skipped == []
    assert added == ["keycloak-operator - postgres"]

    lines = new_text.splitlines()
    openzaak_idx = next(i for i, line in enumerate(lines) if line.startswith("# openzaak"))
    kc_idx = next(i for i, line in enumerate(lines) if line.startswith("#   sidecar: keycloak-operator - postgres"))
    zac_idx = next(i for i, line in enumerate(lines) if line.startswith("# zac"))
    assert openzaak_idx < kc_idx < zac_idx

    assert "#   2. keycloak-operator - postgres 16.0 -> 16.15." in new_text
    assert "#   3. zac 5.0.2 -> 5.1.0." in new_text
    assert "# Three changes:" in new_text
    assert "#   1. openzaak 1.27.4 -> 1.29.3." in new_text
    assert "- name: openzaak/open-zaak" in new_text
    assert "- name: infonl/zaakafhandelcomponent" in new_text


def test_add_missing_images_manifest_entries_ignores_wrapped_line_that_looks_like_an_item(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """A continuation line starting with a version ("1.19.1-static, ...")
    is not a numbered item; a loose "\\d+\\." regex split item prose this
    way, CHANGES_ITEM_RE (whitespace after the period) does not."""
    text = (
        "# One change:\n"
        "#   1. openzaak 1.27.4 -> 1.29.3. Also touches related versions:\n"
        "#      1.19.1-static and 2.3.4-slim, both unrelated to this number.\n"
        "\n"
        "# openzaak — 1.27.4 -> 1.29.3\n"
        "- name: openzaak/open-zaak\n"
        "  url: openzaak/open-zaak\n"
        '  version: "1.29.3"\n'
        '  digest: "sha256:aaaa"\n'
        "\n"
        "# zac — 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:cccc"\n'
        "\n"
        "# keycloak-operator - postgres — 16 -> 16.15\n"
        "- name: postgres\n"
        "  url: postgres\n"
        '  version: "16.15"\n'
        '  digest: "sha256:bbbb"\n'
    )

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        text,
        cdb.MissingEntriesContext(
            ordered_images_manifest_chart_dir,
            _ordered_deps(),
            _ordered_target_values(),
            _ordered_baseline_values(),
        ),
    )

    assert added == []
    assert skipped == []
    assert set(backfilled) == {"zac", "keycloak-operator - postgres"}
    # Item 1's two-line prose stays intact.
    assert (
        "#   1. openzaak 1.27.4 -> 1.29.3. Also touches related versions:\n"
        "#      1.19.1-static and 2.3.4-slim, both unrelated to this number.\n"
        "#   2."
    ) in new_text


def test_add_missing_images_manifest_entries_valid_yaml_after_middle_insertion(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """The inserted block is blank-line separated and the result is valid YAML."""
    text = (
        "# openzaak — 1.27.4 -> 1.29.3\n"
        "- name: openzaak/open-zaak\n"
        "  url: openzaak/open-zaak\n"
        '  version: "1.29.3"\n'
        '  digest: "sha256:aaaa"\n'
        "\n"
        "# zac — 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:cccc"\n'
    )

    new_text, added, skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text,
        cdb.MissingEntriesContext(
            ordered_images_manifest_chart_dir,
            _ordered_deps(),
            _ordered_target_values(),
            _ordered_baseline_values(),
        ),
    )

    assert skipped == []
    assert added == ["keycloak-operator - postgres"]
    entries = yaml.safe_load(new_text)
    assert [e["name"] for e in entries] == ["openzaak/open-zaak", "library/postgres", "infonl/zaakafhandelcomponent"]


def test_add_missing_images_manifest_entries_no_header_still_orders_body(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """Without a "# Changes:" header the body is still ordered."""
    text = (
        "# openzaak — 1.27.4 -> 1.29.3\n"
        "- name: openzaak/open-zaak\n"
        "  url: openzaak/open-zaak\n"
        '  version: "1.29.3"\n'
        '  digest: "sha256:aaaa"\n'
        "\n"
        "# zac — 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:cccc"\n'
    )

    new_text, added, skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text,
        cdb.MissingEntriesContext(
            ordered_images_manifest_chart_dir,
            _ordered_deps(),
            _ordered_target_values(),
            _ordered_baseline_values(),
        ),
    )

    assert skipped == []
    assert added == ["keycloak-operator - postgres"]
    lines = new_text.splitlines()
    openzaak_idx = next(i for i, line in enumerate(lines) if line.startswith("# openzaak"))
    kc_idx = next(i for i, line in enumerate(lines) if line.startswith("#   sidecar: keycloak-operator - postgres"))
    zac_idx = next(i for i, line in enumerate(lines) if line.startswith("# zac"))
    assert openzaak_idx < kc_idx < zac_idx


def test_add_missing_images_manifest_entries_creates_missing_header_from_scratch(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """Regression: with a recognizable intro block but no "# Changes:" header,
    the header is created after the intro so new entries get list items."""
    text = (
        "# Baseline: podiumd 4.8.5. Re-verify before release.\n"
        "#\n"
        "# Images new or changed in podiumd 4.9.0 vs 4.8.5.\n"
        "#\n"
        "# See docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md for the operator upgrade notes.\n"
        "#\n"
        "# openzaak — 1.27.4 -> 1.29.3\n"
        "- name: openzaak/open-zaak\n"
        "  url: openzaak/open-zaak\n"
        '  version: "1.29.3"\n'
        '  digest: "sha256:aaaa"\n'
    )

    new_text, added, skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text,
        cdb.MissingEntriesContext(
            ordered_images_manifest_chart_dir,
            _ordered_deps(),
            _ordered_target_values(),
            _ordered_baseline_values(),
        ),
    )

    assert skipped == []
    assert set(added) == {"keycloak-operator - postgres", "zac"}
    assert "# Changes:\n" in new_text
    header_idx = new_text.index("# Changes:\n")
    intro_idx = new_text.index("# Images new or changed")
    assert intro_idx < header_idx  # created right after the intro block, not just anywhere
    changes_block = new_text[header_idx:]
    for name in ("openzaak", "keycloak-operator - postgres", "zac"):
        assert f". {name} " in changes_block, f"{name!r} has no '# Changes:' list item"


def test_add_missing_images_manifest_entries_empty_bare_header_gets_first_item(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """A fresh stub's bare "# Changes:" header with no items gets numbered
    items for new entries."""
    text = (
        "# Baseline: podiumd 4.8.5. Re-verify before release.\n"
        "#\n"
        "# Images new or changed in podiumd 4.9.0 vs 4.8.5.\n"
        "#\n"
        "# Changes:\n"
        "#\n"
        "# See docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md for the operator upgrade notes.\n"
        "#\n"
        "# Digests are the OCI image index (multi-arch manifest) digest as returned in\n"
        "# the Docker-Content-Digest response header from the source registry.\n\n"
        "[]\n"
    )

    new_text, added, skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text,
        cdb.MissingEntriesContext(
            ordered_images_manifest_chart_dir,
            _ordered_deps(),
            _ordered_target_values(),
            _ordered_baseline_values(),
        ),
    )

    assert skipped == []
    assert set(added) == {"keycloak-operator - postgres", "openzaak", "zac"}
    header_idx = new_text.index("# Changes:\n")
    first_item_idx = new_text.index("#   1. ")
    assert header_idx < first_item_idx < header_idx + len("# Changes:\n") + 40
    assert "# See docs/_UPGRADE_PATHS" in new_text  # rest of the header preserved


def test_add_missing_images_manifest_entries_stub_placeholder_not_left_alongside_first_entry(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """Regression: the stub's literal "[]" must be removed on first insert;
    "[]" followed by "- name:" is invalid YAML."""
    text = "# Baseline: podiumd 4.8.5. Re-verify before release.\n#\n# Changes:\n#\n\n[]\n"

    new_text, added, skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text,
        cdb.MissingEntriesContext(
            ordered_images_manifest_chart_dir,
            _ordered_deps(),
            _ordered_target_values(),
            _ordered_baseline_values(),
        ),
    )

    assert skipped == []
    assert set(added) == {"keycloak-operator - postgres", "openzaak", "zac"}
    assert "[]" not in new_text
    yaml.safe_load(new_text)  # must not raise


def test_add_missing_images_manifest_entries_second_run_is_a_noop_not_a_duplicate(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """Regression: invalid YAML from a surviving "[]" made a second run see
    no entries and re-add them all. Runs must be idempotent."""
    text = "# Baseline: podiumd 4.8.5. Re-verify before release.\n#\n# Changes:\n#\n\n[]\n"

    first_text, first_added, _skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text,
        cdb.MissingEntriesContext(
            ordered_images_manifest_chart_dir,
            _ordered_deps(),
            _ordered_target_values(),
            _ordered_baseline_values(),
        ),
    )
    assert first_added != []

    second_text, second_added, _second_skipped, second_backfilled = cdb.add_missing_images_manifest_entries(
        first_text,
        cdb.MissingEntriesContext(
            ordered_images_manifest_chart_dir,
            _ordered_deps(),
            _ordered_target_values(),
            _ordered_baseline_values(),
        ),
    )

    assert second_added == []
    assert second_backfilled == []
    assert second_text == first_text
    assert second_text.count("- name: library/postgres") == 1
    assert second_text.count("- name: openzaak/open-zaak") == 1


def test_add_missing_images_manifest_entries_backfills_header_item_for_existing_entry(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """An existing entry without a "# Changes:" item gets one backfilled,
    since it's no longer "missing" and would otherwise never be added."""
    text = (
        "# Two changes:\n"
        "#   1. openzaak 1.27.4 -> 1.29.3.\n"
        "#   2. zac 5.0.2 -> 5.1.0.\n"
        "\n"
        "# openzaak — 1.27.4 -> 1.29.3\n"
        "- name: openzaak/open-zaak\n"
        "  url: openzaak/open-zaak\n"
        '  version: "1.29.3"\n'
        '  digest: "sha256:aaaa"\n'
        "\n"
        "# keycloak-operator - postgres — 16 -> 16.15\n"
        "- name: postgres\n"
        "  url: postgres\n"
        '  version: "16.15"\n'
        '  digest: "sha256:bbbb"\n'
        "\n"
        "# zac — 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:cccc"\n'
    )

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        text,
        cdb.MissingEntriesContext(
            ordered_images_manifest_chart_dir,
            _ordered_deps(),
            _ordered_target_values(),
            _ordered_baseline_values(),
        ),
    )

    assert added == []
    assert skipped == []
    assert backfilled == ["keycloak-operator - postgres"]
    assert "#   2. keycloak-operator - postgres 16 -> 16.15." in new_text
    assert "#   3. zac 5.0.2 -> 5.1.0." in new_text
    assert "# Three changes:" in new_text
    assert new_text.count("- name: postgres") == 1


@pytest.fixture
def zgw_office_addin_chart_dir(tmp_path: Path):
    """zgw-office-addin frontend + backend: a multi-image lockstep component
    sharing one display name, each with its own "repository:" override."""
    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [{"name": "zgw-office-addin", "version": "0.0.89", "repository": "@infonl"}],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "zgw-office-addin": {
                    "frontend": {
                        "image": {"repository": "infonl/zgw-office-addin-frontend", "tag": "0.11.0@sha256:aaaa"}
                    },
                    "backend": {
                        "image": {"repository": "infonl/zgw-office-addin-backend", "tag": "0.11.0@sha256:bbbb"}
                    },
                },
            }
        ),
    )
    return tmp_path


def test_add_missing_images_manifest_entries_lockstep_component_gets_one_header_item_not_two(
    cdb: ModuleType, zgw_office_addin_chart_dir
):
    """A lockstep component's two missing paths share one display name:
    both get entry blocks but only one header item."""
    text = "# Changes:\n"
    deps = [{"name": "zgw-office-addin", "version": "0.0.89"}]
    target_values = {
        "zgw-office-addin": {
            "frontend": {"image": {"repository": "infonl/zgw-office-addin-frontend", "tag": "0.11.0@sha256:aaaa"}},
            "backend": {"image": {"repository": "infonl/zgw-office-addin-backend", "tag": "0.11.0@sha256:bbbb"}},
        }
    }
    baseline_values = {
        "zgw-office-addin": {
            "frontend": {"image": {"repository": "infonl/zgw-office-addin-frontend", "tag": "v0.9.313@sha256:cccc"}},
            "backend": {"image": {"repository": "infonl/zgw-office-addin-backend", "tag": "v0.9.313@sha256:dddd"}},
        }
    }

    new_text, added, skipped, _backfilled = cdb.add_missing_images_manifest_entries(
        text,
        cdb.MissingEntriesContext(
            zgw_office_addin_chart_dir,
            deps,
            target_values,
            baseline_values,
        ),
    )

    assert skipped == []
    assert added == ["zgw-office-addin", "zgw-office-addin"]
    assert new_text.count("zgw-office-addin v0.9.313 -> 0.11.0.") == 1
    assert new_text.count("- name: infonl/zgw-office-addin-frontend") == 1
    assert new_text.count("- name: infonl/zgw-office-addin-backend") == 1


def test_add_missing_images_manifest_entries_does_not_backfill_already_covered_entry(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """Only an item naming this exact entry covers it; a dependency-level
    mention ("keycloak-operator chart unchanged") does not."""
    text = (
        "# Three changes:\n"
        "#   1. openzaak 1.27.4 -> 1.29.3.\n"
        "#   2. Keycloak app image 26.6.4 -> 26.7.2 (keycloak-operator chart unchanged).\n"
        "#   3. zac 5.0.2 -> 5.1.0.\n"
        "\n"
        "# openzaak — 1.27.4 -> 1.29.3\n"
        "- name: openzaak/open-zaak\n"
        "  url: openzaak/open-zaak\n"
        '  version: "1.29.3"\n'
        '  digest: "sha256:aaaa"\n'
        "\n"
        "# keycloak-operator - postgres — 16 -> 16.15\n"
        "- name: postgres\n"
        "  url: postgres\n"
        '  version: "16.15"\n'
        '  digest: "sha256:bbbb"\n'
        "\n"
        "# zac — 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:cccc"\n'
    )

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        text,
        cdb.MissingEntriesContext(
            ordered_images_manifest_chart_dir,
            _ordered_deps(),
            _ordered_target_values(),
            _ordered_baseline_values(),
        ),
    )

    assert added == []
    assert skipped == []
    # The dependency-level mention doesn't cover the postgres sidecar; its
    # item sorts right after keycloak-operator's (sidecar tie-break).
    assert backfilled == ["keycloak-operator - postgres"]
    assert "#   3. keycloak-operator - postgres 16 -> 16.15." in new_text
    assert "#   4. zac 5.0.2 -> 5.1.0." in new_text


def test_add_missing_images_manifest_entries_backfill_is_noop_when_already_covered(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """An entry already named in a header item: nothing added or renumbered."""
    text = (
        "# Three changes:\n"
        "#   1. openzaak 1.27.4 -> 1.29.3.\n"
        "#   2. keycloak-operator - postgres 16 -> 16.15.\n"
        "#   3. zac 5.0.2 -> 5.1.0.\n"
        "\n"
        "# openzaak — 1.27.4 -> 1.29.3\n"
        "- name: openzaak/open-zaak\n"
        "  url: openzaak/open-zaak\n"
        '  version: "1.29.3"\n'
        '  digest: "sha256:aaaa"\n'
        "\n"
        "# keycloak-operator - postgres — 16 -> 16.15\n"
        "- name: postgres\n"
        "  url: postgres\n"
        '  version: "16.15"\n'
        '  digest: "sha256:bbbb"\n'
        "\n"
        "# zac — 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:cccc"\n'
    )

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        text,
        cdb.MissingEntriesContext(
            ordered_images_manifest_chart_dir,
            _ordered_deps(),
            _ordered_target_values(),
            _ordered_baseline_values(),
        ),
    )

    assert added == []
    assert skipped == []
    assert backfilled == []
    assert new_text == text


def test_add_missing_images_manifest_entries_backfill_coverage_check_is_case_insensitive(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """Header matching is case-insensitive (real headers capitalize names)
    and whole-word, so "ita" never matches inside another word."""
    text = (
        "# Two changes:\n"
        "#   1. openzaak 1.27.4 -> 1.29.3.\n"
        "#   2. ZAC (Zaakafhandelcomponent) 5.0.2 -> 5.1.0 (some digital detail).\n"
        "\n"
        "# openzaak — 1.27.4 -> 1.29.3\n"
        "- name: openzaak/open-zaak\n"
        "  url: openzaak/open-zaak\n"
        '  version: "1.29.3"\n'
        '  digest: "sha256:aaaa"\n'
        "\n"
        "# zac — 5.0.2 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:cccc"\n'
        "\n"
        "# keycloak-operator - postgres — 16 -> 16.15\n"
        "- name: postgres\n"
        "  url: postgres\n"
        '  version: "16.15"\n'
        '  digest: "sha256:bbbb"\n'
    )

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        text,
        cdb.MissingEntriesContext(
            ordered_images_manifest_chart_dir,
            _ordered_deps(),
            _ordered_target_values(),
            _ordered_baseline_values(),
        ),
    )

    # "zac" is covered by item 2; only the postgres sidecar needs an item.
    assert added == []
    assert skipped == []
    assert backfilled == ["keycloak-operator - postgres"]
    assert new_text.count("ZAC (Zaakafhandelcomponent)") == 1  # item 2 untouched, never duplicated


def test_add_missing_images_manifest_entries_skips_dotted_fallback_name_entirely(cdb: ModuleType, tmp_path: Path):
    """An entry named by the raw dotted-path fallback (no dependency or
    sidecar name) is never backfilled or reported: not a phrase for a
    curated header list."""
    write(
        tmp_path / "Chart.yaml",
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "openzaak", "version": "1.14.2", "repository": "@openzaak"},
                ],
            }
        ),
    )
    write(
        tmp_path / "values.yaml",
        yaml.safe_dump(
            {
                "openzaak": {"image": {"repository": "openzaak/open-zaak", "tag": "1.29.3@sha256:aaaa"}},
                "keycloak": {"image": {"repository": "keycloak/keycloak", "tag": "26.7.2@sha256:bbbb"}},
            }
        ),
    )
    deps = [{"name": "openzaak", "version": "1.14.2"}]
    target_values = {
        "openzaak": {"image": {"repository": "openzaak/open-zaak", "tag": "1.29.3@sha256:aaaa"}},
        "keycloak": {"image": {"repository": "keycloak/keycloak", "tag": "26.7.2@sha256:bbbb"}},
    }
    baseline_values = {
        "openzaak": {"image": {"repository": "openzaak/open-zaak", "tag": "1.27.4@sha256:aaaa"}},
        "keycloak": {"image": {"repository": "keycloak/keycloak", "tag": "26.6.4@sha256:eeee"}},
    }
    text = (
        "# One change:\n"
        "#   1. openzaak 1.27.4 -> 1.29.3.\n"
        "\n"
        "# openzaak — 1.27.4 -> 1.29.3\n"
        "- name: openzaak/open-zaak\n"
        "  url: openzaak/open-zaak\n"
        '  version: "1.29.3"\n'
        '  digest: "sha256:aaaa"\n'
        "\n"
        "# keycloak.image — 26.6.4 -> 26.7.2\n"
        "- name: keycloak/keycloak\n"
        "  url: keycloak/keycloak\n"
        '  version: "26.7.2"\n'
        '  digest: "sha256:bbbb"\n'
    )

    new_text, added, skipped, backfilled = cdb.add_missing_images_manifest_entries(
        text,
        cdb.MissingEntriesContext(
            tmp_path,
            deps,
            target_values,
            baseline_values,
        ),
    )

    assert added == []
    assert skipped == []
    assert backfilled == []
    assert new_text == text
