"""parse_repo, resolve_pin_repo, scan_digest_pins, find_stale_digests, main —
pure logic plus a mocked-registry integration test. No network access
needed: registry_tag_exists is monkeypatched wherever a live fetch would
otherwise happen."""
import io
import subprocess
import tarfile
import urllib.error

import pytest
import yaml


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

def test_parse_repo_bare_docker_hub_official_image(sid):
    assert sid.parse_repo("python") == ("docker.io", "library/python")


def test_parse_repo_bare_docker_hub_namespaced(sid):
    assert sid.parse_repo("nginxinc/nginx-unprivileged") == ("docker.io", "nginxinc/nginx-unprivileged")


def test_parse_repo_explicit_host(sid):
    assert sid.parse_repo("ghcr.io/infonl/zaakafhandelcomponent") == ("ghcr.io", "infonl/zaakafhandelcomponent")


# --- scan_digest_pins ---
# (resolve_pin_repo, the function scan_digest_pins itself calls to resolve
# each pin's repository, now lives in lib.image_digests -- deduped there
# since it already handled split "registry:"/"repository:" style pins
# (see find_sibling_registry) that this script's own former copy didn't.
# Its own dedicated tests are tests/verify-podiumd/test_image_digests.py's;
# no need to duplicate them here.)

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

def test_find_stale_digests_reports_mismatch(sid, tmp_path, monkeypatch):
    lines = [
        "a:",
        "  image:",
        "    repository: org/repo",
        f'    tag: "1.0.0@sha256:{"a" * 64}"',
    ]
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'b' * 64}"))
    monkeypatch.setattr(sid, "is_sliding_tag", lambda *a, **k: False)
    stale, unresolved, fetch_errors = sid.find_stale_digests(lines, tmp_path / "values.yaml")
    assert unresolved == []
    assert fetch_errors == []
    assert len(stale) == 1
    repository, version, old_digest, new_digest, pin_lines, sliding = stale[0]
    assert (repository, version, old_digest, new_digest, pin_lines, sliding) == (
        "org/repo", "1.0.0", "a" * 64, f"sha256:{'b' * 64}", [4], False
    )


def test_find_stale_digests_no_change_when_matching(sid, tmp_path, monkeypatch):
    lines = ["a:", "  image:", "    repository: org/repo", f'    tag: "1.0.0@sha256:{"a" * 64}"']
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'a' * 64}"))
    stale, unresolved, fetch_errors = sid.find_stale_digests(lines, tmp_path / "values.yaml")
    assert stale == [] and unresolved == [] and fetch_errors == []


def test_find_stale_digests_records_unresolved(sid, tmp_path):
    lines = ["a:", "  image:", f'    tag: "1.0.0@sha256:{"a" * 64}"']
    stale, unresolved, fetch_errors = sid.find_stale_digests(lines, tmp_path / "values.yaml")
    assert stale == [] and fetch_errors == []
    assert len(unresolved) == 1 and unresolved[0]["line"] == 3


# --- find_stale_digests: subchart-default repository fallback ---

def test_find_stale_digests_falls_back_to_subchart_default_repository(sid, tmp_path, monkeypatch):
    """openzaak/openformulieren-style pins: no repository in values.yaml at
    all, resolved instead from the vendored subchart's own default (the
    same one Helm merges in at render time)."""
    lines = ["openzaak:", "  image:", f'    tag: "1.27.4@sha256:{"a" * 64}"']
    write_chart_yaml(tmp_path, [{"name": "openzaak", "version": "1.14.2", "repository": "@example"}])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {"repository": "openzaak/open-zaak"}})

    called = []

    def spy(host, repo, tag):
        called.append((host, repo, tag))
        return True, f"sha256:{'a' * 64}"

    monkeypatch.setattr(sid, "registry_tag_exists", spy)
    stale, unresolved, fetch_errors = sid.find_stale_digests(lines, tmp_path / "values.yaml")
    assert unresolved == [] and stale == [] and fetch_errors == []
    assert called == [("docker.io", "openzaak/open-zaak", "1.27.4")]


