"""lib.chart — get_path, replace_scalar_value, chart_version, SEMVER_RE,
find_dependency, chart_ref, local_chart_dir, pull_chart, pulled_chart_dir,
pull_chart_values, find_images, version_of, image_paths_for, dotted_key_path,
subchart_values, subchart_default_repository, resolve_chart_values,
primary_image_repositories. `helm pull` is mocked via lib.procutil.run, so
no `helm` binary or network access needed."""
import io
import tarfile
from pathlib import Path

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


# --- get_path ---

def test_get_path_nested(libchart):
    assert libchart.get_path({"a": {"b": {"c": 1}}}, "a.b.c") == 1


def test_get_path_missing_returns_none(libchart):
    assert libchart.get_path({"a": {}}, "a.b.c") is None


def test_get_path_non_dict_intermediate_returns_none(libchart):
    assert libchart.get_path({"a": "scalar"}, "a.b") is None


# --- replace_scalar_value ---
# moved here from update-component-version (see
# tests/update-component-version/test_update_component_version.py for the
# ucv.replace_scalar_value re-export, still exercised via that import).

def test_replace_scalar_value_preserves_quotes(libchart):
    assert libchart.replace_scalar_value('      tag: "1.0.0@sha256:aaaa"\n', "2.0.0@sha256:bbbb") == \
        '      tag: "2.0.0@sha256:bbbb"\n'


def test_replace_scalar_value_preserves_bare_style(libchart):
    assert libchart.replace_scalar_value("    version: 1.0.297\n", "1.0.298") == "    version: 1.0.298\n"


def test_replace_scalar_value_preserves_trailing_comment(libchart):
    result = libchart.replace_scalar_value('    version: 1.0.297  # pinned\n', "1.0.298")
    assert result == '    version: 1.0.298  # pinned\n'


def test_replace_scalar_value_unparseable_line_raises(libchart):
    with pytest.raises(SystemExit):
        libchart.replace_scalar_value("not a key-value line at all\n", "x")


# --- chart_version / SEMVER_RE ---
# shared by create-doc-version, fix-doc-consistency, update-component-
# version, and create-podiumd-version's own current_chart_version()/
# *_VERSION_RE re-exports — see those scripts' own tests for the
# re-export coverage.

def test_chart_version_reads_top_level_version(libchart, tmp_path):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text("apiVersion: v2\nname: podiumd\nversion: 4.9.0\n", encoding="utf-8")
    assert libchart.chart_version(chart_yaml) == "4.9.0"


def test_semver_re_matches_bare_version(libchart):
    assert libchart.SEMVER_RE.match("4.8.2")
    assert libchart.SEMVER_RE.match("10.20.300")


def test_semver_re_rejects_anything_else(libchart):
    assert not libchart.SEMVER_RE.match("4.8")
    assert not libchart.SEMVER_RE.match("v4.8.2")
    assert not libchart.SEMVER_RE.match("--help")
    assert not libchart.SEMVER_RE.match("4.8.2-rc1")


# --- upgrade_docs_baseline / release_table_baseline ---
# release-baseline.yaml — see lib.chart's RELEASE_BASELINES_FILE_NAME/
# _release_baselines for why podiumd needs two baselines (incremental
# _UPGRADE_PATHS/images-manifest vs. cumulative release-table.csv).

def test_upgrade_docs_baseline_reads_the_key(libchart, tmp_path):
    (tmp_path / "release-baseline.yaml").write_text(
        "upgrade_docs: '4.9.0'\nrelease_table: '4.8.5'\n", encoding="utf-8")
    assert libchart.upgrade_docs_baseline(tmp_path) == "4.9.0"


def test_release_table_baseline_reads_the_key(libchart, tmp_path):
    (tmp_path / "release-baseline.yaml").write_text(
        "upgrade_docs: '4.9.0'\nrelease_table: '4.8.5'\n", encoding="utf-8")
    assert libchart.release_table_baseline(tmp_path) == "4.8.5"


def test_upgrade_docs_baseline_none_when_file_missing(libchart, tmp_path):
    assert libchart.upgrade_docs_baseline(tmp_path) is None


def test_release_table_baseline_none_when_file_missing(libchart, tmp_path):
    assert libchart.release_table_baseline(tmp_path) is None


def test_upgrade_docs_baseline_none_when_key_missing(libchart, tmp_path):
    (tmp_path / "release-baseline.yaml").write_text("release_table: '4.8.5'\n", encoding="utf-8")
    assert libchart.upgrade_docs_baseline(tmp_path) is None


def test_release_table_baseline_none_when_key_missing(libchart, tmp_path):
    (tmp_path / "release-baseline.yaml").write_text("upgrade_docs: '4.9.0'\n", encoding="utf-8")
    assert libchart.release_table_baseline(tmp_path) is None


# --- write_release_baselines ---

def test_write_release_baselines_creates_file_with_both_keys(libchart, tmp_path):
    libchart.write_release_baselines(tmp_path, upgrade_docs="4.9.0", release_table="4.8.5")
    assert libchart.upgrade_docs_baseline(tmp_path) == "4.9.0"
    assert libchart.release_table_baseline(tmp_path) == "4.8.5"


def test_write_release_baselines_updates_only_upgrade_docs_leaves_release_table(libchart, tmp_path):
    libchart.write_release_baselines(tmp_path, upgrade_docs="4.9.0", release_table="4.8.5")
    libchart.write_release_baselines(tmp_path, upgrade_docs="4.9.1")
    assert libchart.upgrade_docs_baseline(tmp_path) == "4.9.1"
    assert libchart.release_table_baseline(tmp_path) == "4.8.5"


def test_write_release_baselines_updates_only_release_table_leaves_upgrade_docs(libchart, tmp_path):
    libchart.write_release_baselines(tmp_path, upgrade_docs="4.9.0", release_table="4.8.5")
    libchart.write_release_baselines(tmp_path, release_table="4.9.0")
    assert libchart.upgrade_docs_baseline(tmp_path) == "4.9.0"
    assert libchart.release_table_baseline(tmp_path) == "4.9.0"


