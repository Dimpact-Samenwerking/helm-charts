"""parse_repo, resolve_pin_repo, scan_digest_pins, find_stale_digests, main —
pure logic plus a mocked-registry integration test. No network access
needed: registry_tag_exists is monkeypatched wherever a live fetch would
otherwise happen."""
import urllib.error

import pytest


# --- parse_repo ---

def test_parse_repo_bare_docker_hub_official_image(sid):
    assert sid.parse_repo("python") == ("docker.io", "library/python")


def test_parse_repo_bare_docker_hub_namespaced(sid):
    assert sid.parse_repo("nginxinc/nginx-unprivileged") == ("docker.io", "nginxinc/nginx-unprivileged")


def test_parse_repo_explicit_host(sid):
    assert sid.parse_repo("ghcr.io/infonl/zaakafhandelcomponent") == ("ghcr.io", "infonl/zaakafhandelcomponent")


# --- resolve_pin_repo ---

def test_resolve_pin_repo_active_sibling_key(sid):
    lines = [
        "    nginx:",
        "      repository: nginxinc/nginx-unprivileged",
        '      tag: "1.31.3@sha256:aaaa"',
    ]
    assert sid.resolve_pin_repo(lines, 2, 6) == "nginxinc/nginx-unprivileged"


def test_resolve_pin_repo_ref_comment_fallback(sid):
    lines = [
        "  opa:",
        "    # openpolicyagent/opa:1.17.1-static@sha256:aaaa",
        "    image:",
        "      #repository: openpolicyagent/opa",
        '      tag: "1.17.1-static@sha256:aaaa"',
    ]
    assert sid.resolve_pin_repo(lines, 4, 6) == "openpolicyagent/opa"


def test_resolve_pin_repo_commented_repository_key_fallback(sid):
    lines = [
        "    image:",
        "      #repository: maykinmedia/open-archiefbeheer",
        '      tag: "2.0.0@sha256:aaaa"',
    ]
    assert sid.resolve_pin_repo(lines, 2, 6) == "maykinmedia/open-archiefbeheer"


def test_resolve_pin_repo_unresolved_returns_none(sid):
    lines = [
        "  image:",
        '    tag: "1.27.4@sha256:aaaa"',
    ]
    assert sid.resolve_pin_repo(lines, 1, 4) is None


# --- scan_digest_pins ---

def test_scan_digest_pins_quoted_and_bare(sid):
    lines = [
        "  a:",
        "    repository: org/repo-a",
        '    tag: "1.0.0@sha256:' + "a" * 64 + '"',
        "  b:",
        "    repository: org/repo-b",
        "    tag: 2.0.0@sha256:" + "b" * 64,
    ]
    pins = sid.scan_digest_pins(lines)
    assert [(p["version"], p["digest"], p["repository"]) for p in pins] == [
        ("1.0.0", "a" * 64, "org/repo-a"),
        ("2.0.0", "b" * 64, "org/repo-b"),
    ]


# --- find_stale_digests ---

def test_find_stale_digests_reports_mismatch(sid, monkeypatch):
    lines = [
        "a:",
        "  image:",
        "    repository: org/repo",
        f'    tag: "1.0.0@sha256:{"a" * 64}"',
    ]
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'b' * 64}"))
    stale, unresolved, fetch_errors = sid.find_stale_digests(lines)
    assert unresolved == []
    assert fetch_errors == []
    assert len(stale) == 1
    repository, version, old_digest, new_digest, pin_lines, sliding = stale[0]
    assert (repository, version, old_digest, new_digest, pin_lines, sliding) == (
        "org/repo", "1.0.0", "a" * 64, f"sha256:{'b' * 64}", [4], False
    )


def test_find_stale_digests_no_change_when_matching(sid, monkeypatch):
    lines = ["a:", "  image:", "    repository: org/repo", f'    tag: "1.0.0@sha256:{"a" * 64}"']
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'a' * 64}"))
    stale, unresolved, fetch_errors = sid.find_stale_digests(lines)
    assert stale == [] and unresolved == [] and fetch_errors == []


