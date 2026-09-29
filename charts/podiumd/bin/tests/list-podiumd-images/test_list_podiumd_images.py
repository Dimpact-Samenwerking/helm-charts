"""list-podiumd-images, offline: load_chart reads locally vendored .tgz
files; the few `helm pull` fallback tests mock subprocess.run."""

import subprocess
import tarfile

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


def write_pulled_chart(dest, name, chart_yaml, values_yaml):
    """Mimic `helm pull --untar` creating dest/<name>/, which load_chart expects."""
    chart_dir = dest / name
    chart_dir.mkdir()
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({"apiVersion": "v2", **chart_yaml}))
    (chart_dir / "values.yaml").write_text(yaml.safe_dump(values_yaml))


def make_vendored_tgz(vendored_dir, tmp_path: Path, name, version, chart_yaml, values_yaml, raw_files=None):
    """`raw_files` ({chart-relative path: text}) are written verbatim, for
    content yaml.safe_dump can't produce, such as a nested sub-subchart's
    commented-out "# image: ..." documentation."""
    staging = tmp_path / f"stage-{name}-{version}"
    chart_dir = staging / name
    chart_dir.mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({"apiVersion": "v2", **chart_yaml}))
    (chart_dir / "values.yaml").write_text(yaml.safe_dump(values_yaml))
    for rel_path, text in (raw_files or {}).items():
        file_path = chart_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(text)
    tgz_path = vendored_dir / f"{name}-{version}.tgz"
    with tarfile.open(tgz_path, "w:gz") as tf:
        tf.add(chart_dir, arcname=name)
    return tgz_path


# --- deep_merge ---


def test_deep_merge_recurses_into_nested_dicts(lpi):
    base = {"a": {"b": 1, "c": 2}}
    override = {"a": {"b": 9}}
    assert lpi.deep_merge(base, override) == {"a": {"b": 9, "c": 2}}


def test_deep_merge_none_override_keeps_base(lpi):
    assert lpi.deep_merge({"a": 1}, {"a": None}) == {"a": 1}


def test_deep_merge_non_dict_override_replaces_base(lpi):
    assert lpi.deep_merge({"a": {"b": 1}}, {"a": "scalar"}) == {"a": "scalar"}


def test_deep_merge_adds_new_keys(lpi):
    assert lpi.deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


# --- version_of / find_images ---


def test_version_of_strips_digest(lpi):
    assert lpi.version_of("5.4.3@sha256:abc") == "5.4.3"


def test_find_images_finds_nested_and_list_images(lpi):
    values = {
        "zac": {"image": {"repository": "r", "tag": "1.0"}},
        "list": [{"image": {"repository": "r2", "tag": "2.0"}}],
    }
    images = lpi.find_images(values)
    assert ("zac.image", "r", "1.0") in images
    assert ("list[0].image", "r2", "2.0") in images


def test_find_images_root_path(lpi):
    assert lpi.find_images({"repository": "r", "tag": "1.0"}) == [("(root)", "r", "1.0")]


def test_find_images_skips_missing_or_empty_tag(lpi):
    assert lpi.find_images({"image": {"repository": "r", "tag": None}}) == []
    assert lpi.find_images({"image": {"repository": "r"}}) == []


def test_find_images_returns_a_numeric_tag_as_text(lpi):
    # An unquoted "tag: 1.5" parses as a float; version_of() and the
    # printers need the text Helm renders for it.
    assert lpi.find_images({"image": {"repository": "r", "tag": 1.5}}) == [("image", "r", "1.5")]


# --- resolution_note ---


def test_resolution_note_resolvable_pair_returns_none(lpi):
    lines = [
        "pabc:",
        "  image:",
        "    repository: ghcr.io/x/pabc-api",
        f'    tag: "1.1.1@sha256:{"a" * 64}"',
    ]
    assert lpi.resolution_note(lines, "pabc", "pabc-api") is None


