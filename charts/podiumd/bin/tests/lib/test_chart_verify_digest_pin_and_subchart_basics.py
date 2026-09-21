"""lib.chart — chart-version verification, image-version/digest checks,
and subchart basics: verify_chart_version, check_image_versions,
version_of, resolved_digest_pin, find_images, image_paths_for,
dotted_key_path, subchart_values, subchart_app_version,
nested_subchart_raw_text, nested_subchart_documented_image_repository,
subchart_dependencies, resolve_subchart_default,
own_template_files_referencing, resolve_values_path_source. `helm pull`
is mocked via lib.procutil.run, so no `helm` binary or network access
needed. Split out of the former test_chart.py (see the other
test_chart_*.py files for the rest)."""

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


# --- verify_chart_version ---
# The chart-existence check verify-component-version owns (and
# verify-image-version no longer reimplements) — pull, report FOUND/
# MISSING, and either return the pulled values.yaml or exit 1.


def test_verify_chart_version_found_returns_values(tmp_path, monkeypatch, capsys, libchartpullandsubchartresolution):
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
    tmp_path, monkeypatch, capsys, libchartpullandsubchartresolution
):
    def raise_if_pulled(dep, version, dest):
        raise AssertionError("should not pull — an exact-version .tgz is already vendored")

    monkeypatch.setattr(libchartpullandsubchartresolution, "pull_chart", raise_if_pulled)
    dep = {"name": "openzaak", "version": "4.9.1", "repository": "@openzaak"}
    make_tgz(tmp_path / "charts", "openzaak", "4.9.1", {"image": {"repository": "openzaak/open-zaak"}})

    values = libchartpullandsubchartresolution.verify_chart_version(tmp_path, dep, "4.9.1")

    assert values == {"image": {"repository": "openzaak/open-zaak"}}
    assert "[FOUND  ] openzaak 4.9.1  (vendored)" in capsys.readouterr().out


def test_verify_chart_version_missing_exits_one(tmp_path, monkeypatch, capsys, libchartpullandsubchartresolution):
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


def test_check_image_versions_single_path_found(monkeypatch, libchartpullandsubchartresolution):
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


def test_check_image_versions_reports_missing_tag(monkeypatch, libchartpullandsubchartresolution):
    monkeypatch.setattr(libchartpullandsubchartresolution, "registry_tag_exists", lambda host, repo, tag: (False, None))
    values = {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}
    results = libchartpullandsubchartresolution.check_image_versions(values, ["image"], "9.9.9")
    assert results[0]["exists"] is False
    assert results[0]["digest"] is None


def test_check_image_versions_checks_every_multi_image_path(monkeypatch, libchartpullandsubchartresolution):
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


def test_check_image_versions_skips_path_with_no_repository(monkeypatch, libchartpullandsubchartresolution):
    """One path missing a "repository:" isn't fatal as long as at least one
    other path has one — only the resolvable path is checked/returned."""
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


def test_check_image_versions_raises_when_no_path_has_a_repository(monkeypatch, libchartpullandsubchartresolution):
    values = {"somethingElse": {"repository": "x/y"}}
    with pytest.raises(SystemExit, match="no repository found"):
        libchartpullandsubchartresolution.check_image_versions(values, ["image"], "5.4.3")


# --- version_of ---


def test_version_of_strips_digest(libchartvaluestreeprimitives):
    assert libchartvaluestreeprimitives.version_of("5.4.3@sha256:abc") == "5.4.3"
    assert libchartvaluestreeprimitives.version_of("1.19.0-static") == "1.19.0-static"


# --- resolved_digest_pin ---

