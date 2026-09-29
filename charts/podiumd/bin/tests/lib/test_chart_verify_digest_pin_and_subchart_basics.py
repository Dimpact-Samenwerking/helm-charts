"""lib.chart: chart-version verification, image-version/digest checks, subchart basics.

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


# --- verify_chart_version ---


def test_verify_chart_version_found_returns_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    libchartpullandsubchartresolution: ModuleType,
):
    def fake_pull_chart(dep, version, dest):
        chart_dir = dest / dep["name"]
        chart_dir.mkdir(parents=True)
        (chart_dir / "values.yaml").write_text(
            yaml.safe_dump({"image": {"repository": "infonl/zac"}}), encoding="utf-8"
        )
        return True, ""

    monkeypatch.setattr(libchartpullandsubchartresolution, "pull_chart", fake_pull_chart)
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297", "repository": "@zac"}

    values = libchartpullandsubchartresolution.verify_chart_version(tmp_path, dep, "1.0.297")

    assert values == {"image": {"repository": "infonl/zac"}}
    out = capsys.readouterr().out
    assert "[FOUND  ] zaakafhandelcomponent 1.0.297" in out


def test_verify_chart_version_prefers_vendored_tgz_without_pulling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    libchartpullandsubchartresolution: ModuleType,
):
    def raise_if_pulled(dep, version, dest):
        msg = "should not pull — an exact-version .tgz is already vendored"
        raise AssertionError(msg)

    monkeypatch.setattr(libchartpullandsubchartresolution, "pull_chart", raise_if_pulled)
    dep = {"name": "openzaak", "version": "4.9.1", "repository": "@openzaak"}
    make_tgz(tmp_path / "charts", "openzaak", "4.9.1", {"image": {"repository": "openzaak/open-zaak"}})

    values = libchartpullandsubchartresolution.verify_chart_version(tmp_path, dep, "4.9.1")

    assert values == {"image": {"repository": "openzaak/open-zaak"}}
    assert "[FOUND  ] openzaak 4.9.1  (vendored)" in capsys.readouterr().out


def test_verify_chart_version_missing_exits_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    libchartpullandsubchartresolution: ModuleType,
):
    monkeypatch.setattr(
        libchartpullandsubchartresolution, "pull_chart", lambda dep, version, dest: (False, "version not found")
    )
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297", "repository": "@zac"}

    with pytest.raises(SystemExit) as exc_info:
        libchartpullandsubchartresolution.verify_chart_version(tmp_path, dep, "9.9.9")

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "[MISSING] zaakafhandelcomponent 9.9.9  (version not found)" in out
    assert "FAIL: chart version does not exist" in out


# --- check_image_versions ---


def test_check_image_versions_single_path_found(
    monkeypatch: pytest.MonkeyPatch, libchartpullandsubchartresolution: ModuleType
):
    monkeypatch.setattr(
        libchartpullandsubchartresolution, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:abc")
    )
    values = {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}
    results = libchartpullandsubchartresolution.check_image_versions(values, ["image"], "5.4.3")
    assert results == [
        {
            "path": "image",
            "repository": "ghcr.io/infonl/zaakafhandelcomponent",
            "host": "ghcr.io",
            "repo_path": "infonl/zaakafhandelcomponent",
            "exists": True,
            "digest": "sha256:abc",
        }
    ]


def test_check_image_versions_reports_missing_tag(
    monkeypatch: pytest.MonkeyPatch, libchartpullandsubchartresolution: ModuleType
):
    monkeypatch.setattr(libchartpullandsubchartresolution, "registry_tag_exists", lambda host, repo, tag: (False, None))
    values = {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}
    results = libchartpullandsubchartresolution.check_image_versions(values, ["image"], "9.9.9")
    assert results[0]["exists"] is False
    assert results[0]["digest"] is None


def test_check_image_versions_checks_every_multi_image_path(
    monkeypatch: pytest.MonkeyPatch, libchartpullandsubchartresolution: ModuleType
):
    checked = []

    def fake_registry_tag_exists(host, repo, tag):
        checked.append(repo)
        return True, "sha256:fake"

    monkeypatch.setattr(libchartpullandsubchartresolution, "registry_tag_exists", fake_registry_tag_exists)
    values = {
        "frontend": {"image": {"repository": "ghcr.io/infonl/zgw-office-addin-frontend"}},
        "backend": {"image": {"repository": "ghcr.io/infonl/zgw-office-addin-backend"}},
    }
    results = libchartpullandsubchartresolution.check_image_versions(
        values, ["frontend.image", "backend.image"], "0.11.0"
    )
    assert checked == ["infonl/zgw-office-addin-frontend", "infonl/zgw-office-addin-backend"]
    assert [r["path"] for r in results] == ["frontend.image", "backend.image"]


def test_check_image_versions_skips_path_with_no_repository(
    monkeypatch: pytest.MonkeyPatch, libchartpullandsubchartresolution: ModuleType
):
    """A path without "repository:" is skipped while another path still resolves."""
    monkeypatch.setattr(
        libchartpullandsubchartresolution, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:fake")
    )
    values = {
        "frontend": {"image": {"repository": "ghcr.io/infonl/zgw-office-addin-frontend"}},
        "backend": {"image": {}},
    }
    results = libchartpullandsubchartresolution.check_image_versions(
        values, ["frontend.image", "backend.image"], "0.11.0"
    )
    assert [r["path"] for r in results] == ["frontend.image"]


def test_check_image_versions_raises_when_no_path_has_a_repository(
    monkeypatch: pytest.MonkeyPatch, libchartpullandsubchartresolution: ModuleType
):
    values = {"somethingElse": {"repository": "x/y"}}
    with pytest.raises(SystemExit, match="no repository found"):
        libchartpullandsubchartresolution.check_image_versions(values, ["image"], "5.4.3")


def test_check_image_versions_honours_sibling_registry(
    monkeypatch: pytest.MonkeyPatch, libchartpullandsubchartresolution: ModuleType
):
    """A sibling "registry:" (openbao) must be used, not Docker Hub."""
    checked = []

    def fake_registry_tag_exists(host, repo, tag):
        checked.append((host, repo))
        return True, "sha256:fake"

    monkeypatch.setattr(libchartpullandsubchartresolution, "registry_tag_exists", fake_registry_tag_exists)
    values = {"server": {"image": {"registry": "quay.io", "repository": "openbao/openbao"}}}
    libchartpullandsubchartresolution.check_image_versions(values, ["server.image"], "2.5.5")
    assert checked == [("quay.io", "openbao/openbao")]


# --- component_check_values ---


def test_component_check_values_overlays_podiumd_values_without_mutating(
    libchartpullandsubchartresolution: ModuleType,
):
    """podiumd overrides win and podiumd-only image blocks are added; input is not mutated."""
    chart_values = {"server": {"image": {"registry": "quay.io", "repository": "openbao/openbao", "tag": ""}}}
    podiumd = {"configuration": {"job": {"image": {"repository": "quay.io/openbao/openbao"}}}}
    merged = libchartpullandsubchartresolution.component_check_values(chart_values, podiumd)
    assert merged["configuration"]["job"]["image"]["repository"] == "quay.io/openbao/openbao"
    assert merged["server"]["image"]["repository"] == "openbao/openbao"
    assert "configuration" not in chart_values


# --- version_of ---


def test_version_of_strips_digest(libchartvaluestreeprimitives: ModuleType):
    assert libchartvaluestreeprimitives.version_of("5.4.3@sha256:abc") == "5.4.3"
    assert libchartvaluestreeprimitives.version_of("1.19.0-static") == "1.19.0-static"


# --- resolved_digest_pin ---

# Shape of lib.settings.digest_pinning_exceptions; only "sibling_field" is read.
SIBLING_FIELDS = {
    ("keycloak-operator", "operator", "config", "keycloakImage"): {"sibling_field": "sha"},
    ("keycloak-operator", "operator", "image"): {"sibling_field": "sha"},
    ("keycloak", "image"): {"sibling_field": "sha"},
    ("eck-operator", "image"): {"sibling_field": "digest"},
}


def test_resolved_digest_pin_already_embedded_returned_as_is(libchartpullandsubchartresolution: ModuleType):
    values = {"zac": {"image": {"tag": "5.4.4@sha256:aaaa"}}}

    assert (
        libchartpullandsubchartresolution.resolved_digest_pin(
            values, ("zac", "image"), "5.4.4@sha256:aaaa", SIBLING_FIELDS
        )
        == "5.4.4@sha256:aaaa"
    )


def test_resolved_digest_pin_split_tag_sha_combines_sibling_sha(libchartpullandsubchartresolution: ModuleType):
    """A split "tag:"/"sha:" pin (keycloak-operator) is combined into "<tag>@sha256:<sha>"."""
    path = ("keycloak-operator", "operator", "config", "keycloakImage")
    values = {
        "keycloak-operator": {
            "operator": {
                "config": {
                    "keycloakImage": {
                        "tag": "26.7.2",
                        "sha": "9d1f1b2b7261ff53c66cb1092dfcdc34a5fb77e81f9e6a6e75b8b6a795de8067",
                    }
                }
            }
        }
    }

    assert libchartpullandsubchartresolution.resolved_digest_pin(values, path, "26.7.2", SIBLING_FIELDS) == (
        "26.7.2@sha256:9d1f1b2b7261ff53c66cb1092dfcdc34a5fb77e81f9e6a6e75b8b6a795de8067"
    )


def test_resolved_digest_pin_split_tag_sha_no_sha_override_returns_none(libchartpullandsubchartresolution: ModuleType):
    """Without a "sha:" override (only the subchart default) there is nothing to combine."""
    path = ("keycloak-operator", "operator", "config", "keycloakImage")
    values = {"keycloak-operator": {"operator": {"config": {"keycloakImage": {"tag": "26.7.2"}}}}}

    assert libchartpullandsubchartresolution.resolved_digest_pin(values, path, "26.7.2", SIBLING_FIELDS) is None


def test_resolved_digest_pin_ordinary_path_with_no_digest_returns_none(libchartpullandsubchartresolution: ModuleType):
    """A bare tag outside the sibling_fields table is unresolvable."""
    values = {"openzaak": {"image": {"tag": "1.29.3"}}}

    assert (
        libchartpullandsubchartresolution.resolved_digest_pin(values, ("openzaak", "image"), "1.29.3", SIBLING_FIELDS)
        is None
    )


def test_resolved_digest_pin_eck_operator_combines_sibling_digest_field(libchartpullandsubchartresolution: ModuleType):
    """The sibling field name is per path: eck-operator uses "digest:", not "sha:"."""
    path = ("eck-operator", "image")
    values = {
        "eck-operator": {
            "image": {
                "tag": "3.5.0",
                "digest": "sha256:b6f261372d9d9af7b00aab03efea25263314d16063c4d440ac322e52c2fdf314",
            }
        }
    }

    assert libchartpullandsubchartresolution.resolved_digest_pin(values, path, "3.5.0", SIBLING_FIELDS) == (
        "3.5.0@sha256:b6f261372d9d9af7b00aab03efea25263314d16063c4d440ac322e52c2fdf314"
    )


def test_resolved_digest_pin_eck_operator_no_digest_override_returns_none(
    libchartpullandsubchartresolution: ModuleType,
):
    """A missing "digest:" sibling returns None, not a KeyError."""
    path = ("eck-operator", "image")
    values = {"eck-operator": {"image": {"tag": "3.5.0"}}}

    assert libchartpullandsubchartresolution.resolved_digest_pin(values, path, "3.5.0", SIBLING_FIELDS) is None


# --- find_images ---


def test_find_images_nested_dict_and_list(libchartvaluestreeprimitives: ModuleType):
    values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.3@sha256:abc"}},
        "items": [{"image": {"repository": "curlimages/curl", "tag": "8.21.0"}}],
    }
    images = libchartvaluestreeprimitives.find_images(values)
    assert ("zac.image", "ghcr.io/infonl/zaakafhandelcomponent", "5.4.3@sha256:abc") in images
    assert ("items[0].image", "curlimages/curl", "8.21.0") in images


def test_find_images_skips_empty_tag(libchartvaluestreeprimitives: ModuleType):
    assert libchartvaluestreeprimitives.find_images({"image": {"repository": "x", "tag": ""}}) == []


def test_find_images_root_path_label(libchartvaluestreeprimitives: ModuleType):
    assert libchartvaluestreeprimitives.find_images({"repository": "x", "tag": "1.0"}) == [("(root)", "x", "1.0")]


# --- image_paths_for ---


def test_image_paths_for_multi_image_component(libchartregisteredpaths: ModuleType):
    assert libchartregisteredpaths.image_paths_for("zgw-office-addin") == ["frontend.image", "backend.image"]


def test_image_paths_for_ita_web_and_poller(libchartregisteredpaths: ModuleType):
    """ITA has two co-equal lockstep images, web and poller."""
    assert libchartregisteredpaths.image_paths_for("internetaakafhandeling") == ["web.image", "poller.image"]


def test_image_paths_for_kiss_chart_frontend_and_sync_jobs(libchartregisteredpaths: ModuleType):
    """kiss-chart's frontend and sync-job images move in lockstep.

    The crawler images are excluded: they have independent upstream versions.
    """
    assert libchartregisteredpaths.image_paths_for("kiss-chart") == ["image", "settings.syncJobs.image"]


def test_image_paths_for_unlisted_component_defaults_to_single_image_block(libchartregisteredpaths: ModuleType):
    assert libchartregisteredpaths.image_paths_for("zac") == ["image"]


# --- dotted_key_path ---


def test_dotted_key_path_nested_component(libchartvaluestreeprimitives: ModuleType):
    lines = [
        "openzaak:",
        "  image:",
        '    tag: "1.27.4@sha256:aaaa"',
    ]
    assert libchartvaluestreeprimitives.dotted_key_path(lines, 2) == "openzaak.image.tag"


def test_dotted_key_path_ignores_comments_and_blank_lines(libchartvaluestreeprimitives: ModuleType):
    lines = [
        "a:",
        "  # a comment",
        "",
        "  image:",
        '    tag: "1.0.0@sha256:aaaa"',
    ]
    assert libchartvaluestreeprimitives.dotted_key_path(lines, 4) == "a.image.tag"


def test_dotted_key_path_pops_stack_on_dedent(libchartvaluestreeprimitives: ModuleType):
    lines = [
        "a:",
        "  b:",
        "    c: 1",
        "d:",
        "  e: 2",
    ]
    assert libchartvaluestreeprimitives.dotted_key_path(lines, 4) == "d.e"


# --- subchart_values ---


def test_subchart_values_reads_vendored_tgz(tmp_path: Path, libchartpullandsubchartresolution: ModuleType):
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {"repository": "openzaak/open-zaak"}})
    dep = {"name": "openzaak", "version": "1.14.2"}
    assert libchartpullandsubchartresolution.subchart_values(tmp_path, dep) == {
        "image": {"repository": "openzaak/open-zaak"}
    }


def test_subchart_values_missing_tgz_returns_none(tmp_path: Path, libchartpullandsubchartresolution: ModuleType):
    dep = {"name": "openzaak", "version": "1.14.2"}
    assert libchartpullandsubchartresolution.subchart_values(tmp_path, dep) is None


def test_subchart_values_missing_member_returns_none(tmp_path: Path, libchartpullandsubchartresolution: ModuleType):
    charts_dir = tmp_path / "charts"
    charts_dir.mkdir()
    with tarfile.open(charts_dir / "openzaak-1.14.2.tgz", "w:gz"):
        pass  # empty archive, no values.yaml member
    dep = {"name": "openzaak", "version": "1.14.2"}
    assert libchartpullandsubchartresolution.subchart_values(tmp_path, dep) is None


def test_subchart_values_returns_a_fresh_copy_each_call(tmp_path: Path, libchartpullandsubchartresolution: ModuleType):
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {"repository": "openzaak/open-zaak"}})
    dep = {"name": "openzaak", "version": "1.14.2"}
    first = libchartpullandsubchartresolution.subchart_values(tmp_path, dep)
    assert first is not None
    first["image"] = "changed"
    assert libchartpullandsubchartresolution.subchart_values(tmp_path, dep) == {
        "image": {"repository": "openzaak/open-zaak"}
    }


def test_subchart_values_rereads_a_replaced_tgz(tmp_path: Path, libchartpullandsubchartresolution: ModuleType):
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {"repository": "openzaak/open-zaak"}})
    dep = {"name": "openzaak", "version": "1.14.2"}
    assert libchartpullandsubchartresolution.subchart_values(tmp_path, dep) is not None
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {"repository": "example/other-repository-name"}})
    assert libchartpullandsubchartresolution.subchart_values(tmp_path, dep) == {
        "image": {"repository": "example/other-repository-name"}
    }


# --- subchart_app_version ---


def test_subchart_app_version_reads_vendored_chart_yaml(tmp_path: Path, libchartpullandsubchartresolution: ModuleType):
    make_tgz(
        tmp_path / "charts",
        "openbao",
        "0.28.4",
        {"server": {"image": {"tag": ""}}},
        chart_yaml={"apiVersion": "v2", "version": "0.28.4", "appVersion": "v2.5.5"},
    )
    dep = {"name": "openbao", "version": "0.28.4"}
    assert libchartpullandsubchartresolution.subchart_app_version(tmp_path, dep) == "v2.5.5"


def test_subchart_app_version_missing_tgz_returns_none(tmp_path: Path, libchartpullandsubchartresolution: ModuleType):
    dep = {"name": "openbao", "version": "0.28.4"}
    assert libchartpullandsubchartresolution.subchart_app_version(tmp_path, dep) is None


def test_subchart_app_version_missing_member_returns_none(
    tmp_path: Path, libchartpullandsubchartresolution: ModuleType
):
    make_tgz(tmp_path / "charts", "openbao", "0.28.4", {"server": {"image": {"tag": ""}}})  # no chart_yaml
    dep = {"name": "openbao", "version": "0.28.4"}
    assert libchartpullandsubchartresolution.subchart_app_version(tmp_path, dep) is None


def test_subchart_app_version_no_app_version_field_returns_none(
    tmp_path: Path, libchartpullandsubchartresolution: ModuleType
):
    make_tgz(
        tmp_path / "charts",
        "openbao",
        "0.28.4",
        {"server": {"image": {"tag": ""}}},
        chart_yaml={"apiVersion": "v2", "version": "0.28.4"},
    )
    dep = {"name": "openbao", "version": "0.28.4"}
    assert libchartpullandsubchartresolution.subchart_app_version(tmp_path, dep) is None


# --- nested_subchart_raw_text / nested_subchart_documented_image_repository ---


def test_nested_subchart_raw_text_reads_nested_file(libchartnestedsubchartidentity: ModuleType, tmp_path: Path):
    dep = {"name": "eck-stack", "version": "0.20.0"}
    make_tgz(
        tmp_path / "charts",
        "eck-stack",
        "0.20.0",
        {},
        raw_files={
            "eck-stack/charts/eck-elasticsearch/values.yaml": "# hello\n",
        },
    )
    assert (
        libchartnestedsubchartidentity.nested_subchart_raw_text(tmp_path, dep, "eck-elasticsearch", "values.yaml")
        == "# hello\n"
    )


def test_nested_subchart_raw_text_missing_tgz_returns_none(libchartnestedsubchartidentity: ModuleType, tmp_path: Path):
    dep = {"name": "eck-stack", "version": "0.20.0"}
    assert (
        libchartnestedsubchartidentity.nested_subchart_raw_text(tmp_path, dep, "eck-elasticsearch", "values.yaml")
        is None
    )


def test_nested_subchart_raw_text_missing_nested_chart_returns_none(
    libchartnestedsubchartidentity: ModuleType, tmp_path: Path
):
    """A vendored .tgz lacking the nested chart (stale registry entry) returns None."""
    dep = {"name": "eck-stack", "version": "0.20.0"}
    make_tgz(
        tmp_path / "charts",
        "eck-stack",
        "0.20.0",
        {},
        raw_files={
            "eck-stack/charts/eck-elasticsearch/values.yaml": "# hello\n",
        },
    )
    assert libchartnestedsubchartidentity.nested_subchart_raw_text(tmp_path, dep, "eck-kibana", "values.yaml") is None


def test_nested_subchart_documented_image_repository_extracts_first_example(
    libchartnestedsubchartidentity: ModuleType, tmp_path: Path
):
    """The first "# image:" example wins, stripped of tag and digest (ECK lists plain first)."""
    dep = {"name": "eck-stack", "version": "0.20.0"}
    make_tgz(
        tmp_path / "charts",
        "eck-stack",
        "0.20.0",
        {},
        raw_files={
            "eck-stack/charts/eck-kibana/values.yaml": (
                "# Kibana Docker image to deploy.\n#\n"
                "# image: docker.elastic.co/kibana/kibana:9.5.0\n"
                "# image: docker.elastic.co/kibana/kibana:9.5.0@sha256:<digest>\n"
                "# image: docker.elastic.co/kibana/kibana@sha256:<digest>\n"
            ),
        },
    )
    assert (
        libchartnestedsubchartidentity.nested_subchart_documented_image_repository(tmp_path, dep, "eck-kibana")
        == "docker.elastic.co/kibana/kibana"
    )


def test_nested_subchart_documented_image_repository_no_comment_returns_none(
    libchartnestedsubchartidentity: ModuleType, tmp_path: Path
):
    dep = {"name": "eck-stack", "version": "0.20.0"}
    make_tgz(
        tmp_path / "charts",
        "eck-stack",
        "0.20.0",
        {},
        raw_files={
            "eck-stack/charts/eck-kibana/values.yaml": "enabled: true\n",
        },
    )
    assert (
        libchartnestedsubchartidentity.nested_subchart_documented_image_repository(tmp_path, dep, "eck-kibana") is None
    )


# --- subchart_dependencies ---


def test_subchart_dependencies_reads_own_chart_yaml(tmp_path: Path, libchartpullandsubchartresolution: ModuleType):
    dep = {"name": "openinwoner", "version": "2.4.0"}
    make_tgz(
        tmp_path / "charts",
        "openinwoner",
        "2.4.0",
        {},
        chart_yaml={
            "name": "openinwoner",
            "version": "2.4.0",
            "dependencies": [
                {"name": "eck-operator", "version": "3.2.0", "repository": "https://helm.elastic.co"},
                {"name": "redis", "version": "18.0.0", "repository": "https://charts.bitnami.com/bitnami"},
            ],
        },
    )
    deps = libchartpullandsubchartresolution.subchart_dependencies(tmp_path, dep)
    assert [d["name"] for d in deps] == ["eck-operator", "redis"]


def test_subchart_dependencies_missing_tgz_returns_empty_list(
    tmp_path: Path, libchartpullandsubchartresolution: ModuleType
):
    dep = {"name": "openinwoner", "version": "2.4.0"}
    assert libchartpullandsubchartresolution.subchart_dependencies(tmp_path, dep) == []


def test_subchart_dependencies_no_dependencies_key_returns_empty_list(
    tmp_path: Path, libchartpullandsubchartresolution: ModuleType
):
    dep = {"name": "zac", "version": "1.0.297"}
    make_tgz(tmp_path / "charts", "zac", "1.0.297", {}, chart_yaml={"name": "zac", "version": "1.0.297"})
    assert libchartpullandsubchartresolution.subchart_dependencies(tmp_path, dep) == []


# --- resolve_subchart_default ---


def test_resolve_subchart_default_top_level_uses_deps_own_app_version(
    tmp_path: Path, libchartpullandsubchartresolution: ModuleType
):
    dep = {"name": "eck-operator", "version": "3.5.0"}
    make_tgz(
        tmp_path / "charts",
        "eck-operator",
        "3.5.0",
        {},
        chart_yaml={
            "name": "eck-operator",
            "version": "3.5.0",
            "appVersion": "3.5.0",
        },
    )
    chart_tree_path, version = libchartpullandsubchartresolution.resolve_subchart_default(
        tmp_path, dep, "podiumd", ("image",)
    )
    assert chart_tree_path == "podiumd/charts/eck-operator"
    assert version == "3.5.0"


def test_resolve_subchart_default_nested_dependency_uses_its_own_chart_yaml(
    tmp_path: Path, libchartpullandsubchartresolution: ModuleType
):
    """A same-named nested dependency takes its path and version from its own files."""
    dep = {"name": "openinwoner", "version": "2.4.0"}
    make_tgz(
        tmp_path / "charts",
        "openinwoner",
        "2.4.0",
        {},
        chart_yaml={
            "name": "openinwoner",
            "version": "2.4.0",
            "dependencies": [{"name": "eck-operator", "version": "3.2.0", "repository": "https://helm.elastic.co"}],
        },
        raw_files={
            "openinwoner/charts/eck-operator/Chart.yaml": yaml.safe_dump(
                {"name": "eck-operator", "version": "3.2.0", "appVersion": "3.2.0"}
            ),
        },
    )
    chart_tree_path, version = libchartpullandsubchartresolution.resolve_subchart_default(
        tmp_path, dep, "podiumd", ("eck-operator", "image")
    )
    assert chart_tree_path == "podiumd/charts/openinwoner/charts/eck-operator"
    assert version == "3.2.0"


def test_resolve_subchart_default_no_nested_match_falls_back_to_top_level(
    tmp_path: Path, libchartpullandsubchartresolution: ModuleType
):
    """A values sub-key that isn't a nested dependency stays at dep's top-level path.

    The path uses the alias, as Helm's "# Source:" annotations do.
    """
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    make_tgz(
        tmp_path / "charts",
        "zaakafhandelcomponent",
        "1.0.297",
        {},
        chart_yaml={
            "name": "zaakafhandelcomponent",
            "version": "1.0.297",
            "appVersion": "5.4.3",
        },
    )
    chart_tree_path, version = libchartpullandsubchartresolution.resolve_subchart_default(
        tmp_path, dep, "podiumd", ("opa", "image")
    )
    assert chart_tree_path == "podiumd/charts/zac"
    assert version == "5.4.3"


def test_resolve_subchart_default_matches_nested_dependency_by_alias_too(
    tmp_path: Path, libchartpullandsubchartresolution: ModuleType
):
    """A nested dependency's path segment is its alias too."""
    dep = {"name": "openinwoner", "version": "2.4.0"}
    make_tgz(
        tmp_path / "charts",
        "openinwoner",
        "2.4.0",
        {},
        chart_yaml={
            "name": "openinwoner",
            "version": "2.4.0",
            "dependencies": [
                {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0", "repository": "https://helm.elastic.co"}
            ],
        },
        raw_files={
            "openinwoner/charts/eck-stack/Chart.yaml": yaml.safe_dump(
                {"name": "eck-stack", "version": "0.20.0", "appVersion": "unused"}
            ),
        },
    )
    chart_tree_path, _version = libchartpullandsubchartresolution.resolve_subchart_default(
        tmp_path, dep, "podiumd", ("kiss-eck", "image")
    )
    assert chart_tree_path == "podiumd/charts/openinwoner/charts/kiss-eck"


def test_resolve_subchart_default_version_none_when_not_vendored(
    tmp_path: Path, libchartpullandsubchartresolution: ModuleType
):
    dep = {"name": "eck-operator", "version": "3.5.0"}
    chart_tree_path, version = libchartpullandsubchartresolution.resolve_subchart_default(
        tmp_path, dep, "podiumd", ("image",)
    )
    assert chart_tree_path == "podiumd/charts/eck-operator"
    assert version is None


# --- own_template_files_referencing / resolve_values_path_source ---


def test_own_template_files_referencing_finds_a_literal_values_reference(
    libchartvaluestreeprimitives: ModuleType, tmp_path: Path
):
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "frankgateway-nginx.yaml").write_text(
        "image: {{ .Values.frankgateway.nginx.image.repository }}\n", encoding="utf-8"
    )
    (tmp_path / "templates" / "unrelated.yaml").write_text(
        "image: {{ .Values.apiproxy.image.repository }}\n", encoding="utf-8"
    )
    files = libchartvaluestreeprimitives.own_template_files_referencing(tmp_path, "frankgateway")
    assert files == ["templates/frankgateway-nginx.yaml"]


