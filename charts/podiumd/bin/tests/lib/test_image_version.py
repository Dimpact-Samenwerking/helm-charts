"""lib.image.version tests; registry_tag_exists is monkeypatched."""

from pathlib import Path
from types import ModuleType

import pytest


def write_values(tmp_path: Path, text):
    path = tmp_path / "values.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# --- image_basename ---


def test_image_basename_multi_segment(libimageversion: ModuleType):
    assert libimageversion.image_basename("ghcr.io/platform-autorisatie-beheer-component/pabc-api") == "pabc-api"


def test_image_basename_two_segment(libimageversion: ModuleType):
    assert libimageversion.image_basename("curlimages/curl") == "curl"


def test_image_basename_bare(libimageversion: ModuleType):
    assert libimageversion.image_basename("python") == "python"


def test_image_basename_trailing_slash(libimageversion: ModuleType):
    assert libimageversion.image_basename("curlimages/curl/") == "curl"


# --- find_matches ---


def test_find_matches_single_pin(libimageversion: ModuleType):
    lines = [
        "a:",
        "  image:",
        "    repository: curlimages/curl",
        '    tag: "8.21.0@sha256:' + "a" * 64 + '"',
    ]
    matches = libimageversion.find_matches(lines, "curl")
    assert len(matches) == 1
    assert matches[0]["line"] == 4


def test_find_matches_multiple_locations(libimageversion: ModuleType):
    lines = [
        "a:",
        "  image:",
        "    repository: curlimages/curl",
        '    tag: "8.21.0@sha256:' + "a" * 64 + '"',
        "b:",
        "  sub:",
        "    image:",
        "      repository: curlimages/curl",
        '      tag: "8.21.0@sha256:' + "a" * 64 + '"',
    ]
    matches = libimageversion.find_matches(lines, "curl")
    assert [m["line"] for m in matches] == [4, 9]


def test_find_matches_ignores_different_basename(libimageversion: ModuleType):
    lines = [
        "a:",
        "  image:",
        "    repository: org/repo-a",
        '    tag: "1.0.0@sha256:' + "a" * 64 + '"',
    ]
    assert libimageversion.find_matches(lines, "curl") == []


def test_find_matches_ignores_unresolved_repository(libimageversion: ModuleType):
    """A pin without its own "repository:" has no basename to match on."""
    lines = [
        "openzaak:",
        "  image:",
        '    tag: "1.29.3@sha256:' + "a" * 64 + '"',
    ]
    assert libimageversion.find_matches(lines, "openzaak") == []


# --- resolve_key_scope ---


def test_resolve_key_scope_accepts_alias(libimageversion: ModuleType):
    dep = {"name": "kiss-chart", "alias": "kiss", "version": "3.1.1"}
    assert libimageversion.resolve_key_scope("kiss", [dep]) == "kiss"


def test_resolve_key_scope_accepts_real_name_translates_to_alias(libimageversion: ModuleType):
    """The Chart.yaml name is accepted like the alias, as update-component-version does."""
    dep = {"name": "kiss-chart", "alias": "kiss", "version": "3.1.1"}
    assert libimageversion.resolve_key_scope("kiss-chart", [dep]) == "kiss"


def test_resolve_key_scope_dependency_with_no_alias_untouched(libimageversion: ModuleType):
    dep = {"name": "keycloak-operator", "version": "1.13.0"}
    assert libimageversion.resolve_key_scope("keycloak-operator", [dep]) == "keycloak-operator"


def test_resolve_key_scope_multiple_passes_through_unchanged(libimageversion: ModuleType):
    dep = {"name": "kiss-chart", "alias": "kiss", "version": "3.1.1"}
    assert libimageversion.resolve_key_scope(libimageversion.MULTIPLE_KEY, [dep]) == libimageversion.MULTIPLE_KEY


def test_resolve_key_scope_no_matching_dependency_passes_through_unchanged(libimageversion: ModuleType):
    """Native components and typos pass through; resolve_scoped_matches reports them."""
    dep = {"name": "kiss-chart", "alias": "kiss", "version": "3.1.1"}
    assert libimageversion.resolve_key_scope("frankgateway", [dep]) == "frankgateway"


# --- find_matches_in_scope / resolve_scoped_matches ---