# A minimal {tuple_path: {"sibling_field": ...}} table, the same shape
# lib.settings.digest_pinning_exceptions returns (resolved_digest_pin
# only ever reads .get(path, {}).get("sibling_field"), so a "writable"
# key isn't needed here) — covers the keycloak-operator split-path
# convention plus eck-operator's differently-named sibling field.
SIBLING_FIELDS = {
    ("keycloak-operator", "operator", "config", "keycloakImage"): {"sibling_field": "sha"},
    ("keycloak-operator", "operator", "image"): {"sibling_field": "sha"},
    ("keycloak", "image"): {"sibling_field": "sha"},
    ("eck-operator", "image"): {"sibling_field": "digest"},
}


def test_resolved_digest_pin_already_embedded_returned_as_is(libchartpullandsubchartresolution):
    values = {"zac": {"image": {"tag": "5.4.4@sha256:aaaa"}}}

    assert (
        libchartpullandsubchartresolution.resolved_digest_pin(
            values, ("zac", "image"), "5.4.4@sha256:aaaa", SIBLING_FIELDS
        )
        == "5.4.4@sha256:aaaa"
    )


def test_resolved_digest_pin_split_tag_sha_combines_sibling_sha(libchartpullandsubchartresolution):
    """keycloak-operator's own primary image (operator.config.keycloakImage)
    uses the adfinis chart's own split "tag:"/"sha:" convention — the
    "tag:" value alone never carries "@sha256:...", so a caller needing a
    real digest-pinned string (e.g. a new images-manifest entry) has to
    read it from the sibling "sha:" field instead."""
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


def test_resolved_digest_pin_split_tag_sha_no_sha_override_returns_none(libchartpullandsubchartresolution):
    """The vendored subchart's own default "sha:" (inherited, no podiumd
    override at all) isn't visible from values.yaml alone — nothing to
    combine, so this can't produce a digest-pinned string yet."""
    path = ("keycloak-operator", "operator", "config", "keycloakImage")
    values = {"keycloak-operator": {"operator": {"config": {"keycloakImage": {"tag": "26.7.2"}}}}}

    assert libchartpullandsubchartresolution.resolved_digest_pin(values, path, "26.7.2", SIBLING_FIELDS) is None


def test_resolved_digest_pin_ordinary_path_with_no_digest_returns_none(libchartpullandsubchartresolution):
    """A path outside the sibling_fields table with a bare,
    non-digest-pinned tag has no sibling field to fall back to at all —
    genuinely unresolvable here, unlike the split-tag-sha case."""
    values = {"openzaak": {"image": {"tag": "1.29.3"}}}

    assert (
        libchartpullandsubchartresolution.resolved_digest_pin(values, ("openzaak", "image"), "1.29.3", SIBLING_FIELDS)
        is None
    )


def test_resolved_digest_pin_eck_operator_combines_sibling_digest_field(libchartpullandsubchartresolution):
    """Regression test (real bug, real chart): eck-operator's own
    upstream chart names its sibling field "digest:", not "sha:" — the
    ONLY sibling_fields path that differs from the keycloak ones.
    Confirms resolved_digest_pin looks up the correct per-path sibling
    field NAME (sibling_fields[path]["sibling_field"]) rather than the
    old hardcoded ".sha"."""
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


def test_resolved_digest_pin_eck_operator_no_digest_override_returns_none(libchartpullandsubchartresolution):
    """Same "vendored default, no podiumd override visible" shape as the
    keycloak sha-less case above — eck-operator's own sibling "digest:"
    field, when absent, still correctly falls through to None rather
    than crashing on a missing key."""
    path = ("eck-operator", "image")
    values = {"eck-operator": {"image": {"tag": "3.5.0"}}}

    assert libchartpullandsubchartresolution.resolved_digest_pin(values, path, "3.5.0", SIBLING_FIELDS) is None


# --- find_images ---


def test_find_images_nested_dict_and_list(libchartvaluestreeprimitives):
    values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.3@sha256:abc"}},
        "items": [{"image": {"repository": "curlimages/curl", "tag": "8.21.0"}}],
    }
    images = libchartvaluestreeprimitives.find_images(values)
    assert ("zac.image", "ghcr.io/infonl/zaakafhandelcomponent", "5.4.3@sha256:abc") in images
    assert ("items[0].image", "curlimages/curl", "8.21.0") in images


