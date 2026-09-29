"""resolve_entry_version, fix_images_manifest_entries — pure logic, no git repo needed."""

from pathlib import Path
from types import ModuleType

# --- resolve_entry_version ---
# (replace_version_spec is tested in tests/lib/test_upgradedoc.py.)


def test_resolve_entry_version_finds_matching_path(cdb: ModuleType):
    paths = {("zac",): "5.1.0@sha256:aaaa", ("zgw-office-addin", "frontend"): "v0.9.352@sha256:bbbb"}
    assert cdb.resolve_entry_version({"name": "zac"}, paths) == "5.1.0"
    assert cdb.resolve_entry_version({"name": "zgw-office-addin-frontend"}, paths) == "v0.9.352"


def test_resolve_entry_version_none_when_unresolvable(cdb: ModuleType):
    assert cdb.resolve_entry_version({"name": "totally-unknown"}, {}) is None


def test_resolve_entry_version_uses_repo_map_for_strip_registry_names(cdb: ModuleType):
    """ "infonl/zaakafhandelcomponent" doesn't word-match the "zac" key;
    repo_map resolves it."""
    paths = {("zac",): "5.4.4@sha256:aaaa"}
    repo_map = {"infonl/zaakafhandelcomponent": ("zac",)}
    assert cdb.resolve_entry_version({"name": "infonl/zaakafhandelcomponent"}, paths) is None
    assert cdb.resolve_entry_version({"name": "infonl/zaakafhandelcomponent"}, paths, repo_map) == "5.4.4"


# --- fix_images_manifest_entries ---


