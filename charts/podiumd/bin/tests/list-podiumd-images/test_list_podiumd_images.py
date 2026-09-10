"""deep_merge, version_of, find_images, row_chart_tree_path, load_chart,
pull_chart, and main() — offline throughout. load_chart's normal path reads a
locally vendored .tgz (exactly like a real `helm dependency update` output),
so most of this needs neither `helm` nor network access; the few tests that
exercise the `helm pull` fallback mock subprocess.run instead. A "file://"
dependency (e.g. mi-data) skips both the vendored-.tgz and pull paths
entirely — see lib.chart.local_chart_dir, tested directly in
tests/lib/test_chart.py — and reads its own source directory instead."""
import subprocess
import tarfile
from types import SimpleNamespace

import pytest
import yaml


def write_pulled_chart(dest, name, chart_yaml, values_yaml):
    """Real `helm pull --untar --untardir dest` creates dest/<name>/... (a
    nested directory) — load_chart() specifically looks for that nested dir,
    so a fake pull_chart must reproduce the same layout."""
    chart_dir = dest / name
    chart_dir.mkdir()
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump(chart_yaml))
    (chart_dir / "values.yaml").write_text(yaml.safe_dump(values_yaml))


def make_vendored_tgz(vendored_dir, tmp_path, name, version, chart_yaml, values_yaml, raw_files=None):
    """`raw_files`, if given (a {path relative to the chart root: text}
    dict, e.g. "charts/eck-elasticsearch/values.yaml") — writes each
    verbatim, in addition to Chart.yaml/values.yaml — for a nested
    sub-subchart's own commented-out "# image: ..." documentation (see
    lib.chart.nested_subchart_documented_image_repository), where the
    content isn't real structured YAML so yaml.safe_dump can't produce
    it (same convention tests/lib/test_chart.py's own make_tgz uses)."""
    staging = tmp_path / f"stage-{name}-{version}"
    chart_dir = staging / name
    chart_dir.mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump(chart_yaml))
    (chart_dir / "values.yaml").write_text(yaml.safe_dump(values_yaml))
    for rel_path, text in (raw_files or {}).items():
        file_path = chart_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(text)
    tgz_path = vendored_dir / f"{name}-{version}.tgz"
    with tarfile.open(tgz_path, "w:gz") as tf:
        tf.add(chart_dir, arcname=name)
    return tgz_path


# chart_ref is a pure passthrough of lib.chart.chart_ref — covered directly
# in tests/lib/test_chart.py, no need to duplicate here.


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
    values = {"zac": {"image": {"repository": "r", "tag": "1.0"}},
              "list": [{"image": {"repository": "r2", "tag": "2.0"}}]}
    images = lpi.find_images(values)
    assert ("zac.image", "r", "1.0") in images
    assert ("list[0].image", "r2", "2.0") in images


def test_find_images_root_path(lpi):
    assert lpi.find_images({"repository": "r", "tag": "1.0"}) == [("(root)", "r", "1.0")]


def test_find_images_skips_missing_or_empty_tag(lpi):
    assert lpi.find_images({"image": {"repository": "r", "tag": None}}) == []
    assert lpi.find_images({"image": {"repository": "r"}}) == []


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
    """A basename only literally pinned under values.yaml's global.images
    scope, not under the component asking about it, isn't a dead end --
    it's pointed at the key that DOES resolve (MULTIPLE, see
    lib.image_version.MULTIPLE_KEY)."""
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

def test_print_image_lines_leads_with_key_basename_version_and_path(lpi, capsys):
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


def test_print_image_lines_appends_note_when_not_resolvable(lpi, capsys):
    lpi.print_image_lines([("openbeheer", "image", "maykinmedia/open-beheer", "0.9.0", False)], [])
    out = capsys.readouterr().out
    assert "unresolvable" in out


def test_print_image_lines_appends_disabled_hint_for_a_never_rendered_row(lpi, capsys):
    """A row whose own chart-tree path never rendered (e.g. a Maykin
    chart's own bundled bitnami/redis, globally disabled via podiumd's
    top-level "tags: {redis: false}") is labeled "disabled" — no longer
    indistinguishable from a real, live image — rather than being
    silently dropped. Combined with an unresolvable resolution_note
    (empty values_lines here), both hints show up, disabled first."""
    lpi.print_image_lines([("openzaak", "redis.image", "redis", "8.0", True)], [])
    first_line, _detail_line = capsys.readouterr().out.splitlines()
    assert "disabled; unresolvable" in first_line