def test_write_release_baselines_no_args_leaves_both_unchanged(libchart, tmp_path):
    libchart.write_release_baselines(tmp_path, upgrade_docs="4.9.0", release_table="4.8.5")
    libchart.write_release_baselines(tmp_path)
    assert libchart.upgrade_docs_baseline(tmp_path) == "4.9.0"
    assert libchart.release_table_baseline(tmp_path) == "4.8.5"


# --- find_dependency ---

def test_find_dependency_by_name(libchart):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac"}]
    assert libchart.find_dependency(deps, "zaakafhandelcomponent")["alias"] == "zac"


def test_find_dependency_by_alias(libchart):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac"}]
    assert libchart.find_dependency(deps, "zac")["name"] == "zaakafhandelcomponent"


def test_find_dependency_not_found_returns_none(libchart):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac"}]
    assert libchart.find_dependency(deps, "totally-unknown") is None


# --- find_app_versions ---
# shared by show-component-baseline-version and show-image-baseline-
# version, via component_state_at_ref below.

def test_find_app_versions_single_image(libchart):
    values = {"zac": {"image": {"tag": "5.0.2@sha256:abc"}}}
    assert libchart.find_app_versions(values, "zac", ["image"]) == [("image", "5.0.2@sha256:abc")]


def test_find_app_versions_multi_image(libchart):
    values = {"zgw-office-addin": {
        "frontend": {"image": {"tag": "v0.9.313@sha256:a"}},
        "backend": {"image": {"tag": "v0.9.313@sha256:b"}},
    }}
    result = libchart.find_app_versions(values, "zgw-office-addin", ["frontend.image", "backend.image"])
    assert result == [("frontend.image", "v0.9.313@sha256:a"), ("backend.image", "v0.9.313@sha256:b")]


def test_find_app_versions_missing_key_returns_empty(libchart):
    assert libchart.find_app_versions({}, "zac", ["image"]) == []


def test_find_app_versions_empty_tag_is_skipped(libchart):
    values = {"zac": {"image": {"tag": ""}}}
    assert libchart.find_app_versions(values, "zac", ["image"]) == []


# --- component_state_at_ref ---
# the full "resolve a component's baseline state via git show" pipeline
# shared by show-component-baseline-version and show-image-baseline-
# version. git_show_yaml itself (and the real `git show` it wraps) is
# lib.gitutil's own — see tests/lib/test_gitutil.py — these tests mock it
# out and only exercise this function's own glue: reading Chart.yaml,
# finding the dependency, and looking up its app version(s).

