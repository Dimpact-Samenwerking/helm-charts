"""main() — BOM stripping, dry-run, and exit codes. No git/network needed;
VALUES_PATH is monkeypatched to a disposable tmp_path file."""
import pytest

BOM = b"\xef\xbb\xbf"


def write(path, data):
    path.write_bytes(data)


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero_without_touching_the_file(sub, tmp_path, monkeypatch, capsys, flag):
    values_path = tmp_path / "values.yaml"
    original = BOM + b"zac:\n  enabled: true\n"
    write(values_path, original)
    monkeypatch.setattr(sub, "VALUES_PATH", values_path)
    monkeypatch.setattr("sys.argv", ["strip-utf8-bom", flag])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == sub.__doc__ + "\n"
    assert values_path.read_bytes() == original


def test_no_bom_exits_zero_and_leaves_file_untouched(sub, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    original = b"zac:\n  enabled: true\n"
    write(values_path, original)
    monkeypatch.setattr(sub, "VALUES_PATH", values_path)
    monkeypatch.setattr("sys.argv", ["strip-utf8-bom"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    assert values_path.read_bytes() == original


def test_bom_is_stripped_and_exits_zero(sub, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    write(values_path, BOM + b"zac:\n  enabled: true\n")
    monkeypatch.setattr(sub, "VALUES_PATH", values_path)
    monkeypatch.setattr("sys.argv", ["strip-utf8-bom"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    assert values_path.read_bytes() == b"zac:\n  enabled: true\n"


def test_dry_run_reports_bom_but_does_not_write(sub, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    original = BOM + b"zac:\n  enabled: true\n"
    write(values_path, original)
    monkeypatch.setattr(sub, "VALUES_PATH", values_path)
    monkeypatch.setattr("sys.argv", ["strip-utf8-bom", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 1
    assert values_path.read_bytes() == original


def test_dry_run_no_bom_exits_zero(sub, tmp_path, monkeypatch):
    values_path = tmp_path / "values.yaml"
    original = b"zac:\n  enabled: true\n"
    write(values_path, original)
    monkeypatch.setattr(sub, "VALUES_PATH", values_path)
    monkeypatch.setattr("sys.argv", ["strip-utf8-bom", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    assert values_path.read_bytes() == original