def test_find_stale_digests_stays_unresolved_when_subchart_has_no_default_either(sid, tmp_path, monkeypatch):
    lines = ["openzaak:", "  image:", f'    tag: "1.27.4@sha256:{"a" * 64}"']
    write_chart_yaml(tmp_path, [{"name": "openzaak", "version": "1.14.2", "repository": "@example"}])
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {}})  # subchart doesn't default one either

    calls = []
    monkeypatch.setattr(sid, "ensure_repos_configured", lambda: calls.append("ensure") or (True, "ok"))
    monkeypatch.setattr(sid, "vendor_dependencies", lambda cd: calls.append("vendor") or (True, "ok"))

    stale, unresolved, fetch_errors = sid.find_stale_digests(lines, tmp_path / "values.yaml")
    assert stale == [] and fetch_errors == []
    assert len(unresolved) == 1
    assert calls == []  # .tgz already present -> nothing to gain from re-vendoring, never triggered


def test_find_stale_digests_vendors_dependencies_when_tgz_missing(sid, tmp_path, monkeypatch):
    """openzaak-style pin: matching Chart.yaml dependency, but its .tgz
    isn't vendored at all yet — worth a real re-vendor, unlike the "already
    vendored, subchart just doesn't default one" case above."""
    lines = ["openzaak:", "  image:", f'    tag: "1.27.4@sha256:{"a" * 64}"']
    write_chart_yaml(tmp_path, [{"name": "openzaak", "version": "1.14.2", "repository": "@example"}])
    # no .tgz vendored at all yet

    calls = []

    def fake_ensure_repos_configured():
        calls.append("ensure")
        return True, "ok"

    def fake_vendor_dependencies(chart_dir):
        calls.append("vendor")
        make_tgz(chart_dir / "charts", "openzaak", "1.14.2", {"image": {"repository": "openzaak/open-zaak"}})
        return True, "1 dependencies bundled"

    monkeypatch.setattr(sid, "ensure_repos_configured", fake_ensure_repos_configured)
    monkeypatch.setattr(sid, "vendor_dependencies", fake_vendor_dependencies)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'a' * 64}"))

    stale, unresolved, fetch_errors = sid.find_stale_digests(lines, tmp_path / "values.yaml")
    assert calls == ["ensure", "vendor"]
    assert unresolved == []
    assert stale == [] and fetch_errors == []


def test_find_stale_digests_warns_and_stays_unresolved_when_repos_configuration_fails(sid, tmp_path, monkeypatch, capsys):
    lines = ["openzaak:", "  image:", f'    tag: "1.27.4@sha256:{"a" * 64}"']
    write_chart_yaml(tmp_path, [{"name": "openzaak", "version": "1.14.2", "repository": "@example"}])

    def fail_if_called(*args, **kwargs):
        raise AssertionError("vendor_dependencies must never run when ensure_repos_configured failed")

    monkeypatch.setattr(sid, "ensure_repos_configured", lambda: (False, "helm repo add zac failed: network unreachable"))
    monkeypatch.setattr(sid, "vendor_dependencies", fail_if_called)

    stale, unresolved, fetch_errors = sid.find_stale_digests(lines, tmp_path / "values.yaml")
    assert len(unresolved) == 1
    assert stale == [] and fetch_errors == []
    err = capsys.readouterr().err
    assert "network unreachable" in err
    assert "will stay unresolved" in err


def test_find_stale_digests_warns_and_stays_unresolved_when_vendoring_fails(sid, tmp_path, monkeypatch, capsys):
    lines = ["openzaak:", "  image:", f'    tag: "1.27.4@sha256:{"a" * 64}"']
    write_chart_yaml(tmp_path, [{"name": "openzaak", "version": "1.14.2", "repository": "@example"}])

    monkeypatch.setattr(sid, "ensure_repos_configured", lambda: (True, "ok"))
    monkeypatch.setattr(sid, "vendor_dependencies", lambda cd: (False, "helm dependency update failed"))

    stale, unresolved, fetch_errors = sid.find_stale_digests(lines, tmp_path / "values.yaml")
    assert len(unresolved) == 1
    err = capsys.readouterr().err
    assert "helm dependency update failed" in err