def test_find_matches_in_scope_finds_pins_under_key(libimageversion: ModuleType):
    lines = [
        "a:",
        "  image:",
        "    repository: curlimages/curl",
        '    tag: "8.21.0@sha256:' + "a" * 64 + '"',
        "b:",
        "  image:",
        "    repository: curlimages/curl",
        '    tag: "8.21.0@sha256:' + "a" * 64 + '"',
    ]
    matches = libimageversion.find_matches_in_scope(lines, "a", "curl")
    assert [m["line"] for m in matches] == [4]


def test_resolve_scoped_matches_multiple_key_translates_to_global_scope(libimageversion: ModuleType):
    """MULTIPLE_KEY (release-table.csv's shared base image) resolves to global.images."""
    lines = [
        "global:",
        "  images:",
        "    curl:",
        "      repository: curlimages/curl",
        '      tag: "8.21.0@sha256:' + "a" * 64 + '"',
    ]
    matches = libimageversion.resolve_scoped_matches(lines, libimageversion.MULTIPLE_KEY, "curl")
    assert [m["line"] for m in matches] == [5]


def test_resolve_scoped_matches_ignores_case_of_key_and_basename(libimageversion: ModuleType) -> None:
    lines = [
        "global:",
        "  images:",
        "    curl:",
        "      repository: curlimages/curl",
        '      tag: "8.21.0@sha256:' + "a" * 64 + '"',
        "zac:",
        "  image:",
        "    repository: ghcr.io/infonl/zaakafhandelcomponent",
        '    tag: "5.0.2@sha256:' + "b" * 64 + '"',
    ]
    assert [m["line"] for m in libimageversion.resolve_scoped_matches(lines, "multiple", "CURL")] == [5]
    assert [m["line"] for m in libimageversion.resolve_scoped_matches(lines, "ZAC", "ZaakAfhandelComponent")] == [9]


def test_resolve_key_scope_ignores_case(libimageversion: ModuleType) -> None:
    dep = {"name": "kiss-chart", "alias": "kiss", "version": "3.1.1"}
    assert libimageversion.resolve_key_scope("KISS-Chart", [dep]) == "kiss"
    assert libimageversion.resolve_key_scope("multiple", [dep]) == libimageversion.MULTIPLE_KEY


def test_resolve_scoped_matches_no_match_under_key_raises(libimageversion: ModuleType):
    lines = [
        "a:",
        "  image:",
        "    repository: curlimages/curl",
        '    tag: "8.21.0@sha256:' + "a" * 64 + '"',
    ]
    with pytest.raises(SystemExit, match="no image pin with basename 'curl' found under 'b'"):
        libimageversion.resolve_scoped_matches(lines, "b", "curl")


def test_resolve_scoped_matches_ambiguous_repository_under_key_raises(libimageversion: ModuleType):
    """Two repositories with the same basename under one key is an error, never a guess."""
    lines = [
        "a:",
        "  image:",
        "    repository: org-one/curl",
        '    tag: "1.0.0@sha256:' + "a" * 64 + '"',
        "  sidecar:",
        "    image:",
        "      repository: org-two/curl",
        '      tag: "1.0.0@sha256:' + "a" * 64 + '"',
    ]
    with pytest.raises(SystemExit, match="'curl' under 'a' is not unique"):
        libimageversion.resolve_scoped_matches(lines, "a", "curl")


# --- check_basename_version ---


def test_check_basename_version_reports_found(libimageversion: ModuleType, monkeypatch: pytest.MonkeyPatch):
    lines = [
        "pabc:",
        "  image:",
        "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api",
        '    tag: "1.1.1@sha256:' + "a" * 64 + '"',
    ]
    monkeypatch.setattr(libimageversion, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))

    results = libimageversion.check_basename_version(lines, "pabc", "pabc-api", "1.1.2")

    assert results == [
        {
            "repository": "ghcr.io/platform-autorisatie-beheer-component/pabc-api",
            "host": "ghcr.io",
            "repo_path": "platform-autorisatie-beheer-component/pabc-api",
            "exists": True,
            "digest": "sha256:" + "b" * 64,
        }
    ]


def test_check_basename_version_reports_missing(libimageversion: ModuleType, monkeypatch: pytest.MonkeyPatch):
    lines = [
        "pabc:",
        "  image:",
        "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api",
        '    tag: "1.1.1@sha256:' + "a" * 64 + '"',
    ]
    monkeypatch.setattr(libimageversion, "registry_tag_exists", lambda host, repo, tag: (False, None))

    results = libimageversion.check_basename_version(lines, "pabc", "pabc-api", "9.9.9")

    assert results[0]["exists"] is False
    assert results[0]["digest"] is None


