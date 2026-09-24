"""check_image_digests — basic mocked-registry matching/mismatch/retry
scenarios, plus the subchart-default repository fallback (openzaak/
openformulieren-style pins with no repository of their own in
values.yaml). No network access needed: registry_tag_exists is
monkeypatched wherever a live fetch would otherwise happen."""

import io
import tarfile
import urllib.error

from pathlib import Path
from types import ModuleType

import pytest
import yaml

from dep_helpers import make_dep


@pytest.fixture(autouse=True)
def _clear_tag_exists_cache(libimagedigests: ModuleType):
    """cached_tag_exists' own in-process memoization (see its own
    docstring) lives in a module-level dict, and libimagedigests is a
    session-scoped fixture — without this, one test's cached (fake)
    registry_tag_exists result could silently leak into a LATER test
    that reuses the same (repository, version), even though that later
    test mocks registry_tag_exists completely differently."""
    libimagedigests.clear_tag_exists_cache()
    yield
    libimagedigests.clear_tag_exists_cache()


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


# --- check_image_digests (mocked registry) ---


def write_values(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


def test_check_image_digests_all_match(
    vp: ModuleType, libimagedigests: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    write_values(tmp_path, (f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{"a" * 64}"\n'))
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'a' * 64}"))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert "1/1 matched" in detail


def test_check_image_digests_no_digest_header_is_unverifiable_not_matched(
    vp: ModuleType,
    libimagedigests: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """registry_tag_exists returns (True, None) when a 200 manifest response
    carried no Docker-Content-Digest header (some registries/proxies). The
    pin cannot be confirmed, so it must NOT count as matched — it goes in
    the same 'couldn't verify' bucket as an unreachable host."""
    write_values(tmp_path, (f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{"a" * 64}"\n'))
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (True, None))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True  # not a build failure, same as an unreachable host
    assert "0/1 matched" in detail
    assert "1 unverifiable" in detail
    assert "[UNVERIFIABLE]" in capsys.readouterr().out


def test_check_image_digests_reports_mismatch(
    vp: ModuleType,
    libimagedigests: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_values(tmp_path, (f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{"a" * 64}"\n'))
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


def test_check_image_digests_reports_missing_tag_as_fetch_error(
    vp: ModuleType,
    libimagedigests: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_values(tmp_path, (f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{"a" * 64}"\n'))
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (False, None))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "fetch error" in detail
    out = capsys.readouterr().out
    assert "FETCH-ERR" in out
    assert "values.yaml:4" in out


def test_check_image_digests_retries_once_on_network_error_then_succeeds(
    vp: ModuleType, libimagedigests: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    write_values(tmp_path, (f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{"a" * 64}"\n'))
    calls = {"n": 0}

    def flaky(host, repo, tag):
        calls["n"] += 1
        if calls["n"] == 1:
            msg = "temporary failure"
            raise urllib.error.URLError(msg)
        return True, f"sha256:{'a' * 64}"

    monkeypatch.setattr(libimagedigests, "registry_tag_exists", flaky)
    ok, detail = vp.check_image_digests(tmp_path)
    assert calls["n"] == 2
    assert ok is True
    assert "1/1 matched" in detail


def test_check_image_digests_gives_up_after_one_retry(
    vp: ModuleType, libimagedigests: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    write_values(tmp_path, (f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{"a" * 64}"\n'))
    monkeypatch.setattr(
        libimagedigests,
        "registry_tag_exists",
        lambda host, repo, tag: (_ for _ in ()).throw(urllib.error.URLError("down")),
    )
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is False
    assert "1 fetch error" in detail


def test_check_image_digests_dedupes_shared_repo_and_tag(
    vp: ModuleType, libimagedigests: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The same repository+tag pinned at two places still only costs one
    registry fetch — but (since 2026-08-26) it's ALSO now a
    [DUPLICATE-PIN] failure in its own right (see
    test_check_image_digests_reports_duplicate_pin): the two concerns are
    independent, so both are exercised here."""
    write_values(
        tmp_path,
        (
            "a:\n"
            "  image:\n"
            "    repository: org/repo\n"
            f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
            "b:\n"
            "  image:\n"
            "    repository: org/repo\n"
            f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
        ),
    )
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


def test_check_image_digests_skips_unresolved_repository(
    vp: ModuleType, libimagedigests: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    write_values(tmp_path, (f'a:\n  image:\n    tag: "1.0.0@sha256:{"a" * 64}"\n'))
    called = []
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda *a: called.append(a))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert called == []
    assert "0/0 matched" in detail


def test_check_image_digests_unresolved_line_names_the_file(
    vp: ModuleType,
    libimagedigests: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A bare "line N" doesn't say which file N is in — prefix with
    values.yaml, same convention as check_duplicate_keys."""
    write_values(tmp_path, (f'a:\n  image:\n    tag: "1.0.0@sha256:{"a" * 64}"\n'))
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda *a: (_ for _ in ()).throw(AssertionError))
    vp.check_image_digests(tmp_path)
    out = capsys.readouterr().out
    assert "values.yaml:3: 1.0.0" in out


# --- check_image_digests: subchart-default repository fallback ---


def test_check_image_digests_falls_back_to_subchart_default_repository(
    vp: ModuleType, libimagedigests: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """openzaak/openformulieren-style pins: no repository in values.yaml at
    all, resolved instead from the vendored subchart's own default (the
    same one Helm merges in at render time)."""
    write_values(tmp_path, (f'openzaak:\n  image:\n    tag: "1.27.4@sha256:{"a" * 64}"\n'))
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


def test_check_image_digests_falls_back_via_alias(
    vp: ModuleType, libimagedigests: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    write_values(tmp_path, (f'openformulieren:\n  image:\n    tag: "3.4.10@sha256:{"a" * 64}"\n'))
    write_chart_yaml(tmp_path, [make_dep("openforms", "1.12.0", alias="openformulieren")])
    make_tgz(tmp_path / "charts", "openforms", "1.12.0", {"image": {"repository": "openformulieren/open-forms"}})
    monkeypatch.setattr(libimagedigests, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'a' * 64}"))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert "1/1 matched" in detail


def test_check_image_digests_stays_unresolved_when_subchart_has_no_default_either(
    vp: ModuleType, libimagedigests: ModuleType, tmp_path: Path
):
    write_values(tmp_path, (f'openzaak:\n  image:\n    tag: "1.27.4@sha256:{"a" * 64}"\n'))
    write_chart_yaml(tmp_path, [make_dep("openzaak", "1.14.2")])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {}})  # subchart doesn't default one either
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert "0/0 matched" in detail


def test_check_image_digests_stays_unresolved_without_chart_yaml(
    vp: ModuleType, libimagedigests: ModuleType, tmp_path: Path
):
    write_values(tmp_path, (f'a:\n  image:\n    tag: "1.0.0@sha256:{"a" * 64}"\n'))
    ok, detail = vp.check_image_digests(tmp_path)
    assert ok is True
    assert "0/0 matched" in detail
