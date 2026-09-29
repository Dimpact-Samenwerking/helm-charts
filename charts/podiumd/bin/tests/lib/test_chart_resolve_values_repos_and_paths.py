"""lib.chart: resolving chart values and grouping image repositories by path.

`helm pull` is mocked, so no `helm` binary or network access is needed.
"""

import io
import tarfile

from pathlib import Path
from types import ModuleType

import pytest
import yaml


def make_tgz(charts_dir, name, version, values, templates=None, chart_yaml=None, raw_files=None):
    """Write a minimal vendored <name>-<version>.tgz.

    `templates` ({filename: text}) go under <name>/templates/, `chart_yaml`
    becomes <name>/Chart.yaml, and `raw_files` ({tar path: text}) are written
    verbatim, for content yaml.safe_dump can't produce (commented-out lines).
    """
    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    data = yaml.safe_dump(values).encode("utf-8")
    with tarfile.open(tgz_path, "w:gz") as tar:
        info = tarfile.TarInfo(name=f"{name}/values.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        for filename, text in (templates or {}).items():
            tpl_data = text.encode("utf-8")
            tpl_info = tarfile.TarInfo(name=f"{name}/templates/{filename}")
            tpl_info.size = len(tpl_data)
            tar.addfile(tpl_info, io.BytesIO(tpl_data))
        if chart_yaml is not None:
            chart_data = yaml.safe_dump(chart_yaml).encode("utf-8")
            chart_info = tarfile.TarInfo(name=f"{name}/Chart.yaml")
            chart_info.size = len(chart_data)
            tar.addfile(chart_info, io.BytesIO(chart_data))
        for internal_path, text in (raw_files or {}).items():
            raw_data = text.encode("utf-8")
            raw_info = tarfile.TarInfo(name=internal_path)
            raw_info.size = len(raw_data)
            tar.addfile(raw_info, io.BytesIO(raw_data))
    return tgz_path


# --- resolve_chart_values ---


def test_resolve_chart_values_prefers_vendored_over_pulling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libchartpullandsubchartresolution: ModuleType
):
    def raise_if_pulled(dep, version, dest):
        msg = "should not pull — already vendored at this exact version"
        raise AssertionError(msg)

    monkeypatch.setattr(libchartpullandsubchartresolution, "pull_chart", raise_if_pulled)
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {"repository": "openzaak/open-zaak"}})
    dep = {"name": "openzaak", "version": "1.14.2"}

    values, source, error = libchartpullandsubchartresolution.resolve_chart_values(tmp_path, dep, "1.14.2")

    assert values == {"image": {"repository": "openzaak/open-zaak"}}
    assert source == "vendored"
    assert error is None


def test_resolve_chart_values_falls_back_to_pull_when_not_vendored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libchartpullandsubchartresolution: ModuleType
):
    def fake_pull_chart(dep, version, dest):
        chart_dir = dest / dep["name"]
        chart_dir.mkdir(parents=True)
        (chart_dir / "values.yaml").write_text(
            yaml.safe_dump({"image": {"repository": "openzaak/open-zaak"}}), encoding="utf-8"
        )
        return True, ""

    monkeypatch.setattr(libchartpullandsubchartresolution, "pull_chart", fake_pull_chart)
    dep = {"name": "openzaak", "version": "1.15.0"}  # not the vendored 1.14.2 from the test above

    values, source, error = libchartpullandsubchartresolution.resolve_chart_values(tmp_path, dep, "1.15.0")

    assert values == {"image": {"repository": "openzaak/open-zaak"}}
    assert source == "pulled"
    assert error is None


def test_resolve_chart_values_pull_failure_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libchartpullandsubchartresolution: ModuleType
):
    monkeypatch.setattr(
        libchartpullandsubchartresolution, "pull_chart", lambda dep, version, dest: (False, "version not found")
    )
    dep = {"name": "openzaak", "version": "9.9.9"}

    values, source, error = libchartpullandsubchartresolution.resolve_chart_values(tmp_path, dep, "9.9.9")

    assert values is None
    assert source is None
    assert error == "version not found"