def test_component_state_at_ref_success(libchart, monkeypatch):
    def fake_git_show_yaml(repo_root, ref, relpath):
        if relpath.endswith("Chart.yaml"):
            return {"dependencies": [
                {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
            ]}
        return {"zac": {"image": {"tag": "5.0.2@sha256:abc"}}}

    monkeypatch.setattr(libchart, "git_show_yaml", fake_git_show_yaml)

    dep, values_key, image_paths, app_versions, error = libchart.component_state_at_ref(
        "repo_root", "podiumd-4.8.5", "charts/podiumd", "zac")

    assert error is None
    assert dep["name"] == "zaakafhandelcomponent"
    assert values_key == "zac"
    assert image_paths == ["image"]
    assert app_versions == [("image", "5.0.2@sha256:abc")]


def test_component_state_at_ref_unreadable_chart_yaml(libchart, monkeypatch):
    monkeypatch.setattr(libchart, "git_show_yaml", lambda repo_root, ref, relpath: None)

    dep, values_key, image_paths, app_versions, error = libchart.component_state_at_ref(
        "repo_root", "podiumd-4.8.5", "charts/podiumd", "zac")

    assert dep is values_key is image_paths is app_versions is None
    assert error == "could not read charts/podiumd/Chart.yaml at podiumd-4.8.5"


def test_component_state_at_ref_dependency_not_found(libchart, monkeypatch):
    monkeypatch.setattr(libchart, "git_show_yaml",
                         lambda repo_root, ref, relpath: {"dependencies": []} if relpath.endswith("Chart.yaml") else {})

    dep, values_key, image_paths, app_versions, error = libchart.component_state_at_ref(
        "repo_root", "podiumd-4.8.5", "charts/podiumd", "totally-unknown")

    assert dep is values_key is image_paths is app_versions is None
    assert error == ("no dependency named or aliased 'totally-unknown' "
                      "in charts/podiumd/Chart.yaml at podiumd-4.8.5")


# --- chart_ref ---

def test_chart_ref_alias_repository(libchart):
    ref, repo_url = libchart.chart_ref({"name": "zaakafhandelcomponent", "repository": "@zac"})
    assert ref == "zac/zaakafhandelcomponent"
    assert repo_url is None


def test_chart_ref_oci_repository(libchart):
    ref, repo_url = libchart.chart_ref(
        {"name": "internetaakafhandeling", "repository": "oci://ghcr.io/interne-taak-afhandeling"}
    )
    assert ref == "oci://ghcr.io/interne-taak-afhandeling/internetaakafhandeling"
    assert repo_url is None


def test_chart_ref_https_repository(libchart):
    ref, repo_url = libchart.chart_ref({"name": "openforms", "repository": "https://maykinmedia.github.io/charts/"})
    assert ref == "openforms"
    assert repo_url == "https://maykinmedia.github.io/charts/"


def test_chart_ref_file_repository_returns_none_none(libchart):
    assert libchart.chart_ref({"name": "mi-data", "repository": "file://../mi-data"}) == (None, None)


def test_chart_ref_unsupported_scheme_raises(libchart):
    with pytest.raises(SystemExit, match="unsupported repository scheme"):
        libchart.chart_ref({"name": "x", "repository": "ftp://nope"})


# --- local_chart_dir ---

def test_local_chart_dir_resolves_relative_to_chart_dir(libchart, tmp_path):
    dep = {"name": "mi-data", "repository": "file://../mi-data"}
    assert libchart.local_chart_dir(tmp_path / "podiumd", dep) == (tmp_path / "mi-data").resolve()


def test_local_chart_dir_none_for_other_schemes(libchart):
    assert libchart.local_chart_dir(Path("/x"), {"name": "zac", "repository": "@zac"}) is None
    assert libchart.local_chart_dir(Path("/x"), {"name": "zac", "repository": "oci://ghcr.io/x"}) is None


# --- pull_chart ---

def test_pull_chart_local_repository_fails_without_subprocess(libchart, tmp_path):
    dep = {"name": "mi-data", "repository": "file://../mi-data"}
    ok, stderr = libchart.pull_chart(dep, "1.0.0", tmp_path)
    assert ok is False
    assert "not fetchable remotely" in stderr


def test_pull_chart_builds_correct_command(libchart, monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        from types import SimpleNamespace
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(libchart, "run", fake_run)
    dep = {"name": "zaakafhandelcomponent", "repository": "@zac"}
    ok, stderr = libchart.pull_chart(dep, "1.0.297", tmp_path)
    assert ok is True
    assert captured["cmd"] == [
        "helm", "pull", "zac/zaakafhandelcomponent", "--version", "1.0.297",
        "--untar", "--untardir", str(tmp_path),
    ]


def test_pull_chart_https_repo_adds_repo_flag(libchart, monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        from types import SimpleNamespace
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(libchart, "run", fake_run)
    dep = {"name": "openforms", "repository": "https://maykinmedia.github.io/charts/"}
    libchart.pull_chart(dep, "1.12.0", tmp_path)
    assert "--repo" in captured["cmd"]
    assert "https://maykinmedia.github.io/charts/" in captured["cmd"]


def test_pull_chart_failure_returns_stderr(libchart, monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        from types import SimpleNamespace
        return SimpleNamespace(returncode=1, stdout="", stderr="version not found\n")

    monkeypatch.setattr(libchart, "run", fake_run)
    dep = {"name": "zaakafhandelcomponent", "repository": "@zac"}
    ok, stderr = libchart.pull_chart(dep, "9.9.9", tmp_path)
    assert ok is False
    assert stderr == "version not found"


# --- pulled_chart_dir ---

def test_pulled_chart_dir_returns_the_single_directory(libchart, tmp_path):
    (tmp_path / "somechart").mkdir()
    (tmp_path / "somefile.txt").write_text("x")
    assert libchart.pulled_chart_dir(tmp_path) == tmp_path / "somechart"


def test_pulled_chart_dir_raises_when_empty(libchart, tmp_path):
    with pytest.raises(SystemExit, match="produced no chart directory"):
        libchart.pulled_chart_dir(tmp_path)


# --- pull_chart_values ---

def test_pull_chart_values_reads_pulled_values_yaml(libchart, monkeypatch):
    def fake_pull_chart(dep, version, dest):
        chart_dir = dest / dep["name"]
        chart_dir.mkdir(parents=True)
        (chart_dir / "values.yaml").write_text(
            yaml.safe_dump({"image": {"repository": "maykinmedia/open-forms"}}), encoding="utf-8"
        )
        return True, ""

    monkeypatch.setattr(libchart, "pull_chart", fake_pull_chart)
    dep = {"name": "openforms", "repository": "@maykinmedia"}
    values = libchart.pull_chart_values(dep, "1.12.0")
    assert values == {"image": {"repository": "maykinmedia/open-forms"}}


def test_pull_chart_values_raises_on_pull_failure(libchart, monkeypatch):
    monkeypatch.setattr(libchart, "pull_chart", lambda dep, version, dest: (False, "not found"))
    dep = {"name": "openforms", "repository": "@maykinmedia"}
    with pytest.raises(SystemExit, match="could not pull"):
        libchart.pull_chart_values(dep, "9.9.9")


# --- verify_chart_version ---
# The chart-existence check verify-component-version owns (and
# verify-image-version no longer reimplements) — pull, report FOUND/
# MISSING, and either return the pulled values.yaml or exit 1.

def test_verify_chart_version_found_returns_values(libchart, tmp_path, monkeypatch, capsys):
    def fake_pull_chart(dep, version, dest):
        chart_dir = dest / dep["name"]
        chart_dir.mkdir(parents=True)
        (chart_dir / "values.yaml").write_text(
            yaml.safe_dump({"image": {"repository": "infonl/zac"}}), encoding="utf-8"
        )
        return True, ""

    monkeypatch.setattr(libchart, "pull_chart", fake_pull_chart)
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297", "repository": "@zac"}

    values = libchart.verify_chart_version(tmp_path, dep, "1.0.297")

    assert values == {"image": {"repository": "infonl/zac"}}
    out = capsys.readouterr().out
    assert "[FOUND  ] zaakafhandelcomponent 1.0.297" in out


def test_verify_chart_version_prefers_vendored_tgz_without_pulling(libchart, tmp_path, monkeypatch, capsys):
    def raise_if_pulled(dep, version, dest):
        raise AssertionError("should not pull — an exact-version .tgz is already vendored")

    monkeypatch.setattr(libchart, "pull_chart", raise_if_pulled)
    dep = {"name": "openzaak", "version": "4.9.1", "repository": "@openzaak"}
    make_tgz(tmp_path / "charts", "openzaak", "4.9.1", {"image": {"repository": "openzaak/open-zaak"}})

    values = libchart.verify_chart_version(tmp_path, dep, "4.9.1")

    assert values == {"image": {"repository": "openzaak/open-zaak"}}
    assert "[FOUND  ] openzaak 4.9.1  (vendored)" in capsys.readouterr().out


def test_verify_chart_version_missing_exits_one(libchart, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(libchart, "pull_chart", lambda dep, version, dest: (False, "version not found"))
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297", "repository": "@zac"}

    with pytest.raises(SystemExit) as exc_info:
        libchart.verify_chart_version(tmp_path, dep, "9.9.9")

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "[MISSING] zaakafhandelcomponent 9.9.9  (version not found)" in out
    assert "FAIL: chart version does not exist" in out


# --- check_image_versions ---

def test_check_image_versions_single_path_found(libchart, monkeypatch):
    monkeypatch.setattr(libchart, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:abc"))
    values = {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}
    results = libchart.check_image_versions(values, ["image"], "5.4.3")
    assert results == [{
        "path": "image", "repository": "ghcr.io/infonl/zaakafhandelcomponent", "host": "ghcr.io",
        "repo_path": "infonl/zaakafhandelcomponent", "exists": True, "digest": "sha256:abc",
    }]


def test_check_image_versions_reports_missing_tag(libchart, monkeypatch):
    monkeypatch.setattr(libchart, "registry_tag_exists", lambda host, repo, tag: (False, None))
    values = {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}
    results = libchart.check_image_versions(values, ["image"], "9.9.9")
    assert results[0]["exists"] is False
    assert results[0]["digest"] is None


def test_check_image_versions_checks_every_multi_image_path(libchart, monkeypatch):
    checked = []

    def fake_registry_tag_exists(host, repo, tag):
        checked.append(repo)
        return True, "sha256:fake"

    monkeypatch.setattr(libchart, "registry_tag_exists", fake_registry_tag_exists)
    values = {
        "frontend": {"image": {"repository": "ghcr.io/infonl/zgw-office-addin-frontend"}},
        "backend": {"image": {"repository": "ghcr.io/infonl/zgw-office-addin-backend"}},
    }
    results = libchart.check_image_versions(values, ["frontend.image", "backend.image"], "0.11.0")
    assert checked == ["infonl/zgw-office-addin-frontend", "infonl/zgw-office-addin-backend"]
    assert [r["path"] for r in results] == ["frontend.image", "backend.image"]


def test_check_image_versions_skips_path_with_no_repository(libchart, monkeypatch):
    """One path missing a "repository:" isn't fatal as long as at least one
    other path has one — only the resolvable path is checked/returned."""
    monkeypatch.setattr(libchart, "registry_tag_exists", lambda host, repo, tag: (True, "sha256:fake"))
    values = {
        "frontend": {"image": {"repository": "ghcr.io/infonl/zgw-office-addin-frontend"}},
        "backend": {"image": {}},
    }
    results = libchart.check_image_versions(values, ["frontend.image", "backend.image"], "0.11.0")
    assert [r["path"] for r in results] == ["frontend.image"]


def test_check_image_versions_raises_when_no_path_has_a_repository(libchart, monkeypatch):
    values = {"somethingElse": {"repository": "x/y"}}
    with pytest.raises(SystemExit, match="no repository found"):
        libchart.check_image_versions(values, ["image"], "5.4.3")


# --- version_of ---

def test_version_of_strips_digest(libchart):
    assert libchart.version_of("5.4.3@sha256:abc") == "5.4.3"
    assert libchart.version_of("1.19.0-static") == "1.19.0-static"


# --- find_images ---

def test_find_images_nested_dict_and_list(libchart):
    values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.3@sha256:abc"}},
        "items": [{"image": {"repository": "curlimages/curl", "tag": "8.21.0"}}],
    }
    images = libchart.find_images(values)
    assert ("zac.image", "ghcr.io/infonl/zaakafhandelcomponent", "5.4.3@sha256:abc") in images
    assert ("items[0].image", "curlimages/curl", "8.21.0") in images


def test_find_images_skips_empty_tag(libchart):
    assert libchart.find_images({"image": {"repository": "x", "tag": ""}}) == []


def test_find_images_root_path_label(libchart):
    assert libchart.find_images({"repository": "x", "tag": "1.0"}) == [("(root)", "x", "1.0")]


# --- image_paths_for ---

def test_image_paths_for_multi_image_component(libchart):
    assert libchart.image_paths_for("zgw-office-addin") == ["frontend.image", "backend.image"]


def test_image_paths_for_ita_web_and_poller(libchart):
    """ITA has no single "app" image at all — web and poller are two
    co-equal images, same lockstep shape as zgw-office-addin's own
    frontend+backend split."""
    assert libchart.image_paths_for("internetaakafhandeling") == ["web.image", "poller.image"]


def test_image_paths_for_unlisted_component_defaults_to_single_image_block(libchart):
    assert libchart.image_paths_for("zac") == ["image"]


# --- dotted_key_path ---

def test_dotted_key_path_nested_component(libchart):
    lines = [
        "openzaak:",
        "  image:",
        '    tag: "1.27.4@sha256:aaaa"',
    ]
    assert libchart.dotted_key_path(lines, 2) == "openzaak.image.tag"


def test_dotted_key_path_ignores_comments_and_blank_lines(libchart):
    lines = [
        "a:",
        "  # a comment",
        "",
        "  image:",
        '    tag: "1.0.0@sha256:aaaa"',
    ]
    assert libchart.dotted_key_path(lines, 4) == "a.image.tag"


def test_dotted_key_path_pops_stack_on_dedent(libchart):
    lines = [
        "a:",
        "  b:",
        "    c: 1",
        "d:",
        "  e: 2",
    ]
    assert libchart.dotted_key_path(lines, 4) == "d.e"


# --- subchart_values ---

def test_subchart_values_reads_vendored_tgz(libchart, tmp_path):
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {"repository": "openzaak/open-zaak"}})
    dep = {"name": "openzaak", "version": "1.14.2"}
    assert libchart.subchart_values(tmp_path, dep) == {"image": {"repository": "openzaak/open-zaak"}}


def test_subchart_values_missing_tgz_returns_none(libchart, tmp_path):
    dep = {"name": "openzaak", "version": "1.14.2"}
    assert libchart.subchart_values(tmp_path, dep) is None


def test_subchart_values_missing_member_returns_none(libchart, tmp_path):
    charts_dir = tmp_path / "charts"
    charts_dir.mkdir()
    with tarfile.open(charts_dir / "openzaak-1.14.2.tgz", "w:gz"):
        pass  # empty archive, no values.yaml member
    dep = {"name": "openzaak", "version": "1.14.2"}
    assert libchart.subchart_values(tmp_path, dep) is None


# --- subchart_app_version ---

def test_subchart_app_version_reads_vendored_chart_yaml(libchart, tmp_path):
    make_tgz(tmp_path / "charts", "openbao", "0.28.4", {"server": {"image": {"tag": ""}}},
             chart_yaml={"apiVersion": "v2", "version": "0.28.4", "appVersion": "v2.5.5"})
    dep = {"name": "openbao", "version": "0.28.4"}
    assert libchart.subchart_app_version(tmp_path, dep) == "v2.5.5"


def test_subchart_app_version_missing_tgz_returns_none(libchart, tmp_path):
    dep = {"name": "openbao", "version": "0.28.4"}
    assert libchart.subchart_app_version(tmp_path, dep) is None


def test_subchart_app_version_missing_member_returns_none(libchart, tmp_path):
    make_tgz(tmp_path / "charts", "openbao", "0.28.4", {"server": {"image": {"tag": ""}}})  # no chart_yaml
    dep = {"name": "openbao", "version": "0.28.4"}
    assert libchart.subchart_app_version(tmp_path, dep) is None


def test_subchart_app_version_no_app_version_field_returns_none(libchart, tmp_path):
    make_tgz(tmp_path / "charts", "openbao", "0.28.4", {"server": {"image": {"tag": ""}}},
             chart_yaml={"apiVersion": "v2", "version": "0.28.4"})
    dep = {"name": "openbao", "version": "0.28.4"}
    assert libchart.subchart_app_version(tmp_path, dep) is None


# --- nested_subchart_raw_text / nested_subchart_documented_image_repository ---

def test_nested_subchart_raw_text_reads_nested_file(libchart, tmp_path):
    dep = {"name": "eck-stack", "version": "0.20.0"}
    make_tgz(tmp_path / "charts", "eck-stack", "0.20.0", {}, raw_files={
        "eck-stack/charts/eck-elasticsearch/values.yaml": "# hello\n",
    })
    assert libchart.nested_subchart_raw_text(tmp_path, dep, "eck-elasticsearch", "values.yaml") == "# hello\n"


def test_nested_subchart_raw_text_missing_tgz_returns_none(libchart, tmp_path):
    dep = {"name": "eck-stack", "version": "0.20.0"}
    assert libchart.nested_subchart_raw_text(tmp_path, dep, "eck-elasticsearch", "values.yaml") is None


def test_nested_subchart_raw_text_missing_nested_chart_returns_none(libchart, tmp_path):
    """The outer .tgz IS vendored, but has no charts/eck-kibana/ inside
    it at all (e.g. a stale/mismatched registry entry) — no crash."""
    dep = {"name": "eck-stack", "version": "0.20.0"}
    make_tgz(tmp_path / "charts", "eck-stack", "0.20.0", {}, raw_files={
        "eck-stack/charts/eck-elasticsearch/values.yaml": "# hello\n",
    })
    assert libchart.nested_subchart_raw_text(tmp_path, dep, "eck-kibana", "values.yaml") is None


def test_nested_subchart_documented_image_repository_extracts_first_example(libchart, tmp_path):
    """The FIRST "# image: <repo>[:<tag>]" comment wins — every ECK-
    family sub-subchart lists the plain "<repo>:<version>" form first,
    then a digest-suffixed variant, then a bare "@sha256:..." form; only
    the plain repository (no tag, no digest) is wanted."""
    dep = {"name": "eck-stack", "version": "0.20.0"}
    make_tgz(tmp_path / "charts", "eck-stack", "0.20.0", {}, raw_files={
        "eck-stack/charts/eck-kibana/values.yaml": (
            "# Kibana Docker image to deploy.\n#\n"
            "# image: docker.elastic.co/kibana/kibana:9.5.0\n"
            "# image: docker.elastic.co/kibana/kibana:9.5.0@sha256:<digest>\n"
            "# image: docker.elastic.co/kibana/kibana@sha256:<digest>\n"
        ),
    })
    assert (libchart.nested_subchart_documented_image_repository(tmp_path, dep, "eck-kibana")
            == "docker.elastic.co/kibana/kibana")


def test_nested_subchart_documented_image_repository_no_comment_returns_none(libchart, tmp_path):
    dep = {"name": "eck-stack", "version": "0.20.0"}
    make_tgz(tmp_path / "charts", "eck-stack", "0.20.0", {}, raw_files={
        "eck-stack/charts/eck-kibana/values.yaml": "enabled: true\n",
    })
    assert libchart.nested_subchart_documented_image_repository(tmp_path, dep, "eck-kibana") is None


# --- resolve_chart_values ---

def test_resolve_chart_values_prefers_vendored_over_pulling(libchart, tmp_path, monkeypatch):
    def raise_if_pulled(dep, version, dest):
        raise AssertionError("should not pull — already vendored at this exact version")

    monkeypatch.setattr(libchart, "pull_chart", raise_if_pulled)
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {"repository": "openzaak/open-zaak"}})
    dep = {"name": "openzaak", "version": "1.14.2"}

    values, source, error = libchart.resolve_chart_values(tmp_path, dep, "1.14.2")

    assert values == {"image": {"repository": "openzaak/open-zaak"}}
    assert source == "vendored"
    assert error is None


def test_resolve_chart_values_falls_back_to_pull_when_not_vendored(libchart, tmp_path, monkeypatch):
    def fake_pull_chart(dep, version, dest):
        chart_dir = dest / dep["name"]
        chart_dir.mkdir(parents=True)
        (chart_dir / "values.yaml").write_text(
            yaml.safe_dump({"image": {"repository": "openzaak/open-zaak"}}), encoding="utf-8"
        )
        return True, ""

    monkeypatch.setattr(libchart, "pull_chart", fake_pull_chart)
    dep = {"name": "openzaak", "version": "1.15.0"}  # not the vendored 1.14.2 from the test above

    values, source, error = libchart.resolve_chart_values(tmp_path, dep, "1.15.0")

    assert values == {"image": {"repository": "openzaak/open-zaak"}}
    assert source == "pulled"
    assert error is None


def test_resolve_chart_values_pull_failure_returns_error(libchart, tmp_path, monkeypatch):
    monkeypatch.setattr(libchart, "pull_chart", lambda dep, version, dest: (False, "version not found"))
    dep = {"name": "openzaak", "version": "9.9.9"}

    values, source, error = libchart.resolve_chart_values(tmp_path, dep, "9.9.9")

    assert values is None
    assert source is None
    assert error == "version not found"


def test_resolve_chart_values_no_pull_allowed_and_not_vendored_returns_error(libchart, tmp_path, monkeypatch):
    def raise_if_pulled(dep, version, dest):
        raise AssertionError("should not pull — allow_pull is False")

    monkeypatch.setattr(libchart, "pull_chart", raise_if_pulled)
    dep = {"name": "openzaak", "version": "1.15.0"}

    values, source, error = libchart.resolve_chart_values(tmp_path, dep, "1.15.0", allow_pull=False)

    assert values is None
    assert source is None
    assert "not vendored" in error


# --- primary_image_repositories ---

def test_primary_image_repositories_own_override_wins(libchart, tmp_path, monkeypatch):
    def raise_if_pulled(dep, version, dest):
        raise AssertionError("own override present — should never consult the subchart")

    monkeypatch.setattr(libchart, "pull_chart", raise_if_pulled)
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    own_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}}

    repos, error = libchart.primary_image_repositories(tmp_path, dep, own_values, allow_pull=False)

    assert repos == {"image": "ghcr.io/infonl/zaakafhandelcomponent"}
    assert error is None