def test_find_stale_digests_never_vendors_when_no_matching_dependency(sid, tmp_path, monkeypatch):
    """A component with no Chart.yaml dependency at all (e.g. a values.yaml
    key that isn't a subchart) can never be resolved by vendoring — must
    not trigger the (real, network-touching) re-vendor path."""
    lines = ["a:", "  image:", f'    tag: "1.0.0@sha256:{"a" * 64}"']
    write_chart_yaml(tmp_path, [])  # no dependencies at all

    def fail_if_called(*args, **kwargs):
        raise AssertionError("vendoring must never be attempted for an unmatched component")

    monkeypatch.setattr(sid, "ensure_repos_configured", fail_if_called)
    monkeypatch.setattr(sid, "vendor_dependencies", fail_if_called)

    stale, unresolved, fetch_errors = sid.find_stale_digests(lines, tmp_path / "values.yaml")
    assert len(unresolved) == 1


def test_find_stale_digests_retries_once_then_gives_up(sid, tmp_path, monkeypatch):
    lines = ["a:", "  image:", "    repository: org/repo", f'    tag: "1.0.0@sha256:{"a" * 64}"']
    monkeypatch.setattr(
        sid, "registry_tag_exists",
        lambda host, repo, tag: (_ for _ in ()).throw(urllib.error.URLError("down")),
    )
    stale, unresolved, fetch_errors = sid.find_stale_digests(lines, tmp_path / "values.yaml")
    assert stale == [] and unresolved == []
    assert len(fetch_errors) == 1 and fetch_errors[0][0] == "org/repo"


def test_find_stale_digests_dedupes_shared_repo_and_tag(sid, tmp_path, monkeypatch):
    lines = [
        "a:", "  image:", "    repository: org/repo", f'    tag: "1.0.0@sha256:{"a" * 64}"',
        "b:", "  image:", "    repository: org/repo", f'    tag: "1.0.0@sha256:{"a" * 64}"',
    ]
    calls = []

    def spy(host, repo, tag):
        calls.append((host, repo, tag))
        return True, f"sha256:{'b' * 64}"

    monkeypatch.setattr(sid, "registry_tag_exists", spy)
    monkeypatch.setattr(sid, "is_sliding_tag", lambda *a, **k: False)
    stale, unresolved, fetch_errors = sid.find_stale_digests(lines, tmp_path / "values.yaml")
    assert calls == [("docker.io", "org/repo", "1.0.0")]
    assert len(stale) == 1
    assert stale[0][4] == [4, 8]  # both pin lines share the one stale digest


def test_find_stale_digests_marks_sliding_from_is_sliding_tag(sid, tmp_path, monkeypatch):
    """find_stale_digests just threads is_sliding_tag's verdict through into
    the returned tuple — the classification logic itself is lib.registry's
    job and is tested there."""
    lines = ["a:", "  image:", "    repository: org/repo", f'    tag: "1.0.0@sha256:{"a" * 64}"']
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'b' * 64}"))
    monkeypatch.setattr(sid, "is_sliding_tag", lambda *a, **k: True)
    stale, unresolved, fetch_errors = sid.find_stale_digests(lines, tmp_path / "values.yaml")
    assert stale[0][5] is True


def test_find_stale_digests_calls_is_sliding_tag_with_live_digest(sid, tmp_path, monkeypatch):
    lines = ["a:", "  image:", "    repository: org/repo", f'    tag: "1.0.0@sha256:{"a" * 64}"']
    values_path = tmp_path / "values.yaml"
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'b' * 64}"))
    calls = []

    def spy(vp, host, repo, version, live_digest):
        calls.append((vp, host, repo, version, live_digest))
        return False

    monkeypatch.setattr(sid, "is_sliding_tag", spy)
    sid.find_stale_digests(lines, values_path)
    assert calls == [(values_path, "docker.io", "org/repo", "1.0.0", f"sha256:{'b' * 64}")]