def test_find_stale_digests_records_unresolved(sid):
    lines = ["a:", "  image:", f'    tag: "1.0.0@sha256:{"a" * 64}"']
    stale, unresolved, fetch_errors = sid.find_stale_digests(lines)
    assert stale == [] and fetch_errors == []
    assert len(unresolved) == 1 and unresolved[0]["line"] == 3


def test_find_stale_digests_retries_once_then_gives_up(sid, monkeypatch):
    lines = ["a:", "  image:", "    repository: org/repo", f'    tag: "1.0.0@sha256:{"a" * 64}"']
    monkeypatch.setattr(
        sid, "registry_tag_exists",
        lambda host, repo, tag: (_ for _ in ()).throw(urllib.error.URLError("down")),
    )
    stale, unresolved, fetch_errors = sid.find_stale_digests(lines)
    assert stale == [] and unresolved == []
    assert len(fetch_errors) == 1 and fetch_errors[0][0] == "org/repo"


def test_find_stale_digests_dedupes_shared_repo_and_tag(sid, monkeypatch):
    lines = [
        "a:", "  image:", "    repository: org/repo", f'    tag: "1.0.0@sha256:{"a" * 64}"',
        "b:", "  image:", "    repository: org/repo", f'    tag: "1.0.0@sha256:{"a" * 64}"',
    ]
    calls = []

    def spy(host, repo, tag):
        calls.append((host, repo, tag))
        return True, f"sha256:{'b' * 64}"

    monkeypatch.setattr(sid, "registry_tag_exists", spy)
    stale, unresolved, fetch_errors = sid.find_stale_digests(lines)
    assert calls == [("docker.io", "org/repo", "1.0.0")]
    assert len(stale) == 1
    assert stale[0][4] == [4, 8]  # both pin lines share the one stale digest


GLOBAL_IMAGES_LINES = (
    "global:\n"
    "  images:\n"
    "    nginx: &nginxImage\n"
    "      repository: nginxinc/nginx-unprivileged\n"
    f'      tag: "1.31.3@sha256:{"a" * 64}"\n'
    "\n"
    "zac:\n"
    "  image:\n"
    "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
    f'    tag: "5.1.0@sha256:{"b" * 64}"\n'
).splitlines()


def test_find_stale_digests_marks_global_images_pin_as_sliding(sid, monkeypatch):
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (
        (True, f"sha256:{'c' * 64}") if repo == "nginxinc/nginx-unprivileged"
        else (True, f"sha256:{'b' * 64}")  # zac unchanged
    ))
    stale, unresolved, fetch_errors = sid.find_stale_digests(GLOBAL_IMAGES_LINES)
    assert len(stale) == 1
    assert stale[0][0] == "nginxinc/nginx-unprivileged"
    assert stale[0][5] is True  # sliding


def test_find_stale_digests_marks_component_pin_as_not_sliding(sid, monkeypatch):
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (
        (True, f"sha256:{'a' * 64}") if repo == "nginxinc/nginx-unprivileged"  # unchanged
        else (True, f"sha256:{'c' * 64}")  # zac drifted
    ))
    stale, unresolved, fetch_errors = sid.find_stale_digests(GLOBAL_IMAGES_LINES)
    assert len(stale) == 1
    assert stale[0][0] == "ghcr.io/infonl/zaakafhandelcomponent"
    assert stale[0][5] is False  # not sliding


# --- main() integration ---

def write_values(path, text):
    path.write_text(text, encoding="utf-8")


