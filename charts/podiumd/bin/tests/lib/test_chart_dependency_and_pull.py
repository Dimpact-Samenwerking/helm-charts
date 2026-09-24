"""lib.chart — dependency lookup, per-baseline component state, and
`helm pull` glue: find_dependency, find_app_versions,
component_state_at_baseline, chart_ref, local_chart_dir, pull_chart,
pulled_chart_dir, pull_chart_values. `helm pull` is mocked via
lib.procutil.run, so no `helm` binary or network access needed. Split out
of the former test_chart.py (see the other test_chart_*.py files for the
rest)."""

from pathlib import Path
from types import ModuleType

import pytest
import yaml

# --- find_dependency ---


def test_find_dependency_by_name(libchartvaluestreeprimitives):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac"}]
    assert libchartvaluestreeprimitives.find_dependency(deps, "zaakafhandelcomponent")["alias"] == "zac"


def test_find_dependency_by_alias(libchartvaluestreeprimitives):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac"}]
    assert libchartvaluestreeprimitives.find_dependency(deps, "zac")["name"] == "zaakafhandelcomponent"


def test_find_dependency_not_found_returns_none(libchartvaluestreeprimitives):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac"}]
    assert libchartvaluestreeprimitives.find_dependency(deps, "totally-unknown") is None


def test_find_dependency_ignores_case(libchartvaluestreeprimitives: ModuleType) -> None:
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac"}]
    assert libchartvaluestreeprimitives.find_dependency(deps, "ZAC") is deps[0]
    assert libchartvaluestreeprimitives.find_dependency(deps, "ZaakAfhandelComponent") is deps[0]


def test_find_dependency_exact_match_wins_over_case_insensitive_one(libchartvaluestreeprimitives: ModuleType) -> None:
    deps = [{"name": "Zac"}, {"name": "zac"}]
    assert libchartvaluestreeprimitives.find_dependency(deps, "zac") is deps[1]


def test_find_dependency_exits_when_case_insensitive_match_is_ambiguous(
    libchartvaluestreeprimitives: ModuleType,
) -> None:
    deps = [{"name": "Zac"}, {"name": "zAC"}]
    with pytest.raises(SystemExit, match="more than one dependency"):
        libchartvaluestreeprimitives.find_dependency(deps, "zac")


def test_values_key_of_is_the_alias_or_else_the_name(libchartvaluestreeprimitives: ModuleType) -> None:
    assert libchartvaluestreeprimitives.values_key_of({"name": "zaakafhandelcomponent", "alias": "zac"}) == "zac"
    assert libchartvaluestreeprimitives.values_key_of({"name": "clamav", "alias": ""}) == "clamav"
    assert libchartvaluestreeprimitives.values_key_of({"name": "clamav"}) == "clamav"


def test_dep_for_values_key_matches_the_values_key_only(libchartvaluestreeprimitives: ModuleType) -> None:
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac"}]
    assert libchartvaluestreeprimitives.dep_for_values_key(deps, "zac") is deps[0]
    assert libchartvaluestreeprimitives.dep_for_values_key(deps, "zaakafhandelcomponent") is None


def test_require_dependency_exits_naming_the_chart_yaml(
    libchartvaluestreeprimitives: ModuleType, tmp_path: Path
) -> None:
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text(yaml.safe_dump({"dependencies": [{"name": "clamav", "version": "3.7.2"}]}), encoding="utf-8")
    assert libchartvaluestreeprimitives.require_dependency(chart_yaml, "ClamAV") == {
        "name": "clamav",
        "version": "3.7.2",
    }
    with pytest.raises(SystemExit, match=r"no dependency named or aliased 'nope' found in .*Chart\.yaml"):
        libchartvaluestreeprimitives.require_dependency(chart_yaml, "nope")


# --- find_app_versions ---
# used by show-component-baseline-version, via component_state_at_baseline
# below.