# --- main() integration ---

def write_values(path, text):
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(sid, monkeypatch, capsys, flag):
    monkeypatch.setattr("sys.argv", ["fix-image-digests", flag])
    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == sid.__doc__ + "\n"


def test_main_dry_run_does_not_write(sid, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    original = "a:\n  image:\n    repository: org/repo\n" f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    write_values(values_path, original)
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'b' * 64}"))
    monkeypatch.setattr(sid, "is_sliding_tag", lambda *a, **k: False)
    monkeypatch.setattr("sys.argv", ["fix-image-digests", "--dry-run"])

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
    monkeypatch.setattr(sid, "is_sliding_tag", lambda *a, **k: False)
    monkeypatch.setattr("sys.argv", ["fix-image-digests"])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 0
    updated = values_path.read_text(encoding="utf-8")
    assert old_digest not in updated
    assert f'tag: "1.0.0@sha256:{new_digest}"' in updated


def test_main_invokes_fix_helm_doc_after_a_real_write(sid, tmp_path, monkeypatch, capsys):
    values_path = tmp_path / "values.yaml"
    write_values(values_path, f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{"a" * 64}"\n')
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'b' * 64}"))
    monkeypatch.setattr(sid, "is_sliding_tag", lambda *a, **k: False)
    monkeypatch.setattr("sys.argv", ["fix-image-digests"])
    calls = []
    monkeypatch.setattr(sid, "run_script",
                         lambda cmd, *a, **k: (calls.append(cmd), subprocess.CompletedProcess(cmd, 0))[1])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()

    assert exc_info.value.code == 0
    assert len(calls) == 1
    assert calls[0] == [sid.sys.executable, str(sid.FIX_HELM_DOC_SCRIPT)]
    assert "fix-helm-doc" in capsys.readouterr().out