def test_primary_image_repositories_falls_back_to_subchart_default(libchart, tmp_path):
    """openzaak-style: no "repository:" override of its own at all — only
    a "tag:" — resolved from the vendored subchart's own default instead,
    with no network access (allow_pull=False)."""
    make_tgz(tmp_path / "charts", "openzaak", "4.9.1", {"image": {"repository": "openzaak/open-zaak"}})
    dep = {"name": "openzaak", "alias": "", "version": "4.9.1"}
    own_values = {"openzaak": {"image": {"tag": "3.28.0@sha256:aaaa"}}}

    repos, error = libchart.primary_image_repositories(tmp_path, dep, own_values, allow_pull=False)

    assert repos == {"image": "openzaak/open-zaak"}
    assert error is None


def test_primary_image_repositories_multi_path_component_reads_subchart_once(libchart, tmp_path, monkeypatch):
    """zgw-office-addin-style: two distinct primary paths, neither with
    its own override — both resolved from the SAME vendored subchart
    values.yaml, read only once and reused across both paths."""
    make_tgz(tmp_path / "charts", "zgw-office-addin", "0.0.92", {
        "frontend": {"image": {"repository": "ghcr.io/infonl/zgw-office-addin-frontend"}},
        "backend": {"image": {"repository": "ghcr.io/infonl/zgw-office-addin-backend"}},
    })
    dep = {"name": "zgw-office-addin", "alias": "", "version": "0.0.92"}
    calls = []
    real_subchart_values = libchart.subchart_values

    def spy(chart_dir, dep_arg, version=None):
        calls.append(dep_arg["name"])
        return real_subchart_values(chart_dir, dep_arg, version)

    monkeypatch.setattr(libchart, "subchart_values", spy)

    repos, error = libchart.primary_image_repositories(tmp_path, dep, {}, allow_pull=False)

    assert repos == {
        "frontend.image": "ghcr.io/infonl/zgw-office-addin-frontend",
        "backend.image": "ghcr.io/infonl/zgw-office-addin-backend",
    }
    assert error is None
    assert calls == ["zgw-office-addin"]  # fetched once, reused for the second path


