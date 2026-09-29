"""check_image_digests: sliding vs pinned tag wiring and the [DIGEST-GONE] check.

registry_tag_exists is monkeypatched; no network access."""

import urllib.error

from email.message import Message
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture(autouse=True)
def _clear_tag_exists_cache(libimagedigests: ModuleType):
    """Clear cached_tag_exists' module-level memo: libimagedigests is session-scoped, so a
    cached fake result would otherwise leak into later tests using the same (repo, version)."""
    libimagedigests.clear_tag_exists_cache()
    yield
    libimagedigests.clear_tag_exists_cache()


def write_values(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


# --- check_image_digests: sliding vs pinned wiring ---
# is_sliding_tag is mocked (tested in lib.registry); only bucket routing is tested here.

TWO_IMAGES_VALUES = (
    "nginx:\n"
    "  image:\n"
    "    repository: nginxinc/nginx-unprivileged\n"
    f'    tag: "1.31.3@sha256:{"a" * 64}"\n'
    "zac:\n"
    "  image:\n"
    "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
    f'    tag: "5.1.0@sha256:{"b" * 64}"\n'
)


def test_check_image_digests_sliding_drift_warns_but_passes(
    vp: ModuleType,
    libimagedigests: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Sliding-tag drift with the old digest still pullable is a warning, not a failure."""
    write_values(tmp_path, TWO_IMAGES_VALUES)
    # nginx tag slid to "c" but old digest "a" still pulls; zac's tag is unchanged
    registry = {
        ("nginxinc/nginx-unprivileged", "1.31.3"): (True, f"sha256:{'c' * 64}"),
        ("nginxinc/nginx-unprivileged", f"sha256:{'a' * 64}"): (True, f"sha256:{'a' * 64}"),
        ("infonl/zaakafhandelcomponent", "5.1.0"): (True, f"sha256:{'b' * 64}"),
    }
    calls: list[tuple[str, str]] = []

    def fake_registry_tag_exists(host, repo, tag):
        calls.append((repo, tag))
        return registry[(repo, tag)]

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", fake_registry_tag_exists)
    monkeypatch.setattr(
        libimagedigests,
        "is_sliding_tag",
        lambda values_path, host, repo, version, live_digest: repo == "nginxinc/nginx-unprivileged",
    )
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    # the old-digest precondition was actually looked up, not a catch-all match
    assert ("nginxinc/nginx-unprivileged", f"sha256:{'a' * 64}") in calls
    assert "1 sliding" in detail
    assert "0 stale" in detail
    out = capsys.readouterr().out
    assert "[SLIDING  ]" in out
    assert "refresh with fix-image-digests" in out
    assert "[DIGEST-GONE]" not in out
    assert "MISMATCH" not in out


def test_check_image_digests_pinned_drift_still_fails(
    vp: ModuleType,
    libimagedigests: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A component release tag drifting fails, even when a sliding tag also drifted."""
    write_values(tmp_path, TWO_IMAGES_VALUES)
    monkeypatch.setattr(
        libimagedigests,
        "registry_tag_exists",
        lambda host, repo, tag: (
            (True, f"sha256:{'d' * 64}")
            if repo == "nginxinc/nginx-unprivileged"  # drifted too, but a known sliding tag
            else (True, f"sha256:{'c' * 64}")  # zac drifted — not sliding
        ),
    )
    monkeypatch.setattr(
        libimagedigests,
        "is_sliding_tag",
        lambda values_path, host, repo, version, live_digest: repo == "nginxinc/nginx-unprivileged",
    )
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "1 sliding" in detail
    assert "1 stale" in detail
    out = capsys.readouterr().out
    assert "[SLIDING  ]" in out
    assert "[MISMATCH ]" in out
    assert "zaakafhandelcomponent" in out


# --- check_image_digests: [DIGEST-GONE] — is the exact pinned digest still pullable?
# registry_tag_exists accepts a digest in the tag position, so it's just a second call.


def test_check_image_digests_matched_pin_never_gets_a_second_call(
    vp: ModuleType, libimagedigests: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Live digest equal to the pinned one: no digest-liveness call is made."""
    write_values(tmp_path, (f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{"a" * 64}"\n'))
    calls = []

    def spy(host, repo, tag):
        calls.append(tag)
        return True, f"sha256:{'a' * 64}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)
    ok, _detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert calls == ["1.0.0"]  # exactly one call, the tag check — no digest-liveness follow-up


def test_check_image_digests_sliding_with_digest_still_pullable_only_warns(
    vp: ModuleType,
    libimagedigests: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Tag slid but the old digest still resolves: [SLIDING] warning, no [DIGEST-GONE]."""
    digest_a = "a" * 64
    write_values(
        tmp_path,
        (f'nginx:\n  image:\n    repository: nginxinc/nginx-unprivileged\n    tag: "1.31.3@sha256:{digest_a}"\n'),
    )
    calls = []

    def spy(host, repo, tag):
        calls.append(tag)
        if tag == f"sha256:{digest_a}":
            return True, f"sha256:{digest_a}"  # the OLD digest still resolves
        return True, f"sha256:{'c' * 64}"  # the TAG now points elsewhere

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)
    monkeypatch.setattr(libimagedigests, "is_sliding_tag", lambda *a, **k: True)
    ok, _detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert calls == ["1.31.3", f"sha256:{digest_a}"]  # tag check, then the digest-liveness follow-up
    out = capsys.readouterr().out
    assert "[SLIDING  ]" in out
    assert "[DIGEST-GONE]" not in out


def test_check_image_digests_sliding_with_digest_gone_fails(
    vp: ModuleType,
    libimagedigests: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Tag slid and the pinned digest is garbage-collected upstream: hard failure, since
    helm install/upgrade would fail now."""
    digest_a = "a" * 64
    write_values(
        tmp_path,
        (f'nginx:\n  image:\n    repository: nginxinc/nginx-unprivileged\n    tag: "1.31.3@sha256:{digest_a}"\n'),
    )

    def spy(host, repo, tag):
        if tag == f"sha256:{digest_a}":
            return False, None  # the OLD digest is gone
        return True, f"sha256:{'c' * 64}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)
    monkeypatch.setattr(libimagedigests, "is_sliding_tag", lambda *a, **k: True)
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "1 pinned digest(s) gone" in detail
    out = capsys.readouterr().out
    assert "[SLIDING  ]" in out
    assert "[DIGEST-GONE]" in out
    assert f"sha256:{digest_a}" in out


def test_check_image_digests_mismatch_with_digest_gone_fails(
    vp: ModuleType,
    libimagedigests: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A non-sliding MISMATCH with a gone digest adds [DIGEST-GONE] on top of [MISMATCH]."""
    digest_a = "a" * 64
    write_values(tmp_path, (f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{digest_a}"\n'))

    def spy(host, repo, tag):
        if tag == f"sha256:{digest_a}":
            return False, None
        return True, f"sha256:{'c' * 64}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)
    monkeypatch.setattr(libimagedigests, "is_sliding_tag", lambda *a, **k: False)
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "1 pinned digest(s) gone" in detail
    out = capsys.readouterr().out
    assert "[MISMATCH ]" in out
    assert "[DIGEST-GONE]" in out


def test_check_image_digests_fetch_error_with_digest_gone_fails(
    vp: ModuleType,
    libimagedigests: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A tag-check fetch error (not UNVERIFIABLE_HOSTS) still checks the old digest."""
    digest_a = "a" * 64
    write_values(tmp_path, (f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{digest_a}"\n'))

    def spy(host, repo, tag):
        if tag == "1.0.0":
            msg = "tag check failed"
            raise urllib.error.URLError(msg)
        return False, None  # the digest-liveness check: gone

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "1 fetch error" in detail
    assert "1 pinned digest(s) gone" in detail
    out = capsys.readouterr().out
    assert "[FETCH-ERR]" in out
    assert "[DIGEST-GONE]" in out


def test_check_image_digests_unverifiable_host_skips_digest_liveness_check_entirely(
    vp: ModuleType,
    libimagedigests: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """UNVERIFIABLE_HOSTS hosts skip the digest-liveness call too (anonymous access fails)."""
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
    calls = []

    def spy(host, repo, tag):
        calls.append(tag)
        msg = "https://firewalled-registry.example.com/v2/..."
        raise urllib.error.HTTPError(msg, 401, "Unauthorized", Message(), None)

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)
    ok, _detail = vp.check_image_digests(tmp_path)
    assert ok is True
    # the tag check retries once on network error; no digest-liveness follow-up
    assert calls == ["1.1.1", "1.1.1"]
    out = capsys.readouterr().out
    assert "[DIGEST-GONE]" not in out
