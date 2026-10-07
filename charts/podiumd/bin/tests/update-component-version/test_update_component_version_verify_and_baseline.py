"""verify_component_version and check_chart_version_lockstep."""

from types import ModuleType

import pytest

# --- verify_component_version ---


def test_verify_component_version_returns_upstream_image_results(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    dep = {"name": "openforms", "alias": "openformulieren", "version": "1.11.0", "repository": "@maykinmedia"}
    digest = "sha256:" + "c" * 64

    monkeypatch.setattr(
        ucv,
        "resolve_chart_values",
        lambda chart_dir, dep_arg, version, allow_pull=True: (
            {"image": {"repository": "maykinmedia/open-forms"}},
            "pulled",
            None,
        ),
    )
    monkeypatch.setattr(
        ucv,
        "check_image_versions",
        lambda values, image_paths, app_version: [
            {
                "path": "image",
                "repository": "maykinmedia/open-forms",
                "host": "docker.io",
                "repo_path": "maykinmedia/open-forms",
                "exists": True,
                "digest": digest,
            }
        ],
    )
    result = ucv.verify_component_version(dep, ["image"], "3.5.6", "1.12.0")
    assert result == {
        "image": {
            "path": "image",
            "repository": "maykinmedia/open-forms",
            "host": "docker.io",
            "repo_path": "maykinmedia/open-forms",
            "exists": True,
            "digest": digest,
        }
    }


def test_verify_component_version_exits_on_pull_failure(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    dep = {"name": "openforms", "repository": "@maykinmedia"}
    monkeypatch.setattr(
        ucv,
        "resolve_chart_values",
        lambda chart_dir, dep_arg, version, allow_pull=True: (None, None, "chart version not found"),
    )
    with pytest.raises(SystemExit):
        ucv.verify_component_version(dep, ["image"], "3.5.6", "9.9.9")


def test_verify_component_version_exits_when_image_does_not_exist(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    dep = {"name": "openforms", "repository": "@maykinmedia"}

    monkeypatch.setattr(
        ucv,
        "resolve_chart_values",
        lambda chart_dir, dep_arg, version, allow_pull=True: (
            {"image": {"repository": "maykinmedia/open-forms"}},
            "pulled",
            None,
        ),
    )
    monkeypatch.setattr(
        ucv,
        "check_image_versions",
        lambda values, image_paths, app_version: [
            {
                "path": "image",
                "repository": "maykinmedia/open-forms",
                "host": "docker.io",
                "repo_path": "maykinmedia/open-forms",
                "exists": False,
                "digest": None,
            }
        ],
    )
    with pytest.raises(SystemExit):
        ucv.verify_component_version(dep, ["image"], "9.9.9", "1.12.0")


def _checked_repositories(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch, component_values):
    """Run verify_component_version against a faked pulled chart; return the
    repository check_image_versions was asked to check."""
    dep = {"name": "openforms", "alias": "openformulieren", "version": "1.11.0", "repository": "@maykinmedia"}
    upstream = {"image": {"repository": "maykinmedia/open-forms", "tag": "3.5.5"}}
    monkeypatch.setattr(
        ucv, "resolve_chart_values", lambda chart_dir, dep_arg, version, allow_pull=True: (upstream, "pulled", None)
    )
    checked = []

    def fake_check(values, image_paths, app_version):
        repo = values["image"]["repository"]
        checked.append(repo)
        return [{"path": "image", "repository": repo, "host": "x", "repo_path": repo, "exists": True, "digest": None}]

    monkeypatch.setattr(ucv, "check_image_versions", fake_check)
    ucv.verify_component_version(dep, ["image"], "3.5.6", "1.12.0", component_values=component_values)
    assert upstream == {"image": {"repository": "maykinmedia/open-forms", "tag": "3.5.5"}}, "pulled values mutated"
    return checked


def test_verify_component_version_checks_podiumd_repository_override(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    component_values = {"image": {"repository": "acr.example.io/open-forms", "tag": "3.5.5"}}
    assert _checked_repositories(ucv, monkeypatch, component_values) == ["acr.example.io/open-forms"]


def test_verify_component_version_falls_back_to_upstream_repository(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    component_values = {"image": {"tag": "3.5.5"}}
    assert _checked_repositories(ucv, monkeypatch, component_values) == ["maykinmedia/open-forms"]


# --- check_chart_version_lockstep ---


def test_check_chart_version_lockstep_refuses_differing_versions(
    ucv: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(
        ucv, "chart_version_lockstep_components", lambda chart_dir: frozenset({"internetaakafhandeling"})
    )

    with pytest.raises(SystemExit) as exc_info:
        ucv.check_chart_version_lockstep("internetaakafhandeling", "3.3.3", "3.3.2", no_chart=False)

    assert exc_info.value.code == 1
    assert "app version 3.3.3 != chart version 3.3.2" in capsys.readouterr().out


def test_check_chart_version_lockstep_accepts_equal_versions(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        ucv, "chart_version_lockstep_components", lambda chart_dir: frozenset({"internetaakafhandeling"})
    )
    ucv.check_chart_version_lockstep("internetaakafhandeling", "3.3.3", "3.3.3", no_chart=False)


def test_check_chart_version_lockstep_ignores_unregistered_component(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        ucv, "chart_version_lockstep_components", lambda chart_dir: frozenset({"internetaakafhandeling"})
    )
    ucv.check_chart_version_lockstep("zac", "5.4.3", "1.0.297", no_chart=False)


def test_check_chart_version_lockstep_ignores_native_component(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ucv, "chart_version_lockstep_components", lambda chart_dir: frozenset({"frankgateway"}))
    ucv.check_chart_version_lockstep("frankgateway", "104", "native", no_chart=True)
