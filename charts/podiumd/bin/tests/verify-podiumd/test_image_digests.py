"""parse_repo, resolve_pin_repo, scan_digest_pins, check_image_digests —
pure logic plus a mocked-registry integration test. No network access
needed: registry_tag_exists is monkeypatched wherever a live fetch would
otherwise happen."""
import io
import tarfile
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest
import yaml

import lib.repo_access_cache as repo_access_cache
from dep_helpers import make_dep


@pytest.fixture(autouse=True)
def _clear_tag_exists_cache(libimagedigests):
    """_cached_tag_exists' own in-process memoization (see its own
    docstring) lives in a module-level dict, and libimagedigests is a
    session-scoped fixture — without this, one test's cached (fake)
    registry_tag_exists result could silently leak into a LATER test
    that reuses the same (repository, version), even though that later
    test mocks registry_tag_exists completely differently."""
    libimagedigests._tag_exists_cache.clear()
    yield
    libimagedigests._tag_exists_cache.clear()


def make_tgz(charts_dir, name, version, values):
    """A minimal vendored <name>-<version>.tgz containing just
    <name>/values.yaml, for exercising the subchart-default-repository
    fallback without a real `helm pull`."""
    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    data = yaml.safe_dump(values).encode("utf-8")
    with tarfile.open(tgz_path, "w:gz") as tar:
        info = tarfile.TarInfo(name=f"{name}/values.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


def write_chart_yaml(chart_dir, deps):
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}), encoding="utf-8")



# --- parse_repo ---

def test_parse_repo_bare_docker_hub_official_image(libimagedigests):
    assert libimagedigests.parse_repo("python") == ("docker.io", "library/python")


def test_parse_repo_bare_docker_hub_namespaced(libimagedigests):
    assert libimagedigests.parse_repo("nginxinc/nginx-unprivileged") == ("docker.io", "nginxinc/nginx-unprivileged")


def test_parse_repo_explicit_host(libimagedigests):
    assert libimagedigests.parse_repo("ghcr.io/infonl/zaakafhandelcomponent") == ("ghcr.io", "infonl/zaakafhandelcomponent")


def test_parse_repo_explicit_docker_io_host(libimagedigests):
    assert libimagedigests.parse_repo("docker.io/alpine/k8s") == ("docker.io", "alpine/k8s")


def test_parse_repo_localhost(libimagedigests):
    assert libimagedigests.parse_repo("localhost/foo") == ("localhost", "foo")


# --- resolve_pin_repo ---