def test_resolve_chart_values_no_pull_allowed_and_not_vendored_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libchartpullandsubchartresolution: ModuleType
):
    def raise_if_pulled(dep, version, dest):
        msg = "should not pull — allow_pull is False"
        raise AssertionError(msg)

    monkeypatch.setattr(libchartpullandsubchartresolution, "pull_chart", raise_if_pulled)
    dep = {"name": "openzaak", "version": "1.15.0"}

    values, source, error = libchartpullandsubchartresolution.resolve_chart_values(
        tmp_path, dep, "1.15.0", allow_pull=False
    )

    assert values is None
    assert source is None
    assert "not vendored" in error


# --- primary_image_repositories ---


def test_primary_image_repositories_own_override_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libchartpullandsubchartresolution: ModuleType
):
    def raise_if_pulled(dep, version, dest):
        msg = "own override present — should never consult the subchart"
        raise AssertionError(msg)

    monkeypatch.setattr(libchartpullandsubchartresolution, "pull_chart", raise_if_pulled)
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    own_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}}

    repos, error = libchartpullandsubchartresolution.primary_image_repositories(
        tmp_path, dep, own_values, allow_pull=False
    )

    assert repos == {"image": "ghcr.io/infonl/zaakafhandelcomponent"}
    assert error is None


def test_primary_image_repositories_falls_back_to_subchart_default(
    tmp_path: Path, libchartpullandsubchartresolution: ModuleType
):
    """Only a "tag:" override: the repository comes from the vendored subchart default."""
    make_tgz(tmp_path / "charts", "openzaak", "4.9.1", {"image": {"repository": "openzaak/open-zaak"}})
    dep = {"name": "openzaak", "alias": "", "version": "4.9.1"}
    own_values = {"openzaak": {"image": {"tag": "3.28.0@sha256:aaaa"}}}

    repos, error = libchartpullandsubchartresolution.primary_image_repositories(
        tmp_path, dep, own_values, allow_pull=False
    )

    assert repos == {"image": "openzaak/open-zaak"}
    assert error is None


def test_primary_image_repositories_multi_path_component_reads_subchart_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, libchartpullandsubchartresolution: ModuleType
):
    """Two primary paths without overrides read the vendored subchart values only once."""
    make_tgz(
        tmp_path / "charts",
        "zgw-office-addin",
        "0.0.92",
        {
            "frontend": {"image": {"repository": "ghcr.io/infonl/zgw-office-addin-frontend"}},
            "backend": {"image": {"repository": "ghcr.io/infonl/zgw-office-addin-backend"}},
        },
    )
    dep = {"name": "zgw-office-addin", "alias": "", "version": "0.0.92"}
    calls = []
    real_subchart_values = libchartpullandsubchartresolution.subchart_values

    def spy(chart_dir, dep_arg, version=None):
        calls.append(dep_arg["name"])
        return real_subchart_values(chart_dir, dep_arg, version)

    monkeypatch.setattr(libchartpullandsubchartresolution, "subchart_values", spy)

    repos, error = libchartpullandsubchartresolution.primary_image_repositories(tmp_path, dep, {}, allow_pull=False)

    assert repos == {
        "frontend.image": "ghcr.io/infonl/zgw-office-addin-frontend",
        "backend.image": "ghcr.io/infonl/zgw-office-addin-backend",
    }
    assert error is None
    assert calls == ["zgw-office-addin"]  # fetched once, reused for the second path


def test_primary_image_repositories_unresolvable_without_vendored_chart(
    tmp_path: Path, libchartpullandsubchartresolution: ModuleType
):
    dep = {"name": "openzaak", "alias": "", "version": "4.9.1"}
    own_values = {"openzaak": {"image": {"tag": "3.28.0@sha256:aaaa"}}}

    repos, error = libchartpullandsubchartresolution.primary_image_repositories(
        tmp_path, dep, own_values, allow_pull=False
    )

    assert repos == {"image": None}
    assert error is not None


def test_primary_image_repositories_chart_dir_none_is_safe_when_unneeded(libchartpullandsubchartresolution: ModuleType):
    """chart_dir=None is fine when no path needs the subchart fallback."""
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    own_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}}

    repos, error = libchartpullandsubchartresolution.primary_image_repositories(None, dep, own_values, allow_pull=False)

    assert repos == {"image": "ghcr.io/infonl/zaakafhandelcomponent"}
    assert error is None


