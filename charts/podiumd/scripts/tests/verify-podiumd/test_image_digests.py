"""parse_repo, resolve_pin_repo, scan_digest_pins, check_image_digests —
pure logic plus a mocked-registry integration test. No network access
needed: registry_tag_exists is monkeypatched wherever a live fetch would
otherwise happen."""
import urllib.error

import pytest


# --- parse_repo ---

def test_parse_repo_bare_docker_hub_official_image(vp):
    assert vp.parse_repo("python") == ("docker.io", "library/python")


def test_parse_repo_bare_docker_hub_namespaced(vp):
    assert vp.parse_repo("nginxinc/nginx-unprivileged") == ("docker.io", "nginxinc/nginx-unprivileged")


def test_parse_repo_explicit_host(vp):
    assert vp.parse_repo("ghcr.io/infonl/zaakafhandelcomponent") == ("ghcr.io", "infonl/zaakafhandelcomponent")


def test_parse_repo_explicit_docker_io_host(vp):
    assert vp.parse_repo("docker.io/alpine/k8s") == ("docker.io", "alpine/k8s")


def test_parse_repo_localhost(vp):
    assert vp.parse_repo("localhost/foo") == ("localhost", "foo")


# --- resolve_pin_repo ---

def test_resolve_pin_repo_active_sibling_key(vp):
    lines = [
        "    nginx:",
        "      repository: nginxinc/nginx-unprivileged",
        '      tag: "1.31.3@sha256:aaaa"',
    ]
    assert vp.resolve_pin_repo(lines, 2, 6) == "nginxinc/nginx-unprivileged"


def test_resolve_pin_repo_active_sibling_key_with_comment_between(vp):
    lines = [
        "      initImage:",
        "        repository: python",
        "        # Digest-pinned to match docs/images/images-4.8.0.yaml",
        '        tag: "3.14-slim@sha256:aaaa"',
    ]
    assert vp.resolve_pin_repo(lines, 3, 8) == "python"


def test_resolve_pin_repo_ref_comment_fallback(vp):
    lines = [
        "  opa:",
        "    # openpolicyagent/opa:1.17.1-static@sha256:aaaa",
        "    image:",
        "      #repository: openpolicyagent/opa",
        '      tag: "1.17.1-static@sha256:aaaa"',
    ]
    assert vp.resolve_pin_repo(lines, 4, 6) == "openpolicyagent/opa"


def test_resolve_pin_repo_ref_comment_tolerates_stray_at(vp):
    lines = [
        "        # lachlanevenson/k8s-kubectl:@v1.25.4",
        "        image:",
        "          #repository:",
        "          tag: v1.25.4@sha256:aaaa",
    ]
    assert vp.resolve_pin_repo(lines, 3, 10) == "lachlanevenson/k8s-kubectl"


def test_resolve_pin_repo_commented_repository_key_fallback(vp):
    lines = [
        "    image:",
        "      #repository: maykinmedia/open-archiefbeheer",
        '      tag: "2.0.0@sha256:aaaa"',
    ]
    assert vp.resolve_pin_repo(lines, 2, 6) == "maykinmedia/open-archiefbeheer"


def test_resolve_pin_repo_unresolved_returns_none(vp):
    lines = [
        "  image:",
        '    tag: "1.27.4@sha256:aaaa"',
    ]
    assert vp.resolve_pin_repo(lines, 1, 4) is None


def test_resolve_pin_repo_stops_at_dedent_does_not_leak_across_blocks(vp):
    lines = [
        "otherBlock:",
        "  repository: should/not-be-used",
        "unrelated:",
        "  image:",
        '    tag: "1.0.0@sha256:aaaa"',
    ]
    assert vp.resolve_pin_repo(lines, 4, 4) is None


# --- scan_digest_pins ---

def test_scan_digest_pins_quoted_and_bare(vp):
    lines = [
        "  a:",
        "    repository: org/repo-a",
        '    tag: "1.0.0@sha256:' + "a" * 64 + '"',
        "  b:",
        "    repository: org/repo-b",
        "    tag: 2.0.0@sha256:" + "b" * 64,
    ]
    pins = vp.scan_digest_pins(lines)
    assert [(p["version"], p["digest"], p["repository"]) for p in pins] == [
        ("1.0.0", "a" * 64, "org/repo-a"),
        ("2.0.0", "b" * 64, "org/repo-b"),
    ]
    assert pins[0]["line"] == 3
    assert pins[1]["line"] == 6


def test_scan_digest_pins_ignores_non_digest_tags(vp):
    lines = ["  image:", "    tag: latest"]
    assert vp.scan_digest_pins(lines) == []


# --- check_image_digests (mocked registry) ---

def write_values(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


def test_check_image_digests_all_match(vp, tmp_path, monkeypatch):
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(vp, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'a' * 64}"))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert "1/1 matched" in detail


def test_check_image_digests_reports_mismatch(vp, tmp_path, monkeypatch, capsys):
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(vp, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'b' * 64}"))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "1 stale" in detail
    out = capsys.readouterr().out
    assert "MISMATCH" in out
    assert "org/repo" in out
    assert "line" in out.lower() or "lines" in out


def test_check_image_digests_reports_missing_tag_as_fetch_error(vp, tmp_path, monkeypatch):
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(vp, "registry_tag_exists", lambda host, repo, tag: (False, None))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "fetch error" in detail


def test_check_image_digests_retries_once_on_network_error_then_succeeds(vp, tmp_path, monkeypatch):
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    calls = {"n": 0}

    def flaky(host, repo, tag):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("temporary failure")
        return True, f"sha256:{'a' * 64}"

    monkeypatch.setattr(vp, "registry_tag_exists", flaky)
    ok, detail = vp.check_image_digests(tmp_path)
    assert calls["n"] == 2
    assert ok is True
    assert "1/1 matched" in detail


def test_check_image_digests_gives_up_after_one_retry(vp, tmp_path, monkeypatch):
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(
        vp, "registry_tag_exists",
        lambda host, repo, tag: (_ for _ in ()).throw(urllib.error.URLError("down")),
    )
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "1 fetch error" in detail


def test_check_image_digests_dedupes_shared_repo_and_tag(vp, tmp_path, monkeypatch):
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
        "b:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    calls = []

    def spy(host, repo, tag):
        calls.append((host, repo, tag))
        return True, f"sha256:{'a' * 64}"

    monkeypatch.setattr(vp, "registry_tag_exists", spy)
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert calls == [("docker.io", "org/repo", "1.0.0")]  # fetched once, not twice
    assert "1/1 matched" in detail


def test_check_image_digests_skips_unresolved_repository(vp, tmp_path, monkeypatch):
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    called = []
    monkeypatch.setattr(vp, "registry_tag_exists", lambda *a: called.append(a))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert called == []
    assert "0/0 matched" in detail
