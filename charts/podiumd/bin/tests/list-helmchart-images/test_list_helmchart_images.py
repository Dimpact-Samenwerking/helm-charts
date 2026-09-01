"""find_dependency, report_chart, and main() — chart_ref/local_chart_dir/
pull_chart/pulled_chart_dir/find_images/version_of themselves are lib.chart's
own (see tests/lib/test_chart.py); these tests just cover this script's own
glue, with `helm pull` mocked out via a fake pull_chart so no `helm` binary
or network access is needed."""
import pytest
import yaml


def write_chart_yaml(lhi, dependencies):
    lhi.CHART_YAML.write_text(yaml.safe_dump({"dependencies": dependencies}))


# --- find_dependency ---

def test_find_dependency_by_name(lhi):
    write_chart_yaml(lhi, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    dep = lhi.find_dependency("zaakafhandelcomponent")
    assert dep["alias"] == "zac"


def test_find_dependency_by_alias(lhi):
    write_chart_yaml(lhi, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    dep = lhi.find_dependency("zac")
    assert dep["name"] == "zaakafhandelcomponent"


def test_find_dependency_not_found_raises(lhi):
    write_chart_yaml(lhi, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    with pytest.raises(SystemExit, match="no dependency named or aliased"):
        lhi.find_dependency("totally-unknown")


# --- report_chart ---

def write_chart(chart_dir, name, version, app_version=None, dependencies=None, values=None):
    chart_dir.mkdir(parents=True, exist_ok=True)
    chart_yaml = {"name": name, "version": version}
    if app_version is not None:
        chart_yaml["appVersion"] = app_version
    if dependencies is not None:
        chart_yaml["dependencies"] = dependencies
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump(chart_yaml))
    (chart_dir / "values.yaml").write_text(yaml.safe_dump(values or {}))


def test_report_chart_prints_chart_deps_and_images(lhi, tmp_path, capsys):
    write_chart(tmp_path, "zaakafhandelcomponent", "1.0.297", app_version="5.5",
                dependencies=[{"name": "opentelemetry-collector", "version": "0.169.0"}],
                values={"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.3@sha256:abc"}})
    lhi.report_chart(tmp_path, "1.0.297", "zac")
    out = capsys.readouterr().out
    assert "Chart: zaakafhandelcomponent 1.0.297 (appVersion: 5.5)" in out
    assert "opentelemetry-collector: 0.169.0" in out
    assert "zac  zaakafhandelcomponent  5.4.3" in out
    assert "ghcr.io/infonl/zaakafhandelcomponent:5.4.3@sha256:abc" in out


def test_report_chart_no_image_references(lhi, tmp_path, capsys):
    write_chart(tmp_path, "mi-data", "1.0.0")
    lhi.report_chart(tmp_path, "1.0.0", "mi")
    assert "No image references found" in capsys.readouterr().out


def test_report_chart_warns_on_version_mismatch(lhi, tmp_path, capsys):
    """A "file://" local dependency only ever has ONE real version —
    whatever's actually checked out — so a requested version that doesn't
    match is a warning, not a hard failure (there's nothing else to
    report instead)."""
    write_chart(tmp_path, "mi-data", "1.0.0")
    lhi.report_chart(tmp_path, "2.0.0", "mi")
    err = capsys.readouterr().err
    assert "actually version '1.0.0'" in err
    assert "requested '2.0.0'" in err


# --- main(): local "file://" dependency ---

def test_main_reads_local_chart_source_for_file_dependency(lhi, tmp_path, monkeypatch, capsys):
    write_chart_yaml(lhi, [{"name": "mi-data", "alias": "mi", "repository": "file://../mi-data"}])
    local_dir = tmp_path / "mi-data"
    write_chart(local_dir, "mi-data", "1.0.0", app_version="1.0.0",
                values={"image": {"repository": "mcr.microsoft.com/azure-cli", "tag": "2.71.0"}})
    monkeypatch.setattr(lhi, "local_chart_dir", lambda chart_dir, dep: local_dir)
    monkeypatch.setattr("sys.argv", ["list-helmchart-images", "mi-data", "1.0.0"])

    lhi.main()

    out = capsys.readouterr().out
    assert f"Reading local chart source: {local_dir}" in out
    assert "Chart: mi-data 1.0.0" in out
    assert "mi  azure-cli  2.71.0" in out
    assert "mcr.microsoft.com/azure-cli:2.71.0" in out


def test_main_local_dependency_missing_directory_raises(lhi, tmp_path, monkeypatch):
    write_chart_yaml(lhi, [{"name": "mi-data", "alias": "mi", "repository": "file://../mi-data"}])
    monkeypatch.setattr(lhi, "local_chart_dir", lambda chart_dir, dep: tmp_path / "does-not-exist")
    monkeypatch.setattr("sys.argv", ["list-helmchart-images", "mi-data", "1.0.0"])
    with pytest.raises(SystemExit, match="does not exist"):
        lhi.main()


# --- main(): pulled (remote) dependency ---

def test_main_full_flow_prints_chart_and_images(lhi, monkeypatch, capsys):
    write_chart_yaml(lhi, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])

    def fake_pull_chart(dep, version, dest):
        write_chart(dest / "zaakafhandelcomponent", "zaakafhandelcomponent", "1.0.297", app_version="5.5",
                    dependencies=[{"name": "opentelemetry-collector", "version": "0.169.0"}],
                    values={"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.3@sha256:abc"}})
        return True, ""

    monkeypatch.setattr(lhi, "pull_chart", fake_pull_chart)
    monkeypatch.setattr("sys.argv", ["list-helmchart-images", "zac", "1.0.297"])
    lhi.main()

    out = capsys.readouterr().out
    assert "Pulling zac/zaakafhandelcomponent @ 1.0.297" in out
    assert "Chart: zaakafhandelcomponent 1.0.297 (appVersion: 5.5)" in out
    assert "opentelemetry-collector: 0.169.0" in out
    assert "zac  zaakafhandelcomponent  5.4.3" in out
    assert "ghcr.io/infonl/zaakafhandelcomponent:5.4.3@sha256:abc" in out


def test_main_pull_failure_raises_systemexit(lhi, monkeypatch):
    write_chart_yaml(lhi, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    monkeypatch.setattr(lhi, "pull_chart", lambda dep, version, dest: (False, "version not found"))
    monkeypatch.setattr("sys.argv", ["list-helmchart-images", "zac", "9.9.9"])
    with pytest.raises(SystemExit, match="helm pull failed"):
        lhi.main()


def test_main_helm_pull_produces_no_directory_raises(lhi, monkeypatch):
    write_chart_yaml(lhi, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    monkeypatch.setattr(lhi, "pull_chart", lambda dep, version, dest: (True, ""))  # creates nothing
    monkeypatch.setattr("sys.argv", ["list-helmchart-images", "zac", "1.0.297"])
    with pytest.raises(SystemExit, match="produced no chart directory"):
        lhi.main()


def test_main_missing_arguments_exits(lhi, monkeypatch):
    monkeypatch.setattr("sys.argv", ["list-helmchart-images", "zac"])
    with pytest.raises(SystemExit):
        lhi.main()


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(lhi, monkeypatch, capsys, flag):
    monkeypatch.setattr("sys.argv", ["list-helmchart-images", flag])
    with pytest.raises(SystemExit) as exc_info:
        lhi.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == lhi.__doc__ + "\n"