def test_find_app_versions_single_image(libchartvaluestreeprimitives):
    values = {"zac": {"image": {"tag": "5.0.2@sha256:abc"}}}
    assert libchartvaluestreeprimitives.find_app_versions(values, "zac", ["image"]) == [("image", "5.0.2@sha256:abc")]


def test_find_app_versions_multi_image(libchartvaluestreeprimitives):
    values = {
        "zgw-office-addin": {
            "frontend": {"image": {"tag": "v0.9.313@sha256:a"}},
            "backend": {"image": {"tag": "v0.9.313@sha256:b"}},
        }
    }
    result = libchartvaluestreeprimitives.find_app_versions(
        values, "zgw-office-addin", ["frontend.image", "backend.image"]
    )
    assert result == [("frontend.image", "v0.9.313@sha256:a"), ("backend.image", "v0.9.313@sha256:b")]


def test_find_app_versions_missing_key_returns_empty(libchartvaluestreeprimitives):
    assert libchartvaluestreeprimitives.find_app_versions({}, "zac", ["image"]) == []


def test_find_app_versions_empty_tag_is_skipped(libchartvaluestreeprimitives):
    values = {"zac": {"image": {"tag": ""}}}
    assert libchartvaluestreeprimitives.find_app_versions(values, "zac", ["image"]) == []


# --- component_state_at_baseline ---
# the full "resolve a component's baseline state via the shared release-
# baseline primitive" pipeline shared by show-component-baseline-version
# (show-image-baseline-version resolves a single image pin directly
# instead — see find_app_versions' own docstring). lib.release_baseline.
# resolve_baseline_chart_state itself (and the real git plumbing it
# wraps) has its own test coverage (tests/lib/test_release_baseline.py)
# — these tests mock IT out and only exercise this function's own glue:
# finding the dependency and looking up its app version(s) on top of
# whatever resolve_baseline_chart_state returns.


def test_component_state_at_baseline_success(monkeypatch, tmp_path, libchartrepoandpathresolution):
    """chart_dir is a real Path (not the opaque "chart_dir" placeholder the
    two error-path tests below use) since this one actually reaches
    image_paths_for(component, chart_dir) -- which now reads chart_dir/
    etc/settings.yaml (missing here, so it falls back to the ["image"]
    default) -- the other two tests return before ever calling it."""
    monkeypatch.setattr(
        libchartrepoandpathresolution,
        "resolve_baseline_chart_state",
        lambda chart_dir, baseline: (
            "podiumd-4.8.5",
            [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}],
            {"zac": {"image": {"tag": "5.0.2@sha256:abc"}}},
            ["zac:", "  image:", '    tag: "5.0.2@sha256:abc"'],
            None,
        ),
    )

    ref, dep, values_key, image_paths, app_versions, error = libchartrepoandpathresolution.component_state_at_baseline(
        tmp_path, "charts/podiumd", "4.8.5", "zac"
    )

    assert error is None
    assert ref == "podiumd-4.8.5"
    assert dep["name"] == "zaakafhandelcomponent"
    assert values_key == "zac"
    assert image_paths == ["image"]
    assert app_versions == [("image", "5.0.2@sha256:abc")]


def test_component_state_at_baseline_propagates_resolve_baseline_chart_state_error(
    monkeypatch, libchartrepoandpathresolution
):
    monkeypatch.setattr(
        libchartrepoandpathresolution,
        "resolve_baseline_chart_state",
        lambda chart_dir, baseline: (None, [], {}, [], "could not resolve baseline '9.9.9' to a git ref (tried ...)"),
    )

    ref, dep, values_key, image_paths, app_versions, error = libchartrepoandpathresolution.component_state_at_baseline(
        "chart_dir", "charts/podiumd", "9.9.9", "zac"
    )

    assert ref is dep is values_key is image_paths is app_versions is None
    assert error == "could not resolve baseline '9.9.9' to a git ref (tried ...)"


