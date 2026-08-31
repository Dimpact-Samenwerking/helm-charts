"""main() — deletes an extracted directory shadowing a pinned .tgz, dry-run,
and exit codes. No git/network needed; CHART_DIR is monkeypatched to a
disposable tmp_path chart."""
import pytest


def make_chart(tmp_path, tgz_names=(), extracted_names=()):
    charts_dir = tmp_path / "charts"
    charts_dir.mkdir()
    for name in tgz_names:
        (charts_dir / f"{name}-1.0.0.tgz").write_bytes(b"fake-tgz")
    for name in extracted_names:
        (charts_dir / name).mkdir()
        (charts_dir / name / "Chart.yaml").write_text("name: " + name + "\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero_without_touching_anything(sub, tmp_path, monkeypatch, capsys, flag):
    chart_dir = make_chart(tmp_path, tgz_names=["redis"], extracted_names=["redis"])
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-vendored-tgz", flag])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == sub.__doc__ + "\n"
    assert (chart_dir / "charts" / "redis").is_dir()


def test_no_conflict_exits_zero_and_leaves_charts_untouched(sub, tmp_path, monkeypatch):
    chart_dir = make_chart(tmp_path, tgz_names=["redis"])
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-vendored-tgz"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    assert list((chart_dir / "charts").iterdir()) == [chart_dir / "charts" / "redis-1.0.0.tgz"]


def test_shadowing_directory_is_deleted_and_exits_zero(sub, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart(tmp_path, tgz_names=["redis"], extracted_names=["redis"])
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-vendored-tgz"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    assert not (chart_dir / "charts" / "redis").exists()
    assert (chart_dir / "charts" / "redis-1.0.0.tgz").is_file()
    assert "Deleted charts/redis/" in capsys.readouterr().out


def test_only_the_shadowing_directory_is_deleted_not_unrelated_ones(sub, tmp_path, monkeypatch):
    chart_dir = make_chart(tmp_path, tgz_names=["redis", "elastic"], extracted_names=["redis", "unrelated-dir"])
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-vendored-tgz"])

    with pytest.raises(SystemExit):
        sub.main()

    assert not (chart_dir / "charts" / "redis").exists()
    assert (chart_dir / "charts" / "unrelated-dir").is_dir()  # not a pinned .tgz's shadow — untouched
    assert (chart_dir / "charts" / "elastic-1.0.0.tgz").is_file()


def test_multiple_shadowing_directories_are_all_deleted(sub, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart(tmp_path, tgz_names=["redis", "elastic"], extracted_names=["redis", "elastic"])
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-vendored-tgz"])

    with pytest.raises(SystemExit):
        sub.main()

    assert not (chart_dir / "charts" / "redis").exists()
    assert not (chart_dir / "charts" / "elastic").exists()
    out = capsys.readouterr().out
    assert "Removed 2 extracted directories" in out


def test_dry_run_reports_but_does_not_delete(sub, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart(tmp_path, tgz_names=["redis"], extracted_names=["redis"])
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-vendored-tgz", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 1
    assert (chart_dir / "charts" / "redis").is_dir()
    out = capsys.readouterr().out
    assert "charts/redis/" in out
    assert "dry-run" in out


def test_dry_run_no_conflict_exits_zero(sub, tmp_path, monkeypatch):
    chart_dir = make_chart(tmp_path, tgz_names=["redis"])
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-vendored-tgz", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0


def test_no_charts_subdir_at_all_exits_zero(sub, tmp_path, monkeypatch):
    chart_dir = tmp_path
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-vendored-tgz"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