def test_resolve_pin_repo_active_sibling_key(libimagedigests):
    lines = [
        "    nginx:",
        "      repository: nginxinc/nginx-unprivileged",
        '      tag: "1.31.3@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 2, 6) == "nginxinc/nginx-unprivileged"


def test_resolve_pin_repo_active_sibling_key_with_comment_between(libimagedigests):
    lines = [
        "      initImage:",
        "        repository: python",
        "        # Digest-pinned to match docs/images/images-4.8.0.yaml",
        '        tag: "3.14-slim@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 3, 8) == "python"


def test_resolve_pin_repo_ref_comment_fallback(libimagedigests):
    lines = [
        "  opa:",
        "    # openpolicyagent/opa:1.17.1-static@sha256:aaaa",
        "    image:",
        "      #repository: openpolicyagent/opa",
        '      tag: "1.17.1-static@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 4, 6) == "openpolicyagent/opa"


def test_resolve_pin_repo_ref_comment_tolerates_stray_at(libimagedigests):
    lines = [
        "        # lachlanevenson/k8s-kubectl:@v1.25.4",
        "        image:",
        "          #repository:",
        "          tag: v1.25.4@sha256:aaaa",
    ]
    assert libimagedigests.resolve_pin_repo(lines, 3, 10) == "lachlanevenson/k8s-kubectl"


def test_resolve_pin_repo_commented_repository_key_fallback(libimagedigests):
    lines = [
        "    image:",
        "      #repository: maykinmedia/open-archiefbeheer",
        '      tag: "2.0.0@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 2, 6) == "maykinmedia/open-archiefbeheer"


def test_resolve_pin_repo_unresolved_returns_none(libimagedigests):
    lines = [
        "  image:",
        '    tag: "1.27.4@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 1, 4) is None


def test_resolve_pin_repo_stops_at_dedent_does_not_leak_across_blocks(libimagedigests):
    lines = [
        "otherBlock:",
        "  repository: should/not-be-used",
        "unrelated:",
        "  image:",
        '    tag: "1.0.0@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 4, 4) is None


def test_resolve_pin_repo_combines_split_registry_and_repository(libimagedigests):
    """redis-ha's actual style: registry: quay.io / repository: opstree/redis
    as two sibling keys, rather than one combined "repository:
    quay.io/opstree/redis" — must resolve to the same host/path a combined
    pin would, or the live lookup asks the wrong registry entirely."""
    lines = [
        "    image:",
        "      registry: quay.io",
        "      repository: opstree/redis",
        '      tag: "v8.6.6@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 3, 6) == "quay.io/opstree/redis"


def test_resolve_pin_repo_registry_key_order_does_not_matter(libimagedigests):
    lines = [
        "    image:",
        "      repository: opstree/redis",
        "      registry: quay.io",
        '      tag: "v8.6.6@sha256:aaaa"',
    ]
    assert libimagedigests.resolve_pin_repo(lines, 3, 6) == "quay.io/opstree/redis"


# --- find_sibling_registry ---

def test_find_sibling_registry_found_at_same_indent(libimagedigests):
    lines = ["    image:", "      registry: quay.io", "      repository: opstree/redis"]
    assert libimagedigests.find_sibling_registry(lines, 2, 6) == "quay.io"


def test_find_sibling_registry_none_when_absent(libimagedigests):
    lines = ["    image:", "      repository: org/repo"]
    assert libimagedigests.find_sibling_registry(lines, 1, 6) is None


def test_find_sibling_registry_stops_at_dedent(libimagedigests):
    lines = ["registry: should/not-be-used", "image:", "  repository: org/repo"]
    assert libimagedigests.find_sibling_registry(lines, 2, 2) is None


# --- scan_digest_pins ---

def test_scan_digest_pins_quoted_and_bare(libimagedigests):
    lines = [
        "  a:",
        "    repository: org/repo-a",
        '    tag: "1.0.0@sha256:' + "a" * 64 + '"',
        "  b:",
        "    repository: org/repo-b",
        "    tag: 2.0.0@sha256:" + "b" * 64,
    ]
    pins = libimagedigests.scan_digest_pins(lines)
    assert [(p["version"], p["digest"], p["repository"]) for p in pins] == [
        ("1.0.0", "a" * 64, "org/repo-a"),
        ("2.0.0", "b" * 64, "org/repo-b"),
    ]
    assert pins[0]["line"] == 3
    assert pins[1]["line"] == 6


def test_scan_digest_pins_ignores_non_digest_tags(libimagedigests):
    lines = ["  image:", "    tag: latest"]
    assert libimagedigests.scan_digest_pins(lines) == []


def test_scan_digest_pins_resolves_split_registry_style(libimagedigests):
    """scan_digest_pins itself only cares about the resolved repository,
    used for the live lookup (see resolve_pin_repo/find_sibling_registry) —
    a split "registry:"/"repository:" pin must resolve to the same
    combined host/path a single-key pin would."""
    lines = [
        "    image:",
        "      registry: quay.io",
        "      repository: opstree/redis",
        '      tag: "v8.6.6@sha256:' + "a" * 64 + '"',
    ]
    pins = libimagedigests.scan_digest_pins(lines)
    assert pins[0]["repository"] == "quay.io/opstree/redis"


def test_scan_digest_pins_combined_style(libimagedigests):
    lines = ["  image:", "    repository: org/repo", '    tag: "1.0.0@sha256:' + "a" * 64 + '"']
    pins = libimagedigests.scan_digest_pins(lines)
    assert pins[0]["repository"] == "org/repo"


# --- scan_version_pins ---
# Deliberately a SEPARATE scanner from scan_digest_pins (see VERSION_PIN_RE's
# own docstring) — verify-release-table-with-podiumd's own comparisons need
# it (release-table.csv never records digests at all), every other caller
# (update-image-version/verify-image-version/show-image-baseline-version)
# stays on scan_digest_pins, digest-required, completely untouched — see the
# "still digest-required" tests just above this section, all still passing
# unchanged.

def test_scan_version_pins_finds_bare_tag_with_no_digest(libimagedigests):
    """The exact real-world case that motivated this: podiumd-4.8.5 (this
    chart's own real, historical release_table baseline as of this
    writing) pinned zaakbrug/pabc/ita with plain, non-digest-pinned tags
    — scan_digest_pins is structurally blind to these (see
    test_scan_digest_pins_ignores_non_digest_tags just above), but a
    real, comparable version string is genuinely there."""
    lines = ["  image:", "    repository: wearefrank/zaakbrug", '    tag: "1.26.15"']
    pins = libimagedigests.scan_version_pins(lines)
    assert [(p["version"], p["digest"], p["repository"]) for p in pins] == [
        ("1.26.15", None, "wearefrank/zaakbrug"),
    ]


def test_scan_version_pins_still_finds_digest_pinned_tags(libimagedigests):
    """A real digest pin still works exactly as before — VERSION_PIN_RE is
    a strict superset of DIGEST_PIN_RE, never a replacement that could
    accidentally stop matching the digest-pinned case."""
    lines = [
        "  a:",
        "    repository: org/repo-a",
        '    tag: "1.0.0@sha256:' + "a" * 64 + '"',
        "  b:",
        "    repository: org/repo-b",
        "    tag: 2.0.0@sha256:" + "b" * 64,
    ]
    pins = libimagedigests.scan_version_pins(lines)
    assert [(p["version"], p["digest"], p["repository"]) for p in pins] == [
        ("1.0.0", "a" * 64, "org/repo-a"),
        ("2.0.0", "b" * 64, "org/repo-b"),
    ]


def test_scan_version_pins_unquoted_bare_tag(libimagedigests):
    lines = ["  image:", "    repository: org/repo", "    tag: 1.26.15"]
    pins = libimagedigests.scan_version_pins(lines)
    assert (pins[0]["version"], pins[0]["digest"]) == ("1.26.15", None)


def test_scan_version_pins_ignores_non_tag_lines(libimagedigests):
    assert libimagedigests.scan_version_pins(["  repository: org/repo", "  enabled: true"]) == []


# --- find_inconsistent_version_pins ---

def test_find_inconsistent_version_pins_flags_same_repo_different_versions(libimagedigests):
    lines = [
        "a:",
        "  image:",
        "    repository: curlimages/curl",
        f'    tag: "8.21.0@sha256:{"a" * 64}"',
        "b:",
        "  image:",
        "    repository: curlimages/curl",
        f'    tag: "8.20.0@sha256:{"b" * 64}"',
    ]
    pins = libimagedigests.scan_digest_pins(lines)
    drift = libimagedigests.find_inconsistent_version_pins(pins)
    assert drift == {"curlimages/curl": {
        "kind": "drift",
        "pins": [(("8.21.0", "a" * 64), [4]), (("8.20.0", "b" * 64), [8])],
    }}


def test_find_inconsistent_version_pins_flags_same_version_different_digest(libimagedigests):
    """The subtler case: both pins agree on the version string, but the
    digest has diverged — e.g. a sliding tag re-published upstream and
    refreshed at one spot but not the other. Invisible to a version-only
    comparison, since neither pin's version string changed at all. Still
    classified "drift" (not "duplicate") — the pins disagree, even though
    only the digest half of the pair differs."""
    lines = [
        "a:",
        "  image:",
        "    repository: curlimages/curl",
        f'    tag: "8.21.0@sha256:{"a" * 64}"',
        "b:",
        "  image:",
        "    repository: curlimages/curl",
        f'    tag: "8.21.0@sha256:{"b" * 64}"',
    ]
    pins = libimagedigests.scan_digest_pins(lines)
    drift = libimagedigests.find_inconsistent_version_pins(pins)
    assert drift == {"curlimages/curl": {
        "kind": "drift",
        "pins": [(("8.21.0", "a" * 64), [4]), (("8.21.0", "b" * 64), [8])],
    }}


def test_find_inconsistent_version_pins_flags_matching_pins_as_duplicate(libimagedigests):
    """The same repository pinned at the same version AND digest in two
    places — every pin agrees, so this is a "duplicate" (not "drift")
    finding: there's no legitimate reason not to use a shared YAML anchor
    here instead of hand-typing the same pin twice."""
    lines = [
        "a:",
        "  image:",
        "    repository: curlimages/curl",
        f'    tag: "8.21.0@sha256:{"a" * 64}"',
        "b:",
        "  image:",
        "    repository: curlimages/curl",
        f'    tag: "8.21.0@sha256:{"a" * 64}"',
    ]
    pins = libimagedigests.scan_digest_pins(lines)
    drift = libimagedigests.find_inconsistent_version_pins(pins)
    assert drift == {"curlimages/curl": {"kind": "duplicate", "pins": [(("8.21.0", "a" * 64), [4, 8])]}}


def test_find_inconsistent_version_pins_ignores_different_repositories(libimagedigests):
    """A shared basename across different orgs/paths is not the same
    image — must never be conflated, only an exact repository match
    counts."""
    lines = [
        "a:",
        "  image:",
        "    repository: orgone/tool",
        f'    tag: "1.0.0@sha256:{"a" * 64}"',
        "b:",
        "  image:",
        "    repository: orgtwo/tool",
        f'    tag: "2.0.0@sha256:{"b" * 64}"',
    ]
    pins = libimagedigests.scan_digest_pins(lines)
    assert libimagedigests.find_inconsistent_version_pins(pins) == {}


def test_find_inconsistent_version_pins_ignores_unresolved_repository(libimagedigests):
    lines = ["a:", "  image:", f'    tag: "1.0.0@sha256:{"a" * 64}"']
    pins = libimagedigests.scan_digest_pins(lines)
    assert libimagedigests.find_inconsistent_version_pins(pins) == {}


# --- _cached_tag_exists ---
#
# The shared, in-process memoization check_image_digests' own loop and
# find_sliding_pins both call through, so a --include=cve-diff run (which
# needs both) only pays for one real per-pin registry lookup, not two.

def test_cached_tag_exists_only_calls_registry_once_for_same_pin(libimagedigests, tmp_path, monkeypatch):
    calls = []

    def fake_registry_tag_exists(host, repo, tag):
        calls.append((host, repo, tag))
        return True, f"sha256:{'a' * 64}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", fake_registry_tag_exists)

    first = libimagedigests._cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")
    second = libimagedigests._cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")

    assert first == second == (True, f"sha256:{'a' * 64}")
    assert len(calls) == 1


def test_cached_tag_exists_different_repository_or_version_is_a_distinct_call(libimagedigests, tmp_path, monkeypatch):
    calls = []

    def fake_registry_tag_exists(host, repo, tag):
        calls.append(tag)
        return True, f"sha256:{'a' * 64}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", fake_registry_tag_exists)

    libimagedigests._cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")
    libimagedigests._cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "2.0.0")

    assert len(calls) == 2


def test_cached_tag_exists_does_not_cache_a_raised_exception(libimagedigests, tmp_path, monkeypatch):
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
        libimagedigests._cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")
    result = libimagedigests._cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")

    assert calls["n"] == 2
    assert result == (True, f"sha256:{'a' * 64}")


# --- _cached_tag_exists: disk tier (lib.repo_access_cache) ---
#
# Genuinely the SAME cache check_repo_access itself uses (same file, same
# cache_key/load_cache/save_cache/cache_entry_is_fresh functions, same
# TTL) -- an entry either one writes must be directly usable by the
# other, no format translation.

def test_cached_tag_exists_reads_a_fresh_disk_entry_without_a_network_call(
        libimagedigests, tmp_path, monkeypatch):
    digest_a = "a" * 64
    key = repo_access_cache.cache_key("registry", ("docker.io", "org/repo", "1.0.0"))
    repo_access_cache.save_cache(tmp_path, {
        key: {"checked_at": datetime.now(timezone.utc).isoformat(), "digest": f"sha256:{digest_a}"},
    })

    def fail_if_called(host, repo, tag):
        raise AssertionError("should have been served from the disk cache")

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", fail_if_called)

    result = libimagedigests._cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")

    assert result == (True, f"sha256:{digest_a}")


def test_cached_tag_exists_writes_a_disk_entry_readable_by_repo_access_cache(
        libimagedigests, tmp_path, monkeypatch):
    digest_a = "a" * 64
    monkeypatch.setattr(libimagedigests, "registry_tag_exists",
                         lambda host, repo, tag: (True, f"sha256:{digest_a}"))

    libimagedigests._cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")

    key = repo_access_cache.cache_key("registry", ("docker.io", "org/repo", "1.0.0"))
    disk = repo_access_cache.load_cache(tmp_path)
    assert key in disk
    assert disk[key]["digest"] == f"sha256:{digest_a}"
    assert repo_access_cache.cache_entry_is_fresh(disk[key]) is True


def test_cached_tag_exists_ignores_a_stale_disk_entry(libimagedigests, tmp_path, monkeypatch):
    stale = datetime.now(timezone.utc) - timedelta(minutes=repo_access_cache.REPO_ACCESS_CACHE_TTL_MINUTES + 1)
    key = repo_access_cache.cache_key("registry", ("docker.io", "org/repo", "1.0.0"))
    repo_access_cache.save_cache(tmp_path, {
        key: {"checked_at": stale.isoformat(), "digest": f"sha256:{'a' * 64}"},
    })

    calls = []

    def spy(host, repo, tag):
        calls.append(tag)
        return True, f"sha256:{'b' * 64}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)

    result = libimagedigests._cached_tag_exists(tmp_path, "org/repo", "docker.io", "org/repo", "1.0.0")

    assert len(calls) == 1
    assert result == (True, f"sha256:{'b' * 64}")


def test_check_image_digests_and_find_sliding_pins_share_the_tag_exists_cache(
        libimagedigests, tmp_path, monkeypatch):
    """The actual redundancy this cache fixes: check_image_digests' own
    loop and find_sliding_pins (check_cve_diff's own candidate source)
    must not each independently re-query the registry for the same pin
    within one process — "CVE diff" lists "Image digests" as a
    prerequisite specifically so both run in the same invocation."""
    digest_a = "a" * 64
    (tmp_path / "values.yaml").write_text((
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{digest_a}"\n'
    ), encoding="utf-8")
    calls = []

    def spy(host, repo, tag):
        calls.append(tag)
        return True, f"sha256:{digest_a}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)

    libimagedigests.check_image_digests(tmp_path)
    libimagedigests.find_sliding_pins(tmp_path)

    assert calls == ["1.0.0"]  # exactly one real lookup, shared by both callers


# --- check_image_digests (mocked registry) ---

def write_values(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


def test_check_image_digests_all_match(vp, libimagedigests, tmp_path, monkeypatch):
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'a' * 64}"))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert "1/1 matched" in detail


def test_check_image_digests_no_digest_header_is_unverifiable_not_matched(vp, libimagedigests, tmp_path,
                                                                          monkeypatch, capsys):
    """registry_tag_exists returns (True, None) when a 200 manifest response
    carried no Docker-Content-Digest header (some registries/proxies). The
    pin cannot be confirmed, so it must NOT count as matched — it goes in
    the same 'couldn't verify' bucket as an unreachable host."""
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (True, None))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True  # not a build failure, same as an unreachable host
    assert "0/1 matched" in detail
    assert "1 unverifiable" in detail
    assert "[UNVERIFIABLE]" in capsys.readouterr().out


def test_check_image_digests_reports_mismatch(vp, libimagedigests, tmp_path, monkeypatch, capsys):
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'b' * 64}"))
    monkeypatch.setattr(libimagedigests, "is_sliding_tag", lambda *a, **k: False)
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "1 stale" in detail
    out = capsys.readouterr().out
    assert "MISMATCH" in out
    assert "org/repo" in out
    assert "values.yaml:4" in out
    assert "fix-image-digests" in out
    assert "[1/1] checking docker.io/org/repo:1.0.0..." in out  # progress line, printed before every check


def test_check_image_digests_reports_missing_tag_as_fetch_error(vp, libimagedigests, tmp_path, monkeypatch, capsys):
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (False, None))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "fetch error" in detail
    out = capsys.readouterr().out
    assert "FETCH-ERR" in out
    assert "values.yaml:4" in out


def test_check_image_digests_retries_once_on_network_error_then_succeeds(vp, libimagedigests, tmp_path, monkeypatch):
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

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", flaky)
    ok, detail = vp.check_image_digests(tmp_path)
    assert calls["n"] == 2
    assert ok is True
    assert "1/1 matched" in detail


def test_check_image_digests_gives_up_after_one_retry(vp, libimagedigests, tmp_path, monkeypatch):
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(
        libimagedigests, "registry_tag_exists",
        lambda host, repo, tag: (_ for _ in ()).throw(urllib.error.URLError("down")),
    )
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "1 fetch error" in detail


def test_check_image_digests_dedupes_shared_repo_and_tag(vp, libimagedigests, tmp_path, monkeypatch):
    """The same repository+tag pinned at two places still only costs one
    registry fetch — but (since 2026-08-26) it's ALSO now a
    [DUPLICATE-PIN] failure in its own right (see
    test_check_image_digests_reports_duplicate_pin): the two concerns are
    independent, so both are exercised here."""
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

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False  # duplicate pin — see [DUPLICATE-PIN]
    assert calls == [("docker.io", "org/repo", "1.0.0")]  # fetched once, not twice
    assert "1/1 matched" in detail
    assert "1 duplicate pin(s)" in detail


def test_check_image_digests_skips_unresolved_repository(vp, libimagedigests, tmp_path, monkeypatch):
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    called = []
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda *a: called.append(a))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert called == []
    assert "0/0 matched" in detail