def test_primary_image_repositories_unresolvable_without_vendored_chart(libchart, tmp_path):
    dep = {"name": "openzaak", "alias": "", "version": "4.9.1"}
    own_values = {"openzaak": {"image": {"tag": "3.28.0@sha256:aaaa"}}}

    repos, error = libchart.primary_image_repositories(tmp_path, dep, own_values, allow_pull=False)

    assert repos == {"image": None}
    assert error is not None


def test_primary_image_repositories_chart_dir_none_is_safe_when_unneeded(libchart):
    """A caller with no vendored-charts location at all (e.g. a pure
    in-memory test) never crashes, as long as no path actually needs the
    subchart fallback — see verify-release-table-with-podiumd's own
    compare(), whose chart_dir defaults to None."""
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    own_values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}}

    repos, error = libchart.primary_image_repositories(None, dep, own_values, allow_pull=False)

    assert repos == {"image": "ghcr.io/infonl/zaakafhandelcomponent"}
    assert error is None


def test_primary_image_repositories_chart_dir_none_and_needed_returns_error(libchart):
    dep = {"name": "openzaak", "alias": "", "version": "4.9.1"}
    own_values = {"openzaak": {"image": {"tag": "3.28.0@sha256:aaaa"}}}

    repos, error = libchart.primary_image_repositories(None, dep, own_values, allow_pull=False)

    assert repos == {"image": None}
    assert error is not None


