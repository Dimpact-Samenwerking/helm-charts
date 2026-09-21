"""lib.chart — resolving chart values (vendored-or-pulled) and grouping
image repositories by path: resolve_chart_values, primary_image_
repositories, strip_registry_host, repository_path_map,
global_image_paths, repo_group_representative, paths_by_repository.
`helm pull` is mocked via lib.procutil.run, so no `helm` binary or
network access needed. Split out of the former test_chart.py (see the
other test_chart_*.py files for the rest)."""

import io
import tarfile

import pytest
import yaml


def make_tgz(charts_dir, name, version, values, templates=None, chart_yaml=None, raw_files=None):
    """A minimal vendored <name>-<version>.tgz containing <name>/values.yaml
    and, if `templates` is given (a {filename: text} dict), <name>/templates/
    <filename> for each entry — enough to exercise subchart_values/
    subchart_default_repository/subchart_template_text without a real
    `helm pull`. `chart_yaml`, if given (a dict), is ALSO written as
    <name>/Chart.yaml — for subchart_app_version. `raw_files`, if given
    (a {internal tar path: text} dict, paths relative to the tgz root —
    e.g. "<name>/charts/<nested>/values.yaml"), writes each verbatim —
    for nested_subchart_raw_text/nested_subchart_documented_image_
    repository, where the content isn't real structured YAML (a
    commented-out example line) so yaml.safe_dump can't produce it."""
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
    libchart, tmp_path, monkeypatch, libchartpullandsubchartresolution
):
    def raise_if_pulled(dep, version, dest):
        raise AssertionError("should not pull — already vendored at this exact version")

    monkeypatch.setattr(libchartpullandsubchartresolution, "pull_chart", raise_if_pulled)
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {"repository": "openzaak/open-zaak"}})
    dep = {"name": "openzaak", "version": "1.14.2"}

    values, source, error = libchartpullandsubchartresolution.resolve_chart_values(tmp_path, dep, "1.14.2")

    assert values == {"image": {"repository": "openzaak/open-zaak"}}
    assert source == "vendored"
    assert error is None


def test_resolve_chart_values_falls_back_to_pull_when_not_vendored(
    libchart, tmp_path, monkeypatch, libchartpullandsubchartresolution
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
    libchart, tmp_path, monkeypatch, libchartpullandsubchartresolution
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
    libchart, tmp_path, monkeypatch, libchartpullandsubchartresolution
):
    def raise_if_pulled(dep, version, dest):
        raise AssertionError("should not pull — allow_pull is False")

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
    libchart, tmp_path, monkeypatch, libchartpullandsubchartresolution
):
    def raise_if_pulled(dep, version, dest):
        raise AssertionError("own override present — should never consult the subchart")

    monkeypatch.setattr(libchartpullandsubchartresolution, "pull_chart", raise_if_pulled)
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    own_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}}

    repos, error = libchartpullandsubchartresolution.primary_image_repositories(
        tmp_path, dep, own_values, allow_pull=False
    )

    assert repos == {"image": "ghcr.io/infonl/zaakafhandelcomponent"}
    assert error is None


def test_primary_image_repositories_falls_back_to_subchart_default(
    libchart, tmp_path, libchartpullandsubchartresolution
):
    """openzaak-style: no "repository:" override of its own at all — only
    a "tag:" — resolved from the vendored subchart's own default instead,
    with no network access (allow_pull=False)."""
    make_tgz(tmp_path / "charts", "openzaak", "4.9.1", {"image": {"repository": "openzaak/open-zaak"}})
    dep = {"name": "openzaak", "alias": "", "version": "4.9.1"}
    own_values = {"openzaak": {"image": {"tag": "3.28.0@sha256:aaaa"}}}

    repos, error = libchartpullandsubchartresolution.primary_image_repositories(
        tmp_path, dep, own_values, allow_pull=False
    )

    assert repos == {"image": "openzaak/open-zaak"}
    assert error is None