def test_check_image_digests_unresolved_line_names_the_file(vp, libimagedigests, tmp_path, monkeypatch, capsys):
    """A bare "line N" doesn't say which file N is in — prefix with
    values.yaml, same convention as check_duplicate_keys."""
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda *a: (_ for _ in ()).throw(AssertionError))
    vp.check_image_digests(tmp_path)
    out = capsys.readouterr().out
    assert "values.yaml:3: 1.0.0" in out


# --- check_image_digests: subchart-default repository fallback ---

def test_check_image_digests_falls_back_to_subchart_default_repository(vp, libimagedigests, tmp_path, monkeypatch):
    """openzaak/openformulieren-style pins: no repository in values.yaml at
    all, resolved instead from the vendored subchart's own default (the
    same one Helm merges in at render time)."""
    write_values(tmp_path, (
        "openzaak:\n"
        "  image:\n"
        f'    tag: "1.27.4@sha256:{"a" * 64}"\n'
    ))
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {"repository": "openzaak/open-zaak"}})

    called = []

    def spy(host, repo, tag):
        called.append((host, repo, tag))
        return True, f"sha256:{'a' * 64}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert called == [("docker.io", "openzaak/open-zaak", "1.27.4")]
    assert "1/1 matched" in detail


def test_check_image_digests_falls_back_via_alias(vp, libimagedigests, tmp_path, monkeypatch):
    write_values(tmp_path, (
        "openformulieren:\n"
        "  image:\n"
        f'    tag: "3.4.10@sha256:{"a" * 64}"\n'
    ))
    write_chart_yaml(tmp_path, [make_dep("openforms", "1.12.0", alias="openformulieren")])
    make_tgz(tmp_path / "charts", "openforms", "1.12.0", {"image": {"repository": "openformulieren/open-forms"}})
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'a' * 64}"))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert "1/1 matched" in detail


