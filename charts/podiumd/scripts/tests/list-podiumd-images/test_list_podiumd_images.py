"""chart_ref, deep_merge, version_of, find_images, is_enabled, load_chart,
pull_chart, and main() — offline throughout. load_chart's normal path reads a
locally vendored .tgz (exactly like a real `helm dependency update` output),
so most of this needs neither `helm` nor network access; the few tests that
exercise the `helm pull` fallback mock subprocess.run instead."""
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


def make_vendored_tgz(vendored_dir, tmp_path, name, version, chart_yaml, values_yaml):
    staging = tmp_path / f"stage-{name}-{version}"
    chart_dir = staging / name
    chart_dir.mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump(chart_yaml))
    (chart_dir / "values.yaml").write_text(yaml.safe_dump(values_yaml))
    tgz_path = vendored_dir / f"{name}-{version}.tgz"
    with tarfile.open(tgz_path, "w:gz") as tf:
        tf.add(chart_dir, arcname=name)
    return tgz_path


# --- chart_ref ---

def test_chart_ref_alias_repository(lpi):
    ref, repo_url = lpi.chart_ref({"name": "zaakafhandelcomponent", "repository": "@zac"})
    assert ref == "zac/zaakafhandelcomponent"
    assert repo_url is None


def test_chart_ref_oci_repository(lpi):
    ref, repo_url = lpi.chart_ref(
        {"name": "internetaakafhandeling", "repository": "oci://ghcr.io/interne-taak-afhandeling"})
    assert ref == "oci://ghcr.io/interne-taak-afhandeling/internetaakafhandeling"
    assert repo_url is None


def test_chart_ref_https_repository(lpi):
    ref, repo_url = lpi.chart_ref({"name": "zaakbrug", "repository": "https://wearefrank.github.io/charts"})
    assert ref == "zaakbrug"
    assert repo_url == "https://wearefrank.github.io/charts"


def test_chart_ref_file_repository_returns_none(lpi):
    ref, repo_url = lpi.chart_ref({"name": "mi-data", "repository": "file://../mi-data"})
    assert ref is None and repo_url is None


def test_chart_ref_unsupported_scheme_raises(lpi):
    with pytest.raises(SystemExit, match="unsupported repository scheme"):
        lpi.chart_ref({"name": "x", "repository": "ftp://nope"})


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


# --- is_enabled ---

def test_is_enabled_no_condition_defaults_true(lpi):
    assert lpi.is_enabled(None, {}) is True


def test_is_enabled_missing_override_defaults_true(lpi):
    assert lpi.is_enabled("zac.enabled", {}) is True


def test_is_enabled_explicit_false(lpi):
    assert lpi.is_enabled("zac.enabled", {"zac": {"enabled": False}}) is False


def test_is_enabled_explicit_true(lpi):
    assert lpi.is_enabled("zac.enabled", {"zac": {"enabled": True}}) is True


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
    with pytest.raises(SystemExit, match="no chart directory found"):
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
    monkeypatch.setattr("sys.argv", ["list-podiumd-images.py", *argv])
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

    run_main(lpi, monkeypatch)
    out = capsys.readouterr().out

    assert "podiumd top-level values" in out
    assert "nginxinc/nginx-unprivileged:1.31.3" in out

    assert "=== zac (zaakafhandelcomponent 1.0.297) ===" in out
    # podiumd's own override must win over the chart default
    assert "ghcr.io/infonl/zaakafhandelcomponent:5.4.3@sha256:abc" in out
    assert "5.0.0-default" not in out

    assert "=== openbeheer (openbeheer 0.1.3)  [disabled] ===" in out


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


def test_main_reports_and_continues_on_load_failure(lpi, monkeypatch, capsys):
    lpi.CHART_YAML.write_text(yaml.safe_dump({"dependencies": [
        {"name": "broken-dep", "version": "1.0.0", "repository": "file://../broken"},
    ]}))
    lpi.VALUES_YAML.write_text("{}\n")
    run_main(lpi, monkeypatch)
    out = capsys.readouterr().out
    assert "=== broken-dep (broken-dep 1.0.0) ===" in out
    assert "not fetchable remotely" in out