def test_primary_image_repositories_multi_path_component_reads_subchart_once(
    libchart, tmp_path, monkeypatch, libchartpullandsubchartresolution
):
    """zgw-office-addin-style: two distinct primary paths, neither with
    its own override — both resolved from the SAME vendored subchart
    values.yaml, read only once and reused across both paths."""
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
    libchart, tmp_path, libchartpullandsubchartresolution
):
    dep = {"name": "openzaak", "alias": "", "version": "4.9.1"}
    own_values = {"openzaak": {"image": {"tag": "3.28.0@sha256:aaaa"}}}

    repos, error = libchartpullandsubchartresolution.primary_image_repositories(
        tmp_path, dep, own_values, allow_pull=False
    )

    assert repos == {"image": None}
    assert error is not None


def test_primary_image_repositories_chart_dir_none_is_safe_when_unneeded(libchart, libchartpullandsubchartresolution):
    """A caller with no vendored-charts location at all (e.g. a pure
    in-memory test) never crashes, as long as no path actually needs the
    subchart fallback — see verify-release-table-with-podiumd's own
    compare(), whose chart_dir defaults to None."""
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    own_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}}

    repos, error = libchartpullandsubchartresolution.primary_image_repositories(None, dep, own_values, allow_pull=False)

    assert repos == {"image": "ghcr.io/infonl/zaakafhandelcomponent"}
    assert error is None


def test_primary_image_repositories_chart_dir_none_and_needed_returns_error(
    libchart, libchartpullandsubchartresolution
):
    dep = {"name": "openzaak", "alias": "", "version": "4.9.1"}
    own_values = {"openzaak": {"image": {"tag": "3.28.0@sha256:aaaa"}}}

    repos, error = libchartpullandsubchartresolution.primary_image_repositories(None, dep, own_values, allow_pull=False)

    assert repos == {"image": None}
    assert error is not None


# --- strip_registry_host ---


@pytest.mark.parametrize(
    "url,expected",
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
def test_strip_registry_host(libchart, libchartvaluestreeprimitives, url, expected):
    assert libchartvaluestreeprimitives.strip_registry_host(url) == expected


# --- repository_path_map ---


def test_repository_path_map_own_override(libchart, tmp_path):
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    own_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}}

    mapping = libchart.repository_path_map(tmp_path, [dep], own_values, [("zac", "image")], allow_pull=False)

    assert mapping == {"infonl/zaakafhandelcomponent": ("zac", "image")}


def test_repository_path_map_subchart_default(libchart, tmp_path):
    make_tgz(tmp_path / "charts", "openzaak", "4.9.1", {"image": {"repository": "openzaak/open-zaak"}})
    dep = {"name": "openzaak", "alias": "", "version": "4.9.1"}
    own_values = {"openzaak": {"image": {"tag": "3.28.0@sha256:aaaa"}}}

    mapping = libchart.repository_path_map(tmp_path, [dep], own_values, [("openzaak", "image")], allow_pull=False)

    assert mapping == {"openzaak/open-zaak": ("openzaak", "image")}


def test_repository_path_map_nested_sidecar_via_subchart_default(libchart, tmp_path):
    """ZAC's own opa/office_converter sidecars: podiumd's own values.yaml
    only overrides their "tag:" (the "repository:" is commented out for
    documentation, not real YAML) — the real repository has to come
    from ZAC's OWN vendored subchart values.yaml, at the path with the
    dependency's own values-tree key ("zac") stripped off."""
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

    mapping = libchart.repository_path_map(tmp_path, [dep], own_values, paths, allow_pull=False)

    assert mapping == {
        "infonl/zaakafhandelcomponent": ("zac", "image"),
        "openpolicyagent/opa": ("zac", "opa", "image"),
        "gotenberg/gotenberg": ("zac", "office_converter", "image"),
    }


def test_repository_path_map_subchart_values_reused_across_paths(
    libchart, tmp_path, monkeypatch, libchartpullandsubchartresolution
):
    """The vendored subchart's own values.yaml is read at most once for
    a given dependency, however many of its own paths need it —
    same caching guarantee as primary_image_repositories."""
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

    libchart.repository_path_map(tmp_path, [dep], own_values, paths, allow_pull=False)

    assert calls == ["zaakafhandelcomponent"]