# --- strip_registry_host ---

@pytest.mark.parametrize("url,expected", [
    ("quay.io/keycloak/keycloak", "keycloak/keycloak"),
    ("docker.io/maykinmedia/open-inwoner", "maykinmedia/open-inwoner"),
    ("ghcr.io/infonl/zaakafhandelcomponent", "infonl/zaakafhandelcomponent"),
    ("docker.io/library/redis", "library/redis"),
    ("localhost:5000/foo/bar", "foo/bar"),
    ("acrprodmgmt.azurecr.io/infonl/zac:5.4.4", "infonl/zac:5.4.4"),
    ("infonl/zaakafhandelcomponent", "infonl/zaakafhandelcomponent"),  # already stripped
    ("ghcr.io/infonl/zaakafhandelcomponent@sha256:aaaa", "infonl/zaakafhandelcomponent"),
])
def test_strip_registry_host(libchart, url, expected):
    assert libchart.strip_registry_host(url) == expected


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
    make_tgz(tmp_path / "charts", "zaakafhandelcomponent", "1.0.297", {
        "image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"},
        "opa": {"image": {"repository": "openpolicyagent/opa"}},
        "office_converter": {"image": {"repository": "gotenberg/gotenberg"}},
    })
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    own_values = {"zac": {
        "image": {"tag": "5.4.4@sha256:aaaa"},
        "opa": {"image": {"tag": "1.19.1-static@sha256:bbbb"}},
        "office_converter": {"image": {"tag": "8.36.0@sha256:cccc"}},
    }}
    paths = [("zac", "image"), ("zac", "opa", "image"), ("zac", "office_converter", "image")]

    mapping = libchart.repository_path_map(tmp_path, [dep], own_values, paths, allow_pull=False)

    assert mapping == {
        "infonl/zaakafhandelcomponent": ("zac", "image"),
        "openpolicyagent/opa": ("zac", "opa", "image"),
        "gotenberg/gotenberg": ("zac", "office_converter", "image"),
    }