def test_primary_image_repositories_chart_dir_none_and_needed_returns_error(
    libchartpullandsubchartresolution: ModuleType,
):
    dep = {"name": "openzaak", "alias": "", "version": "4.9.1"}
    own_values = {"openzaak": {"image": {"tag": "3.28.0@sha256:aaaa"}}}

    repos, error = libchartpullandsubchartresolution.primary_image_repositories(None, dep, own_values, allow_pull=False)

    assert repos == {"image": None}
    assert error is not None


# --- strip_registry_host ---


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("quay.io/keycloak/keycloak", "keycloak/keycloak"),
        ("docker.io/maykinmedia/open-inwoner", "maykinmedia/open-inwoner"),
        ("ghcr.io/infonl/zaakafhandelcomponent", "infonl/zaakafhandelcomponent"),
        ("docker.io/library/redis", "library/redis"),
        ("localhost:5000/foo/bar", "foo/bar"),
        ("acrprodmgmt.azurecr.io/infonl/zac:5.4.4", "infonl/zac:5.4.4"),
        ("infonl/zaakafhandelcomponent", "infonl/zaakafhandelcomponent"),  # already stripped
        ("ghcr.io/infonl/zaakafhandelcomponent@sha256:aaaa", "infonl/zaakafhandelcomponent"),
    ],
)
def test_strip_registry_host(libchartvaluestreeprimitives: ModuleType, url, expected):
    assert libchartvaluestreeprimitives.strip_registry_host(url) == expected


# --- repository_path_map ---


def test_repository_path_map_own_override(tmp_path: Path, libchartrepoandpathresolution: ModuleType):
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    own_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}}

    mapping = libchartrepoandpathresolution.repository_path_map(
        tmp_path, [dep], own_values, [("zac", "image")], allow_pull=False
    )

    assert mapping == {"infonl/zaakafhandelcomponent": ("zac", "image")}


def test_repository_path_map_subchart_default(tmp_path: Path, libchartrepoandpathresolution: ModuleType):
    make_tgz(tmp_path / "charts", "openzaak", "4.9.1", {"image": {"repository": "openzaak/open-zaak"}})
    dep = {"name": "openzaak", "alias": "", "version": "4.9.1"}
    own_values = {"openzaak": {"image": {"tag": "3.28.0@sha256:aaaa"}}}

    mapping = libchartrepoandpathresolution.repository_path_map(
        tmp_path, [dep], own_values, [("openzaak", "image")], allow_pull=False
    )

    assert mapping == {"openzaak/open-zaak": ("openzaak", "image")}


def test_repository_path_map_nested_sidecar_via_subchart_default(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """Tag-only sidecar overrides resolve from the subchart at the path minus the dependency key."""
    make_tgz(
        tmp_path / "charts",
        "zaakafhandelcomponent",
        "1.0.297",
        {
            "image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"},
            "opa": {"image": {"repository": "openpolicyagent/opa"}},
            "office_converter": {"image": {"repository": "gotenberg/gotenberg"}},
        },
    )
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    own_values = {
        "zac": {
            "image": {"tag": "5.4.4@sha256:aaaa"},
            "opa": {"image": {"tag": "1.19.1-static@sha256:bbbb"}},
            "office_converter": {"image": {"tag": "8.36.0@sha256:cccc"}},
        }
    }
    paths = [("zac", "image"), ("zac", "opa", "image"), ("zac", "office_converter", "image")]

    mapping = libchartrepoandpathresolution.repository_path_map(tmp_path, [dep], own_values, paths, allow_pull=False)

    assert mapping == {
        "infonl/zaakafhandelcomponent": ("zac", "image"),
        "openpolicyagent/opa": ("zac", "opa", "image"),
        "gotenberg/gotenberg": ("zac", "office_converter", "image"),
    }


def test_repository_path_map_subchart_values_reused_across_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libchartpullandsubchartresolution: ModuleType,
    libchartrepoandpathresolution: ModuleType,
):
    """The vendored subchart values are read at most once per dependency."""
    make_tgz(
        tmp_path / "charts",
        "zaakafhandelcomponent",
        "1.0.297",
        {
            "image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"},
            "opa": {"image": {"repository": "openpolicyagent/opa"}},
        },
    )
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    own_values = {
        "zac": {
            "image": {"tag": "5.4.4@sha256:aaaa"},
            "opa": {"image": {"tag": "1.19.1-static@sha256:bbbb"}},
        }
    }
    paths = [("zac", "image"), ("zac", "opa", "image")]
    calls = []
    real_subchart_values = libchartpullandsubchartresolution.subchart_values

    def spy(chart_dir, dep_arg, version=None):
        calls.append(dep_arg["name"])
        return real_subchart_values(chart_dir, dep_arg, version)

    monkeypatch.setattr(libchartpullandsubchartresolution, "subchart_values", spy)

    libchartrepoandpathresolution.repository_path_map(tmp_path, [dep], own_values, paths, allow_pull=False)

    assert calls == ["zaakafhandelcomponent"]


