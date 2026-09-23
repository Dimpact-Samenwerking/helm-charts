"""check_image_digests — sliding vs pinned tag wiring, and the
[DIGEST-GONE] check (is the EXACT pinned digest still pullable at all,
independent of whether the tag itself has drifted). No network access
needed: registry_tag_exists is monkeypatched wherever a live fetch would
otherwise happen."""

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
    libimagedigests.clear_tag_exists_cache()
    yield
    libimagedigests.clear_tag_exists_cache()


def write_values(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


# --- check_image_digests: sliding vs pinned wiring ---
#
# The classification logic itself (git-history digest count, registry
# sibling-tag fallback) lives in lib.registry and is tested there —
# is_sliding_tag is mocked here to test only that check_image_digests
# routes its verdict into the right bucket (and print label).

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


def test_check_image_digests_sliding_drift_warns_but_passes(vp, libimagedigests, tmp_path, monkeypatch, capsys):
    """A tag known to slide drifting is routine, expected drift -- and,
    as long as the OLD pinned digest is still independently pullable
    (see the [DIGEST-GONE] check), no longer a failure at all -- just a
    reported warning pointing at fix-image-digests."""
    write_values(tmp_path, TWO_IMAGES_VALUES)
    monkeypatch.setattr(
        libimagedigests,
        "registry_tag_exists",
        lambda host, repo, tag: (
            (True, f"sha256:{'c' * 64}") if repo == "nginxinc/nginx-unprivileged" else (True, f"sha256:{'b' * 64}")
        ),
    )
    monkeypatch.setattr(
        libimagedigests,
        "is_sliding_tag",
        lambda values_path, host, repo, version, live_digest: repo == "nginxinc/nginx-unprivileged",
    )
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert "1 sliding" in detail
    assert "0 stale" in detail
    out = capsys.readouterr().out
    assert "[SLIDING  ]" in out
    assert "[DIGEST-GONE]" not in out
    assert "MISMATCH" not in out


def test_check_image_digests_pinned_drift_still_fails(vp, libimagedigests, tmp_path, monkeypatch, capsys):
    """A component's own release tag drifting is a real failure, even when
    a sliding tag ALSO drifted in the same run."""
    write_values(tmp_path, TWO_IMAGES_VALUES)
    monkeypatch.setattr(
        libimagedigests,
        "registry_tag_exists",
        lambda host, repo, tag: (
            (True, f"sha256:{'a' * 64}")
            if repo == "nginxinc/nginx-unprivileged"  # unchanged, matches
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
    assert "0 sliding" in detail
    assert "1 stale" in detail
    out = capsys.readouterr().out
    assert "[MISMATCH ]" in out
    assert "zaakafhandelcomponent" in out


# --- check_image_digests: [DIGEST-GONE] — is the EXACT pinned digest
# still pullable at all? A genuinely different, harder question than
# whether the TAG has drifted (sliding or not) — see registry_tag_exists,
# whose manifest URL accepts a digest string in exactly the tag position,
# so no new registry-layer code is needed, just a second call.


def test_check_image_digests_matched_pin_never_gets_a_second_call(vp, libimagedigests, tmp_path, monkeypatch):
    """A matched pin's live digest already equals the pinned one -- it's
    trivially still there, so no second (digest-liveness) call is ever
    made for it."""
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
    vp, libimagedigests, tmp_path, monkeypatch, capsys
):
    """The OLD pinned digest independently resolves upstream — the tag
    merely slid, nothing this repo actually deploys is at risk. Warns
    (via [SLIDING], not a failure) and never reports [DIGEST-GONE]."""
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


def test_check_image_digests_sliding_with_digest_gone_fails(vp, libimagedigests, tmp_path, monkeypatch, capsys):
    """The tag slid AND the OLD digest this repo actually still pins has
    since been garbage-collected upstream — a real, hard failure: helm
    install/upgrade would fail outright right now, regardless of the
    tag-level slide itself only being a warning."""
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


def test_check_image_digests_mismatch_with_digest_gone_fails(vp, libimagedigests, tmp_path, monkeypatch, capsys):
    """A non-sliding MISMATCH whose old pinned digest is also gone —
    still just one failure category ([DIGEST-GONE]) added on top of the
    pre-existing [MISMATCH] failure, not a special case."""
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


def test_check_image_digests_fetch_error_with_digest_gone_fails(vp, libimagedigests, tmp_path, monkeypatch, capsys):
    """The tag check itself couldn't be confirmed (a genuine fetch error,
    not an UNVERIFIABLE_HOSTS one) — the old digest is STILL checked, and
    found gone here too."""
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
    vp, libimagedigests, tmp_path, monkeypatch, capsys
):
    """A host in UNVERIFIABLE_HOSTS is skipped for the SECOND call too —
    no point attempting what's already known to fail anonymously."""
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
    # the tag check retries once on its own network error -- both attempts
    # are still just the TAG check; no digest-liveness follow-up at all.
    assert calls == ["1.1.1", "1.1.1"]
    out = capsys.readouterr().out
    assert "[DIGEST-GONE]" not in out