def test_repository_path_map_subchart_values_reused_across_paths(libchart, tmp_path, monkeypatch):
    """The vendored subchart's own values.yaml is read at most once for
    a given dependency, however many of its own paths need it —
    same caching guarantee as primary_image_repositories."""
    make_tgz(tmp_path / "charts", "zaakafhandelcomponent", "1.0.297", {
        "image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"},
        "opa": {"image": {"repository": "openpolicyagent/opa"}},
    })
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    own_values = {"zac": {
        "image": {"tag": "5.4.4@sha256:aaaa"},
        "opa": {"image": {"tag": "1.19.1-static@sha256:bbbb"}},
    }}
    paths = [("zac", "image"), ("zac", "opa", "image")]
    calls = []
    real_subchart_values = libchart.subchart_values

    def spy(chart_dir, dep_arg, version=None):
        calls.append(dep_arg["name"])
        return real_subchart_values(chart_dir, dep_arg, version)

    monkeypatch.setattr(libchart, "subchart_values", spy)

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


# --- repo_group_representative ---

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
        "keycloak-operator", "operator", "config", "keycloakImage")


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
        "keycloak-operator", "operator", "config", "keycloakImage")


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
        "keycloak-operator": {"operator": {"config": {
            "keycloakImage": {"repository": "quay.io/keycloak/keycloak", "tag": "26.7.3"}}}},
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

    assert groups == {"nginxinc/nginx-unprivileged": [
        ("openzaak", "nginx", "image"), ("openformulieren", "nginx", "image")]}


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
    values = {"redis-operator": {"redisOperator": {
        "imageName": "quay.io/opstree/redis-operator", "imageTag": "v0.26.0@sha256:aaaa"}}}
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
    make_tgz(tmp_path / "charts", "eck-stack", "0.20.0", {}, raw_files={
        "eck-stack/charts/eck-elasticsearch/values.yaml": (
            "# Elasticsearch Docker image to deploy.\n#\n"
            "# image: docker.elastic.co/elasticsearch/elasticsearch:9.5.0\n"
            "# image: docker.elastic.co/elasticsearch/elasticsearch:9.5.0@sha256:<digest>\n"
        ),
    })
    values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}}}
    paths = [("kiss-eck", "eck-elasticsearch", "version")]

    groups = libchart.paths_by_repository(tmp_path, [dep], values, paths, allow_pull=False)

    assert groups == {"elasticsearch/elasticsearch": [("kiss-eck", "eck-elasticsearch", "version")]}


# --- canonical_sidecar_row_names ---

def test_canonical_sidecar_row_names_dependency_sidecar(libchart, tmp_path):
    dep = {"name": "redis-operator", "alias": "", "version": "0.26.0"}
    values = {"redis-operator": {"redis-ha": {"image": {"repository": "quay.io/opstree/redis"}}}}
    paths = [("redis-operator", "redis-ha", "image")]

    names = libchart.canonical_sidecar_row_names(tmp_path, [dep], values, paths, allow_pull=False)

    assert names == {"redis-operator - redis": ("redis-operator", "redis-ha", "image")}


def test_canonical_sidecar_row_names_excludes_dependencys_own_primary_image(libchart, tmp_path):
    """The dependency's own registered primary image (image_paths_for) is
    NOT a sidecar — match_dependency already covers it by the
    dependency's plain name/alias, so it must not show up here too."""
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}}
    paths = [("zac", "image")]

    names = libchart.canonical_sidecar_row_names(tmp_path, [dep], values, paths, allow_pull=False)

    assert names == {}


def test_canonical_sidecar_row_names_excludes_self_referential_basename(libchart, tmp_path):
    """A nested image whose OWN repository basename happens to equal the
    parent dependency's own values key (real case: keycloak-operator.
    operator.image, the operator's own container — NOT registered in
    COMPONENT_IMAGE_PATHS, unlike operator.config.keycloakImage) must
    never produce a "<key> - <key>" canonical name — that's structurally
    indistinguishable from "this IS the dependency's own row"
    (match_dependency already covers that case by the bare dependency
    name), and auto-documenting it under the sidecar/image template
    would be wrong regardless of what it's actually for."""
    dep = {"name": "keycloak-operator", "alias": "", "version": "1.12.1"}
    values = {"keycloak-operator": {"operator": {
        "image": {"repository": "quay.io/keycloak/keycloak-operator"}}}}
    paths = [("keycloak-operator", "operator", "image")]

    names = libchart.canonical_sidecar_row_names(tmp_path, [dep], values, paths, allow_pull=False)

    assert names == {}