def test_component_state_at_baseline_dependency_not_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, libchartrepoandpathresolution: ModuleType
) -> None:
    monkeypatch.setattr(
        libchartrepoandpathresolution,
        "resolve_baseline_chart_state",
        lambda chart_dir, baseline: ("podiumd-4.8.5", [], {}, [], None),
    )

    ref, dep, values_key, image_paths, app_versions, error = libchartrepoandpathresolution.component_state_at_baseline(
        tmp_path, "charts/podiumd", "4.8.5", "totally-unknown"
    )

    assert ref is dep is values_key is image_paths is app_versions is None
    assert error == ("no dependency named or aliased 'totally-unknown' in charts/podiumd/Chart.yaml at podiumd-4.8.5")


def test_component_state_at_baseline_native_component(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, libchartrepoandpathresolution: ModuleType
) -> None:
    """A native component (settings.yaml default: frankgateway) resolves
    without a Chart.yaml dependency: dep None, its own name as the key."""
    values = {"frankgateway": {"image": {"tag": "104@sha256:abc"}}}

    def baseline_state(_chart_dir: Path, _baseline: str) -> tuple[str, list[dict], dict, list[str], None]:
        return "podiumd-4.9.1", [], values, [], None

    monkeypatch.setattr(libchartrepoandpathresolution, "resolve_baseline_chart_state", baseline_state)

    ref, dep, values_key, image_paths, app_versions, error = libchartrepoandpathresolution.component_state_at_baseline(
        tmp_path, "charts/podiumd", "4.9.1", "FrankGateway"
    )

    assert (ref, dep, values_key, error) == ("podiumd-4.9.1", None, "frankgateway", None)
    assert image_paths == ["image"]
    assert app_versions == [("image", "104@sha256:abc")]


# --- chart_ref ---


def test_chart_ref_alias_repository(libchartpullandsubchartresolution):
    ref, repo_url = libchartpullandsubchartresolution.chart_ref({"name": "zaakafhandelcomponent", "repository": "@zac"})
    assert ref == "zac/zaakafhandelcomponent"
    assert repo_url is None


def test_chart_ref_oci_repository(libchartpullandsubchartresolution):
    ref, repo_url = libchartpullandsubchartresolution.chart_ref(
        {"name": "internetaakafhandeling", "repository": "oci://ghcr.io/interne-taak-afhandeling"}
    )
    assert ref == "oci://ghcr.io/interne-taak-afhandeling/internetaakafhandeling"
    assert repo_url is None


def test_chart_ref_https_repository(libchartpullandsubchartresolution):
    ref, repo_url = libchartpullandsubchartresolution.chart_ref(
        {"name": "openforms", "repository": "https://maykinmedia.github.io/charts/"}
    )
    assert ref == "openforms"
    assert repo_url == "https://maykinmedia.github.io/charts/"


def test_chart_ref_file_repository_returns_none_none(libchartpullandsubchartresolution):
    assert libchartpullandsubchartresolution.chart_ref({"name": "mi-data", "repository": "file://../mi-data"}) == (
        None,
        None,
    )


def test_chart_ref_unsupported_scheme_raises(libchartpullandsubchartresolution):
    with pytest.raises(SystemExit, match="unsupported repository scheme"):
        libchartpullandsubchartresolution.chart_ref({"name": "x", "repository": "ftp://nope"})


# --- local_chart_dir ---


def test_local_chart_dir_resolves_relative_to_chart_dir(tmp_path, libchartpullandsubchartresolution):
    dep = {"name": "mi-data", "repository": "file://../mi-data"}
    assert (
        libchartpullandsubchartresolution.local_chart_dir(tmp_path / "podiumd", dep) == (tmp_path / "mi-data").resolve()
    )


def test_local_chart_dir_none_for_other_schemes(libchartpullandsubchartresolution):
    assert libchartpullandsubchartresolution.local_chart_dir(Path("/x"), {"name": "zac", "repository": "@zac"}) is None
    assert (
        libchartpullandsubchartresolution.local_chart_dir(Path("/x"), {"name": "zac", "repository": "oci://ghcr.io/x"})
        is None
    )


# --- pull_chart ---


