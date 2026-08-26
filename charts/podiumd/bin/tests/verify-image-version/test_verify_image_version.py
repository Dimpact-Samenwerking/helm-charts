"""find_dependency and main() for verify-image-version.py. `pull_chart_values`
(the actual `helm pull` + values.yaml read) and `check_image_versions` (the
actual registry check, shared with update-component-version.py's own
pre-write gate — see lib.chart.check_image_versions) are both covered by
tests/lib/test_chart.py; these tests mock them out and only exercise this
script's own glue: looking up the Chart.yaml dependency, resolving
image_paths_for(component), and reporting FOUND/MISSING/OK/FAIL."""
import pytest
import yaml


def write_chart_yaml(viv, dependencies):
    viv.CHART_YAML.write_text(yaml.safe_dump({"dependencies": dependencies}))


# --- find_dependency ---

def test_find_dependency_by_name(viv, tmp_path, monkeypatch):
    monkeypatch.setattr(viv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(viv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    assert viv.find_dependency("zaakafhandelcomponent")["alias"] == "zac"


def test_find_dependency_by_alias(viv, tmp_path, monkeypatch):
    monkeypatch.setattr(viv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(viv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    assert viv.find_dependency("zac")["name"] == "zaakafhandelcomponent"


def test_find_dependency_not_found_raises(viv, tmp_path, monkeypatch):
    monkeypatch.setattr(viv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(viv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    with pytest.raises(SystemExit, match="no dependency named or aliased"):
        viv.find_dependency("totally-unknown")


# --- main() ---

def run_main(viv, monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["verify-image-version.py", *argv])
    with pytest.raises(SystemExit) as exc_info:
        viv.main()
    return exc_info.value


def test_main_single_image_component_success(viv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(viv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(viv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    monkeypatch.setattr(viv, "pull_chart_values", lambda dep, version: {"image": {"repository": "x/y"}})
    monkeypatch.setattr(viv, "check_image_versions", lambda values, image_paths, app_version: [
        {"path": "image", "repository": "ghcr.io/infonl/zaakafhandelcomponent", "host": "ghcr.io",
         "repo_path": "infonl/zaakafhandelcomponent", "exists": True, "digest": "sha256:fake"},
    ])

    exc = run_main(viv, monkeypatch, ["zac", "5.4.3", "1.0.297"])
    assert exc.code == 0
    out = capsys.readouterr().out
    assert "[FOUND  ] ghcr.io/infonl/zaakafhandelcomponent:5.4.3  digest=sha256:fake" in out
    assert "OK: image version(s) exist" in out


def test_main_multi_image_component_checks_both(viv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(viv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(viv, [{"name": "zgw-office-addin", "repository": "@zgw-office-addin"}])
    checked_paths = []

    def fake_check_image_versions(values, image_paths, app_version):
        checked_paths.extend(image_paths)
        return [
            {"path": "frontend.image", "repository": "ghcr.io/infonl/zgw-office-addin-frontend", "host": "ghcr.io",
             "repo_path": "infonl/zgw-office-addin-frontend", "exists": True, "digest": "sha256:aaaa"},
            {"path": "backend.image", "repository": "ghcr.io/infonl/zgw-office-addin-backend", "host": "ghcr.io",
             "repo_path": "infonl/zgw-office-addin-backend", "exists": True, "digest": "sha256:bbbb"},
        ]

    monkeypatch.setattr(viv, "pull_chart_values", lambda dep, version: {})
    monkeypatch.setattr(viv, "check_image_versions", fake_check_image_versions)

    exc = run_main(viv, monkeypatch, ["zgw-office-addin", "0.11.0", "0.0.92"])
    assert exc.code == 0
    assert checked_paths == ["frontend.image", "backend.image"]


def test_main_dockerhub_component(viv, tmp_path, monkeypatch, capsys):
    """openformulieren ships on Docker Hub — the registry must be inferred
    from the repository string, not assumed to be ghcr for everything."""
    monkeypatch.setattr(viv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(viv, [{"name": "openforms", "alias": "openformulieren", "repository": "@maykinmedia"}])
    monkeypatch.setattr(viv, "pull_chart_values", lambda dep, version: {})
    monkeypatch.setattr(viv, "check_image_versions", lambda values, image_paths, app_version: [
        {"path": "image", "repository": "openformulieren/open-forms", "host": "docker.io",
         "repo_path": "openformulieren/open-forms", "exists": True, "digest": "sha256:fake"},
    ])

    exc = run_main(viv, monkeypatch, ["openformulieren", "3.5.6", "1.12.0"])
    assert exc.code == 0
    assert "docker.io/openformulieren/open-forms:3.5.6" in capsys.readouterr().out


def test_main_missing_chart_version_propagates_pull_failure(viv, tmp_path, monkeypatch):
    """pull_chart_values (lib.chart) already raises SystemExit with a clear
    message when the chart version can't be pulled — main() has nothing to
    add here, so this just confirms it isn't swallowed."""
    monkeypatch.setattr(viv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(viv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])

    def raise_pull_failure(dep, version):
        raise SystemExit(f"error: could not pull {dep['name']} {version}: version not found")

    monkeypatch.setattr(viv, "pull_chart_values", raise_pull_failure)
    exc = run_main(viv, monkeypatch, ["zac", "5.4.3", "9.9.9"])
    assert "could not pull" in str(exc)


def test_main_missing_app_version_fails(viv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(viv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(viv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    monkeypatch.setattr(viv, "pull_chart_values", lambda dep, version: {"image": {"repository": "x/y"}})
    monkeypatch.setattr(viv, "check_image_versions", lambda values, image_paths, app_version: [
        {"path": "image", "repository": "ghcr.io/infonl/zaakafhandelcomponent", "host": "ghcr.io",
         "repo_path": "infonl/zaakafhandelcomponent", "exists": False, "digest": None},
    ])

    exc = run_main(viv, monkeypatch, ["zac", "9.9.9", "1.0.297"])
    assert exc.code == 1
    out = capsys.readouterr().out
    assert "[MISSING]" in out
    assert "FAIL: one or more app image versions" in out


def test_main_no_repository_at_configured_path_propagates(viv, tmp_path, monkeypatch):
    """check_image_versions (lib.chart) already raises SystemExit with a
    clear message when none of COMPONENT_IMAGE_PATHS resolves to a
    repository — main() has nothing to add here either."""
    monkeypatch.setattr(viv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(viv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    monkeypatch.setattr(viv, "pull_chart_values", lambda dep, version: {"somethingElse": {"repository": "x/y"}})

    def raise_no_repo(values, image_paths, app_version):
        raise SystemExit(f"error: no repository found at {', '.join(f'{p}.repository' for p in image_paths)}")

    monkeypatch.setattr(viv, "check_image_versions", raise_no_repo)
    exc = run_main(viv, monkeypatch, ["zac", "5.4.3", "1.0.297"])
    assert "no repository found" in str(exc)


def test_main_requires_exactly_three_arguments(viv, monkeypatch):
    exc = run_main(viv, monkeypatch, ["zac", "5.4.3"])
    assert exc.code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(viv, monkeypatch, capsys, flag):
    exc = run_main(viv, monkeypatch, [flag])
    assert exc.code == 0
    assert capsys.readouterr().out == viv.__doc__ + "\n"