def test_print_image_lines_puts_note_on_first_line_not_the_detail_line(lpi, capsys):
    """The note is exactly what decides whether <key> <basename> (the
    first line) is usable -- it belongs there, not on the second,
    repo:tag detail line."""
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
# lib.chart.COMPONENT_VERSION_PATHS/COMPONENT_VERSION_PATH_NESTED_SUBCHARTS-
# registered bare version fields — the ONE image shape find_images'
# generic "{repository, tag}" dict match structurally can never see at
# all: redis-operator's own split imageName:/imageTag: sibling fields,
# and eck-stack's own eck-elasticsearch/eck-kibana/eck-enterprise-search
# CRD-version-only fields (repository only ever documented in the nested
# sub-subchart's own vendored values.yaml — see lib.chart.
# nested_subchart_documented_image_repository). Real gap, confirmed
# empirically against the real chart: all 4 of these images are in
# docs/images/images-baseline.yaml but were entirely absent from
# list-podiumd-images's own output before this fix.

def test_component_version_rows_resolves_redis_operator_split_image_fields(lpi):
    """redis-operator's own controller image is never nested under an
    "image:"/"...Image:" dict at all — a split "imageName:"/"imageTag:"
    sibling-field pair instead (lib.chart.COMPONENT_VERSION_PATHS)."""
    dep = {"name": "redis-operator", "version": "0.26.1"}
    digest = "a" * 64
    merged = {"redisOperator": {
        "imageName": "quay.io/opstree/redis-operator",
        "imageTag": f"v0.26.0@sha256:{digest}",
    }}
    root_values = {"redis-operator": {"redisOperator": {"imageName": "quay.io/opstree/redis-operator"}}}

    rows = lpi.component_version_rows(dep, "redis-operator", merged, [dep], root_values,
                                       {"podiumd/charts/redis-operator"})

    assert rows == [("redis-operator", "redisOperator.imageTag",
                      "quay.io/opstree/redis-operator", f"v0.26.0@sha256:{digest}", False)]


def test_component_version_rows_uses_merged_tree_not_just_podiumd_overrides(lpi):
    """Unlike the doc-generation side (lib.upgradedoc.find_component_
    version_tags), which only ever looks at podiumd's own values.yaml,
    this tool's whole point is the full EFFECTIVE image set — a tag that
    ONLY exists in the chart default (never overridden by podiumd) must
    still show up here."""
    dep = {"name": "redis-operator", "version": "0.26.1"}
    digest = "b" * 64
    merged = {"redisOperator": {
        "imageName": "quay.io/opstree/redis-operator",
        "imageTag": f"v0.25.0@sha256:{digest}",  # chart default, no podiumd override at all
    }}
    root_values = {"redis-operator": {"redisOperator": {"imageName": "quay.io/opstree/redis-operator"}}}

    rows = lpi.component_version_rows(dep, "redis-operator", merged, [dep], root_values,
                                       {"podiumd/charts/redis-operator"})

    assert rows == [("redis-operator", "redisOperator.imageTag",
                      "quay.io/opstree/redis-operator", f"v0.25.0@sha256:{digest}", False)]


