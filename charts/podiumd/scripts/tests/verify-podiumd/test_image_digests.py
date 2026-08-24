"""parse_repo, resolve_pin_repo, scan_digest_pins, check_image_digests —
pure logic plus a mocked-registry integration test. No network access
needed: registry_tag_exists is monkeypatched wherever a live fetch would
otherwise happen."""
import io
import tarfile
import urllib.error

import yaml

from conftest import make_dep


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
    assert "line" in out.lower() or "lines" in out
    assert "set-image-digests.py" in out


def test_check_image_digests_reports_missing_tag_as_fetch_error(vp, libimagedigests, tmp_path, monkeypatch):
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
    assert ok is True
    assert calls == [("docker.io", "org/repo", "1.0.0")]  # fetched once, not twice
    assert "1/1 matched" in detail


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


def test_check_image_digests_sliding_drift_passes(vp, libimagedigests, tmp_path, monkeypatch, capsys):
    """A tag known to slide drifting must not fail the check — it's
    expected, routine drift, not a pin bug."""
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