def test_find_images_skips_empty_tag(libchartvaluestreeprimitives):
    assert libchartvaluestreeprimitives.find_images({"image": {"repository": "x", "tag": ""}}) == []


def test_find_images_root_path_label(libchartvaluestreeprimitives):
    assert libchartvaluestreeprimitives.find_images({"repository": "x", "tag": "1.0"}) == [("(root)", "x", "1.0")]


# --- image_paths_for ---


def test_image_paths_for_multi_image_component(libchartregisteredpaths):
    assert libchartregisteredpaths.image_paths_for("zgw-office-addin") == ["frontend.image", "backend.image"]


def test_image_paths_for_ita_web_and_poller(libchartregisteredpaths):
    """ITA has no single "app" image at all — web and poller are two
    co-equal images, same lockstep shape as zgw-office-addin's own
    frontend+backend split."""
    assert libchartregisteredpaths.image_paths_for("internetaakafhandeling") == ["web.image", "poller.image"]


def test_image_paths_for_kiss_chart_frontend_and_sync_jobs(libchartregisteredpaths):
    """kiss-chart's own frontend image ("image") and its
    settings.syncJobs.image (the elastic-sync CronJob) are released from
    the same kiss-chart version and always move together — same
    co-equal lockstep shape as internetaakafhandeling's web+poller split.
    NOT syncJobs.crawlerImage/indexTemplateImage (the Elastic Open
    Crawler images) — those have independent upstream version lines."""
    assert libchartregisteredpaths.image_paths_for("kiss-chart") == ["image", "settings.syncJobs.image"]


def test_image_paths_for_unlisted_component_defaults_to_single_image_block(libchartregisteredpaths):
    assert libchartregisteredpaths.image_paths_for("zac") == ["image"]


# --- dotted_key_path ---


def test_dotted_key_path_nested_component(libchartvaluestreeprimitives):
    lines = [
        "openzaak:",
        "  image:",
        '    tag: "1.27.4@sha256:aaaa"',
    ]
    assert libchartvaluestreeprimitives.dotted_key_path(lines, 2) == "openzaak.image.tag"


def test_dotted_key_path_ignores_comments_and_blank_lines(libchartvaluestreeprimitives):
    lines = [
        "a:",
        "  # a comment",
        "",
        "  image:",
        '    tag: "1.0.0@sha256:aaaa"',
    ]
    assert libchartvaluestreeprimitives.dotted_key_path(lines, 4) == "a.image.tag"


def test_dotted_key_path_pops_stack_on_dedent(libchartvaluestreeprimitives):
    lines = [
        "a:",
        "  b:",
        "    c: 1",
        "d:",
        "  e: 2",
    ]
    assert libchartvaluestreeprimitives.dotted_key_path(lines, 4) == "d.e"


# --- subchart_values ---


def test_subchart_values_reads_vendored_tgz(tmp_path, libchartpullandsubchartresolution):
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {"repository": "openzaak/open-zaak"}})
    dep = {"name": "openzaak", "version": "1.14.2"}
    assert libchartpullandsubchartresolution.subchart_values(tmp_path, dep) == {
        "image": {"repository": "openzaak/open-zaak"}
    }


def test_subchart_values_missing_tgz_returns_none(tmp_path, libchartpullandsubchartresolution):
    dep = {"name": "openzaak", "version": "1.14.2"}
    assert libchartpullandsubchartresolution.subchart_values(tmp_path, dep) is None


def test_subchart_values_missing_member_returns_none(tmp_path, libchartpullandsubchartresolution):
    charts_dir = tmp_path / "charts"
    charts_dir.mkdir()
    with tarfile.open(charts_dir / "openzaak-1.14.2.tgz", "w:gz"):
        pass  # empty archive, no values.yaml member
    dep = {"name": "openzaak", "version": "1.14.2"}
    assert libchartpullandsubchartresolution.subchart_values(tmp_path, dep) is None