def test_resolution_note_shared_global_image_points_to_multiple(lpi):
    """A basename pinned only under global.images points at the key that
    does resolve (MULTIPLE) instead of being a dead end."""
    lines = [
        "global:",
        "  images:",
        "    curl:",
        "      repository: curlimages/curl",
        f'      tag: "8.21.0@sha256:{"a" * 64}"',
    ]
    assert lpi.resolution_note(lines, "zac", "curl") == "use MULTIPLE curl"


def test_resolution_note_unresolvable_pair_reports_generic_reason(lpi):
    assert lpi.resolution_note([], "openbeheer", "open-beheer") == "unresolvable"


# --- print_image_lines ---


def test_print_image_lines_leads_with_key_basename_version_and_path(lpi, capsys: pytest.CaptureFixture[str]):
    lines = [
        "pabc:",
        "  image:",
        "    repository: ghcr.io/x/pabc-api",
        f'    tag: "1.1.1@sha256:{"a" * 64}"',
    ]
    lpi.print_image_lines([("pabc", "image", "ghcr.io/x/pabc-api", f"1.1.1@sha256:{'a' * 64}", False)], lines)
    first_line, detail_line = capsys.readouterr().out.splitlines()
    assert "pabc  pabc-api  1.1.1  (path: image)" in first_line
    assert "—" not in first_line  # resolvable -- no trailing note
    assert detail_line.strip() == f"ghcr.io/x/pabc-api:1.1.1@sha256:{'a' * 64}"


def test_print_image_lines_appends_note_when_not_resolvable(lpi, capsys: pytest.CaptureFixture[str]):
    lpi.print_image_lines([("openbeheer", "image", "maykinmedia/open-beheer", "0.9.0", False)], [])
    out = capsys.readouterr().out
    assert "unresolvable" in out


def test_print_image_lines_appends_disabled_hint_for_a_never_rendered_row(lpi, capsys: pytest.CaptureFixture[str]):
    """A row whose chart-tree path never rendered (e.g. a Maykin chart's
    bundled redis disabled via "tags: {redis: false}") is labelled "disabled"
    rather than dropped; with an unresolvable note both show, disabled first."""
    lpi.print_image_lines([("openzaak", "redis.image", "redis", "8.0", True)], [])
    first_line, _detail_line = capsys.readouterr().out.splitlines()
    assert "disabled; unresolvable" in first_line


def test_print_image_lines_puts_note_on_first_line_not_the_detail_line(lpi, capsys: pytest.CaptureFixture[str]):
    """The note decides whether <key> <basename> is usable, so it belongs on
    the first line, not the repo:tag line."""
    lines = [
        "global:",
        "  images:",
        "    curl:",
        "      repository: curlimages/curl",
        f'      tag: "8.21.0@sha256:{"a" * 64}"',
    ]
    lpi.print_image_lines([("zac", "global.curlImage", "curlimages/curl", f"8.21.0@sha256:{'a' * 64}", False)], lines)
    first_line, detail_line = capsys.readouterr().out.splitlines()
    assert "use MULTIPLE curl" in first_line
    assert "—" not in detail_line


# --- component_version_rows ---
# Registered bare version fields (COMPONENT_VERSION_PATHS) have shapes
# find_images' "{repository, tag}" match can't see: redis-operator's split
# imageName:/imageTag: and eck-stack's CRD "version:" fields.


def test_component_version_rows_resolves_redis_operator_split_image_fields(lpi):
    """redis-operator's controller image uses split imageName:/imageTag: fields."""
    dep = {"name": "redis-operator", "version": "0.26.1"}
    digest = "a" * 64
    merged = {
        "redisOperator": {
            "imageName": "quay.io/opstree/redis-operator",
            "imageTag": f"v0.26.0@sha256:{digest}",
        }
    }
    root_values = {"redis-operator": {"redisOperator": {"imageName": "quay.io/opstree/redis-operator"}}}
    ctx = lpi.ChartContext(deps=[dep], root_values=root_values, rendered_paths={"podiumd/charts/redis-operator"})

    rows = lpi.component_version_rows(dep, "redis-operator", merged, ctx)

    assert rows == [
        (
            "redis-operator",
            "redisOperator.imageTag",
            "quay.io/opstree/redis-operator",
            f"v0.26.0@sha256:{digest}",
            False,
        )
    ]


