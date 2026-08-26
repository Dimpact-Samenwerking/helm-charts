"""check_vendored_tgz_extraction / find_extracted_vendored_dirs — a vendored
sub-chart under charts/podiumd/charts/ must never have BOTH a pinned .tgz
AND an extracted directory of the same name, per
.claude/commands/helm-tgz-inspect.md: Helm silently prefers the extracted
copy over the pinned package."""


def write_tgz(chart_dir, filename):
    charts_dir = chart_dir / "charts"
    charts_dir.mkdir(exist_ok=True)
    (charts_dir / filename).write_bytes(b"")


def write_extracted_dir(chart_dir, name):
    charts_dir = chart_dir / "charts"
    charts_dir.mkdir(exist_ok=True)
    (charts_dir / name).mkdir()


def test_no_charts_dir_passes(vp, tmp_path):
    ok, detail = vp.check_vendored_tgz_extraction(tmp_path)
    assert ok is True
    assert "0 conflict(s)" in detail


def test_empty_charts_dir_passes(vp, tmp_path):
    (tmp_path / "charts").mkdir()
    ok, detail = vp.check_vendored_tgz_extraction(tmp_path)
    assert ok is True
    assert "0 conflict(s)" in detail


def test_tgz_only_passes(vp, tmp_path):
    write_tgz(tmp_path, "openzaak-1.14.2.tgz")
    ok, detail = vp.check_vendored_tgz_extraction(tmp_path)
    assert ok is True
    assert "0 conflict(s)" in detail


def test_tgz_plus_matching_extracted_dir_flagged(vp, tmp_path, capsys):
    write_tgz(tmp_path, "openzaak-1.14.2.tgz")
    write_extracted_dir(tmp_path, "openzaak")
    ok, detail = vp.check_vendored_tgz_extraction(tmp_path)
    assert ok is False
    assert "1 conflict(s)" in detail
    out = capsys.readouterr().out
    assert "charts/openzaak/" in out
    assert "openzaak-<version>.tgz" in out


def test_hyphenated_chart_name_parsed_correctly(vp, tmp_path, capsys):
    """The version suffix must split on the last digit-starting segment,
    not the first hyphen — a chart name like notifynl-omc-nodep or
    keycloak-operator must not be mistaken for name="notifynl" etc."""
    write_tgz(tmp_path, "notifynl-omc-nodep-0.14.1.tgz")
    write_extracted_dir(tmp_path, "notifynl-omc-nodep")
    ok, detail = vp.check_vendored_tgz_extraction(tmp_path)
    assert ok is False
    assert "1 conflict(s)" in detail
    out = capsys.readouterr().out
    assert "charts/notifynl-omc-nodep/" in out


def test_extracted_dir_with_no_matching_tgz_not_flagged(vp, tmp_path):
    """An extracted dir with no pinned .tgz of the same name isn't this
    check's concern (e.g. mi-data, a local file:// dependency with no
    .tgz at all) — only a .tgz shadowed by its own extracted copy is."""
    write_extracted_dir(tmp_path, "mi-data")
    ok, detail = vp.check_vendored_tgz_extraction(tmp_path)
    assert ok is True
    assert "0 conflict(s)" in detail


def test_multiple_conflicts_all_reported(vp, tmp_path, capsys):
    write_tgz(tmp_path, "openzaak-1.14.2.tgz")
    write_extracted_dir(tmp_path, "openzaak")
    write_tgz(tmp_path, "openklant-1.11.0.tgz")
    write_extracted_dir(tmp_path, "openklant")
    ok, detail = vp.check_vendored_tgz_extraction(tmp_path)
    assert ok is False
    assert "2 conflict(s)" in detail
    out = capsys.readouterr().out
    assert "charts/openzaak/" in out
    assert "charts/openklant/" in out


def test_find_extracted_vendored_dirs_returns_sorted_names(libvendoredtgzcheck, tmp_path):
    write_tgz(tmp_path, "openzaak-1.14.2.tgz")
    write_extracted_dir(tmp_path, "openzaak")
    write_tgz(tmp_path, "clamav-3.7.1.tgz")
    write_extracted_dir(tmp_path, "clamav")
    assert libvendoredtgzcheck.find_extracted_vendored_dirs(tmp_path) == ["clamav", "openzaak"]