def test_check_image_digests_stays_unresolved_when_subchart_has_no_default_either(vp, libimagedigests, tmp_path):
    write_values(tmp_path, (
        "openzaak:\n"
        "  image:\n"
        f'    tag: "1.27.4@sha256:{"a" * 64}"\n'
    ))
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {}})  # subchart doesn't default one either
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert "0/0 matched" in detail


def test_check_image_digests_stays_unresolved_without_chart_yaml(vp, libimagedigests, tmp_path):
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert "0/0 matched" in detail


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
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (
        (True, f"sha256:{'c' * 64}") if repo == "nginxinc/nginx-unprivileged"
        else (True, f"sha256:{'b' * 64}")
    ))
    monkeypatch.setattr(libimagedigests, "is_sliding_tag",
                         lambda values_path, host, repo, version, live_digest: repo == "nginxinc/nginx-unprivileged")
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
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (
        (True, f"sha256:{'a' * 64}") if repo == "nginxinc/nginx-unprivileged"  # unchanged, matches
        else (True, f"sha256:{'c' * 64}")  # zac drifted — not sliding
    ))
    monkeypatch.setattr(libimagedigests, "is_sliding_tag",
                         lambda values_path, host, repo, version, live_digest: repo == "nginxinc/nginx-unprivileged")
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
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    calls = []

    def spy(host, repo, tag):
        calls.append(tag)
        return True, f"sha256:{'a' * 64}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert calls == ["1.0.0"]  # exactly one call, the tag check — no digest-liveness follow-up