def test_component_version_rows_uses_merged_tree_not_just_podiumd_overrides(lpi):
    """Unlike doc generation, this tool shows the effective image set, so a
    tag only present in the chart default must appear."""
    dep = {"name": "redis-operator", "version": "0.26.1"}
    digest = "b" * 64
    merged = {
        "redisOperator": {
            "imageName": "quay.io/opstree/redis-operator",
            "imageTag": f"v0.25.0@sha256:{digest}",  # chart default, no podiumd override at all
        }
    }
    root_values = {"redis-operator": {"redisOperator": {"imageName": "quay.io/opstree/redis-operator"}}}
    ctx = lpi.ChartContext(deps=[dep], root_values=root_values, rendered_paths={"podiumd/charts/redis-operator"})

    rows = lpi.component_version_rows(dep, "redis-operator", merged, ctx)

    assert rows == [
        (
            "redis-operator",
            "redisOperator.imageTag",
            "quay.io/opstree/redis-operator",
            f"v0.25.0@sha256:{digest}",
            False,
        )
    ]


def test_component_version_rows_resolves_eck_stack_nested_subchart_images(lpi, tmp_path: Path):
    """eck-stack's CRD "version:" fields have no repository in podiumd's
    values.yaml; it's only documented in the nested sub-subchart's values.yaml."""
    dep = {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}
    make_vendored_tgz(
        lpi.VENDORED_DIR,
        tmp_path,
        "eck-stack",
        "0.20.0",
        {"name": "eck-stack", "version": "0.20.0"},
        {},
        raw_files={
            "charts/eck-elasticsearch/values.yaml": "# image: docker.elastic.co/elasticsearch/elasticsearch:9.5.0\n",
            "charts/eck-kibana/values.yaml": "# image: docker.elastic.co/kibana/kibana:9.5.0\n",
            "charts/eck-enterprise-search/values.yaml": (
                "# image: docker.elastic.co/enterprise-search/enterprise-search:9.5.0\n"
            ),
        },
    )
    merged = {
        "eck-elasticsearch": {"version": "8.19.19"},
        "eck-kibana": {"version": "8.19.19"},
        "eck-enterprise-search": {"version": "8.19.19"},
    }

    # chart-tree path is keyed by the dep's alias, not its chart name.
    ctx = lpi.ChartContext(deps=[dep], root_values={}, rendered_paths={"podiumd/charts/kiss-eck"})
    rows = lpi.component_version_rows(dep, "kiss-eck", merged, ctx)

    assert sorted(rows) == sorted(
        [
            (
                "kiss-eck",
                "eck-elasticsearch.version",
                "docker.elastic.co/elasticsearch/elasticsearch",
                "8.19.19",
                False,
            ),
            (
                "kiss-eck",
                "eck-enterprise-search.version",
                "docker.elastic.co/enterprise-search/enterprise-search",
                "8.19.19",
                False,
            ),
            ("kiss-eck", "eck-kibana.version", "docker.elastic.co/kibana/kibana", "8.19.19", False),
        ]
    )


def test_component_version_rows_blank_tag_is_skipped(lpi):
    dep = {"name": "redis-operator", "version": "0.26.1"}
    merged = {"redisOperator": {"imageName": "quay.io/opstree/redis-operator", "imageTag": ""}}
    root_values = {"redis-operator": {"redisOperator": {"imageName": "quay.io/opstree/redis-operator"}}}
    ctx = lpi.ChartContext(deps=[dep], root_values=root_values, rendered_paths={"podiumd/charts/redis-operator"})
    assert lpi.component_version_rows(dep, "redis-operator", merged, ctx) == []


