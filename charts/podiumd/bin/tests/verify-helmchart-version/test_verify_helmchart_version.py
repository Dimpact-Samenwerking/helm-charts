"""find_dependency and main() for verify-helmchart-version.py. `pull_chart` itself
(and the `helm` subprocess it wraps) is covered by tests/lib/test_chart.py —
these tests mock it out and only exercise this script's own glue: looking up
the Chart.yaml dependency and reporting FOUND/MISSING/OK/FAIL."""
import pytest
import yaml


def write_chart_yaml(vhcv, dependencies):
    vhcv.CHART_YAML.write_text(yaml.safe_dump({"dependencies": dependencies}))


# --- find_dependency ---

def test_find_dependency_by_name(vhcv, tmp_path, monkeypatch):
    monkeypatch.setattr(vhcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vhcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    assert vhcv.find_dependency("zaakafhandelcomponent")["alias"] == "zac"


def test_find_dependency_by_alias(vhcv, tmp_path, monkeypatch):
    monkeypatch.setattr(vhcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vhcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    assert vhcv.find_dependency("zac")["name"] == "zaakafhandelcomponent"


def test_find_dependency_not_found_raises(vhcv, tmp_path, monkeypatch):
    monkeypatch.setattr(vhcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vhcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    with pytest.raises(SystemExit, match="no dependency named or aliased"):
        vhcv.find_dependency("totally-unknown")


# --- main() ---

def run_main(vhcv, monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["verify-helmchart-version.py", *argv])
    with pytest.raises(SystemExit) as exc_info:
        vhcv.main()
    return exc_info.value.code


def test_main_chart_version_exists(vhcv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vhcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vhcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    monkeypatch.setattr(vhcv, "pull_chart", lambda dep, version, dest: (True, ""))

    code = run_main(vhcv, monkeypatch, ["zac", "1.0.297"])
    assert code == 0
    out = capsys.readouterr().out
    assert "[FOUND  ] zaakafhandelcomponent 1.0.297" in out
    assert "OK: chart version exists" in out


def test_main_chart_version_missing(vhcv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vhcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vhcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    monkeypatch.setattr(vhcv, "pull_chart", lambda dep, version, dest: (False, "version not found"))

    code = run_main(vhcv, monkeypatch, ["zac", "9.9.9"])
    assert code == 1
    out = capsys.readouterr().out
    assert "[MISSING] zaakafhandelcomponent 9.9.9  (version not found)" in out
    assert "FAIL: chart version does not exist" in out


def test_main_requires_exactly_two_arguments(vhcv, monkeypatch):
    code = run_main(vhcv, monkeypatch, ["zac"])
    assert code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(vhcv, monkeypatch, capsys, flag):
    code = run_main(vhcv, monkeypatch, [flag])
    assert code == 0
    assert capsys.readouterr().out == vhcv.__doc__ + "\n"