def test_repository_path_map_skips_path_with_no_known_dependency_and_no_own_repository(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """A path with no owning dependency and no own repository is skipped, not an error."""
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    own_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}},
        "mystery": {"image": {"tag": "1.0.0@sha256:aaaa"}},
    }
    paths = [("zac", "image"), ("mystery", "image")]

    mapping = libchartrepoandpathresolution.repository_path_map(tmp_path, [dep], own_values, paths, allow_pull=False)

    assert mapping == {"infonl/zaakafhandelcomponent": ("zac", "image")}


def test_repository_path_map_includes_own_repository_with_no_known_dependency(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """A non-dependency block (e.g. apiproxy) with its own repository is still mapped.

    Excluding it would split a shared-image group (apiproxy aliases the same
    global.images.nginx anchor as dependency nginx sidecars).
    """
    own_values = {
        "apiproxy": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}},
    }
    paths = [("apiproxy", "image")]

    mapping = libchartrepoandpathresolution.repository_path_map(tmp_path, [], own_values, paths, allow_pull=False)

    assert mapping == {"nginxinc/nginx-unprivileged": ("apiproxy", "image")}


def test_repository_path_map_skips_unresolvable_and_multiple_deps(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """An unresolvable dependency is skipped; the resolvable ones are still mapped."""
    zac = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    openzaak = {"name": "openzaak", "alias": "", "version": "4.9.1"}  # not vendored here
    own_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}},
        "openzaak": {"image": {"tag": "3.28.0@sha256:aaaa"}},
    }
    paths = [("zac", "image"), ("openzaak", "image")]

    mapping = libchartrepoandpathresolution.repository_path_map(
        tmp_path, [zac, openzaak], own_values, paths, allow_pull=False
    )

    assert mapping == {"infonl/zaakafhandelcomponent": ("zac", "image")}


# --- global_image_paths ---


def test_global_image_paths_reads_every_shared_anchor(libchartpullandsubchartresolution: ModuleType):
    values = {
        "global": {
            "images": {
                "nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"},
                "curl": {"repository": "curlimages/curl", "tag": "8.21.0@sha256:bbbb"},
            }
        }
    }

    paths = dict(libchartpullandsubchartresolution.global_image_paths(values))

    assert paths == {
        ("global", "images", "nginx"): "1.31.4@sha256:aaaa",
        ("global", "images", "curl"): "8.21.0@sha256:bbbb",
    }


def test_global_image_paths_skips_entries_without_a_tag(libchartpullandsubchartresolution: ModuleType):
    values = {
        "global": {
            "images": {
                "nginx": {"repository": "nginxinc/nginx-unprivileged"},  # no tag set
            }
        }
    }

    assert libchartpullandsubchartresolution.global_image_paths(values) == []


def test_global_image_paths_no_global_images_block_returns_empty(libchartpullandsubchartresolution: ModuleType):
    assert libchartpullandsubchartresolution.global_image_paths({}) == []
    assert libchartpullandsubchartresolution.global_image_paths({"global": {"configuration": {}}}) == []


# --- repo_group_representative ---


def test_repo_group_representative_global_beats_everything(libchartrepoandpathresolution: ModuleType):
    """The global anchor is the representative over every alias site pointing at it."""
    deps = [{"name": "openzaak", "alias": "", "version": "1.14.2"}]
    repo_paths = [
        ("apiproxy", "image"),
        ("openzaak", "nginx", "image"),
        ("global", "images", "nginx"),
    ]

    assert libchartrepoandpathresolution.repo_group_representative(repo_paths, deps) == ("global", "images", "nginx")


