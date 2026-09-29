"""verify-component-version glue: dependency lookup, image_paths_for and the
app-image report lines; lib.chart's chart pull and registry check are mocked."""

from pathlib import Path
from types import ModuleType

import pytest
import yaml

from lib.registry import ImagePathTagCheck
from lib.yaml_types import YamlMapping


def write_chart_yaml(vcv: ModuleType, dependencies):
    """Chart.yaml with `dependencies`, each given a version unless set."""
    versioned = [{"version": "1.0.0", **dep} for dep in dependencies]
    vcv.CHART_YAML.write_text(yaml.safe_dump({"dependencies": versioned}))


# --- find_dependency ---


def test_find_dependency_by_name(vcv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    assert vcv.find_dependency("zaakafhandelcomponent")["alias"] == "zac"


def test_find_dependency_by_alias(vcv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    assert vcv.find_dependency("zac")["name"] == "zaakafhandelcomponent"


def test_find_dependency_not_found_raises(vcv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    with pytest.raises(SystemExit, match="no dependency named or aliased"):
        vcv.find_dependency("totally-unknown")


# --- main() ---


def run_main(vcv: ModuleType, monkeypatch: pytest.MonkeyPatch, argv):
    monkeypatch.setattr("sys.argv", ["verify-component-version", *argv])
    with pytest.raises(SystemExit) as exc_info:
        vcv.main()
    return exc_info.value


def test_main_single_image_component_success(
    vcv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    monkeypatch.setattr(vcv, "verify_chart_version", lambda chart_dir, dep, version: {"image": {"repository": "x/y"}})
    monkeypatch.setattr(
        vcv,
        "check_image_versions",
        lambda values, image_paths, app_version: [
            {
                "path": "image",
                "repository": "ghcr.io/infonl/zaakafhandelcomponent",
                "host": "ghcr.io",
                "repo_path": "infonl/zaakafhandelcomponent",
                "exists": True,
                "digest": "sha256:fake",
            },
        ],
    )

    exc = run_main(vcv, monkeypatch, ["zac", "5.4.3", "1.0.297"])
    assert exc.code == 0
    out = capsys.readouterr().out
    assert "[FOUND  ] ghcr.io/infonl/zaakafhandelcomponent:5.4.3  digest=sha256:fake" in out
    assert "OK: chart + image version(s) exist" in out


def test_main_multi_image_component_checks_both(
    vcv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zgw-office-addin", "repository": "@zgw-office-addin"}])
    checked_paths = []

    def fake_check_image_versions(values, image_paths, app_version):
        checked_paths.extend(image_paths)
        return [
            {
                "path": "frontend.image",
                "repository": "ghcr.io/infonl/zgw-office-addin-frontend",
                "host": "ghcr.io",
                "repo_path": "infonl/zgw-office-addin-frontend",
                "exists": True,
                "digest": "sha256:aaaa",
            },
            {
                "path": "backend.image",
                "repository": "ghcr.io/infonl/zgw-office-addin-backend",
                "host": "ghcr.io",
                "repo_path": "infonl/zgw-office-addin-backend",
                "exists": True,
                "digest": "sha256:bbbb",
            },
        ]

    monkeypatch.setattr(vcv, "verify_chart_version", lambda chart_dir, dep, version: {})
    monkeypatch.setattr(vcv, "check_image_versions", fake_check_image_versions)

    exc = run_main(vcv, monkeypatch, ["zgw-office-addin", "0.11.0", "0.0.92"])
    assert exc.code == 0
    assert checked_paths == ["frontend.image", "backend.image"]


def test_main_alias_argument_resolves_full_multi_path_registration(
    vcv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: image_paths_for is keyed by the Chart.yaml name, not the
    alias, so the alias argument ("kiss") must be resolved to "kiss-chart"
    first or co-registered lockstep paths are silently skipped."""
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "kiss-chart", "alias": "kiss", "repository": "@kiss"}])
    checked_paths = []

    def fake_check_image_versions(values, image_paths, app_version):
        checked_paths.extend(image_paths)
        return [
            {
                "path": "image",
                "repository": "ghcr.io/klantinteractie-servicesysteem/kiss-frontend",
                "host": "ghcr.io",
                "repo_path": "klantinteractie-servicesysteem/kiss-frontend",
                "exists": True,
                "digest": "sha256:aaaa",
            },
            {
                "path": "settings.syncJobs.image",
                "repository": "ghcr.io/klantinteractie-servicesysteem/kiss-elastic-sync",
                "host": "ghcr.io",
                "repo_path": "klantinteractie-servicesysteem/kiss-elastic-sync",
                "exists": True,
                "digest": "sha256:bbbb",
            },
        ]

    monkeypatch.setattr(vcv, "verify_chart_version", lambda chart_dir, dep, version: {})
    monkeypatch.setattr(vcv, "check_image_versions", fake_check_image_versions)

    exc = run_main(vcv, monkeypatch, ["kiss", "3.1.1", "3.1.1"])
    assert exc.code == 0
    assert checked_paths == ["image", "settings.syncJobs.image"]


def test_main_dockerhub_component(
    vcv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """The registry is inferred from the repository (Docker Hub here), not assumed ghcr."""
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "openforms", "alias": "openformulieren", "repository": "@maykinmedia"}])
    monkeypatch.setattr(vcv, "verify_chart_version", lambda chart_dir, dep, version: {})
    monkeypatch.setattr(
        vcv,
        "check_image_versions",
        lambda values, image_paths, app_version: [
            {
                "path": "image",
                "repository": "openformulieren/open-forms",
                "host": "docker.io",
                "repo_path": "openformulieren/open-forms",
                "exists": True,
                "digest": "sha256:fake",
            },
        ],
    )

    exc = run_main(vcv, monkeypatch, ["openformulieren", "3.5.6", "1.12.0"])
    assert exc.code == 0
    assert "docker.io/openformulieren/open-forms:3.5.6" in capsys.readouterr().out


def test_main_missing_chart_version_propagates(vcv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """verify_chart_version's own FAIL exit must propagate, not be swallowed."""
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])

    def raise_pull_failure(chart_dir, dep, version):
        raise SystemExit(1)

    monkeypatch.setattr(vcv, "verify_chart_version", raise_pull_failure)
    exc = run_main(vcv, monkeypatch, ["zac", "5.4.3", "9.9.9"])
    assert exc.code == 1


def test_main_missing_app_version_fails(
    vcv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    monkeypatch.setattr(vcv, "verify_chart_version", lambda chart_dir, dep, version: {"image": {"repository": "x/y"}})
    monkeypatch.setattr(
        vcv,
        "check_image_versions",
        lambda values, image_paths, app_version: [
            {
                "path": "image",
                "repository": "ghcr.io/infonl/zaakafhandelcomponent",
                "host": "ghcr.io",
                "repo_path": "infonl/zaakafhandelcomponent",
                "exists": False,
                "digest": None,
            },
        ],
    )

    exc = run_main(vcv, monkeypatch, ["zac", "9.9.9", "1.0.297"])
    assert exc.code == 1
    out = capsys.readouterr().out
    assert "[MISSING]" in out
    assert "FAIL: one or more app image versions" in out


def test_main_no_repository_at_configured_path_propagates(
    vcv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """check_image_versions' own SystemExit for unresolvable paths propagates."""
    monkeypatch.setattr(vcv, "CHART_YAML", tmp_path / "Chart.yaml")
    write_chart_yaml(vcv, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    monkeypatch.setattr(
        vcv, "verify_chart_version", lambda chart_dir, dep, version: {"somethingElse": {"repository": "x/y"}}
    )

    def raise_no_repo(values, image_paths, app_version):
        msg = f"error: no repository found at {', '.join(f'{p}.repository' for p in image_paths)}"
        raise SystemExit(msg)

    monkeypatch.setattr(vcv, "check_image_versions", raise_no_repo)
    exc = run_main(vcv, monkeypatch, ["zac", "5.4.3", "1.0.297"])
    assert "no repository found" in str(exc)


def test_main_requires_exactly_three_arguments(vcv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    exc = run_main(vcv, monkeypatch, ["zac", "5.4.3"])
    assert exc.code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(
    vcv: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], flag
):
    exc = run_main(vcv, monkeypatch, [flag])
    assert exc.code == 0
    assert capsys.readouterr().out == f"{vcv.__doc__}\n"


def test_main_native_component_reads_podiumd_values(
    vcv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """chart-version "native": no chart pull; the image repositories come
    from podiumd's own values.yaml block of the native component."""
    monkeypatch.setattr(vcv, "CHART_DIR", tmp_path)
    (tmp_path / "values.yaml").write_text(yaml.safe_dump({"frankgateway": {"image": {"repository": "x/fg"}}}))

    def no_chart_pull(*_args: object) -> None:
        pytest.fail("must not pull a chart")

    monkeypatch.setattr(vcv, "verify_chart_version", no_chart_pull)
    seen = {}

    def fake_check_image_versions(
        values: YamlMapping, image_paths: list[str], app_version: str
    ) -> list[ImagePathTagCheck]:
        seen.update(values=values, image_paths=image_paths)
        return [
            {
                "path": "image",
                "repository": "x/fg",
                "host": "docker.io",
                "repo_path": "x/fg",
                "exists": True,
                "digest": None,
            }
        ]

    monkeypatch.setattr(vcv, "check_image_versions", fake_check_image_versions)

    exc = run_main(vcv, monkeypatch, ["FrankGateway", "104", "Native"])

    assert exc.code == 0
    assert seen == {"values": {"image": {"repository": "x/fg"}}, "image_paths": ["image"]}
    assert "[FOUND  ] docker.io/x/fg:104" in capsys.readouterr().out


def test_main_native_rejects_a_non_native_component(
    vcv: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(vcv, "CHART_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["verify-component-version", "zac", "5.4.3", "native"])
    with pytest.raises(SystemExit, match="only valid for a component in"):
        vcv.main()