def test_component_version_rows_unresolvable_repository_is_skipped(lpi):
    """A version field with no resolvable repository is skipped, never given
    a fabricated or missing repository."""
    dep = {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}
    merged = {"eck-elasticsearch": {"version": "8.19.19"}}
    ctx = lpi.ChartContext(deps=[dep], root_values={}, rendered_paths={"podiumd/charts/kiss-eck"})
    assert lpi.component_version_rows(dep, "kiss-eck", merged, ctx) == []


def test_component_version_rows_irrelevant_for_unregistered_component(lpi):
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297"}
    ctx = lpi.ChartContext(deps=[dep], root_values={}, rendered_paths={"podiumd/charts/zaakafhandelcomponent"})
    assert lpi.component_version_rows(dep, "zac", {"image": {"tag": "5.4.3"}}, ctx) == []


def test_component_version_rows_marks_row_disabled_when_its_own_path_never_rendered(lpi):
    """The render-gate applies to split-field rows too: a resolvable one
    still gets "disabled" when its chart-tree path never rendered."""
    dep = {"name": "redis-operator", "version": "0.26.1"}
    digest = "a" * 64
    merged = {
        "redisOperator": {
            "imageName": "quay.io/opstree/redis-operator",
            "imageTag": f"v0.26.0@sha256:{digest}",
        }
    }
    root_values = {"redis-operator": {"redisOperator": {"imageName": "quay.io/opstree/redis-operator"}}}
    ctx = lpi.ChartContext(deps=[dep], root_values=root_values, rendered_paths=set())

    rows = lpi.component_version_rows(dep, "redis-operator", merged, ctx)

    assert rows == [
        ("redis-operator", "redisOperator.imageTag", "quay.io/opstree/redis-operator", f"v0.26.0@sha256:{digest}", True)
    ]


# --- row_chart_tree_path ---


def test_row_chart_tree_path_defaults_to_the_dependency_own_top_level_path(lpi):
    dep = {"name": "openzaak", "version": "1.14.2"}
    assert lpi.row_chart_tree_path(lpi.VENDORED_DIR.parent, dep, "redis") == "podiumd/charts/openzaak"


def test_row_chart_tree_path_resolves_a_nested_chart_yaml_dependency(lpi, tmp_path: Path):
    """openzaak's bundled redis resolves to its own nested chart-tree path,
    so podiumd's "tags: {redis: false}" disables only that path."""
    dep = {"name": "openzaak", "version": "1.14.2"}
    make_vendored_tgz(
        lpi.VENDORED_DIR,
        tmp_path,
        "openzaak",
        "1.14.2",
        {
            "name": "openzaak",
            "version": "1.14.2",
            "dependencies": [{"name": "redis", "version": "18.0.0", "repository": "@bitnami"}],
        },
        {},
    )
    assert lpi.row_chart_tree_path(lpi.VENDORED_DIR.parent, dep, "redis") == "podiumd/charts/openzaak/charts/redis"


# --- load_chart ---