def test_repository_path_map_skips_path_with_no_known_dependency_and_no_own_repository(libchart, tmp_path):
    """A path whose first segment isn't any dependency's own values-tree
    key at all, AND has no own "repository:" override either — nothing
    to resolve it against either way — is silently skipped, not an
    error."""
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    own_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}},
        "mystery": {"image": {"tag": "1.0.0@sha256:aaaa"}},
    }
    paths = [("zac", "image"), ("mystery", "image")]

    mapping = libchart.repository_path_map(tmp_path, [dep], own_values, paths, allow_pull=False)

    assert mapping == {"infonl/zaakafhandelcomponent": ("zac", "image")}


def test_repository_path_map_includes_own_repository_with_no_known_dependency(libchart, tmp_path):
    """A path whose first segment isn't any Chart.yaml dependency at all
    — one of podiumd's own directly-templated top-level blocks, like the
    real "apiproxy"/"frankgateway"/"keycloak" — is still resolved when
    podiumd's own values.yaml sets its "repository:" directly (same
    resolution order lib.image_repository_check.find_images_without_
    repository already uses: own override first, dependency status
    irrelevant to that lookup). Real case this exists for: "apiproxy"
    aliases the very same shared global.images.nginx anchor a real
    dependency's own "<component>.nginx.image" sidecar does — excluding
    it here would wrongly split one shared-image group in two."""
    own_values = {
        "apiproxy": {"image": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.4@sha256:aaaa"}},
    }
    paths = [("apiproxy", "image")]

    mapping = libchart.repository_path_map(tmp_path, [], own_values, paths, allow_pull=False)

    assert mapping == {"nginxinc/nginx-unprivileged": ("apiproxy", "image")}


def test_repository_path_map_skips_unresolvable_and_multiple_deps(libchart, tmp_path):
    """A dependency whose repository can't be resolved at all (no
    override, subchart not vendored) is silently skipped, not an error
    for the whole map — the other, resolvable dependencies still end up
    in it."""
    zac = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    openzaak = {"name": "openzaak", "alias": "", "version": "4.9.1"}  # not vendored here
    own_values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}},
        "openzaak": {"image": {"tag": "3.28.0@sha256:aaaa"}},
    }
    paths = [("zac", "image"), ("openzaak", "image")]

    mapping = libchart.repository_path_map(tmp_path, [zac, openzaak], own_values, paths, allow_pull=False)

    assert mapping == {"infonl/zaakafhandelcomponent": ("zac", "image")}


# --- global_image_paths ---


def test_global_image_paths_reads_every_shared_anchor(libchart, libchartpullandsubchartresolution):
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


def test_global_image_paths_skips_entries_without_a_tag(libchart, libchartpullandsubchartresolution):
    values = {
        "global": {
            "images": {
                "nginx": {"repository": "nginxinc/nginx-unprivileged"},  # no tag set
            }
        }
    }

    assert libchartpullandsubchartresolution.global_image_paths(values) == []


def test_global_image_paths_no_global_images_block_returns_empty(libchart, libchartpullandsubchartresolution):
    assert libchartpullandsubchartresolution.global_image_paths({}) == []
    assert libchartpullandsubchartresolution.global_image_paths({"global": {"configuration": {}}}) == []


# --- repo_group_representative ---


def test_repo_group_representative_global_beats_everything(libchart):
    """The shared nginx-unprivileged anchor: aliased by apiproxy's own
    top-level image (orphan) AND by a real dependency's own nginx
    sidecar alike. Neither alias site is "the" component this image
    belongs to — "global" (the one true source both merely point at) is,
    regardless of how many other candidates are in the group or what
    tier they'd otherwise rank at."""
    deps = [{"name": "openzaak", "alias": "", "version": "1.14.2"}]
    repo_paths = [
        ("apiproxy", "image"),
        ("openzaak", "nginx", "image"),
        ("global", "images", "nginx"),
    ]

    assert libchart.repo_group_representative(repo_paths, deps) == ("global", "images", "nginx")


def test_repo_group_representative_global_beats_real_dependency_primary(libchart):
    """Even a real dependency's own PRIMARY image (the highest of the
    other tiers) never outranks "global" — structurally impossible in
    practice (a primary app image is never itself a global-anchor
    alias), but the ranking itself must still be unconditional, not just
    "usually wins"."""
    deps = [{"name": "openzaak", "alias": "", "version": "1.14.2"}]
    repo_paths = [
        ("openzaak", "image"),
        ("global", "images", "nginx"),
    ]

    assert libchart.repo_group_representative(repo_paths, deps) == ("global", "images", "nginx")


