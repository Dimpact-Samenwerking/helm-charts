"""cached_tag_exists — the shared, in-process + on-disk memoization
check_image_digests' own loop and find_sliding_pins both call through, so
a --include=cve-diff run (which needs both) only pays for one real
per-pin registry lookup, not two. No network access needed:
registry_tag_exists is monkeypatched wherever a live fetch would
otherwise happen."""

import urllib.error

from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest

import lib.repo_access_cache as repo_access_cache


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


# --- cached_tag_exists ---
#
# The shared, in-process memoization check_image_digests' own loop and
# find_sliding_pins both call through, so a --include=cve-diff run (which
# needs both) only pays for one real per-pin registry lookup, not two.


def testcached_tag_exists_only_calls_registry_once_for_same_pin(libimagedigests, tmp_path, monkeypatch):
    calls = []

    def fake_registry_tag_exists(host, repo, tag):
        calls.append((host, repo, tag))
        return True, f"sha256:{'a' * 64}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", fake_registry_tag_exists)

    first = libimagedigests.cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")
    second = libimagedigests.cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")

    assert first == second == (True, f"sha256:{'a' * 64}")
    assert len(calls) == 1


def testcached_tag_exists_different_repository_or_version_is_a_distinct_call(libimagedigests, tmp_path, monkeypatch):
    calls = []

    def fake_registry_tag_exists(host, repo, tag):
        calls.append(tag)
        return True, f"sha256:{'a' * 64}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", fake_registry_tag_exists)

    libimagedigests.cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")
    libimagedigests.cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "2.0.0")

    assert len(calls) == 2


def testcached_tag_exists_does_not_cache_a_raised_exception(libimagedigests, tmp_path, monkeypatch):
    """A network error must propagate uncached -- check_image_digests' own
    retry-on-transient-network-error loop still genuinely retries over
    the network rather than replaying a cached failure."""
    calls = {"n": 0}

    def flaky(host, repo, tag):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("temporary failure")
        return True, f"sha256:{'a' * 64}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", flaky)

    with pytest.raises(urllib.error.URLError):
        libimagedigests.cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")
    result = libimagedigests.cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")

    assert calls["n"] == 2
    assert result == (True, f"sha256:{'a' * 64}")


# --- cached_tag_exists: disk tier (lib.repo_access_cache) ---
#
# Genuinely the SAME cache check_repo_access itself uses (same file, same
# cache_key/load_cache/save_cache/cache_entry_is_fresh functions, same
# TTL) -- an entry either one writes must be directly usable by the
# other, no format translation.


def testcached_tag_exists_reads_a_fresh_disk_entry_without_a_network_call(libimagedigests, tmp_path, monkeypatch):
    digest_a = "a" * 64
    key = repo_access_cache.cache_key("registry", ("docker.io", "org/repo", "1.0.0"))
    repo_access_cache.save_cache(
        tmp_path,
        {
            key: {"checked_at": datetime.now(timezone.utc).isoformat(), "digest": f"sha256:{digest_a}"},
        },
    )

    def fail_if_called(host, repo, tag):
        raise AssertionError("should have been served from the disk cache")

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", fail_if_called)

    result = libimagedigests.cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")

    assert result == (True, f"sha256:{digest_a}")


def testcached_tag_exists_writes_a_disk_entry_readable_by_repo_access_cache(libimagedigests, tmp_path, monkeypatch):
    digest_a = "a" * 64
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{digest_a}"))

    libimagedigests.cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")

    key = repo_access_cache.cache_key("registry", ("docker.io", "org/repo", "1.0.0"))
    disk = repo_access_cache.load_cache(tmp_path)
    assert key in disk
    assert disk[key]["digest"] == f"sha256:{digest_a}"
    assert repo_access_cache.cache_entry_is_fresh(disk[key], 30) is True


def testcached_tag_exists_ignores_a_stale_disk_entry(libimagedigests, tmp_path, monkeypatch):
    stale = datetime.now(timezone.utc) - timedelta(minutes=30 + 1)
    key = repo_access_cache.cache_key("registry", ("docker.io", "org/repo", "1.0.0"))
    repo_access_cache.save_cache(
        tmp_path,
        {
            key: {"checked_at": stale.isoformat(), "digest": f"sha256:{'a' * 64}"},
        },
    )

    calls = []

    def spy(host, repo, tag):
        calls.append(tag)
        return True, f"sha256:{'b' * 64}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)

    result = libimagedigests.cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")

    assert len(calls) == 1
    assert result == (True, f"sha256:{'b' * 64}")


def test_check_image_digests_and_find_sliding_pins_share_the_tag_exists_cache(libimagedigests, tmp_path, monkeypatch):
    """The actual redundancy this cache fixes: check_image_digests' own
    loop and find_sliding_pins (check_cve_diff's own candidate source)
    must not each independently re-query the registry for the same pin
    within one process — "CVE diff" lists "Image digests" as a
    prerequisite specifically so both run in the same invocation."""
    digest_a = "a" * 64
    (tmp_path / "values.yaml").write_text(
        (f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{digest_a}"\n'), encoding="utf-8"
    )
    calls = []

    def spy(host, repo, tag):
        calls.append(tag)
        return True, f"sha256:{digest_a}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)

    libimagedigests.check_image_digests(tmp_path)
    libimagedigests.find_sliding_pins(tmp_path)

    assert calls == ["1.0.0"]  # exactly one real lookup, shared by both callers