def test_check_image_digests_sliding_with_digest_still_pullable_only_warns(
        vp, libimagedigests, tmp_path, monkeypatch, capsys):
    """The OLD pinned digest independently resolves upstream — the tag
    merely slid, nothing this repo actually deploys is at risk. Warns
    (via [SLIDING], not a failure) and never reports [DIGEST-GONE]."""
    digest_a = "a" * 64
    write_values(tmp_path, (
        "nginx:\n"
        "  image:\n"
        "    repository: nginxinc/nginx-unprivileged\n"
        f'    tag: "1.31.3@sha256:{digest_a}"\n'
    ))
    calls = []

    def spy(host, repo, tag):
        calls.append(tag)
        if tag == f"sha256:{digest_a}":
            return True, f"sha256:{digest_a}"  # the OLD digest still resolves
        return True, f"sha256:{'c' * 64}"  # the TAG now points elsewhere

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)
    monkeypatch.setattr(libimagedigests, "is_sliding_tag", lambda *a, **k: True)
    ok, detail = vp.check_image_digests(tmp_path)
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
    write_values(tmp_path, (
        "nginx:\n"
        "  image:\n"
        "    repository: nginxinc/nginx-unprivileged\n"
        f'    tag: "1.31.3@sha256:{digest_a}"\n'
    ))

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
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{digest_a}"\n'
    ))

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
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{digest_a}"\n'
    ))

    def spy(host, repo, tag):
        if tag == "1.0.0":
            raise urllib.error.URLError("tag check failed")
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
        vp, libimagedigests, tmp_path, monkeypatch, capsys):
    """A host in UNVERIFIABLE_HOSTS is skipped for the SECOND call too —
    no point attempting what's already known to fail anonymously."""
    write_values(tmp_path, (
        "pabc:\n"
        "  image:\n"
        "    repository: firewalled-registry.example.com/platform-autorisatie-beheer-component/pabc-api\n"
        f'    tag: "1.1.1@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(libimagedigests, "UNVERIFIABLE_HOSTS", {"firewalled-registry.example.com"})
    calls = []

    def spy(host, repo, tag):
        calls.append(tag)
        raise urllib.error.HTTPError("https://firewalled-registry.example.com/v2/...", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", spy)
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    # the tag check retries once on its own network error -- both attempts
    # are still just the TAG check; no digest-liveness follow-up at all.
    assert calls == ["1.1.1", "1.1.1"]
    out = capsys.readouterr().out
    assert "[DIGEST-GONE]" not in out


# --- check_image_digests: split registry:/repository: style resolution ---

def test_check_image_digests_split_style_pin_queries_the_correct_registry(vp, libimagedigests, tmp_path, monkeypatch):
    """Regression test for the actual bug: a split-style pin (redis-ha's
    real values.yaml shape) must resolve against ITS OWN registry (quay.io
    here), not silently fall back to docker.io."""
    write_values(tmp_path, (
        "redis-ha:\n"
        "  image:\n"
        "    registry: quay.io\n"
        "    repository: opstree/redis\n"
        f'    tag: "v8.6.6@sha256:{"a" * 64}"\n'
    ))
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
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: curlimages/curl\n"
        f'    tag: "8.21.0@sha256:{"a" * 64}"\n'
        "b:\n"
        "  image:\n"
        "    repository: curlimages/curl\n"
        f'    tag: "8.20.0@sha256:{"b" * 64}"\n'
    ))
    digests_by_tag = {"8.21.0": "a" * 64, "8.20.0": "b" * 64}
    monkeypatch.setattr(libimagedigests, "registry_tag_exists",
                         lambda host, repo, tag: (True, f"sha256:{digests_by_tag[tag]}"))
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
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: curlimages/curl\n"
        f'    tag: "8.21.0@sha256:{"a" * 64}"\n'
        "b:\n"
        "  image:\n"
        "    repository: curlimages/curl\n"
        f'    tag: "8.21.0@sha256:{"a" * 64}"\n'
    ))
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
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: curlimages/curl\n"
        f'    tag: "8.21.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'a' * 64}"))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert "0 duplicate pin(s)" in detail
    assert "0 version-drift finding" in detail