def test_load_chart_uses_vendored_tgz_without_network(lpi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297", "repository": "@zac"}
    make_vendored_tgz(
        lpi.VENDORED_DIR,
        tmp_path,
        "zaakafhandelcomponent",
        "1.0.297",
        {"name": "zaakafhandelcomponent", "version": "1.0.297", "appVersion": "5.5"},
        {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": ""}},
    )

    def must_not_be_called(*a, **kw):
        msg = "pull_chart should not be called when a vendored .tgz exists"
        raise AssertionError(msg)

    monkeypatch.setattr(lpi, "pull_chart", must_not_be_called)

    tmproot = tmp_path / "tmproot"
    tmproot.mkdir()
    chart_yaml, values = lpi.load_chart(dep, tmproot, refresh=False)
    assert chart_yaml["version"] == "1.0.297"
    assert values["image"]["repository"] == "ghcr.io/infonl/zaakafhandelcomponent"


def test_load_chart_refresh_flag_bypasses_vendored_tgz(lpi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297", "repository": "@zac"}
    make_vendored_tgz(
        lpi.VENDORED_DIR,
        tmp_path,
        "zaakafhandelcomponent",
        "1.0.297",
        {"name": "zaakafhandelcomponent", "version": "1.0.297", "appVersion": "FROM-VENDORED"},
        {},
    )

    def fake_pull_chart(dep, dest):
        write_pulled_chart(
            dest,
            "zaakafhandelcomponent",
            {"name": "zaakafhandelcomponent", "version": "1.0.297", "appVersion": "FROM-PULL"},
            {},
        )

    monkeypatch.setattr(lpi, "pull_chart", fake_pull_chart)
    tmproot = tmp_path / "tmproot"
    tmproot.mkdir()
    chart_yaml, _ = lpi.load_chart(dep, tmproot, refresh=True)
    assert chart_yaml["appVersion"] == "FROM-PULL"


def test_load_chart_falls_back_to_pull_when_not_vendored(lpi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297", "repository": "@zac"}

    def fake_pull_chart(dep, dest):
        write_pulled_chart(dest, "zaakafhandelcomponent", {"name": "zaakafhandelcomponent", "version": "1.0.297"}, {})

    monkeypatch.setattr(lpi, "pull_chart", fake_pull_chart)
    tmproot = tmp_path / "tmproot"
    tmproot.mkdir()
    chart_yaml, values = lpi.load_chart(dep, tmproot, refresh=False)
    assert chart_yaml["name"] == "zaakafhandelcomponent"
    assert values == {}


def test_load_chart_raises_if_nothing_produced(lpi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297", "repository": "@zac"}
    monkeypatch.setattr(lpi, "pull_chart", lambda dep, dest: None)
    tmproot = tmp_path / "tmproot"
    tmproot.mkdir()
    with pytest.raises(SystemExit, match="produced no chart directory"):
        lpi.load_chart(dep, tmproot, refresh=False)


def test_load_chart_reads_local_source_for_file_dependency(lpi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A "file://" dependency is read from its source directory, regardless
    of --refresh."""
    dep = {"name": "mi-data", "version": "1.0.0", "repository": "file://../mi-data"}
    local_dir = tmp_path / "mi-data"
    local_dir.mkdir()
    (local_dir / "Chart.yaml").write_text(yaml.safe_dump({"apiVersion": "v2", "name": "mi-data", "version": "1.0.0"}))
    (local_dir / "values.yaml").write_text(yaml.safe_dump({"image": {"repository": "azure-cli", "tag": "2.71.0"}}))
    monkeypatch.setattr(lpi, "local_chart_dir", lambda podiumd_dir, d: local_dir)
    monkeypatch.setattr(
        lpi,
        "pull_chart",
        lambda dep, dest: (_ for _ in ()).throw(
            AssertionError("pull_chart should not be called for a file:// dependency")
        ),
    )

    tmproot = tmp_path / "tmproot"
    tmproot.mkdir()
    chart_yaml, values = lpi.load_chart(dep, tmproot, refresh=True)
    assert chart_yaml["version"] == "1.0.0"
    assert values["image"]["repository"] == "azure-cli"


def test_load_chart_local_dependency_missing_directory_raises(lpi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dep = {"name": "mi-data", "version": "1.0.0", "repository": "file://../mi-data"}
    monkeypatch.setattr(lpi, "local_chart_dir", lambda podiumd_dir, d: tmp_path / "does-not-exist")
    tmproot = tmp_path / "tmproot"
    tmproot.mkdir()
    with pytest.raises(SystemExit, match="does not exist"):
        lpi.load_chart(dep, tmproot, refresh=False)


# --- pull_chart ---


def test_pull_chart_local_repository_raises_without_subprocess(lpi, tmp_path: Path):
    dep = {"name": "mi-data", "version": "1.0.0", "repository": "file://../mi-data"}
    with pytest.raises(SystemExit, match="not fetchable remotely"):
        lpi.pull_chart(dep, tmp_path)


def test_pull_chart_https_repo_adds_repo_flag(lpi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    dep = {"name": "zaakbrug", "version": "2.3.28", "repository": "https://wearefrank.github.io/charts"}
    lpi.pull_chart(dep, tmp_path)
    assert "--repo" in captured["cmd"]
    assert "https://wearefrank.github.io/charts" in captured["cmd"]


def test_pull_chart_alias_repo_has_no_repo_flag(lpi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297", "repository": "@zac"}
    lpi.pull_chart(dep, tmp_path)
    assert "--repo" not in captured["cmd"]


def test_pull_chart_failure_raises(lpi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="boom"))
    dep = {"name": "zaakafhandelcomponent", "version": "9.9.9", "repository": "@zac"}
    with pytest.raises(SystemExit, match="helm pull failed"):
        lpi.pull_chart(dep, tmp_path)


# --- main() ---


def run_main(lpi, monkeypatch: pytest.MonkeyPatch, argv=()):
    monkeypatch.setattr("sys.argv", ["list-podiumd-images", *argv])
    lpi.main()


def test_main_full_offline_flow(
    lpi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    lpi.CHART_YAML.write_text(
        yaml.safe_dump(
            {
                "dependencies": [
                    {
                        "name": "zaakafhandelcomponent",
                        "alias": "zac",
                        "version": "1.0.297",
                        "repository": "@zac",
                        "condition": "zac.enabled",
                    },
                    {
                        "name": "openbeheer",
                        "version": "0.1.3",
                        "repository": "@maykinmedia",
                        "condition": "openbeheer.enabled",
                    },
                ]
            }
        )
    )
    lpi.VALUES_YAML.write_text(
        yaml.safe_dump(
            {
                "global": {"images": {"nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3"}}},
                "zac": {
                    "enabled": True,
                    "image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.3@sha256:abc"},
                },
                "openbeheer": {"enabled": False},
            }
        )
    )
    make_vendored_tgz(
        lpi.VENDORED_DIR,
        tmp_path,
        "zaakafhandelcomponent",
        "1.0.297",
        {"name": "zaakafhandelcomponent", "version": "1.0.297", "appVersion": "5.5"},
        # chart default tag would be overridden by podiumd's own values.yaml override above
        {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.0-default@sha256:default"}},
    )
    make_vendored_tgz(
        lpi.VENDORED_DIR,
        tmp_path,
        "openbeheer",
        "0.1.3",
        {"name": "openbeheer", "version": "0.1.3", "appVersion": "0.1.0"},
        {"image": {"repository": "maykinmedia/open-beheer", "tag": "0.9.0"}},
    )
    # Only zac's path rendered (a condition:-disabled dependency case); keyed
    # by alias, not chart name.
    monkeypatch.setattr(lpi, "rendered_chart_paths", lambda stdout: {"podiumd/charts/zac"})

    run_main(lpi, monkeypatch)
    out = capsys.readouterr().out

    assert "podiumd top-level values" in out
    assert "nginxinc/nginx-unprivileged:1.31.3" in out

    assert "=== zac (zaakafhandelcomponent 1.0.297) ===" in out
    # podiumd's own override must win over the chart default
    assert "ghcr.io/infonl/zaakafhandelcomponent:5.4.3@sha256:abc" in out
    assert "5.0.0-default" not in out

    assert "=== openbeheer (openbeheer 0.1.3)  [disabled] ===" in out


def test_main_nested_tags_disabled_sidecar_is_labeled_disabled_not_dropped(
    lpi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A Maykin-style chart's nested redis, disabled via "tags: {redis: false}",
    is labelled "disabled" while openzaak itself stays live."""
    lpi.CHART_YAML.write_text(
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "openzaak", "version": "1.14.2", "repository": "@openzaak"},
                ]
            }
        )
    )
    lpi.VALUES_YAML.write_text(yaml.safe_dump({"tags": {"redis": False}}))
    make_vendored_tgz(
        lpi.VENDORED_DIR,
        tmp_path,
        "openzaak",
        "1.14.2",
        {
            "name": "openzaak",
            "version": "1.14.2",
            "dependencies": [{"name": "redis", "version": "18.0.0", "repository": "@bitnami", "tags": ["redis"]}],
        },
        {
            "image": {"repository": "openzaak/open-zaak", "tag": "1.14.2"},
            "redis": {"image": {"repository": "docker.io/bitnami/redis", "tag": "8.0.0"}},
        },
    )
    # openzaak's own path rendered; its own nested redis sub-subchart did not.
    monkeypatch.setattr(lpi, "rendered_chart_paths", lambda stdout: {"podiumd/charts/openzaak"})

    run_main(lpi, monkeypatch)
    out = capsys.readouterr().out

    assert "=== openzaak (openzaak 1.14.2) ===" in out  # enabled -- no [disabled] header
    assert "openzaak/open-zaak:1.14.2" in out

    redis_line = next(line for line in out.splitlines() if "redis.image" in line)
    assert "disabled" in redis_line


def test_main_render_failure_raises(lpi, monkeypatch: pytest.MonkeyPatch):
    lpi.CHART_YAML.write_text(yaml.safe_dump({"dependencies": []}))
    lpi.VALUES_YAML.write_text("{}\n")
    monkeypatch.setattr(
        lpi, "render_chart", lambda chart_dir, extra_args: SimpleNamespace(returncode=1, stdout="", stderr="boom")
    )
    with pytest.raises(SystemExit, match="helm template failed to render"):
        run_main(lpi, monkeypatch)


def test_main_refresh_flag_forces_pull(lpi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lpi.CHART_YAML.write_text(
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                ]
            }
        )
    )
    lpi.VALUES_YAML.write_text("{}\n")
    make_vendored_tgz(
        lpi.VENDORED_DIR,
        tmp_path,
        "zaakafhandelcomponent",
        "1.0.297",
        {"name": "zaakafhandelcomponent", "version": "1.0.297"},
        {},
    )

    calls = []

    def fake_pull_chart(dep, dest):
        calls.append(dep["name"])
        write_pulled_chart(dest, dep["name"], {"name": dep["name"], "version": dep["version"]}, {})

    monkeypatch.setattr(lpi, "pull_chart", fake_pull_chart)
    run_main(lpi, monkeypatch, ["--refresh"])
    assert calls == ["zaakafhandelcomponent"]


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(
    lpi, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], flag
):
    monkeypatch.setattr("sys.argv", ["list-podiumd-images", flag])
    with pytest.raises(SystemExit) as exc_info:
        lpi.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == f"{lpi.__doc__}\n"


