"""add_missing_images_manifest_entries' own ordering/header/backfill scenarios (the
ordered_images_manifest_chart_dir fixture cluster), including 4 backfill-coverage
tests that are physically colocated with the dedupe tests in the original file but
exercise this same fixture cluster, not dedupe logic."""

from pathlib import Path
from types import ModuleType

import pytest
import yaml


def write(path, text):
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def ordered_images_manifest_chart_dir(tmp_path: Path):
    """Three dependencies, values.yaml top-level order openzaak ->
    keycloak-operator -> zac — keycloak-operator's own postgres sidecar
    resolves via an own override, no vendored subchart tgz needed."""
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
    """A missing entry for the MIDDLE component (values.yaml order
    openzaak -> keycloak-operator -> zac) is inserted between the
    existing openzaak and zac blocks — both in the body and in the "#
    Changes:" header's own numbered list — not appended after zac just
    because zac happened to be added to the file first."""
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
    # Both existing entries' own content stays exactly as it was.
    assert "#   1. openzaak 1.27.4 -> 1.29.3." in new_text
    assert "- name: openzaak/open-zaak" in new_text
    assert "- name: infonl/zaakafhandelcomponent" in new_text


def test_add_missing_images_manifest_entries_ignores_wrapped_line_that_looks_like_an_item(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """A wrapped CONTINUATION line that happens to start with a version
    number (e.g. "1.19.1-static, ...") must never be mistaken for a
    genuine "#   N. ..." numbered item — real case this corrupted:
    item 1's own real-world continuation text "ZAC's bundled sidecar
    images also bumped: opa 1.17.1-static ->\n1.19.1-static,
    office_converter ..." got its SECOND line ("1.19.1-static, ...")
    matched as if it were its own item, splitting item 1's own prose in
    two around a newly-inserted item. CHANGES_ITEM_RE (which requires
    whitespace after the period) never makes this mistake; a looser
    "\\d+\\." regex does."""
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
    # Item 1's own two-line prose stays intact and adjacent to whatever
    # item follows it — never torn apart around a newly-inserted item.
    assert (
        "#   1. openzaak 1.27.4 -> 1.29.3. Also touches related versions:\n"
        "#      1.19.1-static and 2.3.4-slim, both unrelated to this number.\n"
        "#   2."
    ) in new_text


def test_add_missing_images_manifest_entries_valid_yaml_after_middle_insertion(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """The inserted block is properly blank-line-separated from its
    neighbors on both sides — the result parses as a valid, 3-entry
    manifest, not malformed or merged-together YAML."""
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
    assert [e["name"] for e in entries] == ["openzaak/open-zaak", "postgres", "infonl/zaakafhandelcomponent"]


def test_add_missing_images_manifest_entries_no_header_still_orders_body(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """No "# Changes:" header at all in this file — the body still gets
    ordered correctly; nothing about header-handling is required for
    body ordering to work."""
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
    """Regression test (real bug, real doc): images-4.9.1.yaml's own
    real intro block ("# Baseline: ...", "# Images new or changed...",
    "# See docs/_UPGRADE_PATHS...") with NO "# Changes:" header at all
    (distinct from test_add_missing_images_manifest_entries_no_header_
    still_orders_body above, whose text has no recognizable intro block
    to anchor a fresh header on either) — every new entry must still get
    both its own body comment AND a matching "# Changes:" list item,
    with the header itself created right after the intro line, not
    silently skipped forever."""
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
    """The real symptom a fresh lib.component_docs.IMAGES_STUB_TEMPLATE
    file has: a bare "# Changes:" header with NO items under it yet
    (not "no header at all" — see the no_header_still_orders_body test
    above, a genuinely different case). Before IMAGES_STUB_TEMPLATE
    included this header line at all, a freshly-created manifest had
    no anchor whatsoever for a numbered item to attach to, so new
    entries were added to the body but silently never got a matching
    "# Changes:" item — exactly the "top comment list stayed '[]'"
    symptom reported live."""
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
    # The bare "# Changes:" header actually got numbered items under it —
    # not left as the literal "[]" placeholder with nothing above it.
    header_idx = new_text.index("# Changes:\n")
    first_item_idx = new_text.index("#   1. ")
    assert header_idx < first_item_idx < header_idx + len("# Changes:\n") + 40
    assert "# See docs/_UPGRADE_PATHS" in new_text  # rest of the header preserved


def test_add_missing_images_manifest_entries_stub_placeholder_not_left_alongside_first_entry(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """Real bug: the fresh stub's own literal bare "[]" (yaml.safe_load's
    empty-list spelling) was left in place while the first real entry got
    inserted right after it — "[]" followed by a "- name: ..." block is
    NOT valid YAML for a single document, so the result couldn't be
    parsed back at all."""
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
    """Real bug downstream of the "[]" placeholder surviving the first
    insert: since the resulting file was invalid YAML, a second run's own
    `yaml.safe_load(text)` raised and silently fell back to `entries =
    []` — treating the (now actually non-empty) manifest as if it still
    had NOTHING in it, and re-adding every single entry a second time
    right alongside the first copies. A clean run must be idempotent."""
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
    assert second_text.count("- name: postgres") == 1
    assert second_text.count("- name: openzaak/open-zaak") == 1


def test_add_missing_images_manifest_entries_backfills_header_item_for_existing_entry(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """A component that already has its own comment+entry block (e.g.
    added by an earlier run of this same function, before header-list
    support existed) but was never given a "# Changes:" header item is
    backfilled one now — real case: keycloak-operator - postgres was
    added to the body in a previous run, but its header item was
    missing, and re-running the (now header-aware) fix script alone
    didn't add it, since the entry itself was no longer "missing"."""
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
    # The body itself is untouched — only the header list gained an item.
    assert new_text.count("- name: postgres") == 1


@pytest.fixture
def zgw_office_addin_chart_dir(tmp_path: Path):
    """zgw-office-addin's own frontend + backend images — one of
    COMPONENT_IMAGE_PATHS' MULTI-image "lockstep" entries (both share
    ONE path_display_name, "zgw-office-addin") — each with its own
    explicit "repository:" override, matching lib.chart.paths_by_
    repository's own "no owning dependency needed" resolution."""
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
    """Real bug: a multi-image lockstep component reports TWO missing_
    paths (frontend + backend), both resolving to the SAME path_display_
    name ("zgw-office-addin") — the per-path loop used to insert a
    header item for EACH one unconditionally, producing two identical
    "#   N. zgw-office-addin v0.9.313 -> 0.11.0." items for what is really
    ONE logical change (same bug class internetaakafhandeling's web+
    poller and eck-stack's elasticsearch+kibana can trigger too). Both
    paths still get their own comment+entry block — only the SECOND
    header item is now skipped, the same whole-word "already mentioned"
    check the backfill pass already uses."""
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
    """An entry already named in some existing header item is left
    alone — a dependency-level mention (e.g. "keycloak-operator chart
    unchanged") is NOT enough; only an item naming this exact entry
    ("keycloak-operator - postgres") counts as covering it."""
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
    # keycloak-operator's own dependency-level mention doesn't cover the
    # postgres SIDECAR specifically — it still needs (and gets) its own
    # item, sorted right after keycloak-operator's own primary-image
    # item (same key_order index, sidecar tie-break puts it second).
    assert backfilled == ["keycloak-operator - postgres"]
    assert "#   3. keycloak-operator - postgres 16 -> 16.15." in new_text
    assert "#   4. zac 5.0.2 -> 5.1.0." in new_text


def test_add_missing_images_manifest_entries_backfill_is_noop_when_already_covered(
    cdb: ModuleType, ordered_images_manifest_chart_dir
):
    """An entry whose exact display name IS already mentioned in an
    existing header item is left alone entirely — nothing added,
    nothing renumbered."""
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
    """A header item written in natural prose case ("ZAC
    (Zaakafhandelcomponent) 5.0.2 -> ...") still covers the entry whose
    own display name is the bare, lowercase values key ("zac") — real
    case this matters for: the actual images-4.9.0.yaml header
    capitalizes every component name in its own prose. Whole-word, not
    a raw substring — "ita" is never mistaken for a match buried inside
    an unrelated word."""
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

    # "zac" is already covered (case-insensitively) by item 2 — only
    # keycloak-operator - postgres genuinely needs a new item. The
    # stray "digital" in item 2's own text never gets mistaken for an
    # "ita"-shaped match either (there's no "ita" entry here at all, but
    # this fixture wouldn't spuriously match anything from it).
    assert added == []
    assert skipped == []
    assert backfilled == ["keycloak-operator - postgres"]
    assert new_text.count("ZAC (Zaakafhandelcomponent)") == 1  # item 2 untouched, never duplicated


def test_add_missing_images_manifest_entries_skips_dotted_fallback_name_entirely(cdb: ModuleType, tmp_path: Path):
    """An entry whose own display name is path_display_name's raw-
    dotted-path fallback (no real Chart.yaml dependency AND no
    canonical sidecar name resolves it — real case: podiumd's own
    "keycloak" top-level block, distinct from the "keycloak-operator"
    dependency) is never backfilled a header item, and never reported
    either — a dotted values.yaml path is not a phrase worth adding to
    a curated header list verbatim."""
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