def test_canonical_sidecar_row_names_global_shared_image(libchart, tmp_path):
    """A "global"-rooted image has no single owning dependency at all —
    the canonical name is bare "<basename>" (update-image-version's
    MULTIPLE_KEY convention), never "<values_key> - <basename>"."""
    values = {"global": {"images": {"nginx": {"image": {"repository": "docker.io/nginxinc/nginx-unprivileged"}}}}}
    paths = [("global", "images", "nginx", "image")]

    names = libchart.canonical_sidecar_row_names(tmp_path, [], values, paths, allow_pull=False)

    assert names == {"nginx-unprivileged": ("global", "images", "nginx", "image")}


def test_canonical_sidecar_row_names_multiple_sidecars_stay_distinct(libchart, tmp_path):
    values = {"redis-operator": {
        "redis-ha": {"image": {"repository": "quay.io/opstree/redis"}},
        "redis-exporter": {"image": {"repository": "quay.io/opstree/redis-exporter"}},
    }}
    dep = {"name": "redis-operator", "alias": "", "version": "0.26.0"}
    paths = [("redis-operator", "redis-ha", "image"), ("redis-operator", "redis-exporter", "image")]

    names = libchart.canonical_sidecar_row_names(tmp_path, [dep], values, paths, allow_pull=False)

    assert names == {
        "redis-operator - redis": ("redis-operator", "redis-ha", "image"),
        "redis-operator - redis-exporter": ("redis-operator", "redis-exporter", "image"),
    }


# --- subchart_template_text ---

def test_subchart_template_text_concatenates_all_template_files(libchart, tmp_path):
    make_tgz(tmp_path / "charts", "pabc", "1.1.1", {"image": {"repository": "pabc/pabc-api"}},
             templates={
                 "deployment.yaml": "image: {{ .Values.image.repository }}\n",
                 "service.yaml": "kind: Service\n",
             })
    dep = {"name": "pabc", "version": "1.1.1"}
    text = libchart.subchart_template_text(tmp_path, dep)
    assert "{{ .Values.image.repository }}" in text
    assert "kind: Service" in text


def test_subchart_template_text_missing_tgz_returns_none(libchart, tmp_path):
    dep = {"name": "pabc", "version": "1.1.1"}
    assert libchart.subchart_template_text(tmp_path, dep) is None


def test_subchart_template_text_no_templates_dir_returns_none(libchart, tmp_path):
    """A .tgz with only values.yaml (no templates/ at all — the shape
    make_tgz produces when `templates` is omitted) is "can't tell", not
    an empty-but-valid haystack — callers must be able to distinguish the
    two, so this returns None rather than ""."""
    make_tgz(tmp_path / "charts", "pabc", "1.1.1", {"image": {"repository": "pabc/pabc-api"}})
    dep = {"name": "pabc", "version": "1.1.1"}
    assert libchart.subchart_template_text(tmp_path, dep) is None


# --- subchart_default_repository ---

def test_subchart_default_repository_resolves_via_alias(libchart, tmp_path):
    """openformulieren is a values.yaml/Chart.yaml alias for the openforms
    subchart — the .tgz and its internal values.yaml are keyed by the
    real chart name, not the alias."""
    make_tgz(tmp_path / "charts", "openforms", "1.12.0", {"image": {"repository": "openformulieren/open-forms"}})
    deps = [{"name": "openforms", "alias": "openformulieren", "version": "1.12.0"}]
    lines = [
        "openformulieren:",
        "  image:",
        '    tag: "3.4.10@sha256:aaaa"',
    ]
    assert libchart.subchart_default_repository(tmp_path, lines, 3, deps) == "openformulieren/open-forms"


def test_subchart_default_repository_nested_subpath(libchart, tmp_path):
    make_tgz(tmp_path / "charts", "zgw-office-addin", "0.9.352", {
        "frontend": {"image": {"repository": "example/frontend"}},
    })
    deps = [{"name": "zgw-office-addin", "version": "0.9.352"}]
    lines = [
        "zgw-office-addin:",
        "  frontend:",
        "    image:",
        '      tag: "v0.9.352@sha256:aaaa"',
    ]
    assert libchart.subchart_default_repository(tmp_path, lines, 4, deps) == "example/frontend"


def test_subchart_default_repository_unknown_component_returns_none(libchart, tmp_path):
    lines = ["a:", "  image:", '    tag: "1.0.0@sha256:aaaa"']
    assert libchart.subchart_default_repository(tmp_path, lines, 3, []) is None


def test_subchart_default_repository_too_shallow_path_returns_none(libchart, tmp_path):
    lines = ['tag: "1.0.0@sha256:aaaa"']
    assert libchart.subchart_default_repository(tmp_path, lines, 1, [{"name": "a"}]) is None


def test_subchart_default_repository_subchart_has_no_repository_at_path(libchart, tmp_path):
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {}})
    deps = [{"name": "openzaak", "version": "1.14.2"}]
    lines = ["openzaak:", "  image:", '    tag: "1.27.4@sha256:aaaa"']
    assert libchart.subchart_default_repository(tmp_path, lines, 3, deps) is None


def test_subchart_default_repository_caches_across_calls(libchart, tmp_path, monkeypatch):
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {
        "image": {"repository": "openzaak/open-zaak"},
        "worker": {"image": {"repository": "openzaak/open-zaak-worker"}},
    })
    deps = [{"name": "openzaak", "version": "1.14.2"}]
    lines = [
        "openzaak:",
        "  image:",
        '    tag: "1.27.4@sha256:aaaa"',
        "  worker:",
        "    image:",
        '      tag: "1.27.4@sha256:bbbb"',
    ]
    calls = []
    real_subchart_values = libchart.subchart_values

    def spy(chart_dir, dep):
        calls.append(dep["name"])
        return real_subchart_values(chart_dir, dep)

    monkeypatch.setattr(libchart, "subchart_values", spy)
    cache = {}
    assert libchart.subchart_default_repository(tmp_path, lines, 3, deps, cache) == "openzaak/open-zaak"
    assert libchart.subchart_default_repository(tmp_path, lines, 6, deps, cache) == "openzaak/open-zaak-worker"
    assert calls == ["openzaak"]  # second lookup served from cache, .tgz read only once