def test_own_template_files_referencing_no_templates_dir_returns_empty(
    libchartvaluestreeprimitives: ModuleType, tmp_path: Path
):
    assert libchartvaluestreeprimitives.own_template_files_referencing(tmp_path, "frankgateway") == []


def test_own_template_files_referencing_no_match_returns_empty(
    libchartvaluestreeprimitives: ModuleType, tmp_path: Path
):
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "unrelated.yaml").write_text(
        "image: {{ .Values.apiproxy.image.repository }}\n", encoding="utf-8"
    )
    assert libchartvaluestreeprimitives.own_template_files_referencing(tmp_path, "frankgateway") == []


def test_resolve_values_path_source_real_dependency_shows_chart_and_version(
    libchartvaluestreeprimitives: ModuleType, tmp_path: Path
):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    source = libchartvaluestreeprimitives.resolve_values_path_source(tmp_path, deps, ("zac", "nginx", "image"))
    assert source == "chart zaakafhandelcomponent@1.0.297"


def test_resolve_values_path_source_orphan_key_shows_local_template(
    libchartvaluestreeprimitives: ModuleType, tmp_path: Path
):
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "frankgateway-nginx.yaml").write_text(
        "image: {{ .Values.frankgateway.nginx.image.repository }}\n", encoding="utf-8"
    )
    source = libchartvaluestreeprimitives.resolve_values_path_source(tmp_path, [], ("frankgateway", "nginx", "image"))
    assert source == "local: templates/frankgateway-nginx.yaml"


def test_resolve_values_path_source_orphan_key_no_match_says_so(
    libchartvaluestreeprimitives: ModuleType, tmp_path: Path
):
    source = libchartvaluestreeprimitives.resolve_values_path_source(tmp_path, [], ("global", "images", "nginx"))
    assert source == "local: no referencing template found"
