"""verify_component_version, baseline_doc_paths, load_baseline_values:
split out of the former, monolithic test_update_component_version.py for
pylint's too-many-lines check."""

import subprocess

import pytest


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


# --- verify_component_version ---


def test_verify_component_version_returns_upstream_image_results(ucv, monkeypatch):
    dep = {"name": "openforms", "alias": "openformulieren", "version": "1.11.0", "repository": "@maykinmedia"}
    digest = "sha256:" + "c" * 64

    monkeypatch.setattr(
        ucv,
        "resolve_chart_values",
        lambda chart_dir, dep_arg, version, allow_pull=True: (
            {"image": {"repository": "maykinmedia/open-forms"}},
            "pulled",
            None,
        ),
    )
    monkeypatch.setattr(
        ucv,
        "check_image_versions",
        lambda values, image_paths, app_version: [
            {
                "path": "image",
                "repository": "maykinmedia/open-forms",
                "host": "docker.io",
                "repo_path": "maykinmedia/open-forms",
                "exists": True,
                "digest": digest,
            }
        ],
    )
    result = ucv.verify_component_version(dep, ["image"], "3.5.6", "1.12.0")
    assert result == {
        "image": {
            "path": "image",
            "repository": "maykinmedia/open-forms",
            "host": "docker.io",
            "repo_path": "maykinmedia/open-forms",
            "exists": True,
            "digest": digest,
        }
    }


def test_verify_component_version_exits_on_pull_failure(ucv, monkeypatch):
    dep = {"name": "openforms", "repository": "@maykinmedia"}
    monkeypatch.setattr(
        ucv,
        "resolve_chart_values",
        lambda chart_dir, dep_arg, version, allow_pull=True: (None, None, "chart version not found"),
    )
    with pytest.raises(SystemExit):
        ucv.verify_component_version(dep, ["image"], "3.5.6", "9.9.9")


def test_verify_component_version_exits_when_image_does_not_exist(ucv, monkeypatch):
    dep = {"name": "openforms", "repository": "@maykinmedia"}

    monkeypatch.setattr(
        ucv,
        "resolve_chart_values",
        lambda chart_dir, dep_arg, version, allow_pull=True: (
            {"image": {"repository": "maykinmedia/open-forms"}},
            "pulled",
            None,
        ),
    )
    monkeypatch.setattr(
        ucv,
        "check_image_versions",
        lambda values, image_paths, app_version: [
            {
                "path": "image",
                "repository": "maykinmedia/open-forms",
                "host": "docker.io",
                "repo_path": "maykinmedia/open-forms",
                "exists": False,
                "digest": None,
            }
        ],
    )
    with pytest.raises(SystemExit):
        ucv.verify_component_version(dep, ["image"], "9.9.9", "1.12.0")


# --- baseline_doc_paths ---


def test_baseline_doc_paths_finds_pair(ucv, tmp_path, monkeypatch):
    monkeypatch.setattr(ucv, "DOC_DIR", tmp_path)
    write(tmp_path / "4.8.5-to-4.9.0-upgrade.md", "x")
    write(tmp_path / "4.8.5-to-4.9.0-values-deltas.md", "x")
    upgrade_path, values_deltas_path = ucv.baseline_doc_paths("4.8.5", "4.9.0")
    assert upgrade_path == tmp_path / "4.8.5-to-4.9.0-upgrade.md"
    assert values_deltas_path == tmp_path / "4.8.5-to-4.9.0-values-deltas.md"


def test_baseline_doc_paths_missing_values_deltas_is_none(ucv, tmp_path, monkeypatch):
    monkeypatch.setattr(ucv, "DOC_DIR", tmp_path)
    write(tmp_path / "4.8.5-to-4.9.0-upgrade.md", "x")
    upgrade_path, values_deltas_path = ucv.baseline_doc_paths("4.8.5", "4.9.0")
    assert upgrade_path == tmp_path / "4.8.5-to-4.9.0-upgrade.md"
    assert values_deltas_path is None


def test_baseline_doc_paths_no_upgrade_doc_returns_none_none(ucv, tmp_path, monkeypatch):
    monkeypatch.setattr(ucv, "DOC_DIR", tmp_path)
    assert ucv.baseline_doc_paths("4.8.5", "4.9.0") == (None, None)


def test_baseline_doc_paths_no_baseline_returns_none_none(ucv, tmp_path, monkeypatch):
    monkeypatch.setattr(ucv, "DOC_DIR", tmp_path)
    write(tmp_path / "4.8.5-to-4.9.0-upgrade.md", "x")
    assert ucv.baseline_doc_paths(None, "4.9.0") == (None, None)


def write(path, text):
    path.write_text(text, encoding="utf-8")


# --- load_baseline_values ---


def init_git_repo(root):
    git("init", "-q", cwd=root)
    git("config", "user.email", "test@example.com", cwd=root)
    git("config", "user.name", "Test", cwd=root)


def test_load_baseline_values_resolves_real_baseline(ucv, tmp_path, monkeypatch):
    values_yaml = tmp_path / "values.yaml"
    init_git_repo(tmp_path)
    values_yaml.write_text('zac:\n  image:\n    tag: "5.0.2@sha256:aaaa"\n', encoding="utf-8")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    assert ucv.load_baseline_values("4.8.5") == {"zac": {"image": {"tag": "5.0.2@sha256:aaaa"}}}


def test_load_baseline_values_none_when_baseline_tag_missing(ucv, tmp_path, monkeypatch):
    values_yaml = tmp_path / "values.yaml"
    init_git_repo(tmp_path)
    values_yaml.write_text("zac: {}\n", encoding="utf-8")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "only commit, no baseline tag", cwd=tmp_path)

    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    assert ucv.load_baseline_values("9.9.9") is None


def test_load_baseline_values_none_outside_git_repo(ucv, tmp_path, monkeypatch):
    values_yaml = tmp_path / "values.yaml"
    values_yaml.write_text("zac: {}\n", encoding="utf-8")
    monkeypatch.setattr(ucv, "VALUES_YAML", values_yaml)
    assert ucv.load_baseline_values("4.8.5") is None
