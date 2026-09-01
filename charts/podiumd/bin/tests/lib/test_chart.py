"""lib.chart — get_path, replace_scalar_value, chart_version, SEMVER_RE,
find_dependency, chart_ref, local_chart_dir, pull_chart, pulled_chart_dir,
pull_chart_values, find_images, version_of, image_paths_for, dotted_key_path,
subchart_values, subchart_default_repository. `helm pull` is mocked via
lib.procutil.run, so no `helm` binary or network access needed."""
import io
import tarfile
from pathlib import Path

import pytest
import yaml


def make_tgz(charts_dir, name, version, values, templates=None):
    """A minimal vendored <name>-<version>.tgz containing <name>/values.yaml
    and, if `templates` is given (a {filename: text} dict), <name>/templates/
    <filename> for each entry — enough to exercise subchart_values/
    subchart_default_repository/subchart_template_text without a real
    `helm pull`."""
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


# --- release_baseline ---
# shared by verify-podiumd's release-baseline check and its Docs
# consistency default, create-doc-version's and fix-doc-consistency's
# default argument, and show-component-baseline-version's default
# argument.

def test_release_baseline_reads_and_strips_the_file(libchart, tmp_path):
    (tmp_path / "release-baseline").write_text("4.8.4\n", encoding="utf-8")
    assert libchart.release_baseline(tmp_path) == "4.8.4"


def test_release_baseline_none_when_file_missing(libchart, tmp_path):
    assert libchart.release_baseline(tmp_path) is None


# --- upgrade_docs_baseline / release_table_baseline ---
# release-baseline.yaml, the successor to release_baseline()/release-
# baseline above — see lib.chart's RELEASE_BASELINES_FILE_NAME/
# _release_baselines for why podiumd now needs two baselines instead of
# one (incremental _UPGRADE_PATHS/images-manifest vs. cumulative
# release-table.csv).

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


def test_release_baselines_independent_of_old_plain_text_file(libchart, tmp_path):
    """The two files/mechanisms coexist and never read each other's
    data — the new file being absent must not fall back to the old
    plain-text release-baseline file, and vice versa."""
    (tmp_path / "release-baseline").write_text("4.8.4\n", encoding="utf-8")
    assert libchart.upgrade_docs_baseline(tmp_path) is None
    assert libchart.release_table_baseline(tmp_path) is None

    (tmp_path / "release-baseline.yaml").write_text("upgrade_docs: '4.9.0'\n", encoding="utf-8")
    assert libchart.release_baseline(tmp_path) == "4.8.4"


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

def test_verify_chart_version_found_returns_values(libchart, monkeypatch, capsys):
    def fake_pull_chart(dep, version, dest):
        chart_dir = dest / dep["name"]
        chart_dir.mkdir(parents=True)
        (chart_dir / "values.yaml").write_text(
            yaml.safe_dump({"image": {"repository": "infonl/zac"}}), encoding="utf-8"
        )
        return True, ""

    monkeypatch.setattr(libchart, "pull_chart", fake_pull_chart)
    dep = {"name": "zaakafhandelcomponent", "repository": "@zac"}

    values = libchart.verify_chart_version(dep, "1.0.297")

    assert values == {"image": {"repository": "infonl/zac"}}
    out = capsys.readouterr().out
    assert "[FOUND  ] zaakafhandelcomponent 1.0.297" in out


def test_verify_chart_version_missing_exits_one(libchart, monkeypatch, capsys):
    monkeypatch.setattr(libchart, "pull_chart", lambda dep, version, dest: (False, "version not found"))
    dep = {"name": "zaakafhandelcomponent", "repository": "@zac"}

    with pytest.raises(SystemExit) as exc_info:
        libchart.verify_chart_version(dep, "9.9.9")

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
