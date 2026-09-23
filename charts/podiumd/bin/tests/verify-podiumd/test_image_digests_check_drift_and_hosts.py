"""check_image_digests — split registry:/repository: style resolution,
version-drift/duplicate-pin reporting, and UNVERIFIABLE_HOSTS handling.
No network access needed: registry_tag_exists is monkeypatched wherever
a live fetch would otherwise happen."""

import urllib.error

from email.message import Message

import pytest


@pytest.fixture(autouse=True)
def _clear_tag_exists_cache(libimagedigests):
    """cached_tag_exists' own in-process memoization (see its own
    docstring) lives in a module-level dict, and libimagedigests is a
    session-scoped fixture — without this, one test's cached (fake)
    registry_tag_exists result could silently leak into a LATER test
    that reuses the same (repository, version), even though that later
    test mocks registry_tag_exists completely differently."""
    libimagedigests._tag_exists_cache.clear()
    yield
    libimagedigests._tag_exists_cache.clear()


def write_values(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


# --- check_image_digests: split registry:/repository: style resolution ---


def test_check_image_digests_split_style_pin_queries_the_correct_registry(vp, libimagedigests, tmp_path, monkeypatch):
    """Regression test for the actual bug: a split-style pin (redis-ha's
    real values.yaml shape) must resolve against ITS OWN registry (quay.io
    here), not silently fall back to docker.io."""
    write_values(
        tmp_path,
        (
            "redis-ha:\n"
            "  image:\n"
            "    registry: quay.io\n"
            "    repository: opstree/redis\n"
            f'    tag: "v8.6.6@sha256:{"a" * 64}"\n'
        ),
    )
    calls = []

    def spy(host, repo, tag):
        calls.append((host, repo, tag))
        return True, f"sha256:{'a' * 64}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert calls == [("quay.io", "opstree/redis", "v8.6.6")]
    assert "1/1 matched" in detail


def test_check_image_digests_reports_version_drift(vp, libimagedigests, tmp_path, monkeypatch, capsys):
    write_values(
        tmp_path,
        (
            "a:\n"
            "  image:\n"
            "    repository: curlimages/curl\n"
            f'    tag: "8.21.0@sha256:{"a" * 64}"\n'
            "b:\n"
            "  image:\n"
            "    repository: curlimages/curl\n"
            f'    tag: "8.20.0@sha256:{"b" * 64}"\n'
        ),
    )
    digests_by_tag = {"8.21.0": "a" * 64, "8.20.0": "b" * 64}
    monkeypatch.setattr(
        libimagedigests, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{digests_by_tag[tag]}")
    )
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "1 version-drift finding" in detail
    assert "0 duplicate pin(s)" in detail
    out = capsys.readouterr().out
    assert "[VERSION-DRIFT]" in out
    assert "curlimages/curl" in out
    assert "8.21.0@sha256:" + "a" * 64 in out
    assert "8.20.0@sha256:" + "b" * 64 in out
    assert "values.yaml:4" in out
    assert "values.yaml:8" in out


def test_check_image_digests_reports_duplicate_pin(vp, libimagedigests, tmp_path, monkeypatch, capsys):
    write_values(
        tmp_path,
        (
            "a:\n"
            "  image:\n"
            "    repository: curlimages/curl\n"
            f'    tag: "8.21.0@sha256:{"a" * 64}"\n'
            "b:\n"
            "  image:\n"
            "    repository: curlimages/curl\n"
            f'    tag: "8.21.0@sha256:{"a" * 64}"\n'
        ),
    )
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'a' * 64}"))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "1 duplicate pin(s)" in detail
    assert "0 version-drift finding" in detail
    out = capsys.readouterr().out
    assert "[DUPLICATE-PIN] curlimages/curl:8.21.0" in out
    assert "values.yaml:4, 8" in out
    assert "YAML anchor" in out


def test_check_image_digests_no_inconsistency_when_repository_pinned_once(vp, libimagedigests, tmp_path, monkeypatch):
    write_values(tmp_path, (f'a:\n  image:\n    repository: curlimages/curl\n    tag: "8.21.0@sha256:{"a" * 64}"\n'))
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'a' * 64}"))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert "0 duplicate pin(s)" in detail
    assert "0 version-drift finding" in detail


# --- check_image_digests: UNVERIFIABLE_HOSTS ---


def test_check_image_digests_unverifiable_host_does_not_fail_the_check(
    vp, libimagedigests, tmp_path, monkeypatch, capsys
):
    """A registry this environment can never reach anonymously (see
    lib.registry.UNVERIFIABLE_HOSTS) must be reported distinctly from a
    genuine FETCH-ERR, and must not fail the check on its own — it can't
    succeed here regardless of whether the pin is actually correct.
    UNVERIFIABLE_HOSTS is empty by default (no such host currently known —
    see its docstring in lib/registry.py), so this injects a fake one
    rather than depending on any real, possibly-transient special case."""
    write_values(
        tmp_path,
        (
            "pabc:\n"
            "  image:\n"
            "    repository: firewalled-registry.example.com/platform-autorisatie-beheer-component/pabc-api\n"
            f'    tag: "1.1.1@sha256:{"a" * 64}"\n'
        ),
    )
    monkeypatch.setattr(libimagedigests, "UNVERIFIABLE_HOSTS", {"firewalled-registry.example.com"})
    monkeypatch.setattr(
        libimagedigests,
        "registry_tag_exists",
        lambda host, repo, tag: (_ for _ in ()).throw(
            urllib.error.HTTPError(
                "https://firewalled-registry.example.com/v2/...", 401, "Unauthorized", Message(), None
            )
        ),
    )
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert "0 fetch error" in detail
    assert "1 unverifiable" in detail
    out = capsys.readouterr().out
    assert "[UNVERIFIABLE]" in out
    assert "values.yaml:4" in out
    assert "FETCH-ERR" not in out


def test_check_image_digests_non_unverifiable_host_fetch_error_still_fails(vp, libimagedigests, tmp_path, monkeypatch):
    write_values(tmp_path, (f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{"a" * 64}"\n'))
    monkeypatch.setattr(
        libimagedigests,
        "registry_tag_exists",
        lambda host, repo, tag: (_ for _ in ()).throw(
            urllib.error.HTTPError("https://docker.io/v2/...", 401, "Unauthorized", Message(), None)
        ),
    )
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "1 fetch error" in detail
    assert "0 unverifiable" in detail