def test_component_version_rows_resolves_eck_stack_nested_subchart_images(lpi, tmp_path):
    """eck-stack's own eck-elasticsearch/eck-kibana/eck-enterprise-search
    fields are bare CRD "version:" scalars with no repository sibling
    anywhere in podiumd's own values.yaml at all — the real repository
    is only ever documented in the nested sub-subchart's own vendored
    values.yaml."""
    dep = {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}
    make_vendored_tgz(
        lpi.VENDORED_DIR, tmp_path, "eck-stack", "0.20.0",
        {"name": "eck-stack", "version": "0.20.0"}, {},
        raw_files={
            "charts/eck-elasticsearch/values.yaml": "# image: docker.elastic.co/elasticsearch/elasticsearch:9.5.0\n",
            "charts/eck-kibana/values.yaml": "# image: docker.elastic.co/kibana/kibana:9.5.0\n",
            "charts/eck-enterprise-search/values.yaml":
                "# image: docker.elastic.co/enterprise-search/enterprise-search:9.5.0\n",
        },
    )
    merged = {
        "eck-elasticsearch": {"version": "8.19.19"},
        "eck-kibana": {"version": "8.19.19"},
        "eck-enterprise-search": {"version": "8.19.19"},
    }

    # chart-tree path is keyed by dep's own alias ("kiss-eck"), never
    # its real chart name ("eck-stack").
    rows = lpi.component_version_rows(dep, "kiss-eck", merged, [dep], {}, {"podiumd/charts/kiss-eck"})

    assert sorted(rows) == sorted([
        ("kiss-eck", "eck-elasticsearch.version", "docker.elastic.co/elasticsearch/elasticsearch", "8.19.19", False),
        ("kiss-eck", "eck-enterprise-search.version", "docker.elastic.co/enterprise-search/enterprise-search",
         "8.19.19", False),
        ("kiss-eck", "eck-kibana.version", "docker.elastic.co/kibana/kibana", "8.19.19", False),
    ])


def test_component_version_rows_blank_tag_is_skipped(lpi):
    dep = {"name": "redis-operator", "version": "0.26.1"}
    merged = {"redisOperator": {"imageName": "quay.io/opstree/redis-operator", "imageTag": ""}}
    root_values = {"redis-operator": {"redisOperator": {"imageName": "quay.io/opstree/redis-operator"}}}
    assert lpi.component_version_rows(dep, "redis-operator", merged, [dep], root_values,
                                       {"podiumd/charts/redis-operator"}) == []


def test_component_version_rows_unresolvable_repository_is_skipped(lpi):
    """A registered version field with a real tag but no resolvable
    repository anywhere (no podiumd override, no vendored nested
    sub-subchart) is silently skipped — never a row with a fabricated or
    missing repository."""
    dep = {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}
    merged = {"eck-elasticsearch": {"version": "8.19.19"}}
    assert lpi.component_version_rows(dep, "kiss-eck", merged, [dep], {}, {"podiumd/charts/kiss-eck"}) == []


def test_component_version_rows_irrelevant_for_unregistered_component(lpi):
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297"}
    assert lpi.component_version_rows(dep, "zac", {"image": {"tag": "5.4.3"}}, [dep], {},
                                       {"podiumd/charts/zaakafhandelcomponent"}) == []


def test_component_version_rows_marks_row_disabled_when_its_own_path_never_rendered(lpi):
    """The render-gate applies here too, independent of the merged
    tag/repository resolution above it: a registered version field with
    a real, resolvable tag+repository still gets a "disabled" row when
    its own chart-tree path never rendered — the exact same mechanism
    that fixes the 9 Maykin-chart redis rows in find_images-derived rows
    below, just for the split-field shape instead."""
    dep = {"name": "redis-operator", "version": "0.26.1"}
    digest = "a" * 64
    merged = {"redisOperator": {
        "imageName": "quay.io/opstree/redis-operator",
        "imageTag": f"v0.26.0@sha256:{digest}",
    }}
    root_values = {"redis-operator": {"redisOperator": {"imageName": "quay.io/opstree/redis-operator"}}}

    rows = lpi.component_version_rows(dep, "redis-operator", merged, [dep], root_values, set())

    assert rows == [("redis-operator", "redisOperator.imageTag",
                      "quay.io/opstree/redis-operator", f"v0.26.0@sha256:{digest}", True)]


# --- row_chart_tree_path ---

def test_row_chart_tree_path_defaults_to_the_dependency_own_top_level_path(lpi):
    dep = {"name": "openzaak", "version": "1.14.2"}
    assert lpi.row_chart_tree_path(lpi.VENDORED_DIR.parent, dep, "redis") == "podiumd/charts/openzaak"