def test_main_dry_run_does_not_invoke_fix_helm_doc(sid, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    write_values(values_path, f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{"a" * 64}"\n')
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'b' * 64}"))
    monkeypatch.setattr(sid, "is_sliding_tag", lambda *a, **k: False)
    monkeypatch.setattr("sys.argv", ["fix-image-digests", "--dry-run"])
    calls = []
    monkeypatch.setattr(sid, "run_script", lambda cmd, *a, **k: calls.append(cmd))

    with pytest.raises(SystemExit):
        sid.main()

    assert calls == []


def test_main_nothing_stale_does_not_invoke_fix_helm_doc(sid, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    digest = "a" * 64
    write_values(values_path, f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{digest}"\n')
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{digest}"))
    monkeypatch.setattr(sid, "is_sliding_tag", lambda *a, **k: False)
    monkeypatch.setattr("sys.argv", ["fix-image-digests"])
    calls = []
    monkeypatch.setattr(sid, "run_script", lambda cmd, *a, **k: calls.append(cmd))

    with pytest.raises(SystemExit):
        sid.main()

    assert calls == []


def test_main_propagates_fix_helm_doc_failure_exit_code(sid, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    write_values(values_path, f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{"a" * 64}"\n')
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'b' * 64}"))
    monkeypatch.setattr(sid, "is_sliding_tag", lambda *a, **k: False)
    monkeypatch.setattr("sys.argv", ["fix-image-digests"])
    monkeypatch.setattr(sid, "run_script", lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 1))

    with pytest.raises(SystemExit) as exc_info:
        sid.main()

    assert exc_info.value.code == 1


def test_main_stale_digest_report_names_the_file(sid, tmp_path, monkeypatch, capsys):
    """A bare "lines: N" doesn't say which file N is in — prefix with
    values.yaml, same convention as check_image_digests/check_duplicate_keys."""
    values_path = tmp_path / "values.yaml"
    old_digest = "a" * 64
    new_digest = "b" * 64
    write_values(values_path, f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{old_digest}"\n')
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{new_digest}"))
    monkeypatch.setattr(sid, "is_sliding_tag", lambda *a, **k: False)
    monkeypatch.setattr("sys.argv", ["fix-image-digests"])

    with pytest.raises(SystemExit):
        sid.main()
    out = capsys.readouterr().out
    assert "lines: values.yaml:4" in out


def test_main_unresolved_report_names_the_file(sid, tmp_path, monkeypatch, capsys):
    values_path = tmp_path / "values.yaml"
    write_values(values_path, 'a:\n  image:\n    tag: "1.0.0@sha256:' + "a" * 64 + '"\n')
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr("sys.argv", ["fix-image-digests"])

    with pytest.raises(SystemExit):
        sid.main()
    out = capsys.readouterr().out
    assert "values.yaml:3: 1.0.0" in out


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
    monkeypatch.setattr(sid, "is_sliding_tag", lambda *a, **k: False)
    monkeypatch.setattr("sys.argv", ["fix-image-digests"])

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
    monkeypatch.setattr("sys.argv", ["fix-image-digests"])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 1


def test_main_exits_zero_when_nothing_stale(sid, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    write_values(values_path, f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{"a" * 64}"\n')
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (True, f"sha256:{'a' * 64}"))
    monkeypatch.setattr("sys.argv", ["fix-image-digests"])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 0


# --- main(): sliding pins are refreshed by default, same as any other ---

def write_two_image_values(path, nginx_digest, zac_digest):
    write_values(path, (
        "nginx:\n"
        "  image:\n"
        "    repository: nginxinc/nginx-unprivileged\n"
        f'    tag: "1.31.3@sha256:{nginx_digest}"\n'
        "zac:\n"
        "  image:\n"
        "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
        f'    tag: "5.1.0@sha256:{zac_digest}"\n'
    ))


def mock_is_sliding_tag_by_repo(monkeypatch, sid, sliding_repos):
    monkeypatch.setattr(sid, "is_sliding_tag",
                         lambda values_path, host, repo, version, live_digest: repo in sliding_repos)


def test_main_default_updates_sliding_and_pinned_alike(sid, tmp_path, monkeypatch, capsys):
    """verify-podiumd's own check fails on a sliding mismatch the same
    as a pinned one, so there's no reason for this tool to leave a sliding
    pin unfixed by default -- both get rewritten in the same run, the
    sliding one just gets the "(sliding)" label in the report."""
    values_path = tmp_path / "values.yaml"
    old_nginx, new_nginx = "a" * 64, "c" * 64
    old_zac, new_zac = "b" * 64, "d" * 64
    write_two_image_values(values_path, old_nginx, old_zac)
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (
        (True, f"sha256:{new_nginx}") if repo == "nginxinc/nginx-unprivileged"
        else (True, f"sha256:{new_zac}")
    ))
    mock_is_sliding_tag_by_repo(monkeypatch, sid, {"nginxinc/nginx-unprivileged"})
    monkeypatch.setattr("sys.argv", ["fix-image-digests"])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 0
    updated = values_path.read_text(encoding="utf-8")
    assert old_nginx not in updated and new_nginx in updated  # sliding pin updated too
    assert old_zac not in updated and new_zac in updated
    out = capsys.readouterr().out
    assert "nginxinc/nginx-unprivileged:1.31.3  (sliding)" in out


# --- main(): <key> <basename> scopes to one image ---

def test_main_target_updates_sliding_pin(sid, tmp_path, monkeypatch):
    """Naming the image explicitly still works when it happens to be
    sliding -- no different from the default, unscoped behavior."""
    values_path = tmp_path / "values.yaml"
    old_nginx, new_nginx = "a" * 64, "c" * 64
    zac_digest = "b" * 64
    write_two_image_values(values_path, old_nginx, zac_digest)
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (
        (True, f"sha256:{new_nginx}") if repo == "nginxinc/nginx-unprivileged"
        else (True, f"sha256:{zac_digest}")
    ))
    mock_is_sliding_tag_by_repo(monkeypatch, sid, {"nginxinc/nginx-unprivileged"})
    monkeypatch.setattr("sys.argv", ["fix-image-digests", "nginx", "nginx-unprivileged"])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 0
    updated = values_path.read_text(encoding="utf-8")
    assert old_nginx not in updated
    assert new_nginx in updated


def test_main_target_leaves_other_stale_pins_untouched(sid, tmp_path, monkeypatch):
    """Both images drifted, but only the named one is refreshed -- the
    other stays exactly as it was, not silently swept in."""
    values_path = tmp_path / "values.yaml"
    old_nginx, new_nginx = "a" * 64, "c" * 64
    old_zac, new_zac = "b" * 64, "d" * 64
    write_two_image_values(values_path, old_nginx, old_zac)
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (
        (True, f"sha256:{new_nginx}") if repo == "nginxinc/nginx-unprivileged"
        else (True, f"sha256:{new_zac}")
    ))
    mock_is_sliding_tag_by_repo(monkeypatch, sid, set())
    monkeypatch.setattr("sys.argv", ["fix-image-digests", "nginx", "nginx-unprivileged"])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 0
    updated = values_path.read_text(encoding="utf-8")
    assert new_nginx in updated
    assert old_zac in updated and new_zac not in updated


def test_main_target_no_stale_digest_reports_nothing_to_do(sid, tmp_path, monkeypatch, capsys):
    values_path = tmp_path / "values.yaml"
    nginx_digest = "a" * 64
    zac_digest = "b" * 64
    write_two_image_values(values_path, nginx_digest, zac_digest)
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (
        (True, f"sha256:{nginx_digest}") if repo == "nginxinc/nginx-unprivileged"
        else (True, f"sha256:{zac_digest}")
    ))
    mock_is_sliding_tag_by_repo(monkeypatch, sid, set())
    monkeypatch.setattr("sys.argv", ["fix-image-digests", "nginx", "nginx-unprivileged"])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "'nginx' 'nginx-unprivileged' has no stale digest to update — nothing to do." in out


def test_main_target_resolves_given_key_and_basename(sid, tmp_path, monkeypatch, capsys):
    """<key> "zac" scopes the search to that component's own values.yaml
    subtree, where <basename> "zaakafhandelcomponent" is pinned."""
    values_path = tmp_path / "values.yaml"
    old_nginx = "a" * 64
    old_zac, new_zac = "b" * 64, "d" * 64
    write_two_image_values(values_path, old_nginx, old_zac)
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr(sid, "registry_tag_exists", lambda host, repo, tag: (
        (True, f"sha256:{old_nginx}") if repo == "nginxinc/nginx-unprivileged"
        else (True, f"sha256:{new_zac}")
    ))
    mock_is_sliding_tag_by_repo(monkeypatch, sid, set())
    monkeypatch.setattr("sys.argv", ["fix-image-digests", "zac", "zaakafhandelcomponent"])

    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 0
    updated = values_path.read_text(encoding="utf-8")
    assert old_zac not in updated and new_zac in updated
    assert old_nginx in updated  # untouched -- not the named target


def test_main_unknown_target_raises(sid, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    write_two_image_values(values_path, "a" * 64, "b" * 64)
    monkeypatch.setattr(sid, "VALUES_PATH", values_path)
    monkeypatch.setattr("sys.argv", ["fix-image-digests", "nginx", "totally-unknown"])

    with pytest.raises(SystemExit, match="no image pin with basename 'totally-unknown' found under 'nginx'"):
        sid.main()


def test_main_more_than_two_targets_raises(sid, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["fix-image-digests", "nginx", "nginx-unprivileged", "extra"])
    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 1


def test_main_one_target_raises(sid, tmp_path, monkeypatch):
    """<key> <basename> must be given together -- a lone positional
    argument is rejected rather than guessed at."""
    monkeypatch.setattr("sys.argv", ["fix-image-digests", "nginx"])
    with pytest.raises(SystemExit) as exc_info:
        sid.main()
    assert exc_info.value.code == 1