def test_repo_group_representative_real_dependency_primary_beats_orphan(libchart):
    """The keycloak/keycloak-operator case: "keycloak.image" is podiumd's
    own directly-templated top-level override (tier 2 — no owning
    Chart.yaml dependency at all) and "keycloak-operator.operator.
    config.keycloakImage" is keycloak-operator's own COMPONENT_IMAGE_
    PATHS-registered primary image (tier 1 — real ownership). Both count
    as "primary" under is_primary_image_path alone, and "keycloak" sorts
    after "keycloak-operator" in values.yaml top-level traversal, so a
    naive "last path wins" pick lands on the orphan — real ownership
    must win instead."""
    deps = [{"name": "keycloak-operator", "alias": "", "version": "26.7.3"}]
    repo_paths = [
        ("keycloak-operator", "operator", "config", "keycloakImage"),
        ("keycloak", "image"),
    ]

    assert libchart.repo_group_representative(repo_paths, deps) == (
        "keycloak-operator",
        "operator",
        "config",
        "keycloakImage",
    )


def test_repo_group_representative_order_independent(libchart):
    """Same case, paths given in the opposite order — the real
    dependency's own path must still win, not just "whichever came
    first"."""
    deps = [{"name": "keycloak-operator", "alias": "", "version": "26.7.3"}]
    repo_paths = [
        ("keycloak", "image"),
        ("keycloak-operator", "operator", "config", "keycloakImage"),
    ]

    assert libchart.repo_group_representative(repo_paths, deps) == (
        "keycloak-operator",
        "operator",
        "config",
        "keycloakImage",
    )


def test_repo_group_representative_orphan_only_falls_back_to_last(libchart):
    """No real dependency in the group at all (e.g. "apiproxy" and
    "frankgateway" both aliasing the same shared global.images.nginx
    anchor, neither a Chart.yaml dependency of its own) — falls back to
    the last path, the historical convention every caller used to
    inline."""
    repo_paths = [("apiproxy", "image"), ("frankgateway", "image")]

    assert libchart.repo_group_representative(repo_paths, []) == ("frankgateway", "image")


def test_repo_group_representative_sidecars_only_falls_back_to_last(libchart):
    """No path in the group is a dependency's own PRIMARY path (e.g. two
    unrelated dependencies' sidecars sharing one base image, like nginx)
    — falls back to the last path, same as before this function
    existed."""
    deps = [
        {"name": "openzaak", "alias": "", "version": "4.9.1"},
        {"name": "openformulieren", "alias": "", "version": "3.5.6"},
    ]
    repo_paths = [("openzaak", "nginx", "image"), ("openformulieren", "nginx", "image")]

    assert libchart.repo_group_representative(repo_paths, deps) == ("openformulieren", "nginx", "image")


def test_repository_path_map_prefers_dependency_own_primary_over_orphan(libchart, tmp_path):
    """Integration-level version of the keycloak/keycloak-operator case
    through repository_path_map itself — the map entry for the shared
    repository resolves to the real dependency's own path, not podiumd's
    orphan top-level override, matching -upgrade.md's own dependency-
    first name resolution (never routed through this map at all)."""
    dep = {"name": "keycloak-operator", "alias": "", "version": "26.7.3"}
    own_values = {
        "keycloak-operator": {
            "operator": {"config": {"keycloakImage": {"repository": "quay.io/keycloak/keycloak", "tag": "26.7.3"}}}
        },
        "keycloak": {"image": {"repository": "quay.io/keycloak/keycloak", "tag": "26.7.3"}},
    }
    paths = [
        ("keycloak-operator", "operator", "config", "keycloakImage"),
        ("keycloak", "image"),
    ]

    mapping = libchart.repository_path_map(tmp_path, [dep], own_values, paths, allow_pull=False)

    assert mapping == {"keycloak/keycloak": ("keycloak-operator", "operator", "config", "keycloakImage")}


# --- paths_by_repository ---


