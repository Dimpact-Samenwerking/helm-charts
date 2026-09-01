"""lib.image_version — image_basename, find_matches, find_matches_in_scope,
resolve_scoped_matches, check_basename_version, update_image_version,
basenames_under_scope, resolve_basename. No network needed: lib.registry.
registry_tag_exists is monkeypatched wherever a live fetch would otherwise
happen."""
import pytest


def write_values(tmp_path, text):
    path = tmp_path / "values.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def write_chart_yaml(chart_dir, deps):
    """`deps`: [(name, alias_or_none), ...]."""
    lines = ["apiVersion: v2", "name: podiumd", "version: 1.0.0", "dependencies:"]
    for name, alias in deps:
        lines.append(f"  - name: {name}")
        if alias:
            lines.append(f"    alias: {alias}")
        lines += ["    version: 1.0.0", '    repository: "@x"']
    (chart_dir / "Chart.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


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


# --- find_matches_in_scope / resolve_scoped_matches ---

def test_find_matches_in_scope_finds_pins_under_key(libimageversion):
    lines = [
        "a:", "  image:", "    repository: curlimages/curl",
        '    tag: "8.21.0@sha256:' + "a" * 64 + '"',
        "b:", "  image:", "    repository: curlimages/curl",
        '    tag: "8.21.0@sha256:' + "a" * 64 + '"',
    ]
    matches = libimageversion.find_matches_in_scope(lines, "a", "curl")
    assert [m["line"] for m in matches] == [4]


def test_resolve_scoped_matches_multiple_key_translates_to_global_scope(libimageversion):
    """MULTIPLE_KEY (release-table.csv's own convention for a base image
    shared across several unrelated components) resolves against
    values.yaml's global.images scope, not a literal "MULTIPLE" key."""
    lines = [
        "global:",
        "  images:",
        "    curl:", "      repository: curlimages/curl",
        '      tag: "8.21.0@sha256:' + "a" * 64 + '"',
    ]
    matches = libimageversion.resolve_scoped_matches(lines, libimageversion.MULTIPLE_KEY, "curl")
    assert [m["line"] for m in matches] == [5]


def test_resolve_scoped_matches_no_match_under_key_raises(libimageversion):
    lines = [
        "a:", "  image:", "    repository: curlimages/curl",
        '    tag: "8.21.0@sha256:' + "a" * 64 + '"',
    ]
    with pytest.raises(SystemExit, match="no image pin with basename 'curl' found under 'b'"):
        libimageversion.resolve_scoped_matches(lines, "b", "curl")


def test_resolve_scoped_matches_ambiguous_repository_under_key_raises(libimageversion):
    """Two DISTINCT repositories sharing a basename under the SAME
    scope key can't be identified uniquely from <key> <basename> alone —
    an error, never a guess."""
    lines = [
        "a:", "  image:", "    repository: org-one/curl",
        '    tag: "1.0.0@sha256:' + "a" * 64 + '"',
        "  sidecar:", "    image:", "      repository: org-two/curl",
        '      tag: "1.0.0@sha256:' + "a" * 64 + '"',
    ]
    with pytest.raises(SystemExit, match="'curl' under 'a' is not unique"):
        libimageversion.resolve_scoped_matches(lines, "a", "curl")


# --- check_basename_version ---

def test_check_basename_version_reports_found(libimageversion, monkeypatch):
    lines = [
        "pabc:",
        "  image:",
        "    repository: ghcr.io/platform-autorisatie-beheer-component/pabc-api",
        '    tag: "1.1.1@sha256:' + "a" * 64 + '"',
    ]
    monkeypatch.setattr(libimageversion, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "b" * 64))

    results = libimageversion.check_basename_version(lines, "pabc", "pabc-api", "1.1.2")

    assert results == [{
        "repository": "ghcr.io/platform-autorisatie-beheer-component/pabc-api",
        "host": "ghcr.io", "repo_path": "platform-autorisatie-beheer-component/pabc-api",
        "exists": True, "digest": "sha256:" + "b" * 64,
    }]


def test_check_basename_version_reports_missing(libimageversion, monkeypatch):
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