def test_repo_group_representative_global_beats_real_dependency_primary(libchartrepoandpathresolution: ModuleType):
    """The "global" anchor ranks above even a dependency's primary image, unconditionally."""
    deps = [{"name": "openzaak", "alias": "", "version": "1.14.2"}]
    repo_paths = [
        ("openzaak", "image"),
        ("global", "images", "nginx"),
    ]

    assert libchartrepoandpathresolution.repo_group_representative(repo_paths, deps) == ("global", "images", "nginx")


def test_repo_group_representative_real_dependency_primary_beats_orphan(libchartrepoandpathresolution: ModuleType):
    """A dependency's primary image beats an orphan top-level block sharing its repository.

    Both are "primary" per is_primary_image_path and the orphan comes last,
    so "last path wins" would wrongly pick the orphan.
    """
    deps = [{"name": "openzaak", "alias": "", "version": "1.14.2"}]
    repo_paths = [
        ("openzaak", "image"),
        ("openzaak-standalone", "image"),
    ]

    assert libchartrepoandpathresolution.repo_group_representative(repo_paths, deps) == ("openzaak", "image")


def test_repo_group_representative_order_independent(libchartrepoandpathresolution: ModuleType):
    """Same as above with reversed order: ownership wins, not position."""
    deps = [{"name": "openzaak", "alias": "", "version": "1.14.2"}]
    repo_paths = [
        ("openzaak-standalone", "image"),
        ("openzaak", "image"),
    ]

    assert libchartrepoandpathresolution.repo_group_representative(repo_paths, deps) == ("openzaak", "image")


def test_repo_group_representative_native_primary_beats_dependency_sidecar(libchartrepoandpathresolution: ModuleType):
    """Native keycloak.image beats its alias, a keycloak-operator sidecar, in either order."""
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.13.0"}]
    sidecar = ("keycloak-operator", "operator", "config", "keycloakImage")
    native = ("keycloak", "image")

    assert libchartrepoandpathresolution.repo_group_representative([native, sidecar], deps) == native
    assert libchartrepoandpathresolution.repo_group_representative([sidecar, native], deps) == native


def test_repo_group_representative_orphan_only_falls_back_to_last(libchartrepoandpathresolution: ModuleType):
    """Orphan-only groups fall back to the last path."""
    repo_paths = [("apiproxy", "image"), ("frankgateway", "image")]

    assert libchartrepoandpathresolution.repo_group_representative(repo_paths, []) == ("frankgateway", "image")


def test_repo_group_representative_sidecars_only_falls_back_to_last(libchartrepoandpathresolution: ModuleType):
    """Sidecar-only groups fall back to the last path."""
    deps = [
        {"name": "openzaak", "alias": "", "version": "4.9.1"},
        {"name": "openformulieren", "alias": "", "version": "3.5.6"},
    ]
    repo_paths = [("openzaak", "nginx", "image"), ("openformulieren", "nginx", "image")]

    assert libchartrepoandpathresolution.repo_group_representative(repo_paths, deps) == (
        "openformulieren",
        "nginx",
        "image",
    )