def test_row_chart_tree_path_resolves_a_nested_chart_yaml_dependency(lpi, tmp_path):
    """openzaak's own bundled bitnami/redis (a real, separate Chart.yaml
    dependency OF openzaak itself, tagged "redis" in openzaak's own
    Chart.yaml "tags:" list) must resolve to ITS OWN nested chart-tree
    path — not openzaak's own top-level one — so podiumd's own top-level
    "tags: {redis: false}" (which disables ONLY this nested path, not
    openzaak itself) is reflected correctly."""
    dep = {"name": "openzaak", "version": "1.14.2"}
    make_vendored_tgz(
        lpi.VENDORED_DIR, tmp_path, "openzaak", "1.14.2",
        {"name": "openzaak", "version": "1.14.2",
         "dependencies": [{"name": "redis", "version": "18.0.0", "repository": "@bitnami"}]},
        {},
    )
    assert lpi.row_chart_tree_path(lpi.VENDORED_DIR.parent, dep, "redis") == "podiumd/charts/openzaak/charts/redis"


# --- load_chart ---

def test_load_chart_uses_vendored_tgz_without_network(lpi, tmp_path, monkeypatch):
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297", "repository": "@zac"}
    make_vendored_tgz(
        lpi.VENDORED_DIR, tmp_path, "zaakafhandelcomponent", "1.0.297",
        {"name": "zaakafhandelcomponent", "version": "1.0.297", "appVersion": "5.5"},
        {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": ""}},
    )

    def must_not_be_called(*a, **kw):
        raise AssertionError("pull_chart should not be called when a vendored .tgz exists")

    monkeypatch.setattr(lpi, "pull_chart", must_not_be_called)

    tmproot = tmp_path / "tmproot"
    tmproot.mkdir()
    chart_yaml, values = lpi.load_chart(dep, tmproot, refresh=False)
    assert chart_yaml["version"] == "1.0.297"
    assert values["image"]["repository"] == "ghcr.io/infonl/zaakafhandelcomponent"


def test_load_chart_refresh_flag_bypasses_vendored_tgz(lpi, tmp_path, monkeypatch):
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297", "repository": "@zac"}
    make_vendored_tgz(
        lpi.VENDORED_DIR, tmp_path, "zaakafhandelcomponent", "1.0.297",
        {"name": "zaakafhandelcomponent", "version": "1.0.297", "appVersion": "FROM-VENDORED"}, {},
    )

    def fake_pull_chart(dep, dest):
        write_pulled_chart(dest, "zaakafhandelcomponent",
                            {"name": "zaakafhandelcomponent", "version": "1.0.297", "appVersion": "FROM-PULL"}, {})

    monkeypatch.setattr(lpi, "pull_chart", fake_pull_chart)
    tmproot = tmp_path / "tmproot"
    tmproot.mkdir()
    chart_yaml, _ = lpi.load_chart(dep, tmproot, refresh=True)
    assert chart_yaml["appVersion"] == "FROM-PULL"


def test_load_chart_falls_back_to_pull_when_not_vendored(lpi, tmp_path, monkeypatch):
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297", "repository": "@zac"}

    def fake_pull_chart(dep, dest):
        write_pulled_chart(dest, "zaakafhandelcomponent",
                            {"name": "zaakafhandelcomponent", "version": "1.0.297"}, {})

    monkeypatch.setattr(lpi, "pull_chart", fake_pull_chart)
    tmproot = tmp_path / "tmproot"
    tmproot.mkdir()
    chart_yaml, values = lpi.load_chart(dep, tmproot, refresh=False)
    assert chart_yaml["name"] == "zaakafhandelcomponent"
    assert values == {}


def test_load_chart_raises_if_nothing_produced(lpi, tmp_path, monkeypatch):
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297", "repository": "@zac"}
    monkeypatch.setattr(lpi, "pull_chart", lambda dep, dest: None)
    tmproot = tmp_path / "tmproot"
    tmproot.mkdir()
    with pytest.raises(SystemExit, match="produced no chart directory"):
        lpi.load_chart(dep, tmproot, refresh=False)


def test_load_chart_reads_local_source_for_file_dependency(lpi, tmp_path, monkeypatch):
    """A "file://" dependency has no remote to pull from and no vendored
    .tgz shape to extract — read straight from its own source directory
    instead, regardless of --refresh (there's nothing to refresh: reading
    the directory live is already always current)."""
    dep = {"name": "mi-data", "version": "1.0.0", "repository": "file://../mi-data"}
    local_dir = tmp_path / "mi-data"
    local_dir.mkdir()
    (local_dir / "Chart.yaml").write_text(yaml.safe_dump({"name": "mi-data", "version": "1.0.0"}))
    (local_dir / "values.yaml").write_text(yaml.safe_dump({"image": {"repository": "azure-cli", "tag": "2.71.0"}}))
    monkeypatch.setattr(lpi, "local_chart_dir", lambda podiumd_dir, d: local_dir)
    monkeypatch.setattr(lpi, "pull_chart", lambda dep, dest: (_ for _ in ()).throw(
        AssertionError("pull_chart should not be called for a file:// dependency")))

    tmproot = tmp_path / "tmproot"
    tmproot.mkdir()
    chart_yaml, values = lpi.load_chart(dep, tmproot, refresh=True)
    assert chart_yaml["version"] == "1.0.0"
    assert values["image"]["repository"] == "azure-cli"


def test_load_chart_local_dependency_missing_directory_raises(lpi, tmp_path, monkeypatch):
    dep = {"name": "mi-data", "version": "1.0.0", "repository": "file://../mi-data"}
    monkeypatch.setattr(lpi, "local_chart_dir", lambda podiumd_dir, d: tmp_path / "does-not-exist")
    tmproot = tmp_path / "tmproot"
    tmproot.mkdir()
    with pytest.raises(SystemExit, match="does not exist"):
        lpi.load_chart(dep, tmproot, refresh=False)


# --- pull_chart ---

def test_pull_chart_local_repository_raises_without_subprocess(lpi, tmp_path):
    dep = {"name": "mi-data", "version": "1.0.0", "repository": "file://../mi-data"}
    with pytest.raises(SystemExit, match="not fetchable remotely"):
        lpi.pull_chart(dep, tmp_path)


def test_pull_chart_https_repo_adds_repo_flag(lpi, tmp_path, monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    dep = {"name": "zaakbrug", "version": "2.3.28", "repository": "https://wearefrank.github.io/charts"}
    lpi.pull_chart(dep, tmp_path)
    assert "--repo" in captured["cmd"]
    assert "https://wearefrank.github.io/charts" in captured["cmd"]


def test_pull_chart_alias_repo_has_no_repo_flag(lpi, tmp_path, monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    dep = {"name": "zaakafhandelcomponent", "version": "1.0.297", "repository": "@zac"}
    lpi.pull_chart(dep, tmp_path)
    assert "--repo" not in captured["cmd"]


def test_pull_chart_failure_raises(lpi, tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                         lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="boom"))
    dep = {"name": "zaakafhandelcomponent", "version": "9.9.9", "repository": "@zac"}
    with pytest.raises(SystemExit, match="helm pull failed"):
        lpi.pull_chart(dep, tmp_path)


# --- main() ---

def run_main(lpi, monkeypatch, argv=()):
    monkeypatch.setattr("sys.argv", ["list-podiumd-images", *argv])
    lpi.main()


def test_main_full_offline_flow(lpi, tmp_path, monkeypatch, capsys):
    lpi.CHART_YAML.write_text(yaml.safe_dump({"dependencies": [
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297",
         "repository": "@zac", "condition": "zac.enabled"},
        {"name": "openbeheer", "version": "0.1.3", "repository": "@maykinmedia",
         "condition": "openbeheer.enabled"},
    ]}))
    lpi.VALUES_YAML.write_text(yaml.safe_dump({
        "global": {"images": {"nginx": {"repository": "nginxinc/nginx-unprivileged", "tag": "1.31.3"}}},
        "zac": {"enabled": True, "image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.3@sha256:abc"}},
        "openbeheer": {"enabled": False},
    }))
    make_vendored_tgz(
        lpi.VENDORED_DIR, tmp_path, "zaakafhandelcomponent", "1.0.297",
        {"name": "zaakafhandelcomponent", "version": "1.0.297", "appVersion": "5.5"},
        # chart default tag would be overridden by podiumd's own values.yaml override above
        {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.0.0-default@sha256:default"}},
    )
    make_vendored_tgz(
        lpi.VENDORED_DIR, tmp_path, "openbeheer", "0.1.3",
        {"name": "openbeheer", "version": "0.1.3", "appVersion": "0.1.0"},
        {"image": {"repository": "maykinmedia/open-beheer", "tag": "0.9.0"}},
    )
    # Overrides the autouse stub_render_chart default (which reports
    # every chart-tree path as rendered) — this test specifically
    # exercises the render-gate's own "condition:-disabled dependency"
    # case: only zac's own path actually rendered. Keyed by zac's own
    # alias, never its real chart name ("zaakafhandelcomponent").
    monkeypatch.setattr(lpi, "rendered_chart_paths",
                         lambda stdout: {"podiumd/charts/zac"})

    run_main(lpi, monkeypatch)
    out = capsys.readouterr().out

    assert "podiumd top-level values" in out
    assert "nginxinc/nginx-unprivileged:1.31.3" in out

    assert "=== zac (zaakafhandelcomponent 1.0.297) ===" in out
    # podiumd's own override must win over the chart default
    assert "ghcr.io/infonl/zaakafhandelcomponent:5.4.3@sha256:abc" in out
    assert "5.0.0-default" not in out

    assert "=== openbeheer (openbeheer 0.1.3)  [disabled] ===" in out


def test_main_nested_tags_disabled_sidecar_is_labeled_disabled_not_dropped(lpi, tmp_path, monkeypatch, capsys):
    """The real bug this task fixes: a Maykin-style chart bundles its own
    bitnami/redis as a SEPARATE nested Chart.yaml dependency of its own,
    globally disabled via podiumd's own top-level "tags: {redis: false}"
    — the dependency itself (openzaak) is very much enabled and renders
    fine, but its own nested redis sidecar never renders. The redis row
    must be labeled "disabled", not silently look like a live image —
    while openzaak's own header and its own real image stay unaffected."""
    lpi.CHART_YAML.write_text(yaml.safe_dump({"dependencies": [
        {"name": "openzaak", "version": "1.14.2", "repository": "@openzaak"},
    ]}))
    lpi.VALUES_YAML.write_text(yaml.safe_dump({"tags": {"redis": False}}))
    make_vendored_tgz(
        lpi.VENDORED_DIR, tmp_path, "openzaak", "1.14.2",
        {"name": "openzaak", "version": "1.14.2",
         "dependencies": [{"name": "redis", "version": "18.0.0", "repository": "@bitnami", "tags": ["redis"]}]},
        {"image": {"repository": "openzaak/open-zaak", "tag": "1.14.2"},
         "redis": {"image": {"repository": "docker.io/bitnami/redis", "tag": "8.0.0"}}},
    )
    # openzaak's own path rendered; its own nested redis sub-subchart did not.
    monkeypatch.setattr(lpi, "rendered_chart_paths", lambda stdout: {"podiumd/charts/openzaak"})

    run_main(lpi, monkeypatch)
    out = capsys.readouterr().out

    assert "=== openzaak (openzaak 1.14.2) ===" in out  # enabled -- no [disabled] header
    assert "openzaak/open-zaak:1.14.2" in out

    redis_line = next(line for line in out.splitlines() if "redis.image" in line)
    assert "disabled" in redis_line


def test_main_render_failure_raises(lpi, monkeypatch):
    lpi.CHART_YAML.write_text(yaml.safe_dump({"dependencies": []}))
    lpi.VALUES_YAML.write_text("{}\n")
    monkeypatch.setattr(lpi, "render_chart",
                         lambda chart_dir, extra_args: SimpleNamespace(returncode=1, stdout="", stderr="boom"))
    with pytest.raises(SystemExit, match="helm template failed to render"):
        run_main(lpi, monkeypatch)


def test_main_refresh_flag_forces_pull(lpi, tmp_path, monkeypatch):
    lpi.CHART_YAML.write_text(yaml.safe_dump({"dependencies": [
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
    ]}))
    lpi.VALUES_YAML.write_text("{}\n")
    make_vendored_tgz(
        lpi.VENDORED_DIR, tmp_path, "zaakafhandelcomponent", "1.0.297",
        {"name": "zaakafhandelcomponent", "version": "1.0.297"}, {},
    )

    calls = []

    def fake_pull_chart(dep, dest):
        calls.append(dep["name"])
        write_pulled_chart(dest, dep["name"], {"name": dep["name"], "version": dep["version"]}, {})

    monkeypatch.setattr(lpi, "pull_chart", fake_pull_chart)
    run_main(lpi, monkeypatch, ["--refresh"])
    assert calls == ["zaakafhandelcomponent"]


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(lpi, monkeypatch, capsys, flag):
    monkeypatch.setattr("sys.argv", ["list-podiumd-images", flag])
    with pytest.raises(SystemExit) as exc_info:
        lpi.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == lpi.__doc__ + "\n"


def test_main_reports_and_continues_on_load_failure(lpi, monkeypatch, capsys):
    lpi.CHART_YAML.write_text(yaml.safe_dump({"dependencies": [
        {"name": "broken-dep", "version": "1.0.0", "repository": "file://../broken"},
    ]}))
    lpi.VALUES_YAML.write_text("{}\n")
    run_main(lpi, monkeypatch)
    out = capsys.readouterr().out
    assert "=== broken-dep (broken-dep 1.0.0) ===" in out
    assert "does not exist" in out


def test_main_includes_component_version_path_images(lpi, tmp_path, monkeypatch, capsys):
    """Regression test for the real gap (confirmed empirically against
    the real chart): redis-operator's own controller image (split
    imageName:/imageTag: fields) and eck-stack's own eck-elasticsearch/
    eck-kibana/eck-enterprise-search (bare CRD "version:" fields,
    repository only documented in the nested sub-subchart's own
    vendored values.yaml) were BOTH entirely invisible to
    list-podiumd-images before this fix — find_images' generic
    "{repository, tag}" dict match structurally can't see either shape
    at all. Also confirms no double-counting: each basename appears
    exactly once in the whole run's output."""
    digest = "a" * 64
    lpi.CHART_YAML.write_text(yaml.safe_dump({"dependencies": [
        {"name": "redis-operator", "version": "0.26.1", "repository": "@opstree"},
        {"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0", "repository": "https://helm.elastic.co"},
    ]}))
    lpi.VALUES_YAML.write_text(yaml.safe_dump({
        "redis-operator": {"redisOperator": {
            "imageName": "quay.io/opstree/redis-operator",
            "imageTag": f"v0.26.0@sha256:{digest}",
        }},
        "kiss-eck": {
            "eck-elasticsearch": {"version": "8.19.19"},
            "eck-kibana": {"version": "8.19.19"},
            "eck-enterprise-search": {"version": "8.19.19"},
        },
    }))
    make_vendored_tgz(
        lpi.VENDORED_DIR, tmp_path, "redis-operator", "0.26.1",
        {"name": "redis-operator", "version": "0.26.1"}, {},
    )
    make_vendored_tgz(
        lpi.VENDORED_DIR, tmp_path, "eck-stack", "0.20.0",
        {"name": "eck-stack", "version": "0.20.0"}, {},
        raw_files={
            "charts/eck-elasticsearch/values.yaml": "# image: docker.elastic.co/elasticsearch/elasticsearch:9.5.0\n",
            "charts/eck-kibana/values.yaml": "# image: docker.elastic.co/kibana/kibana:9.5.0\n",
            "charts/eck-enterprise-search/values.yaml":
                "# image: docker.elastic.co/enterprise-search/enterprise-search:9.5.0\n",
        },
    )

    run_main(lpi, monkeypatch)
    out = capsys.readouterr().out

    assert f"quay.io/opstree/redis-operator:v0.26.0@sha256:{digest}" in out
    assert "docker.elastic.co/elasticsearch/elasticsearch:8.19.19" in out
    assert "docker.elastic.co/kibana/kibana:8.19.19" in out
    assert "docker.elastic.co/enterprise-search/enterprise-search:8.19.19" in out

    # no double-counting: each basename's own first-line key+basename
    # column shows up exactly once across the whole run.
    assert out.count("redis-operator  redis-operator ") == 1
    assert out.count("kiss-eck  elasticsearch ") == 1
    assert out.count("kiss-eck  kibana ") == 1
    assert out.count("kiss-eck  enterprise-search ") == 1