def test_main_dry_run_does_not_write(sid, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    original = "a:\n  image:\n    repository: org/repo\n" f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    write_values(values_path, original)
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'b' * 64}"))
    monkeypatch.setattr("sys.argv", ["set-image-digests.py", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 0
    assert values_path.read_text(encoding="utf-8") == original


def test_main_writes_new_digest_preserving_everything_else(sid, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    old_digest = "a" * 64
    new_digest = "b" * 64
    write_values(values_path, f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{old_digest}"\n')
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{new_digest}"))
    monkeypatch.setattr("sys.argv", ["set-image-digests.py"])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 0
    updated = values_path.read_text(encoding="utf-8")
    assert old_digest not in updated
    assert f'tag: "1.0.0@sha256:{new_digest}"' in updated


def test_main_updates_all_occurrences_of_shared_digest(sid, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    old_digest = "a" * 64
    new_digest = "b" * 64
    write_values(values_path, (
        "a:\n  image:\n    repository: org/repo\n    tag: "
        f'"1.0.0@sha256:{old_digest}"\n'
        "b:\n  image:\n    repository: org/repo\n    tag: "
        f'"1.0.0@sha256:{old_digest}"\n'
    ))
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{new_digest}"))
    monkeypatch.setattr("sys.argv", ["set-image-digests.py"])

    with pytest.raises(SystemExit):
        sid.main()
    updated = values_path.read_text(encoding="utf-8")
    assert updated.count(new_digest) == 2
    assert old_digest not in updated


def test_main_exits_nonzero_on_fetch_error(sid, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    write_values(values_path, f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{"a" * 64}"\n')
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(
        sid, "registry_tag_exists",
        lambda host, repo, tag: (_ for _ in ()).throw(urllib.error.URLError("down")),
    )
    monkeypatch.setattr("sys.argv", ["set-image-digests.py"])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 1


def test_main_exits_zero_when_nothing_stale(sid, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    write_values(values_path, f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{"a" * 64}"\n')
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'a' * 64}"))
    monkeypatch.setattr("sys.argv", ["set-image-digests.py"])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 0


# --- main(): --all vs default (sliding vs pinned) ---

def write_global_images_values(path, nginx_digest, zac_digest):
    write_values(path, (
        "global:\n"
        "  images:\n"
        "    nginx: &nginxImage\n"
        "      repository: nginxinc/nginx-unprivileged\n"
        f'      tag: "1.31.3@sha256:{nginx_digest}"\n'
        "\n"
        "zac:\n"
        "  image:\n"
        "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
        f'    tag: "5.1.0@sha256:{zac_digest}"\n'
    ))


def test_main_default_updates_pinned_but_not_sliding(sid, tmp_path, monkeypatch, capsys):
    values_path = tmp_path / "values.yaml"
    old_nginx, new_nginx = "a" * 64, "c" * 64
    old_zac, new_zac = "b" * 64, "d" * 64
    write_global_images_values(values_path, old_nginx, old_zac)
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (
        (True, f"sha256:{new_nginx}") if repo == "nginxinc/nginx-unprivileged"
        else (True, f"sha256:{new_zac}")
    ))
    monkeypatch.setattr("sys.argv", ["set-image-digests.py"])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 0
    updated = values_path.read_text(encoding="utf-8")
    assert old_nginx in updated  # sliding pin left untouched by default
    assert new_nginx not in updated
    assert old_zac not in updated  # pinned tag updated
    assert new_zac in updated
    out = capsys.readouterr().out
    assert "not updated (pass --all to include)" in out


def test_main_all_flag_updates_sliding_too(sid, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    old_nginx, new_nginx = "a" * 64, "c" * 64
    old_zac, new_zac = "b" * 64, "d" * 64
    write_global_images_values(values_path, old_nginx, old_zac)
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (
        (True, f"sha256:{new_nginx}") if repo == "nginxinc/nginx-unprivileged"
        else (True, f"sha256:{new_zac}")
    ))
    monkeypatch.setattr("sys.argv", ["set-image-digests.py", "--all"])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 0
    updated = values_path.read_text(encoding="utf-8")
    assert old_nginx not in updated
    assert new_nginx in updated
    assert old_zac not in updated
    assert new_zac in updated


def test_main_default_no_pinned_staleness_reports_sliding_skip(sid, tmp_path, monkeypatch, capsys):
    """Only the sliding pin drifted — default run must still exit cleanly
    and say nothing was updated, rather than claiming full success silently."""
    values_path = tmp_path / "values.yaml"
    old_nginx, new_nginx = "a" * 64, "c" * 64
    zac_digest = "b" * 64
    write_global_images_values(values_path, old_nginx, zac_digest)
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (
        (True, f"sha256:{new_nginx}") if repo == "nginxinc/nginx-unprivileged"
        else (True, f"sha256:{zac_digest}")
    ))
    monkeypatch.setattr("sys.argv", ["set-image-digests.py"])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 0
    assert old_nginx in values_path.read_text(encoding="utf-8")  # left untouched, not written
    out = capsys.readouterr().out
    assert "nothing to update" in out
    assert "pass --all to include them" in out