def test_check_basename_version_dedupes_shared_repository(libimageversion, monkeypatch):
    """The same basename pinned twice under the SAME repository (e.g.
    curl, shared via values.yaml's global.images anchor block) only
    needs one registry lookup, same as update_image_version's own
    dedup."""
    lines = [
        "global:",
        "  a:", "    image:", "      repository: curlimages/curl",
        '      tag: "8.21.0@sha256:' + "a" * 64 + '"',
        "  b:", "    sub:", "      image:", "        repository: curlimages/curl",
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


def test_check_basename_version_no_match_raises(libimageversion):
    with pytest.raises(SystemExit, match="no image pin with basename 'curl' found under 'a'"):
        libimageversion.check_basename_version([], "a", "curl", "8.22.0")


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
    changes = libimageversion.update_image_version(values_path, "pabc", "pabc-api", "1.1.2")
    assert len(changes) == 1
    assert changes[0] == {
        "line": 4, "repository": "ghcr.io/platform-autorisatie-beheer-component/pabc-api",
        "old_version": "1.1.1", "old_digest": "sha256:" + "a" * 64,
        "new_version": "1.1.2", "new_digest": "sha256:" + "b" * 64,
    }
    assert f'tag: "1.1.2@sha256:{"b" * 64}"' in values_path.read_text(encoding="utf-8")


def test_update_image_version_updates_all_shared_occurrences(libimageversion, tmp_path, monkeypatch):
    """curlimages/curl, shared via values.yaml's global.images anchor
    block, pinned at two unrelated places under it — both must update,
    with only one registry lookup between them."""
    values_path = write_values(tmp_path, (
        "global:\n"
        "  images:\n"
        "    curl: &curlImage\n"
        "      repository: curlimages/curl\n"
        f'      tag: "8.21.0@sha256:{"a" * 64}"\n'
        "  kiss:\n"
        "    indexTemplateImage:\n"
        "      repository: curlimages/curl\n"
        f'      tag: "8.21.0@sha256:{"a" * 64}"\n'
    ))
    calls = []

    def fake_registry_tag_exists(host, repo, tag):
        calls.append((host, repo, tag))
        return True, "sha256:" + "c" * 64

    monkeypatch.setattr(libimageversion, "registry_tag_exists", fake_registry_tag_exists)
    changes = libimageversion.update_image_version(values_path, libimageversion.MULTIPLE_KEY, "curl", "8.22.0")
    assert [c["line"] for c in changes] == [5, 9]
    assert len(calls) == 1  # deduped: same repository, one lookup
    text = values_path.read_text(encoding="utf-8")
    assert text.count(f'8.22.0@sha256:{"c" * 64}') == 2


def test_update_image_version_no_match_raises(libimageversion, tmp_path):
    values_path = write_values(tmp_path, "a:\n  image:\n    repository: org/repo\n    tag: \"1.0.0@sha256:" + "a" * 64 + "\"\n")
    with pytest.raises(SystemExit, match="no image pin with basename 'curl' found under 'a'"):
        libimageversion.update_image_version(values_path, "a", "curl", "8.22.0")


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
    changes = libimageversion.update_image_version(values_path, "pabc", "pabc-api", "1.1.2")
    assert changes == []
    assert values_path.read_text(encoding="utf-8") == original


def test_update_image_version_only_updates_stale_occurrence(libimageversion, tmp_path, monkeypatch):
    """One of two shared occurrences already at the target version — only
    the other actually gets rewritten, but the registry is still queried
    (needed for the one that IS changing)."""
    values_path = write_values(tmp_path, (
        "global:\n"
        "  a:\n"
        "    image:\n"
        "      repository: curlimages/curl\n"
        f'      tag: "8.22.0@sha256:{"a" * 64}"\n'
        "  b:\n"
        "    image:\n"
        "      repository: curlimages/curl\n"
        f'      tag: "8.21.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(libimageversion, "registry_tag_exists",
                         lambda host, repo, tag: (True, "sha256:" + "c" * 64))
    changes = libimageversion.update_image_version(values_path, libimageversion.MULTIPLE_KEY, "curl", "8.22.0")
    assert [c["line"] for c in changes] == [9]


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
        libimageversion.update_image_version(values_path, "pabc", "pabc-api", "9.9.9")
    assert values_path.read_text(encoding="utf-8") == original  # nothing written on failure


def test_update_image_version_ambiguous_repositories_under_key_raises(libimageversion, tmp_path, monkeypatch):
    """Two DISTINCT repositories sharing a basename under the SAME scope
    key can't be identified uniquely (see resolve_scoped_matches) —
    rejected before any registry lookup or write happens."""
    values_path = write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org-one/curl\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
        "  sidecar:\n"
        "    image:\n"
        "      repository: org-two/curl\n"
        f'      tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))

    def fail_if_called(*a, **kw):
        raise AssertionError("registry should not be queried when the image isn't identified uniquely")

    monkeypatch.setattr(libimageversion, "registry_tag_exists", fail_if_called)
    original = values_path.read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="'curl' under 'a' is not unique"):
        libimageversion.update_image_version(values_path, "a", "curl", "2.0.0")
    assert values_path.read_text(encoding="utf-8") == original


# --- basenames_under_scope ---

def test_basenames_under_scope_finds_nested_pins(libimageversion, tmp_path):
    values_path = write_values(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{"a" * 64}"
  solr-operator:
    image:
      repository: apache/solr-operator
      tag: "0.9.1@sha256:{"b" * 64}"
""")
    lines = values_path.read_text(encoding="utf-8").splitlines()
    available = libimageversion.basenames_under_scope(lines, "zac")
    assert set(available) == {"zaakafhandelcomponent", "solr-operator"}


def test_basenames_under_scope_ignores_other_components(libimageversion, tmp_path):
    values_path = write_values(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{"a" * 64}"
openzaak:
  image:
    repository: openzaak/open-zaak
    tag: "1.0.0@sha256:{"b" * 64}"
""")
    lines = values_path.read_text(encoding="utf-8").splitlines()
    assert set(libimageversion.basenames_under_scope(lines, "zac")) == {"zaakafhandelcomponent"}


# --- resolve_basename ---

def test_resolve_basename_already_a_real_basename_short_circuits(libimageversion, tmp_path):
    """No Chart.yaml needed at all when `target` is already a basename
    with real pins -- existing update-image-version CLI behavior must
    never change for a call that already works today."""
    values_path = write_values(tmp_path, f"""\
a:
  image:
    repository: curlimages/curl
    tag: "8.21.0@sha256:{"a" * 64}"
""")
    lines = values_path.read_text(encoding="utf-8").splitlines()
    assert libimageversion.resolve_basename(tmp_path, lines, "curl") == "curl"


def test_resolve_basename_dependency_with_exactly_one_image_resolves(libimageversion, tmp_path):
    write_chart_yaml(tmp_path, [("openklant", None)])
    values_path = write_values(tmp_path, f"""\
openklant:
  image:
    repository: maykinmedia/open-klant
    tag: "2.15.0@sha256:{"a" * 64}"
""")
    lines = values_path.read_text(encoding="utf-8").splitlines()
    assert libimageversion.resolve_basename(tmp_path, lines, "openklant") == "open-klant"


def test_resolve_basename_resolves_via_alias_not_just_name(libimageversion, tmp_path):
    write_chart_yaml(tmp_path, [("zaakafhandelcomponent", "zac")])
    values_path = write_values(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{"a" * 64}"
""")
    lines = values_path.read_text(encoding="utf-8").splitlines()
    assert libimageversion.resolve_basename(tmp_path, lines, "zac") == "zaakafhandelcomponent"


def test_resolve_basename_dependency_with_multiple_images_raises_listing_them(libimageversion, tmp_path):
    write_chart_yaml(tmp_path, [("zaakafhandelcomponent", "zac")])
    values_path = write_values(tmp_path, f"""\
zac:
  image:
    repository: ghcr.io/infonl/zaakafhandelcomponent
    tag: "5.0.0@sha256:{"a" * 64}"
  solr-operator:
    image:
      repository: apache/solr-operator
      tag: "0.9.1@sha256:{"b" * 64}"
""")
    lines = values_path.read_text(encoding="utf-8").splitlines()
    with pytest.raises(SystemExit, match="solr-operator.*zaakafhandelcomponent"):
        libimageversion.resolve_basename(tmp_path, lines, "zac")


def test_resolve_basename_dependency_with_no_images_raises(libimageversion, tmp_path):
    write_chart_yaml(tmp_path, [("openzaak", None)])
    values_path = write_values(tmp_path, "openzaak:\n  enabled: true\n")
    lines = values_path.read_text(encoding="utf-8").splitlines()
    with pytest.raises(SystemExit, match="no digest-pinned image was found"):
        libimageversion.resolve_basename(tmp_path, lines, "openzaak")


def test_resolve_basename_unresolvable_target_raises(libimageversion, tmp_path):
    write_chart_yaml(tmp_path, [("openzaak", None)])
    values_path = write_values(tmp_path, "openzaak:\n  enabled: true\n")
    lines = values_path.read_text(encoding="utf-8").splitlines()
    with pytest.raises(SystemExit, match="is not a pinned image basename"):
        libimageversion.resolve_basename(tmp_path, lines, "nonexistent-thing")


def test_resolve_basename_no_chart_yaml_still_raises_cleanly(libimageversion, tmp_path):
    values_path = write_values(tmp_path, "openzaak:\n  enabled: true\n")
    lines = values_path.read_text(encoding="utf-8").splitlines()
    with pytest.raises(SystemExit, match="is not a pinned image basename"):
        libimageversion.resolve_basename(tmp_path, lines, "openzaak")