# --- check_image_digests: UNVERIFIABLE_HOSTS ---

def test_check_image_digests_unverifiable_host_does_not_fail_the_check(vp, libimagedigests, tmp_path, monkeypatch, capsys):
    """A registry this environment can never reach anonymously (see
    lib.registry.UNVERIFIABLE_HOSTS) must be reported distinctly from a
    genuine FETCH-ERR, and must not fail the check on its own — it can't
    succeed here regardless of whether the pin is actually correct.
    UNVERIFIABLE_HOSTS is empty by default (no such host currently known —
    see its docstring in lib/registry.py), so this injects a fake one
    rather than depending on any real, possibly-transient special case."""
    write_values(tmp_path, (
        "pabc:\n"
        "  image:\n"
        "    repository: firewalled-registry.example.com/platform-autorisatie-beheer-component/pabc-api\n"
        f'    tag: "1.1.1@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(libimagedigests, "UNVERIFIABLE_HOSTS", {"firewalled-registry.example.com"})
    monkeypatch.setattr(
        libimagedigests, "registry_tag_exists",
        lambda host, repo, tag: (_ for _ in ()).throw(urllib.error.HTTPError(
            "https://firewalled-registry.example.com/v2/...", 401, "Unauthorized", {}, None)),
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
    write_values(tmp_path, (
        "a:\n"
        "  image:\n"
        "    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(
        libimagedigests, "registry_tag_exists",
        lambda host, repo, tag: (_ for _ in ()).throw(urllib.error.HTTPError(
            "https://docker.io/v2/...", 401, "Unauthorized", {}, None)),
    )
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "1 fetch error" in detail
    assert "0 unverifiable" in detail
