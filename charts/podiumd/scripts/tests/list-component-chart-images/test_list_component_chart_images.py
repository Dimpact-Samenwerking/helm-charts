"""find_dependency, chart_ref, version_of, find_images, pull_chart, and main()
— `helm pull` is mocked out (via a fake pull_chart / fake subprocess.run), so
these tests need neither `helm` nor network access."""
import subprocess
from types import SimpleNamespace

import pytest
import yaml


def write_chart_yaml(lci, dependencies):
    lci.CHART_YAML.write_text(yaml.safe_dump({"dependencies": dependencies}))


# --- find_dependency ---

def test_find_dependency_by_name(lci):
    write_chart_yaml(lci, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    dep = lci.find_dependency("zaakafhandelcomponent")
    assert dep["alias"] == "zac"


def test_find_dependency_by_alias(lci):
    write_chart_yaml(lci, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    dep = lci.find_dependency("zac")
    assert dep["name"] == "zaakafhandelcomponent"


def test_find_dependency_not_found_raises(lci):
    write_chart_yaml(lci, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    with pytest.raises(SystemExit, match="no dependency named or aliased"):
        lci.find_dependency("totally-unknown")


# --- chart_ref ---

def test_chart_ref_alias_repository(lci):
    dep = {"name": "zaakafhandelcomponent", "repository": "@zac"}
    assert lci.chart_ref(dep) == "zac/zaakafhandelcomponent"


def test_chart_ref_oci_repository(lci):
    dep = {"name": "internetaakafhandeling", "repository": "oci://ghcr.io/interne-taak-afhandeling"}
    assert lci.chart_ref(dep) == "oci://ghcr.io/interne-taak-afhandeling/internetaakafhandeling"


def test_chart_ref_unsupported_scheme_raises(lci):
    dep = {"name": "zaakbrug", "repository": "https://wearefrank.github.io/charts"}
    with pytest.raises(SystemExit, match="unsupported repository scheme"):
        lci.chart_ref(dep)


# --- version_of ---

def test_version_of_strips_digest(lci):
    assert lci.version_of("5.4.3@sha256:abc") == "5.4.3"
    assert lci.version_of("1.19.0-static") == "1.19.0-static"


# --- find_images ---

def test_find_images_nested_dict_and_list(lci):
    values = {
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.3@sha256:abc"}},
        "items": [{"image": {"repository": "curlimages/curl", "tag": "8.21.0"}}],
    }
    images = lci.find_images(values)
    assert ("zac.image", "ghcr.io/infonl/zaakafhandelcomponent", "5.4.3@sha256:abc") in images
    assert ("items[0].image", "curlimages/curl", "8.21.0") in images


def test_find_images_skips_empty_tag(lci):
    assert lci.find_images({"image": {"repository": "x", "tag": ""}}) == []


def test_find_images_root_path_label(lci):
    images = lci.find_images({"repository": "x", "tag": "1.0"})
    assert images == [("(root)", "x", "1.0")]


# --- pull_chart ---

def test_pull_chart_success_does_not_raise(lci, monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""))
    lci.pull_chart("zac/zaakafhandelcomponent", "1.0.297", tmp_path)  # must not raise


def test_pull_chart_failure_raises_systemexit(lci, monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run",
                         lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="not found"))
    with pytest.raises(SystemExit, match="helm pull failed"):
        lci.pull_chart("zac/zaakafhandelcomponent", "9.9.9", tmp_path)


def test_pull_chart_builds_correct_command(lci, monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    lci.pull_chart("zac/zaakafhandelcomponent", "1.0.297", tmp_path)
    assert captured["cmd"] == [
        "helm", "pull", "zac/zaakafhandelcomponent", "--version", "1.0.297",
        "--untar", "--untardir", str(tmp_path),
    ]


# --- main() ---

def fake_chart_tgz_contents(tmpdir, chart_name, chart_version, app_version, image_tag):
    """Simulate what `helm pull --untar` would have produced."""
    chart_dir = tmpdir / chart_name
    chart_dir.mkdir()
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({
        "name": chart_name, "version": chart_version, "appVersion": app_version,
        "dependencies": [{"name": "opentelemetry-collector", "version": "0.169.0"}],
    }))
    (chart_dir / "values.yaml").write_text(yaml.safe_dump({
        "image": {"repository": f"ghcr.io/infonl/{chart_name}", "tag": image_tag},
    }))


def run_main(lci, monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["list-component-chart-images.py", *argv])
    lci.main()


def test_main_full_flow_prints_chart_and_images(lci, monkeypatch, capsys):
    write_chart_yaml(lci, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])

    def fake_pull_chart(ref, version, dest):
        fake_chart_tgz_contents(dest, "zaakafhandelcomponent", "1.0.297", "5.5", "5.4.3@sha256:abc")

    monkeypatch.setattr(lci, "pull_chart", fake_pull_chart)
    run_main(lci, monkeypatch, ["zac", "1.0.297"])
    out = capsys.readouterr().out
    assert "Chart: zaakafhandelcomponent 1.0.297 (appVersion: 5.5)" in out
    assert "opentelemetry-collector: 0.169.0" in out
    assert "5.4.3" in out and "ghcr.io/infonl/zaakafhandelcomponent:5.4.3@sha256:abc" in out


def test_main_no_image_references(lci, monkeypatch, capsys):
    write_chart_yaml(lci, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])

    def fake_pull_chart(ref, version, dest):
        chart_dir = dest / "zaakafhandelcomponent"
        chart_dir.mkdir()
        (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({"name": "zaakafhandelcomponent", "version": "1.0.297"}))
        (chart_dir / "values.yaml").write_text("{}\n")

    monkeypatch.setattr(lci, "pull_chart", fake_pull_chart)
    run_main(lci, monkeypatch, ["zac", "1.0.297"])
    assert "No image references found" in capsys.readouterr().out


def test_main_missing_arguments_exits(lci, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["list-component-chart-images.py", "zac"])
    with pytest.raises(SystemExit):
        lci.main()


def test_main_helm_pull_produces_no_directory_raises(lci, monkeypatch):
    write_chart_yaml(lci, [{"name": "zaakafhandelcomponent", "alias": "zac", "repository": "@zac"}])
    monkeypatch.setattr(lci, "pull_chart", lambda ref, version, dest: None)  # creates nothing
    monkeypatch.setattr("sys.argv", ["list-component-chart-images.py", "zac", "1.0.297"])
    with pytest.raises(SystemExit, match="produced no chart directory"):
        lci.main()