def test_fix_images_manifest_entries_corrects_stale_source(cdb: ModuleType):
    text = (
        "# ZAC — 5.0.1 -> 5.1.0\n"
        "- name: zac\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n'
    )
    target_values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    baseline_values = {"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}

    new_text, changed, unresolved = cdb.fix_images_manifest_entries(
        text, cdb.ManifestEntriesContext(None, [], target_values, baseline_values)
    )
    assert unresolved == []
    assert changed == [("zac", "5.0.2", "5.1.0")]
    assert "# ZAC — 5.0.2 -> 5.1.0" in new_text
    assert "5.0.1" not in new_text


def test_fix_images_manifest_entries_leaves_correct_entry_untouched(cdb: ModuleType):
    text = '# ZAC — 5.0.2 -> 5.1.0\n- name: zac\n  version: "5.1.0"\n'
    target_values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    baseline_values = {"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}

    new_text, changed, _unresolved = cdb.fix_images_manifest_entries(
        text, cdb.ManifestEntriesContext(None, [], target_values, baseline_values)
    )
    assert changed == []
    assert new_text == text


def test_fix_images_manifest_entries_reports_missing_comment(cdb: ModuleType):
    text = '- name: zgw-office-addin-backend\n  version: "v0.9.352"\n'
    target_values = {"zgw-office-addin": {"backend": {"image": {"tag": "v0.9.352@sha256:aaaa"}}}}
    new_text, changed, unresolved = cdb.fix_images_manifest_entries(
        text, cdb.ManifestEntriesContext(None, [], target_values, {})
    )
    assert changed == []
    assert unresolved == ["zgw-office-addin-backend"]
    assert new_text == text


def test_fix_images_manifest_entries_reports_unresolvable_baseline(cdb: ModuleType):
    text = '# ZAC — 5.0.1 -> 5.1.0\n- name: zac\n  version: "5.1.0"\n'
    target_values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    new_text, changed, unresolved = cdb.fix_images_manifest_entries(
        text, cdb.ManifestEntriesContext(None, [], target_values, {})
    )
    assert changed == []
    assert unresolved == ["zac"]
    assert new_text == text


def test_fix_images_manifest_entries_resolves_strip_registry_name_via_repo_map(cdb: ModuleType):
    """The manifest name doesn't word-match the "zac" key; without repo_map
    the entry would be unresolved."""
    text = (
        "# ZAC — 5.0.1 -> 5.1.0\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.1.0"\n'
        '  digest: "sha256:aaaa"\n'
    )
    target_values = {"zac": {"image": {"tag": "5.1.0@sha256:aaaa"}}}
    baseline_values = {"zac": {"image": {"tag": "5.0.2@sha256:bbbb"}}}
    repo_map = {"infonl/zaakafhandelcomponent": ("zac", "image")}

    new_text, changed, unresolved = cdb.fix_images_manifest_entries(
        text, cdb.ManifestEntriesContext(None, [], target_values, baseline_values, repo_map)
    )
    assert unresolved == []
    assert changed == [("infonl/zaakafhandelcomponent", "5.0.2", "5.1.0")]
    assert "# ZAC — 5.0.2 -> 5.1.0" in new_text

    # Without repo_map the same entry is unresolved.
    _new_text2, changed2, unresolved2 = cdb.fix_images_manifest_entries(
        text, cdb.ManifestEntriesContext(None, [], target_values, baseline_values)
    )
    assert changed2 == []
    assert unresolved2 == ["infonl/zaakafhandelcomponent"]


def test_fix_images_manifest_entries_fixes_shared_group_comment_via_either_entry(cdb: ModuleType):
    """zgw-office-addin backend (no comment of its own) is fixed via the
    comment shared with frontend, not reported unresolved."""
    text = (
        "# ZGW Office Add-in — v0.9.300 -> v0.9.352\n"
        "- name: zgw-office-addin-frontend\n"
        '  version: "v0.9.352"\n'
        "\n"
        "- name: zgw-office-addin-backend\n"
        '  version: "v0.9.352"\n'
    )
    target_values = {
        "zgw-office-addin": {
            "frontend": {"image": {"tag": "v0.9.352@sha256:aaaa"}},
            "backend": {"image": {"tag": "v0.9.352@sha256:bbbb"}},
        }
    }
    baseline_values = {
        "zgw-office-addin": {
            "frontend": {"image": {"tag": "v0.9.313@sha256:cccc"}},
            "backend": {"image": {"tag": "v0.9.313@sha256:dddd"}},
        }
    }

    new_text, changed, unresolved = cdb.fix_images_manifest_entries(
        text, cdb.ManifestEntriesContext(None, [], target_values, baseline_values)
    )
    assert unresolved == []
    assert changed == [("zgw-office-addin-frontend", "v0.9.313", "v0.9.352")]
    assert "# ZGW Office Add-in — v0.9.313 -> v0.9.352" in new_text
    assert "v0.9.300" not in new_text


def test_fix_images_manifest_entries_corrects_stale_arrow_to_new(cdb: ModuleType):
    """Regression: a path absent from a resolved baseline must become
    "(new)" rather than stay unresolved, so a stale existing comment
    (e.g. "0.158.0 -> 0.158.0") gets corrected. An unresolvable baseline
    still reports unresolved."""
    text = (
        "#   sidecar: zac - opentelemetry-collector-contrib 0.158.0 -> 0.158.0\n"
        "- name: otel/opentelemetry-collector-contrib\n"
        "  url: docker.io/otel/opentelemetry-collector-contrib\n"
        '  version: "0.158.0"\n'
        '  digest: "sha256:aaaa"\n'
    )
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    target_values = {
        "zac": {
            "opentelemetry-collector": {
                "image": {"repository": "otel/opentelemetry-collector-contrib", "tag": "0.158.0@sha256:aaaa"}
            }
        }
    }
    # Resolved baseline: zac existed, this sidecar is new.
    baseline_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.2@sha256:eeee"}}
    }

    repo_map = {"otel/opentelemetry-collector-contrib": ("zac", "opentelemetry-collector", "image")}
    new_text, changed, unresolved = cdb.fix_images_manifest_entries(
        text, cdb.ManifestEntriesContext(None, deps, target_values, baseline_values, repo_map)
    )
    assert unresolved == []
    assert changed == [("otel/opentelemetry-collector-contrib", None, "0.158.0")]
    assert "opentelemetry-collector-contrib 0.158.0 (new)" in new_text
    assert "0.158.0 -> 0.158.0" not in new_text


def test_fix_images_manifest_entries_finds_historical_baseline_for_new_path(cdb: ModuleType, tmp_path: Path):
    """A path absent from the baseline but present in an earlier
    images-<version>.yaml gets a real "<old> -> <new>" transition."""
    images_dir = tmp_path / "docs" / "images"
    images_dir.mkdir(parents=True)
    (images_dir / "images-4.8.0.yaml").write_text(
        "- name: brp-api/personen-mock\n"
        "  url: ghcr.io/brp-api/personen-mock\n"
        '  version: "2.6.0"\n'
        '  digest: "sha256:aaaa"\n',
        encoding="utf-8",
    )
    text = (
        "# brppersonenmock 2.6.0 -> 2.7.0\n"
        "- name: brp-api/personen-mock\n"
        "  url: ghcr.io/brp-api/personen-mock\n"
        '  version: "2.7.0"\n'
        '  digest: "sha256:bbbb"\n'
    )
    deps = [{"name": "brp-personen-mock", "alias": "brppersonenmock", "version": "1.2.9"}]
    target_values = {
        "brppersonenmock": {"image": {"repository": "ghcr.io/brp-api/personen-mock", "tag": "2.7.0@sha256:bbbb"}}
    }
    baseline_values = {"unrelated": {"image": {"repository": "example/other", "tag": "1.0.0@sha256:cccc"}}}

    repo_map = {"brp-api/personen-mock": ("brppersonenmock", "image")}
    new_text, changed, unresolved = cdb.fix_images_manifest_entries(
        text,
        cdb.ManifestEntriesContext(
            tmp_path, deps, target_values, baseline_values, repo_map, upgrade_docs_baseline="4.8.5"
        ),
    )
    assert unresolved == []
    assert changed == []  # already correctly reads "2.6.0 -> 2.7.0"
    assert new_text == text


def test_fix_images_manifest_entries_corrects_moved_repository_comment(cdb: ModuleType, tmp_path: Path):
    """podiumd 4.9.1 postgres consolidation: global.images.postgres is new but
    the same repository existed elsewhere at baseline, so a stale "(new)" is
    corrected to the real transition (same fallback as the other writers)."""
    text = (
        "# postgres 16.15-alpine (new)\n"
        "- name: postgres\n"
        "  url: postgres\n"
        '  version: "16.15-alpine"\n'
        '  digest: "sha256:aaaa"\n'
    )
    deps = [{"name": "openbao", "version": "2.0.0"}]
    target_values = {
        "global": {"images": {"postgres": {"repository": "postgres", "tag": "16.15-alpine@sha256:aaaa"}}},
        "openbao": {
            "database": {"schemaJob": {"image": {"repository": "postgres", "tag": "16.15-alpine@sha256:aaaa"}}}
        },
    }
    baseline_values = {
        "openbao": {"database": {"schemaJob": {"image": {"repository": "postgres", "tag": "16-alpine@sha256:bbbb"}}}},
    }
    repo_map = {"postgres": ("global", "images", "postgres")}

    new_text, changed, unresolved = cdb.fix_images_manifest_entries(
        text,
        cdb.ManifestEntriesContext(
            tmp_path, deps, target_values, baseline_values, repo_map, upgrade_docs_baseline="4.8.5"
        ),
    )

    assert unresolved == []
    assert changed == [("postgres", "16-alpine", "16.15-alpine")]
    assert "# postgres 16-alpine -> 16.15-alpine" in new_text
    assert "(new)" not in new_text


def test_fix_images_manifest_entries_correctly_verified_digest_changed_untouched(cdb: ModuleType):
    """A correct "(digest changed)" annotation survives because the digest
    change is actually confirmed via resolved_digest_pin, not just left
    unmatched by the version regex."""
    text = (
        "#   sidecar: keycloak-operator - python 3.14.7-slim (digest changed)\n"
        "- name: python\n"
        "  url: docker.io/library/python\n"
        '  version: "3.14.7-slim"\n'
        '  digest: "sha256:' + "b" * 64 + '"\n'
    )
    deps = [{"name": "keycloak-operator", "version": "1.13.0"}]
    target_values = {
        "keycloak-operator": {
            "jobs": {
                "ensurePodiumdAdminUser": {
                    "initImage": {"repository": "docker.io/library/python", "tag": "3.14.7-slim@sha256:" + "b" * 64}
                }
            }
        }
    }
    baseline_values = {
        "keycloak-operator": {
            "jobs": {
                "ensurePodiumdAdminUser": {
                    "initImage": {"repository": "docker.io/library/python", "tag": "3.14.7-slim@sha256:" + "a" * 64}
                }
            }
        }
    }

    repo_map = {"python": ("keycloak-operator", "jobs", "ensurePodiumdAdminUser", "initImage")}
    new_text, changed, unresolved = cdb.fix_images_manifest_entries(
        text, cdb.ManifestEntriesContext(None, deps, target_values, baseline_values, repo_map)
    )
    assert unresolved == []
    assert changed == []
    assert new_text == text