def test_main_reports_and_continues_on_load_failure(
    lpi, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    lpi.CHART_YAML.write_text(
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "broken-dep", "version": "1.0.0", "repository": "file://../broken"},
                ]
            }
        )
    )
    lpi.VALUES_YAML.write_text("{}\n")
    run_main(lpi, monkeypatch)
    out = capsys.readouterr().out
    assert "=== broken-dep (broken-dep 1.0.0) ===" in out
    assert "does not exist" in out


def test_main_includes_component_version_path_images(
    lpi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Regression: split imageName:/imageTag: and bare CRD "version:" images
    were invisible to find_images; each must appear exactly once."""
    digest = "a" * 64
    lpi.CHART_YAML.write_text(
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "redis-operator", "version": "0.26.1", "repository": "@opstree"},
                    {
                        "name": "eck-stack",
                        "alias": "kiss-eck",
                        "version": "0.20.0",
                        "repository": "https://helm.elastic.co",
                    },
                ]
            }
        )
    )
    lpi.VALUES_YAML.write_text(
        yaml.safe_dump(
            {
                "redis-operator": {
                    "redisOperator": {
                        "imageName": "quay.io/opstree/redis-operator",
                        "imageTag": f"v0.26.0@sha256:{digest}",
                    }
                },
                "kiss-eck": {
                    "eck-elasticsearch": {"version": "8.19.19"},
                    "eck-kibana": {"version": "8.19.19"},
                    "eck-enterprise-search": {"version": "8.19.19"},
                },
            }
        )
    )
    make_vendored_tgz(
        lpi.VENDORED_DIR,
        tmp_path,
        "redis-operator",
        "0.26.1",
        {"name": "redis-operator", "version": "0.26.1"},
        {},
    )
    make_vendored_tgz(
        lpi.VENDORED_DIR,
        tmp_path,
        "eck-stack",
        "0.20.0",
        {"name": "eck-stack", "version": "0.20.0"},
        {},
        raw_files={
            "charts/eck-elasticsearch/values.yaml": "# image: docker.elastic.co/elasticsearch/elasticsearch:9.5.0\n",
            "charts/eck-kibana/values.yaml": "# image: docker.elastic.co/kibana/kibana:9.5.0\n",
            "charts/eck-enterprise-search/values.yaml": (
                "# image: docker.elastic.co/enterprise-search/enterprise-search:9.5.0\n"
            ),
        },
    )

    run_main(lpi, monkeypatch)
    out = capsys.readouterr().out

    assert f"quay.io/opstree/redis-operator:v0.26.0@sha256:{digest}" in out
    assert "docker.elastic.co/elasticsearch/elasticsearch:8.19.19" in out
    assert "docker.elastic.co/kibana/kibana:8.19.19" in out
    assert "docker.elastic.co/enterprise-search/enterprise-search:8.19.19" in out

    # Each basename's key+basename first line appears exactly once.
    assert out.count("redis-operator  redis-operator ") == 1
    assert out.count("kiss-eck  elasticsearch ") == 1
    assert out.count("kiss-eck  kibana ") == 1
    assert out.count("kiss-eck  enterprise-search ") == 1


# --- safe_extract_tgz ---


def _write_tgz(tgz_path: Path, member_name: str) -> None:
    src = tgz_path.parent / "payload.txt"
    src.write_text("x\n", encoding="utf-8")
    with tarfile.open(tgz_path, "w:gz") as tf:
        tf.add(src, arcname=member_name)


def _record_extractall_kwargs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_extractall(self: tarfile.TarFile, path: Path, **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(tarfile.TarFile, "extractall", fake_extractall)
    return calls


def test_safe_extract_tgz_rejects_a_member_escaping_dest(lpi, tmp_path: Path):
    tgz = tmp_path / "evil.tgz"
    _write_tgz(tgz, "../escape.txt")
    dest = tmp_path / "dest"
    dest.mkdir()

    with pytest.raises(SystemExit, match="would extract outside"):
        lpi.safe_extract_tgz(tgz, dest)


def test_safe_extract_tgz_passes_the_data_filter_when_available(lpi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tgz = tmp_path / "chart.tgz"
    _write_tgz(tgz, "chart/values.yaml")
    monkeypatch.setattr(tarfile, "data_filter", object(), raising=False)
    calls = _record_extractall_kwargs(monkeypatch)

    lpi.safe_extract_tgz(tgz, tmp_path)

    assert calls == [{"filter": "data"}]


def test_safe_extract_tgz_without_the_data_filter_extracts_unfiltered(
    lpi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    tgz = tmp_path / "chart.tgz"
    _write_tgz(tgz, "chart/values.yaml")
    monkeypatch.delattr(tarfile, "data_filter", raising=False)
    calls = _record_extractall_kwargs(monkeypatch)

    lpi.safe_extract_tgz(tgz, tmp_path)

    assert calls == [{}]
