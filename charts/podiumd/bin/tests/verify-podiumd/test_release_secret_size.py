"""lib.release_secret_size — packaged_files/bucket_files/build_release/
check_subchart_freshness/encoded_secret_size/record_result (the core
computation, shared by the standalone verify-helm-secret-size CLI and
this module's own check_release_secret_size), plus check_release_secret_
size itself (the verify-podiumd integration — a REAL pass/fail step, not
report-only). All `helm package`/`helm template` calls are mocked via
librelease_secret_size.run/.render_chart — no real helm invocation
happens in these tests."""
import io
import json
import gzip
import base64
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


def make_tgz_bytes(name, files):
    """A real gzipped tar, in memory, with every {internal path: text}
    entry written under a leading "<name>/" prefix — the exact shape
    `helm package` produces and packaged_files() strips back off."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel_path, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name=f"{name}/{rel_path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def fake_helm_package(tgz_name, files):
    """A librelease_secret_size.run replacement: writes make_tgz_bytes'
    own output to the -d destination directory `helm package` was asked
    for, mirroring what a real `helm package -d <dir>` invocation does."""
    def run(cmd, **kwargs):
        dest = Path(cmd[cmd.index("-d") + 1])
        (dest / f"{tgz_name}.tgz").write_bytes(make_tgz_bytes(tgz_name.rsplit("-", 1)[0], files))
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    return run


# --- packaged_files ---

def test_packaged_files_strips_chart_name_prefix(librelease_secret_size, monkeypatch, tmp_path):
    monkeypatch.setattr(librelease_secret_size, "run",
                         fake_helm_package("podiumd-1.0.0", {"values.yaml": "a: 1\n", "templates/x.yaml": "kind: X\n"}))
    files = librelease_secret_size.packaged_files(tmp_path)
    assert files["values.yaml"] == b"a: 1\n"
    assert files["templates/x.yaml"] == b"kind: X\n"
    assert not any(k.startswith("podiumd") for k in files)


def test_packaged_files_raises_on_helm_package_failure(librelease_secret_size, monkeypatch, tmp_path):
    monkeypatch.setattr(librelease_secret_size, "run",
                         lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="boom"))
    with pytest.raises(RuntimeError, match="helm package failed"):
        librelease_secret_size.packaged_files(tmp_path)


# --- check_subchart_freshness ---

def test_check_subchart_freshness_matching_version_is_silent(librelease_secret_size, tmp_path):
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts" / "zac-1.0.297.tgz").write_bytes(b"")
    metadata = {"dependencies": [{"name": "zac", "version": "1.0.297"}]}
    assert librelease_secret_size.check_subchart_freshness(tmp_path, metadata) == []


def test_check_subchart_freshness_stale_vendored_version_warns(librelease_secret_size, tmp_path):
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts" / "zac-1.0.290.tgz").write_bytes(b"")
    metadata = {"dependencies": [{"name": "zac", "version": "1.0.297"}]}
    warnings = librelease_secret_size.check_subchart_freshness(tmp_path, metadata)
    assert len(warnings) == 1
    assert "zac@1.0.297" in warnings[0]
    assert "zac-1.0.290.tgz" in warnings[0]
    assert "helm dependency update" in warnings[0]


def test_check_subchart_freshness_not_vendored_at_all_is_silent(librelease_secret_size, tmp_path):
    """Not vendored locally (e.g. condition-disabled) — nothing to compare,
    not a staleness finding."""
    (tmp_path / "charts").mkdir()
    metadata = {"dependencies": [{"name": "zac", "version": "1.0.297"}]}
    assert librelease_secret_size.check_subchart_freshness(tmp_path, metadata) == []


def test_check_subchart_freshness_no_charts_dir_is_silent(librelease_secret_size, tmp_path):
    metadata = {"dependencies": [{"name": "zac", "version": "1.0.297"}]}
    assert librelease_secret_size.check_subchart_freshness(tmp_path, metadata) == []


def test_check_subchart_freshness_no_dependencies_is_silent(librelease_secret_size, tmp_path):
    assert librelease_secret_size.check_subchart_freshness(tmp_path, {}) == []


# --- bucket_files ---

def test_bucket_files_excludes_subcharts_and_special_files(librelease_secret_size):
    paths = {
        "Chart.yaml": b"x", "values.yaml": b"x", "Chart.lock": b"x", "values.schema.json": b"x",
        "charts/zac/values.yaml": b"x",
        "templates/deployment.yaml": b"tpl",
        "crds/foo.yaml": b"crd",
    }
    templates, files = librelease_secret_size.bucket_files(paths)
    assert [t["name"] for t in templates] == ["templates/deployment.yaml"]
    assert [f["name"] for f in files] == ["crds/foo.yaml"]


def test_bucket_files_data_is_base64(librelease_secret_size):
    templates, _files = librelease_secret_size.bucket_files({"templates/a.yaml": b"hello"})
    assert templates[0]["data"] == librelease_secret_size.b64(b"hello")


# --- build_release ---

CHART_YAML_TEXT = yaml.safe_dump({"name": "podiumd", "version": "4.9.1", "dependencies": []})
VALUES_YAML_TEXT = yaml.safe_dump({"foo": "bar"})


def _mock_packaged_files(monkeypatch, librelease_secret_size, extra=None):
    paths = {"Chart.yaml": CHART_YAML_TEXT.encode(), "values.yaml": VALUES_YAML_TEXT.encode()}
    paths.update(extra or {})
    monkeypatch.setattr(librelease_secret_size, "packaged_files", lambda chart_dir: paths)
    return paths


def test_build_release_basic_shape(librelease_secret_size, monkeypatch, tmp_path):
    _mock_packaged_files(monkeypatch, librelease_secret_size)
    release, version, warnings = librelease_secret_size.build_release(
        tmp_path, None, "---\nmanifest text\n", "podiumd", "podiumd")

    assert version == "4.9.1"
    assert warnings == []
    assert release["name"] == "podiumd"
    assert release["namespace"] == "podiumd"
    assert release["manifest"] == "---\nmanifest text\n"
    assert release["chart"]["metadata"]["name"] == "podiumd"
    assert release["chart"]["values"] == {"foo": "bar"}
    assert "config" not in release


def test_build_release_includes_config_when_values_override_given(librelease_secret_size, monkeypatch, tmp_path):
    _mock_packaged_files(monkeypatch, librelease_secret_size)
    release, _version, _warnings = librelease_secret_size.build_release(
        tmp_path, {"override": "x"}, "manifest", "podiumd", "podiumd")
    assert release["config"] == {"override": "x"}


def test_build_release_no_lock_or_schema_when_absent(librelease_secret_size, monkeypatch, tmp_path):
    _mock_packaged_files(monkeypatch, librelease_secret_size)
    release, _version, _warnings = librelease_secret_size.build_release(
        tmp_path, None, "manifest", "podiumd", "podiumd")
    assert release["chart"]["lock"] is None
    assert release["chart"]["schema"] is None


def test_build_release_includes_lock_and_schema_when_present(librelease_secret_size, monkeypatch, tmp_path):
    lock_text = yaml.safe_dump({"dependencies": []})
    _mock_packaged_files(monkeypatch, librelease_secret_size, extra={
        "Chart.lock": lock_text.encode(), "values.schema.json": b'{"type": "object"}',
    })
    release, _version, _warnings = librelease_secret_size.build_release(
        tmp_path, None, "manifest", "podiumd", "podiumd")
    assert release["chart"]["lock"] == {"dependencies": []}
    assert release["chart"]["schema"] == librelease_secret_size.b64(b'{"type": "object"}')


def test_build_release_warns_on_notes_txt(librelease_secret_size, monkeypatch, tmp_path):
    _mock_packaged_files(monkeypatch, librelease_secret_size, extra={"templates/NOTES.txt": b"hi"})
    _release, _version, warnings = librelease_secret_size.build_release(
        tmp_path, None, "manifest", "podiumd", "podiumd")
    assert any("templates/NOTES.txt" in w for w in warnings)


def test_build_release_includes_subchart_freshness_warnings(librelease_secret_size, monkeypatch, tmp_path):
    chart_yaml_text = yaml.safe_dump({
        "name": "podiumd", "version": "4.9.1",
        "dependencies": [{"name": "zac", "version": "1.0.297"}],
    })
    _mock_packaged_files(monkeypatch, librelease_secret_size, extra={"Chart.yaml": chart_yaml_text.encode()})
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts" / "zac-1.0.290.tgz").write_bytes(b"")

    _release, _version, warnings = librelease_secret_size.build_release(
        tmp_path, None, "manifest", "podiumd", "podiumd")
    assert any("zac@1.0.297" in w for w in warnings)


def test_build_release_unknown_version_when_metadata_has_none(librelease_secret_size, monkeypatch, tmp_path):
    _mock_packaged_files(monkeypatch, librelease_secret_size, extra={
        "Chart.yaml": yaml.safe_dump({"name": "podiumd"}).encode(),
    })
    _release, version, _warnings = librelease_secret_size.build_release(
        tmp_path, None, "manifest", "podiumd", "podiumd")
    assert version == "unknown"


# --- encoded_secret_size ---

def test_encoded_secret_size_round_trips_gzip_base64(librelease_secret_size):
    release = {"name": "x", "manifest": "y" * 1000}
    raw_len, gzipped_len, size, pct = librelease_secret_size.encoded_secret_size(release)
    assert raw_len == len(json.dumps(release, separators=(",", ":")).encode())
    # sanity: gzip+base64 of this repetitive input is much smaller than raw
    assert gzipped_len < raw_len
    assert size > gzipped_len  # base64 expands
    assert pct == pytest.approx(size / librelease_secret_size.SECRET_LIMIT)


def test_encoded_secret_size_pct_crosses_threshold_for_large_release(librelease_secret_size):
    """Real regression check on the actual pass/fail math: a genuinely
    incompressible manifest (secrets.token_hex — gzip can't shrink random
    hex meaningfully, unlike a repetitive string) sized comfortably past
    the 1 MiB raw mark must report pct >= WARN_THRESHOLD once gzipped and
    base64-encoded."""
    import secrets
    release = {"name": "x", "manifest": secrets.token_hex(700_000)}
    _raw_len, _gzipped_len, _size, pct = librelease_secret_size.encoded_secret_size(release)
    assert pct >= librelease_secret_size.WARN_THRESHOLD


# --- format_report / over_limit_warning ---

def test_format_report_contains_all_fields(librelease_secret_size):
    report = librelease_secret_size.format_report("podiumd", "4.9.1", 100, 50, 70, 0.5)
    assert "podiumd 4.9.1" in report
    assert "100 bytes" in report
    assert "50 bytes" in report
    assert "70 bytes" in report
    assert "50.00%" in report


def test_over_limit_warning_names_chart_and_percentage(librelease_secret_size):
    warning = librelease_secret_size.over_limit_warning("podiumd", "4.9.1", 950000, 0.95)
    assert "podiumd 4.9.1" in warning
    assert "95.0%" in warning
    assert "request entity too large" in warning


# --- record_result ---

def test_record_result_creates_new_file_with_header(librelease_secret_size, tmp_path):
    doc_path = librelease_secret_size.record_result(tmp_path, "podiumd", "4.9.1", 468600, 0.447)
    text = doc_path.read_text()
    assert "podiumd — release Secret size tracking" in text
    assert "verify-helm-secret-size" in text
    assert "| 4.9.1 | 468,600 | 44.7% |" in text


def test_record_result_appends_new_version_row(librelease_secret_size, tmp_path):
    librelease_secret_size.record_result(tmp_path, "podiumd", "4.9.0", 100000, 0.1)
    doc_path = librelease_secret_size.record_result(tmp_path, "podiumd", "4.9.1", 200000, 0.2)
    text = doc_path.read_text()
    assert "| 4.9.0 |" in text
    assert "| 4.9.1 |" in text


def test_record_result_replaces_existing_row_for_same_version(librelease_secret_size, tmp_path):
    librelease_secret_size.record_result(tmp_path, "podiumd", "4.9.1", 100000, 0.1)
    doc_path = librelease_secret_size.record_result(tmp_path, "podiumd", "4.9.1", 500000, 0.5)
    text = doc_path.read_text()
    assert text.count("| 4.9.1 |") == 1
    assert "500,000" in text
    assert "100,000" not in text


def test_record_result_duplicate_rows_warns_and_replaces_only_first(librelease_secret_size, tmp_path, capsys):
    doc_path = tmp_path / "docs" / "release-secret-size.md"
    doc_path.parent.mkdir(parents=True)
    doc_path.write_text(
        "# podiumd\n\n| Version | Encoded bytes | % of 1 MiB limit | Date |\n|---|---|---|---|\n"
        "| 4.9.1 | 1 | 0.0% | 2026-01-01 |\n"
        "| 4.9.1 | 2 | 0.0% | 2026-01-02 |\n"
    )
    librelease_secret_size.record_result(tmp_path, "podiumd", "4.9.1", 999, 0.9)
    out = capsys.readouterr().out
    assert "already had more than one row" in out
    text = doc_path.read_text()
    assert text.count("| 4.9.1 |") == 2  # both rows still present, only first replaced
    assert "999" in text


# --- values_file_from_extra_args ---

def test_values_file_from_extra_args_finds_path(librelease_secret_size):
    assert librelease_secret_size.values_file_from_extra_args(["-f", "ci/lint-values.yaml"]) == Path("ci/lint-values.yaml")


def test_values_file_from_extra_args_none_when_absent(librelease_secret_size):
    assert librelease_secret_size.values_file_from_extra_args([]) is None


# --- check_release_secret_size ---

def test_check_release_secret_size_render_failure(librelease_secret_size, monkeypatch, tmp_path):
    monkeypatch.setattr(librelease_secret_size, "render_chart",
                         lambda chart_dir, extra_args: SimpleNamespace(returncode=1, stdout="", stderr="boom"))
    ok, detail = librelease_secret_size.check_release_secret_size(tmp_path, [])
    assert ok is False
    assert "helm template failed to render" in detail


def test_check_release_secret_size_passes_under_threshold(librelease_secret_size, monkeypatch, tmp_path):
    monkeypatch.setattr(librelease_secret_size, "render_chart",
                         lambda chart_dir, extra_args: SimpleNamespace(returncode=0, stdout="manifest", stderr=""))
    monkeypatch.setattr(librelease_secret_size, "build_release",
                         lambda chart_dir, values_override, manifest, name, namespace:
                             ({"name": name, "manifest": manifest}, "4.9.1", []))

    ok, detail = librelease_secret_size.check_release_secret_size(tmp_path, [])

    assert ok is True
    assert "bytes" in detail


def test_check_release_secret_size_fails_at_warn_threshold(librelease_secret_size, monkeypatch, tmp_path, capsys):
    """Real pass/fail regression: a percentage right at WARN_THRESHOLD
    must fail the step (ok=False) and print the same over-limit warning
    the standalone CLI's own sys.exit(1) path prints — this is the
    behavior that would NOT have existed at all before this feature was
    wired into verify-podiumd (a bloated release used to only ever be
    caught by manually running the standalone script)."""
    monkeypatch.setattr(librelease_secret_size, "render_chart",
                         lambda chart_dir, extra_args: SimpleNamespace(returncode=0, stdout="manifest", stderr=""))
    monkeypatch.setattr(librelease_secret_size, "build_release",
                         lambda chart_dir, values_override, manifest, name, namespace:
                             ({}, "4.9.1", []))
    monkeypatch.setattr(librelease_secret_size, "encoded_secret_size",
                         lambda release: (1000, 500, 950000, 0.95))

    ok, detail = librelease_secret_size.check_release_secret_size(tmp_path, [])

    assert ok is False
    assert "95.0%" in detail
    out = capsys.readouterr().out
    assert "request entity too large" in out


def test_check_release_secret_size_prints_subchart_freshness_warnings(librelease_secret_size, monkeypatch, tmp_path,
                                                                        capsys):
    monkeypatch.setattr(librelease_secret_size, "render_chart",
                         lambda chart_dir, extra_args: SimpleNamespace(returncode=0, stdout="manifest", stderr=""))
    monkeypatch.setattr(librelease_secret_size, "build_release",
                         lambda chart_dir, values_override, manifest, name, namespace:
                             ({}, "4.9.1", ["Chart.yaml declares zac@1.0.297, but ... 1.0.290.tgz"]))

    librelease_secret_size.check_release_secret_size(tmp_path, [])

    out = capsys.readouterr().out
    assert "WARNING: Chart.yaml declares zac@1.0.297" in out


def test_check_release_secret_size_reads_values_override_from_extra_args(librelease_secret_size, monkeypatch,
                                                                            tmp_path):
    """Reuses verify-podiumd's own already-computed lint_args_for result
    (extra_args) to locate the values override -- never re-derives
    ci/lint-values.yaml itself."""
    values_path = tmp_path / "lint-values.yaml"
    values_path.write_text("foo: bar\n")
    monkeypatch.setattr(librelease_secret_size, "render_chart",
                         lambda chart_dir, extra_args: SimpleNamespace(returncode=0, stdout="manifest", stderr=""))
    captured = {}

    def fake_build_release(chart_dir, values_override, manifest, name, namespace):
        captured["values_override"] = values_override
        return {}, "4.9.1", []

    monkeypatch.setattr(librelease_secret_size, "build_release", fake_build_release)

    librelease_secret_size.check_release_secret_size(tmp_path, ["-f", str(values_path)])

    assert captured["values_override"] == {"foo": "bar"}


def test_check_release_secret_size_never_writes_the_doc(librelease_secret_size, monkeypatch, tmp_path):
    """verify-podiumd's checks are read-only -- check_release_secret_size
    must never call record_result (--record stays exclusive to the
    standalone CLI)."""
    monkeypatch.setattr(librelease_secret_size, "render_chart",
                         lambda chart_dir, extra_args: SimpleNamespace(returncode=0, stdout="manifest", stderr=""))
    monkeypatch.setattr(librelease_secret_size, "build_release",
                         lambda chart_dir, values_override, manifest, name, namespace: ({}, "4.9.1", []))

    def fail_if_called(*a, **kw):
        raise AssertionError("check_release_secret_size must never call record_result")

    monkeypatch.setattr(librelease_secret_size, "record_result", fail_if_called)

    librelease_secret_size.check_release_secret_size(tmp_path, [])  # must not raise
    assert not (tmp_path / "docs" / "release-secret-size.md").exists()