def test_check_basename_version_dedupes_shared_repository(libimageversion: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """The same repository pinned twice needs only one registry lookup."""
    lines = [
        "global:",
        "  a:",
        "    image:",
        "      repository: curlimages/curl",
        '      tag: "8.21.0@sha256:' + "a" * 64 + '"',
        "  b:",
        "    sub:",
        "      image:",
        "        repository: curlimages/curl",
        '        tag: "8.21.0@sha256:' + "a" * 64 + '"',
    ]
    calls = []

    def fake_registry_tag_exists(host, repo, tag):
        calls.append((host, repo, tag))
        return True, "sha256:" + "b" * 64

    monkeypatch.setattr(libimageversion, "registry_tag_exists", fake_registry_tag_exists)

    results = libimageversion.check_basename_version(lines, libimageversion.MULTIPLE_KEY, "curl", "8.22.0")

    assert len(results) == 1
    assert len(calls) == 1


def test_check_basename_version_no_match_raises(libimageversion: ModuleType):
    with pytest.raises(SystemExit, match="no image pin with basename 'curl' found under 'a'"):
        libimageversion.check_basename_version([], "a", "curl", "8.22.0")


# --- update_image_version ---


def test_update_image_version_single_match(
    libimageversion: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    values_path = write_values(
        tmp_path,
        (
            "pabc:\n"
            "  image:\n"
            "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
            f'    tag: "1.1.1@sha256:{"a" * 64}"\n'
        ),
    )
    monkeypatch.setattr(libimageversion, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    changes = libimageversion.update_image_version(values_path, "pabc", "pabc-api", "1.1.2")
    assert len(changes) == 1
    assert changes[0] == {
        "line": 4,
        "repository": "ghcr.io/platform-autorisatie-beheer-component/pabc-api",
        "old_version": "1.1.1",
        "old_digest": "sha256:" + "a" * 64,
        "new_version": "1.1.2",
        "new_digest": "sha256:" + "b" * 64,
    }
    assert f'tag: "1.1.2@sha256:{"b" * 64}"' in values_path.read_text(encoding="utf-8")


def test_update_image_version_updates_all_shared_occurrences(
    libimageversion: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Both pins of a shared repository update, with one registry lookup."""
    values_path = write_values(
        tmp_path,
        (
            "global:\n"
            "  images:\n"
            "    curl: &curlImage\n"
            "      repository: curlimages/curl\n"
            f'      tag: "8.21.0@sha256:{"a" * 64}"\n'
            "  kiss:\n"
            "    indexTemplateImage:\n"
            "      repository: curlimages/curl\n"
            f'      tag: "8.21.0@sha256:{"a" * 64}"\n'
        ),
    )
    calls = []

    def fake_registry_tag_exists(host, repo, tag):
        calls.append((host, repo, tag))
        return True, "sha256:" + "c" * 64

    monkeypatch.setattr(libimageversion, "registry_tag_exists", fake_registry_tag_exists)
    changes = libimageversion.update_image_version(values_path, libimageversion.MULTIPLE_KEY, "curl", "8.22.0")
    assert [c["line"] for c in changes] == [5, 9]
    assert len(calls) == 1  # deduped: same repository, one lookup
    text = values_path.read_text(encoding="utf-8")
    assert text.count(f"8.22.0@sha256:{'c' * 64}") == 2


def test_update_image_version_no_match_raises(libimageversion: ModuleType, tmp_path: Path):
    values_path = write_values(
        tmp_path, 'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:' + "a" * 64 + '"\n'
    )
    with pytest.raises(SystemExit, match="no image pin with basename 'curl' found under 'a'"):
        libimageversion.update_image_version(values_path, "a", "curl", "8.22.0")


def test_update_image_version_already_at_target_is_noop(
    libimageversion: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    values_path = write_values(
        tmp_path,
        (
            "pabc:\n"
            "  image:\n"
            "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
            f'    tag: "1.1.2@sha256:{"a" * 64}"\n'
        ),
    )

    def fail_if_called(*a, **kw):
        msg = "registry should not be queried when nothing needs updating"
        raise AssertionError(msg)

    monkeypatch.setattr(libimageversion, "registry_tag_exists", fail_if_called)
    original = values_path.read_text(encoding="utf-8")
    changes = libimageversion.update_image_version(values_path, "pabc", "pabc-api", "1.1.2")
    assert changes == []
    assert values_path.read_text(encoding="utf-8") == original


def test_update_image_version_only_updates_stale_occurrence(
    libimageversion: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Only the occurrence not yet at the target version is rewritten."""
    values_path = write_values(
        tmp_path,
        (
            "global:\n"
            "  a:\n"
            "    image:\n"
            "      repository: curlimages/curl\n"
            f'      tag: "8.22.0@sha256:{"a" * 64}"\n'
            "  b:\n"
            "    image:\n"
            "      repository: curlimages/curl\n"
            f'      tag: "8.21.0@sha256:{"a" * 64}"\n'
        ),
    )
    monkeypatch.setattr(libimageversion, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:" + "c" * 64))
    changes = libimageversion.update_image_version(values_path, libimageversion.MULTIPLE_KEY, "curl", "8.22.0")
    assert [c["line"] for c in changes] == [9]


def test_update_image_version_raises_when_version_missing_upstream(
    libimageversion: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    values_path = write_values(
        tmp_path,
        (
            "pabc:\n"
            "  image:\n"
            "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
            f'    tag: "1.1.1@sha256:{"a" * 64}"\n'
        ),
    )
    monkeypatch.setattr(libimageversion, "registry_tag_exists", lambda host, repo, tag: (False, None))
    original = values_path.read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="not found upstream"):
        libimageversion.update_image_version(values_path, "pabc", "pabc-api", "9.9.9")
    assert values_path.read_text(encoding="utf-8") == original  # nothing written on failure


def test_update_image_version_ambiguous_repositories_under_key_raises(
    libimageversion: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An ambiguous basename is rejected before any registry lookup or write."""
    values_path = write_values(
        tmp_path,
        (
            "a:\n"
            "  image:\n"
            "    repository: org-one/curl\n"
            f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
            "  sidecar:\n"
            "    image:\n"
            "      repository: org-two/curl\n"
            f'      tag: "1.0.0@sha256:{"a" * 64}"\n'
        ),
    )

    def fail_if_called(*a, **kw):
        msg = "registry should not be queried when the image isn't identified uniquely"
        raise AssertionError(msg)

    monkeypatch.setattr(libimageversion, "registry_tag_exists", fail_if_called)
    original = values_path.read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="'curl' under 'a' is not unique"):
        libimageversion.update_image_version(values_path, "a", "curl", "2.0.0")
    assert values_path.read_text(encoding="utf-8") == original


# --- basenames_under_scope ---


def test_basenames_under_scope_finds_nested_pins(libimageversion: ModuleType, tmp_path: Path):
    values_path = write_values(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{"a" * 64}"
  solr-operator:
    image:
      repository: apache/solr-operator
      tag: "0.9.1@sha256:{"b" * 64}"
""",
    )
    lines = values_path.read_text(encoding="utf-8").splitlines()
    available = libimageversion.basenames_under_scope(lines, "zac")
    assert set(available) == {"zaakafhandelcomponent", "solr-operator"}


def test_basenames_under_scope_ignores_other_components(libimageversion: ModuleType, tmp_path: Path):
    values_path = write_values(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{"a" * 64}"
openzaak:
  image:
    repository: openzaak/open-zaak
    tag: "1.0.0@sha256:{"b" * 64}"
""",
    )
    lines = values_path.read_text(encoding="utf-8").splitlines()
    assert set(libimageversion.basenames_under_scope(lines, "zac")) == {"zaakafhandelcomponent"}


# --- basenames_under_scope_any_tag / find_matches_any_tag ---
# Only for verify-release-table-with-podiumd: old baselines have bare (undigested) tags.


def test_basenames_under_scope_any_tag_finds_bare_tag_pin(libimageversion: ModuleType, tmp_path: Path):
    """A bare-tag pin (as in the 4.8.5 baseline) is found here but not by basenames_under_scope."""
    values_path = write_values(
        tmp_path,
        """\
zaakbrug:
  image:
    repository: wearefrank/zaakbrug
    tag: "1.26.15"
""",
    )
    lines = values_path.read_text(encoding="utf-8").splitlines()
    assert libimageversion.basenames_under_scope(lines, "zaakbrug") == {}
    available = libimageversion.basenames_under_scope_any_tag(lines, "zaakbrug")
    assert set(available) == {"zaakbrug"}
    assert available["zaakbrug"][0]["version"] == "1.26.15"
    assert available["zaakbrug"][0]["digest"] is None


def test_basenames_under_scope_any_tag_still_finds_digest_pinned_pins(libimageversion: ModuleType, tmp_path: Path):
    values_path = write_values(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{"a" * 64}"
""",
    )
    lines = values_path.read_text(encoding="utf-8").splitlines()
    available = libimageversion.basenames_under_scope_any_tag(lines, "zac")
    assert available["zaakafhandelcomponent"][0]["version"] == "5.0.0"
    assert available["zaakafhandelcomponent"][0]["digest"] == "a" * 64


def test_find_matches_any_tag_finds_bare_tag_pin(libimageversion: ModuleType, tmp_path: Path):
    values_path = write_values(
        tmp_path,
        """\
pabc:
  image:
    repository: acrprodmgmt.azurecr.io/platform-autorisatie-beheer-component/pabc-api
    tag: 1.1.0
""",
    )
    lines = values_path.read_text(encoding="utf-8").splitlines()
    assert libimageversion.find_matches(lines, "pabc-api") == []
    matches = libimageversion.find_matches_any_tag(lines, "pabc-api")
    assert [(m["version"], m["digest"]) for m in matches] == [("1.1.0", None)]


# --- repository_for_basename_in_scope ---
# Used by check_images_source to cross-check the baseline's unscoped fallback.


def test_repository_for_basename_in_scope_uses_scoped_hit(libimageversion: ModuleType, tmp_path: Path):
    values_path = write_values(
        tmp_path,
        """\
global:
  images:
    redis:
      repository: redis
      tag: "8.0@sha256:"""
        + "a" * 64
        + '"\n',
    )
    lines = values_path.read_text(encoding="utf-8").splitlines()
    assert libimageversion.repository_for_basename_in_scope(lines, "global", "redis") == "redis"


def test_repository_for_basename_in_scope_falls_back_to_unscoped(libimageversion: ModuleType, tmp_path: Path):
    """With no scoped hit (keycloak-config-cli lives under "keycloak"), a unique unscoped hit is used."""
    values_path = write_values(
        tmp_path,
        """\
keycloak:
  keycloakConfigCli:
    image:
      repository: adorsys/keycloak-config-cli
      tag: "6.5.1-26@sha256:"""
        + "c" * 64
        + '"\n',
    )
    lines = values_path.read_text(encoding="utf-8").splitlines()
    assert (
        libimageversion.repository_for_basename_in_scope(lines, "keycloak-operator", "keycloak-config-cli")
        == "adorsys/keycloak-config-cli"
    )


def test_repository_for_basename_in_scope_none_when_nothing_resolves(libimageversion: ModuleType):
    assert libimageversion.repository_for_basename_in_scope([], "keycloak-operator", "keycloak-config-cli") is None


def test_repository_for_basename_in_scope_none_when_ambiguous(libimageversion: ModuleType, tmp_path: Path):
    """Ambiguous unscoped hits return None rather than a guess."""
    values_path = write_values(
        tmp_path,
        """\
a:
  image:
    repository: some/redis
    tag: "1.0.0@sha256:"""
        + "a" * 64
        + '"\n'
        + """
b:
  image:
    repository: other/redis
    tag: "2.0.0@sha256:"""
        + "b" * 64
        + '"\n',
    )
    lines = values_path.read_text(encoding="utf-8").splitlines()
    assert libimageversion.repository_for_basename_in_scope(lines, "nowhere", "redis") is None


def test_basenames_under_scope_ignores_scope_key_case(libimageversion: ModuleType) -> None:
    """Scope matching ignores case, the same as find_matches_in_scope."""
    lines = ["zac:", "  image:", "    repository: ghcr.io/infonl/zac", '    tag: "1.0@sha256:' + "a" * 64 + '"']
    assert list(libimageversion.basenames_under_scope(lines, "ZAC")) == ["zac"]
    assert list(libimageversion.basenames_under_scope_any_tag(lines, "Zac")) == ["zac"]