def test_repository_path_map_prefers_dependency_own_primary_over_orphan(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """repository_path_map picks the dependency's primary over a later orphan, like -upgrade.md."""
    dep = {"name": "openzaak", "alias": "", "version": "1.14.2"}
    own_values = {
        "openzaak": {"image": {"repository": "docker.io/openzaak/open-zaak", "tag": "1.20.0"}},
        "openzaak-standalone": {"image": {"repository": "docker.io/openzaak/open-zaak", "tag": "1.20.0"}},
    }
    paths = [
        ("openzaak", "image"),
        ("openzaak-standalone", "image"),
    ]

    mapping = libchartrepoandpathresolution.repository_path_map(tmp_path, [dep], own_values, paths, allow_pull=False)

    assert mapping == {"openzaak/open-zaak": ("openzaak", "image")}


def test_repository_path_map_keycloak_server_resolves_to_native_anchor_site(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """The keycloak repository maps to the native anchor site, not the operator's alias."""
    dep = {"name": "keycloak-operator", "alias": "", "version": "1.13.0"}
    own_values = {
        "keycloak": {"image": {"repository": "quay.io/keycloak/keycloak", "tag": "26.7.3"}},
        "keycloak-operator": {
            "operator": {"config": {"keycloakImage": {"repository": "quay.io/keycloak/keycloak", "tag": "26.7.3"}}}
        },
    }
    paths = [
        ("keycloak", "image"),
        ("keycloak-operator", "operator", "config", "keycloakImage"),
    ]

    mapping = libchartrepoandpathresolution.repository_path_map(tmp_path, [dep], own_values, paths, allow_pull=False)

    assert mapping == {"keycloak/keycloak": ("keycloak", "image")}


# --- paths_by_repository ---


def test_paths_by_repository_groups_shared_repository(tmp_path: Path, libchartrepoandpathresolution: ModuleType):
    """Paths sharing a repository are all kept, in processing order."""
    openzaak = {"name": "openzaak", "alias": "", "version": "4.9.1"}
    openformulieren = {"name": "openformulieren", "alias": "", "version": "3.5.6"}
    own_values = {
        "openzaak": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged"}}},
        "openformulieren": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged"}}},
    }
    paths = [("openzaak", "nginx", "image"), ("openformulieren", "nginx", "image")]

    groups = libchartrepoandpathresolution.paths_by_repository(
        tmp_path, [openzaak, openformulieren], own_values, paths, allow_pull=False
    )

    assert groups == {
        "nginxinc/nginx-unprivileged": [("openzaak", "nginx", "image"), ("openformulieren", "nginx", "image")]
    }


def test_paths_by_repository_matches_repository_path_map_last_survivor(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """repository_path_map must equal each group's last entry, so the two never disagree."""
    openzaak = {"name": "openzaak", "alias": "", "version": "4.9.1"}
    openformulieren = {"name": "openformulieren", "alias": "", "version": "3.5.6"}
    own_values = {
        "openzaak": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged"}}},
        "openformulieren": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged"}}},
    }
    paths = [("openzaak", "nginx", "image"), ("openformulieren", "nginx", "image")]

    groups = libchartrepoandpathresolution.paths_by_repository(
        tmp_path, [openzaak, openformulieren], own_values, paths, allow_pull=False
    )
    mapping = libchartrepoandpathresolution.repository_path_map(
        tmp_path, [openzaak, openformulieren], own_values, paths, allow_pull=False
    )

    assert mapping == {repo: repo_paths[-1] for repo, repo_paths in groups.items()}


def test_paths_by_repository_resolves_via_component_version_repository_sibling(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """redis-operator's repository is the sibling "imageName:" (COMPONENT_VERSION_REPOSITORY_PATHS)."""
    dep = {"name": "redis-operator", "version": "0.26.1"}
    values = {
        "redis-operator": {
            "redisOperator": {"imageName": "quay.io/opstree/redis-operator", "imageTag": "v0.26.0@sha256:aaaa"}
        }
    }
    paths = [("redis-operator", "redisOperator", "imageTag")]

    groups = libchartrepoandpathresolution.paths_by_repository(tmp_path, [dep], values, paths, allow_pull=False)

    assert groups == {"opstree/redis-operator": [("redis-operator", "redisOperator", "imageTag")]}


def test_paths_by_repository_nested_subchart_not_vendored_falls_through(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """A registered nested-subchart lookup whose .tgz isn't vendored excludes the path, no crash."""
    dep = {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}
    values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}}}
    paths = [("kiss-eck", "eck-elasticsearch", "version")]

    groups = libchartrepoandpathresolution.paths_by_repository(tmp_path, [dep], values, paths, allow_pull=False)

    assert groups == {}


def test_paths_by_repository_resolves_via_nested_subchart_documented_default(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """eck-stack's repository comes only from a commented-out example in a nested subchart."""
    dep = {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}
    make_tgz(
        tmp_path / "charts",
        "eck-stack",
        "0.20.0",
        {},
        raw_files={
            "eck-stack/charts/eck-elasticsearch/values.yaml": (
                "# Elasticsearch Docker image to deploy.\n#\n"
                "# image: docker.elastic.co/elasticsearch/elasticsearch:9.5.0\n"
                "# image: docker.elastic.co/elasticsearch/elasticsearch:9.5.0@sha256:<digest>\n"
            ),
        },
    )
    values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}}}
    paths = [("kiss-eck", "eck-elasticsearch", "version")]

    groups = libchartrepoandpathresolution.paths_by_repository(tmp_path, [dep], values, paths, allow_pull=False)

    assert groups == {"elasticsearch/elasticsearch": [("kiss-eck", "eck-elasticsearch", "version")]}
