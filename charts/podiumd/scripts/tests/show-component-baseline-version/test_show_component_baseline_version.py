"""baseline_ref_candidates, find_dependency, get_path, find_app_versions —
pure logic, no git/network needed — plus resolve_git_ref/git_show_yaml and
a full main() integration test against a real, hermetic temp git repo."""
import subprocess

import pytest
import yaml


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


# --- baseline_ref_candidates ---

def test_baseline_ref_candidates_bare_version(scbv):
    assert scbv.baseline_ref_candidates("4.8.5") == [
        "podiumd-4.8.5", "origin/feature/podiumd-4.8.5", "feature/podiumd-4.8.5"
    ]


def test_baseline_ref_candidates_explicit_ref(scbv):
    assert scbv.baseline_ref_candidates("origin/some-branch") == ["origin/some-branch"]
    assert scbv.baseline_ref_candidates("abc1234") == ["abc1234"]


# --- find_dependency ---

def test_find_dependency_by_name(scbv):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac"}]
    assert scbv.find_dependency(deps, "zaakafhandelcomponent")["alias"] == "zac"


def test_find_dependency_by_alias(scbv):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac"}]
    assert scbv.find_dependency(deps, "zac")["name"] == "zaakafhandelcomponent"


def test_find_dependency_not_found_returns_none(scbv):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac"}]
    assert scbv.find_dependency(deps, "totally-unknown") is None


# --- get_path ---

def test_get_path_nested(scbv):
    assert scbv.get_path({"a": {"b": {"c": 1}}}, "a.b.c") == 1


def test_get_path_missing_returns_none(scbv):
    assert scbv.get_path({"a": {}}, "a.b.c") is None


def test_get_path_non_dict_intermediate_returns_none(scbv):
    assert scbv.get_path({"a": "scalar"}, "a.b") is None


# --- find_app_versions ---

def test_find_app_versions_single_image(scbv):
    values = {"zac": {"image": {"tag": "5.0.2@sha256:abc"}}}
    assert scbv.find_app_versions(values, "zac", ["image"]) == [("image", "5.0.2@sha256:abc")]


def test_find_app_versions_multi_image(scbv):
    values = {"zgw-office-addin": {
        "frontend": {"image": {"tag": "v0.9.313@sha256:a"}},
        "backend": {"image": {"tag": "v0.9.313@sha256:b"}},
    }}
    result = scbv.find_app_versions(values, "zgw-office-addin", ["frontend.image", "backend.image"])
    assert result == [("frontend.image", "v0.9.313@sha256:a"), ("backend.image", "v0.9.313@sha256:b")]


def test_find_app_versions_missing_key_returns_empty(scbv):
    assert scbv.find_app_versions({}, "zac", ["image"]) == []


def test_find_app_versions_empty_tag_is_skipped(scbv):
    values = {"zac": {"image": {"tag": ""}}}
    assert scbv.find_app_versions(values, "zac", ["image"]) == []


# --- git-backed helpers, against a real hermetic temp repo ---

@pytest.fixture
def repo(tmp_path):
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    chart_dir = tmp_path / "charts" / "podiumd"
    chart_dir.mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({
        "dependencies": [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
        ]
    }))
    (chart_dir / "values.yaml").write_text(yaml.safe_dump({
        "zac": {"image": {"tag": "5.0.2@sha256:abc"}}
    }))
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    (chart_dir / "values.yaml").write_text(yaml.safe_dump({
        "zac": {"image": {"tag": "5.4.3@sha256:def"}}
    }))
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zac", cwd=tmp_path)
    return tmp_path


def test_resolve_git_ref_finds_tag(scbv, repo):
    assert scbv.resolve_git_ref(repo, ["nonexistent", "podiumd-4.8.5"]) == "podiumd-4.8.5"


def test_resolve_git_ref_returns_none_when_nothing_resolves(scbv, repo):
    assert scbv.resolve_git_ref(repo, ["nope-1", "nope-2"]) is None


def test_git_show_yaml_reads_historical_content(scbv, repo):
    data = scbv.git_show_yaml(repo, "podiumd-4.8.5", "charts/podiumd/values.yaml")
    assert data["zac"]["image"]["tag"] == "5.0.2@sha256:abc"
    data_head = scbv.git_show_yaml(repo, "HEAD", "charts/podiumd/values.yaml")
    assert data_head["zac"]["image"]["tag"] == "5.4.3@sha256:def"


def test_git_show_yaml_returns_none_for_missing_file(scbv, repo):
    assert scbv.git_show_yaml(repo, "HEAD", "does-not-exist.yaml") is None


def test_find_repo_root_returns_repo_root(scbv, repo, monkeypatch):
    monkeypatch.setattr(scbv, "__file__", str(repo / "charts" / "podiumd" / "scripts" / "fake.py"))
    (repo / "charts" / "podiumd" / "scripts").mkdir(exist_ok=True)
    assert scbv.find_repo_root().resolve() == repo.resolve()


# --- main() integration ---
# main() only calls sys.exit() on error paths; on success it just returns,
# so only the failure-path tests wrap the call in pytest.raises(SystemExit).

def set_argv_and_repo(scbv, monkeypatch, repo, argv):
    monkeypatch.setattr("sys.argv", ["show-component-baseline-version.py", *argv])
    monkeypatch.setattr(scbv, "find_repo_root", lambda: repo)


def test_main_shows_chart_and_app_version_at_baseline(scbv, repo, monkeypatch, capsys):
    set_argv_and_repo(scbv, monkeypatch, repo, ["zac", "4.8.5"])
    scbv.main()  # success path: must not raise
    out = capsys.readouterr().out
    assert "Helm chart version: 1.0.297" in out
    assert "5.0.2" in out
    assert "5.4.3" not in out  # must read the BASELINE tag's content, not HEAD


def test_main_unresolvable_baseline_fails(scbv, repo, monkeypatch, capsys):
    set_argv_and_repo(scbv, monkeypatch, repo, ["zac", "9.9.9"])
    with pytest.raises(SystemExit) as exc_info:
        scbv.main()
    assert exc_info.value.code == 1
    assert "could not resolve baseline" in capsys.readouterr().out


def test_main_unknown_component_fails(scbv, repo, monkeypatch, capsys):
    set_argv_and_repo(scbv, monkeypatch, repo, ["totally-unknown", "4.8.5"])
    with pytest.raises(SystemExit) as exc_info:
        scbv.main()
    assert exc_info.value.code == 1
    assert "no dependency named or aliased" in capsys.readouterr().out


def test_main_requires_exactly_two_arguments(scbv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["show-component-baseline-version.py", "zac"])
    with pytest.raises(SystemExit) as exc_info:
        scbv.main()
    assert exc_info.value.code == 1