# --- subchart_app_version ---


def test_subchart_app_version_reads_vendored_chart_yaml(tmp_path, libchartpullandsubchartresolution):
    make_tgz(
        tmp_path / "charts",
        "openbao",
        "0.28.4",
        {"server": {"image": {"tag": ""}}},
        chart_yaml={"apiVersion": "v2", "version": "0.28.4", "appVersion": "v2.5.5"},
    )
    dep = {"name": "openbao", "version": "0.28.4"}
    assert libchartpullandsubchartresolution.subchart_app_version(tmp_path, dep) == "v2.5.5"


def test_subchart_app_version_missing_tgz_returns_none(tmp_path, libchartpullandsubchartresolution):
    dep = {"name": "openbao", "version": "0.28.4"}
    assert libchartpullandsubchartresolution.subchart_app_version(tmp_path, dep) is None


def test_subchart_app_version_missing_member_returns_none(tmp_path, libchartpullandsubchartresolution):
    make_tgz(tmp_path / "charts", "openbao", "0.28.4", {"server": {"image": {"tag": ""}}})  # no chart_yaml
    dep = {"name": "openbao", "version": "0.28.4"}
    assert libchartpullandsubchartresolution.subchart_app_version(tmp_path, dep) is None


def test_subchart_app_version_no_app_version_field_returns_none(tmp_path, libchartpullandsubchartresolution):
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


def test_nested_subchart_raw_text_reads_nested_file(libchartnestedsubchartidentity, tmp_path):
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


def test_nested_subchart_raw_text_missing_tgz_returns_none(libchartnestedsubchartidentity, tmp_path):
    dep = {"name": "eck-stack", "version": "0.20.0"}
    assert (
        libchartnestedsubchartidentity.nested_subchart_raw_text(tmp_path, dep, "eck-elasticsearch", "values.yaml")
        is None
    )


def test_nested_subchart_raw_text_missing_nested_chart_returns_none(libchartnestedsubchartidentity, tmp_path):
    """The outer .tgz IS vendored, but has no charts/eck-kibana/ inside
    it at all (e.g. a stale/mismatched registry entry) — no crash."""
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


def test_nested_subchart_documented_image_repository_extracts_first_example(libchartnestedsubchartidentity, tmp_path):
    """The FIRST "# image: <repo>[:<tag>]" comment wins — every ECK-
    family sub-subchart lists the plain "<repo>:<version>" form first,
    then a digest-suffixed variant, then a bare "@sha256:..." form; only
    the plain repository (no tag, no digest) is wanted."""
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


def test_nested_subchart_documented_image_repository_no_comment_returns_none(libchartnestedsubchartidentity, tmp_path):
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


def test_subchart_dependencies_reads_own_chart_yaml(tmp_path, libchartpullandsubchartresolution):
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


def test_subchart_dependencies_missing_tgz_returns_empty_list(tmp_path, libchartpullandsubchartresolution):
    dep = {"name": "openinwoner", "version": "2.4.0"}
    assert libchartpullandsubchartresolution.subchart_dependencies(tmp_path, dep) == []


def test_subchart_dependencies_no_dependencies_key_returns_empty_list(tmp_path, libchartpullandsubchartresolution):
    dep = {"name": "zac", "version": "1.0.297"}
    make_tgz(tmp_path / "charts", "zac", "1.0.297", {}, chart_yaml={"name": "zac", "version": "1.0.297"})
    assert libchartpullandsubchartresolution.subchart_dependencies(tmp_path, dep) == []


# --- resolve_subchart_default ---


def test_resolve_subchart_default_top_level_uses_deps_own_app_version(tmp_path, libchartpullandsubchartresolution):
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
    tmp_path, libchartpullandsubchartresolution
):
    """openinwoner's own bundled eck-operator (3.2.0) is a SEPARATE,
    same-named nested dependency of openinwoner's own Chart.yaml,
    distinct from the top-level "eck-operator" dependency (3.5.0) —
    both the chart-tree path and the version must come from the NESTED
    dependency's own files, not openinwoner's."""
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


