"""lib.release_baseline.resolve_baseline_chart_state — against a real,
hermetic temp git repo (same convention as tests/lib/test_gitutil.py)."""
import subprocess

import pytest
import yaml


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)

    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({
        "dependencies": [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}],
    }))
    (tmp_path / "values.yaml").write_text(
        'zac:\n  image:\n    tag: "5.0.2@sha256:aaaa"\n')
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({
        "dependencies": [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.257"}],
    }))
    (tmp_path / "values.yaml").write_text(
        'zac:\n  image:\n    tag: "5.1.0@sha256:bbbb"\n')
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zac", cwd=tmp_path)
    return tmp_path


def test_resolve_baseline_chart_state_resolves_real_baseline(librelease_baseline, repo):
    ref, deps, values, lines, error = librelease_baseline.resolve_baseline_chart_state(repo, "4.8.5")
    assert error is None
    assert ref == "podiumd-4.8.5"
    assert deps == [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.251"}]
    assert values == {"zac": {"image": {"tag": "5.0.2@sha256:aaaa"}}}
    assert lines == ['zac:', '  image:', '    tag: "5.0.2@sha256:aaaa"']


def test_resolve_baseline_chart_state_lines_match_current_values_yaml_convention(librelease_baseline, repo):
    """No keepends, no trailing empty entry — the exact same
    VALUES_YAML.read_text().splitlines() shape verify-release-table-
    with-podiumd already uses for the CURRENT side, so lib.image_version's
    raw-line scanners resolve both sides identically."""
    _ref, _deps, _values, lines, _error = librelease_baseline.resolve_baseline_chart_state(repo, "4.8.5")
    text = (repo / "values.yaml").read_text(encoding="utf-8")
    # Read the file back at that same ref via git show, to prove `lines`
    # matches splitlines() of the ref's OWN content, not just today's.
    shown = subprocess.run(["git", "-C", str(repo), "show", "podiumd-4.8.5:values.yaml"],
                            capture_output=True, text=True, check=True).stdout
    assert lines == shown.splitlines()
    assert text != shown  # sanity: current values.yaml really did move on


def test_resolve_baseline_chart_state_error_when_ref_unresolvable(librelease_baseline, repo):
    ref, deps, values, lines, error = librelease_baseline.resolve_baseline_chart_state(repo, "9.9.9")
    assert ref is None
    assert deps == []
    assert values == {}
    assert lines == []
    assert "could not resolve baseline '9.9.9' to a git ref" in error


def test_resolve_baseline_chart_state_error_outside_git_repo(librelease_baseline, tmp_path):
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    ref, deps, values, lines, error = librelease_baseline.resolve_baseline_chart_state(outside, "4.8.5")
    assert ref is None
    assert deps == []
    assert values == {}
    assert lines == []
    assert "is not inside a git repository" in error


def test_resolve_baseline_chart_state_error_when_chart_yaml_unreadable_at_ref(librelease_baseline, tmp_path):
    """A real, resolvable ref whose Chart.yaml still can't be read (here:
    the chart didn't exist at that path yet) — baseline_ref must come
    back None too, not the resolved ref, matching lib.docs_consistency's
    own pre-existing convention (a resolved-but-unusable ref is still an
    overall failure)."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    (tmp_path / "README.md").write_text("nothing chart-shaped here yet\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "no chart yet", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    ref, deps, values, lines, error = librelease_baseline.resolve_baseline_chart_state(tmp_path, "4.8.5")
    assert ref is None
    assert deps == []
    assert values == {}
    assert lines == []
    assert "could not read Chart.yaml at that ref" in error


def test_resolve_baseline_chart_state_empty_dependencies_is_not_a_failure(librelease_baseline, tmp_path):
    """A chart with zero Chart.yaml dependencies at the baseline ref is a
    real, valid state — never itself treated as an error."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"apiVersion": "v2", "name": "podiumd"}))
    (tmp_path / "values.yaml").write_text("{}\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "no deps yet", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    ref, deps, values, lines, error = librelease_baseline.resolve_baseline_chart_state(tmp_path, "4.8.5")
    assert error is None
    assert ref == "podiumd-4.8.5"
    assert deps == []
    assert values == {}