def test_pull_chart_local_repository_fails_without_subprocess(tmp_path, libchartpullandsubchartresolution):
    dep = {"name": "mi-data", "repository": "file://../mi-data"}
    ok, stderr = libchartpullandsubchartresolution.pull_chart(dep, "1.0.0", tmp_path)
    assert ok is False
    assert "not fetchable remotely" in stderr


def test_pull_chart_builds_correct_command(monkeypatch, tmp_path, libchartpullandsubchartresolution):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        from types import SimpleNamespace

        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(libchartpullandsubchartresolution, "run", fake_run)
    dep = {"name": "zaakafhandelcomponent", "repository": "@zac"}
    ok, _stderr = libchartpullandsubchartresolution.pull_chart(dep, "1.0.297", tmp_path)
    assert ok is True
    assert captured["cmd"] == [
        "helm",
        "pull",
        "zac/zaakafhandelcomponent",
        "--version",
        "1.0.297",
        "--untar",
        "--untardir",
        str(tmp_path),
    ]


def test_pull_chart_https_repo_adds_repo_flag(monkeypatch, tmp_path, libchartpullandsubchartresolution):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        from types import SimpleNamespace

        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(libchartpullandsubchartresolution, "run", fake_run)
    dep = {"name": "openforms", "repository": "https://maykinmedia.github.io/charts/"}
    libchartpullandsubchartresolution.pull_chart(dep, "1.12.0", tmp_path)
    assert "--repo" in captured["cmd"]
    assert "https://maykinmedia.github.io/charts/" in captured["cmd"]


def test_pull_chart_failure_returns_stderr(monkeypatch, tmp_path, libchartpullandsubchartresolution):
    def fake_run(cmd, **kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(returncode=1, stdout="", stderr="version not found\n")

    monkeypatch.setattr(libchartpullandsubchartresolution, "run", fake_run)
    dep = {"name": "zaakafhandelcomponent", "repository": "@zac"}
    ok, stderr = libchartpullandsubchartresolution.pull_chart(dep, "9.9.9", tmp_path)
    assert ok is False
    assert stderr == "version not found"


# --- pulled_chart_dir ---


def test_pulled_chart_dir_returns_the_single_directory(tmp_path, libchartpullandsubchartresolution):
    (tmp_path / "somechart").mkdir()
    (tmp_path / "somefile.txt").write_text("x")
    assert libchartpullandsubchartresolution.pulled_chart_dir(tmp_path) == tmp_path / "somechart"


def test_pulled_chart_dir_raises_when_empty(tmp_path, libchartpullandsubchartresolution):
    with pytest.raises(SystemExit, match="produced no chart directory"):
        libchartpullandsubchartresolution.pulled_chart_dir(tmp_path)


# --- pull_chart_values ---


def test_pull_chart_values_reads_pulled_values_yaml(monkeypatch, libchartpullandsubchartresolution):
    def fake_pull_chart(dep, version, dest):
        chart_dir = dest / dep["name"]
        chart_dir.mkdir(parents=True)
        (chart_dir / "values.yaml").write_text(
            yaml.safe_dump({"image": {"repository": "maykinmedia/open-forms"}}), encoding="utf-8"
        )
        return True, ""

    monkeypatch.setattr(libchartpullandsubchartresolution, "pull_chart", fake_pull_chart)
    dep = {"name": "openforms", "repository": "@maykinmedia"}
    values = libchartpullandsubchartresolution.pull_chart_values(dep, "1.12.0")
    assert values == {"image": {"repository": "maykinmedia/open-forms"}}


def test_pull_chart_values_raises_on_pull_failure(monkeypatch, libchartpullandsubchartresolution):
    monkeypatch.setattr(
        libchartpullandsubchartresolution, "pull_chart", lambda dep, version, dest: (False, "not found")
    )
    dep = {"name": "openforms", "repository": "@maykinmedia"}
    with pytest.raises(SystemExit, match="could not pull"):
        libchartpullandsubchartresolution.pull_chart_values(dep, "9.9.9")