def test_resolve_subchart_default_no_nested_match_falls_back_to_top_level(tmp_path, libchartpullandsubchartresolution):
    """path[0] not matching any of dep's own nested dependencies — e.g.
    zac's own "opa" sidecar — stays at dep's own top-level path (opa
    isn't a real Chart.yaml dependency, just a values sub-key). The
    chart-tree path itself is keyed by dep's own alias ("zac"), never
    its real chart name ("zaakafhandelcomponent") — confirmed live
    against the real chart: Helm's own "# Source:" annotations name a
    chart-tree directory by alias when the dependency declares one."""
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


def test_resolve_subchart_default_matches_nested_dependency_by_alias_too(tmp_path, libchartpullandsubchartresolution):
    """The NESTED dependency's own chart-tree segment is likewise keyed
    by ITS OWN alias ("kiss-eck"), not its real chart name ("eck-stack")
    — same convention, one level deeper."""
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


def test_resolve_subchart_default_version_none_when_not_vendored(tmp_path, libchartpullandsubchartresolution):
    dep = {"name": "eck-operator", "version": "3.5.0"}
    chart_tree_path, version = libchartpullandsubchartresolution.resolve_subchart_default(
        tmp_path, dep, "podiumd", ("image",)
    )
    assert chart_tree_path == "podiumd/charts/eck-operator"
    assert version is None


# --- own_template_files_referencing / resolve_values_path_source ---


def test_own_template_files_referencing_finds_a_literal_values_reference(libchartvaluestreeprimitives, tmp_path):
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "frankgateway-nginx.yaml").write_text(
        "image: {{ .Values.frankgateway.nginx.image.repository }}\n", encoding="utf-8"
    )
    (tmp_path / "templates" / "unrelated.yaml").write_text(
        "image: {{ .Values.apiproxy.image.repository }}\n", encoding="utf-8"
    )
    files = libchartvaluestreeprimitives.own_template_files_referencing(tmp_path, "frankgateway")
    assert files == ["templates/frankgateway-nginx.yaml"]


def test_own_template_files_referencing_no_templates_dir_returns_empty(libchartvaluestreeprimitives, tmp_path):
    assert libchartvaluestreeprimitives.own_template_files_referencing(tmp_path, "frankgateway") == []


def test_own_template_files_referencing_no_match_returns_empty(libchartvaluestreeprimitives, tmp_path):
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "unrelated.yaml").write_text(
        "image: {{ .Values.apiproxy.image.repository }}\n", encoding="utf-8"
    )
    assert libchartvaluestreeprimitives.own_template_files_referencing(tmp_path, "frankgateway") == []


def test_resolve_values_path_source_real_dependency_shows_chart_and_version(libchartvaluestreeprimitives, tmp_path):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    source = libchartvaluestreeprimitives.resolve_values_path_source(tmp_path, deps, ("zac", "nginx", "image"))
    assert source == "chart zaakafhandelcomponent@1.0.297"


def test_resolve_values_path_source_orphan_key_shows_local_template(libchartvaluestreeprimitives, tmp_path):
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "frankgateway-nginx.yaml").write_text(
        "image: {{ .Values.frankgateway.nginx.image.repository }}\n", encoding="utf-8"
    )
    source = libchartvaluestreeprimitives.resolve_values_path_source(tmp_path, [], ("frankgateway", "nginx", "image"))
    assert source == "local: templates/frankgateway-nginx.yaml"


def test_resolve_values_path_source_orphan_key_no_match_says_so(libchartvaluestreeprimitives, tmp_path):
    source = libchartvaluestreeprimitives.resolve_values_path_source(tmp_path, [], ("global", "images", "nginx"))
    assert source == "local: no referencing template found"
