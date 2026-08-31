"""parse_repo, resolve_pin_repo, scan_digest_pins, check_image_digests —
pure logic plus a mocked-registry integration test. No network access
needed: registry_tag_exists is monkeypatched wherever a live fetch would
otherwise happen."""
import io
import tarfile
import urllib.error

import yaml

from dep_helpers import make_dep


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


def test_check_image_digests_sliding_drift_fails(vp, libimagedigests, tmp_path, monkeypatch, capsys):
    """A tag known to slide drifting is routine, expected drift -- but the
    pin is still stale, so it must fail the check like any other stale
    pin (just labeled/reported differently, pointing at --all)."""
    write_values(tmp_path, TWO_IMAGES_VALUES)
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (
        (True, f"sha256:{'c' * 64}") if repo == "nginxinc/nginx-unprivileged"
        else (True, f"sha256:{'b' * 64}")
    ))
    monkeypatch.setattr(libimagedigests, "is_sliding_tag",
                         lambda values_path, host, repo, version, live_digest: repo == "nginxinc/nginx-unprivileged")
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "1 sliding" in detail
    assert "0 stale" in detail
    out = capsys.readouterr().out
    assert "[SLIDING  ]" in out
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
