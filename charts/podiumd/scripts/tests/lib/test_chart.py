"""lib.chart — get_path, find_dependency, chart_ref, pull_chart,
pulled_chart_dir, pull_chart_values, find_images, version_of,
image_paths_for, dotted_key_path, subchart_values,
subchart_default_repository. `helm pull` is mocked via lib.procutil.run,
so no `helm` binary or network access needed."""
import io
import tarfile

import pytest
import yaml


def make_tgz(charts_dir, name, version, values):
    """A minimal vendored <name>-<version>.tgz containing just
    <name>/values.yaml — enough to exercise subchart_values/
    subchart_default_repository without a real `helm pull`."""
    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    data = yaml.safe_dump(values).encode("utf-8")
    with tarfile.open(tgz_path, "w:gz") as tar:
        info = tarfile.TarInfo(name=f"{name}/values.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return tgz_path


# --- get_path ---

def test_get_path_nested(libchart):
    assert libchart.get_path({"a": {"b": {"c": 1}}}, "a.b.c") == 1


def test_get_path_missing_returns_none(libchart):
    assert libchart.get_path({"a": {}}, "a.b.c") is None


def test_get_path_non_dict_intermediate_returns_none(libchart):
    assert libchart.get_path({"a": "scalar"}, "a.b") is None


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
