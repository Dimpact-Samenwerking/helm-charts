"""find_dependency and main() for verify-component-version. The chart-
pull-and-report step itself (lib.chart.verify_chart_version) and the
registry check (lib.chart.check_image_versions, shared with update-
component-version's own pre-write gate) are both covered by
tests/lib/test_chart.py — these tests mock them out and only exercise
this script's own glue: looking up the Chart.yaml dependency, resolving
image_paths_for(component), and reporting the app-image FOUND/MISSING/
OK/FAIL lines on top of whatever verify_chart_version already reported."""
import pytest
import yaml


def write_chart_yaml(vcv, dependencies):
    vcv.CHART_YAML.write_text(yaml.safe_dump({"dependencies": dependencies}))


# --- find_dependency ---

def test_find_dependency_by_name(vcv, tmp_path, monkeypatch):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    assert vcv.find_dependency("zaakafhandelcomponent")["alias"] == "zac"


def test_find_dependency_by_alias(vcv, tmp_path, monkeypatch):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    assert vcv.find_dependency("zac")["name"] == "zaakafhandelcomponent"


def test_find_dependency_not_found_raises(vcv, tmp_path, monkeypatch):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    with pytest.raises(SystemExit, match="no dependency named or aliased"):
        vcv.find_dependency("totally-unknown")


# --- main() ---

def run_main(vcv, monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["verify-component-version", *argv])
    with pytest.raises(SystemExit) as exc_info:
        vcv.main()
    return exc_info.value


def test_main_single_image_component_success(vcv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    monkeypatch.setattr(vcv, "verify_chart_version", lambda dep, version: {"image": {"repository": "x/y"}})
    monkeypatch.setattr(vcv, "check_image_versions", lambda values, image_paths, app_version: [
        {"path": "image", "repository": "ghcr.io/infonl/zaakafhandelcomponent", "host": "ghcr.io",
         "repo_path": "infonl/zaakafhandelcomponent", "exists": True, "digest": "sha256:fake"},
    ])

    exc = run_main(vcv, monkeypatch, ["zac", "5.4.3", "1.0.297"])
    assert exc.code == 0
    out = capsys.readouterr().out
    assert "[FOUND  ] ghcr.io/infonl/zaakafhandelcomponent:5.4.3  digest=sha256:fake" in out
    assert "OK: chart + image version(s) exist" in out


def test_main_multi_image_component_checks_both(vcv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zgw-office-addin", "repository": "@zgw-office-addin"}])
    checked_paths = []

    def fake_check_image_versions(values, image_paths, app_version):
        checked_paths.extend(image_paths)
        return [
            {"path": "frontend.image", "repository": "ghcr.io/infonl/zgw-office-addin-frontend", "host": "ghcr.io",
             "repo_path": "infonl/zgw-office-addin-frontend", "exists": True, "digest": "sha256:aaaa"},
            {"path": "backend.image", "repository": "ghcr.io/infonl/zgw-office-addin-backend", "host": "ghcr.io",
             "repo_path": "infonl/zgw-office-addin-backend", "exists": True, "digest": "sha256:bbbb"},
        ]

    monkeypatch.setattr(vcv, "verify_chart_version", lambda dep, version: {})
    monkeypatch.setattr(vcv, "check_image_versions", fake_check_image_versions)

    exc = run_main(vcv, monkeypatch, ["zgw-office-addin", "0.11.0", "0.0.92"])
    assert exc.code == 0
    assert checked_paths == ["frontend.image", "backend.image"]


def test_main_dockerhub_component(vcv, tmp_path, monkeypatch, capsys):
    """openformulieren ships on Docker Hub — the registry must be inferred
    from the repository string, not assumed to be ghcr for everything."""
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "openforms", "alias": "openformulieren", "repository": "@maykinmedia"}])
    monkeypatch.setattr(vcv, "verify_chart_version", lambda dep, version: {})
    monkeypatch.setattr(vcv, "check_image_versions", lambda values, image_paths, app_version: [
        {"path": "image", "repository": "openformulieren/open-forms", "host": "docker.io",
         "repo_path": "openformulieren/open-forms", "exists": True, "digest": "sha256:fake"},
    ])

    exc = run_main(vcv, monkeypatch, ["openformulieren", "3.5.6", "1.12.0"])
    assert exc.code == 0
    assert "docker.io/openformulieren/open-forms:3.5.6" in capsys.readouterr().out


def test_main_missing_chart_version_propagates(vcv, tmp_path, monkeypatch):
    """verify_chart_version (lib.chart) already prints its own FAIL message
    and exits 1 when the chart version can't be pulled — main() has
    nothing to add and must not swallow that exit."""
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])

    def raise_pull_failure(dep, version):
        raise SystemExit(1)

    monkeypatch.setattr(vcv, "verify_chart_version", raise_pull_failure)
    exc = run_main(vcv, monkeypatch, ["zac", "5.4.3", "9.9.9"])
    assert exc.code == 1


def test_main_missing_app_version_fails(vcv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    monkeypatch.setattr(vcv, "verify_chart_version", lambda dep, version: {"image": {"repository": "x/y"}})
    monkeypatch.setattr(vcv, "check_image_versions", lambda values, image_paths, app_version: [
        {"path": "image", "repository": "ghcr.io/infonl/zaakafhandelcomponent", "host": "ghcr.io",
         "repo_path": "infonl/zaakafhandelcomponent", "exists": False, "digest": None},
    ])

    exc = run_main(vcv, monkeypatch, ["zac", "9.9.9", "1.0.297"])
    assert exc.code == 1
    out = capsys.readouterr().out
    assert "[MISSING]" in out
    assert "FAIL: one or more app image versions" in out


def test_main_no_repository_at_configured_path_propagates(vcv, tmp_path, monkeypatch):
    """check_image_versions (lib.chart) already raises SystemExit with a
    clear message when none of COMPONENT_IMAGE_PATHS resolves to a
    repository — main() has nothing to add here either."""
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    monkeypatch.setattr(vcv, "verify_chart_version", lambda dep, version: {"somethingElse": {"repository": "x/y"}})

    def raise_no_repo(values, image_paths, app_version):
        raise SystemExit(f"error: no repository found at {', '.join(f'{p}.repository' for p in image_paths)}")

    monkeypatch.setattr(vcv, "check_image_versions", raise_no_repo)
    exc = run_main(vcv, monkeypatch, ["zac", "5.4.3", "1.0.297"])
    assert "no repository found" in str(exc)


def test_main_requires_exactly_three_arguments(vcv, monkeypatch):
    exc = run_main(vcv, monkeypatch, ["zac", "5.4.3"])
    assert exc.code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(vcv, monkeypatch, capsys, flag):
    exc = run_main(vcv, monkeypatch, [flag])
    assert exc.code == 0
    assert capsys.readouterr().out == vcv.__doc__ + "\n"
