"""lib.image_version — image_basename, find_matches, update_image_version.
No network needed: lib.registry.registry_tag_exists is monkeypatched
wherever a live fetch would otherwise happen."""
import pytest


def write_values(tmp_path, text):
    path = tmp_path / "values.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# --- image_basename ---

def test_image_basename_multi_segment(libimageversion):
    assert libimageversion.image_basename("ghcr.io/platform-autorisatie-beheer-component/pabc-api") == "pabc-api"


def test_image_basename_two_segment(libimageversion):
    assert libimageversion.image_basename("curlimages/curl") == "curl"


def test_image_basename_bare(libimageversion):
    assert libimageversion.image_basename("python") == "python"


def test_image_basename_trailing_slash(libimageversion):
    assert libimageversion.image_basename("curlimages/curl/") == "curl"


# --- find_matches ---

def test_find_matches_single_pin(libimageversion):
    lines = [
        "a:",
        "  image:",
        "    repository: curlimages/curl",
        '    tag: "8.21.0@sha256:' + "a" * 64 + '"',
    ]
    matches = libimageversion.find_matches(lines, "curl")
    assert len(matches) == 1
    assert matches[0]["line"] == 4


def test_find_matches_multiple_locations(libimageversion):
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


def test_find_matches_ignores_different_basename(libimageversion):
    lines = [
        "a:",
        "  image:",
        "    repository: org/repo-a",
        '    tag: "1.0.0@sha256:' + "a" * 64 + '"',
    ]
    assert libimageversion.find_matches(lines, "curl") == []


def test_find_matches_ignores_unresolved_repository(libimageversion):
    """A pin relying on a vendored sub-chart's own default (no explicit
    "repository:" of its own in values.yaml) can never be matched by
    basename — there's nothing to derive one from."""
    lines = [
        "openzaak:",
        "  image:",
        '    tag: "1.29.3@sha256:' + "a" * 64 + '"',
    ]
    assert libimageversion.find_matches(lines, "openzaak") == []


# --- update_image_version ---

def test_update_image_version_single_match(libimageversion, tmp_path, monkeypatch):
    values_path = write_values(tmp_path, (
        "pabc:\n"
        "  image:\n"
        "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
        f'    tag: "1.1.1@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(libimageversion, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "b" * 64))
    changes = libimageversion.update_image_version(values_path, "pabc-api", "1.1.2")
    assert len(changes) == 1
    assert changes[0] == {
        "line": 4, "repository": "ghcr.io/platform-autorisatie-beheer-component/pabc-api",
        "old_version": "1.1.1", "old_digest": "sha256:" + "a" * 64,
        "new_version": "1.1.2", "new_digest": "sha256:" + "b" * 64,
    }
    assert f'tag: "1.1.2@sha256:{"b" * 64}"' in values_path.read_text(encoding="utf-8")


def test_update_image_version_updates_all_shared_occurrences(libimageversion, tmp_path, monkeypatch):
    """curlimages/curl pinned at two unrelated places — both must update,
    with only one registry lookup between them."""
    values_path = write_values(tmp_path, (
        "images:\n"
        "  curl: &curlImage\n"
        "    repository: curlimages/curl\n"
        f'    tag: "8.21.0@sha256:{"a" * 64}"\n'
        "kiss:\n"
        "  indexTemplateImage:\n"
        "    repository: curlimages/curl\n"
        f'    tag: "8.21.0@sha256:{"a" * 64}"\n'
    ))
    calls = []

    def fake_registry_tag_exists(host, repo, tag):
        calls.append((host, repo, tag))
        return True, "sha256:" + "c" * 64

    monkeypatch.setattr(libimageversion, "registry_tag_exists", fake_registry_tag_exists)
    changes = libimageversion.update_image_version(values_path, "curl", "8.22.0")
    assert [c["line"] for c in changes] == [4, 8]
    assert len(calls) == 1  # deduped: same repository, one lookup
    text = values_path.read_text(encoding="utf-8")
    assert text.count(f'8.22.0@sha256:{"c" * 64}') == 2


def test_update_image_version_no_match_raises(libimageversion, tmp_path):
    values_path = write_values(tmp_path, "a:\n  image:\n    repository: org/repo\n    tag: \"1.0.0@sha256:" + "a" * 64 + "\"\n")
    with pytest.raises(SystemExit, match="no image pin with basename 'curl'"):
        libimageversion.update_image_version(values_path, "curl", "8.22.0")


def test_update_image_version_already_at_target_is_noop(libimageversion, tmp_path, monkeypatch):
    values_path = write_values(tmp_path, (
        "pabc:\n"
        "  image:\n"
        "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
        f'    tag: "1.1.2@sha256:{"a" * 64}"\n'
    ))

    def fail_if_called(*a, **kw):
        raise AssertionError("registry should not be queried when nothing needs updating")

    monkeypatch.setattr(libimageversion, "registry_tag_exists", fail_if_called)
    original = values_path.read_text(encoding="utf-8")
    changes = libimageversion.update_image_version(values_path, "pabc-api", "1.1.2")
    assert changes == []
    assert values_path.read_text(encoding="utf-8") == original


def test_update_image_version_only_updates_stale_occurrence(libimageversion, tmp_path, monkeypatch):
    """One of two shared occurrences already at the target version — only
    the other actually gets rewritten, but the registry is still queried
    (needed for the one that IS changing)."""
    values_path = write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: curlimages/curl\n"
        f'    tag: "8.22.0@sha256:{"a" * 64}"\n'
        "b:\n"
        "  image:\n"
        "    repository: curlimages/curl\n"
        f'    tag: "8.21.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(libimageversion, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "c" * 64))
    changes = libimageversion.update_image_version(values_path, "curl", "8.22.0")
    assert [c["line"] for c in changes] == [8]


def test_update_image_version_raises_when_version_missing_upstream(libimageversion, tmp_path, monkeypatch):
    values_path = write_values(tmp_path, (
        "pabc:\n"
        "  image:\n"
        "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api\n"
        f'    tag: "1.1.1@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(libimageversion, "registry_tag_exists", lambda host, repo, tag: (False, None))
    original = values_path.read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="not found upstream"):
        libimageversion.update_image_version(values_path, "pabc-api", "9.9.9")
    assert values_path.read_text(encoding="utf-8") == original  # nothing written on failure


def test_update_image_version_atomic_across_multiple_repositories(libimageversion, tmp_path, monkeypatch):
    """Two DIFFERENT repositories sharing a basename (unusual, but
    possible) — if the second one's version doesn't exist upstream,
    nothing is written for either, even though the first one's lookup
    already succeeded."""
    values_path = write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org-one/curl\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
        "b:\n"
        "  image:\n"
        "    repository: org-two/curl\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))

    def fake_registry_tag_exists(host, repo, tag):
        if repo == "org-two/curl":
            return False, None
        return True, "sha256:" + "c" * 64

    monkeypatch.setattr(libimageversion, "registry_tag_exists", fake_registry_tag_exists)
    original = values_path.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        libimageversion.update_image_version(values_path, "curl", "2.0.0")
    assert values_path.read_text(encoding="utf-8") == original