def test_paths_by_repository_groups_shared_repository(libchart, tmp_path):
    """Several paths resolving to the same repository (e.g. every
    "<component>.nginx.image" sidecar aliasing the same shared
    global.images.nginx YAML anchor) land together under that one
    repository, in the order they were processed — not collapsed down
    to a single survivor the way repository_path_map's own result is."""
    openzaak = {"name": "openzaak", "alias": "", "version": "4.9.1"}
    openformulieren = {"name": "openformulieren", "alias": "", "version": "3.5.6"}
    own_values = {
        "openzaak": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged"}}},
        "openformulieren": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged"}}},
    }
    paths = [("openzaak", "nginx", "image"), ("openformulieren", "nginx", "image")]

    groups = libchart.paths_by_repository(tmp_path, [openzaak, openformulieren], own_values, paths, allow_pull=False)

    assert groups == {
        "nginxinc/nginx-unprivileged": [("openzaak", "nginx", "image"), ("openformulieren", "nginx", "image")]
    }


def test_paths_by_repository_matches_repository_path_map_last_survivor(libchart, tmp_path):
    """repository_path_map's own single-path result is exactly this
    function's own group, collapsed to its last entry — the two must
    never disagree about which path "wins" for a shared repository."""
    openzaak = {"name": "openzaak", "alias": "", "version": "4.9.1"}
    openformulieren = {"name": "openformulieren", "alias": "", "version": "3.5.6"}
    own_values = {
        "openzaak": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged"}}},
        "openformulieren": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged"}}},
    }
    paths = [("openzaak", "nginx", "image"), ("openformulieren", "nginx", "image")]

    groups = libchart.paths_by_repository(tmp_path, [openzaak, openformulieren], own_values, paths, allow_pull=False)
    mapping = libchart.repository_path_map(tmp_path, [openzaak, openformulieren], own_values, paths, allow_pull=False)

    assert mapping == {repo: repo_paths[-1] for repo, repo_paths in groups.items()}


def test_paths_by_repository_resolves_via_component_version_repository_sibling(libchart, tmp_path):
    """redis-operator's own image has no "<path>.repository" field at
    all — its repository lives at the sibling "imageName:" field next
    to "imageTag:" (see COMPONENT_VERSION_REPOSITORY_PATHS), a shape
    the ordinary "own override, else subchart default" resolution never
    finds on its own."""
    dep = {"name": "redis-operator", "version": "0.26.1"}
    values = {
        "redis-operator": {
            "redisOperator": {"imageName": "quay.io/opstree/redis-operator", "imageTag": "v0.26.0@sha256:aaaa"}
        }
    }
    paths = [("redis-operator", "redisOperator", "imageTag")]

    groups = libchart.paths_by_repository(tmp_path, [dep], values, paths, allow_pull=False)

    assert groups == {"opstree/redis-operator": [("redis-operator", "redisOperator", "imageTag")]}


def test_paths_by_repository_nested_subchart_not_vendored_falls_through(libchart, tmp_path):
    """eck-stack's own COMPONENT_VERSION_PATHS entries ("version:" bare
    fields) have a registered nested-subchart lookup (see
    COMPONENT_VERSION_PATH_NESTED_SUBCHARTS), but the .tgz itself isn't
    vendored at tmp_path — must not error, just fall through exactly
    as an unregistered component would (no own override, no vendored
    subchart either -> path silently excluded, not a crash)."""
    dep = {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}
    values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}}}
    paths = [("kiss-eck", "eck-elasticsearch", "version")]

    groups = libchart.paths_by_repository(tmp_path, [dep], values, paths, allow_pull=False)

    assert groups == {}


def test_paths_by_repository_resolves_via_nested_subchart_documented_default(libchart, tmp_path):
    """eck-stack's own three "version:" fields have no repository
    anywhere in podiumd's own values.yaml, nor a live default in the
    vendored eck-stack chart's own top-level values.yaml — only a
    commented-out example inside its NESTED eck-elasticsearch sub-
    subchart's own values.yaml, which is what this resolves through."""
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

    groups = libchart.paths_by_repository(tmp_path, [dep], values, paths, allow_pull=False)

    assert groups == {"elasticsearch/elasticsearch": [("kiss-eck", "eck-elasticsearch", "version")]}
